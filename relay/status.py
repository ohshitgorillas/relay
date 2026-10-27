"""Parses the lead's final status line."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LeadStatus:
    kind: Literal["DONE", "RECUT", "NEEDS-OWNER", "RETIRED"]
    text: str


def parse_status(result_text: str | None) -> LeadStatus | None:
    raise NotImplementedError
