"""The state machine for one `relay go`."""

from __future__ import annotations

import os
import stat
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Literal, cast

from relay import backends, git, ladder, ping, progress, research
from relay.check import owner_text, run_checks
from relay.config import Config
from relay.errors import ExitCode, QueueFormatError, ResearchError
from relay.files import atomic_write
from relay.ledger import Kind, Ledger, Spend
from relay.prompts import (
    ask_brief,
    check_feedback,
    design_answer_brief,
    design_brief,
    design_retry_brief,
    handoff,
    lead_prompt,
    recut_brief,
    refresh_brief,
    research_brief,
)
from relay.queue import Section, blocked_by, parse_queue, queue_design, same_entry
from relay.runner import DrainSwitch, RunResult, drain_armed, error_line, run_agent, run_failed
from relay.state import CHECK_LIMIT, DESIGN_FAILURE_LIMIT, FAILURE_LIMIT, Pending, State
from relay.status import parse_status
from relay.stream import StreamState

_Stop = tuple[int, str, str]  # (exit code, reason, detail)


def _drained() -> _Stop:
    return ExitCode.DRAINED, "drained", "a drain was requested; running work finished and was recorded"


def _resume_pending(
    queue: Path,
    cfg: Config,
    state: State,
    ledger: Ledger,
    since: float,
    cwd: Path,
    retire_flag: Path,
    section: Section,
    pending: Pending,
    drain: DrainSwitch,
) -> _Stop | None:
    if drain.requested:
        state.set_pending(section.id, pending)
        return _drained()
    current = state.section(section.id)
    if _over_cap(cfg, queue, state, ledger, section):
        return None
    if current.design_failures >= DESIGN_FAILURE_LIMIT:
        return _design_failed_stop(section.id, current.design_failures, current.design_failure)
    lead_log = Path(pending.lead_log)
    if pending.kind == "climb":
        assert pending.status is not None and pending.text is not None
        return _climb(
            queue, cfg, state, ledger, since, cwd, retire_flag, section,
            pending.status, pending.text, lead_log, drain,
        )
    assert pending.design is not None
    design = Path(pending.design)
    if pending.kind == "design-retry":
        assert pending.brief is not None
        ran = _architect_run(
            cfg, state, ledger, since, retire_flag, section, design, pending.brief, pending.problem, drain
        )
        if ran is None:
            state.set_pending(section.id, pending)
            return _drained()
        result, report = ran
        return _design_outcome(
            queue, cfg, state, ledger, since, cwd, retire_flag, section, design,
            pending.problem, lead_log, result, report, drain,
        )
    failed = _recut(
        queue, cfg, state, ledger, since, cwd, retire_flag, section,
        pending.problem, lead_log, design, 2, drain=drain,
    )
    if isinstance(failed, tuple):
        state.set_pending(section.id, pending)
        return failed
    if failed:
        _park(cfg, queue, state, section.id, ladder.failed_text(section.id, design, failed))
    return None


def _git_top(directory: Path) -> Path:
    """The nearest ancestor of `directory` holding a `.git`, or `directory` itself."""
    directory = directory.resolve()
    for candidate in (directory, *directory.parents):
        if (candidate / ".git").exists():
            return candidate
    return directory


def run(queue: Path, cfg: Config) -> int:
    state = State.open(queue, cfg)

    def on_request() -> None:
        state.mark_draining()
        progress.draining()

    with drain_armed(on_request) as drain:
        state.lock()
        try:
            state.publish_run(os.getpid())
            progress.started(queue, cfg)
            try:
                code, reason, detail = _loop(queue, cfg, state, drain)
            except Exception as exc:
                ping.stopped(cfg, queue, "crashed", f"{type(exc).__name__}: {exc}")
                progress.ended(queue, ExitCode.ERROR, "crashed", f"{type(exc).__name__}: {exc}")
                raise
            ping.stopped(cfg, queue, reason, detail)
            progress.ended(queue, code, reason, detail)
            return code
        finally:
            state.clear_run()


