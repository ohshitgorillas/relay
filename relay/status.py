"""Parses the lead's final status line."""

from dataclasses import dataclass
from typing import Literal, get_args

Kind = Literal["DONE", "RECUT", "DESIGN", "WAITING", "NEEDS-OWNER", "RETIRED"]

# The one list of status words, and the name of the text each text-bearing word requires.
KINDS: tuple[Kind, ...] = get_args(Kind)
TEXT_NAMES: dict[Kind, str] = {
    "RECUT": "reason",
    "DESIGN": "problem",
    "WAITING": "section id",
    "NEEDS-OWNER": "question",
}


@dataclass(frozen=True)
class LeadStatus:
    kind: Kind
    text: str


def parse_status(result_text: str | None) -> LeadStatus | None:
    if not result_text:
        return None
    lines = [line.rstrip() for line in result_text.splitlines() if line.strip()]
    if not lines:
        return None
    last = lines[-1]
    for kind in KINDS:
        if kind in TEXT_NAMES:
            prefix = f"{kind}: "
            if last.startswith(prefix) and last[len(prefix) :].strip():
                return LeadStatus(kind=kind, text=last[len(prefix) :])
        elif last == kind:
            return LeadStatus(kind=kind, text="")
    return None
