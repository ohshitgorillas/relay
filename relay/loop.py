"""The state machine for one `relay go`."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from relay import git, ping, progress
from relay.check import owner_text, run_checks
from relay.config import Config
from relay.errors import ExitCode
from relay.ledger import Kind, Ledger, Spend
from relay.prompts import check_feedback, lead_prompt, recut_brief
from relay.queue import Section, blocked_by, parse_queue
from relay.runner import RunResult, run_agent
from relay.state import CHECK_LIMIT, FAILURE_LIMIT, State
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
    if current.check_pending:
        _verify(cfg, queue, state, ledger, cwd, section, state.pending_check_log(sid))
        return None
    resume = current.last_session or state.last_session_any
    answer = state.take_answer(sid)
    feedback = state.take_check_feedback(sid)
    prompt = lead_prompt(queue, section, resume, answer, retire_flag, feedback)
    watch = _watcher(cfg, ledger, since, "lead", sid, cwd)

    retire_flag.unlink(missing_ok=True)
    progress.lead_started(sid, resume, answer is not None)
    result = run_agent(cfg.lead_command, prompt, cwd, state.run_dir, watch.on_event, retire_flag)
    session = result.stream.session_id
    ledger.append("lead", sid, session, result.stream.spend)
    state.set_last_log(sid, result.log)
    if session is not None:
        state.set_last_session(sid, session)

    status = parse_status(result.stream.result_text)
    progress.lead_finished(sid, result, status)
    failed = result.killed or result.exit_code != 0 or status is None
    if watch.idle_retired:
        pass  # handled as RETIRED: no failure recorded
    elif failed:
        second, count = _fail(state, sid)
        progress.failed(sid, count)
        if second:
            return _failed_twice(sid)
    elif status.kind == "DONE":
        _verify(cfg, queue, state, ledger, cwd, section, state.check_log(result.log))
    elif status.kind == "RECUT" and current.from_recut:
        # A section a recut made gets no second recut: the owner decides what happens to it.
        question = f"a section from a recut asked to recut again: {status.text}"
        _park(cfg, queue, state, sid, question)
    elif status.kind == "RECUT":
        if _recut(queue, cfg, state, ledger, since, cwd, retire_flag, section, status.text, result):
            return _failed_twice(sid)
    elif status.kind == "NEEDS-OWNER":
        _park(cfg, queue, state, sid, status.text)
    # RETIRED: nothing to record; the next pass runs a fresh lead on the same section.

    if watch.budget_hit:
        return ExitCode.BUDGET, "over budget", "a lead was retired when the budget ran out"
    return None


@dataclass
class _Watch:
    on_event: Callable[[StreamState], Literal["go", "retire", "kill"]]
    budget_hit: bool = False
    idle_retired: bool = False


def _watcher(
    cfg: Config, ledger: Ledger, since: float, who: Kind, sid: str, repo: Path
) -> _Watch:
    """The run_agent callback, with flags set when a budget ran out or an idle lead was killed."""
    retiring = [False]
    shown = [0]  # agent events already printed
    snapshot: list[dict[str, str]] = []  # branch heads when the retire flag first went up

    def on_event(stream: StreamState) -> Literal["go", "retire", "kill"]:
        events = stream.activity.events
        for event in events[shown[0] :]:
            progress.agent_event(who, sid, event)
        shown[0] = len(events)
        if stream.context_tokens >= cfg.hard_ceiling:
            progress.killing(sid, stream.context_tokens)
            return "kill"
        why: Literal["context", "budget"] | None = None
        if ledger.over(cfg, stream.spend, since) is not None:
            watch.budget_hit = True
            why = "budget"
        elif stream.context_tokens >= cfg.context_limit:
            why = "context"
        if why is None:
            return "go"
        if not retiring[0]:
            retiring[0] = True
            progress.retiring(sid, why, stream.context_tokens)
        if who == "lead":
            if not snapshot:
                snapshot.append(git.heads(repo))
            elif stream.context_tokens >= cfg.idle_ceiling and snapshot[0]:
                # `git.heads` is {} when git fails: an empty read proves no commit either way.
                now = git.heads(repo)
                if now and now == snapshot[0]:
                    watch.idle_retired = True
                    progress.retired_idle(sid, stream.context_tokens)
                    return "kill"
        return "retire"

    watch = _Watch(on_event=on_event)  # `on_event` reads `watch` when it runs, after this line
    return watch


def _park(cfg: Config, queue: Path, state: State, sid: str, question: str) -> None:
    """Park `sid` with `question`, ping the owner and show the question: the one park."""
    state.park(sid, question)
    ping.needs_owner(cfg, queue, sid, question)
    progress.needs_answer(sid, question)


def _verify(
    cfg: Config,
    queue: Path,
    state: State,
    ledger: Ledger,
    cwd: Path,
    section: Section,
    check_log: Path,
) -> None:
    """Run the section's checks and act on the verdict; a fail below the limit leaves it open."""
    sid = section.id
    where = git.section_worktree(cwd, sid) or cwd
    progress.check_started(sid, len(section.checks), where)
    result = run_checks(cfg, section, where, check_log)
    ledger.append_check(sid, result)
    progress.check_finished(sid, result)
    if result.verdict in ("pass", "none"):
        state.mark_done(sid)
    elif result.verdict == "fail":
        state.set_check_pending(sid, False)
        count = state.record_check_failure(sid, check_feedback(result))
        progress.check_failed(sid, count)
        if count >= CHECK_LIMIT:
            _park(cfg, queue, state, sid, owner_text(result, count))
    else:
        state.set_check_pending(sid, True)
        _park(cfg, queue, state, sid, owner_text(result, state.section(sid).check_failures))


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
    watch = _watcher(cfg, ledger, since, "recut", section.id, cwd)
    progress.recut_started(section.id, reason)
    result = run_agent(cfg.recut_command, brief, cwd, state.run_dir, watch.on_event, retire_flag)
    ledger.append("recut", section.id, result.stream.session_id, result.stream.spend)
    after = parse_queue(queue)
    changed = after != before
    progress.recut_finished(section.id, result, changed)
    known = {s.id for s in before}
    nested = any(s.id not in known and s.id.startswith(f"{section.id}.") for s in after)
    # A recut that keeps the section's id rewrote it in place; it is the recut's as much as a new id.
    # Whatever the recut wrote stays on disk, even when it failed or was rejected: mark it all.
    if changed:
        for made in after:
            if made.id not in known or made.id == section.id:
                state.mark_from_recut(made.id)
    if result.killed or result.exit_code != 0 or not changed or nested:
        second, count = _fail(state, section.id)
        progress.failed(section.id, count)
        return second
    return False