def _loop(queue: Path, cfg: Config, state: State, drain: DrainSwitch) -> _Stop:
    since = time.time()
    ledger = Ledger(state.ledger_path)
    cwd = _git_top(queue.parent)
    state.run_dir.mkdir(parents=True, exist_ok=True)
    retire_flag = state.retire_flag
    last_waiting: list[str] | None = None

    while True:
        if drain.requested:
            return _drained()
        if state.stop_file.exists():
            return ExitCode.STOP_FILE, "by stop file", "the stop file exists"
        over = ledger.over(cfg, Spend(0, 0.0), since)
        if over is not None:
            return ExitCode.BUDGET, "over budget", f"the {over} budget is spent"

        sections = parse_queue(queue)
        _wake(sections, state, cwd, queue)
        parked = {s.id for s in sections if state.section(s.id).status == "parked"}
        waiting_ids = {s.id for s in sections if state.section(s.id).status == "waiting"}
        blocked = blocked_by(sections, parked | waiting_ids)
        runnable = [
            s
            for s in sections
            if s.open and state.section(s.id).status == "open" and s.id not in blocked
        ]
        if not runnable:
            if not parked and not waiting_ids:
                return ExitCode.QUEUE_EMPTY, "queue empty", "every section is done"
            waiting = sorted(parked | waiting_ids)
            if waiting != last_waiting:
                progress.waiting(waiting)
                last_waiting = waiting
            drain.pause(cfg.poll_seconds)
            continue

        stop = _run_section(queue, cfg, state, ledger, since, cwd, retire_flag, sections, runnable[0], drain)
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
    drain: DrainSwitch,
) -> _Stop | None:
    sid = section.id
    current = state.section(sid)
    if current.check_pending:
        _verify(cfg, queue, state, ledger, cwd, section, state.pending_check_log(sid))
        return None
    if _over_cap(cfg, queue, state, ledger, section):
        return None
    if current.design_failures >= DESIGN_FAILURE_LIMIT:
        return _design_failed_stop(sid, current.design_failures, current.design_failure)
    if drain.requested:
        return _drained()
    pending = state.take_pending(sid)
    if pending is not None:
        return _resume_pending(queue, cfg, state, ledger, since, cwd, retire_flag, section, pending, drain)
    if current.design_open is not None:
        answer = current.answer
        if answer is not None:
            return _design_answer(
                queue, cfg, state, ledger, since, cwd, retire_flag, section, current.design_open, answer, drain
            )
    m, spent = _research(cfg, state, ledger, since, cwd, queue, section, drain)
    if spent:
        return ExitCode.BUDGET, "over budget", "a researcher was retired when the budget ran out"
    if drain.requested:
        return _drained()
    resume = current.last_session or state.last_session_any
    previous_backend = current.last_backend if current.last_session else state.last_backend_any
    backend = backends.get_backend(previous_backend)
    current = state.section(sid)
    answer = current.answer
    feedback = current.check_feedback
    guidance = current.guidance
    prompt = lead_prompt(
        queue,
        section,
        resume,
        current.last_report,
        answer,
        retire_flag,
        feedback,
        research.block(m) if m is not None else None,
        handoff_hint=backend.resume_hint(resume) if resume is not None else None,
        backend=cfg.backend,
        guidance=guidance,
        worktree=_section_worktree(cwd, queue, sid, state)
        or git.SectionWorktree(git.section_branch(queue, sid), git.section_path(cwd, queue, sid)),
    )

    retire_flag.unlink(missing_ok=True)
    if drain.requested:
        return _drained()
    state.take_answer(sid)
    state.take_check_feedback(sid)
    state.take_guidance(sid)
    progress.lead_started(sid, resume, answer is not None)
    result, watch = _run(
        cfg,
        state,
        ledger,
        since,
        "lead",
        sid,
        cfg.lead_command,
        prompt,
        cwd,
        retire_flag,
        m.commit if m is not None else None,
        cap=ladder.section_cap(cfg, section),
    )
    session = result.stream.session_id
    state.set_last_log(sid, result.log)
    status = parse_status(result.stream.result_text)
    if session is not None:
        state.set_last_session(sid, session, cfg.backend)
        state.set_last_report(sid, handoff(result, status))

    _section_worktree(cwd, queue, sid, state)
    progress.lead_finished(sid, result, status)
    failed = run_failed(result, require_tokens=False) or status is None
    if watch.idle_retired and not result.stream.is_error:
        pass  # handled as RETIRED: no failure recorded
    elif failed:
        second, count = _fail(state, sid)
        progress.failed(sid, count)
        if second:
            return _failed_twice(sid)
    elif status.kind == "DONE":
        _verify(cfg, queue, state, ledger, cwd, section, state.check_log(result.log))
    elif status.kind in ("RECUT", "DESIGN"):
        if drain.requested:
            state.set_pending(sid, Pending(
                kind="climb", lead_log=str(result.log), problem=ladder.split_reason(status.text)[0],
                status=status.kind, text=status.text,
            ))
            if watch.budget_hit:
                return ExitCode.BUDGET, "over budget", "a lead was retired when the budget ran out"
            return _drained()
        stop = _climb(
            queue, cfg, state, ledger, since, cwd, retire_flag, section, status.kind, status.text, result.log, drain
        )
        if stop is not None:
            return stop
    elif status.kind == "WAITING":
        _wait(queue, cfg, state, sections, section, status.text)
    elif status.kind == "NEEDS-OWNER":
        _park(cfg, queue, state, sid, status.text)
    # RETIRED: nothing to record; the next pass runs a fresh lead on the same section.

    if watch.budget_hit:
        return ExitCode.BUDGET, "over budget", "a lead was retired when the budget ran out"
    return None


