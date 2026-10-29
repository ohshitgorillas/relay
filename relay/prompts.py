"""Builds every text Relay sends to an agent."""

import re
from pathlib import Path

from relay.config import Config
from relay.ladder import GUESS
from relay.check import CheckResult, outcome_text
from relay.queue import Section
from relay.research import ANSWER_CLOSE, ANSWER_OPEN, LINKS, MAP_CLOSE, MAP_OPEN
from relay.status import KINDS, Kind, TEXT_NAMES


def _status_form(kind: Kind) -> str:
    return f"{kind}: <{TEXT_NAMES[kind]}>" if kind in TEXT_NAMES else kind


def lead_prompt(
    queue: Path,
    section: Section,
    resume: str | None,
    report: str | None,
    answer: str | None,
    retire_flag: Path,
    check_feedback: str | None = None,
    map_block: str | None = None,
    *,
    handoff_hint: str | None = None,
    backend: str = "claude",
    guidance: str | None = None,
) -> str:
    parts = [
        "You are a lead. Carry the queue section below through development until it is done.",
        f"Queue: {queue}\nSection: {section.id}",
        f"Section body:\n{section.body}",
    ]
    if handoff_hint is not None:
        parts.append(handoff_hint)
    elif resume is not None:
        parts.append(f"resume {resume}")
    if report is not None:
        parts.append(
            "The previous lead's final report (that session's last reply, so you need "
            f"not recall it):\n{report}"
        )
    if answer is not None:
        parts.append(f"The owner's answer to your earlier question:\n{answer}")
    if guidance is not None:
        parts.append(
            "Relay ran the architect twice on this section's last DESIGN or RECUT and it filed no "
            "design change. Its final message, as guidance: go on with the section, or end with "
            f"RECUT: if its cut is wrong:\n{guidance}"
        )
    if check_feedback is not None:
        parts.append(
            "Relay ran this section's check after your DONE and it failed. "
            "Fix the section and end with DONE again:\n" + check_feedback
        )
    if map_block is not None:
        ask_command = "relay ask" if backend == "claude" else f"relay ask --backend {backend}"
        parts.append(
            "Relay's researcher mapped this section's code. "
            "Put the block below verbatim in every brief you send for this section, the architect's included. "
            f'When an agent reports it needs more, run `{ask_command} {queue} {section.id} "<question>"` '
            "with a 600000 ms timeout or in the background, "
            "and pass on its answer; on a non-zero exit the agent reads for itself.\n\n" + map_block
        )
    parts.append(
        "Retire contract: before every dispatch and after every commit, whether it "
        f"succeeded or failed, check whether the file {retire_flag} exists. If it exists, "
        "dispatch nothing new, wait for agents already running, and end with RETIRED. "
        "A session grown heavy, past about 100k tokens of context, also stops at its "
        "next safe point and ends with RETIRED, never RECUT: Relay starts a fresh lead "
        "on the same section, which resumes from this session. RECUT is only for a "
        "section whose cut is wrong or too big."
    )
    parts.append(
        "Status rule: the text after RECUT: or DESIGN: is the problem: what fails, its evidence, "
        f"and the design step it is under. A fix you have in mind follows only after `{GUESS}`. "
        "DESIGN: is for when the section's design lacks something no recut can supply. "
        "WAITING: <id> is for when the section cannot go on until queue section <id> lands."
    )
    parts.append(
        "Status contract: the last line of your final message is exactly one of these, "
        "and nothing follows it:\n" + "\n".join(_status_form(kind) for kind in KINDS)
    )
    return "\n\n".join(parts) + "\n"


def recut_brief(
    queue: Path, section: Section, reason: str, lead_log: Path, design: Path | None = None
) -> str:
    return (
        f"recut section {section.id} of the queue at {queue}.\n\n"
        f"A lead asked for this recut. Its reason: {reason}\n"
        f"The lead's run log: {lead_log}\n\n"
        f"Section body:\n{section.body}\n"
        + (
            f"\nThe design {design} was amended for this problem. "
            "Cut this section's work again from it, its new Order steps included.\n"
            if design is not None
            else ""
        )
    )


