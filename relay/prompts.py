"""Builds every text Relay sends to an agent."""

import re
from pathlib import Path

from relay import git
from relay.config import Config
from relay.ladder import GUESS
from relay.check import CheckResult, outcome_text
from relay.queue import Section
from relay.research import ANSWER_CLOSE, ANSWER_OPEN, LINKS, MAP_CLOSE, MAP_OPEN, Map, block
from relay.runner import RunResult, error_line
from relay.status import KINDS, LeadStatus, Kind, TEXT_NAMES


WORKER_RULE = (
    "Worker reply rule: when a worker replies OVERLOADED, or stops heavy with work left, "
    "end this session with RECUT: <that worker's report>, and never cut or resend the step yourself. "
    "When a worker replies REJECTED: STEERING, resend the same brief once, "
    "with the quoted lines struck and nothing added; no assayer runs on a rejection. "
    "A second rejection of the same step ends this session with RECUT: <both rejections>."
)


def _status_form(kind: Kind) -> str:
    return f"{kind}: <{TEXT_NAMES[kind]}>" if kind in TEXT_NAMES else kind


def handoff(result: RunResult, status: LeadStatus | None) -> str | None:
    """With a status: "The previous lead's final report (that session's last reply, so you need
    not recall it):\n<result_text>", or None when result_text is empty. With no status:
    "The previous lead stopped without a final report (<error_line(result)>). Its last reply:
    <result_text or 'none'>\nIts agents, as Relay saw them: <one line per agents.Agent:
    name, description, status or 'running when it stopped'>.\""""
    text = result.stream.result_text or ""
    if status is not None:
        if not text:
            return None
        return (
            "The previous lead's final report (that session's last reply, so you need "
            f"not recall it):\n{text}"
        )
    lines = "\n".join(
        f"{a.name}, {a.description}, {a.status or 'running when it stopped'}"
        for a in result.stream.activity.agents
    )
    return (
        f"The previous lead stopped without a final report ({error_line(result)}). "
        f"Its last reply: {text or 'none'}\nIts agents, as Relay saw them:\n{lines}"
    )


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
    worktree: git.SectionWorktree | None = None,
) -> str:
    parts = [
        "You are a lead. Carry the queue section below through development until it is done.",
        f"Queue: {queue}\nSection: {section.id}",
        f"Section body:\n{section.body}",
    ]
    if worktree is not None:
        parts.append(
            f"Worktree assignment: use exactly branch {worktree.branch} at {worktree.path}. "
            "Create the worktree there if absent, and perform this section's work there. "
            "This assignment takes precedence over generic naming in the section body or "
            "a recalled session. Include this line in your final report:\n"
            f"BRANCH {worktree.branch} {worktree.path}"
        )
    if handoff_hint is not None:
        parts.append(handoff_hint)
    elif resume is not None:
        parts.append(f"resume {resume}")
    if report is not None:
        parts.append(report)
    if answer is not None:
        parts.append(f"The owner's answer to your earlier question:\n{answer}")
    if guidance is not None:
        parts.append(guidance)
    if check_feedback is not None:
        parts.append(
            "Relay ran this section's check after your DONE and it failed. "
            "Fix the section and end with DONE again:\n" + check_feedback
        )
    if map_block is not None:
        ask_command = "relay ask" if backend == "claude" else f"relay ask --backend {backend}"
        parts.append(
            "Relay's researcher mapped this section's code. "
            "Put the block below verbatim in every brief you send for this section except an architect's; "
            "an architect brief carries only its ruling lines. "
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
    parts.append(WORKER_RULE)
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
    queue: Path,
    section: Section,
    reason: str,
    lead_log: Path,
    design: Path | None = None,
) -> str:
    return (
        f"recut section {section.id} of the queue at {queue}.\n\n"
        f"A lead asked for this recut. Its reason: {reason}\n"
        f"The lead's run log: {lead_log}\n\n"
        f"Section body:\n{section.body}\n"
        + (
            f"\nThe design {design} was amended for this problem; its Order steps changed.\n"
            if design is not None
            else ""
        )
    )


def _ruling(marker: str, words: str) -> str:
    """`<marker> <words>` on one line: each run of whitespace in words becomes one space."""
    return f"{marker} {' '.join(words.split())}"


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
    """rulings, one `lead new:` line (the section, its steps, the problem, the evidence, where the
    lead's code is, the section's text), one `new:` per owner answer, approve; every line but the
    first built by _ruling."""
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
    lines = [
        f"rulings {design}",
        _ruling(
            "lead new:",
            f"Section {section.id} of the queue at {queue}, under this design's Order "
            f"{steps}, cannot go on: {problem} Evidence: {paths}.{where} "
            f"Section text: {section.body}",
        ),
        *(_ruling("new:", answer) for answer in answers),
        _ruling("approve:", approval),
    ]
    return "\n".join(lines) + "\n"


