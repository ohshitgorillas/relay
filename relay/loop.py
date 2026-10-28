"""The state machine for one `relay go`."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Literal

from relay import ping
from relay.config import Config
from relay.errors import ExitCode
from relay.ledger import Ledger, Spend
from relay.prompts import lead_prompt, recut_brief
from relay.queue import Section, blocked_by, parse_queue
from relay.runner import RunResult, run_agent
from relay.state import State
from relay.status import parse_status
from relay.stream import StreamState

_Stop = tuple[int, str, str]  # (exit code, reason, detail)


def _git_top(directory: Path) -> Path:
    """The nearest ancestor of `directory` holding a `.git`, or `directory` itself."""
    directory = directory.resolve()
    for candidate in (directory, *directory.parents):
        if (candidate / ".git").exists():
            return candidate
    return directory


def run(queue: Path, cfg: Config) -> int:
    state = State.open(queue, cfg)
    state.lock()
    try:
        code, reason, detail = _loop(queue, cfg, state)
    except Exception as exc:
        ping.stopped(cfg, queue, "crashed", f"{type(exc).__name__}: {exc}")
        raise
    ping.stopped(cfg, queue, reason, detail)
    return code


def _loop(queue: Path, cfg: Config, state: State) -> _Stop:
    since = time.time()
    ledger = Ledger(state.stop_file.parent / "ledger.jsonl")
    cwd = _git_top(queue.parent)
    state.run_dir.mkdir(parents=True, exist_ok=True)
    retire_flag = state.run_dir / "retire"

    while True:
        if state.stop_file.exists():
            return ExitCode.STOP_FILE, "by stop file", "the stop file exists"
        over = ledger.over(cfg, Spend(0, 0.0), since)
        if over is not None:
            return ExitCode.BUDGET, "over budget", f"the {over} budget is spent"

        sections = parse_queue(queue)
        parked = {s.id for s in sections if state.section(s.id).status == "parked"}
        blocked = blocked_by(sections, parked)
        runnable = [
            s
            for s in sections
            if s.open and state.section(s.id).status == "open" and s.id not in blocked
        ]
        if not runnable:
            if not parked:
                return ExitCode.QUEUE_EMPTY, "queue empty", "every section is done"
            time.sleep(cfg.poll_seconds)
            continue

        stop = _run_section(queue, cfg, state, ledger, since, cwd, retire_flag, sections, runnable[0])
        if stop is not None:
            return stop


def _run_section(
    queue: Path,
    cfg: Config,
    state: State,
    ledger: Ledger,
    since: float,
    cwd: Path,
    retire_flag: Path,
    sections: list[Section],
    section: Section,
) -> _Stop | None:
    sid = section.id
    current = state.section(sid)
    resume = current.last_session or state.last_session_any
    prompt = lead_prompt(queue, section, resume, state.take_answer(sid), retire_flag)
    on_event, budget_hit = _watcher(cfg, ledger, since)

    retire_flag.unlink(missing_ok=True)
    result = run_agent(cfg.lead_command, prompt, cwd, state.run_dir, on_event, retire_flag)
    session = result.stream.session_id
    ledger.append("lead", sid, session, result.stream.spend)
    if session is not None:
        state.set_last_session(sid, session)

    status = parse_status(result.stream.result_text)
    failed = result.killed or result.exit_code != 0 or status is None
    if failed:
        if _fail(state, sid):
            return _failed_twice(sid)
    elif status.kind == "DONE":
        state.mark_done(sid)
    elif status.kind == "RECUT":
        if _recut(queue, cfg, state, ledger, since, cwd, retire_flag, section, status.text, result):
            return _failed_twice(sid)
    elif status.kind == "NEEDS-OWNER":
        state.park(sid, status.text)
        ping.needs_owner(cfg, queue, sid, status.text)
    # RETIRED: nothing to record; the next pass runs a fresh lead on the same section.

    if budget_hit[0]:
        return ExitCode.BUDGET, "over budget", "a lead was retired when the budget ran out"
    return None


def _watcher(
    cfg: Config, ledger: Ledger, since: float
) -> tuple[Callable[[StreamState], Literal["go", "retire", "kill"]], list[bool]]:
    """The run_agent callback, and a one-slot flag set when a budget ran out mid-run."""
    hit = [False]

    def on_event(stream: StreamState) -> Literal["go", "retire", "kill"]:
        if stream.context_tokens >= cfg.hard_ceiling:
            return "kill"
        if ledger.over(cfg, stream.spend, since) is not None:
            hit[0] = True
            return "retire"
        if stream.context_tokens >= cfg.context_limit:
            return "retire"
        return "go"

    return on_event, hit


def _fail(state: State, sid: str) -> bool:
    """Record a failure of `sid`; True when it is the second."""
    return state.record_failure(sid) >= 2


def _failed_twice(sid: str) -> _Stop:
    return ExitCode.FAILED_TWICE, "failed twice", f"section {sid} failed twice"


def _recut(
    queue: Path,
    cfg: Config,
    state: State,
    ledger: Ledger,
    since: float,
    cwd: Path,
    retire_flag: Path,
    section: Section,
    reason: str,
    lead: RunResult,
) -> bool:
    """Run the divvyer's recut; True when it failed and that was the section's second failure."""
    brief = recut_brief(queue, section, reason, lead.log)
    before = parse_queue(queue)
    on_event, _hit = _watcher(cfg, ledger, since)
    result = run_agent(cfg.recut_command, brief, cwd, state.run_dir, on_event, retire_flag)
    ledger.append("recut", section.id, result.stream.session_id, result.stream.spend)
    if result.killed or result.exit_code != 0 or parse_queue(queue) == before:
        return _fail(state, section.id)
    return False
