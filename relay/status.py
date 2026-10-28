"""Parses the lead's final status line."""

import re
from dataclasses import dataclass
from typing import Literal

_STATUS_LINE = re.compile(r"^(?:(DONE|RETIRED)|(RECUT|NEEDS-OWNER): (\S.*))$")


@dataclass(frozen=True)
class LeadStatus:
    kind: Literal["DONE", "RECUT", "NEEDS-OWNER", "RETIRED"]
    text: str


def parse_status(result_text: str | None) -> LeadStatus | None:
    if not result_text:
        return None
    lines = [line.rstrip() for line in result_text.splitlines() if line.strip()]
    if not lines:
        return None
    match = _STATUS_LINE.match(lines[-1])
    if match is None:
        return None
    if match.group(1):
        return LeadStatus(kind=match.group(1), text="")  # type: ignore[arg-type]
    return LeadStatus(kind=match.group(2), text=match.group(3))  # type: ignore[arg-type]