def _landed(blocker: str, sections: list[Section], state: State, cwd: Path, queue: Path) -> bool:
    """A blocker in the queue has landed when done and its section worktree is not dirty; one
    gone from the queue, when every section recut from it has landed (or none exists)."""
    found = next((s for s in sections if s.id == blocker), None)
    if found is None:
        return all(_landed(s.id, sections, state, cwd, queue) for s in sections if s.came_from == blocker)
    if state.section(blocker).status != "done" and found.open:
        return False
    tree = _section_worktree(cwd, queue, blocker, state)
    return tree is None or git.clean(tree.path) is not False


def _wake(sections: list[Section], state: State, cwd: Path, queue: Path) -> None:
    """Reopen each waiting section whose blocker has landed. No ping."""
    for s in sections:
        record = state.section(s.id)
        blocker = record.waits_on
        if record.status == "waiting" and blocker is not None and _landed(blocker, sections, state, cwd, queue):
            state.wake(s.id)
            progress.woken(s.id, blocker)


def _wait(
    queue: Path, cfg: Config, state: State, sections: list[Section], section: Section, blocker: str
) -> None:
    """WAITING: hold the section on its blocker with no ping, or park it when that cannot work."""
    sid = section.id
    by_id = {s.id: s for s in sections}
    known = blocker in by_id or any(s.came_from == blocker for s in sections)
    reason = None
    if not known:
        reason = f"it waits on {blocker}, which is not in the queue"
    elif blocker == sid:
        reason = "it waits on itself"
    elif _landed(blocker, sections, state, cwd=_git_top(queue.parent), queue=queue):
        reason = f"it waits on {blocker}, which has already landed"
    else:
        seen: set[str] = set()
        todo = [blocker]
        while todo and reason is None:
            cur = todo.pop()
            if cur in seen:
                continue
            seen.add(cur)
            if cur == sid:
                reason = f"it waits on {blocker}, which waits on it"
            elif cur in by_id:
                todo.extend(by_id[cur].depends_on)
                onward = state.section(cur).waits_on
                if onward is not None:
                    todo.append(onward)
            else:  # recut out of the queue: it lands through the sections cut from it
                todo.extend(s.id for s in sections if s.came_from == cur)
    if reason is not None:
        _park(cfg, queue, state, sid, f"Section {sid} cannot wait: {reason}.")
        return
    state.wait(sid, blocker)
    progress.section_waiting(sid, blocker)


