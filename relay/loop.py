"""The state machine for one `relay go`."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Literal

from relay import backends, ping, progress
from relay.config import Config
from relay.errors import ExitCode
from relay.ledger import Ledger, Spend
from relay.prompts import lead_prompt, recut_brief
from relay.queue import Section, blocked_by, parse_queue
from relay.runner import RunResult, run_agent
from relay.state import FAILURE_LIMIT, State
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
    progress.started(queue, cfg)
    try:
        code, reason, detail = _loop(queue, cfg, state)
    except Exception as exc:
        ping.stopped(cfg, queue, "crashed", f"{type(exc).__name__}: {exc}")
        progress.ended(queue, ExitCode.ERROR, "crashed", f"{type(exc).__name__}: {exc}")
        raise
    ping.stopped(cfg, queue, reason, detail)
    progress.ended(queue, code, reason, detail)
    return code


def _loop(queue: Path, cfg: Config, state: State) -> _Stop:
    since = time.time()
    ledger = Ledger(state.ledger_path)
    cwd = _git_top(queue.parent)
    state.run_dir.mkdir(parents=True, exist_ok=True)
    retire_flag = state.retire_flag
    last_waiting: list[str] | None = None

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
            waiting = sorted(parked)
            if waiting != last_waiting:
                progress.waiting(waiting)
                last_waiting = waiting
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
    backend = backends.get_backend(cfg.backend)
    answer = state.take_answer(sid)
    prompt = lead_prompt(
        queue, section, resume, current.last_report, answer, retire_flag,
        handoff_hint=backend.resume_hint(resume) if resume is not None else None,
    )
    on_event, budget_hit = _watcher(cfg, ledger, since, "lead", sid)

    retire_flag.unlink(missing_ok=True)
    progress.lead_started(sid, resume, answer is not None)
    result = run_agent(cfg.lead_command, prompt, cwd, state.run_dir, on_event, retire_flag,
                       backend=backend, cfg=cfg, role="lead")
    session = result.stream.session_id
    ledger.append("lead", sid, session, result.stream.spend)
    if session is not None:
        state.set_last_session(sid, session)
        state.set_last_report(sid, result.stream.result_text or None)

    status = parse_status(result.stream.result_text)
    progress.lead_finished(sid, result, status)
    failed = result.killed or result.exit_code != 0 or status is None
    if failed:
        second, count = _fail(state, sid)
        progress.failed(sid, count)
        if second:
            return _failed_twice(sid)
    elif status.kind == "DONE":
        state.mark_done(sid)
    elif status.kind == "RECUT" and current.from_recut:
        # A section a recut made gets no second recut: the owner decides what happens to it.
        question = f"a section from a recut asked to recut again: {status.text}"
        state.park(sid, question)
        ping.needs_owner(cfg, queue, sid, question)
        progress.needs_answer(sid, question)
    elif status.kind == "RECUT":
        if _recut(queue, cfg, state, ledger, since, cwd, retire_flag, section, status.text, result):
            return _failed_twice(sid)
    elif status.kind == "NEEDS-OWNER":
        state.park(sid, status.text)
        ping.needs_owner(cfg, queue, sid, status.text)
        progress.needs_answer(sid, status.text)
    # RETIRED: nothing to record; the next pass runs a fresh lead on the same section.

    if budget_hit[0]:
        return ExitCode.BUDGET, "over budget", "a lead was retired when the budget ran out"
    return None


def _watcher(
    cfg: Config, ledger: Ledger, since: float, who: Literal["lead", "recut"], sid: str
) -> tuple[Callable[[StreamState], Literal["go", "retire", "kill"]], list[bool]]:
    """The run_agent callback, and a one-slot flag set when a budget ran out mid-run."""
    hit = [False]
    retiring = [False]
    shown = [0]  # agent events already printed
    capabilities = backends.get_backend(cfg.backend).capabilities

    def on_event(stream: StreamState) -> Literal["go", "retire", "kill"]:
        events = stream.activity.events
        for event in events[shown[0] :]:
            progress.agent_event(who, sid, event)
        shown[0] = len(events)
        if capabilities.context and stream.context_tokens >= cfg.hard_ceiling:
            progress.killing(sid, stream.context_tokens)
            return "kill"
        if ledger.over(cfg, stream.spend, since, capabilities=capabilities) is not None:
            hit[0] = True
            if not retiring[0]:
                retiring[0] = True
                progress.retiring(sid, "budget", stream.context_tokens)
            return "retire"
        if capabilities.context and stream.context_tokens >= cfg.context_limit:
            if not retiring[0]:
                retiring[0] = True
                progress.retiring(sid, "context", stream.context_tokens)
            return "retire"
        return "go"

    return on_event, hit


def _fail(state: State, sid: str) -> tuple[bool, int]:
    """Record a failure of `sid`; (True when it is the second, the count recorded)."""
    count = state.record_failure(sid)
    return count >= FAILURE_LIMIT, count


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
    on_event, _hit = _watcher(cfg, ledger, since, "recut", section.id)
    progress.recut_started(section.id, reason)
    result = run_agent(cfg.recut_command, brief, cwd, state.run_dir, on_event, retire_flag,
                       backend=backends.get_backend(cfg.backend), cfg=cfg, role="recut")
    ledger.append("recut", section.id, result.stream.session_id, result.stream.spend)
    changed = parse_queue(queue) != before
    progress.recut_finished(section.id, result, changed)
    if result.killed or result.exit_code != 0 or not changed:
        second, count = _fail(state, section.id)
        progress.failed(section.id, count)
        return second
    # A recut that keeps the section's id rewrote it in place; it is the recut's as much as a new id.
    known = {s.id for s in before}
    for made in parse_queue(queue):
        if made.id not in known or made.id == section.id:
            state.mark_from_recut(made.id)
    return False
