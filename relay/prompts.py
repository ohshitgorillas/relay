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
) -> str:
    parts = [
        "You are a lead. Carry the queue section below through development until it is done.",
        f"Queue: {queue}\nSection: {section.id}",
        f"Section body:\n{section.body}",
    ]
    if resume is not None:
        parts.append(f"resume {resume}")
    if report is not None:
        parts.append(
            "The previous lead's final report (that session's last reply, so you need "
            f"not recall it):\n{report}"
        )
    if answer is not None:
        parts.append(f"The owner's answer to your earlier question:\n{answer}")
    if check_feedback is not None:
        parts.append(
            "Relay ran this section's check after your DONE and it failed. "
            "Fix the section and end with DONE again:\n" + check_feedback
        )
    if map_block is not None:
        parts.append(
            "Relay's researcher mapped this section's code. "
            "Put the block below verbatim in every brief you send for this section, the architect's included. "
            f'When an agent reports it needs more, run `relay ask {queue} {section.id} "<question>"` '
            "with a 600000 ms timeout or in the background, "
            "and pass on its answer; on a non-zero exit the agent reads for itself.\n\n" + map_block
        )
    parts.append(
        "Retire contract: on reaching a safe point, after a step's commit, check whether "
        f"the file {retire_flag} exists. If it exists, stop and end with RETIRED. "
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
) -> str:
    """Three lines: rulings, lead new, approve."""
    steps = ", ".join(section.steps) if section.steps else "steps unnamed"
    paths = ", ".join(str(path) for path in evidence)
    return (
        f"rulings {design}\n"
        f"lead new: Section {section.id} of the queue at {queue}, under this design's Order "
        f"{steps}, cannot go on: {problem} Evidence: {paths}.\n"
        f"approve: {approval}\n"
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