def _section_worktree(
    cwd: Path, queue: Path, sid: str, state: State,
) -> git.SectionWorktree | None:
    """Resolve and persist this queue section's validated worktree."""
    current = state.section(sid)
    recorded = None
    if current.worktree_branch is not None and current.worktree_path is not None:
        recorded = git.SectionWorktree(current.worktree_branch, Path(current.worktree_path))
    else:
        report = ladder.lead_branch(current.last_report)
        if report is not None:
            recorded = git.SectionWorktree(*report)
    found = git.section_worktree(cwd, queue, sid, recorded)
    if found is None and recorded is not None:
        found = git.section_worktree(cwd, queue, sid)
    if found is not None and (
        current.worktree_branch != found.branch or current.worktree_path != str(found.path)
    ):
        state.bind_worktree(sid, found.branch, found.path)
    return found


def _section_cwd(
    cwd: Path, queue: Path, sid: str, state: State,
) -> Path:
    """Where a section's check and research run: its worktree, else `cwd`."""
    tree = _section_worktree(cwd, queue, sid, state)
    return tree.path if tree is not None else cwd


def _run(
    cfg: Config,
    state: State,
    ledger: Ledger,
    since: float | None,
    kind: Kind,
    sid: str,
    argv: list[str],
    text: str,
    cwd: Path,
    flag: Path,
    map_commit: str | None = None,
    rung: int | None = None,
    cap: float | None = None,
) -> tuple[RunResult, _Watch]:
    """The one agent run: watch it, run it, ledger it. Returns the result and its watch."""
    watch = _watcher(cfg, ledger, since, kind, sid, cwd, cap)
    backend = backends.get_backend(cfg.backend)
    invocation = replace(cfg, research_command=argv) if kind == "ask" else cfg
    result = run_agent(
        argv, text, cwd, state.run_dir, watch.on_event, flag,
        backend=backend, cfg=invocation, role=kind,
    )
    ledger.append(
        kind,
        sid,
        result.stream.session_id,
        result.stream.spend,
        map_commit,
        result.stream.activity.agents,
        rung,
    )
    return result, watch


def _research(
    cfg: Config,
    state: State,
    ledger: Ledger,
    since: float,
    cwd: Path,
    queue: Path,
    section: Section,
    drain: DrainSwitch,
) -> tuple[research.Map | None, bool]:
    """The section's map and whether the budget ran out in research; None on no map.

    Holds the section's research lock, so a `relay ask` never meets a map half-refreshed.
    """
    sid = section.id
    where = _section_cwd(cwd, queue, sid, state)
    with state.research_lock(sid):
        if drain.requested:
            return None, False
        since_ns = time.time_ns()
        saved = research.load(state.map_path(sid), sid)
        if saved is not None and not research.owned(saved, queue):
            state.drop_map(sid)
            saved = None
        changed = research.changed(saved, where) if saved is not None else frozenset()
        if saved is not None and not changed:
            progress.map_reused(sid, saved)
            return saved, False
        kept = research.split(saved, changed) if saved is not None else None
        commit = git.head(where)
        if commit is None:
            return None, False
        flag = state.research_flag(sid)
        flag.unlink(missing_ok=True)
        if kept is not None:
            progress.research_refreshing(sid, where, changed, kept)
            text = refresh_brief(queue, section, kept, tuple(sorted(changed)), flag, cfg)
        else:
            progress.research_started(sid, where)
            text = research_brief(queue, section, flag, cfg)
        if drain.requested:
            return None, False
        result, watch = _run(
            cfg,
            state,
            ledger,
            since,
            "research",
            sid,
            cfg.research_command,
            text,
            where,
            flag,
        )
        state.set_research_session(sid, result.stream.session_id, cfg.backend)
        failed = run_failed(result)
        m = None
        if not failed:
            if kept is not None:
                m = research.parse_refresh(kept, commit, changed, result.stream.result_text, cfg)
            else:
                m = research.parse_map(sid, commit, result.stream.result_text, cfg)
        if m is not None:
            m = research.attribute(research.stamp(m, where, since_ns), queue)
            research.save(m, state.map_path(sid))
        progress.research_finished(sid, result, m)
        if failed:
            ping.research_failed(cfg, queue, sid, error_line(result))
        return m, watch.budget_hit


