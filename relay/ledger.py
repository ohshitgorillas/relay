"""The spend ledger."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from relay.config import Config


@dataclass(frozen=True)
class Spend:
    tokens: int
    dollars: float


class Ledger:
    def __init__(self, path: Path):
        raise NotImplementedError

    def append(
        self,
        kind: Literal["lead", "recut"],
        section: str,
        session: str | None,
        spend: Spend,
    ) -> None:
        raise NotImplementedError

    def total(self, since: float | None) -> Spend:
        raise NotImplementedError

    def over(
        self, cfg: Config, live: Spend, since: float | None
    ) -> Literal["tokens", "dollars"] | None:
        raise NotImplementedError
