"""Relay's own record for one queue."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from relay.config import Config

SectionStatus = Literal["open", "done", "parked"]


@dataclass
class SectionState:
    status: SectionStatus
    failures: int
    question: str | None
    answer: str | None
    last_session: str | None


class State:
    @classmethod
    def open(cls, queue: Path, cfg: Config) -> "State":
        raise NotImplementedError

    def lock(self) -> None:
        raise NotImplementedError

    def section(self, sid: str) -> SectionState:
        raise NotImplementedError

    def mark_done(self, sid: str) -> None:
        raise NotImplementedError

    def park(self, sid: str, question: str) -> None:
        raise NotImplementedError

    def set_answer(self, sid: str, answer: str) -> None:
        raise NotImplementedError

    def take_answer(self, sid: str) -> str | None:
        raise NotImplementedError

    def record_failure(self, sid: str) -> int:
        raise NotImplementedError

    def set_last_session(self, sid: str, session: str) -> None:
        raise NotImplementedError

    @property
    def last_session_any(self) -> str | None:
        raise NotImplementedError

    @property
    def stop_file(self) -> Path:
        raise NotImplementedError

    @property
    def run_dir(self) -> Path:
        raise NotImplementedError
