"""One home for `relay go` progress lines."""

import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from relay.agents import Event, duration
from relay.config import Config
from relay.runner import RunResult
from relay.state import CHECK_LIMIT, FAILURE_LIMIT
from relay.status import LeadStatus

if TYPE_CHECKING:
    from relay.check import CheckResult


def _write(text: str) -> None:
    try:
        sys.stdout.write(time.strftime("%H:%M:%S ") + text + "\n")
        sys.stdout.flush()
    except OSError:
        pass


def _cut(text: str) -> str:
    lines = text.splitlines()
    first = lines[0] if lines else ""
    if len(first) > 120:
        return first[:119] + "…"
    return first


def _spend(result: RunResult) -> str:
    spend = result.stream.spend
    return f"({spend.tokens} tokens, ${spend.dollars:.2f})"


def started(queue: Path, cfg: Config) -> None:
    tokens = (
        "no token budget" if cfg.token_budget is None else f"budget {cfg.token_budget} tokens"
    )
    dollars = "no dollar budget" if cfg.dollar_budget is None else f"${cfg.dollar_budget:.2f}"
    _write(f"relay go {queue.name}: started; {tokens}, {dollars}")


def lead_started(sid: str, resume: str | None, answered: bool) -> None:
    how = f"resuming {resume}" if resume else "fresh"
    tail = ", with the owner's answer" if answered else ""
    _write(f"lead {sid}: started{',' if resume else ''} {how}{tail}")


def lead_finished(sid: str, result: RunResult, status: LeadStatus | None) -> None:
    if result.killed:
        outcome = "killed"
    elif result.exit_code != 0:
        outcome = f"exit {result.exit_code}"
    elif status is None:
        outcome = "with no status line"
    elif status.kind == "RECUT":
        outcome = f"{status.kind}: {_cut(status.text)}"
    else:
        outcome = status.kind
    _write(f"lead {sid}: finished {outcome} {_spend(result)}")


def retiring(sid: str, why: Literal["context", "budget"], tokens: int) -> None:
    if why == "context":
        _write(f"lead {sid}: asked to retire at {tokens} context tokens")
    else:
        _write(f"lead {sid}: asked to retire, budget spent")


def killing(sid: str, tokens: int) -> None:
    _write(f"lead {sid}: killed at {tokens} context tokens, past the hard ceiling")


def recut_started(sid: str, reason: str) -> None:
    _write(f"recut {sid}: started: {_cut(reason)}")


def recut_finished(sid: str, result: RunResult, changed: bool) -> None:
    if result.killed:
        outcome = "killed"
    elif result.exit_code != 0:
        outcome = f"exit {result.exit_code}"
    elif not changed:
        outcome = "with the queue unchanged"
    else:
        outcome = "with the queue recut"
    _write(f"recut {sid}: finished {outcome} {_spend(result)}")


def agent_event(who: Literal["lead", "recut"], sid: str, event: Event) -> None:
    agent = event.agent
    if event.kind == "started":
        what = f"agent {agent.name} started"
    else:
        took = "time unknown" if agent.duration_ms is None else f"in {duration(agent.duration_ms)}"
        what = f"agent {agent.name} {agent.status or 'finished'} {took}, context {agent.context}"
    plural = "" if event.live == 1 else "s"
    _write(f"{who} {sid}: {what}: {_cut(agent.description)} ({who} + {event.live} agent{plural})")


def needs_answer(sid: str, question: str) -> None:
    _write(f"section {sid}: needs an answer: {_cut(question)}")


def failed(sid: str, failures: int) -> None:
    _write(f"section {sid}: failed ({failures} of {FAILURE_LIMIT})")


def waiting(parked: list[str]) -> None:
    _write("waiting for answers on " + ", ".join(parked))


def ended(queue: Path, code: int, reason: str, detail: str) -> None:
    _write(f"relay go {queue.name}: ended {reason}: {_cut(detail)} (exit {code})")


def check_started(sid: str, command_count: int, cwd: Path) -> None:
    noun = "check" if command_count == 1 else "checks"
    _write(f"check {sid}: running {command_count} {noun} in {cwd}")


def check_finished(sid: str, result: "CheckResult") -> None:
    if result.verdict == "pass":
        what = "passed"
    elif result.verdict == "none":
        what = "none to run"
    elif result.verdict == "outside":
        what = f"outside the code: exit {result.exit_code}"
    elif result.timed_out:
        what = "timed out"
    else:
        what = f"failed: exit {result.exit_code}"
    _write(f"check {sid}: {what}")


def check_failed(sid: str, failures: int) -> None:
    _write(f"section {sid}: check failed ({failures} of {CHECK_LIMIT})")


def retired_idle(sid: str, tokens: int) -> None:
    _write(f"lead {sid}: retired at {tokens} context tokens, no commit since the retire flag")