def ask(queue: Path, cfg: Config, sid: str, question: str) -> str:
    """Put `question` to the section's researcher and return its answer; ResearchError without one."""
    state = State.open(queue, cfg)
    with state.research_lock(sid):
        saved = research.load(state.map_path(sid), sid)
        if saved is not None and not research.owned(saved, queue):
            state.drop_map(sid)
            raise ResearchError(f"section {sid} research must be refreshed before a follow-up")
        current = state.section(sid)
        session = current.research_session
        if session is None:
            raise ResearchError(f"section {sid} has no researcher to ask")
        if not backends.get_backend(cfg.backend).capabilities.resume:
            raise ResearchError(f"backend {cfg.backend} cannot resume a researcher")
        if current.research_backend != cfg.backend:
            raise ResearchError(
                f"section {sid} researcher used {current.research_backend}; selected backend is {cfg.backend}"
            )
        state.run_dir.mkdir(parents=True, exist_ok=True)
        cwd = _git_top(queue.parent)
        flag = state.research_flag(sid)
        flag.unlink(missing_ok=True)
        result, _ = _run(
            cfg,
            state,
            Ledger(state.ledger_path),
            None,
            "ask",
            sid,
            [*cfg.research_command, "--resume", session],
            ask_brief(question, flag, cfg),
            _section_cwd(cwd, queue, sid, state),
            flag,
        )
        if run_failed(result):
            raise ResearchError(f"the researcher for section {sid} failed: {error_line(result)}")
        answer = research.parse_answer(result.stream.result_text, cfg)
        if answer is None:
            raise ResearchError(f"the researcher for section {sid} gave no answer")
        return answer


@dataclass
class _Watch:
    on_event: Callable[[StreamState], Literal["go", "retire", "kill"]]
    budget_hit: bool = False
    idle_retired: bool = False


def _watcher(
    cfg: Config, ledger: Ledger, since: float | None, who: Kind, sid: str, repo: Path,
    cap: float | None = None,
) -> _Watch:
    """The run_agent callback: `budget_hit` on a spent budget, `idle_retired` for an idle lead."""
    retiring = [False]
    shown = [0]  # agent events already printed
    capabilities = backends.get_backend(cfg.backend).capabilities
    snapshot: list[dict[str, str]] = []  # branch heads when the retire flag first went up

    def on_event(stream: StreamState) -> Literal["go", "retire", "kill"]:
        events = stream.activity.events
        for event in events[shown[0] :]:
            progress.agent_event(who, sid, event)
        shown[0] = len(events)
        if capabilities.context and stream.context_tokens >= cfg.hard_ceiling:
            progress.killing(sid, stream.context_tokens, who)
            return "kill"
        why: Literal["context", "budget", "cap"] | None = None
        if since is not None and ledger.over(cfg, stream.spend, since, capabilities=capabilities) is not None:
            watch.budget_hit = True
            why = "budget"
        elif capabilities.dollars and cap is not None and ledger.section_spend(sid).dollars + stream.spend.dollars > cap:
            why = "cap"
        elif capabilities.context and stream.context_tokens >= cfg.context_limit:
            why = "context"
        if why is None:
            return "go"
        if not retiring[0]:
            retiring[0] = True
            progress.retiring(sid, why, stream.context_tokens, who)
        if who not in ("recut", "design"):  # these edit files and need not commit: no commit-based idle kill
            if not snapshot:
                snapshot.append(git.heads(repo))
            elif capabilities.context and stream.context_tokens >= cfg.idle_ceiling and snapshot[0]:
                # `git.heads` is {} when git fails: an empty read proves no commit either way.
                now = git.heads(repo)
                if now and now == snapshot[0]:
                    if who == "lead":  # a research or ask run killed here is a failed run
                        watch.idle_retired = True
                    progress.retired_idle(sid, stream.context_tokens, who)
                    return "kill"
        return "retire"

    watch = _Watch(on_event=on_event)  # `on_event` reads `watch` when it runs, after this line
    return watch


def _park(
    cfg: Config,
    queue: Path,
    state: State,
    sid: str,
    question: str,
    design: tuple[str, tuple[int, ...]] | None = None,
) -> None:
    """Park `sid` with `question`, ping the owner and show the question: the one park.
    `design` (path, numbers) marks the question as the open design decisions' (state.park)."""
    state.park(sid, question, design)
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
    where = _section_cwd(cwd, queue, sid, state)
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