def design_retry_brief(brief: str, said: str, error: str | None) -> str:
    """`brief` with one `lead new:` line before its `approve:` line saying why the previous run
    filed no design change."""
    why = (
        f"it failed: {error}"
        if error is not None
        else "its final message had no BRIEF … END DESIGN block"
    )
    reason = _ruling(
        "lead new:",
        f"The previous run on this brief filed no design change: {why}. Its final message: {said} "
        "Make the design change, or file a report saying why none is needed.",
    )
    lines = brief.splitlines()
    at = max(
        (i for i, line in enumerate(lines) if line.startswith("approve: ")),
        default=len(lines),
    )
    return "\n".join([*lines[:at], reason, *lines[at:]]) + "\n"


def design_answer_brief(design: Path, numbers: tuple[int, ...], answer: str, approval: str) -> str:
    """The rulings line, the answer lines, the approve line."""
    kept = [
        line
        for line in answer.splitlines()
        if (m := re.match(r"(\d+):", line)) and int(m.group(1)) in numbers
    ]
    if not kept:
        marker = f"{numbers[0]}:" if len(numbers) == 1 else "new:"
        kept = [_ruling(marker, answer)]
    return "\n".join([f"rulings {design}", *kept, _ruling("approve:", approval)]) + "\n"


def check_feedback(result: CheckResult) -> str:
    return (
        f"{result.command}\n{outcome_text(result)}\n{result.log}\n{result.tail.rstrip(chr(10))}\n"
    )


ENTRY_RULE = (
    "Each entry names what lies at its lines (a symbol, table, section or call) in nouns. "
    "An entry never says what the code proves, lacks, allows, or justifies, and never tells "
    "a reader what to open, skip or search.\n"
)

READ_RULE = (
    "Read the section's files yourself, and send a reader only for a file too large to read "
    "whole within the map caps.\n"
)


def _map_form(flag: Path, max_lines: int, max_chars: int, *, additions: bool = False) -> str:
    """The shared final-map form, caps and researcher flag rule."""
    allowance = (
        f"adding at most {max_lines} lines and {max_chars} characters to the kept map"
        if additions
        else f"at most {max_lines} lines and {max_chars} characters"
    )
    return (
        "End your final message with the map, "
        f"{allowance}, in this form "
        f"and nothing after {MAP_CLOSE}:\n"
        f"{MAP_OPEN}\n"
        "<path>:<line>[-<line>] | <what it does>\n"
        f"{LINKS}\n"
        "<path>:<line> -> <path>:<line> | <how>\n"
        f"{MAP_CLOSE}\n\n"
        f"{ENTRY_RULE}"
        f"When the file {flag} exists, send no more readers and return the map you have.\n"
    )


def research_brief(queue: Path, section: Section, flag: Path, cfg: Config) -> str:
    """The researcher's brief: queue, section, caps, MAP form and the flag rule."""
    return (
        f"research section {section.id} of the queue at {queue}.\n\n"
        f"Section body:\n{section.body}\n"
        "Map the code this section's steps touch. "
        + READ_RULE
        + _map_form(flag, cfg.map_max_lines, cfg.map_max_chars)
    )


def refresh_brief(
    queue: Path, section: Section, kept: Map, changed: tuple[str, ...], flag: Path, cfg: Config
) -> str:
    """Map changed paths within the caps left after kept; preserve the kept entries."""
    paths = "\n".join(sorted(changed))
    return (
        f"refresh research section {section.id} of the queue at {queue}.\n\n"
        f"Section body:\n{section.body}\n\n"
        f"Kept map:\n{block(kept)}\n"
        f"Changed paths:\n{paths}\n\n"
        "Map only code in the changed paths that this section touches. "
        "You may name new paths. "
        "No entry may name a file that a kept entry names. "
        "The following caps count only the increase in the merged map over the kept map. "
        "Repeated MAP and END MAP framing, and a LINKS marker already in the kept map, "
        "do not consume this allowance. "
        + READ_RULE
        + _map_form(
            flag,
            cfg.map_max_lines - len(kept.body.splitlines()),
            cfg.map_max_chars - len(kept.body),
            additions=True,
        )
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
