"""Choose the rung, split the lead's reason, read the architect's report, word the owner's text.

Pure: no I/O, no state writes, no git.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from relay.config import Config
from relay.queue import Section
from relay.state import SectionState

GUESS = " | guess: "
SPECS = Path("docs/superpowers/specs")
Rung = Literal[1, 2, 3]


@dataclass(frozen=True)
class Climb:
    rung: Rung
    why: str  # rung 3: the question parked for the owner; rungs 1 and 2: the progress text


def climb(kind: Literal["RECUT", "DESIGN"], s: SectionState, design: Path | None, sid: str) -> Climb:
    """RECUT on a section that is not from_recut, or on a design_changed one: rung 1.
    Any other RECUT, or DESIGN, when design is not None: rung 2.
    design None at rung 2: rung 3, "no design to amend: the queue names none".
    A design change never sends a section to the owner (owner's ruling, 28 Oct); the budget bounds it."""
    if kind == "RECUT" and (s.design_changed or not s.from_recut):
        return Climb(1, "recut")
    if design is None:
        return Climb(3, "no design to amend: the queue names none")
    return Climb(2, "design change")


def split_reason(text: str) -> tuple[str, str | None]:
    """(problem, guess): the stripped text before the first GUESS and after it; (text.strip(), None)
    when GUESS is absent."""
    problem, sep, guess = text.partition(GUESS)
    return (problem.strip(), guess.strip()) if sep else (text.strip(), None)


@dataclass(frozen=True)
class DesignReport:
    rejected: bool  # the first non-blank line is `REJECTED: STEERING`
    approved: bool  # the STATUS line's text starts `Status: approved`
    decisions: tuple[str, ...]  # each indented line under DECISIONS, as written
    unfiled: tuple[str, ...]  # each indented line under UNFILED, as written


def parse_report(result_text: str | None) -> DesignReport | None:
    """The architect's report: `REJECTED: STEERING` first gives rejected=True. Otherwise the
    last block from a line starting `BRIEF ` to the line `END DESIGN`. None when neither is found."""
    if not result_text:
        return None
    lines = result_text.splitlines()
    first = next((x for x in lines if x.strip()), None)
    if first is not None and first.strip() == "REJECTED: STEERING":
        return DesignReport(True, False, (), ())
    end = None
    for n in range(len(lines) - 1, -1, -1):
        if lines[n].strip() == "END DESIGN":
            end = n
            break
    if end is None:
        return None
    start = next((n for n in range(end - 1, -1, -1) if lines[n].startswith("BRIEF ")), None)
    if start is None:
        return None
    approved = False
    decisions: list[str] = []
    unfiled: list[str] = []
    section: list[str] | None = None
    for line in lines[start + 1 : end]:
        if line.startswith("STATUS"):
            approved = line[len("STATUS") :].strip().startswith("Status: approved")
            section = None
        elif line.strip() == "DECISIONS":
            section = decisions
        elif line.strip() == "UNFILED":
            section = unfiled
        elif line[:1] in (" ", "\t") and line.strip():
            if section is not None:
                section.append(line.strip())
        elif line.strip():
            section = None
    return DesignReport(False, approved, tuple(decisions), tuple(unfiled))


SAID_LIMIT = 1500  # characters of an unparsed architect message quoted to the owner


def said(result_text: str | None) -> str:
    """The architect's final message for the owner: stripped, its last SAID_LIMIT characters
    after "…" when longer, "(nothing)" when empty."""
    text = (result_text or "").strip()
    if not text:
        return "(nothing)"
    return text if len(text) <= SAID_LIMIT else "…" + text[-SAID_LIMIT:]


def lead_branch(report: str | None) -> tuple[str, Path] | None:
    """(branch, worktree) from the last `BRANCH <branch> <worktree path>` line of a lead's
    report; None when there is none."""
    for line in reversed((report or "").splitlines()):
        parts = line.strip().split(" ", 2)
        if len(parts) == 3 and parts[0] == "BRANCH" and parts[1] and parts[2].strip():
            return parts[1], Path(parts[2].strip())
    return None


def decision_numbers(report: DesignReport) -> tuple[int, ...]:
    """The leading <n> of each decision line, in order."""
    return tuple(int(d.split("|", 1)[0].strip()) for d in report.decisions)


def design_of(design_line: str | None, top: Path) -> Path | None:
    """The queue head's design path (queue.queue_design), resolved against `top` when relative;
    None when design_line is None."""
    if design_line is None:
        return None
    return top / design_line


def section_cap(cfg: Config, section: Section) -> float | None:
    """section.dollar_cap when set, else cfg.section_dollar_cap."""
    return section.dollar_cap if section.dollar_cap is not None else cfg.section_dollar_cap


def cap_text(sid: str, spent: float, cap: float) -> str:
    """"section <sid> spent $<spent:.2f> of its $<cap:.2f> cap; raise `cap:` in the queue or
    --section-dollar-cap to go on"."""
    return (
        f"section {sid} spent ${spent:.2f} of its ${cap:.2f} cap; "
        "raise `cap:` in the queue or --section-dollar-cap to go on"
    )


def decisions_text(sid: str, design: Path, report: DesignReport) -> str:
    """"the design change for <sid> in <design> needs a product choice:" then each decision
    and unfiled line verbatim, each with its recommendation and alternative."""
    head = f"the design change for {sid} in {design} needs a product choice:"
    return "\n".join([head, *report.decisions, *report.unfiled])


def failed_text(sid: str, design: Path, what: str) -> str:
    """"the design change for <sid> in <design> did not land: <what>"."""
    return f"the design change for {sid} in {design} did not land: {what}"


def handback_text(what: str, said: str) -> str:
    """The guidance a lead gets when the architect filed no design change."""
    raise NotImplementedError