def _design_failed_stop(sid: str, count: int, reason: str | None) -> _Stop:
    return (
        ExitCode.FAILED_TWICE,
        "architect failed repeatedly",
        f"section {sid}: {count} unusable architect cycles; last failure: {reason or 'unknown'}; "
        "fix the cause, then relay answer to retry",
    )


def _climb(
    queue: Path,
    cfg: Config,
    state: State,
    ledger: Ledger,
    since: float,
    cwd: Path,
    retire_flag: Path,
    section: Section,
    kind: Literal["RECUT", "DESIGN"],
    text: str,
    lead_log: Path,
    drain: DrainSwitch,
) -> _Stop | None:
    """The ladder's move for a RECUT or DESIGN: rung 1 a recut, rung 2 a design change, rung 3 a park."""
    sid = section.id
    design = ladder.design_of(queue_design(queue), cwd)
    step = ladder.climb(kind, state.section(sid), design, sid)
    problem = ladder.split_reason(text)[0]
    if step.rung == 1:
        failed = _recut(
            queue, cfg, state, ledger, since, cwd, retire_flag, section, problem, lead_log, drain=drain
        )
        if isinstance(failed, tuple):
            state.set_pending(sid, Pending(
                kind="climb", lead_log=str(lead_log), problem=problem, status=kind, text=text,
            ))
            return failed
        if failed:
            second, count = _fail(state, sid)
            progress.failed(sid, count)
            if second:
                return _failed_twice(sid)
    elif step.rung == 3:
        _park(cfg, queue, state, sid, step.why)
    else:
        # ladder.climb gives rung 2 only with a design in hand.
        stop = _design_change(
            queue, cfg, state, ledger, since, cwd, retire_flag, section, cast(Path, design), problem, lead_log, drain
        )
        if stop == _drained() and state.section(sid).pending is None:
            state.set_pending(sid, Pending(
                kind="climb", lead_log=str(lead_log), problem=problem, status=kind, text=text,
            ))
        return stop
    return None


def _design_change(
    queue: Path,
    cfg: Config,
    state: State,
    ledger: Ledger,
    since: float,
    cwd: Path,
    retire_flag: Path,
    section: Section,
    design: Path,
    problem: str,
    lead_log: Path,
    drain: DrainSwitch,
) -> _Stop | None:
    """Run the architect on `design` for `problem`, then act on its report."""
    if _over_cap(cfg, queue, state, ledger, section):
        return
    check_log = state.check_log(lead_log)
    evidence = [lead_log, *([check_log] if check_log.exists() else [])]
    current = state.section(section.id)
    brief = design_brief(
        design, queue, section, problem, evidence, cfg.design_approval,
        current.answers, _lead_code(cwd, queue, section.id, state),
    )
    return _architect(queue, cfg, state, ledger, since, cwd, retire_flag, section, design, brief, problem, lead_log, drain)


def _lead_code(cwd: Path, queue: Path, sid: str, state: State) -> tuple[str, str | None] | None:
    """The validated lead branch and its current worktree HEAD for architect evidence."""
    tree = _section_worktree(cwd, queue, sid, state)
    return (tree.branch, git.head(tree.path)) if tree is not None else None


def _design_answer(
    queue: Path,
    cfg: Config,
    state: State,
    ledger: Ledger,
    since: float,
    cwd: Path,
    retire_flag: Path,
    section: Section,
    design_open: str,
    answer: str,
    drain: DrainSwitch,
) -> _Stop | None:
    """Run the architect with the owner's `answer` to the open decisions, then act on its report."""
    sid = section.id
    current = state.section(sid)
    design = Path(design_open)
    if not current.last_log:
        # The recut needs the lead's log as evidence; none is recorded, so the design change cannot land.
        state.set_design_open(sid, None)
        what = "no lead log is recorded for the section"
        _park(cfg, queue, state, sid, ladder.failed_text(sid, design, what))
        return
    # A record parked before the numbers were stored has none: the brief then numbers the answer "new".
    numbers = tuple(current.design_numbers or ())
    brief = design_answer_brief(design, numbers, answer, cfg.design_approval)
    problem = f"the owner ruled on the open design decisions: {answer}"
    return _architect(
        queue, cfg, state, ledger, since, cwd, retire_flag, section, design, brief, problem,
        Path(current.last_log), drain, on_dispatch=lambda: state.take_answer(sid),
    )


