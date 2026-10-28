"""Runs a section's checks, judges the result, words the record."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import re

from relay.config import Config
from relay.queue import Section
from relay.runner import run_command

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
    timeout: float | None = None  # seconds the command was allowed; required when timed_out

    def __post_init__(self) -> None:
        if self.timed_out and self.timeout is None:
            raise ValueError("a timed-out CheckResult records the limit it timed out at")


def _tail(text: str) -> str:
    kept = "\n".join(text.splitlines()[-TAIL_LINES:])
    if text.endswith("\n") and kept:
        kept += "\n"
    return kept[-TAIL_CHARS:]


def _read_from(log: Path, offset: int) -> str:
    with log.open("rb") as handle:
        handle.seek(offset)
        return handle.read().decode("utf-8", errors="replace")


def run_checks(cfg: Config, section: Section, cwd: Path, log: Path) -> CheckResult:
    """Run each check in order, stop at the first non-zero exit, judge it."""
    if not section.checks:
        return CheckResult(None, None, False, "", None, "none")
    for command in section.checks:
        offset = log.stat().st_size if log.exists() else 0
        outcome = run_command(command, cwd, log, cfg.check_timeout)
        if outcome.exit_code == 0 and not outcome.timed_out:
            continue
        tail = _tail(_read_from(log, offset))
        verdict = classify(cfg, outcome.exit_code, outcome.timed_out, tail)
        limit = cfg.check_timeout if outcome.timed_out else None
        return CheckResult(command, outcome.exit_code, outcome.timed_out, tail, log, verdict, limit)
    return CheckResult(section.checks[-1], 0, False, "", log, "pass")


def classify(
    cfg: Config, exit_code: int | None, timed_out: bool, tail: str
) -> Literal["fail", "outside"]:
    """"outside" for exit 126/127 or a check_outside pattern in the tail, else "fail"."""
    if exit_code in (126, 127):
        return "outside"
    if any(re.search(pattern, tail) for pattern in cfg.check_outside):
        return "outside"
    return "fail"


def outcome_text(result: CheckResult) -> str:
    """The one wording of how a check ended: "timed out after <s>s" or "exit <n>"."""
    if result.timed_out:
        return f"timed out after {result.timeout:g}s"
    return f"exit {result.exit_code}"


def owner_text(result: CheckResult, failures: int) -> str:
    """The question parked for the owner: command, outcome, count, log, tail."""
    parts = [f"Check failed: {result.command}", outcome_text(result)]
    if result.verdict == "fail":
        parts.append(f"failed check {failures}")
    parts.append(f"log: {result.log}")
    parts.append(result.tail.rstrip("\n"))
    return "\n".join(parts)