def design_brief(
    design: Path,
    queue: Path,
    section: Section,
    problem: str,
    evidence: list[Path],
    approval: str,
    answers: list[str] | tuple[str, ...] = (),
    code: tuple[str, str | None] | None = None,
) -> str:
    """rulings, lead new (with where the lead's code is: its branch and commit in this repository,
    read through git, never a path outside it), one `new:` per owner answer verbatim, approve;
    then the section's text from the queue."""
    steps = ", ".join(section.steps) if section.steps else "steps unnamed"
    paths = ", ".join(str(path) for path in evidence)
    where = ""
    if code is not None:
        branch, commit = code
        at = f" at {commit}" if commit else ""
        ref = commit or branch
        where = (
            f" The lead's code is on branch {branch}{at} in this repository, not in this checkout; "
            f"read a file with `git show {ref}:<path>` and its changes with `git diff main...{ref}`."
        )
    owner = "".join(f"new: {answer}\n" for answer in answers)
    return (
        f"rulings {design}\n"
        f"lead new: Section {section.id} of the queue at {queue}, under this design's Order "
        f"{steps}, cannot go on: {problem} Evidence: {paths}.{where}\n"
        f"{owner}"
        f"approve: {approval}\n"
        f"\nSection {section.id} as the queue has it:\n{section.body.rstrip()}\n"
    )


def design_retry_brief(brief: str, said: str) -> str:
    """`brief`, then the previous architect run's final message and why it was no report."""
    return (
        f"{brief.rstrip()}\n\n"
        "Your previous run on this brief filed no report: its final message had no "
        "`BRIEF …` … `END DESIGN` block. Its final message:\n"
        f"{said}\n\n"
        "Either make the design change, or end with a BRIEF … END DESIGN block explaining why "
        "none is needed.\n"
    )


def design_answer_brief(design: Path, numbers: tuple[int, ...], answer: str, approval: str) -> str:
    """The rulings line, the answer lines, the approve line."""
    kept = [
        line
        for line in answer.splitlines()
        if (m := re.match(r"(\d+):", line)) and int(m.group(1)) in numbers
    ]
    if not kept:
        kept = [f"{numbers[0]}: {answer}" if len(numbers) == 1 else f"new: {answer}"]
    return "\n".join([f"rulings {design}", *kept, f"approve: {approval}"]) + "\n"


def check_feedback(result: CheckResult) -> str:
    return f"{result.command}\n{outcome_text(result)}\n{result.log}\n{result.tail.rstrip(chr(10))}\n"


def research_brief(queue: Path, section: Section, flag: Path, cfg: Config) -> str:
    """The researcher's brief: queue, section, caps, MAP form and the flag rule."""
    return (
        f"research section {section.id} of the queue at {queue}.\n\n"
        f"Section body:\n{section.body}\n"
        "Map the code this section's steps touch. End your final message with the map, "
        f"at most {cfg.map_max_lines} lines and {cfg.map_max_chars} characters, in this form "
        f"and nothing after {MAP_CLOSE}:\n"
        f"{MAP_OPEN}\n"
        "<path>:<line>[-<line>] | <what it does>\n"
        f"{LINKS}\n"
        "<path>:<line> -> <path>:<line> | <how>\n"
        f"{MAP_CLOSE}\n\n"
        f"When the file {flag} exists, send no more readers and return the map you have.\n"
    )


def ask_brief(question: str, flag: Path, cfg: Config) -> str:
    """The follow-up brief: question, ANSWER form, cap and the flag rule."""
    return (
        f"Answer this question about the code you mapped:\n{question}\n\n"
        f"End your final message with the answer, at most {cfg.map_max_chars} characters, "
        f"in this form and nothing after {ANSWER_CLOSE}:\n"
        f"{ANSWER_OPEN}\n"
        "<file:line pointers, one line each>\n"
        f"{ANSWER_CLOSE}\n\n"
        f"When the file {flag} exists, send no more readers and return the answer you have.\n"
    )
