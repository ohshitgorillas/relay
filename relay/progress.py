"""One home for `relay go` progress lines."""

from pathlib import Path
from typing import Literal

from relay.config import Config
from relay.runner import RunResult
from relay.status import LeadStatus


def started(queue: Path, cfg: Config) -> None:
    raise NotImplementedError


def lead_started(sid: str, resume: str | None, answered: bool) -> None:
    raise NotImplementedError


def lead_finished(sid: str, result: RunResult, status: LeadStatus | None) -> None:
    raise NotImplementedError


def retiring(sid: str, why: Literal["context", "budget"], tokens: int) -> None:
    raise NotImplementedError


def killing(sid: str, tokens: int) -> None:
    raise NotImplementedError


def recut_started(sid: str, reason: str) -> None:
    raise NotImplementedError


def recut_finished(sid: str, result: RunResult, changed: bool) -> None:
    raise NotImplementedError


def needs_answer(sid: str, question: str) -> None:
    raise NotImplementedError


def failed(sid: str, failures: int) -> None:
    raise NotImplementedError


def waiting(parked: list[str]) -> None:
    raise NotImplementedError


def ended(queue: Path, code: int, reason: str, detail: str) -> None:
    raise NotImplementedError