def _over_cap(cfg: Config, queue: Path, state: State, ledger: Ledger, section: Section) -> bool:
    """Park `section` and return True when its spend is over its dollar cap."""
    cap = ladder.section_cap(cfg, section)
    if cap is None or not backends.get_backend(cfg.backend).capabilities.dollars:
        return False
    spent = ledger.section_spend(section.id).dollars
    if spent <= cap:
        return False
    _park(cfg, queue, state, section.id, ladder.cap_text(section.id, spent, cap))
    return True


def _architect(
    queue: Path,
    cfg: Config,
    state: State,
    ledger: Ledger,
    since: float,
    cwd: Path,
    retire_flag: Path,
    section: Section,
    design: Path,
    brief: str,
    problem: str,
    lead_log: Path,
    drain: DrainSwitch,
    on_dispatch: Callable[[], object] | None = None,
) -> _Stop | None:
    """The architect run on `design` with `brief`, run once more when it failed or filed no report
    (the reason and its final message added to the brief) unless the budget or the section's cap is
    spent; then act on its report."""
    sid = section.id
    current = state.section(sid)
    if current.design_failures >= DESIGN_FAILURE_LIMIT:
        return _design_failed_stop(sid, current.design_failures, current.design_failure)
    ran = _architect_run(
        cfg, state, ledger, since, retire_flag, section, design, brief, problem, drain, on_dispatch
    )
    if ran is None:
        return _drained()
    result, report = ran
    failed = run_failed(result)
    if failed or report is None:
        if _over_cap(cfg, queue, state, ledger, section):
            return
        if ledger.over(cfg, Spend(0, 0.0), since) is None:
            error = error_line(result) if failed else None
            what = f"it failed: {error}" if failed else "it filed no report"
            progress.design_retrying(sid, what)
            retry = design_retry_brief(brief, ladder.said(result.stream.result_text), error)
            ran = _architect_run(
                cfg, state, ledger, since, retire_flag, section, design, retry, problem, drain
            )
            if ran is None:
                state.set_pending(sid, Pending(
                    kind="design-retry", lead_log=str(lead_log), problem=problem,
                    design=str(design), brief=retry,
                ))
                return _drained()
            result, report = ran
    return _design_outcome(
        queue, cfg, state, ledger, since, cwd, retire_flag, section, design, problem, lead_log, result, report, drain
    )


def _architect_run(
    cfg: Config,
    state: State,
    ledger: Ledger,
    since: float,
    retire_flag: Path,
    section: Section,
    design: Path,
    brief: str,
    problem: str,
    drain: DrainSwitch,
    on_dispatch: Callable[[], object] | None = None,
) -> tuple[RunResult, ladder.DesignReport | None] | None:
    """One architect run on `design` with `brief`: its result and its parsed report."""
    where = _git_top(design.parent)
    if drain.requested:
        return None
    if on_dispatch is not None:
        on_dispatch()
    progress.design_started(section.id, design, section.steps, problem)
    result, _ = _run(
        cfg, state, ledger, since, "design", section.id, cfg.design_command, brief,
        where, retire_flag, None, 2,
    )
    report = ladder.parse_report(result.stream.result_text)
    progress.design_finished(section.id, result, report)
    return result, report


def _went_wrong(result: RunResult, report: ladder.DesignReport | None) -> str | None:
    """Why the architect's run filed no design change, None when its report decides something
    (decisions, unfiled lines or an approval)."""
    if run_failed(result):
        return f"it failed: {error_line(result)}"
    if report is None:
        return "it filed no report"
    if report.rejected:
        return "it rejected the brief as steering"
    if report.decisions or report.unfiled:
        return None
    if not report.approved:
        return "it did not approve the design"
    return None


