"""Runs a section's checks, judges the result, words the record."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from relay.config import Config
from relay.queue import Section

TAIL_LINES = 40
TAIL_CHARS = 4000

Verdict = Literal["pass", "fail", "outside", "none"]


@dataclass(frozen=True)
class CheckResult:
    command: str | None
    exit_code: int | None
    timed_out: bool
    tail: str
    log: Path | None
    verdict: Verdict


def run_checks(cfg: Config, section: Section, cwd: Path, log: Path) -> CheckResult:
    raise NotImplementedError


def classify(
    cfg: Config, exit_code: int | None, timed_out: bool, tail: str
) -> Literal["fail", "outside"]:
    raise NotImplementedError


def owner_text(result: CheckResult, failures: int) -> str:
    raise NotImplementedError
