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
Rung = Literal[1, 2, 3]


@dataclass(frozen=True)
class Climb:
    rung: Rung
    why: str  # rung 3: the question parked for the owner; rungs 1 and 2: the progress text


def climb(kind: Literal["RECUT", "DESIGN"], s: SectionState, design: Path | None) -> Climb:
    """RECUT on a section that is neither from_recut nor design_changed: rung 1.
    RECUT on a from_recut section, or DESIGN, when not design_changed and design is not None: rung 2.
    design_changed: rung 3, "the ladder ran out: section <sid> already had its design change".
    design None at rung 2: rung 3, "no design to amend: the queue names none"."""
    raise NotImplementedError


def split_reason(text: str) -> tuple[str, str | None]:
    """(problem, guess): the stripped text before the first GUESS and after it; (text.strip(), None)
    when GUESS is absent."""
    raise NotImplementedError


@dataclass(frozen=True)
class DesignReport:
    rejected: bool  # the first non-blank line is `REJECTED: STEERING`
    approved: bool  # the STATUS line's text starts `Status: approved`
    decisions: tuple[str, ...]  # each indented line under DECISIONS, as written
    unfiled: tuple[str, ...]  # each indented line under UNFILED, as written


def parse_report(result_text: str | None) -> DesignReport | None:
    """The architect's report: `REJECTED: STEERING` first gives rejected=True. Otherwise the
    last block from a line starting `BRIEF ` to the line `END DESIGN`. None when neither is found."""
    raise NotImplementedError


def decision_numbers(report: DesignReport) -> tuple[int, ...]:
    """The leading <n> of each decision line, in order."""
    raise NotImplementedError


def design_of(design_line: str | None, top: Path) -> Path | None:
    """The queue head's design path (queue.queue_design), resolved against `top` when relative;
    None when design_line is None."""
    raise NotImplementedError


def section_cap(cfg: Config, section: Section) -> float | None:
    """section.dollar_cap when set, else cfg.section_dollar_cap."""
    raise NotImplementedError


def cap_text(sid: str, spent: float, cap: float) -> str:
    """"section <sid> spent $<spent:.2f> of its $<cap:.2f> cap; raise `cap:` in the queue or
    --section-dollar-cap to go on"."""
    raise NotImplementedError


def decisions_text(sid: str, design: Path, report: DesignReport) -> str:
    """"the design change for <sid> in <design> needs a product choice:" then each decision
    and unfiled line verbatim, each with its recommendation and alternative."""
    raise NotImplementedError


def failed_text(sid: str, design: Path, what: str) -> str:
    """"the design change for <sid> in <design> did not land: <what>"."""
    raise NotImplementedError