def _design_outcome(
    queue: Path,
    cfg: Config,
    state: State,
    ledger: Ledger,
    since: float,
    cwd: Path,
    retire_flag: Path,
    section: Section,
    design: Path,
    problem: str,
    lead_log: Path,
    result: RunResult,
    report: ladder.DesignReport | None,
    drain: DrainSwitch,
) -> _Stop | None:
    """Reset the failure bound on usable progress; otherwise count the completed unusable
    cycle, handing back below the limit and stopping at it without a product-choice park."""
    sid = section.id
    what = _went_wrong(result, report)
    if what is not None:
        count = state.record_design_failure(sid, what)
        state.set_design_open(sid, None)
        if count >= DESIGN_FAILURE_LIMIT:
            return _design_failed_stop(sid, count, what)
        state.set_guidance(sid, ladder.handback_text(what, ladder.said(result.stream.result_text)))
        progress.design_handed_back(sid, what)
        return
    assert report is not None
    state.clear_design_failures(sid)
    if report.decisions or report.unfiled:
        _park(
            cfg, queue, state, sid, ladder.decisions_text(sid, design, report),
            (str(design), ladder.decision_numbers(report)),
        )
        return
    state.set_design_open(sid, None)
    state.mark_design_changed(sid)
    if drain.requested:
        state.set_pending(sid, Pending(
            kind="design-recut", lead_log=str(lead_log), problem=problem, design=str(design),
        ))
        return _drained()
    failed = _recut(
        queue, cfg, state, ledger, since, cwd, retire_flag, section, problem, lead_log, design, 2, drain=drain
    )
    if isinstance(failed, tuple):
        state.set_pending(sid, Pending(
            kind="design-recut", lead_log=str(lead_log), problem=problem, design=str(design),
        ))
        return failed
    if failed:
        _park(cfg, queue, state, sid, ladder.failed_text(sid, design, failed))


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
    lead_log: Path,
    design: Path | None = None,
    rung: Literal[1, 2] = 1,
    *,
    drain: DrainSwitch,
) -> str | _Stop | None:
    """Run a transactional recut; why it failed, else None, with failure policy owned by the caller."""
    brief = recut_brief(queue, section, reason, lead_log, design)
    original_queue = queue.read_bytes()
    original_mode = stat.S_IMODE(queue.stat().st_mode)
    before = parse_queue(queue)
    if drain.requested:
        return _drained()
    progress.recut_started(section.id, reason)
    changed = False
    after = before
    known = {s.id: s for s in before}
    nested: list[str] = []
    kept: Path | None = None
    try:
        result, _ = _run(
            cfg, state, ledger, since, "recut", section.id, cfg.recut_command, brief,
            cwd, retire_flag, None, rung,
        )
        failed = run_failed(result, require_tokens=False)
        if not failed:
            try:
                after = parse_queue(queue)
            except QueueFormatError:
                failed = True
            else:
                changed = after != before
                nested = sorted(s.id for s in after if s.id not in known and s.id.startswith(f"{section.id}."))
                if nested:
                    # A rejected recut's sections never run: keep the cut beside the run log.
                    kept = state.rejected_cut(result.log)
                    atomic_write(kept, queue.read_bytes())
                failed = not changed or bool(nested)
    except BaseException:
        atomic_write(queue, original_queue, mode=original_mode)
        raise
    if failed:
        # A failed restoration must propagate without attempting it again.
        atomic_write(queue, original_queue, mode=original_mode)
        changed = False
    if nested:
        why = f"Relay rejects nested ids ({', '.join(nested)})"
        progress.recut_finished(section.id, result, False, why)
        return f"{why}; the rejected cut is kept in {kept}"
    progress.recut_finished(section.id, result, changed)
    if failed:
        return "the recut made no usable change"
    if section.id not in {s.id for s in after}:
        state.drop_map(section.id)
    # A recut that keeps the section's id rewrote it in place only when its own entry changed
    # (the blank lines trailing it are not part of it): mark each new id, and the section then.
    for made in after:
        if made.id not in known or (made.id == section.id and not same_entry(made, known[made.id])):
            state.mark_from_recut(made.id)
            if design is not None:
                state.mark_design_changed(made.id)
    return None
