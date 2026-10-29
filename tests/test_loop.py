"""Red tests for Relay's loop (design: Modules `relay/loop.py`, its pass steps 1 to 8, its stops and the lead's cwd; Order 13)."""

from __future__ import annotations

import dataclasses
import inspect
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

import relay.ping
import relay.queue
import relay.runner
import relay.backends
from relay.backends.base import Capabilities
from relay.stream import StreamState
from relay.config import Config
from relay.errors import ExitCode, LockedError
from relay.ledger import Ledger, Spend
from relay.loop import run
from relay.queue import parse_queue
from relay.research import Map, block
from relay.state import State
from harness import RECORD as _RECORD
from harness import Background as _Background, ledger_line as _ledger_line, pings as _pings, until as _until

from tests.conftest import _GIT, GitRepo

FIXTURES = Path(__file__).parent / "fixtures"
WORKBOARD = "workboard-queue.md"
M2 = "m2-rest-queue.md"

# The scripted lead whose result ends "DONE" (session "sess-lead-1"), and the one whose
# result carries no status line (session "sess-lead-2").
DONE_LEAD = "stream-lead.jsonl"
NO_STATUS_LEAD = "stream-error.jsonl"



def _lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text().splitlines()


_UNITTEST_MODULES = ("test_model", "test_collect", "test_repos", "test_sources", "test_lineage")
_IMPORTED_MODULES = (
    "budget",
    "sources",
    "events",
    "hook",
    "statusline",
    "history",
    "lineage",
    "otel",
    "progress",
    "repos",
    "state",
    "terminus",
    "transcript",
    "views",
)
_CHECKED_SCRIPTS = (
    "core.js",
    "strip.js",
    "drill.js",
    "views/failures.js",
    "views/history.js",
    "views/now.js",
    "views/steps.js",
    "views/timeline.js",
    "views/worktrees.js",
)


def _workboard_checks_pass(top: Path) -> None:
    """Give the git top level `top` the files every `done-check:` line of the WORKBOARD queue
    needs to exit 0 there, so a `DONE` on any of its sections passes its check: the older tests
    here claim what follows a section finished and checked, not a failed check."""
    for name in _UNITTEST_MODULES:
        (top / f"{name}.py").write_text(
            "import unittest\n\n\nclass Stub(unittest.TestCase):\n    def test_stub(self):\n        pass\n"
        )
    for name in _IMPORTED_MODULES:
        (top / f"{name}.py").write_text("")
    for name in _CHECKED_SCRIPTS:
        script = top / "web" / name
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("")
    (top / "install").mkdir()
    (top / "install" / "README.md").write_text("Install.\n")


@pytest.fixture
def cfg(loop_cfg: Config, tmp_path: Path) -> Config:
    _workboard_checks_pass(tmp_path)
    return loop_cfg


def _open_ids(queue: Path) -> list[str]:
    """Ids of the sections the queue itself leaves open, in queue order."""
    return [s.id for s in parse_queue(queue) if s.open]


def _untouched(queue: Path, cfg: Config) -> None:
    """No lead ran on any section: none has a session, a failure or a new status."""
    state = State.open(queue, cfg)
    for sid in [s.id for s in parse_queue(queue)]:
        section = state.section(sid)
        assert section.last_session is None, sid
        assert section.failures == 0, sid


def _ran_on(queue: Path, cfg: Config, session: str) -> set[str]:
    """Ids of the sections whose recorded session is `session`."""
    state = State.open(queue, cfg)
    return {s.id for s in parse_queue(queue) if state.section(s.id).last_session == session}


def _park_all_but_done(queue: Path, cfg: Config, parked: str) -> State:
    """Park `parked` and mark every other section of the queue done."""
    state = State.open(queue, cfg)
    for sid in [s.id for s in parse_queue(queue)]:
        if sid != parked:
            state.mark_done(sid)
    state.park(parked, "Which port should the server use?")
    return state


# Behavior 2: If the stop file exists, stop with `STOP_FILE`.


def test_a_stop_file_present_at_the_start_stops_with_stop_file_and_runs_no_lead(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    State.open(queue, cfg).stop_file.touch()
    assert run(queue, cfg) == ExitCode.STOP_FILE
    _untouched(queue, cfg)
    state = State.open(queue, cfg)
    assert all(state.section(sid).status == "open" for sid in _open_ids(queue))


def test_the_stop_file_is_checked_before_the_budget(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    cfg = dataclasses.replace(cfg, token_budget=1, dollar_budget=0.01)
    state = State.open(queue, cfg)
    _ledger_line(state, time.time() + 3600, 1_000_000, 900.0)
    state.stop_file.touch()
    assert run(queue, cfg) == ExitCode.STOP_FILE
    _untouched(queue, cfg)


def test_the_stop_file_is_checked_before_an_empty_queue(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(M2)
    scenario(_lines(DONE_LEAD))
    state = State.open(queue, cfg)
    for sid in _open_ids(queue):
        state.mark_done(sid)
    state.stop_file.touch()
    assert run(queue, cfg) == ExitCode.STOP_FILE


# Behavior 3: If the ledger, summed since this `relay go` started, is over budget, stop with `BUDGET`.


@pytest.mark.parametrize(
    "budget",
    [{"token_budget": 100}, {"dollar_budget": 0.1}],
    ids=["tokens", "dollars"],
)
def test_a_lead_run_that_spends_past_the_budget_stops_with_budget_before_another_lead(
    cfg: Config,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    budget: dict[str, object],
) -> None:
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    cfg = dataclasses.replace(cfg, **budget)
    assert run(queue, cfg) == ExitCode.BUDGET
    assert _ran_on(queue, cfg, "sess-lead-1") == {_open_ids(queue)[0]}


@pytest.mark.parametrize(
    ("budget", "tokens", "dollars"),
    [({"token_budget": 1000}, 1001, 0.0), ({"dollar_budget": 1.0}, 0, 1.01)],
    ids=["tokens", "dollars"],
)
def test_ledger_spend_stamped_since_this_go_started_over_budget_stops_with_budget_and_runs_no_lead(
    cfg: Config,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    budget: dict[str, object],
    tokens: int,
    dollars: float,
) -> None:
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    cfg = dataclasses.replace(cfg, **budget)
    _ledger_line(State.open(queue, cfg), time.time() + 3600, tokens, dollars)
    assert run(queue, cfg) == ExitCode.BUDGET
    _untouched(queue, cfg)


def test_ledger_spend_from_before_this_go_started_does_not_count_toward_the_budget(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(M2)
    scenario(_lines(DONE_LEAD))
    cfg = dataclasses.replace(cfg, token_budget=1000, dollar_budget=1.0)
    state = State.open(queue, cfg)
    _ledger_line(state, time.time() - 3600, 1_000_000_000, 1_000_000.0)
    _ledger_line(state, time.time() - 7 * 86400, 1_000_000_000, 1_000_000.0)
    for sid in _open_ids(queue):
        state.mark_done(sid)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY


# Behavior 4: Re-parse the queue. Pick the first section that is open in the queue, not `done`
# or `parked` in state, and not blocked by a parked section.


@pytest.mark.parametrize("name", [WORKBOARD, M2])
def test_the_lead_runs_on_the_first_section_the_queue_leaves_open(
    name: str, cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(name)
    scenario(_lines(NO_STATUS_LEAD))
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    first = _open_ids(queue)[0]
    assert _ran_on(queue, cfg, "sess-lead-2") == {first}
    state = State.open(queue, cfg)
    assert state.section(first).failures >= 1
    assert state.section(first).failures == 2
    assert all(state.section(sid).failures == 0 for sid in _open_ids(queue) if sid != first)


def test_a_section_done_in_state_is_passed_over(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(WORKBOARD)
    scenario(_lines(NO_STATUS_LEAD))
    ids = _open_ids(queue)
    state = State.open(queue, cfg)
    state.mark_done(ids[0])
    state.mark_done(ids[1])
    run(queue, cfg)
    assert _ran_on(queue, cfg, "sess-lead-2") == {ids[2]}
    assert State.open(queue, cfg).section(ids[0]).status == "done"
    assert State.open(queue, cfg).section(ids[1]).status == "done"


def _with_depends(queue: Path, depends: dict[str, str]) -> Path:
    """Give each section `sid` of `queue` a `depends: <id>` field on its header line, the
    divvyer's dependency format; return `queue`."""
    lines = queue.read_text().splitlines(keepends=True)
    for n, line in enumerate(lines):
        for sid, dep in depends.items():
            if line.startswith(f"section {sid} |"):
                lines[n] = line.rstrip("\n") + f" | depends: {dep}\n"
    queue.write_text("".join(lines))
    return queue


# The first three sections of each fixture queue, and the section that should run once the
# first is parked: the second depends on the first and the third on the second, so parking
# the first blocks both, the third transitively.
_CHAINS = {WORKBOARD: ("s1.1.1", "s1.1.2", "s1.2", "s2"), M2: ("s1", "s2", "s3", "s4")}


@pytest.mark.parametrize("name", [WORKBOARD, M2])
def test_a_parked_section_and_every_section_it_blocks_are_passed_over(
    name: str, cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop runs a section that depends, directly or transitively, on a parked one.
    first, second, third, expected = _CHAINS[name]
    queue = _with_depends(queue_file(name), {second: first, third: second})
    scenario(_lines(NO_STATUS_LEAD))
    State.open(queue, cfg).park(first, "Which port should the server use?")
    run(queue, cfg)
    assert _ran_on(queue, cfg, "sess-lead-2") == {expected}
    assert State.open(queue, cfg).section(first).status == "parked"


def test_a_section_parked_mid_queue_is_passed_over_for_the_next_unblocked_one(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop never weighs dependencies, so s1.2, which depends on the parked
    # s1.1.2, runs next.
    queue = _with_depends(queue_file(WORKBOARD), {"s1.2": "s1.1.2"})
    scenario(_lines(NO_STATUS_LEAD))
    state = State.open(queue, cfg)
    state.mark_done("s1.1.1")
    state.park("s1.1.2", "Keep the v1 routes?")
    run(queue, cfg)
    assert _ran_on(queue, cfg, "sess-lead-2") == {"s2"}


def _replace_queue(queue: Path, name: str) -> None:
    """Replace `queue` with the fixture `name` in one rename, so no reader sees it half written."""
    staged = queue.with_name(queue.name + ".staged")
    staged.write_bytes((FIXTURES / name).read_bytes())
    os.replace(staged, queue)


def _between_passes(monkeypatch: pytest.MonkeyPatch, change: Callable[[], None]) -> Callable[[float], None]:
    """Wrap `parse_queue` in every loaded `relay` module that holds it; return `apply`.

    `apply(timeout)` makes `change` happen once, in the loop's own thread just before its next
    queue parse, so no pass both read the queue from before `change` and sees state from after
    it. A loop that never parses again gets `change` from the test thread after `timeout`."""
    original = relay.queue.parse_queue
    armed = threading.Event()
    applied = threading.Event()
    once = threading.Lock()
    # Set on the thread running `change`, so a `parse_queue` that `change` itself reaches goes
    # straight to the original instead of waiting on `once`, which that thread holds.
    changing = threading.local()

    def apply_once() -> None:
        with once:
            if not applied.is_set():
                changing.active = True
                try:
                    change()
                finally:
                    changing.active = False
                applied.set()

    def wrapped(*args: object, **kwargs: object) -> object:
        if armed.is_set() and not getattr(changing, "active", False):
            apply_once()
        return original(*args, **kwargs)

    for name, module in list(sys.modules.items()):
        if (name == "relay" or name.startswith("relay.")) and getattr(module, "parse_queue", None) is original:
            monkeypatch.setattr(module, "parse_queue", wrapped)

    def apply(timeout: float) -> None:
        armed.set()
        if not applied.wait(timeout):
            apply_once()

    return apply


def test_each_pass_re_parses_the_queue(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = queue_file(WORKBOARD)
    scenario(_lines(NO_STATUS_LEAD))
    parked = _open_ids(queue)[0]
    state = _park_all_but_done(queue, cfg, parked)

    def replace_and_answer() -> None:
        _replace_queue(queue, M2)
        State.open(queue, cfg).set_answer(parked, "Use port 8080.")

    apply = _between_passes(monkeypatch, replace_and_answer)
    loop = _Background(queue, cfg)
    try:
        loop.wait_for_pass()
        assert loop.still_running()
        apply(5.0)
        loop.finish()
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    assert _ran_on(queue, cfg, "sess-lead-2") == {_open_ids(queue)[0]}
    assert State.open(queue, cfg).section(parked).last_session is None


# Behavior 5: If no such section exists and nothing is parked, stop with `QUEUE_EMPTY`.


@pytest.mark.parametrize("name", [WORKBOARD, M2])
def test_every_section_done_in_state_stops_with_queue_empty_and_runs_no_lead(
    name: str, cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(name)
    scenario(_lines(NO_STATUS_LEAD))
    state = State.open(queue, cfg)
    for sid in _open_ids(queue):
        state.mark_done(sid)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    _untouched(queue, cfg)


# Behavior 1: `relay/loop.py`: the state machine for one `relay go`: pass after pass until a stop.


def test_leads_that_each_end_done_run_the_queue_until_it_is_empty(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(M2)
    scenario(_lines(DONE_LEAD))
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    state = State.open(queue, cfg)
    assert all(state.section(sid).status == "done" for sid in _open_ids(queue))


# Behavior 6: If no section is runnable but some are parked, wait, holding the lock: check every
# `poll_seconds` for the stop file (stop with `STOP_FILE`) or a `relay answer` on a parked
# section (start the next pass). The ping for each parked section went out when it parked;
# waiting sends none.


@pytest.mark.parametrize("name", [WORKBOARD, M2])
def test_with_only_parked_sections_left_the_loop_waits_instead_of_stopping(
    name: str, cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(name)
    scenario(_lines(DONE_LEAD))
    parked = _open_ids(queue)[0]
    state = _park_all_but_done(queue, cfg, parked)
    loop = _Background(queue, cfg)
    try:
        loop.wait_for_pass()
        assert loop.still_running()
        assert State.open(queue, cfg).section(parked).status == "parked"
        assert State.open(queue, cfg).section(parked).last_session is None
    finally:
        state.stop_file.touch()
        loop.thread.join(15)


def test_a_stop_file_created_while_waiting_stops_with_stop_file(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    parked = _open_ids(queue)[0]
    # The stop's ping stamps the wall time as its first act, before any import, so the time
    # measured ends when the loop has seen the stop file and begun its ping, not when the
    # ping's own work and `run`'s return are done.
    stamps = tmp_path / "ping-stamps.txt"
    stamp = "import time, sys; t = time.time(); f = open(sys.argv[1], 'a'); f.write(repr(t) + chr(10)); f.close()"
    cfg = dataclasses.replace(cfg, ping_command=[sys.executable, "-I", "-S", "-c", stamp, str(stamps), "{message}"])
    state = _park_all_but_done(queue, cfg, parked)
    loop = _Background(queue, cfg)
    try:
        loop.wait_for_pass()
        assert loop.still_running()
        touched = time.time()
        State.open(queue, cfg).stop_file.touch()
        assert loop.finish(timeout=5.0) == ExitCode.STOP_FILE
        # A check every `poll_seconds` sees the stop file within one wait: a wait of a fixed
        # second or more misses this bound.
        seen = [float(line) for line in stamps.read_text().splitlines()]
        assert len(seen) == 1
        assert seen[0] - touched < 7 * cfg.poll_seconds
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    assert State.open(queue, cfg).section(parked).last_session is None


def test_an_answer_on_a_parked_section_while_waiting_starts_the_next_pass(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    parked = _open_ids(queue)[0]
    state = _park_all_but_done(queue, cfg, parked)
    loop = _Background(queue, cfg)
    try:
        loop.wait_for_pass()
        assert loop.still_running()
        State.open(queue, cfg).set_answer(parked, "Use port 8080.")
        assert loop.finish() == ExitCode.QUEUE_EMPTY
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    section = State.open(queue, cfg).section(parked)
    assert section.status == "done"
    assert section.last_session == "sess-lead-1"


def test_the_loop_holds_the_lock_while_waiting(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    state = _park_all_but_done(queue, cfg, _open_ids(queue)[0])
    loop = _Background(queue, cfg)
    try:
        loop.wait_for_pass()
        assert loop.still_running()
        with pytest.raises(LockedError):
            State.open(queue, cfg).lock()
    finally:
        state.stop_file.touch()
        loop.thread.join(15)


def test_waiting_sends_no_ping(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    state = _park_all_but_done(queue, cfg, _open_ids(queue)[0])
    loop = _Background(queue, cfg)
    try:
        loop.wait_for_pass()
        assert loop.still_running()
        loop.wait_for_pass()
        assert loop.still_running()
        assert _pings(tmp_path) == []
    finally:
        state.stop_file.touch()
        loop.thread.join(15)


# Behaviors 7 to 11 use the in-process runner to record prompts and retire flags.

# In DONE_LEAD, the first assistant message (line 1) leaves context_tokens at 3 + 1200 + 5000
# and spend.tokens at 3 + 1200 + 5000 + 40; the second (line 3) leaves context_tokens at
# 7 + 100 + 900 and adds 7 + 100 + 900 + 25 to the spend; the result adds 0.4321 dollars.
FIRST_CONTEXT = 3 + 1200 + 5000
FIRST_SPEND = 3 + 1200 + 5000 + 40
DONE_SPEND = Spend(tokens=(3 + 1200 + 5000 + 40) + (7 + 100 + 900 + 25), dollars=0.4321)
# In NO_STATUS_LEAD, one assistant message and a result without total_cost_usd.
NO_STATUS_SPEND = Spend(tokens=5 + 0 + 2000 + 10, dollars=0.0)


def _shimmed(cfg: Config, tmp_path: Path, split: int = 0, touch: Path | None = None) -> Config:
    """`cfg` with its lead behind the recording shim, recording to `<tmp_path>/records`; each
    lead creates `touch` as it starts, when given."""
    rec = tmp_path / "records"
    rec.mkdir(exist_ok=True)
    lead = ["fake-record", str(rec), str(split), str(touch) if touch is not None else ""]
    return dataclasses.replace(cfg, lead_command=lead)


def _shimmed_runs(tmp_path: Path) -> int:
    """How many leads the recording shim has seen."""
    return len(list((tmp_path / "records").glob("run-*.json")))


def _record(tmp_path: Path, n: int) -> dict[str, object]:
    return json.loads((tmp_path / "records" / f"run-{n}.json").read_text())


def _ledger(queue: Path, cfg: Config) -> Ledger:
    return Ledger(State.open(queue, cfg).stop_file.parent / "ledger.jsonl")


# Behavior 7: 6. Otherwise, run a lead with `resume` set to the section's `last_session`, or
# else `last_session_any`. During the run, `on_event` returns:


def test_the_lead_resumes_its_sections_own_last_session(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop passes last_session_any, or no resume, though the section has its own.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first, other = _open_ids(queue)[:2]
    state = State.open(queue, cfg)
    state.set_last_session(first, "sess-own")
    state.set_last_session(other, "sess-other")
    run(queue, _shimmed(cfg, tmp_path))
    prompt = _record(tmp_path, 0)["prompt"]
    assert "resume sess-own" in prompt
    assert "resume sess-other" not in prompt


def test_a_section_without_its_own_session_resumes_last_session_any(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop passes no resume when only another section has a session.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    other = _open_ids(queue)[1]
    State.open(queue, cfg).set_last_session(other, "sess-other")
    run(queue, _shimmed(cfg, tmp_path))
    assert "resume sess-other" in _record(tmp_path, 0)["prompt"]


def test_the_next_sections_lead_resumes_the_session_the_last_lead_recorded(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the second lead of a `relay go` is not given the first lead's session.
    queue = queue_file(M2)
    scenario(_lines(DONE_LEAD))
    run(queue, _shimmed(cfg, tmp_path))
    assert "resume sess-lead-1" in _record(tmp_path, 1)["prompt"]


# Behavior 8: - `retire` once `context_tokens ≥ context_limit` or the live spend passes a budget;


def test_context_tokens_reaching_context_limit_create_the_retire_flag_during_the_run(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: on_event compares context_tokens with `>` or never returns "retire".
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    cfg = dataclasses.replace(cfg, context_limit=FIRST_CONTEXT)
    run(queue, _shimmed(cfg, tmp_path, split=2))
    appeared = _record(tmp_path, 0)["appeared"]
    assert appeared != []


def test_context_tokens_below_context_limit_create_no_retire_flag(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: on_event returns "retire" below context_limit.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    cfg = dataclasses.replace(cfg, context_limit=FIRST_CONTEXT + 1)
    assert run(queue, _shimmed(cfg, tmp_path, split=2)) == ExitCode.QUEUE_EMPTY
    assert _record(tmp_path, 0)["appeared"] == []


def test_live_spend_passing_the_token_budget_creates_the_retire_flag_during_the_run(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: on_event ignores the live spend, leaving the budget to the next pass.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    cfg = dataclasses.replace(cfg, token_budget=FIRST_SPEND - 1)
    assert run(queue, _shimmed(cfg, tmp_path, split=2)) == ExitCode.BUDGET
    assert _record(tmp_path, 0)["appeared"] != []


def test_live_spend_counts_this_gos_ledger_spend_toward_the_budget(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: on_event weighs the run's own spend alone against the budget.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    cfg = dataclasses.replace(cfg, token_budget=10_000)
    _ledger_line(State.open(queue, cfg), time.time() + 3600, 5000, 0.0)
    run(queue, _shimmed(cfg, tmp_path, split=2))
    assert _record(tmp_path, 0)["appeared"] != []


def test_live_spend_leaves_ledger_spend_from_before_this_go_out_of_the_budget(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: on_event weighs the live spend against the all-time ledger (since=None).
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    cfg = dataclasses.replace(cfg, token_budget=10_000)
    _ledger_line(State.open(queue, cfg), time.time() - 3600, 5000, 0.0)
    run(queue, _shimmed(cfg, tmp_path, split=2))
    assert _record(tmp_path, 0)["appeared"] == []


# Behavior 9: - `kill` at `hard_ceiling`.


def test_a_lead_whose_context_reaches_hard_ceiling_is_killed_and_not_marked_done(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: on_event returns "retire" or "go" at hard_ceiling, letting the lead end DONE.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    cfg = dataclasses.replace(cfg, context_limit=FIRST_CONTEXT - 200, hard_ceiling=FIRST_CONTEXT)
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert State.open(queue, cfg).section(_open_ids(queue)[0]).status == "open"


def test_a_lead_whose_context_stays_below_hard_ceiling_is_not_killed(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: on_event returns "kill" below hard_ceiling, or at context_limit.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    cfg = dataclasses.replace(cfg, context_limit=FIRST_CONTEXT - 200, hard_ceiling=FIRST_CONTEXT + 1)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    state = State.open(queue, cfg)
    assert all(state.section(sid).status == "done" for sid in _open_ids(queue))


# Behavior 10: 7. Append the run's spend to the ledger and record its session.


def test_each_lead_runs_spend_is_appended_to_the_ledger(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop appends no spend, or one entry for the whole `relay go`.
    queue = queue_file(M2)
    scenario(_lines(DONE_LEAD))
    n = len(_open_ids(queue))
    run(queue, cfg)
    total = _ledger(queue, cfg).total(None)
    assert total.tokens == n * DONE_SPEND.tokens
    assert total.dollars == pytest.approx(n * DONE_SPEND.dollars)
    # One readable line per lead run, each holding that run's own spend.
    assert _ledger(queue, cfg).unreadable() == []
    lines = [json.loads(line) for line in (State.open(queue, cfg).stop_file.parent / "ledger.jsonl").read_text().splitlines()]
    # relay-check-design.md:168-170: a check line is kind "check"; every other line is a lead run's.
    entries = [e for e in lines if e["kind"] != "check"]
    assert len(entries) == n
    assert all(e["tokens"] == DONE_SPEND.tokens for e in entries)
    assert all(e["dollars"] == pytest.approx(DONE_SPEND.dollars) for e in entries)
    # relay-check-design.md:244-247: no m2 section has a check line, so each DONE adds one check
    # line with verdict "none"; relay-check-design.md:168-170: its session is null and it spends nothing.
    checks = [e for e in lines if e["kind"] == "check"]
    assert sorted(e["section"] for e in checks) == sorted(_open_ids(queue))
    assert all(e["verdict"] == "none" for e in checks)
    assert all(e["session"] is None and e["tokens"] == 0 and e["dollars"] == 0.0 for e in checks)


def test_a_failed_lead_runs_spend_is_appended_to_the_ledger_too(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop appends spend only for a run that ends DONE.
    queue = queue_file(WORKBOARD)
    scenario(_lines(NO_STATUS_LEAD))
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert _ledger(queue, cfg).total(None) == Spend(tokens=2 * NO_STATUS_SPEND.tokens, dollars=0.0)


def test_each_lead_runs_session_is_recorded_on_its_section(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop records no session, or records it on another section.
    queue = queue_file(M2)
    scenario(_lines(DONE_LEAD))
    run(queue, cfg)
    assert _ran_on(queue, cfg, "sess-lead-1") == set(_open_ids(queue))
    assert State.open(queue, cfg).last_session_any == "sess-lead-1"


def test_a_failed_lead_runs_session_is_recorded_too(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop records a session only for a run that ends DONE.
    queue = queue_file(WORKBOARD)
    scenario(_lines(NO_STATUS_LEAD))
    run(queue, cfg)
    assert State.open(queue, cfg).section(_open_ids(queue)[0]).last_session == "sess-lead-2"


# Behavior 11: The lead and the recut run with `cwd` set to the git top level of the queue's directory.


def test_the_lead_runs_in_the_git_top_level_of_the_queues_directory(
    cfg: Config, tmp_path: Path, scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the lead runs in the queue's own directory or in Relay's working directory.
    queue = tmp_path / "docs" / "plans" / WORKBOARD
    queue.parent.mkdir(parents=True)
    queue.write_bytes((FIXTURES / WORKBOARD).read_bytes())
    scenario(_lines(DONE_LEAD))
    run(queue, _shimmed(cfg, tmp_path))
    assert Path(str(_record(tmp_path, 0)["cwd"])).resolve() == tmp_path.resolve()


# Pass step 8 scripts successive leads and recuts through the shared fake runner.
# Behaviors of pass step 8, the budget-triggered retire and the stops (s7.d3) script each
# lead and recut run through a sequencing shim put in front of the fake `claude`. The shim
# reads the prompt on stdin and writes `{"cwd", "prompt"}` to `<record dir>/run-<n>.json`,
# n counting from 0. Run n takes the plan's step n (the last step once the plan runs out,
# or step n modulo the plan's length when it cycles): it copies the step's `write` source
# over its target when the step has one, then runs the step's `then` command when it has one,
# runs the fake on the step's scenario file and exits with the step's exit code. Every stream
# line it emits is the fake's, from `tests/fixtures/`.
_SEQ = r"""
import json, os, subprocess, sys
rec, fake, plan = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
prompt = sys.stdin.read()
n = len([p for p in os.listdir(rec) if p.startswith("run-") and p.endswith(".json")])
out = os.path.join(rec, "run-%d.json" % n)
with open(out + ".part", "w") as f:
    json.dump({"cwd": os.getcwd(), "prompt": prompt}, f)
os.replace(out + ".part", out)
steps = plan["steps"]
step = steps[n % len(steps)] if plan["cycle"] else steps[min(n, len(steps) - 1)]
if step.get("write"):
    src, dst = step["write"]
    with open(src, "rb") as f:
        data = f.read()
    with open(dst, "wb") as f:
        f.write(data)
if step.get("then"):
    subprocess.run(step["then"], stdin=subprocess.DEVNULL, check=True)
env = dict(os.environ, RELAY_FAKE_SCENARIO=step["scenario"])
sys.stdout.flush()
subprocess.run([fake], stdin=subprocess.DEVNULL, env=env, check=True)
sys.exit(step["exit"])
"""

# Scripted leads of `tests/fixtures/`, each a session of its own, ending with the status line named.
RETIRED_LEAD = "stream-retired.jsonl"  # "RETIRED", session "sess-lead-3"
RECUT_LEAD = "stream-recut.jsonl"  # "RECUT: step 2 needs a split", session "sess-lead-4"
NEEDS_OWNER_LEAD = "stream-needs-owner.jsonl"  # "NEEDS-OWNER: Which port should the server use?", "sess-lead-5"
DONE_SMALL_LEAD = "stream-done-small.jsonl"  # "DONE", session "sess-lead-6", context 1 + 50 + 400
DIVVYER_RUN = "stream-divvyer.jsonl"  # the divvyer's recut run, session "sess-recut-1"

RECUT_REASON = "step 2 needs a split"
QUESTION = "Which port should the server use?"
RETIRED_CONTEXT = 4 + 300 + 1500
RETIRED_SPEND = Spend(tokens=4 + 300 + 1500 + 20, dollars=0.1111)
RECUT_SPEND = Spend(tokens=6 + 200 + 1000 + 30, dollars=0.2222)
DIVVYER_SPEND = Spend(tokens=8 + 400 + 2000 + 50, dollars=0.0444)

REPO = Path(__file__).resolve().parents[1]

# A ping command that records `[message, status of <sid> in state at ping time]` to the record path.
_RECORD_STATE = r"""
import json, sys
from pathlib import Path
repo, record, queue, root, sid, message = sys.argv[1:7]
sys.path.insert(0, repo)
from relay.config import Config
from relay.state import State
cfg = Config(token_budget=None, dollar_budget=None, context_limit=1, hard_ceiling=2, poll_seconds=1.0,
             lead_command=[], recut_command=[], ping_command=[], state_root=Path(root))
status = State.open(Path(queue), cfg).section(sid).status
with open(record, "a") as f:
    f.write(json.dumps([message, status]) + chr(10))
"""


def _step(name: str, exit: int = 0, write: tuple[Path, Path] | None = None, then: list[str] | None = None) -> dict[str, object]:
    """One run of the plan: the fixture scenario `name`, its exit code, a file to copy over another
    first, and a command to run after that copy."""
    return {
        "scenario": str(FIXTURES / name),
        "exit": exit,
        "write": [str(write[0]), str(write[1])] if write else None,
        "then": then,
    }


def _plan(tmp_path: Path, fake: str, role: str, steps: list[dict[str, object]], cycle: bool) -> list[str]:
    rec = tmp_path / "plans" / role
    rec.mkdir(parents=True, exist_ok=True)
    return ["fake-plan", str(rec), json.dumps({"steps": steps, "cycle": cycle})]


def _sequenced(
    cfg: Config,
    tmp_path: Path,
    leads: list[dict[str, object]],
    recuts: list[dict[str, object]] | None = None,
    cycle: bool = False,
) -> Config:
    """`cfg` with each lead run, and each recut run, taking the next step of its plan."""
    fake = cfg.lead_command[0]
    recut_plan = recuts if recuts is not None else [_step(DIVVYER_RUN)]
    return dataclasses.replace(
        cfg,
        lead_command=_plan(tmp_path, fake, "lead", leads, cycle),
        recut_command=_plan(tmp_path, fake, "recut", recut_plan, False),
    )


def _runs(tmp_path: Path, role: str) -> list[dict[str, object]]:
    """The records of every `role` run ("lead" or "recut"), in run order."""
    rec = tmp_path / "plans" / role
    count = len([p for p in rec.iterdir() if p.name.startswith("run-") and p.name.endswith(".json")])
    return [json.loads((rec / f"run-{n}.json").read_text()) for n in range(count)]


def _only_first_open(queue: Path, cfg: Config) -> str:
    """Mark every section but the queue's first open one done in state; return that one's id."""
    ids = _open_ids(queue)
    state = State.open(queue, cfg)
    for sid in [s.id for s in parse_queue(queue)]:
        if sid != ids[0]:
            state.mark_done(sid)
    return ids[0]


def test_generic_loop_ignores_budgets_and_accepts_plain_stdout(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path]
) -> None:
    # Breaks when the loop uses Claude parsing or budget capabilities for generic.
    queue = queue_file(WORKBOARD)
    _only_first_open(queue, cfg)
    command = [sys.executable, "-c", "import sys; sys.stdin.read(); print('DONE')"]
    generic = dataclasses.replace(cfg, backend="generic", lead_command=command,
                                  recut_command=command, token_budget=1,
                                  dollar_budget=0.01)
    _ledger_line(State.open(queue, cfg), time.time() + 3600, 900, 5.0)
    assert run(queue, generic) == ExitCode.QUEUE_EMPTY


@pytest.mark.parametrize("backend", ["generic", "claude"])
def test_zero_token_successful_lead_completes_for_each_token_policy_backend(
    backend: str, cfg: Config, tmp_path: Path,
    queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path],
) -> None:
    # Breaks when lead success requires usage, including for a metered backend.
    queue = queue_file(WORKBOARD)
    sid = _only_first_open(queue, cfg)
    if backend == "generic":
        cfg = dataclasses.replace(cfg, backend=backend, lead_command=[
            sys.executable, "-c", "import sys; sys.stdin.read(); print('DONE')",
        ])
    else:
        events = [json.loads(line) for line in _lines(DONE_LEAD)]
        for event in events:
            event.pop("usage", None)
            event.pop("total_cost_usd", None)
            if "message" in event:
                event["message"].pop("usage", None)
        scenario([json.dumps(event) for event in events])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    section = State.open(queue, cfg).section(sid)
    assert section.status == "done" and section.failures == 0
    assert _entries(queue, cfg, "lead")[0]["tokens"] == 0


def test_zero_token_generic_recut_accepts_a_valid_changed_queue(
    cfg: Config, tmp_path: Path,
) -> None:
    # Breaks when recut requires tokens or fails to run the newly cut section.
    queue = _queue_of(tmp_path / "generic-queue.md", "s1")
    lead = [sys.executable, "-c", (
        "import pathlib,sys; sys.stdin.read(); "
        "print('RECUT: split work' if 'section s1 |' in pathlib.Path(sys.argv[1]).read_text() else 'DONE')"
    ), str(queue)]
    recut = [sys.executable, "-c", (
        "import pathlib,sys; sys.stdin.read(); "
        "pathlib.Path(sys.argv[1]).write_text('section s1a | lead | steps: 1\\n  new work\\n')"
    ), str(queue)]
    cfg = dataclasses.replace(cfg, backend="generic", lead_command=lead, recut_command=recut)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    state = State.open(queue, cfg)
    assert _open_ids(queue) == ["s1a"]
    assert state.section("s1a").status == "done"
    assert state.section("s1").failures == 0
    recuts = _entries(queue, cfg, "recut")
    assert len(recuts) == 1 and recuts[0]["tokens"] == 0


def test_rotation_starts_fresh_runs_with_backend_hint_and_previous_report(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when rotation omits the backend hint/report or resumes the retired process.
    queue = queue_file(WORKBOARD)
    _only_first_open(queue, cfg)
    prompts: list[Path] = []
    roles: list[str] = []
    report = "Committed rotation checkpoint.\nRETIRED"

    class RotatingBackend:
        capabilities = Capabilities(True, True, False, False)

        def argv(self, role: str, cfg: Config, cwd: Path, output: Path) -> list[str]:
            roles.append(role)
            prompt = tmp_path / f"prompt-{len(prompts)}"
            prompts.append(prompt)
            answer = report if len(prompts) == 1 else "DONE"
            script = (
                "import pathlib,sys; "
                "pathlib.Path(sys.argv[1]).write_text(sys.stdin.read()); "
                "print(sys.argv[2])"
            )
            return [sys.executable, "-c", script, str(prompt), answer]

        def parse(self, state: StreamState, line: str) -> StreamState:
            return dataclasses.replace(
                state, session_id=f"thread-{len(prompts)}",
                result_text=(state.result_text or "") + line,
            )

        def poll(self, state: StreamState) -> StreamState:
            return state

        def finish(self, state: StreamState, output: Path) -> StreamState:
            return state

        def resume_hint(self, session_id: str) -> str:
            return f"Prior thread: {session_id}; native history: codex exec resume {session_id}"

    monkeypatch.setattr(relay.backends, "get_backend", lambda name: RotatingBackend())
    assert run(queue, dataclasses.replace(cfg, backend="codex")) == ExitCode.QUEUE_EMPTY
    assert roles == ["lead", "lead"]
    assert report not in prompts[0].read_text()
    assert report in prompts[1].read_text()
    assert "native history: codex exec resume thread-1" in prompts[1].read_text()


@pytest.mark.parametrize("failed_role", ["lead", "recut"])
def test_backend_finalization_error_overrides_successful_child_report(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    failed_role: str,
) -> None:
    # Breaks when runner loses finish's error or loop accepts a DONE report or
    # changed recut queue despite that error (backend design, Modules).
    queue = queue_file(WORKBOARD)
    first = _only_first_open(queue, cfg)
    roles: list[str] = []
    finalized: list[tuple[str, bool]] = []

    class FinalizationBackend:
        capabilities = Capabilities(True, True, False, False)

        def argv(self, role: str, cfg: Config, cwd: Path, output: Path) -> list[str]:
            self.role = role
            roles.append(role)
            answer = "RECUT: split the remaining work" if failed_role == "recut" and len(roles) == 1 else "DONE"
            script = "import pathlib,sys; sys.stdin.read(); print(sys.argv[1]); "
            if role == "recut":
                script += "p=pathlib.Path(sys.argv[2]); p.write_text(p.read_text() + '\\n<!-- recut -->\\n')"
            return [sys.executable, "-c", script, answer, str(queue)]

        def parse(self, state: StreamState, line: str) -> StreamState:
            return dataclasses.replace(state, result_text=(state.result_text or "") + line)

        def poll(self, state: StreamState) -> StreamState:
            return state

        def finish(self, state: StreamState, output: Path) -> StreamState:
            failed = self.role == failed_role
            finalized.append((self.role, failed))
            return dataclasses.replace(state, is_error=failed)

        def resume_hint(self, session_id: str) -> str:
            return ""

    monkeypatch.setattr(relay.backends, "get_backend", lambda name: FinalizationBackend())
    result = run(queue, dataclasses.replace(cfg, backend="codex"))
    section = State.open(queue, cfg).section(first)
    assert section.failures == (2 if failed_role == "lead" else 1)
    assert result == (ExitCode.FAILED_TWICE if failed_role == "lead" else ExitCode.QUEUE_EMPTY)
    assert section.status == ("open" if failed_role == "lead" else "done")
    assert finalized == ([("lead", True), ("lead", True)] if failed_role == "lead" else
                         [("lead", False), ("recut", True), ("lead", False)])


def test_failed_recut_cannot_finish_queue_by_removing_pending_work(
    cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when a finalized recut error leaves its queue changes eligible for
    # acceptance on the next loop pass (backend design, Modules).
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    State.open(queue, cfg).mark_done("s2")
    roles: list[str] = []

    class FailedRecutBackend:
        capabilities = Capabilities(True, True, False, False)

        def argv(self, role: str, cfg: Config, cwd: Path, output: Path) -> list[str]:
            self.role = role
            roles.append(role)
            answer = "RECUT: split the remaining work" if len(roles) == 1 else "No successful report"
            script = "import pathlib,sys; sys.stdin.read(); print(sys.argv[1]); "
            if role == "recut":
                script += "pathlib.Path(sys.argv[2]).write_text('section s2 | lead | steps: 1\\n  s2 work\\n')"
            return [sys.executable, "-c", script, answer, str(queue)]

        def parse(self, state: StreamState, line: str) -> StreamState:
            return dataclasses.replace(state, result_text=(state.result_text or "") + line)

        def poll(self, state: StreamState) -> StreamState:
            return state

        def finish(self, state: StreamState, output: Path) -> StreamState:
            return dataclasses.replace(state, is_error=self.role == "recut")

        def resume_hint(self, session_id: str) -> str:
            return ""

    monkeypatch.setattr(relay.backends, "get_backend", lambda name: FailedRecutBackend())
    result = run(queue, dataclasses.replace(cfg, backend="codex"))
    assert result != ExitCode.QUEUE_EMPTY, "failed recut changes completed the queue"


@pytest.mark.parametrize(("failure", "damage"), [
    (failure, damage)
    for failure in ["exit", "backend", "exception", "success", "killed", "restore-error"]
    for damage in ["valid", "malformed", "empty", "missing", "unchanged"]
    if (failure, damage) != ("success", "valid")
])
def test_recut_transaction_restores_bytes_mode_and_retries(
    cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    damage: str, failure: str,
) -> None:
    # Breaks when failed or invalid recuts escape rollback or skip the retry;
    # unchanged sections must restore even edits outside the parsed sections.
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    original = queue.read_bytes() + b"\n<!-- retained exactly -->\r\n"
    queue.write_bytes(original)
    queue.chmod(0o640)
    State.open(queue, cfg).mark_done("s2")
    roles: list[str] = []
    damaged = False
    original_parse = relay.queue.parse_queue

    def observed_parse(path: Path):
        if damaged and failure in ("exit", "backend", "killed", "restore-error"):
            assert queue.exists(), "failed output parsed before rollback"
            assert queue.read_bytes() == original, "failed output parsed before rollback"
            assert queue.stat().st_mode & 0o777 == 0o640, "mode not restored before parse"
        return original_parse(path)

    monkeypatch.setattr(relay.loop, "parse_queue", observed_parse)

    class RecoveryBackend:
        capabilities = Capabilities(True, True, False, False)

        def argv(self, role: str, cfg: Config, cwd: Path, output: Path) -> list[str]:
            self.role = role
            roles.append(role)
            if len(roles) > 2:
                assert queue.read_bytes() == original, "retry observed failed recut bytes"
                assert queue.stat().st_mode & 0o777 == 0o640, "retry observed changed mode"
            answer = "RECUT: split remaining work" if len(roles) == 1 else "No successful report"
            return [sys.executable, "-c", "import sys; sys.stdin.read(); print(sys.argv[1])", answer]

        def parse(self, state: StreamState, line: str) -> StreamState:
            return dataclasses.replace(
                state, result_text=(state.result_text or "") + line,
                context_tokens=cfg.hard_ceiling if failure == "killed" and self.role == "recut" else 0,
            )

        def poll(self, state: StreamState) -> StreamState:
            return state

        def finish(self, state: StreamState, output: Path) -> StreamState:
            nonlocal damaged
            if self.role != "recut":
                return state
            damaged = True
            if damage == "missing":
                queue.unlink()
            else:
                content = {"valid": b"section s2 | lead | steps: 1\n  s2 work\n",
                           "malformed": b"section malformed\n",
                           "empty": b"", "unchanged": b"<!-- changed -->\n" + original}[damage]
                queue.write_bytes(content)
                queue.chmod(0o600)
            if failure == "exception":
                raise RuntimeError("recut invocation failed")
            return dataclasses.replace(state, is_error=failure in ("backend", "restore-error"))

        def resume_hint(self, session_id: str) -> str:
            return ""

    if failure == "exit":
        original_argv = RecoveryBackend.argv

        def failing_argv(self: RecoveryBackend, role: str, cfg: Config, cwd: Path, output: Path) -> list[str]:
            command = original_argv(self, role, cfg, cwd, output)
            if role == "recut":
                command[2] += "; sys.exit(1)"
            return command

        monkeypatch.setattr(RecoveryBackend, "argv", failing_argv)
    monkeypatch.setattr(relay.backends, "get_backend", lambda name: RecoveryBackend())
    if failure == "restore-error":
        replace = os.replace
        restorations: list[bytes] = []

        def broken_replace(src: object, dst: object, *args: object, **kwargs: object) -> None:
            if Path(dst) == queue:
                restorations.append(Path(src).read_bytes())
                raise OSError("queue restoration failed")
            replace(src, dst, *args, **kwargs)

        monkeypatch.setattr(os, "replace", broken_replace)
        caught = None
        try:
            run(queue, cfg)
        except Exception as exc:
            caught = exc
        assert isinstance(caught, OSError), "restoration error must propagate"
        assert str(caught) == "queue restoration failed"
        assert restorations == [original]
        assert roles == ["lead", "recut"]
        return
    if failure == "exception":
        with pytest.raises(RuntimeError, match="recut invocation failed"):
            run(queue, cfg)
        assert roles == ["lead", "recut"]
    else:
        try:
            result = run(queue, cfg)
        except Exception:
            assert False, "failed recut must recover and retry without raising"
        assert result == ExitCode.FAILED_TWICE
        assert roles == ["lead", "recut", "lead"]
        section = State.open(queue, cfg).section("s1")
        assert section.failures == 2
        assert section.status == "open"
        assert not section.from_recut
    assert queue.exists(), "recut deleted original queue"
    assert queue.read_bytes() == original
    assert queue.stat().st_mode & 0o777 == 0o640


def _body(queue: Path, sid: str) -> str:
    return next(s.body for s in parse_queue(queue) if s.id == sid)


# Behavior 1 (s7.d3): - DONE: `mark_done`.


def test_a_lead_ending_done_marks_its_section_done_and_the_next_lead_takes_the_next_section(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop leaves a DONE section open, or records a failure on it.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    ids = _open_ids(queue)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD), _step(NO_STATUS_LEAD)])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    state = State.open(queue, cfg)
    assert state.section(ids[0]).status == "done"
    assert state.section(ids[0]).failures == 0
    assert state.section(ids[0]).last_session == "sess-lead-1"
    assert _ran_on(queue, cfg, "sess-lead-2") == {ids[1]}
    assert len(_runs(tmp_path, "lead")) == 3


def test_a_section_marked_done_gets_no_second_lead(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: mark_done is skipped, so the next pass runs the same section again.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD), _step(NO_STATUS_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert len(_runs(tmp_path, "lead")) == 1
    assert State.open(queue, cfg).section(first).status == "done"


def test_an_answer_to_a_done_section_wakes_no_lead(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: `relay answer` on a done section reopens it, so `relay go` resumes its lead.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    state = State.open(queue, cfg)
    ids = _open_ids(queue)
    for sid in ids:
        state.mark_done(sid)
    state.set_answer(ids[0], "Use port 8080.")
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    _untouched(queue, cfg)
    assert State.open(queue, cfg).section(ids[0]).status == "done"


# Behavior 2 (s7.d3): - RETIRED: run a fresh lead on the same section; this is no failure.


def test_a_retired_lead_is_followed_by_a_fresh_lead_on_the_same_section(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: RETIRED moves the loop on to the next section, or marks the section done.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    ids = _open_ids(queue)
    cfg = _sequenced(cfg, tmp_path, [_step(RETIRED_LEAD), _step(DONE_LEAD), _step(NO_STATUS_LEAD)])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    runs = _runs(tmp_path, "lead")
    assert _body(queue, ids[0]) in str(runs[1]["prompt"])
    assert "resume sess-lead-3" in str(runs[1]["prompt"])
    state = State.open(queue, cfg)
    assert state.section(ids[0]).status == "done"
    assert state.section(ids[0]).last_session == "sess-lead-1"
    assert _ran_on(queue, cfg, "sess-lead-2") == {ids[1]}


def test_retired_leads_count_no_failure(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop calls record_failure on RETIRED, so a second retire stops FAILED_TWICE.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    leads = [_step(RETIRED_LEAD), _step(RETIRED_LEAD), _step(RETIRED_LEAD), _step(DONE_SMALL_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert len(_runs(tmp_path, "lead")) == 4
    section = State.open(queue, cfg).section(first)
    assert section.failures == 0
    assert section.status == "done"


# Behavior 3 (s7.d3): - RECUT: run `recut_command` with `recut_brief`, append its spend to the
# ledger, and re-parse. A non-zero exit or an unchanged queue file counts as a failure of the section.


def _recut_to_m2(cfg: Config, tmp_path: Path, queue: Path, exit: int = 0) -> Config:
    """Leads: RECUT, then DONE; the recut copies the m2 queue over `queue` and exits `exit`."""
    recut = _step(DIVVYER_RUN, exit=exit, write=(FIXTURES / M2, queue))
    return _sequenced(cfg, tmp_path, [_step(RECUT_LEAD), _step(DONE_LEAD)], recuts=[recut])


def test_a_recut_status_runs_the_recut_command_once_with_the_recut_brief(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop never runs recut_command, or sends it a brief without the reason and the lead's log.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    sid = _open_ids(queue)[0]
    run_dir = State.open(queue, cfg).run_dir
    cfg = _recut_to_m2(cfg, tmp_path, queue)
    run(queue, cfg)
    recuts = _runs(tmp_path, "recut")
    assert len(recuts) == 1
    brief = str(recuts[0]["prompt"])
    assert RECUT_REASON in brief
    assert sid in brief
    assert str(run_dir) in brief
    # The log named is the RECUT lead's own run log, `<run_dir>/<n>.jsonl`.
    logs = sorted(set(re.findall(re.escape(str(run_dir).rstrip("/")) + r"/\d+\.jsonl", brief)))
    assert len(logs) == 1, logs
    log = Path(logs[0])
    assert log.exists()
    assert "sess-lead-4" in log.read_text()
    assert RECUT_REASON in log.read_text()


def test_after_a_recut_the_loop_re_parses_the_queue_and_counts_no_failure(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop keeps the queue it parsed before the recut, or fails a recut that changed it.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    sid = _open_ids(queue)[0]
    cfg = _recut_to_m2(cfg, tmp_path, queue)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    m2_ids = _open_ids(queue)
    assert str(_body(queue, m2_ids[0])) in str(_runs(tmp_path, "lead")[1]["prompt"])
    state = State.open(queue, cfg)
    assert all(state.section(m2).status == "done" for m2 in m2_ids)
    assert state.section(sid).failures == 0


def test_the_recut_runs_spend_is_appended_to_the_ledger(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop appends the leads' spend but not the recut's.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    cfg = _recut_to_m2(cfg, tmp_path, queue)
    run(queue, cfg)
    n = len(_open_ids(queue))
    total = _ledger(queue, cfg).total(None)
    assert total.tokens == RECUT_SPEND.tokens + DIVVYER_SPEND.tokens + n * DONE_SPEND.tokens
    assert total.dollars == pytest.approx(RECUT_SPEND.dollars + DIVVYER_SPEND.dollars + n * DONE_SPEND.dollars)


def test_a_recut_with_a_non_zero_exit_counts_as_a_failure_of_the_section(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop ignores the recut's exit code.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    sid = _open_ids(queue)[0]
    cfg = _recut_to_m2(cfg, tmp_path, queue, exit=1)
    run(queue, cfg)
    assert State.open(queue, cfg).section(sid).failures == 1


def test_a_recut_that_leaves_the_queue_file_unchanged_counts_as_a_failure_of_the_section(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop treats a zero-exit recut as success without checking the queue file changed.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    cfg = _sequenced(cfg, tmp_path, [_step(RECUT_LEAD), _step(DONE_LEAD)], recuts=[_step(DIVVYER_RUN)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    section = State.open(queue, cfg).section(first)
    assert section.failures == 1
    assert section.status == "done"


def test_two_recuts_that_leave_the_queue_unchanged_stop_with_failed_twice(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: a failed recut is not counted with the section's other failures.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    cfg = _sequenced(cfg, tmp_path, [_step(RECUT_LEAD)], recuts=[_step(DIVVYER_RUN)])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert len(_runs(tmp_path, "recut")) == 2
    assert State.open(queue, cfg).section(first).failures == 2


# A section a recut made that itself ends RECUT climbs to rung 2, a design change
# (relay-ladder-design.md:58). With no design named by the queue, rung 2 is rung 3, parked for the
# owner with "no design to amend: the queue names no design file under docs/superpowers/specs/"
# (relay-ladder-design.md:61; relay-codex-architect-design.md:64-66), and it gets no second recut.
NO_DESIGN = "no design to amend: the queue names no design file under docs/superpowers/specs/"


def _queue_of(path: Path, *ids: str) -> Path:
    path.write_text("".join(f"section {sid} | lead | steps: 1\n  {sid} work\n" for sid in ids))
    return path


def test_a_section_from_a_recut_that_ends_recut_with_no_design_is_parked_as_no_design_to_amend_and_not_recut_again(
    cfg: Config, tmp_path: Path, scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: a recut section's RECUT under a queue naming no design runs the divvyer again,
    # parks without NO_DESIGN, or counts a failure.
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    # relay-check-design.md:297: a split makes flat siblings, `s1` giving `s1a`, `s1b`.
    recut = _queue_of(tmp_path / "recut.md", "s1a", "s1b", "s2")
    scenario(_lines(DONE_LEAD))
    leads = [_step(RECUT_LEAD), _step(RECUT_LEAD), _step(NO_STATUS_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads, recuts=[_step(DIVVYER_RUN, write=(recut, queue))])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert len(_runs(tmp_path, "recut")) == 1
    state = State.open(queue, cfg)
    parked = state.section("s1a")
    assert parked.status == "parked"
    assert parked.question is not None and NO_DESIGN in parked.question
    assert parked.failures == 0
    assert state.section("s1b").from_recut
    assert not state.section("s2").from_recut


def test_a_section_from_a_recut_that_ends_recut_with_no_design_pings_the_owner_with_no_design_to_amend_once_parked(
    cfg: Config, tmp_path: Path, scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the recut section parked for having no design to amend sends no needs-owner ping,
    # pings without NO_DESIGN, or pings before it is parked.
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    # relay-check-design.md:297: a split makes flat siblings, `s1` giving `s1a`.
    recut = _queue_of(tmp_path / "recut.md", "s1a", "s2")
    scenario(_lines(DONE_LEAD))
    record = tmp_path / "pings.jsonl"
    ping = [sys.executable, "-c", _RECORD_STATE, str(REPO), str(record), str(queue), str(cfg.state_root), "s1a", "{message}"]
    cfg = dataclasses.replace(cfg, ping_command=ping)
    leads = [_step(RECUT_LEAD), _step(RECUT_LEAD), _step(NO_STATUS_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads, recuts=[_step(DIVVYER_RUN, write=(recut, queue))])
    run(queue, cfg)
    asked = [p for p in _pings(tmp_path) if NO_DESIGN in p[0]]
    assert len(asked) == 1
    message, status = asked[0]
    assert "s1a" in message and "needs the owner" in message
    assert status == "parked"


def test_a_section_the_recut_left_in_place_that_ends_recut_is_still_recut(
    cfg: Config, tmp_path: Path, scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: every section of a recut queue is taken as a recut's, so an original section's RECUT is parked.
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    # relay-check-design.md:297: a split makes flat siblings, `s1` giving `s1a` and `s2` giving `s2a`.
    first = _queue_of(tmp_path / "first.md", "s1a", "s2")
    second = _queue_of(tmp_path / "second.md", "s1a", "s2a")
    scenario(_lines(DONE_LEAD))
    leads = [_step(RECUT_LEAD), _step(DONE_LEAD), _step(RECUT_LEAD), _step(NO_STATUS_LEAD)]
    recuts = [_step(DIVVYER_RUN, write=(first, queue)), _step(DIVVYER_RUN, write=(second, queue))]
    cfg = _sequenced(cfg, tmp_path, leads, recuts=recuts)
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert len(_runs(tmp_path, "recut")) == 2
    state = State.open(queue, cfg)
    assert state.section("s2").status == "open"
    assert state.section("s2a").from_recut


def test_a_recut_that_keeps_the_section_id_runs_it_on_under_that_id_and_parks_its_second_recut(
    cfg: Config, tmp_path: Path, scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: a section the recut rewrote in place under its own id is not taken as the recut's,
    # so its next RECUT, under a queue naming no design, runs the divvyer again instead of parking
    # with NO_DESIGN (relay-ladder-design.md:58, 61; relay-codex-architect-design.md:64-66).
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    widened = tmp_path / "widened.md"
    widened.write_text(
        "section s1 | lead | steps: 1\n  s1 work, paths widened\nsection s2 | lead | steps: 1\n  s2 work\n"
    )
    scenario(_lines(DONE_LEAD))
    leads = [_step(RECUT_LEAD), _step(RECUT_LEAD), _step(NO_STATUS_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads, recuts=[_step(DIVVYER_RUN, write=(widened, queue))])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert len(_runs(tmp_path, "recut")) == 1
    assert [s.id for s in parse_queue(queue)] == ["s1", "s2"]
    state = State.open(queue, cfg)
    kept = state.section("s1")
    assert kept.from_recut
    assert kept.status == "parked"
    assert kept.question is not None and NO_DESIGN in kept.question
    assert kept.failures == 0
    assert "s1 work, paths widened" in str(_runs(tmp_path, "lead")[1]["prompt"])
    assert not state.section("s2").from_recut


def test_a_recut_that_leaves_the_section_entry_unchanged_does_not_mark_it_and_recuts_it_again(
    cfg: Config, tmp_path: Path, scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: a recut that keeps the section's id but not its entry changed (only the blank
    # lines trailing it differ) marks it as the recut's, so its next RECUT parks as "no design to
    # amend" instead of running the divvyer again at rung 1.
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    added = tmp_path / "added.md"
    added.write_text(
        "section s1 | lead | steps: 1\n  s1 work\n\n\n"
        "section s1a | lead | steps: 1\n  s1a work\n"
        "section s2 | lead | steps: 1\n  s2 work\n"
    )
    split = _queue_of(tmp_path / "split.md", "s1b", "s1a", "s2")
    scenario(_lines(DONE_LEAD))
    leads = [_step(RECUT_LEAD), _step(RECUT_LEAD), _step(NO_STATUS_LEAD), _step(NO_STATUS_LEAD)]
    recuts = [_step(DIVVYER_RUN, write=(added, queue)), _step(DIVVYER_RUN, write=(split, queue))]
    cfg = _sequenced(cfg, tmp_path, leads, recuts=recuts)
    run(queue, cfg)
    assert len(_runs(tmp_path, "recut")) == 2
    state = State.open(queue, cfg)
    assert not state.section("s1").from_recut
    assert state.section("s1a").from_recut
    assert state.section("s1b").from_recut
    assert not state.section("s2").from_recut


def test_a_recut_that_splits_the_section_runs_the_child_ids_and_leaves_the_old_id_behind(
    cfg: Config, tmp_path: Path, scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: after a real split the old id is still run or marked, or a child id is not the recut's.
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    # relay-check-design.md:297: a split makes flat siblings, `s1` giving `s1a`, `s1b`.
    split = _queue_of(tmp_path / "split.md", "s1a", "s1b", "s2")
    scenario(_lines(DONE_LEAD))
    leads = [_step(RECUT_LEAD), _step(DONE_LEAD), _step(NO_STATUS_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads, recuts=[_step(DIVVYER_RUN, write=(split, queue))])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    state = State.open(queue, cfg)
    assert state.section("s1a").from_recut and state.section("s1a").status == "done"
    assert state.section("s1b").from_recut
    assert not state.section("s1").from_recut
    assert "Section: s1a" in str(_runs(tmp_path, "lead")[1]["prompt"])
    assert "Section: s1b" in str(_runs(tmp_path, "lead")[2]["prompt"])


# Behavior 4 (s7.d3): - NEEDS-OWNER: `park`, then `ping.needs_owner`.


def test_needs_owner_parks_the_section_with_its_question_and_the_loop_goes_on(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: NEEDS-OWNER does not park, parks without the question, or counts a failure.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    ids = _open_ids(queue)
    # The workboard queue gives no section a dependency, so parking s1.1.1 blocks nothing and
    # the next section in queue order runs.
    expected = "s1.1.2"
    cfg = _sequenced(cfg, tmp_path, [_step(NEEDS_OWNER_LEAD), _step(NO_STATUS_LEAD)])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    section = State.open(queue, cfg).section(ids[0])
    assert section.status == "parked"
    assert section.question == QUESTION
    assert section.failures == 0
    assert _ran_on(queue, cfg, "sess-lead-2") == {expected}


def test_needs_owner_pings_the_owner_with_the_question_once_the_section_is_parked(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop sends no needs-owner ping, or pings before it parks the section.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    sid = _open_ids(queue)[0]
    record = tmp_path / "pings.jsonl"
    ping = [sys.executable, "-c", _RECORD_STATE, str(REPO), str(record), str(queue), str(cfg.state_root), sid, "{message}"]
    cfg = dataclasses.replace(cfg, ping_command=ping)
    cfg = _sequenced(cfg, tmp_path, [_step(NEEDS_OWNER_LEAD), _step(NO_STATUS_LEAD)])
    run(queue, cfg)
    asked = [p for p in _pings(tmp_path) if QUESTION in p[0]]
    assert len(asked) == 1
    message, status = asked[0]
    assert message.startswith("relay ")
    assert status == "parked"


# Behavior 5 (s7.d3): - A missing status, non-zero exit or kill: `record_failure`. A second
# failure stops with `FAILED_TWICE`.


def test_a_lead_with_no_status_line_records_one_failure_and_the_section_is_run_again(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: a missing status records no failure, or stops at the first failure.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    cfg = _sequenced(cfg, tmp_path, [_step(NO_STATUS_LEAD), _step(DONE_SMALL_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    section = State.open(queue, cfg).section(first)
    assert section.failures == 1
    assert section.status == "done"


def test_a_lead_ending_done_with_a_non_zero_exit_records_a_failure(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop reads the status line and ignores the lead's exit code.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD, exit=1), _step(DONE_SMALL_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    section = State.open(queue, cfg).section(first)
    assert section.failures == 1
    assert section.last_session == "sess-lead-6"


def test_two_leads_ending_done_with_a_non_zero_exit_stop_with_failed_twice(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: a non-zero exit with a DONE line marks the section done.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD, exit=1)])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    section = State.open(queue, cfg).section(first)
    assert section.failures == 2
    assert section.status == "open"


def test_a_killed_lead_records_one_failure(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: a kill at hard_ceiling records no failure.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    cfg = dataclasses.replace(cfg, context_limit=FIRST_CONTEXT - 200, hard_ceiling=FIRST_CONTEXT)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD), _step(DONE_SMALL_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    section = State.open(queue, cfg).section(first)
    assert section.failures == 1
    assert section.status == "done"


def test_a_second_failure_stops_with_failed_twice_and_runs_no_further_lead(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop goes on past the section's second failure.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    ids = _open_ids(queue)
    cfg = _sequenced(cfg, tmp_path, [_step(NO_STATUS_LEAD)])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert len(_runs(tmp_path, "lead")) == 2
    assert _ran_on(queue, cfg, "sess-lead-2") == {ids[0]}
    section = State.open(queue, cfg).section(ids[0])
    assert section.failures == 2
    assert section.status == "open"


def test_one_failure_in_each_of_several_sections_does_not_stop_the_loop(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop counts failures across sections instead of per section.
    queue = queue_file(M2)
    scenario(_lines(DONE_LEAD))
    ids = _open_ids(queue)
    cfg = _sequenced(cfg, tmp_path, [_step(NO_STATUS_LEAD), _step(DONE_LEAD)], cycle=True)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    state = State.open(queue, cfg)
    assert all(state.section(sid).failures == 1 for sid in ids)
    assert all(state.section(sid).status == "done" for sid in ids)


def test_a_failure_recorded_before_this_go_counts_toward_the_second(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop counts only the failures of this `relay go` in memory.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    State.open(queue, cfg).record_failure(first)
    cfg = _sequenced(cfg, tmp_path, [_step(NO_STATUS_LEAD), _step(DONE_SMALL_LEAD)])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert len(_runs(tmp_path, "lead")) == 1


# Behavior 6 (s7.d3): After a budget-triggered retire, the pass ends with `BUDGET`. Every stop
# calls `ping.stopped` before returning.


# In RETIRED_LEAD, the assistant message (line 1) brings the live spend to RETIRED_SPEND.tokens,
# and the result (line 2) brings its dollars to RETIRED_SPEND.dollars: the shim watches for the
# retire flag after the line that passes each budget.
@pytest.mark.parametrize(
    ("budget", "split"),
    [({"token_budget": RETIRED_SPEND.tokens - 1}, 2), ({"dollar_budget": 0.1}, 3)],
    ids=["tokens", "dollars"],
)
def test_a_budget_triggered_retire_ends_the_pass_with_budget_and_runs_no_fresh_lead(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    budget: dict[str, object],
    split: int,
) -> None:
    # Breaks when: a lead retired on budget is followed by a fresh lead like any RETIRED, or by
    # a next pass; or when on_event never retires the lead on its live spend.
    queue = queue_file(WORKBOARD)
    scenario(_lines(RETIRED_LEAD))
    _only_first_open(queue, cfg)
    cfg = dataclasses.replace(cfg, **budget)
    # The lead creates the stop file as it starts: a next pass would stop at step 1 with
    # STOP_FILE, so only the pass ending on the budget-triggered retire returns BUDGET.
    stop_file = State.open(queue, cfg).stop_file
    cfg = _shimmed(cfg, tmp_path, split=split, touch=stop_file)
    assert run(queue, cfg) == ExitCode.BUDGET
    assert _shimmed_runs(tmp_path) == 1
    assert _record(tmp_path, 0)["appeared"] != []


def test_a_context_triggered_retire_does_not_end_the_pass_with_budget(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop ends with BUDGET after any retire, not only a budget-triggered one.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    _only_first_open(queue, cfg)
    cfg = dataclasses.replace(cfg, context_limit=RETIRED_CONTEXT)
    cfg = _sequenced(cfg, tmp_path, [_step(RETIRED_LEAD), _step(DONE_SMALL_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert len(_runs(tmp_path, "lead")) == 2


def _stop_on(kind: str, queue: Path, cfg: Config) -> Config:
    """Set up state so that `run` stops with `kind`; return the config to run with."""
    state = State.open(queue, cfg)
    if kind == "stop-file":
        state.stop_file.touch()
    elif kind == "budget":
        cfg = dataclasses.replace(cfg, token_budget=1000)
        _ledger_line(state, time.time() + 3600, 1001, 0.0)
    elif kind == "queue-empty":
        for sid in _open_ids(queue):
            state.mark_done(sid)
    return cfg


@pytest.mark.parametrize(
    ("kind", "code", "lead"),
    [
        ("stop-file", ExitCode.STOP_FILE, DONE_LEAD),
        ("budget", ExitCode.BUDGET, DONE_LEAD),
        ("queue-empty", ExitCode.QUEUE_EMPTY, DONE_LEAD),
        ("failed-twice", ExitCode.FAILED_TWICE, NO_STATUS_LEAD),
    ],
    ids=["stop-file", "budget", "queue-empty", "failed-twice"],
)
def test_every_stop_sends_one_stopped_ping_before_run_returns(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    kind: str,
    code: int,
    lead: str,
) -> None:
    # Breaks when: a stop returns without calling ping.stopped.
    queue = queue_file(WORKBOARD)
    scenario(_lines(lead))
    cfg = _stop_on(kind, queue, cfg)
    assert run(queue, cfg) == code
    pings = _pings(tmp_path)
    assert len(pings) == 1
    assert pings[0][0].startswith("relay ")


def test_a_budget_triggered_retire_sends_one_stopped_ping(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the BUDGET stop after a live-spend retire skips ping.stopped.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    _only_first_open(queue, cfg)
    cfg = dataclasses.replace(cfg, token_budget=RETIRED_SPEND.tokens - 1)
    cfg = _sequenced(cfg, tmp_path, [_step(RETIRED_LEAD)])
    assert run(queue, cfg) == ExitCode.BUDGET
    assert len(_pings(tmp_path)) == 1
    assert _pings(tmp_path)[0][0].startswith("relay ")


def test_a_stop_file_while_waiting_sends_one_stopped_ping(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the STOP_FILE stop from the wait returns without calling ping.stopped.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    state = _park_all_but_done(queue, cfg, _open_ids(queue)[0])
    loop = _Background(queue, cfg)
    try:
        loop.wait_for_pass()
        assert loop.still_running()
        State.open(queue, cfg).stop_file.touch()
        assert loop.finish(timeout=5.0) == ExitCode.STOP_FILE
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    pings = _pings(tmp_path)
    assert len(pings) == 1
    assert pings[0][0].startswith("relay ")


def _stopped_message(cfg: Config, base: Path, variant: str, scenario: Callable[[list[str]], Path]) -> str:
    """Run the WORKBOARD queue, in a directory of its own under `base`, to the stop `variant`
    names, and return its one stopped ping with that directory's path written as `<dir>`."""
    where = base / variant
    where.mkdir()
    queue = where / WORKBOARD
    queue.write_bytes((FIXTURES / WORKBOARD).read_bytes())
    record = where / "pings.jsonl"
    cfg = dataclasses.replace(
        cfg,
        state_root=where / "state",
        ping_command=[sys.executable, "-c", _RECORD, str(record), "{message}"],
    )
    if variant == "budget-retire":
        _only_first_open(queue, cfg)
        cfg = dataclasses.replace(cfg, token_budget=RETIRED_SPEND.tokens - 1)
        assert run(queue, _sequenced(cfg, where, [_step(RETIRED_LEAD)])) == ExitCode.BUDGET
    elif variant == "stop-file-waiting":
        scenario(_lines(DONE_LEAD))
        state = _park_all_but_done(queue, cfg, _open_ids(queue)[0])
        loop = _Background(queue, cfg)
        try:
            loop.wait_for_pass()
            assert loop.still_running()
            state.stop_file.touch()
            assert loop.finish(timeout=5.0) == ExitCode.STOP_FILE
        finally:
            state.stop_file.touch()
            loop.thread.join(15)
    else:
        codes = {"stop-file": ExitCode.STOP_FILE, "budget": ExitCode.BUDGET,
                 "queue-empty": ExitCode.QUEUE_EMPTY, "failed-twice": ExitCode.FAILED_TWICE}
        scenario(_lines(NO_STATUS_LEAD if variant == "failed-twice" else DONE_LEAD))
        assert run(queue, _stop_on(variant, queue, cfg)) == codes[variant]
    pings = _pings(where)
    assert len(pings) == 1, (variant, pings)
    message = pings[0][0]
    assert message.startswith("relay "), message
    for path in {str(where.resolve()), str(where)}:
        message = message.replace(path, "<dir>")
    return message


def test_each_kind_of_stop_sends_a_stopped_ping_unlike_every_other_kinds(
    cfg: Config, tmp_path: Path, scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: ping.stopped is called with one reason for every stop, or two kinds of stop
    # share one, so the owner cannot tell from the ping why Relay stopped.
    kinds = {
        "stop-file": ["stop-file", "stop-file-waiting"],
        "budget": ["budget", "budget-retire"],
        "queue-empty": ["queue-empty"],
        "failed-twice": ["failed-twice"],
    }
    messages = {kind: [_stopped_message(cfg, tmp_path, v, scenario) for v in variants] for kind, variants in kinds.items()}
    for kind, mine in messages.items():
        for other, theirs in messages.items():
            if other != kind:
                assert not set(mine) & set(theirs), (kind, mine, other, theirs)


# Progress lines (design `relay-progress-design.md`, Modules: `relay/loop.py` calls these).
# Each test reads what `run` wrote with `capsys` and matches each line after its `HH:MM:SS `
# prefix. A test that must see where a call falls among the lines wraps that call so it writes
# a marker line of its own, which carries no such prefix.

_STAMP = re.compile(r"(\d{2}):(\d{2}):(\d{2}) (.*)")
_STARTED = r"relay go .+: started; .+"

# Every line `relay/progress.py` words, as the design gives it.
_PROGRESS = [
    re.compile(_STARTED),
    re.compile(r"lead \S+: started(?: fresh|, resuming \S+)(?:, with the owner's answer)?"),
    re.compile(r"lead \S+: finished .+ \(\d+ tokens, \$\d+\.\d{2}\)"),
    re.compile(r"lead \S+: asked to retire(?: at \d+ context tokens|, budget spent)"),
    re.compile(r"lead \S+: killed at \d+ context tokens, past the hard ceiling"),
    re.compile(r"(?:lead|recut) \S+: agent \S+ (?:started|\S+ (?:in \S+|time unknown), context \d+): .+ \((?:lead|recut) \+ \d+ agents?\)"),
    re.compile(r"recut \S+: started: .+"),
    re.compile(r"recut \S+: finished .+ \(\d+ tokens, \$\d+\.\d{2}\)"),
    re.compile(r"section \S+: needs an answer: .+"),
    re.compile(r"section \S+: failed \(\d+ of 2\)"),
    re.compile(r"waiting for answers on .+"),
    re.compile(r"relay go .+: ended .+: .* \(exit \d+\)"),
    # relay-check-design.md:219-220: `check_started` and `check_finished`.
    re.compile(r"check \S+: running \d+ (?:checks?|check\(s\)) in .+"),
    re.compile(r"check \S+: (?:passed|failed: .+|timed out.*|outside the code: .+|none to run)"),
]


def _texts(out: str) -> list[str]:
    """Each line of `out`: a progress line cut to what follows its `HH:MM:SS ` prefix, a marker kept whole."""
    texts = []
    for line in out.splitlines():
        stamped = _STAMP.fullmatch(line)
        texts.append(stamped.group(4) if stamped else line)
    return texts


def _failed(texts: list[str]) -> list[str]:
    return [t for t in texts if t.startswith("section ") and ": failed (" in t]


def _mark(
    monkeypatch: pytest.MonkeyPatch, owner: object, name: str, marker: str, before: bool = False
) -> list[inspect.BoundArguments]:
    """Wrap `owner.name` so each call writes `marker` as a line of its own to stdout, before the
    call when `before`, else after it; return the list each call's bound arguments go to."""
    original = getattr(owner, name)
    calls: list[inspect.BoundArguments] = []

    def wrapped(*args: object, **kwargs: object) -> object:
        calls.append(inspect.signature(original).bind(*args, **kwargs))
        if before:
            sys.stdout.write(marker + "\n")
        result = original(*args, **kwargs)
        if not before:
            sys.stdout.write(marker + "\n")
        return result

    monkeypatch.setattr(owner, name, wrapped)
    return calls


def _every_run_agent(
    monkeypatch: pytest.MonkeyPatch, replace: Callable[[Callable[..., object]], Callable[..., object]]
) -> None:
    """Put `replace(run_agent)` in place of `relay.runner.run_agent` in every loaded `relay`
    module that holds it, `relay.runner` itself included, so the stand-in is what runs however
    `relay/loop.py` reaches `run_agent`: through its own name for it or through `relay.runner`."""
    original = relay.runner.run_agent
    stand_in = replace(original)
    for name, module in list(sys.modules.items()):
        if (name == "relay" or name.startswith("relay.")) and getattr(module, "run_agent", None) is original:
            monkeypatch.setattr(module, "run_agent", stand_in)


def _mark_run_agent(monkeypatch: pytest.MonkeyPatch, marker: str) -> list[inspect.BoundArguments]:
    """Write `marker` as a line of its own to stdout just before each `run_agent` call, however
    `relay/loop.py` reaches it; return the list each call's bound arguments go to."""
    calls: list[inspect.BoundArguments] = []

    def replace(original: Callable[..., object]) -> Callable[..., object]:
        def wrapped(*args: object, **kwargs: object) -> object:
            calls.append(inspect.signature(original).bind(*args, **kwargs))
            sys.stdout.write(marker + "\n")
            return original(*args, **kwargs)

        return wrapped

    _every_run_agent(monkeypatch, replace)
    return calls


# Progress behavior 1: `relay/loop.py` calls these, and nothing else in it writes to the
# terminal; the lines of a whole `relay go` come in the order the run produced them.

# In NEEDS_OWNER_LEAD, one assistant message and a result of 0.0333 dollars.
NEEDS_OWNER_SPEND = Spend(tokens=2 + 100 + 800 + 15, dollars=0.0333)


def _running(sid: str, count: int, cwd: Path, literal: bool) -> str:
    """A `check_started` line: relay-check-design.md:219 words it "check <sid>: running <n>
    check(s) in <cwd>", read either as that literal "check(s)" or with the noun counted, as
    tests/test_progress.py's check_started test reads it."""
    noun = "check(s)" if literal else ("check" if count == 1 else "checks")
    return f"check {sid}: running {count} {noun} in {cwd}"


def _finished(spend: Spend) -> str:
    """The `(<tokens> tokens, $<dollars>)` tail of a finished line, for the spends used here,
    whose dollars each round to two places without a tie."""
    return f"({spend.tokens} tokens, ${spend.dollars:.2f})"


def test_a_go_writes_each_progress_line_in_the_order_the_run_produced_it_worded_with_its_outcome(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a line is missing, repeated or out of the run's order; a finished line
    # carries another outcome than the lead's (DONE, the RECUT reason, NEEDS-OWNER, no status
    # line); the lead given the owner's answer does not say so; or the loop writes a line of
    # its own, or to stderr.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    a, b, c = _open_ids(queue)[:3]
    state = State.open(queue, cfg)
    for sid in [s.id for s in parse_queue(queue)]:
        if sid not in (a, b, c):
            state.mark_done(sid)
    # a: no status line, then DONE. b: RECUT, whose recut leaves the queue unchanged, then
    # NEEDS-OWNER. c: DONE, leaving only b parked, so the loop waits. b, answered: DONE.
    leads = [
        _step(NO_STATUS_LEAD),
        _step(DONE_LEAD),
        _step(RECUT_LEAD),
        _step(NEEDS_OWNER_LEAD),
        _step(DONE_LEAD),
        _step(DONE_LEAD),
    ]
    cfg = _sequenced(cfg, tmp_path, leads, recuts=[_step(DIVVYER_RUN)])
    stops = _mark(monkeypatch, relay.ping, "stopped", "<ping.stopped>")
    loop = _Background(queue, cfg)
    try:
        _until(lambda: State.open(queue, cfg).section(c).status == "done")
        loop.wait_for_pass()
        assert loop.still_running()
        State.open(queue, cfg).set_answer(b, "Use port 8080.")
        assert loop.finish() == ExitCode.QUEUE_EMPTY
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    captured = capsys.readouterr()
    assert captured.err == ""
    for line in captured.out.splitlines():
        if line == "<ping.stopped>":
            continue
        stamped = _STAMP.fullmatch(line)
        assert stamped is not None, line
        hours, minutes, seconds = (int(stamped.group(n)) for n in (1, 2, 3))
        assert hours < 24 and minutes < 60 and seconds < 60, line
        assert any(p.fullmatch(stamped.group(4)) for p in _PROGRESS), line
    assert len(stops) == 1
    reason, detail = stops[0].arguments["reason"], stops[0].arguments["detail"]
    name = queue.name
    # relay-check-design.md:244-247 and 219-220: each DONE runs the section's checks in the queue's
    # git top level (no section worktree here); the WORKBOARD fixture gives section a one
    # done-check, b none and c three, all of which `cfg` makes pass. b has no check line, so
    # `check_finished` reports "none to run"; the design does not say whether `check_started`
    # comes before it with 0, so its "running 0 checks" line is allowed, not required. Each
    # `check_started` line takes one reading of the design's "check(s)" wording, the same in all.
    top = tmp_path.resolve()

    def head(literal: bool) -> list[str]:
        return [
            f"relay go {name}: started; no token budget, no dollar budget",
            f"lead {a}: started fresh",
            f"lead {a}: finished with no status line {_finished(NO_STATUS_SPEND)}",
            f"section {a}: failed (1 of 2)",
            f"lead {a}: started, resuming sess-lead-2",
            f"lead {a}: finished DONE {_finished(DONE_SPEND)}",
            _running(a, 1, top, literal),
            f"check {a}: passed",
            f"lead {b}: started, resuming sess-lead-1",
            f"lead {b}: finished RECUT: {RECUT_REASON} {_finished(RECUT_SPEND)}",
            f"recut {b}: started: {RECUT_REASON}",
            f"recut {b}: finished with the queue unchanged {_finished(DIVVYER_SPEND)}",
            f"section {b}: failed (1 of 2)",
            f"lead {b}: started, resuming sess-lead-4",
            f"lead {b}: finished NEEDS-OWNER {_finished(NEEDS_OWNER_SPEND)}",
            f"section {b}: needs an answer: {QUESTION}",
            f"lead {c}: started, resuming sess-lead-5",
            f"lead {c}: finished DONE {_finished(DONE_SPEND)}",
            _running(c, 3, top, literal),
            f"check {c}: passed",
            f"waiting for answers on {b}",
            f"lead {b}: started, resuming sess-lead-5, with the owner's answer",
            f"lead {b}: finished DONE {_finished(DONE_SPEND)}",
        ]

    tail = [
        "<ping.stopped>",
        f"relay go {name}: ended {reason}: {detail} (exit {int(ExitCode.QUEUE_EMPTY)})",
    ]
    assert _texts(captured.out) in [
        expected
        for literal in (False, True)
        for expected in (
            [*head(literal), _running(b, 0, top, literal), f"check {b}: none to run", *tail],
            [*head(literal), f"check {b}: none to run", *tail],
        )
    ]


AGENTS_LEAD = "stream-agents.jsonl"  # "DONE", session "sess-agents-1", two subagents and a shell task


def test_a_lead_run_writes_one_line_per_subagent_start_and_finish_between_its_started_and_finished_lines(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the loop drops, repeats or reorders an agent line, prints one for a shell
    # task, or prints them outside the lead's own started and finished lines.
    queue = queue_file(WORKBOARD)
    scenario(_lines(AGENTS_LEAD))
    sid = _only_first_open(queue, cfg)
    cfg = _sequenced(cfg, tmp_path, [_step(AGENTS_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    texts = _texts(capsys.readouterr().out)
    start = texts.index(f"lead {sid}: started fresh")
    assert texts[start + 1 : start + 5] == [
        f"lead {sid}: agent builder started: Build s2.d1 stub (lead + 1 agent)",
        f"lead {sid}: agent test-writer started: s2.d2 red tests (lead + 2 agents)",
        f"lead {sid}: agent builder completed in 36.9s, context 21844: Build s2.d1 stub (lead + 1 agent)",
        f"lead {sid}: agent test-writer failed in 1m35s, context 41000: s2.d2 red tests (lead + 0 agents)",
    ]
    assert texts[start + 5].startswith(f"lead {sid}: finished DONE ")


# Progress behavior 2: `run` calls `progress.started` after `state.lock()` succeeds, and
# `progress.ended` after each `ping.stopped`.


def test_started_is_written_first_once_the_lock_is_taken_and_not_when_another_go_holds_it(
    cfg: Config,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: run writes the started line before it takes the lock, or never writes it.
    scenario(_lines(DONE_LEAD))
    held = queue_file(M2)
    holder = State.open(held, cfg)
    holder.lock()
    try:
        run(held, cfg)
    except LockedError:
        pass
    assert not any(re.fullmatch(_STARTED, t) for t in _texts(capsys.readouterr().out))
    free = queue_file(WORKBOARD)
    state = State.open(free, cfg)
    for sid in _open_ids(free):
        state.mark_done(sid)
    assert run(free, cfg) == ExitCode.QUEUE_EMPTY
    texts = _texts(capsys.readouterr().out)
    assert texts != []
    assert re.fullmatch(_STARTED, texts[0]), texts
    assert len([t for t in texts if re.fullmatch(_STARTED, t)]) == 1


@pytest.mark.parametrize(
    ("kind", "code", "lead"),
    [
        ("stop-file", ExitCode.STOP_FILE, DONE_LEAD),
        ("budget", ExitCode.BUDGET, DONE_LEAD),
        ("queue-empty", ExitCode.QUEUE_EMPTY, DONE_LEAD),
        ("failed-twice", ExitCode.FAILED_TWICE, NO_STATUS_LEAD),
        ("budget-retire", ExitCode.BUDGET, DONE_LEAD),
    ],
    ids=["stop-file", "budget", "queue-empty", "failed-twice", "budget-retire"],
)
def test_ended_is_the_last_line_written_just_after_the_stopped_ping_with_its_reason_and_detail(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    kind: str,
    code: int,
    lead: str,
) -> None:
    # Breaks when: a stop writes no ended line, writes it before ping.stopped, or words it
    # with another reason, detail or exit code than the stop's.
    queue = queue_file(WORKBOARD)
    scenario(_lines(lead))
    if kind == "budget-retire":
        _only_first_open(queue, cfg)
        cfg = dataclasses.replace(cfg, token_budget=RETIRED_SPEND.tokens - 1)
        cfg = _sequenced(cfg, tmp_path, [_step(RETIRED_LEAD)])
    else:
        cfg = _stop_on(kind, queue, cfg)
    stops = _mark(monkeypatch, relay.ping, "stopped", "<ping.stopped>")
    assert run(queue, cfg) == code
    texts = _texts(capsys.readouterr().out)
    assert len(stops) == 1
    assert len(_pings(tmp_path)) == 1
    reason, detail = stops[0].arguments["reason"], stops[0].arguments["detail"]
    ended = [t for t in texts if re.fullmatch(r"relay go .+: ended .+", t)]
    assert len(ended) == 1, texts
    assert texts[-2:] == ["<ping.stopped>", ended[0]], texts
    expected = re.escape(f"{reason}: {detail} (exit {int(code)})")
    assert re.fullmatch(r"relay go .+: ended " + expected, ended[0]), ended


def test_a_stop_file_while_waiting_writes_ended_just_after_the_stopped_ping(
    cfg: Config,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the STOP_FILE stop from the wait returns with no ended line after its ping.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    stops = _mark(monkeypatch, relay.ping, "stopped", "<ping.stopped>")
    state = _park_all_but_done(queue, cfg, _open_ids(queue)[0])
    loop = _Background(queue, cfg)
    try:
        loop.wait_for_pass()
        assert loop.still_running()
        State.open(queue, cfg).stop_file.touch()
        assert loop.finish(timeout=5.0) == ExitCode.STOP_FILE
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    texts = _texts(capsys.readouterr().out)
    assert len(stops) == 1
    reason, detail = stops[0].arguments["reason"], stops[0].arguments["detail"]
    assert texts[-2:-1] == ["<ping.stopped>"], texts
    expected = re.escape(f"{reason}: {detail} (exit {int(ExitCode.STOP_FILE)})")
    assert re.fullmatch(r"relay go .+: ended " + expected, texts[-1]), texts


# Progress behavior 2a: the started and ended lines name the queue file `relay go` was given
# and the budgets its config holds, or that there is none.


def _all_done(queue: Path, cfg: Config) -> None:
    state = State.open(queue, cfg)
    for sid in _open_ids(queue):
        state.mark_done(sid)


@pytest.mark.parametrize("name", [WORKBOARD, M2])
def test_started_and_ended_name_the_queue_file_relay_go_was_given(
    name: str,
    cfg: Config,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: started or ended names another queue than the one run was given, or none.
    queue = queue_file(name)
    scenario(_lines(DONE_LEAD))
    _all_done(queue, cfg)
    stops = _mark(monkeypatch, relay.ping, "stopped", "<ping.stopped>")
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    texts = _texts(capsys.readouterr().out)
    assert len(stops) == 1
    reason, detail = stops[0].arguments["reason"], stops[0].arguments["detail"]
    assert texts == [
        f"relay go {name}: started; no token budget, no dollar budget",
        "<ping.stopped>",
        f"relay go {name}: ended {reason}: {detail} (exit {int(ExitCode.QUEUE_EMPTY)})",
    ]


@pytest.mark.parametrize(
    ("budgets", "wording"),
    [
        ({}, r"no token budget, no dollar budget"),
        ({"token_budget": 900}, r"budget 900 tokens, no dollar budget"),
        ({"dollar_budget": 2.5}, r"no token budget, \$2\.50?"),
        ({"token_budget": 900, "dollar_budget": 2.5}, r"budget 900 tokens, \$2\.50?"),
    ],
    ids=["none", "tokens", "dollars", "both"],
)
def test_started_names_the_budgets_the_config_holds_or_that_there_is_none(
    cfg: Config,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
    budgets: dict[str, object],
    wording: str,
) -> None:
    # Breaks when: started leaves out a budget the config holds, names one it does not hold,
    # or gives another amount than the config's.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    _all_done(queue, cfg)
    cfg = dataclasses.replace(cfg, **budgets)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    texts = _texts(capsys.readouterr().out)
    started = [t for t in texts if re.fullmatch(_STARTED, t)]
    assert len(started) == 1, texts
    assert re.fullmatch(re.escape(f"relay go {WORKBOARD}: started; ") + wording, started[0]), started


# Progress behavior 2b: a crash in the loop also writes the ended line, with reason `crashed`
# and code `ExitCode.ERROR`, just after its stopped ping.


def test_a_crash_in_a_leads_run_writes_ended_crashed_with_exit_error_just_after_its_stopped_ping(
    cfg: Config,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the crash path writes no ended line, writes it before its stopped ping, or
    # words it with another reason or exit code, whether loop.py calls run_agent by its own
    # name for it or through relay.runner.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))

    def replace(original: Callable[..., object]) -> Callable[..., object]:
        def crash(*args: object, **kwargs: object) -> object:
            raise RuntimeError("the runner broke")

        return crash

    _every_run_agent(monkeypatch, replace)
    stops = _mark(monkeypatch, relay.ping, "stopped", "<ping.stopped>")
    try:
        run(queue, cfg)
    except RuntimeError:
        pass
    texts = _texts(capsys.readouterr().out)
    assert len(stops) == 1
    ended = [t for t in texts if re.fullmatch(r"relay go .+: ended .+", t)]
    assert len(ended) == 1, texts
    assert texts[-2:] == ["<ping.stopped>", ended[0]], texts
    wanted = re.escape(f"relay go {WORKBOARD}: ended crashed: ") + r".*" + re.escape(f" (exit {int(ExitCode.ERROR)})")
    assert re.fullmatch(wanted, ended[0]), ended


# Progress behavior 3: `_run_section` calls `progress.lead_started` just before `run_agent`.


def test_lead_started_naming_each_section_is_written_just_before_its_leads_run_however_the_loop_reaches_run_agent(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the lead_started line is written once per go or per pass instead of just
    # before each section's run_agent, names the section of an earlier or later lead, or is
    # missing when loop.py calls run_agent through relay.runner rather than its own name.
    queue = queue_file(M2)
    scenario(_lines(DONE_LEAD))
    ids = _open_ids(queue)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD)])
    runs = _mark_run_agent(monkeypatch, "<run_agent>")
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    texts = _texts(capsys.readouterr().out)
    assert len(runs) == len(ids)
    assert len(_runs(tmp_path, "lead")) == len(ids)
    at = [n for n, t in enumerate(texts) if t == "<run_agent>"]
    assert len(at) == len(ids), texts
    expected = [f"lead {ids[0]}: started fresh"] + [f"lead {sid}: started, resuming sess-lead-1" for sid in ids[1:]]
    assert [texts[n - 1] for n in at] == expected, texts
    assert [t for t in texts if t.startswith("lead ") and ": started" in t] == expected, texts


def test_lead_started_is_written_just_before_each_lead_runs_however_the_loop_reaches_run_agent(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a lead runs with no lead_started line just before it, the line names another
    # section or session, or a lead_started line is written for no run, whether loop.py calls
    # run_agent by its own name for it or through relay.runner.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    cfg = _sequenced(cfg, tmp_path, [_step(RETIRED_LEAD), _step(DONE_SMALL_LEAD)])
    runs = _mark_run_agent(monkeypatch, "<run_agent>")
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    texts = _texts(capsys.readouterr().out)
    assert len(runs) == 2
    assert len(_runs(tmp_path, "lead")) == 2
    at = [n for n, t in enumerate(texts) if t == "<run_agent>"]
    assert len(at) == 2, texts
    assert texts[at[0] - 1] == f"lead {first}: started fresh", texts
    assert texts[at[1] - 1] == f"lead {first}: started, resuming sess-lead-3", texts
    assert len([t for t in texts if t.startswith("lead ") and ": started" in t]) == 2


def test_lead_started_comes_just_before_the_lead_that_asks_for_a_recut_and_recut_started_before_the_recut(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: lead_started is written for the recut's run_agent too, or not just before
    # each lead's; or recut_started is not written between the lead's run and the recut's,
    # whether loop.py calls run_agent by its own name for it or through relay.runner.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    cfg = _sequenced(cfg, tmp_path, [_step(RECUT_LEAD), _step(DONE_SMALL_LEAD)], recuts=[_step(DIVVYER_RUN)])
    runs = _mark_run_agent(monkeypatch, "<run_agent>")
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    texts = _texts(capsys.readouterr().out)
    assert len(runs) == 3
    assert len(_runs(tmp_path, "lead")) == 2
    assert len(_runs(tmp_path, "recut")) == 1
    at = [n for n, t in enumerate(texts) if t == "<run_agent>"]
    assert len(at) == 3, texts
    assert texts[at[0] - 1] == f"lead {first}: started fresh", texts
    assert not texts[at[1] - 1].startswith("lead "), texts
    assert texts[at[2] - 1] == f"lead {first}: started, resuming sess-lead-4", texts
    started = f"recut {first}: started: {RECUT_REASON}"
    assert started in texts, texts
    assert at[0] < texts.index(started) < at[1], texts
    assert len([t for t in texts if t.startswith("lead ") and ": started" in t]) == 2


# Progress behavior 4: On `NEEDS-OWNER` it calls `progress.needs_answer` beside `ping.needs_owner`.


def test_needs_owner_writes_needs_an_answer_beside_the_needs_owner_ping(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: NEEDS-OWNER writes no needs-an-answer line, writes it apart from the ping,
    # or the ping no longer goes out.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    sid = _open_ids(queue)[0]
    cfg = _sequenced(cfg, tmp_path, [_step(NEEDS_OWNER_LEAD), _step(NO_STATUS_LEAD)])
    asks = _mark(monkeypatch, relay.ping, "needs_owner", "<ping.needs_owner>")
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    texts = _texts(capsys.readouterr().out)
    assert len(asks) == 1
    assert len([p for p in _pings(tmp_path) if QUESTION in p[0]]) == 1
    needs = [n for n, t in enumerate(texts) if re.fullmatch(r"section \S+: needs an answer: .+", t)]
    assert len(needs) == 1, texts
    assert texts[needs[0]] == f"section {sid}: needs an answer: {QUESTION}"
    assert abs(texts.index("<ping.needs_owner>") - needs[0]) == 1, texts


# Progress behavior 5: On every failure `record_failure` counts, the recut's included, it calls
# `progress.failed` with the new count.


@pytest.mark.parametrize(
    ("failing", "context"),
    [(_step(NO_STATUS_LEAD), None), (_step(DONE_LEAD, exit=1), None), (_step(DONE_LEAD), FIRST_CONTEXT)],
    ids=["no-status-line", "non-zero-exit", "killed"],
)
def test_a_lead_failure_writes_failed_with_the_count_one(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
    failing: dict[str, object],
    context: int | None,
) -> None:
    # Breaks when: a failure record_failure counts writes no failed line, or another count.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    if context is not None:
        cfg = dataclasses.replace(cfg, context_limit=context - 200, hard_ceiling=context)
    cfg = _sequenced(cfg, tmp_path, [failing, _step(DONE_SMALL_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert _failed(_texts(capsys.readouterr().out)) == [f"section {first}: failed (1 of 2)"]


def test_a_second_failure_writes_failed_with_the_count_two(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the failed line carries a count other than record_failure's.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    cfg = _sequenced(cfg, tmp_path, [_step(NO_STATUS_LEAD)])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert _failed(_texts(capsys.readouterr().out)) == [
        f"section {first}: failed (1 of 2)",
        f"section {first}: failed (2 of 2)",
    ]


def test_a_failure_recorded_before_this_go_makes_the_first_failed_line_count_two(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the loop counts this go's failures itself instead of taking record_failure's count.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    State.open(queue, cfg).record_failure(first)
    cfg = _sequenced(cfg, tmp_path, [_step(NO_STATUS_LEAD), _step(DONE_SMALL_LEAD)])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert _failed(_texts(capsys.readouterr().out)) == [f"section {first}: failed (2 of 2)"]


def test_a_recut_that_leaves_the_queue_unchanged_writes_failed_after_the_recut_line(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a recut that changed nothing counts its failure with no failed line.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    cfg = _sequenced(cfg, tmp_path, [_step(RECUT_LEAD), _step(DONE_LEAD)], recuts=[_step(DIVVYER_RUN)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    texts = _texts(capsys.readouterr().out)
    assert _failed(texts) == [f"section {first}: failed (1 of 2)"]
    recut = [n for n, t in enumerate(texts) if t.startswith(f"recut {first}: finished ")]
    assert len(recut) == 1, texts
    assert texts.index(f"section {first}: failed (1 of 2)") > recut[0]


def test_a_recut_with_a_non_zero_exit_writes_failed_with_the_new_count(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a recut's non-zero exit counts a failure with no failed line.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    sid = _open_ids(queue)[0]
    cfg = _recut_to_m2(cfg, tmp_path, queue, exit=1)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert _failed(_texts(capsys.readouterr().out)) == [f"section {sid}: failed (1 of 2)"]


# Progress behavior 6: `_watcher` takes the section id and calls `progress.retiring` the first
# time it returns `retire` in a run and `progress.killing` when it returns `kill`; it never
# repeats a line within one run.


def _between(texts: list[str], line: str, sid: str) -> None:
    """`line` lies after the first `lead <sid>: started` line and before the next `lead <sid>: finished` line."""
    started = next(n for n, t in enumerate(texts) if t.startswith(f"lead {sid}: started"))
    finished = next(n for n, t in enumerate(texts) if n > started and t.startswith(f"lead {sid}: finished "))
    assert started < texts.index(line) < finished, texts


def test_a_context_retire_writes_one_asked_to_retire_line_though_every_later_event_returns_retire(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the watcher writes a retiring line on every event that returns retire, writes
    # none, or names another section or context than the first retire's.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    # Both assistant messages of DONE_LEAD leave context_tokens at or above this limit.
    cfg = dataclasses.replace(cfg, context_limit=7 + 100 + 900)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    texts = _texts(capsys.readouterr().out)
    line = f"lead {first}: asked to retire at {FIRST_CONTEXT} context tokens"
    assert [t for t in texts if ": asked to retire" in t] == [line], texts
    _between(texts, line, first)


def test_a_budget_retire_writes_one_budget_spent_line_though_every_later_event_returns_retire(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the watcher repeats the budget retiring line per event, words it as a context
    # retire, or writes none.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    # The live spend passes this budget at DONE_LEAD's first assistant message and stays past it.
    cfg = dataclasses.replace(cfg, token_budget=FIRST_SPEND - 1)
    assert run(queue, cfg) == ExitCode.BUDGET
    texts = _texts(capsys.readouterr().out)
    line = f"lead {first}: asked to retire, budget spent"
    assert [t for t in texts if ": asked to retire" in t] == [line], texts
    _between(texts, line, first)


def test_each_run_that_retires_writes_its_own_asked_to_retire_line_and_a_run_that_does_not_writes_none(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the first-retire memory outlives its run, so a later run that retires writes
    # no line; or a run that never returns retire writes one.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    cfg = dataclasses.replace(cfg, context_limit=RETIRED_CONTEXT)
    cfg = _sequenced(cfg, tmp_path, [_step(RETIRED_LEAD), _step(RETIRED_LEAD), _step(DONE_SMALL_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    texts = _texts(capsys.readouterr().out)
    line = f"lead {first}: asked to retire at {RETIRED_CONTEXT} context tokens"
    assert [t for t in texts if ": asked to retire" in t] == [line, line], texts
    starts = [n for n, t in enumerate(texts) if t.startswith(f"lead {first}: started")]
    retires = [n for n, t in enumerate(texts) if t == line]
    assert len(starts) == 3, texts
    assert starts[0] < retires[0] < starts[1] < retires[1] < starts[2], texts


def test_a_run_killed_at_the_hard_ceiling_writes_its_killed_line_and_no_asked_to_retire_line(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the watcher writes an asked-to-retire line for a run it kills (the context
    # being past context_limit too), writes no killed line on kill, repeats it, writes it for
    # a run that stays below hard_ceiling, or names another section or context.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    # DONE_LEAD's first assistant message takes context_tokens to FIRST_CONTEXT: past
    # context_limit and at hard_ceiling at once.
    cfg = dataclasses.replace(cfg, context_limit=FIRST_CONTEXT - 200, hard_ceiling=FIRST_CONTEXT)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD), _step(DONE_SMALL_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert len(_runs(tmp_path, "lead")) == 2
    texts = _texts(capsys.readouterr().out)
    line = f"lead {first}: killed at {FIRST_CONTEXT} context tokens, past the hard ceiling"
    watched = [t for t in texts if ": killed at " in t or ": asked to retire" in t]
    assert watched == [line], texts
    _between(texts, line, first)


# Progress behavior 7: `_recut` calls `progress.recut_started` before its `run_agent` and
# `progress.recut_finished` after it.


@pytest.mark.parametrize(
    ("exit", "rewrite", "outcome"),
    [(0, False, "with the queue unchanged"), (0, True, "with the queue recut"), (1, True, "exit 1")],
    ids=["unchanged", "recut", "non-zero-exit"],
)
def test_recut_started_comes_before_the_recuts_run_and_recut_finished_after_it_however_the_loop_reaches_run_agent(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    exit: int,
    rewrite: bool,
    outcome: str,
) -> None:
    # Breaks when: the recut writes no started line before its run_agent, no finished line
    # after it, or a finished line with another outcome or spend than its run's, whether
    # loop.py calls run_agent by its own name for it or through relay.runner.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    recut = _step(DIVVYER_RUN, exit=exit, write=(FIXTURES / M2, queue) if rewrite else None)
    cfg = _sequenced(cfg, tmp_path, [_step(RECUT_LEAD), _step(DONE_SMALL_LEAD)], recuts=[recut])
    runs = _mark_run_agent(monkeypatch, "<run_agent>")
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    texts = _texts(capsys.readouterr().out)
    assert len(_runs(tmp_path, "recut")) == 1
    at = [n for n, t in enumerate(texts) if t == "<run_agent>"]
    assert len(at) == len(runs) >= 3, texts
    started = f"recut {first}: started: {RECUT_REASON}"
    finished = f"recut {first}: finished {outcome} ({DIVVYER_SPEND.tokens} tokens, $0.04)"
    assert [t for t in texts if t.startswith("recut ")] == [started, finished], texts
    assert at[0] < texts.index(started) < at[1] < texts.index(finished) < at[2], texts


# Progress behavior 8: `_loop` calls `progress.waiting` when it enters a wait and the parked
# set differs from the set it last printed; a wait that goes on prints nothing more.

_WAITING = "waiting for answers on "


def _park_two(queue: Path, cfg: Config) -> tuple[State, str, str]:
    """Park the queue's first two open sections and mark every other section done."""
    a, b = _open_ids(queue)[:2]
    state = State.open(queue, cfg)
    for sid in [s.id for s in parse_queue(queue)]:
        if sid not in (a, b):
            state.mark_done(sid)
    state.park(a, QUESTION)
    state.park(b, QUESTION)
    return state, a, b


def _waits(texts: list[str]) -> list[set[str]]:
    """The set of ids each waiting line names, in line order."""
    return [set(t[len(_WAITING) :].split(", ")) for t in texts if t.startswith(_WAITING)]


def test_a_wait_that_goes_on_writes_one_waiting_line_naming_the_parked_section(
    cfg: Config,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the loop writes a waiting line on every poll, or none on entering the wait.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    parked = _open_ids(queue)[0]
    state = _park_all_but_done(queue, cfg, parked)
    loop = _Background(queue, cfg)
    try:
        loop.wait_for_pass()
        assert loop.still_running()
        loop.wait_for_pass()
        assert loop.still_running()
        State.open(queue, cfg).stop_file.touch()
        assert loop.finish(timeout=5.0) == ExitCode.STOP_FILE
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    texts = _texts(capsys.readouterr().out)
    assert [t for t in texts if t.startswith(_WAITING)] == [f"{_WAITING}{parked}"], texts


def test_a_wait_writes_one_waiting_line_naming_each_parked_section_exactly_once(
    cfg: Config,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the waiting line names only some of several parked sections, names one
    # twice, names a section that is not parked, or the wait writes no waiting line.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    parked = _open_ids(queue)[:3]
    state = State.open(queue, cfg)
    for sid in [s.id for s in parse_queue(queue)]:
        if sid not in parked:
            state.mark_done(sid)
    for sid in parked:
        state.park(sid, QUESTION)
    loop = _Background(queue, cfg)
    try:
        loop.wait_for_pass()
        assert loop.still_running()
        State.open(queue, cfg).stop_file.touch()
        assert loop.finish(timeout=5.0) == ExitCode.STOP_FILE
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    texts = _texts(capsys.readouterr().out)
    waiting = [t for t in texts if t.startswith(_WAITING)]
    assert len(waiting) == 1, texts
    assert sorted(waiting[0][len(_WAITING) :].split(", ")) == sorted(parked), waiting


def test_a_new_wait_on_a_changed_parked_set_writes_a_new_waiting_line(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the loop writes the waiting line only on its first wait of the run.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    state, a, b = _park_two(queue, cfg)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_SMALL_LEAD)])
    loop = _Background(queue, cfg)
    try:
        loop.wait_for_pass()
        assert loop.still_running()
        State.open(queue, cfg).set_answer(a, "Use port 8080.")
        _until(lambda: State.open(queue, cfg).section(a).status == "done")
        loop.wait_for_pass()
        assert loop.still_running()
        State.open(queue, cfg).stop_file.touch()
        assert loop.finish(timeout=5.0) == ExitCode.STOP_FILE
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    assert _waits(_texts(capsys.readouterr().out)) == [{a, b}, {b}]


def test_a_new_wait_on_the_parked_set_last_printed_writes_no_waiting_line(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the loop writes a waiting line on every wait it enters, though the parked
    # set is the one it last printed.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    state, a, b = _park_two(queue, cfg)
    # The answered section's lead parks it again with the same question.
    cfg = _sequenced(cfg, tmp_path, [_step(NEEDS_OWNER_LEAD)])
    loop = _Background(queue, cfg)
    try:
        loop.wait_for_pass()
        assert loop.still_running()
        State.open(queue, cfg).set_answer(a, "Use port 8080.")
        _until(lambda: len(_pings(tmp_path)) == 1)
        loop.wait_for_pass()
        assert loop.still_running()
        State.open(queue, cfg).stop_file.touch()
        assert loop.finish(timeout=5.0) == ExitCode.STOP_FILE
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    assert len(_runs(tmp_path, "lead")) == 1
    assert State.open(queue, cfg).section(a).status == "parked"
    texts = _texts(capsys.readouterr().out)
    assert any(t.startswith(f"lead {a}: finished ") for t in texts), texts
    assert _waits(texts) == [{a, b}]


# Progress behavior 9: a progress line never replaces a ping.


def test_every_ping_still_goes_out_beside_its_progress_line(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the loop writes the needs-an-answer or ended line in place of its ping.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _open_ids(queue)[0]
    cfg = _sequenced(cfg, tmp_path, [_step(NEEDS_OWNER_LEAD), _step(NO_STATUS_LEAD)])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    texts = _texts(capsys.readouterr().out)
    assert f"section {first}: needs an answer: {QUESTION}" in texts, texts
    assert any(re.fullmatch(r"relay go .+: ended .+", t) for t in texts), texts
    pings = [p[0] for p in _pings(tmp_path)]
    assert len(pings) == 2, pings
    assert QUESTION in pings[0]
    assert pings[1].startswith("relay ")
    assert not set(pings) & set(texts)


# Check behaviors (relay-check design, Order 7): `_verify` runs a section's checks on the lead's
# `DONE`. The fixture queue's s1 carries two check lines, each running the script that
# `RELAY_CHECK_SCRIPT` names with the argument `first` or `second`; s2 carries none. Each test
# writes that script: it appends "<arg> ran" to `<tmp_path>/checks-ran.txt`, prints
# "check <arg> output", and exits as the test says.

CHECK_QUEUE = "loop-check-queue.md"
FIRST_CHECK = 'sh "$RELAY_CHECK_SCRIPT" first'
FAIL_MARK = "assertion broke at line 7"
FEEDBACK_INTRO = "Relay ran this section's check after your DONE and it failed."


def _script_text(tmp_path: Path, exit: int, extra: str = "") -> str:
    ran = tmp_path / "checks-ran.txt"
    return f'printf "%s ran\\n" "$1" >> "{ran}"\nprintf "check %s output\\n" "$1"\n{extra}exit {exit}\n'


def _check_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit: int, extra: str = "") -> Path:
    """Write the check script, exiting `exit` after printing `extra`, and name it in `RELAY_CHECK_SCRIPT`."""
    script = tmp_path / "check.sh"
    script.write_text(_script_text(tmp_path, exit, extra))
    monkeypatch.setenv("RELAY_CHECK_SCRIPT", str(script))
    return script


def _failing_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return _check_script(tmp_path, monkeypatch, 1, f'echo "{FAIL_MARK}"\n')


def _passing_source(tmp_path: Path) -> Path:
    """A passing check script, for a lead's plan step to copy over the check script."""
    source = tmp_path / "check-pass.sh"
    source.write_text(_script_text(tmp_path, 0))
    return source


def _checks_ran(tmp_path: Path) -> list[str]:
    ran = tmp_path / "checks-ran.txt"
    return ran.read_text().splitlines() if ran.exists() else []


def _check_entries(queue: Path, cfg: Config) -> list[dict[str, object]]:
    """The ledger's check lines, in file order."""
    path = State.open(queue, cfg).stop_file.parent / "ledger.jsonl"
    entries = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [e for e in entries if e.get("kind") == "check"]


def _lead_logs(queue: Path, cfg: Config) -> list[Path]:
    """Each lead's run log, `<run_dir>/<n>.jsonl`, in run order."""
    return sorted(State.open(queue, cfg).run_dir.glob("*.jsonl"), key=lambda p: int(p.stem))


def _done_in_state(queue: Path, cfg: Config, *sids: str) -> None:
    state = State.open(queue, cfg)
    for sid in sids:
        state.mark_done(sid)


# Check behavior 1: a check on `DONE`: pass, fail and resume with the output, the third fail
# parking, outside parking and rerunning on the next pass with no lead, and a section with no check.


def test_a_done_whose_checks_all_pass_marks_the_section_done_after_running_each_check(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when: the loop marks a DONE section done without running its check lines.
    queue = queue_file(CHECK_QUEUE)
    scenario(_lines(DONE_LEAD))
    _done_in_state(queue, cfg, "s2")
    _check_script(tmp_path, monkeypatch, 0)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert _checks_ran(tmp_path) == ["first ran", "second ran"]
    assert len(_runs(tmp_path, "lead")) == 1
    section = State.open(queue, cfg).section("s1")
    assert section.status == "done"
    assert section.check_failures == 0
    assert section.failures == 0


def test_a_failed_check_resumes_the_lead_with_the_checks_output(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when: the next lead after a failed check starts fresh, or its prompt carries no
    # check output, exit code or check log.
    queue = queue_file(CHECK_QUEUE)
    scenario(_lines(DONE_LEAD))
    _done_in_state(queue, cfg, "s2")
    script = _failing_check(tmp_path, monkeypatch)
    leads = [_step(DONE_LEAD), _step(DONE_SMALL_LEAD, write=(_passing_source(tmp_path), script))]
    cfg = _sequenced(cfg, tmp_path, leads)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    runs = _runs(tmp_path, "lead")
    assert len(runs) == 2
    assert FEEDBACK_INTRO not in str(runs[0]["prompt"])
    prompt = str(runs[1]["prompt"])
    assert "resume sess-lead-1" in prompt
    assert FEEDBACK_INTRO in prompt
    feedback = prompt[prompt.index(FEEDBACK_INTRO) :]
    assert FAIL_MARK in feedback
    assert "exit 1" in feedback
    assert str(State.open(queue, cfg).check_log(_lead_logs(queue, cfg)[0])) in feedback
    section = State.open(queue, cfg).section("s1")
    assert section.status == "done"
    assert section.failures == 0


def test_the_third_failed_check_parks_the_section_with_a_ping_and_sends_it_to_no_recut(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the loop parks below three failed checks, never parks, counts a failed check
    # toward FAILURE_LIMIT, or parks without a ping naming the failing check.
    queue = queue_file(CHECK_QUEUE)
    scenario(_lines(DONE_LEAD))
    _failing_check(tmp_path, monkeypatch)
    leads = [_step(DONE_LEAD), _step(DONE_LEAD), _step(DONE_LEAD), _step(NO_STATUS_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads)
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    runs = _runs(tmp_path, "lead")
    assert len(runs) == 5
    assert all(_body(queue, "s1") in str(r["prompt"]) for r in runs[:3])
    assert all(_body(queue, "s2") in str(r["prompt"]) for r in runs[3:])
    assert _runs(tmp_path, "recut") == []
    section = State.open(queue, cfg).section("s1")
    assert section.status == "parked"
    assert section.check_failures == 3
    assert section.failures == 0
    assert section.check_pending is False
    pings = [p[0] for p in _pings(tmp_path)]
    assert FAIL_MARK in pings[0]
    assert "exit 1" in pings[0]
    assert str(State.open(queue, cfg).check_log(_lead_logs(queue, cfg)[2])) in pings[0]
    texts = _texts(capsys.readouterr().out)
    failed = [t for t in texts if t.startswith("section s1: check failed")]
    assert failed == [f"section s1: check failed ({n} of 3)" for n in (1, 2, 3)], texts


def test_a_check_failing_outside_the_code_parks_the_section_and_its_answer_reruns_the_check_with_no_lead(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when: an outside verdict counts as a failed check, resumes a lead, parks with no
    # ping, or the answered section runs a lead instead of rerunning its check.
    queue = queue_file(CHECK_QUEUE)
    scenario(_lines(DONE_LEAD))
    _done_in_state(queue, cfg, "s2")
    script = _check_script(tmp_path, monkeypatch, 127)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD)])
    state = State.open(queue, cfg)
    loop = _Background(queue, cfg)
    try:
        _until(lambda: len(_pings(tmp_path)) == 1)
        parked = State.open(queue, cfg).section("s1")
        assert parked.status == "parked"
        assert parked.check_pending is True
        assert parked.check_failures == 0
        assert parked.failures == 0
        assert "exit 127" in _pings(tmp_path)[0][0]
        assert _checks_ran(tmp_path) == ["first ran"]
        script.write_text(_script_text(tmp_path, 0))
        State.open(queue, cfg).set_answer("s1", "The tool is installed now.")
        assert loop.finish() == ExitCode.QUEUE_EMPTY
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    assert len(_runs(tmp_path, "lead")) == 1
    assert _checks_ran(tmp_path) == ["first ran", "first ran", "second ran"]
    section = State.open(queue, cfg).section("s1")
    assert section.status == "done"
    assert section.check_pending is False
    assert [e["verdict"] for e in _check_entries(queue, cfg)] == ["outside", "pass"]


def test_a_section_left_pending_on_its_check_reruns_the_check_and_no_lead(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when: a section with check_pending runs a lead, or is marked done without its check.
    queue = queue_file(CHECK_QUEUE)
    scenario(_lines(DONE_LEAD))
    _done_in_state(queue, cfg, "s2")
    State.open(queue, cfg).set_check_pending("s1", True)
    _check_script(tmp_path, monkeypatch, 0)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert _runs(tmp_path, "lead") == []
    assert _checks_ran(tmp_path) == ["first ran", "second ran"]
    section = State.open(queue, cfg).section("s1")
    assert section.status == "done"
    assert section.check_pending is False


def test_a_done_on_a_section_with_no_check_marks_it_done_with_a_none_verdict(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a section with no check line is left open on DONE, or gets no ledger line
    # and progress line saying none ran.
    queue = queue_file(CHECK_QUEUE)
    scenario(_lines(DONE_LEAD))
    _done_in_state(queue, cfg, "s1")
    _check_script(tmp_path, monkeypatch, 1)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert State.open(queue, cfg).section("s2").status == "done"
    assert _checks_ran(tmp_path) == []
    entries = _check_entries(queue, cfg)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["section"] == "s2"
    assert entry["verdict"] == "none"
    assert entry["command"] is None
    assert entry["exit"] is None
    assert entry["log"] is None
    assert "check s2: none to run" in _texts(capsys.readouterr().out)


# Check behavior 2: the check inheriting `relay go`'s environment.


def test_the_check_runs_with_the_environment_relay_go_started_with(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when: the loop or its runner gives the check a fresh or trimmed environment.
    queue = queue_file(CHECK_QUEUE)
    scenario(_lines(DONE_LEAD))
    _done_in_state(queue, cfg, "s2")
    seen = tmp_path / "mark-seen.txt"
    _check_script(tmp_path, monkeypatch, 0, f'printf "%s" "$RELAY_CHECK_MARK" >> "{seen}"\n')
    monkeypatch.setenv("RELAY_CHECK_MARK", "inherited from relay go")
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert _checks_ran(tmp_path) == ["first ran", "second ran"]
    assert seen.read_text() == "inherited from relay go" * 2


# Check behavior 3: the ledger line and the check log.


def test_each_check_run_appends_one_check_line_to_the_ledger(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when: the loop writes no check line, writes it with another field, or a check line
    # that spends tokens or dollars or that the ledger cannot read.
    queue = queue_file(CHECK_QUEUE)
    scenario(_lines(DONE_LEAD))
    _done_in_state(queue, cfg, "s2")
    script = _failing_check(tmp_path, monkeypatch)
    leads = [_step(DONE_LEAD), _step(DONE_SMALL_LEAD, write=(_passing_source(tmp_path), script))]
    cfg = _sequenced(cfg, tmp_path, leads)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    state = State.open(queue, cfg)
    logs = _lead_logs(queue, cfg)
    assert len(logs) == 2
    entries = _check_entries(queue, cfg)
    assert len(entries) == 2
    fail, ok = entries
    keys = {"time", "kind", "section", "session", "tokens", "dollars", "command", "exit", "timed_out", "verdict", "tail", "log"}
    assert set(fail) == keys
    assert set(ok) == keys
    assert fail["section"] == "s1"
    assert fail["session"] is None
    assert fail["tokens"] == 0
    assert fail["dollars"] == 0.0
    assert fail["command"] == FIRST_CHECK
    assert fail["exit"] == 1
    assert fail["timed_out"] is False
    assert fail["verdict"] == "fail"
    assert FAIL_MARK in str(fail["tail"])
    assert fail["log"] == str(state.check_log(logs[0]))
    assert ok["section"] == "s1"
    assert ok["session"] is None
    assert ok["tokens"] == 0
    assert ok["dollars"] == 0.0
    assert ok["exit"] == 0
    assert ok["timed_out"] is False
    assert ok["verdict"] == "pass"
    assert ok["log"] == str(state.check_log(logs[1]))
    ledger = _ledger(queue, cfg)
    assert ledger.unreadable() == []
    path = state.stop_file.parent / "ledger.jsonl"
    leads_only = [json.loads(line) for line in path.read_text().splitlines()]
    leads_only = [e for e in leads_only if e.get("kind") != "check"]
    assert ledger.total(None).tokens == sum(int(e["tokens"]) for e in leads_only)


def test_the_check_log_beside_the_leads_run_log_holds_every_checks_output_in_order(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when: the check output goes to no log, to another path than check_log of the
    # lead's run log, or only the last check's output is kept.
    queue = queue_file(CHECK_QUEUE)
    scenario(_lines(DONE_LEAD))
    _done_in_state(queue, cfg, "s2")
    _check_script(tmp_path, monkeypatch, 0)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    logs = _lead_logs(queue, cfg)
    assert len(logs) == 1
    check_log = State.open(queue, cfg).check_log(logs[0])
    assert check_log.exists()
    text = check_log.read_text()
    assert "check first output" in text
    assert "check second output" in text
    assert text.index("check first output") < text.index("check second output")


def test_a_pending_check_with_no_lead_run_logs_to_the_sections_own_check_log(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when: a check run with no lead log behind it logs nowhere, or to another path than
    # runs/check-<sid>.check.
    queue = queue_file(CHECK_QUEUE)
    scenario(_lines(DONE_LEAD))
    _done_in_state(queue, cfg, "s2")
    State.open(queue, cfg).set_check_pending("s1", True)
    _check_script(tmp_path, monkeypatch, 0)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    check_log = State.open(queue, cfg).run_dir / "check-s1.check"
    assert check_log.exists()
    assert "check first output" in check_log.read_text()
    assert [e["log"] for e in _check_entries(queue, cfg)] == [str(check_log)]


# Check behavior 4: `DONE` calls `_verify` in place of `mark_done`.


def test_a_done_whose_check_fails_leaves_the_section_open(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when: DONE still calls mark_done, whatever the check says.
    queue = queue_file(CHECK_QUEUE)
    scenario(_lines(DONE_LEAD))
    _done_in_state(queue, cfg, "s2")
    _failing_check(tmp_path, monkeypatch)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD), _step(NO_STATUS_LEAD)])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert _checks_ran(tmp_path) == ["first ran"]
    section = State.open(queue, cfg).section("s1")
    assert section.status == "open"
    assert section.check_failures == 1


@pytest.mark.parametrize("lead", [RETIRED_LEAD, NO_STATUS_LEAD])
def test_the_checks_run_on_the_leads_done_and_after_no_other_status(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    lead: str,
) -> None:
    # Breaks when: the loop runs the checks after a lead's run whatever its status, or not on DONE.
    queue = queue_file(CHECK_QUEUE)
    scenario(_lines(DONE_LEAD))
    _done_in_state(queue, cfg, "s2")
    _check_script(tmp_path, monkeypatch, 0)
    cfg = _sequenced(cfg, tmp_path, [_step(lead), _step(DONE_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert len(_runs(tmp_path, "lead")) == 2
    assert _checks_ran(tmp_path) == ["first ran", "second ran"]
    assert [e["verdict"] for e in _check_entries(queue, cfg)] == ["pass"]
    assert State.open(queue, cfg).section("s1").status == "done"


# Check behavior 5: The section stays open on a fail below the limit, so the next pass resumes its lead.


def test_failed_checks_below_the_limit_keep_the_section_open_for_its_resumed_lead(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a failed check below CHECK_LIMIT parks the section, moves the loop on to the
    # next section, or stops the run.
    queue = queue_file(CHECK_QUEUE)
    scenario(_lines(DONE_LEAD))
    script = _failing_check(tmp_path, monkeypatch)
    leads = [_step(DONE_LEAD), _step(DONE_LEAD), _step(DONE_SMALL_LEAD, write=(_passing_source(tmp_path), script))]
    cfg = _sequenced(cfg, tmp_path, leads)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    runs = _runs(tmp_path, "lead")
    assert len(runs) == 4
    for again in runs[1:3]:
        assert _body(queue, "s1") in str(again["prompt"])
        assert "resume sess-lead-1" in str(again["prompt"])
    assert _body(queue, "s2") in str(runs[3]["prompt"])
    assert _pings(tmp_path)[:-1] == []
    state = State.open(queue, cfg)
    assert state.section("s1").status == "done"
    assert state.section("s1").failures == 0
    assert state.section("s2").status == "done"
    texts = _texts(capsys.readouterr().out)
    failed = [t for t in texts if t.startswith("section s1: check failed")]
    assert failed == ["section s1: check failed (1 of 3)", "section s1: check failed (2 of 3)"], texts


# Check behavior 6: `take_check_feedback` feeds `lead_prompt`.


def test_the_check_feedback_goes_to_the_next_lead_only(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when: the loop reads the feedback without taking it, so every later lead carries
    # it, or never passes it to lead_prompt.
    queue = queue_file(CHECK_QUEUE)
    scenario(_lines(DONE_LEAD))
    _done_in_state(queue, cfg, "s2")
    script = _failing_check(tmp_path, monkeypatch)
    leads = [_step(DONE_LEAD), _step(NO_STATUS_LEAD), _step(DONE_SMALL_LEAD, write=(_passing_source(tmp_path), script))]
    cfg = _sequenced(cfg, tmp_path, leads)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    prompts = [str(r["prompt"]) for r in _runs(tmp_path, "lead")]
    assert len(prompts) == 3
    assert FEEDBACK_INTRO not in prompts[0]
    assert FEEDBACK_INTRO in prompts[1]
    assert FAIL_MARK in prompts[1]
    assert FEEDBACK_INTRO not in prompts[2]
    assert FAIL_MARK not in prompts[2]
    section = State.open(queue, cfg).section("s1")
    assert section.status == "done"
    assert section.check_feedback is None


# Idle retire (relay-check design, Order 7; `_watcher` and `_run_section`). When the retire flag
# first goes up, `_watcher` snapshots the branch heads; on an event at `idle_ceiling` or more
# with the flag up and the heads unchanged it kills the lead, writes the retired-idle line, and
# the run is handled as `RETIRED`. Each lead below runs through a climbing shim: it records
# `{"cwd", "prompt"}` to `<tmp_path>/plans/lead/run-<n>.json` as `_SEQ` does and takes plan step
# n (the last once the plan runs out). It runs the fake on the step's first stream; when the step
# has a second, it waits for the retire flag (a path the prompt names that did not exist when
# the lead started), and, when the step has a gate, writes `<gate>/ready` and waits for
# `<gate>/go` (the test commits in between), then runs the fake on the second stream.
_CLIMB = r"""
import json, os, re, subprocess, sys, time
rec, fake, plan = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
prompt = sys.stdin.read()
n = len([p for p in os.listdir(rec) if p.startswith("run-") and p.endswith(".json")])
out = os.path.join(rec, "run-%d.json" % n)
with open(out + ".part", "w") as f:
    json.dump({"cwd": os.getcwd(), "prompt": prompt}, f)
os.replace(out + ".part", out)
step = plan[min(n, len(plan) - 1)]
paths = sorted({p.rstrip(".,;:)") for p in re.findall(r"/[^\s`'\"<>]+", prompt)})
before = {p for p in paths if os.path.exists(p)}
def emit(stream):
    sys.stdout.flush()
    env = dict(os.environ, RELAY_FAKE_SCENARIO=stream)
    subprocess.run([fake], stdin=subprocess.DEVNULL, env=env, check=True)
emit(step["first"])
if step["second"]:
    end = time.time() + 10
    while time.time() < end and not [p for p in paths if p not in before and os.path.exists(p)]:
        time.sleep(0.02)
    if step["gate"]:
        time.sleep(0.2)
        open(os.path.join(step["gate"], "ready"), "w").close()
        end = time.time() + 15
        while time.time() < end and not os.path.exists(os.path.join(step["gate"], "go")):
            time.sleep(0.02)
    emit(step["second"])
"""

# With `fake_cfg`'s context_limit 100_000, idle_ceiling 130_000 and hard_ceiling 200_000: the
# first stream's message raises the retire flag below the idle ceiling, the second's reaches it.
FLAG_CONTEXT = 110_000
IDLE_CONTEXT = 150_000
PAST_HARD_CONTEXT = 210_000


def _usage(context: int) -> dict[str, int]:
    """Usage whose context tokens (input plus both cache counts) come to `context`."""
    return {
        "input_tokens": 10,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": context - 10,
        "output_tokens": 5,
    }


def _climb_step(tmp_path: Path, session: str, second_context: int, gate: Path | None = None) -> dict[str, object]:
    """A climbing lead's plan step: a first stream (init, one message at FLAG_CONTEXT) and a
    second (one message at `second_context`, then a result ending DONE), in session `session`."""
    streams = tmp_path / "streams"
    streams.mkdir(exist_ok=True)

    def message(n: int, context: int) -> str:
        body = {
            "id": f"msg_{session}_{n}",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Working."}],
            "usage": _usage(context),
        }
        return json.dumps({"type": "assistant", "message": body, "session_id": session})

    init = {"type": "system", "subtype": "init", "session_id": session, "cwd": "/work", "model": "claude-opus", "tools": ["Bash"]}
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 100,
        "num_turns": 2,
        "result": "Step committed.\nDONE",
        "session_id": session,
        "total_cost_usd": 0.01,
        "usage": _usage(second_context),
    }
    first = streams / f"{session}-1.jsonl"
    second = streams / f"{session}-2.jsonl"
    first.write_text(json.dumps(init) + "\n" + message(1, FLAG_CONTEXT) + "\n")
    second.write_text(message(2, second_context) + "\n" + json.dumps(result) + "\n")
    return {"first": str(first), "second": str(second), "gate": str(gate) if gate else None}


def _fixture_step(name: str) -> dict[str, object]:
    """A plan step that runs the fixture stream `name` whole."""
    return {"first": str(FIXTURES / name), "second": None, "gate": None}


def _climbing(cfg: Config, tmp_path: Path, steps: list[dict[str, object]]) -> Config:
    rec = tmp_path / "plans" / "lead"
    rec.mkdir(parents=True, exist_ok=True)
    lead = ["fake-climb", str(rec), json.dumps(steps)]
    return dataclasses.replace(cfg, lead_command=lead)


def _retired_idle(sid: str, tokens: int) -> str:
    return f"lead {sid}: retired at {tokens} context tokens, no commit since the retire flag"


# Loop behavior 1: idle retire with and without a commit.


def test_a_lead_with_no_commit_since_the_retire_flag_is_retired_at_the_idle_ceiling(
    cfg: Config,
    tmp_path: Path,
    git_repo: GitRepo,
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the watcher never compares the heads at idle_ceiling, compares with `>`, or
    # lets the lead run on to its DONE with no commit since the flag.
    queue = _queue_of(git_repo.root / "queue.md", "s1")
    scenario(_lines(DONE_LEAD))
    cfg = dataclasses.replace(cfg, idle_ceiling=IDLE_CONTEXT)
    steps = [_climb_step(tmp_path, "sess-climb-1", IDLE_CONTEXT), _fixture_step(DONE_SMALL_LEAD)]
    cfg = _climbing(cfg, tmp_path, steps)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert len(_runs(tmp_path, "lead")) == 2
    texts = _texts(capsys.readouterr().out)
    assert [t for t in texts if ": retired at " in t] == [_retired_idle("s1", IDLE_CONTEXT)], texts
    section = State.open(queue, cfg).section("s1")
    assert section.status == "done"
    assert section.last_session == "sess-lead-6"


def test_a_commit_since_the_retire_flag_keeps_the_lead_running_past_the_idle_ceiling(
    cfg: Config,
    tmp_path: Path,
    git_repo: GitRepo,
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the watcher retires at idle_ceiling whatever the heads say, snapshots the heads
    # at each event instead of when the flag goes up, or retires a lead that committed.
    queue = _queue_of(git_repo.root / "queue.md", "s1", "s2")
    scenario(_lines(DONE_LEAD))
    gate = tmp_path / "gate"
    gate.mkdir()
    steps = [
        _climb_step(tmp_path, "sess-climb-1", IDLE_CONTEXT, gate=gate),
        _climb_step(tmp_path, "sess-climb-2", IDLE_CONTEXT),
        _fixture_step(DONE_SMALL_LEAD),
    ]
    cfg = _climbing(cfg, tmp_path, steps)
    loop = _Background(queue, cfg)
    try:
        _until(lambda: (gate / "ready").exists())
        git_repo.commit(cwd=git_repo.worktrees["s1"], message="step 1")
        (gate / "go").touch()
        assert loop.finish() == ExitCode.QUEUE_EMPTY
    finally:
        (gate / "go").touch()
        State.open(queue, cfg).stop_file.touch()
        loop.thread.join(15)
    runs = _runs(tmp_path, "lead")
    assert len(runs) == 3
    assert _body(queue, "s2") in str(runs[1]["prompt"])
    assert _body(queue, "s2") in str(runs[2]["prompt"])
    texts = _texts(capsys.readouterr().out)
    assert [t for t in texts if ": retired at " in t] == [_retired_idle("s2", IDLE_CONTEXT)], texts
    state = State.open(queue, cfg)
    assert state.section("s1").status == "done"
    assert state.section("s1").last_session == "sess-climb-1"
    assert state.section("s1").failures == 0
    assert state.section("s2").status == "done"


# Loop behavior 2: A run with `idle_retired` set is handled as `RETIRED`. It records no failure.


def test_idle_retired_runs_are_followed_by_a_fresh_lead_and_count_no_failure(
    cfg: Config,
    tmp_path: Path,
    git_repo: GitRepo,
    scenario: Callable[[list[str]], Path],
) -> None:
    # Breaks when: an idle retire is taken as a kill, so it records a failure and the second
    # stops the run FAILED_TWICE, or the loop moves on from the section.
    queue = _queue_of(git_repo.root / "queue.md", "s1")
    scenario(_lines(DONE_LEAD))
    steps = [
        _climb_step(tmp_path, "sess-climb-1", IDLE_CONTEXT),
        _climb_step(tmp_path, "sess-climb-2", IDLE_CONTEXT),
        _fixture_step(DONE_SMALL_LEAD),
    ]
    cfg = _climbing(cfg, tmp_path, steps)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    runs = _runs(tmp_path, "lead")
    assert len(runs) == 3
    assert all(_body(queue, "s1") in str(r["prompt"]) for r in runs)
    assert "resume sess-climb-1" in str(runs[1]["prompt"])
    assert "resume sess-climb-2" in str(runs[2]["prompt"])
    section = State.open(queue, cfg).section("s1")
    assert section.failures == 0
    assert section.status == "done"


# Loop behavior 3: The hard_ceiling kill keeps its order and meaning.


def test_past_the_hard_ceiling_a_lead_is_killed_as_a_failure_not_retired_idle(
    cfg: Config,
    tmp_path: Path,
    git_repo: GitRepo,
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the watcher weighs the idle ceiling before the hard ceiling, so a lead past
    # hard_ceiling with no commit since the flag is retired and counts no failure.
    queue = _queue_of(git_repo.root / "queue.md", "s1")
    scenario(_lines(DONE_LEAD))
    steps = [
        _climb_step(tmp_path, "sess-climb-1", IDLE_CONTEXT),
        _climb_step(tmp_path, "sess-climb-2", PAST_HARD_CONTEXT),
        _fixture_step(DONE_SMALL_LEAD),
    ]
    cfg = _climbing(cfg, tmp_path, steps)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert len(_runs(tmp_path, "lead")) == 3
    texts = _texts(capsys.readouterr().out)
    retired = _retired_idle("s1", IDLE_CONTEXT)
    killed = f"lead s1: killed at {PAST_HARD_CONTEXT} context tokens, past the hard ceiling"
    assert [t for t in texts if ": retired at " in t] == [retired], texts
    assert [t for t in texts if ": killed at " in t and str(PAST_HARD_CONTEXT) in t] == [killed], texts
    assert texts.index(retired) < texts.index(killed)
    section = State.open(queue, cfg).section("s1")
    assert section.failures == 1
    assert section.status == "done"


# Loop behavior 4: a nested recut id failing the recut.


@pytest.mark.parametrize(
    "ids",
    [("s1.1", "s1.2", "s2"), ("s1a", "s1.1", "s2")],
    ids=["all-nested", "one-nested-beside-a-flat-one"],
)
def test_a_recut_that_adds_an_id_nested_under_the_section_counts_as_a_failure_of_the_section(
    cfg: Config,
    tmp_path: Path,
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
    ids: tuple[str, ...],
) -> None:
    # Breaks when: `_recut` takes a changed queue as a good recut whatever ids it adds, or fails
    # it only when every new id is nested.
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    recut = _queue_of(tmp_path / "recut.md", *ids)
    scenario(_lines(DONE_LEAD))
    recuts = [_step(DIVVYER_RUN, write=(recut, queue))]
    cfg = _sequenced(cfg, tmp_path, [_step(RECUT_LEAD), _step(DONE_LEAD)], recuts=recuts)
    run(queue, cfg)
    assert len(_runs(tmp_path, "recut")) == 1
    assert State.open(queue, cfg).section("s1").failures == 1
    assert "section s1: failed (1 of 2)" in _texts(capsys.readouterr().out)
    # The rejected cut is put back: the second lead runs on s1, and no nested section exists.
    assert [s.id for s in parse_queue(queue)] == ["s1", "s2"]
    assert "Section: s1\n" in str(_runs(tmp_path, "lead")[1]["prompt"])


# Nested recut behavior 1: A recut that replaces a section with ids nested under it (`s1` cut into
# `s1.1`, `s1.2`) fails the recut, and a rejected recut's sections never run: the queue is put
# back to its text from before the recut, and the next lead runs on the parent section, never on
# a nested one; this holds for a ladder recut and for the recut after a lead's design change.
# Nested recut behavior 2: When the recut after a design change is rejected for nested ids, the
# parent section stays in the queue and is parked with a question that names the nested ids and
# says Relay rejects nested ids, never "the recut made no usable change"; the rejected cut is kept
# in a file beside the recut's run log, and the question gives that file's path.
# Both run on the ladder queue (see "The escalation ladder" below for its helpers).

NO_USABLE_CHANGE = "the recut made no usable change"


def _nested_cut(queue: Path, out: Path) -> Path:
    """`queue`'s text with `s1` cut into the nested ids `s1.1` and `s1.2`: `s1`'s header and every
    `depends:` on it renamed to `s1.1`, and a section `s1.2` appended."""
    _renamed(queue, "s1", "s1.1", out)
    out.write_text(out.read_text() + "section s1.2 | lead | steps: 2\n  s1.2 work\n")
    return out


def _on_parent_only(prompt: str) -> bool:
    """The lead prompt names section `s1` itself, and no section nested under it."""
    return re.search(r"Section: s1(?![.\w])", prompt) is not None and "Section: s1." not in prompt


def _design_change_leads(tmp_path: Path) -> list[dict[str, object]]:
    """A lead on s1 ending `DESIGN: <problem>`, then a lead with no status line."""
    return [_step(str(_status_lead(tmp_path, "sess-design", f"DESIGN: {PROBLEM}"))), _step(NO_STATUS_LEAD)]


def _answer_and_rerun(queue: Path, cfg: Config) -> None:
    """Clear the stop file the park's ping touched, answer the parked s1 and run the queue again."""
    State.open(queue, cfg).stop_file.unlink(missing_ok=True)
    State.open(queue, cfg).set_answer("s1", "Go on.")
    _Background(queue, cfg).finish()


@pytest.mark.parametrize("how", ["ladder-recut", "design-change-recut"])
def test_a_recut_into_nested_ids_is_put_back_and_the_next_lead_runs_on_the_parent_section(
    how: str,
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
) -> None:
    # Breaks when: `_recut` keeps a cut that adds `<sid>.<n>` ids, or fails it without writing the
    # queue's text from before the recut back, so the next lead runs on `s1.1` or `s1.2`; for the
    # ladder recut or for the recut after a design change.
    queue = _ladder(queue_file, cfg, tmp_path)
    before = queue.read_text()
    nested = _nested_cut(queue, tmp_path / "nested.md")
    scenario(_lines(DONE_LEAD))
    recuts = [_step(DIVVYER_RUN, write=(nested, queue))]
    if how == "ladder-recut":
        cfg = _sequenced(cfg, tmp_path, [_step(RECUT_LEAD), _step(NO_STATUS_LEAD)], recuts=recuts)
        cfg = _with_architect(cfg, tmp_path, [_step(ARCHITECT_APPROVED)])
        cfg = _stop_on_ping(cfg, queue)
        run(queue, cfg)
    else:
        cfg = _sequenced(cfg, tmp_path, _design_change_leads(tmp_path), recuts=recuts)
        cfg = _with_architect(cfg, tmp_path, [_step(ARCHITECT_APPROVED)])
        cfg = _record_and_stop_on_ping(cfg, queue, tmp_path)
        run(queue, cfg)
        assert queue.read_text() == before
        _answer_and_rerun(queue, cfg)
    assert len(_runs(tmp_path, "recut")) == 1
    assert queue.read_text() == before
    assert [s.id for s in parse_queue(queue)] == ["s1", "s2", "s3"]
    leads = [str(r["prompt"]) for r in _runs(tmp_path, "lead")]
    assert len(leads) >= 2
    assert all("Section: s1." not in prompt for prompt in leads)
    assert _on_parent_only(leads[1])


def test_a_design_change_recut_into_nested_ids_parks_the_parent_with_a_question_giving_the_kept_cut(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: a design-change recut rejected for nested ids leaves `s1` open or drops it from
    # the queue, parks it with "the recut made no usable change" or a question that names neither
    # nested id nor says Relay rejects nested ids, or keeps no copy of the rejected cut beside the
    # recut's run log at a path the question gives, parks it with a question that does not open
    # "the design change for s1 in <design> did not land: <what>", or records a failure
    # (relay-ladder-design.md, `_design_outcome` and `failed_text`).
    queue = _ladder(queue_file, cfg, tmp_path)
    nested = _nested_cut(queue, tmp_path / "nested.md")
    cut = nested.read_text()
    scenario(_lines(DONE_LEAD))
    recuts = [_step(DIVVYER_RUN, write=(nested, queue))]
    cfg = _sequenced(cfg, tmp_path, _design_change_leads(tmp_path), recuts=recuts)
    cfg = _with_architect(cfg, tmp_path, [_step(ARCHITECT_APPROVED)])
    cfg = _record_and_stop_on_ping(cfg, queue, tmp_path)
    run(queue, cfg)
    assert [s.id for s in parse_queue(queue)] == ["s1", "s2", "s3"]
    state = State.open(queue, cfg)
    parked = state.section("s1")
    assert parked.status == "parked"
    question = parked.question
    assert question is not None
    assert re.match(_failed_design("s1"), question), question
    assert parked.failures == 0
    assert "s1.1" in question and "s1.2" in question
    assert "rejects nested ids" in question.lower()
    assert NO_USABLE_CHANGE not in question
    run_dir = str(state.run_dir).rstrip("/")
    recut_logs = [p for p in state.run_dir.glob("*.jsonl") if "sess-recut-1" in p.read_text()]
    assert len(recut_logs) == 1, recut_logs
    named = [m.rstrip(".,;:)'\"") for m in re.findall(re.escape(run_dir) + r"/\S+", question)]
    kept = [Path(p) for p in named if Path(p) != recut_logs[0] and Path(p).is_file()]
    assert len(kept) == 1, named
    assert kept[0].parent == recut_logs[0].parent
    assert kept[0].read_text() == cut


# Research behaviors (relay-research design, Order 7): `_research` maps a section's code before
# its lead (relay-research-design.md:201-206, 216-218). Each test puts the researcher behind the
# sequencing shim, recording to `<tmp_path>/plans/research`, and runs the queue from the main
# checkout of `git_repo`, whose `lead/s1` worktree holds the files the map names, committed.
# The researcher's stream `tests/fixtures/stream-research.jsonl` (session "sess-research-1",
# two reader subagents) ends on the map text of `tests/fixtures/research-map.txt`.

RESEARCH_RUN = "stream-research.jsonl"
AGENTS_LEAD = "stream-agents.jsonl"  # "DONE", session "sess-agents-1", two subagents
_MAP_TEXT = (FIXTURES / "research-map.txt").read_text()
# The map's body: its lines from `MAP` to `END MAP`, both included (relay-research-design.md:44).
MAP_BODY = _MAP_TEXT[_MAP_TEXT.index("MAP\n") : _MAP_TEXT.index("END MAP") + len("END MAP")]
# Every path the map names (relay-research-design.md:43).
MAPPED_FILES = ("relay/git.py", "relay/loop.py", "relay/research.py")
# The lead's subagents in AGENTS_LEAD as a ledger line records them (relay-research-design.md:143).
LEAD_AGENTS = [
    {"name": "builder", "task_id": "a1", "total_tokens": 21844},
    {"name": "test-writer", "task_id": "a2", "total_tokens": 41000},
]


def _map_block(commit: str) -> str:
    """The block a lead prompt carries for s1's map at `commit`: research.block's usage paragraph,
    header and body (relay-research-design.md:69-73, 218)."""
    return block(Map(sid="s1", commit=commit, files=MAPPED_FILES, body=MAP_BODY))


def _mapped_worktree(repo: GitRepo) -> str:
    """Commit every file the map names in the `lead/s1` worktree; return that worktree's HEAD."""
    wt = repo.worktrees["s1"]
    for name in MAPPED_FILES:
        path = wt / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n")
    repo.git("add", *MAPPED_FILES, cwd=wt)
    return repo.commit(cwd=wt, message="mapped files")


def _research_queue(repo: GitRepo) -> Path:
    """The check fixture queue (sections s1 and s2) in the repository's main checkout."""
    queue = repo.root / CHECK_QUEUE
    queue.write_bytes((FIXTURES / CHECK_QUEUE).read_bytes())
    return queue


def _researched(cfg: Config, tmp_path: Path, leads: list[dict[str, object]]) -> Config:
    """`cfg` with its leads taking `leads` and each research run taking RESEARCH_RUN."""
    fake = cfg.lead_command[0]
    cfg = _sequenced(cfg, tmp_path, leads)
    research = _plan(tmp_path, fake, "research", [_step(RESEARCH_RUN)], False)
    return dataclasses.replace(cfg, research_command=research)


def _research_runs(tmp_path: Path) -> list[dict[str, object]]:
    """The records of every research run, in run order."""
    return _runs(tmp_path, "research")


def _run_entries(queue: Path, cfg: Config) -> list[dict[str, object]]:
    """The ledger's lines other than check lines, in file order."""
    path = State.open(queue, cfg).stop_file.parent / "ledger.jsonl"
    entries = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [e for e in entries if e.get("kind") != "check"]


# Research behavior 1: research before a lead, its map in the lead prompt, the lead's ledger
# line carrying the map commit and agents.


def test_research_runs_before_the_lead_and_its_map_goes_into_the_lead_prompt(
    cfg: Config, tmp_path: Path, git_repo: GitRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: the lead runs with no research before it, or its prompt lacks the map block,
    # its usage paragraph included (a header and body built in loop.py instead of by `block`).
    commit = _mapped_worktree(git_repo)
    queue = _research_queue(git_repo)
    _done_in_state(queue, cfg, "s2")
    _check_script(tmp_path, monkeypatch, 0)
    cfg = _researched(cfg, tmp_path, [_step(AGENTS_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    research = _research_runs(tmp_path)
    assert len(research) == 1
    assert _body(queue, "s1") in str(research[0]["prompt"])
    leads = _runs(tmp_path, "lead")
    assert len(leads) == 1
    prompt = str(leads[0]["prompt"])
    assert f"map s1 at {commit}" in prompt
    assert MAP_BODY in prompt
    assert _map_block(commit) in prompt
    kinds = [(e["kind"], e["section"]) for e in _run_entries(queue, cfg)]
    assert kinds == [("research", "s1"), ("lead", "s1")]


def test_the_leads_ledger_line_carries_the_map_commit_and_its_agents(
    cfg: Config, tmp_path: Path, git_repo: GitRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: the lead's ledger line holds a null map or no agents though its prompt carried
    # a map and the lead dispatched subagents.
    commit = _mapped_worktree(git_repo)
    queue = _research_queue(git_repo)
    _done_in_state(queue, cfg, "s2")
    _check_script(tmp_path, monkeypatch, 0)
    cfg = _researched(cfg, tmp_path, [_step(AGENTS_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    leads = [e for e in _run_entries(queue, cfg) if e["kind"] == "lead"]
    assert len(leads) == 1
    assert leads[0]["session"] == "sess-agents-1"
    assert leads[0].get("map") == commit
    assert leads[0].get("agents") == LEAD_AGENTS


# Research behavior 2: no research on a `check_pending` pass.


def test_a_check_pending_pass_runs_no_research_and_the_next_leads_pass_does(
    cfg: Config, tmp_path: Path, git_repo: GitRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: `_research` runs on the pass that only reruns s1's pending check, or not
    # before s2's lead.
    _mapped_worktree(git_repo)
    queue = _research_queue(git_repo)
    State.open(queue, cfg).set_check_pending("s1", True)
    _check_script(tmp_path, monkeypatch, 0)
    cfg = _researched(cfg, tmp_path, [_step(DONE_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert _checks_ran(tmp_path) == ["first ran", "second ran"]
    research = _research_runs(tmp_path)
    assert len(research) == 1
    assert _body(queue, "s2") in str(research[0]["prompt"])
    assert _body(queue, "s1") not in str(research[0]["prompt"])
    entries = _run_entries(queue, cfg)
    assert [(e["kind"], e["section"]) for e in entries] == [("research", "s2"), ("lead", "s2")]


# Research behavior 3: reuse after a retire with the mapped files unchanged, refresh after one
# changed, both in the section worktree.


def test_a_fresh_lead_after_a_retire_reuses_the_map_when_its_files_are_unchanged(
    cfg: Config,
    tmp_path: Path,
    git_repo: GitRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the second pass reruns the researcher though no mapped file changed, the
    # fresh lead starts without the saved map, or research runs outside the section worktree.
    commit = _mapped_worktree(git_repo)
    queue = _research_queue(git_repo)
    _done_in_state(queue, cfg, "s2")
    _check_script(tmp_path, monkeypatch, 0)
    cfg = _researched(cfg, tmp_path, [_step(RETIRED_LEAD), _step(DONE_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    research = _research_runs(tmp_path)
    assert len(research) == 1
    assert Path(str(research[0]["cwd"])).resolve() == git_repo.worktrees["s1"]
    leads = _runs(tmp_path, "lead")
    assert len(leads) == 2
    for lead in leads:
        assert f"map s1 at {commit}" in str(lead["prompt"])
        assert MAP_BODY in str(lead["prompt"])
        assert _map_block(commit) in str(lead["prompt"])
    texts = _texts(capsys.readouterr().out)
    assert f"research s1: map at {commit} still current, reused" in texts, texts
    assert [e["kind"] for e in _run_entries(queue, cfg)] == ["research", "lead", "lead"]


def test_a_fresh_lead_after_a_retire_that_changed_a_mapped_file_gets_a_fresh_map(
    cfg: Config,
    tmp_path: Path,
    git_repo: GitRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the second pass reuses a map whose file the retired lead changed, the
    # refreshing research runs outside the section worktree, or the refreshed map keeps the stale
    # map's commit instead of the HEAD read again before the researcher reran.
    commit = _mapped_worktree(git_repo)
    queue = _research_queue(git_repo)
    _done_in_state(queue, cfg, "s2")
    _check_script(tmp_path, monkeypatch, 0)
    wt = git_repo.worktrees["s1"]
    edited = tmp_path / "edited-git.py"
    edited.write_text("# relay/git.py, edited by the lead\n")
    changed = (edited, wt / "relay" / "git.py")
    # The retired lead commits its edit in the `lead/s1` worktree, so HEAD moves on.
    committed = [*_GIT, "-C", str(wt), "commit", "-q", "-a", "-m", "lead edit"]
    leads_plan = [_step(RETIRED_LEAD, write=changed, then=committed), _step(DONE_LEAD)]
    cfg = _researched(cfg, tmp_path, leads_plan)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    head = git_repo.git("rev-parse", "HEAD", cwd=wt).strip()
    assert head != commit
    research = _research_runs(tmp_path)
    assert len(research) == 2
    for record in research:
        assert Path(str(record["cwd"])).resolve() == git_repo.worktrees["s1"]
    leads = _runs(tmp_path, "lead")
    assert len(leads) == 2
    assert f"map s1 at {commit}" in str(leads[0]["prompt"])
    assert f"map s1 at {head}" in str(leads[1]["prompt"])
    assert f"map s1 at {commit}" not in str(leads[1]["prompt"])
    assert MAP_BODY in str(leads[1]["prompt"])
    assert _map_block(head) in str(leads[1]["prompt"])
    texts = _texts(capsys.readouterr().out)
    assert not any(t.endswith("still current, reused") for t in texts), texts
    assert [e["kind"] for e in _run_entries(queue, cfg)] == ["research", "lead", "research", "lead"]


# Research behavior 4: a failed or over-cap research: the lead starts without a map, no failure
# counted; a failed run is reported as failed and pings, an over-cap map is reported as no usable
# map and pings nothing (relay-research-design.md:213, 247, 312). The research stream's one assistant
# message leaves context_tokens at 2 + 150 + 800; DONE_SMALL_LEAD's stays at 1 + 50 + 400. The
# map body runs 7 lines from `MAP` to `END MAP`, 5 between them.
RESEARCH_CONTEXT = 2 + 150 + 800


def _without_map(cfg: Config, how: str) -> tuple[Config, int]:
    """`cfg` changed so the research run fails `how`, and the exit code of its plan step."""
    if how == "killed":
        return dataclasses.replace(cfg, context_limit=RESEARCH_CONTEXT - 50, hard_ceiling=RESEARCH_CONTEXT), 0
    if how == "over-lines":
        return dataclasses.replace(cfg, map_max_lines=4), 0
    if how == "over-chars":
        return dataclasses.replace(cfg, map_max_chars=len(MAP_BODY) - 20), 0
    return cfg, 1


@pytest.mark.parametrize("how", ["failed", "killed", "over-lines", "over-chars"])
def test_a_research_that_fails_is_killed_or_is_over_a_cap_leaves_the_lead_to_start_without_a_map_and_counts_no_failure(
    how: str,
    cfg: Config,
    tmp_path: Path,
    git_repo: GitRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a research run that exits non-zero, is killed at hard_ceiling, or returns a map
    # over map_max_lines or map_max_chars hands its map to the lead, records a failure on the
    # section, or stops the lead from starting; a failed run is reported as "no usable map" or
    # sends no ping; an over-cap map is reported as failed or pings the owner.
    _mapped_worktree(git_repo)
    queue = _research_queue(git_repo)
    _done_in_state(queue, cfg, "s2")
    _check_script(tmp_path, monkeypatch, 0)
    cfg, exit = _without_map(cfg, how)
    fake = cfg.lead_command[0]
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_SMALL_LEAD)])
    research = _plan(tmp_path, fake, "research", [_step(RESEARCH_RUN, exit=exit)], False)
    cfg = dataclasses.replace(cfg, research_command=research)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert len(_research_runs(tmp_path)) == 1
    leads = _runs(tmp_path, "lead")
    assert len(leads) == 1
    prompt = str(leads[0]["prompt"])
    assert "map s1 at" not in prompt
    assert "END MAP" not in prompt
    section = State.open(queue, cfg).section("s1")
    assert section.failures == 0
    assert section.status == "done"
    entries = _run_entries(queue, cfg)
    assert [(e["kind"], e["section"]) for e in entries] == [("research", "s1"), ("lead", "s1")]
    assert "map" in entries[1] and entries[1]["map"] is None
    texts = _texts(capsys.readouterr().out)
    failed_run = how in ("failed", "killed")
    if failed_run:
        finished = [t for t in texts if t.startswith("research s1: failed: ")]
        assert len(finished) == 1, texts
        assert finished[0].endswith("; the lead starts without a map"), texts
        assert not any(t.startswith("research s1: no usable map ") for t in texts), texts
    else:
        finished = [t for t in texts if t.startswith("research s1: no usable map ")]
        assert len(finished) == 1, texts
        assert finished[0].endswith("; the lead starts without one"), texts
        assert not any(t.startswith("research s1: failed: ") for t in texts), texts
    assert not any(t.startswith("research s1: map of ") for t in texts), texts
    research_pings = [p[0] for p in _pings(tmp_path) if "research s1 failed: " in p[0]]
    assert len(research_pings) == (1 if failed_run else 0), _pings(tmp_path)
    if not failed_run:
        assert not any("research s1" in p[0] for p in _pings(tmp_path)), _pings(tmp_path)


# Research behavior 5: the research run's own flag, the lead's flag untouched
# (relay-research-design.md:12, 162, 203).


def test_the_research_brief_names_the_research_flag_and_the_lead_prompt_names_the_leads_flag(
    cfg: Config, tmp_path: Path, git_repo: GitRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: the research brief names the lead's retire flag, or the lead's prompt names the
    # research flag in its place.
    _mapped_worktree(git_repo)
    queue = _research_queue(git_repo)
    _done_in_state(queue, cfg, "s2")
    _check_script(tmp_path, monkeypatch, 0)
    state = State.open(queue, cfg)
    cfg = _researched(cfg, tmp_path, [_step(DONE_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    research = _research_runs(tmp_path)
    assert len(research) == 1
    brief = str(research[0]["prompt"])
    assert str(state.research_flag("s1")) in brief
    assert str(state.retire_flag) not in brief
    leads = _runs(tmp_path, "lead")
    assert len(leads) == 1
    assert str(state.retire_flag) in str(leads[0]["prompt"])
    assert str(state.research_flag("s1")) not in str(leads[0]["prompt"])


def test_a_research_run_asked_to_retire_touches_its_own_flag_and_leaves_the_leads_flag_alone(
    cfg: Config, tmp_path: Path, git_repo: GitRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: the research run's retire touches the lead's retire flag instead of, or as well
    # as, `research_flag(sid)`, so the lead's flag is up when the research run ends, or the
    # research flag never appears.
    commit = _mapped_worktree(git_repo)
    queue = _research_queue(git_repo)
    _done_in_state(queue, cfg, "s2")
    _check_script(tmp_path, monkeypatch, 0)
    state = State.open(queue, cfg)
    # Whether the lead's flag is up as each research run's ledger line is written, which is
    # after the run ends and before the lead's flag is unlinked for the lead
    # (relay-research-design.md:12, 195-196, 203-205).
    lead_flag_up: list[bool] = []
    append = Ledger.append

    def _seen_append(self: Ledger, *args: Any, **kwargs: Any) -> None:
        if (args[0] if args else kwargs.get("kind")) == "research":
            lead_flag_up.append(state.retire_flag.exists())
        append(self, *args, **kwargs)

    monkeypatch.setattr(Ledger, "append", _seen_append)
    cfg = dataclasses.replace(cfg, context_limit=RESEARCH_CONTEXT)
    cfg = _researched(cfg, tmp_path, [_step(DONE_SMALL_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert len(_research_runs(tmp_path)) == 1
    assert state.research_flag("s1").exists()
    assert lead_flag_up == [False]
    leads = _runs(tmp_path, "lead")
    assert len(leads) == 1
    assert f"map s1 at {commit}" in str(leads[0]["prompt"])
    assert State.open(queue, cfg).section("s1").status == "done"


# Research behavior 6: the map dropped on `DONE` and on a recut that removes the section
# (relay-research-design.md:166, 220). Each lead plan step that copies the section's map file
# aside proves the map was saved while that lead ran; a missing map fails the copy, and the lead.


def test_a_done_section_has_its_map_dropped_and_its_researcher_cleared(
    cfg: Config, tmp_path: Path, git_repo: GitRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: `mark_done` on the lead's DONE leaves the section's map file or its
    # research_session in place.
    _mapped_worktree(git_repo)
    queue = _research_queue(git_repo)
    _done_in_state(queue, cfg, "s2")
    _check_script(tmp_path, monkeypatch, 0)
    state = State.open(queue, cfg)
    seen = tmp_path / "seen.map"
    cfg = _researched(cfg, tmp_path, [_step(DONE_LEAD, write=(state.map_path("s1"), seen))])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert MAP_BODY in seen.read_text()
    assert not state.map_path("s1").exists()
    section = State.open(queue, cfg).section("s1")
    assert section.status == "done"
    assert section.research_session is None


def test_a_recut_that_removes_the_section_drops_its_map_and_its_researcher(
    cfg: Config, tmp_path: Path, git_repo: GitRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: `_recut` leaves the map file or research_session of a section the recut
    # queue no longer holds.
    _mapped_worktree(git_repo)
    queue = _research_queue(git_repo)
    _done_in_state(queue, cfg, "s2")
    _check_script(tmp_path, monkeypatch, 0)
    state = State.open(queue, cfg)
    seen = tmp_path / "seen.map"
    # relay-check-design.md:297: a split makes flat siblings, `s1` giving `s1a`.
    split = _queue_of(tmp_path / "split.md", "s1a", "s2")
    leads = [_step(RECUT_LEAD, write=(state.map_path("s1"), seen)), _step(DONE_LEAD)]
    fake = cfg.lead_command[0]
    cfg = _researched(cfg, tmp_path, leads)
    recut = _plan(tmp_path, fake, "recut", [_step(DIVVYER_RUN, write=(split, queue))], False)
    cfg = dataclasses.replace(cfg, recut_command=recut)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert len(_runs(tmp_path, "recut")) == 1
    assert MAP_BODY in seen.read_text()
    assert not state.map_path("s1").exists()
    assert State.open(queue, cfg).section("s1").research_session is None


def test_a_recut_that_keeps_the_section_id_keeps_its_map_for_the_next_pass(
    cfg: Config,
    tmp_path: Path,
    git_repo: GitRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: `_recut` drops the map of a section the recut queue still holds, so the next
    # pass runs the researcher again instead of reusing the current map.
    commit = _mapped_worktree(git_repo)
    queue = _research_queue(git_repo)
    _done_in_state(queue, cfg, "s2")
    _check_script(tmp_path, monkeypatch, 0)
    widened = tmp_path / "widened.md"
    widened.write_text(
        "section s1 | lead | steps: 1\n  s1 work, paths widened\nsection s2 | lead | steps: 1\n  s2 work\n"
    )
    fake = cfg.lead_command[0]
    cfg = _researched(cfg, tmp_path, [_step(RECUT_LEAD), _step(DONE_LEAD)])
    recut = _plan(tmp_path, fake, "recut", [_step(DIVVYER_RUN, write=(widened, queue))], False)
    cfg = dataclasses.replace(cfg, recut_command=recut)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert len(_runs(tmp_path, "recut")) == 1
    assert len(_research_runs(tmp_path)) == 1
    leads = _runs(tmp_path, "lead")
    assert len(leads) == 2
    assert "s1 work, paths widened" in str(leads[1]["prompt"])
    assert f"map s1 at {commit}" in str(leads[1]["prompt"])
    assert MAP_BODY in str(leads[1]["prompt"])
    texts = _texts(capsys.readouterr().out)
    assert f"research s1: map at {commit} still current, reused" in texts, texts


# The escalation ladder (relay-ladder-design.md, Order 8): which move a RECUT or DESIGN takes,
# run on the ladder queue, whose head line names `docs/superpowers/specs/ladder-design.md`.

LADDER = "ladder-queue.md"
LADDER_DESIGN = "ladder-design.md"
ARCHITECT_APPROVED = "stream-architect-approved.jsonl"

# A lead's reason in the problem / guess form (relay-ladder-design.md, The architect's brief).
PROBLEM = "two() reads one() before one.py lands"
GUESS_FIX = "split Order 3 so one.py lands first"


def _ladder(queue_file: Callable[[str], Path], cfg: Config, tmp_path: Path) -> Path:
    """The ladder queue under `tmp_path`, its design where its head line names it, and every
    section but `s1` done in state; return the queue."""
    queue = queue_file(LADDER)
    design = tmp_path / "docs" / "superpowers" / "specs" / LADDER_DESIGN
    design.parent.mkdir(parents=True, exist_ok=True)
    design.write_bytes((FIXTURES / LADDER_DESIGN).read_bytes())
    state = State.open(queue, cfg)
    for sid in ("s2", "s3"):
        state.mark_done(sid)
    return queue


def _renamed(source: Path, old: str, new: str, out: Path) -> Path:
    """`source`'s text with section `old`'s header, and every `depends:` on it, renamed to `new`,
    written to `out`: the divvyer's recut of `old` into the flat sibling `new`
    (relay-check-design.md:297)."""
    text = source.read_text().replace(f"section {old} |", f"section {new} |")
    out.write_text(text.replace(f"| depends: {old} |", f"| depends: {new} |"))
    return out


def _status_lead(tmp_path: Path, session: str, status: str) -> Path:
    """A scripted lead in session `session` whose result ends with the status line `status`."""
    streams = tmp_path / "streams"
    streams.mkdir(exist_ok=True)
    usage = {"input_tokens": 6, "cache_creation_input_tokens": 200, "cache_read_input_tokens": 1000, "output_tokens": 30}
    init = {"type": "system", "subtype": "init", "session_id": session, "cwd": "/work", "model": "claude-opus", "tools": ["Bash"]}
    body = {"id": f"msg_{session}", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "Stuck."}], "usage": usage}
    message = {"type": "assistant", "message": body, "session_id": session}
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 800,
        "num_turns": 1,
        "result": f"Stuck.\n{status}",
        "session_id": session,
        "total_cost_usd": 0.01,
        "usage": usage,
    }
    path = streams / f"{session}.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in (init, message, result)))
    return path


def _with_architect(cfg: Config, tmp_path: Path, steps: list[dict[str, object]]) -> Config:
    """`cfg` with each architect run taking the next step of its plan, recorded as role "design".
    The fake comes from `design_command`, which `_sequenced` leaves as `fake_cfg` set it: after
    `_sequenced`, `lead_command[0]` is the plan's interpreter, not the fake."""
    return dataclasses.replace(cfg, design_command=_plan(tmp_path, cfg.design_command[0], "design", steps, False))


def _entries(queue: Path, cfg: Config, kind: str) -> list[dict[str, Any]]:
    """The ledger's lines of kind `kind`, in order."""
    path = State.open(queue, cfg).stop_file.parent / "ledger.jsonl"
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    return [e for e in lines if e.get("kind") == kind]


def _stop_on_ping(cfg: Config, queue: Path) -> Config:
    """`cfg` whose every ping touches the queue's stop file, so a section parked for the owner ends
    the run with `STOP_FILE` instead of leaving the loop waiting (relay-ladder-design.md: rung 2
    sends no ping)."""
    stop = State.open(queue, cfg).stop_file
    touch = "import pathlib, sys; pathlib.Path(sys.argv[1]).touch()"
    return dataclasses.replace(cfg, ping_command=[sys.executable, "-I", "-S", "-c", touch, str(stop), "{message}"])


def _record_and_stop_on_ping(cfg: Config, queue: Path, tmp_path: Path) -> Config:
    """`cfg` whose every ping is recorded to `<tmp_path>/pings.jsonl`, as `cfg` records them, and
    then touches the queue's stop file, so a park's own ping both ends the run with `STOP_FILE`
    and stays readable through `_pings`."""
    stop = State.open(queue, cfg).stop_file
    record = tmp_path / "pings.jsonl"
    script = (
        "import json, pathlib, sys; f = open(sys.argv[1], 'a'); f.write(json.dumps(sys.argv[3:]) + chr(10)); "
        "f.close(); pathlib.Path(sys.argv[2]).touch()"
    )
    command = [sys.executable, "-I", "-S", "-c", script, str(record), str(stop), "{message}"]
    return dataclasses.replace(cfg, ping_command=command)


# Rung 1: a recut as now, and its ledger line.


def test_rung_1_a_recut_on_a_section_no_recut_made_runs_the_divvyer_not_the_architect_and_its_ledger_line_carries_rung_1(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the recut's ledger line carries no rung, or rung 2; or a first RECUT on a
    # section whose queue names a design goes to the architect instead of the divvyer.
    queue = _ladder(queue_file, cfg, tmp_path)
    split = _renamed(queue, "s1", "s1a", tmp_path / "split.md")
    scenario(_lines(DONE_LEAD))
    leads = [_step(RECUT_LEAD), _step(NO_STATUS_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads, recuts=[_step(DIVVYER_RUN, write=(split, queue))])
    cfg = _with_architect(cfg, tmp_path, [_step(ARCHITECT_APPROVED)])
    cfg = _stop_on_ping(cfg, queue)
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert _runs(tmp_path, "design") == []
    recuts = _runs(tmp_path, "recut")
    assert len(recuts) == 1
    assert RECUT_REASON in str(recuts[0]["prompt"])
    assert "was amended for this problem" not in str(recuts[0]["prompt"])
    assert "Section: s1a" in str(_runs(tmp_path, "lead")[1]["prompt"])
    state = State.open(queue, cfg)
    assert state.section("s1").failures == 0
    assert state.section("s1a").from_recut
    lines = _entries(queue, cfg, "recut")
    assert len(lines) == 1
    assert lines[0]["section"] == "s1"
    assert lines[0].get("rung") == 1
    # relay-ladder-design.md, Why: a ledger line carries a rung only when one is given.
    assert all("rung" not in e for e in _entries(queue, cfg, "lead"))


# Rung 2 from RECUT on a recut section and from DESIGN: the architect's brief holds no guess,
# the divvyer is briefed with the design, the new sections run in the same `relay go`, and the
# `design` and `recut` ledger lines carry rung 2.


@pytest.mark.parametrize("how", ["recut-on-a-recut-section", "design"])
def test_rung_2_runs_the_architect_without_the_guess_then_the_divvyer_with_the_design_and_the_new_sections_in_the_same_go(
    how: str,
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
) -> None:
    # Breaks when: the guess after ` | guess: ` reaches the architect's or the divvyer's brief;
    # the rung-2 recut is briefed without the amended design; the loop stops or parks after
    # the design change instead of running the new section; or the design or recut line
    # carries no rung 2.
    queue = _ladder(queue_file, cfg, tmp_path)
    scenario(_lines(DONE_LEAD))
    reason = f"{PROBLEM} | guess: {GUESS_FIX}"
    if how == "design":
        asker = "s1"
        asking = "sess-design"
        leads = [_step(str(_status_lead(tmp_path, asking, f"DESIGN: {reason}"))), _step(NO_STATUS_LEAD)]
        after = _renamed(queue, "s1", "s1b", tmp_path / "amended.md")
        recuts = [_step(DIVVYER_RUN, write=(after, queue))]
        rungs = [2]
    else:
        asker = "s1a"
        asking = "sess-recut-again"
        first = _renamed(queue, "s1", "s1a", tmp_path / "split.md")
        after = _renamed(first, "s1a", "s1b", tmp_path / "amended.md")
        leads = [
            _step(RECUT_LEAD),
            _step(str(_status_lead(tmp_path, asking, f"RECUT: {reason}"))),
            _step(NO_STATUS_LEAD),
        ]
        recuts = [_step(DIVVYER_RUN, write=(first, queue)), _step(DIVVYER_RUN, write=(after, queue))]
        rungs = [1, 2]
    cfg = _sequenced(cfg, tmp_path, leads, recuts=recuts)
    cfg = _with_architect(cfg, tmp_path, [_step(ARCHITECT_APPROVED)])
    cfg = _stop_on_ping(cfg, queue)
    assert run(queue, cfg) == ExitCode.FAILED_TWICE

    designs = _runs(tmp_path, "design")
    assert len(designs) == 1
    brief = str(designs[0]["prompt"])
    head = brief.splitlines()[0]
    assert head.startswith("rulings ")
    assert head.endswith(f"docs/superpowers/specs/{LADDER_DESIGN}")
    assert PROBLEM in brief
    assert asker in brief
    assert GUESS_FIX not in brief
    assert "guess" not in brief
    assert f"approve: {cfg.design_approval}" in brief
    # relay-ladder-design.md, `_design_change` and `design_brief`: the brief names the asking
    # section's own `steps:` (s1's, which its recut s1a keeps) and, as evidence, the asking
    # lead's run log, plus the section's last check log only when one exists (none ran here).
    assert "under this design's Order 1, 2, cannot go on" in brief
    state = State.open(queue, cfg)
    named = sorted(set(re.findall(re.escape(str(state.run_dir).rstrip("/")) + r"/\d+\.jsonl", brief)))
    assert len(named) == 1, named
    lead_log = Path(named[0])
    assert lead_log.exists()
    assert asking in lead_log.read_text()
    assert not state.check_log(lead_log).exists()
    assert f"Evidence: {lead_log}." in brief

    recut_runs = _runs(tmp_path, "recut")
    assert len(recut_runs) == len(rungs)
    divvyer = str(recut_runs[-1]["prompt"])
    assert "was amended for this problem" in divvyer
    assert f"docs/superpowers/specs/{LADDER_DESIGN}" in divvyer
    assert PROBLEM in divvyer
    assert GUESS_FIX not in divvyer

    assert "Section: s1b" in str(_runs(tmp_path, "lead")[len(rungs)]["prompt"])
    state = State.open(queue, cfg)
    assert state.section(asker).status != "parked"
    assert state.section("s1b").last_session == "sess-lead-2"

    design_lines = _entries(queue, cfg, "design")
    assert len(design_lines) == 1
    assert design_lines[0]["section"] == asker
    assert design_lines[0].get("rung") == 2
    recut_lines = _entries(queue, cfg, "recut")
    assert [e.get("rung") for e in recut_lines] == rungs
    assert recut_lines[-1]["section"] == asker


# Rung 3: a second design change in the lineage, no design line, a rejected or unapproved
# report, a decision parked with its recommendation and then resumed by `relay answer`, a
# section over its queue cap or `--section-dollar-cap`, and a mid-run retire at the cap.

ARCHITECT_DECISION = "stream-architect-decision.jsonl"
ARCHITECT_REJECTED = "stream-architect-rejected.jsonl"
ARCHITECT_UNAPPROVED = "stream-architect-unapproved.jsonl"
DESIGN_PATH = f"docs/superpowers/specs/{LADDER_DESIGN}"
# The decision lines of ARCHITECT_DECISION's report, as written under DECISIONS.
DECISION_1 = "1 | Should two() return 2 when one.py is absent? | recommend: no, fail loudly | alternative: return 2"
DECISION_2 = "2 | Should three() ship in this release? | recommend: yes | alternative: hold it for the next"


def _failed_design(sid: str) -> str:
    """`ladder.failed_text`'s form for the ladder design, with any `what`
    (relay-ladder-design.md, `relay/ladder.py`)."""
    return re.escape(f"the design change for {sid} in ") + r"\S*" + re.escape(f"{DESIGN_PATH} did not land: ") + r".+"


def _section_spent(queue: Path, cfg: Config, sid: str, dollars: float) -> None:
    """One ledger line of an earlier lead on `sid`, spending `dollars`."""
    _ledger(queue, cfg).append("lead", sid, "sess-earlier", Spend(tokens=10, dollars=dollars))


def test_rung_3_a_design_status_under_a_queue_naming_no_design_is_parked_as_no_design_to_amend(
    cfg: Config, tmp_path: Path, scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: DESIGN under a queue with no head design line runs the architect or the
    # divvyer, records a failure, or parks without NO_DESIGN (relay-codex-architect-design.md:64-66).
    queue = _queue_of(tmp_path / "queue.md", "s1")
    scenario(_lines(DONE_LEAD))
    leads = [_step(str(_status_lead(tmp_path, "sess-design", f"DESIGN: {PROBLEM}")))]
    cfg = _sequenced(cfg, tmp_path, leads)
    cfg = _with_architect(cfg, tmp_path, [_step(ARCHITECT_APPROVED)])
    cfg = _stop_on_ping(cfg, queue)
    assert run(queue, cfg) == ExitCode.STOP_FILE
    assert _runs(tmp_path, "design") == []
    assert _runs(tmp_path, "recut") == []
    section = State.open(queue, cfg).section("s1")
    assert section.status == "parked"
    assert section.question == NO_DESIGN
    assert section.failures == 0
    assert section.design_changed is False


@pytest.mark.parametrize("report", [ARCHITECT_REJECTED, ARCHITECT_UNAPPROVED])
def test_rung_3_a_rejected_or_unapproved_design_report_hands_the_section_back_to_its_lead_unparked(
    report: str,
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
) -> None:
    # Breaks when: a rejected or unapproved report goes on to the divvyer, marks the section
    # design_changed, records a failure, parks the section, or the next lead gets no hand-back
    # guidance naming what went wrong (relay-codex-architect-design.md:98-103).
    queue = _ladder(queue_file, cfg, tmp_path)
    scenario(_lines(DONE_LEAD))
    leads = [_step(str(_status_lead(tmp_path, "sess-design", f"DESIGN: {PROBLEM}"))), _step(NO_STATUS_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads)
    cfg = _with_architect(cfg, tmp_path, [_step(report)])
    cfg = _stop_on_ping(cfg, queue)
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert len(_runs(tmp_path, "design")) == 1
    assert _runs(tmp_path, "recut") == []
    leads_run = _runs(tmp_path, "lead")
    assert len(leads_run) == 3
    assert HANDBACK + _WHATS[report] + ")" in str(leads_run[1]["prompt"])
    handback = str(leads_run[1]["prompt"])
    assert _SAIDS[report] in handback[handback.index(HANDBACK + _WHATS[report] + ")") :], handback
    section = State.open(queue, cfg).section("s1")
    assert section.question is None
    # The two failures that end the go are the scripted status-less leads after the hand-back.
    assert section.failures == 2
    assert section.design_changed is False
    assert section.design_open is None
    assert _entries(queue, cfg, "recut") == []


def _lead_tree(tmp_path: Path) -> tuple[Path, str]:
    """A git repository standing in for the lead's worktree, one commit in; (tree, head commit)."""
    tree = tmp_path / "lead-tree"
    tree.mkdir()
    for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "step 21"]):
        subprocess.run([*_GIT, *args], cwd=tree, check=True, capture_output=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tree, check=True, capture_output=True, text=True).stdout.strip()
    return tree, commit


REPORTLESS = "Blocked: the cited Relay log is outside the repository.\n\nEND DESIGN"
REPORTLESS_AGAIN = "Still blocked: Order 3 already covers step 21; the lead should go on."


def test_a_reportless_architect_is_rerun_with_its_message_then_the_section_goes_back_to_its_lead_unparked(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when (owner's ruling, 29 Oct; Gauntlet s2, runs 24-29): an owner answer the lead took
    # never reaches the architect; the brief lacks the section's text or the lead's branch and head
    # commit, or points the architect at the lead's worktree path (outside its repository, which
    # architect.md forbids it to read); a reportless architect is not rerun once with its final
    # message and the reason; or after a second reportless run the section is parked or pinged
    # for the owner, a failure is counted, or the next lead is not given the architect's message.
    queue = _ladder(queue_file, cfg, tmp_path)
    tree, commit = _lead_tree(tmp_path)
    state = State.open(queue, cfg)
    state.set_answer("s1", "Compress the spec throughout.")
    state.set_answer("s1", "The cap stays at 40,000 bytes.")
    scenario(_lines(DONE_LEAD))
    status = f"BRANCH lead/m2-images {tree}\nEND LEAD\nDESIGN: {PROBLEM}"
    leads = [_step(str(_status_lead(tmp_path, "sess-design", status))), _step(NO_STATUS_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads)
    architects = [
        _step(str(_status_lead(tmp_path, "sess-arch", REPORTLESS))),
        _step(str(_status_lead(tmp_path, "sess-arch-2", REPORTLESS_AGAIN))),
    ]
    cfg = _with_architect(cfg, tmp_path, architects)
    cfg = _record_and_stop_on_ping(cfg, queue, tmp_path)
    assert run(queue, cfg) == ExitCode.FAILED_TWICE

    designs = _runs(tmp_path, "design")
    assert len(designs) == 2
    brief = str(designs[0]["prompt"])
    lines = brief.splitlines()
    assert "new: Compress the spec throughout." in lines
    assert "new: The cap stays at 40,000 bytes." in lines
    assert f"branch lead/m2-images at {commit} in this repository" in lines[1]
    assert f"`git show {commit}:<path>`" in lines[1]
    assert f"`git diff main...{commit}`" in lines[1]
    assert str(tree) not in brief
    s1 = next(sec for sec in parse_queue(queue) if sec.id == "s1")
    # relay-codex-architect-design.md:36-39: the section text ends the `lead new:` line, through
    # _ruling, each run of whitespace one space.
    assert "Section text: " + " ".join(s1.body.split()) in lines[1]
    # relay-codex-architect-design.md:41-45: the rerun's brief is the first with one `lead new:`
    # line inserted before its `approve:` line.
    retry = str(designs[1]["prompt"]).splitlines()
    assert lines[-1].startswith("approve: ")
    assert retry[-1] == lines[-1]
    assert retry[:-2] == lines[:-1]
    added = retry[-2]
    assert added.startswith("lead new: ")
    assert "Blocked: the cited Relay log is outside the repository." in added
    assert "its final message had no BRIEF … END DESIGN block" in added

    # The one ping is the go's own stop; none asks the owner anything.
    assert [" ".join(p) for p in _pings(tmp_path)] == ["relay ladder-queue.md: stopped failed twice: section s1 failed twice"]
    assert _runs(tmp_path, "recut") == []
    leads_run = _runs(tmp_path, "lead")
    assert REPORTLESS_AGAIN in str(leads_run[1]["prompt"])
    assert all(REPORTLESS_AGAIN not in str(r["prompt"]) for r in leads_run[2:])
    section = State.open(queue, cfg).section("s1")
    assert section.question is None
    assert section.design_open is None
    assert section.design_changed is False
    # The two failures that end the go are the scripted status-less leads after the hand-back.
    assert section.failures == 2
    assert len(_entries(queue, cfg, "design")) == 2


def test_an_architect_that_files_a_report_on_its_rerun_lands_the_design_change(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: an approved report on the architect's rerun is not acted on as one on its first
    # run would be (the divvyer recuts from the amended design), or the architect runs a third time.
    queue = _ladder(queue_file, cfg, tmp_path)
    scenario(_lines(DONE_LEAD))
    leads = [_step(str(_status_lead(tmp_path, "sess-design", f"DESIGN: {PROBLEM}"))), _step(NO_STATUS_LEAD)]
    after = _renamed(queue, "s1", "s1b", tmp_path / "amended.md")
    cfg = _sequenced(cfg, tmp_path, leads, recuts=[_step(DIVVYER_RUN, write=(after, queue))])
    cfg = _with_architect(cfg, tmp_path, [_step(str(_status_lead(tmp_path, "sess-arch", REPORTLESS))), _step(ARCHITECT_APPROVED)])
    cfg = _stop_on_ping(cfg, queue)
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert len(_runs(tmp_path, "design")) == 2
    assert "was amended for this problem" in str(_runs(tmp_path, "recut")[0]["prompt"])
    state = State.open(queue, cfg)
    assert state.section("s1b").design_changed is True
    assert state.section("s1").status != "parked"


# An architect run that crashes or files no report retries once, then hands the section back to
# its lead with guidance: no park, no failure (relay-codex-architect-design.md, `relay/loop.py`,
# `design_retry_brief`, `handback_text`, `design_retrying`, `design_handed_back`; Order 5).

# The opening of `ladder.handback_text`, up to the `<what>` it carries in brackets.
HANDBACK = "Relay's architect filed no design change for this section's last DESIGN or RECUT ("
STOPPED_FAILED_TWICE = "relay ladder-queue.md: stopped failed twice: section s1 failed twice"


def _architect_run(
    tmp_path: Path, session: str, text: str, *, is_error: bool = False, context: int = 1206, result: bool = True
) -> Path:
    """A scripted architect run in session `session`: one assistant message at `context` context
    tokens, then, when `result`, a result event carrying `text`, marked an error when `is_error`."""
    streams = tmp_path / "streams"
    streams.mkdir(exist_ok=True)
    usage = {"input_tokens": 6, "cache_creation_input_tokens": 200, "cache_read_input_tokens": context - 206, "output_tokens": 30}
    init = {"type": "system", "subtype": "init", "session_id": session, "cwd": "/work", "model": "claude-opus", "tools": ["Bash"]}
    body = {"id": f"msg_{session}", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "Reading."}], "usage": usage}
    lines: list[dict[str, object]] = [init, {"type": "assistant", "message": body, "session_id": session}]
    if result:
        lines.append(
            {
                "type": "result",
                "subtype": "error_during_execution" if is_error else "success",
                "is_error": is_error,
                "duration_ms": 800,
                "num_turns": 1,
                "result": text,
                "session_id": session,
                "total_cost_usd": 0.01,
                "usage": usage,
            }
        )
    path = streams / f"{session}.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


def _architect_goes_wrong(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], architects: list[dict[str, object]]
) -> tuple[Path, Config]:
    """The ladder queue whose lead on s1 asks for DESIGN, then ends with no status line every run
    after; each architect run takes the next of `architects`; every ping is recorded and stops
    the go. Return (queue, cfg)."""
    queue = _ladder(queue_file, cfg, tmp_path)
    leads = [_step(str(_status_lead(tmp_path, "sess-design", f"DESIGN: {PROBLEM}"))), _step(NO_STATUS_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads)
    cfg = _with_architect(cfg, tmp_path, architects)
    return queue, _record_and_stop_on_ping(cfg, queue, tmp_path)


def _retry_line(tmp_path: Path) -> str:
    """The one line the architect's second brief adds to its first: the brief's lines, with one
    line more just before the closing `approve:` line."""
    designs = _runs(tmp_path, "design")
    assert len(designs) == 2, designs
    first = str(designs[0]["prompt"]).splitlines()
    retry = str(designs[1]["prompt"]).splitlines()
    assert first[-1].startswith("approve: "), first
    assert retry[-1] == first[-1], retry
    assert retry[:-2] == first[:-1], retry
    added = retry[-2]
    assert added.startswith("lead new: "), added
    return added


def _seed_design_failures(queue: Path, cfg: Config, count: int) -> None:
    """A persisted record left by earlier architect cycles, before this go starts."""
    state = State.open(queue, cfg)
    state.set_last_session("s1", "earlier-lead")
    path = state.stop_file.parent / "state.json"
    data = json.loads(path.read_text())
    data["sections"]["s1"].update(design_failures=count, design_failure="it filed no report")
    path.write_text(json.dumps(data))


@pytest.mark.parametrize("outcome", ["reportless", "killed", "exit", "error", "zero", "rejected", "unapproved"])
def test_two_unusable_architect_cycles_stop_without_a_budget_or_cap(
    outcome: str, cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path], capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: child invocations count as cycles, or repeated unusable cycles spend forever.
    queue = _ladder(queue_file, cfg, tmp_path)
    queue.write_text(re.sub(r" \| cap: \$[\d.]+", "", queue.read_text()))
    scenario(_lines(DONE_LEAD))
    request = _step(str(_status_lead(tmp_path, "request", f"DESIGN: {PROBLEM}")))
    cfg = _sequenced(cfg, tmp_path, [request, request, _step(NO_STATUS_LEAD)])
    expected_runs = 4
    if outcome in ("rejected", "unapproved"):
        architect = _step(ARCHITECT_REJECTED if outcome == "rejected" else ARCHITECT_UNAPPROVED)
        expected_runs = 2
    else:
        path = _architect_run(tmp_path, "unusable", "API Error: overloaded" if outcome == "error" else REPORTLESS,
                              is_error=outcome == "error", context=cfg.hard_ceiling if outcome == "killed" else 1206,
                              result=outcome != "zero")
        if outcome == "zero":
            path.write_text(path.read_text().splitlines()[0] + "\n")
        architect = _step(str(path), exit=1 if outcome == "exit" else 0)
    cfg = _with_architect(cfg, tmp_path, [architect])
    cfg = _record_and_stop_on_ping(cfg, queue, tmp_path)
    assert cfg.token_budget is None and cfg.dollar_budget is None and cfg.section_dollar_cap is None
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    section = State.open(queue, cfg).section("s1")
    assert section.design_failures == 2
    assert section.design_failure
    assert section.failures == 0
    assert section.status == "open" and section.question is None
    assert len(_runs(tmp_path, "lead")) == 2
    assert len(_runs(tmp_path, "design")) == expected_runs
    assert HANDBACK in str(_runs(tmp_path, "lead")[1]["prompt"])
    assert _runs(tmp_path, "recut") == []
    messages = [" ".join(p) for p in _pings(tmp_path)]
    assert len(messages) == 1
    for detail in ("architect failed repeatedly", "s1", "2", section.design_failure, "relay answer"):
        assert detail in messages[0]
    assert "architect failed repeatedly" in capsys.readouterr().out


@pytest.mark.parametrize("usable", ["decisions", "unfiled", "approved"])
def test_usable_architect_progress_clears_failures_before_park_or_failed_recut(
    usable: str, cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when: usable progress retains the earlier failure, including when its recut fails.
    queue = _ladder(queue_file, cfg, tmp_path)
    _seed_design_failures(queue, cfg, 1)
    park = State.park

    def park_after_reset(self, sid, *args, **kwargs):
        section = State.open(queue, cfg).section(sid)
        assert (section.design_failures, section.design_failure) == (0, None)
        return park(self, sid, *args, **kwargs)

    monkeypatch.setattr(State, "park", park_after_reset)
    scenario(_lines(DONE_LEAD))
    request = _step(str(_status_lead(tmp_path, "request", f"DESIGN: {PROBLEM}")))
    before_recut = tmp_path / "state-before-recut.json"
    state_path = State.open(queue, cfg).stop_file.parent / "state.json"
    cfg = _sequenced(cfg, tmp_path, [request], recuts=[_step(DIVVYER_RUN, exit=1, write=(state_path, before_recut))])
    report = ARCHITECT_APPROVED if usable == "approved" else ARCHITECT_DECISION
    if usable == "unfiled":
        events = [json.loads(line) for line in (FIXTURES / ARCHITECT_DECISION).read_text().splitlines()]
        text = events[-1]["result"]
        text = text.replace(f"  {DECISION_1}\n", "")
        text = text.replace(f"  {DECISION_2}\n", "")
        events[-1]["result"] = text.replace("UNFILED\n", "UNFILED\n  Should two() return 2?\n")
        unfiled = tmp_path / "unfiled.jsonl"
        unfiled.write_text("".join(json.dumps(event) + "\n" for event in events))
        report = str(unfiled)
    cfg = _with_architect(cfg, tmp_path, [_step(report)])
    cfg = _record_and_stop_on_ping(cfg, queue, tmp_path)
    assert run(queue, cfg) == ExitCode.STOP_FILE
    section = State.open(queue, cfg).section("s1")
    assert (section.design_failures, section.design_failure) == (0, None)
    assert section.status == "parked"
    assert len(_runs(tmp_path, "recut")) == (1 if usable == "approved" else 0)
    if usable == "approved":
        section_before_recut = json.loads(before_recut.read_text())["sections"]["s1"]
        assert (section_before_recut["design_failures"], section_before_recut["design_failure"]) == (0, None)


@pytest.mark.parametrize("report", [ARCHITECT_APPROVED, ARCHITECT_DECISION])
def test_zero_token_usable_architect_reports_retry_then_reach_persistent_cycle_bound(
    report: str, cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
) -> None:
    # Breaks when valid report text overrides zero-token failure or clears its cycle count.
    queue = _ladder(queue_file, cfg, tmp_path)
    scenario(_lines(DONE_LEAD))
    events = [json.loads(line) for line in _lines(report)]
    for event in events:
        event.pop("usage", None)
        event.pop("total_cost_usd", None)
        if "message" in event:
            event["message"].pop("usage", None)
    stream = tmp_path / "zero-token-architect.jsonl"
    stream.write_text("".join(json.dumps(event) + "\n" for event in events))
    request = _step(str(_status_lead(tmp_path, "request", f"DESIGN: {PROBLEM}")))
    cfg = _sequenced(cfg, tmp_path, [request])
    cfg = _with_architect(cfg, tmp_path, [_step(str(stream))])
    cfg = _record_and_stop_on_ping(cfg, queue, tmp_path)
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    section = State.open(queue, cfg).section("s1")
    assert section.design_failures == 2 and section.failures == 0
    assert section.status == "open" and section.question is None
    assert len(_runs(tmp_path, "lead")) == 2
    assert len(_runs(tmp_path, "design")) == 4
    assert _runs(tmp_path, "recut") == []
    assert HANDBACK in str(_runs(tmp_path, "lead")[1]["prompt"])
    assert all(entry["tokens"] == 0 for entry in _entries(queue, cfg, "design"))
    assert "architect failed repeatedly" in " ".join(_pings(tmp_path)[0])


@pytest.mark.parametrize("answered", [False, True])
def test_restart_at_architect_bound_launches_nothing_until_explicit_answer(
    answered: bool, cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path], fake_run,
) -> None:
    # Breaks when: a restart launches any agent at the bound, or relay answer cannot recover it.
    queue = _ladder(queue_file, cfg, tmp_path)
    scenario(_lines(DONE_LEAD))
    state = State.open(queue, cfg)
    if answered:
        state.park("s1", "Product choice?", design=(DESIGN_PATH, (1,)))
        state.set_answer("s1", "1: proceed")
    _seed_design_failures(queue, cfg, 2)
    state.set_last_log("s1", _status_lead(tmp_path, "earlier-lead", f"DESIGN: {PROBLEM}"))
    cfg = _sequenced(cfg, tmp_path, [_step(NO_STATUS_LEAD)])
    cfg = _with_architect(cfg, tmp_path, [_step(ARCHITECT_UNAPPROVED)])
    cfg = _record_and_stop_on_ping(cfg, queue, tmp_path)
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert fake_run.calls == []
    assert State.open(queue, cfg).section("s1").design_failures == 2
    State.open(queue, cfg).stop_file.unlink(missing_ok=True)
    assert State.open(queue, cfg).set_answer("s1", "The cause is fixed; retry.")
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert fake_run.calls


def test_answered_design_failure_propagates_architect_stop(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path],
) -> None:
    # Breaks when: the answered-decision path loses an architect stop or launches another lead.
    queue = _ladder(queue_file, cfg, tmp_path)
    state = State.open(queue, cfg)
    state.park("s1", "Product choice?", design=(DESIGN_PATH, (1,)))
    state.set_answer("s1", "1: proceed")
    _seed_design_failures(queue, cfg, 1)
    state.set_last_log("s1", _status_lead(tmp_path, "earlier-lead", f"DESIGN: {PROBLEM}"))
    scenario(_lines(DONE_LEAD))
    cfg = _sequenced(cfg, tmp_path, [_step(NO_STATUS_LEAD)])
    cfg = _with_architect(cfg, tmp_path, [_step(ARCHITECT_UNAPPROVED)])
    cfg = _record_and_stop_on_ping(cfg, queue, tmp_path)
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert len(_runs(tmp_path, "design")) == 1
    assert _runs(tmp_path, "lead") == []
    section = State.open(queue, cfg).section("s1")
    assert section.design_failures == 2 and section.failures == 0
    assert "architect failed repeatedly" in " ".join(_pings(tmp_path)[0])


def test_lead_retirement_keeps_the_previous_architect_cycle_failure(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path],
) -> None:
    # Breaks when: retiring a lead clears its section's earlier architect cycle failure.
    queue = _ladder(queue_file, cfg, tmp_path)
    _seed_design_failures(queue, cfg, 1)
    scenario(_lines(DONE_LEAD))
    request = _step(str(_status_lead(tmp_path, "request", f"DESIGN: {PROBLEM}")))
    cfg = _sequenced(cfg, tmp_path, [_step(RETIRED_LEAD), request, _step(NO_STATUS_LEAD)])
    cfg = _with_architect(cfg, tmp_path, [_step(ARCHITECT_UNAPPROVED)])
    cfg = _record_and_stop_on_ping(cfg, queue, tmp_path)
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    section = State.open(queue, cfg).section("s1")
    assert section.design_failures == 2
    assert section.failures == 0
    assert len(_runs(tmp_path, "lead")) == 2
    assert len(_runs(tmp_path, "design")) == 1


def test_restart_at_architect_bound_stops_before_research_launch(
    cfg: Config, tmp_path: Path, git_repo: GitRepo,
) -> None:
    # Breaks when: the persisted bound is checked after a runnable section starts research.
    _mapped_worktree(git_repo)
    queue = _research_queue(git_repo)
    _done_in_state(queue, cfg, "s2")
    _seed_design_failures(queue, cfg, 2)
    cfg = _researched(cfg, tmp_path, [_step(DONE_LEAD)])
    cfg = _record_and_stop_on_ping(cfg, queue, tmp_path)
    result = run(queue, cfg)
    assert _research_runs(tmp_path) == []
    assert _runs(tmp_path, "lead") == []
    assert result == ExitCode.FAILED_TWICE
    assert State.open(queue, cfg).section("s1").design_failures == 2


def _handed_back_unparked(queue: Path, cfg: Config, tmp_path: Path) -> str:
    """Check the section went back to its lead, parked for no one and with no failure of the
    architect's counted; return the prompt of the lead run straight after the hand-back."""
    # The go ends on the two status-less leads after the hand-back: a counted architect failure
    # would end it after one, and a park would ping and stop it.
    leads = _runs(tmp_path, "lead")
    assert len(leads) == 3, leads
    assert [" ".join(p) for p in _pings(tmp_path)] == [STOPPED_FAILED_TWICE]
    assert _runs(tmp_path, "recut") == []
    section = State.open(queue, cfg).section("s1")
    assert section.question is None
    assert section.design_open is None
    assert section.design_changed is False
    assert section.failures == 2
    assert len(_entries(queue, cfg, "design")) == 2
    return str(leads[1]["prompt"])


@pytest.mark.parametrize("how", ["killed", "nonzero-exit", "backend-error"])
def test_a_failed_architect_run_reruns_once_with_its_error_line_then_goes_back_to_the_lead_with_no_park_and_no_failure(
    how: str,
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a killed, nonzero-exit or backend-error architect run parks the section with
    # failed_text, pings the owner or counts a failure; it is not rerun, or rerun more than once;
    # the rerun's brief lacks a `lead new:` line before `approve:` saying "it failed: <error
    # line>"; the next lead gets no hand-back guidance naming the failure; or the retrying and
    # handed-back progress lines are not written.
    scenario(_lines(DONE_LEAD))
    text = "Blocked: the cited Relay log is outside the repository."
    if how == "killed":
        architect = _step(str(_architect_run(tmp_path, "sess-arch", text, context=cfg.hard_ceiling)))
    elif how == "nonzero-exit":
        architect = _step(str(_architect_run(tmp_path, "sess-arch", text)), exit=1)
    else:
        architect = _step(str(_architect_run(tmp_path, "sess-arch", "API Error: overloaded", is_error=True)))
    queue, cfg = _architect_goes_wrong(cfg, tmp_path, queue_file, [architect])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE

    added = _retry_line(tmp_path)
    assert re.search(r"it failed: \S", added), added
    # relay-codex-architect-design.md:41-45: the `lead new:` line carries the run's error line
    # after "it failed: " and the run's final message. A killed run ends before its result event,
    # so it leaves no final message to carry.
    said = {"killed": None, "nonzero-exit": text, "backend-error": "API Error: overloaded"}[how]
    if said is not None:
        assert said in added, added
    if how == "backend-error":
        assert "it failed: API Error: overloaded" in added, added
    prompt = _handed_back_unparked(queue, cfg, tmp_path)
    assert HANDBACK + "it failed: " in prompt, prompt
    # relay-codex-architect-design.md:68-71, 98-103: the hand-back ends with the architect's final
    # message, on the line after its opening.
    if said is not None:
        assert said in prompt[prompt.index(HANDBACK) :].split("\n", 1)[1], prompt
    texts = _texts(capsys.readouterr().out)
    retrying = [t for t in texts if t.startswith("design s1: it failed: ") and t.endswith("; running the architect again")]
    assert len(retrying) == 1, texts
    back = [t for t in texts if t.startswith("design s1: it failed: ") and t.endswith("; back to the lead with the architect's message")]
    assert len(back) == 1, texts


@pytest.mark.parametrize("how", ["no-report", "stopped-mid-turn"])
def test_a_reportless_architect_run_reruns_once_then_goes_back_to_the_lead_with_no_park_and_no_failure(
    how: str,
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: an architect run with no report, a clean one or one that stops mid-turn with no
    # result, no stderr and no report, parks the section, pings the owner or counts a failure; it
    # is not rerun, or rerun more than once; the rerun's brief lacks a `lead new:` line before
    # `approve:` giving the reason and the run's final message; the next lead gets no hand-back
    # guidance with the architect's message; or the progress lines are not written.
    scenario(_lines(DONE_LEAD))
    if how == "no-report":
        architects = [
            _step(str(_architect_run(tmp_path, "sess-arch", REPORTLESS))),
            _step(str(_architect_run(tmp_path, "sess-arch-2", REPORTLESS_AGAIN))),
        ]
    else:
        architects = [_step(str(_architect_run(tmp_path, "sess-arch", "", result=False)))]
    queue, cfg = _architect_goes_wrong(cfg, tmp_path, queue_file, architects)
    assert run(queue, cfg) == ExitCode.FAILED_TWICE

    added = _retry_line(tmp_path)
    no_block = "BRIEF" in added and "END DESIGN" in added and "it failed: " not in added
    prompt = _handed_back_unparked(queue, cfg, tmp_path)
    texts = _texts(capsys.readouterr().out)
    if how == "no-report":
        assert no_block, added
        assert "Blocked: the cited Relay log is outside the repository." in added, added
        assert HANDBACK + "it filed no report)" in prompt, prompt
        assert REPORTLESS_AGAIN in prompt, prompt
        whats = ["it filed no report"]
    else:
        # A run cut off mid-turn may be judged failed or reportless; either way it is rerun once
        # and handed back.
        assert no_block or re.search(r"it failed: \S", added), added
        assert HANDBACK + "it filed no report)" in prompt or HANDBACK + "it failed: " in prompt, prompt
        whats = ["it filed no report", "it failed: "]
    retrying = [
        t for t in texts
        if any(t.startswith(f"design s1: {w}") for w in whats) and t.endswith("; running the architect again")
    ]
    assert len(retrying) == 1, texts
    back = [
        t for t in texts
        if any(t.startswith(f"design s1: {w}") for w in whats) and t.endswith("; back to the lead with the architect's message")
    ]
    assert len(back) == 1, texts


# A rejected or unapproved run is not rerun: it goes back to the lead with no park; decisions
# still park, a rerun's included; and no rerun once the section cap or the budget is spent
# (relay-codex-architect-design.md, `relay/loop.py` `_architect`, `_design_outcome`; Order 5).

_WHATS = {ARCHITECT_REJECTED: "it rejected the brief as steering", ARCHITECT_UNAPPROVED: "it did not approve the design"}
# A line of each fixture's final message, which the hand-back carries as guidance.
_SAIDS = {
    ARCHITECT_REJECTED: "\"lead's guess, free to ignore: make two() return 2\"",
    ARCHITECT_UNAPPROVED: "Amended the design, but its approve: line does not quote the standing ruling.",
}
CAP_TEXT = re.compile(
    r"section s1 spent \$\d+\.\d\d of its \$5\.00 cap; raise `cap:` in the queue or --section-dollar-cap to go on"
)


@pytest.mark.parametrize("report", [ARCHITECT_REJECTED, ARCHITECT_UNAPPROVED])
def test_a_rejected_or_unapproved_architect_run_goes_back_to_the_lead_with_no_park_no_rerun_and_no_failure(
    report: str,
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a rejected or unapproved architect report parks the section with failed_text,
    # pings the owner, counts a failure or leaves design_open set; it is rerun; it goes on to the
    # divvyer; the next lead gets no hand-back guidance naming what went wrong; or the
    # handed-back progress line is not written.
    scenario(_lines(DONE_LEAD))
    queue, cfg = _architect_goes_wrong(cfg, tmp_path, queue_file, [_step(report)])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE

    what = _WHATS[report]
    assert len(_runs(tmp_path, "design")) == 1
    assert len(_entries(queue, cfg, "design")) == 1
    assert _runs(tmp_path, "recut") == []
    leads = _runs(tmp_path, "lead")
    assert len(leads) == 3, leads
    assert HANDBACK + what + ")" in str(leads[1]["prompt"]), leads[1]["prompt"]
    # relay-codex-architect-design.md:68-71, 98-103: the architect's final message follows as guidance.
    handback = str(leads[1]["prompt"])
    assert _SAIDS[report] in handback[handback.index(HANDBACK + what + ")") :], handback
    assert [" ".join(p) for p in _pings(tmp_path)] == [STOPPED_FAILED_TWICE]
    section = State.open(queue, cfg).section("s1")
    assert section.question is None
    assert section.design_open is None
    assert section.design_changed is False
    assert section.failures == 2
    texts = _texts(capsys.readouterr().out)
    assert f"design s1: {what}; back to the lead with the architect's message" in texts, texts
    assert all(not t.endswith("; running the architect again") for t in texts), texts


def test_a_failed_architect_run_whose_rerun_files_decisions_still_parks_with_the_decisions(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a report with decisions, filed on the rerun after a failed architect run, is
    # handed back to the lead instead of parking the section for the owner with each decision
    # line and the exact design_open destination; the decision is marked as a landed change;
    # false hand-back guidance is emitted; or the failed first run is never rerun.
    scenario(_lines(DONE_LEAD))
    failed = _step(str(_architect_run(tmp_path, "sess-arch", "Blocked.")), exit=1)
    queue, cfg = _architect_goes_wrong(cfg, tmp_path, queue_file, [failed, _step(ARCHITECT_DECISION)])
    assert run(queue, cfg) == ExitCode.STOP_FILE

    assert len(_runs(tmp_path, "design")) == 2
    assert _runs(tmp_path, "recut") == []
    assert len(_runs(tmp_path, "lead")) == 1
    section = State.open(queue, cfg).section("s1")
    assert section.status == "parked"
    assert section.design_open is not None
    assert section.design_open.endswith(DESIGN_PATH)
    assert section.design_open == str((tmp_path / DESIGN_PATH).resolve())
    assert section.design_changed is False
    assert section.question is not None
    assert f"{DESIGN_PATH} needs a product choice:" in section.question
    # The last ping is the stop's own; the park's ping comes before it and carries the decisions.
    pings = _pings(tmp_path)[:-1]
    assert len(pings) == 1, pings
    for line in (DECISION_1, DECISION_2):
        assert line in section.question
        assert line in pings[0][0]
    assert section.failures == 0
    assert (section.design_failures, section.design_failure) == (0, None)
    texts = _texts(capsys.readouterr().out)
    assert all(not t.endswith("; back to the lead with the architect's message") for t in texts), texts


@pytest.mark.parametrize("how", ["nonzero-exit", "backend-error"])
def test_an_architect_run_that_spends_the_section_cap_is_not_rerun_and_the_next_pass_parks_on_the_cap(
    how: str,
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a failed architect run, nonzero exit or backend error, whose spend passes the
    # section's `cap:` is rerun anyway; or it parks the section with failed_text, or counts a
    # failure, instead of handing it back so that the next pass parks it on the cap text.
    scenario(_lines(DONE_LEAD))
    if how == "nonzero-exit":
        architect = _step(str(_architect_run(tmp_path, "sess-arch", "Blocked.")), exit=1)
    else:
        architect = _step(str(_architect_run(tmp_path, "sess-arch", "API Error: overloaded", is_error=True)))
    queue, cfg = _architect_goes_wrong(cfg, tmp_path, queue_file, [architect, _step(ARCHITECT_APPROVED)])
    # s1's `cap: $5` is under its spend before the lead ($4.985) and after it ($4.995), and
    # spent once the architect's $0.01 lands ($5.005).
    _section_spent(queue, cfg, "s1", 4.985)
    assert run(queue, cfg) == ExitCode.STOP_FILE

    assert len(_runs(tmp_path, "design")) == 1
    assert len(_runs(tmp_path, "lead")) == 1
    assert _runs(tmp_path, "recut") == []
    section = State.open(queue, cfg).section("s1")
    assert section.status == "parked"
    assert section.question is not None
    assert CAP_TEXT.fullmatch(section.question)
    assert section.design_open is None
    assert section.failures == 0
    texts = _texts(capsys.readouterr().out)
    assert all(not t.endswith("; running the architect again") for t in texts), texts


@pytest.mark.parametrize("how", ["nonzero-exit", "backend-error"])
def test_an_architect_run_that_spends_the_budget_is_not_rerun_and_the_go_stops_on_the_budget_with_no_park(
    how: str,
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a failed architect run, nonzero exit or backend error, whose spend passes the
    # go's dollar budget is rerun anyway; or it parks the section with failed_text, pings the
    # owner about it or counts a failure, instead of handing it back and letting the budget end
    # the go.
    scenario(_lines(DONE_LEAD))
    if how == "nonzero-exit":
        architect = _step(str(_architect_run(tmp_path, "sess-arch", "Blocked.")), exit=1)
    else:
        architect = _step(str(_architect_run(tmp_path, "sess-arch", "API Error: overloaded", is_error=True)))
    queue, cfg = _architect_goes_wrong(cfg, tmp_path, queue_file, [architect, _step(ARCHITECT_APPROVED)])
    # The lead spends $0.01, under the budget; the architect's $0.01 more passes it.
    cfg = dataclasses.replace(cfg, dollar_budget=0.015)
    assert run(queue, cfg) == ExitCode.BUDGET

    assert len(_runs(tmp_path, "design")) == 1
    assert len(_runs(tmp_path, "lead")) == 1
    assert _runs(tmp_path, "recut") == []
    section = State.open(queue, cfg).section("s1")
    assert section.status == "open"
    assert section.question is None
    assert section.design_open is None
    assert section.failures == 0
    texts = _texts(capsys.readouterr().out)
    assert all(not t.endswith("; running the architect again") for t in texts), texts


def test_rung_3_a_design_decision_parks_with_its_recommendation_and_relay_answer_resumes_the_architect(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
) -> None:
    # Breaks when: a report with decisions parks without each decision line and its
    # recommendation, or without design_open; or the answer runs a lead on the parked section
    # instead of the architect with the answer brief, or does not go on to the rung-2 recut.
    queue = _ladder(queue_file, cfg, tmp_path)
    scenario(_lines(DONE_LEAD))
    after = _renamed(queue, "s1", "s1b", tmp_path / "amended.md")
    leads = [_step(str(_status_lead(tmp_path, "sess-design", f"DESIGN: {PROBLEM}"))), _step(NO_STATUS_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads, recuts=[_step(DIVVYER_RUN, write=(after, queue))])
    cfg = _with_architect(cfg, tmp_path, [_step(ARCHITECT_DECISION), _step(ARCHITECT_APPROVED)])
    state = State.open(queue, cfg)
    loop = _Background(queue, cfg)
    try:
        _until(lambda: len(_pings(tmp_path)) == 1)
        parked = State.open(queue, cfg).section("s1")
        assert parked.status == "parked"
        assert parked.design_open is not None
        assert parked.design_open.endswith(DESIGN_PATH)
        assert parked.question is not None
        assert parked.question.startswith("the design change for s1 in ")
        assert f"{DESIGN_PATH} needs a product choice:" in parked.question
        message = _pings(tmp_path)[0][0]
        for line in (DECISION_1, DECISION_2):
            assert line in parked.question
            assert line in message
        assert len(_runs(tmp_path, "design")) == 1
        assert _runs(tmp_path, "recut") == []
        assert len(_runs(tmp_path, "lead")) == 1
        State.open(queue, cfg).set_answer("s1", "1: no, fail loudly\n2: yes")
        assert loop.finish() == ExitCode.FAILED_TWICE
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    designs = _runs(tmp_path, "design")
    assert len(designs) == 2
    answer = str(designs[1]["prompt"]).splitlines()
    assert answer[0].startswith("rulings ")
    assert answer[0].endswith(DESIGN_PATH)
    assert "1: no, fail loudly" in answer
    assert "2: yes" in answer
    assert answer[-1] == f"approve: {cfg.design_approval}"
    recuts = _runs(tmp_path, "recut")
    assert len(recuts) == 1
    assert "was amended for this problem" in str(recuts[0]["prompt"])
    leads_run = _runs(tmp_path, "lead")
    assert len(leads_run) == 3
    assert all("Section: s1b" in str(r["prompt"]) for r in leads_run[1:])
    state = State.open(queue, cfg)
    assert state.section("s1").design_open is None
    assert state.section("s1b").design_changed is True
    assert len(_entries(queue, cfg, "design")) == 2


def test_rung_3_a_section_over_its_queue_cap_is_parked_before_any_run_whatever_the_section_dollar_cap(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
) -> None:
    # Breaks when: the loop runs a lead on a section whose ledger spend is over its queue `cap:`,
    # lets `section_dollar_cap` override the queue's cap, or parks without the cap text.
    queue = _ladder(queue_file, cfg, tmp_path)
    scenario(_lines(DONE_LEAD))
    _section_spent(queue, cfg, "s1", 5.5)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD)])
    cfg = _with_architect(cfg, tmp_path, [_step(ARCHITECT_APPROVED)])
    cfg = dataclasses.replace(cfg, section_dollar_cap=100.0)
    cfg = _stop_on_ping(cfg, queue)
    assert run(queue, cfg) == ExitCode.STOP_FILE
    assert _runs(tmp_path, "lead") == []
    assert _runs(tmp_path, "design") == []
    section = State.open(queue, cfg).section("s1")
    assert section.status == "parked"
    assert section.question == (
        "section s1 spent $5.50 of its $5.00 cap; raise `cap:` in the queue or --section-dollar-cap to go on"
    )
    assert section.failures == 0


def test_rung_3_a_section_under_its_queue_cap_runs_though_its_spend_is_over_a_lower_section_dollar_cap(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
) -> None:
    # Breaks when: the loop takes the lower of the queue `cap:` and `section_dollar_cap`, or lets
    # `section_dollar_cap` apply at all to a section whose header carries `cap:`, so s1 ($2.00
    # spent, `cap: $5`) is parked on a $1.00 `--section-dollar-cap` (relay-ladder-design.md
    # `section_cap`: "section.dollar_cap when set, else cfg.section_dollar_cap"; `relay/config.py`:
    # "A section's `cap:` overrides `section_dollar_cap` for that section"). The lead parks s1 on
    # its own NEEDS-OWNER question, so the park that ends the run is the lead's, not the cap's.
    queue = _ladder(queue_file, cfg, tmp_path)
    scenario(_lines(DONE_LEAD))
    _section_spent(queue, cfg, "s1", 2.0)
    cfg = _sequenced(cfg, tmp_path, [_step(NEEDS_OWNER_LEAD)])
    cfg = _with_architect(cfg, tmp_path, [_step(ARCHITECT_APPROVED)])
    cfg = dataclasses.replace(cfg, section_dollar_cap=1.0)
    cfg = _stop_on_ping(cfg, queue)
    assert run(queue, cfg) == ExitCode.STOP_FILE
    assert len(_runs(tmp_path, "lead")) == 1
    assert _runs(tmp_path, "design") == []
    section = State.open(queue, cfg).section("s1")
    assert section.status == "parked"
    assert section.question == QUESTION
    assert section.failures == 0


def test_rung_3_a_section_with_no_queue_cap_over_the_section_dollar_cap_is_parked_before_any_run(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
) -> None:
    # Breaks when: `section_dollar_cap` (`--section-dollar-cap`) is not applied to a section
    # whose queue header carries no `cap:`, or the cap text names the wrong spend or cap.
    queue = queue_file(LADDER)
    state = State.open(queue, cfg)
    for sid in ("s1", "s2"):
        state.mark_done(sid)
    scenario(_lines(DONE_LEAD))
    _section_spent(queue, cfg, "s3", 1.5)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD)])
    cfg = dataclasses.replace(cfg, section_dollar_cap=1.0)
    cfg = _stop_on_ping(cfg, queue)
    assert run(queue, cfg) == ExitCode.STOP_FILE
    assert _runs(tmp_path, "lead") == []
    section = State.open(queue, cfg).section("s3")
    assert section.status == "parked"
    assert section.question == (
        "section s3 spent $1.50 of its $1.00 cap; raise `cap:` in the queue or --section-dollar-cap to go on"
    )


def test_rung_3_a_lead_whose_live_spend_passes_the_section_cap_is_retired_mid_run_and_the_next_pass_parks_it(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the watcher weighs the run's own spend alone, or not at all, against the
    # section cap, so it writes no "asked to retire, section cap spent" line; or the next pass
    # runs a fresh lead instead of parking the section with the cap text.
    queue = _ladder(queue_file, cfg, tmp_path)
    scenario(_lines(DONE_LEAD))
    _section_spent(queue, cfg, "s1", 4.95)
    cfg = _sequenced(cfg, tmp_path, [_step(RETIRED_LEAD), _step(NO_STATUS_LEAD)])
    cfg = _with_architect(cfg, tmp_path, [_step(ARCHITECT_APPROVED)])
    cfg = _stop_on_ping(cfg, queue)
    assert run(queue, cfg) == ExitCode.STOP_FILE
    texts = _texts(capsys.readouterr().out)
    assert "lead s1: asked to retire, section cap spent" in texts, texts
    assert len(_runs(tmp_path, "lead")) == 1
    section = State.open(queue, cfg).section("s1")
    assert section.status == "parked"
    assert section.question == (
        "section s1 spent $5.06 of its $5.00 cap; raise `cap:` in the queue or --section-dollar-cap to go on"
    )
    assert section.failures == 0


# The third failed check still parks: under a queue that names a design, three failed checks
# park the section for the owner, with no architect and no recut (relay-ladder-design.md, Why).


def test_the_third_failed_check_under_a_queue_naming_a_design_still_parks_with_no_architect_run(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when: the third failed check climbs the ladder to the architect or the divvyer
    # instead of parking, or parks without the failing check in its ping.
    queue = queue_file(CHECK_QUEUE)
    scenario(_lines(DONE_LEAD))
    _done_in_state(queue, cfg, "s2")
    _failing_check(tmp_path, monkeypatch)
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_LEAD)])
    cfg = _with_architect(cfg, tmp_path, [_step(ARCHITECT_APPROVED)])
    state = State.open(queue, cfg)
    loop = _Background(queue, cfg)
    try:
        _until(lambda: len(_pings(tmp_path)) == 1)
        section = State.open(queue, cfg).section("s1")
        assert section.status == "parked"
        assert section.check_failures == 3
        assert section.failures == 0
        assert section.design_changed is False
        assert section.design_open is None
        assert FAIL_MARK in _pings(tmp_path)[0][0]
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    assert loop.finish() == ExitCode.STOP_FILE
    assert len(_runs(tmp_path, "lead")) == 3
    assert _runs(tmp_path, "design") == []
    assert _runs(tmp_path, "recut") == []


# Auto-wake (relay-ladder-design.md, Order 8; `_wait`, `_wake`, `_landed`): `WAITING: <id>` holds
# the section with no ping until queue section <id> lands. A blocker still in the queue has
# landed when it is done and `git.clean` on its section worktree is not False (with no worktree,
# done is enough); a blocker gone from the queue has landed when every section whose `from:`
# names it has landed. An unknown, self, landed or cyclic blocker parks the section instead.

WOKEN = "section s1: woken, s2 landed"


def _waiting_lead(tmp_path: Path, session: str, blocker: str) -> dict[str, object]:
    """A lead step in session `session` ending `WAITING: <blocker>`."""
    return _step(str(_status_lead(tmp_path, session, f"WAITING: {blocker}")))


def _repo_queue(repo: GitRepo) -> Path:
    """Sections s1 and s2, neither depending on the other, in the repository's main checkout."""
    return _queue_of(repo.root / "queue.md", "s1", "s2")


def _stop_lead(queue: Path, cfg: Config) -> dict[str, object]:
    """A lead step past the ones a test scripts: it touches the stop file and ends with no status
    line, so a loop that runs one lead more than the behavior allows stops with `STOP_FILE` and
    the test's count of lead runs fails, instead of the plan's last step running forever."""
    stop = State.open(queue, cfg).stop_file
    touch = [sys.executable, "-I", "-S", "-c", "import pathlib, sys; pathlib.Path(sys.argv[1]).touch()", str(stop)]
    return _step(NO_STATUS_LEAD, then=touch)


@pytest.fixture
def stop_after() -> Iterator[Callable[[Path, Config], None]]:
    """Arm a watchdog that touches the queue's stop file 15 seconds on, so a loop left holding or
    waiting where the behavior says it wakes or stops ends with `STOP_FILE` and the test's own
    asserts fail, instead of the run never returning; every watchdog is cancelled at teardown."""
    timers: list[threading.Timer] = []

    def arm(queue: Path, cfg: Config) -> None:
        timer = threading.Timer(15.0, State.open(queue, cfg).stop_file.touch)
        timer.daemon = True
        timer.start()
        timers.append(timer)

    yield arm
    for timer in timers:
        timer.cancel()


def test_waiting_holds_the_section_on_its_blocker_with_no_ping_while_the_loop_goes_on(
    cfg: Config,
    tmp_path: Path,
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: WAITING parks the section, pings the owner, counts a failure, or leaves it
    # open so its lead runs again before its blocker lands; or no "waiting on" line is written.
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    scenario(_lines(DONE_LEAD))
    cfg = _sequenced(cfg, tmp_path, [_waiting_lead(tmp_path, "sess-wait", "s2"), _step(NEEDS_OWNER_LEAD)])
    state = State.open(queue, cfg)
    loop = _Background(queue, cfg)
    try:
        _until(lambda: State.open(queue, cfg).section("s2").status == "parked")
        loop.wait_for_pass()
        assert loop.still_running()
        waiting = State.open(queue, cfg).section("s1")
        assert waiting.status == "waiting"
        assert waiting.waits_on == "s2"
        assert waiting.failures == 0
        runs = _runs(tmp_path, "lead")
        assert len(runs) == 2
        assert _body(queue, "s2") in str(runs[1]["prompt"])
        pings = _pings(tmp_path)
        assert len(pings) == 1
        assert QUESTION in pings[0][0]
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    assert loop.finish() == ExitCode.STOP_FILE
    assert "section s1: waiting on s2" in _texts(capsys.readouterr().out)


def test_a_waiting_section_wakes_once_its_blocker_is_done_with_a_clean_worktree_and_sends_no_ping(
    cfg: Config,
    tmp_path: Path,
    git_repo: GitRepo,
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
    stop_after: Callable[[Path, Config], None],
) -> None:
    # Breaks when: a blocker done in state with a clean `lead/<sid>` worktree does not wake its
    # waiter, the wake pings the owner, or no "woken" line is written.
    queue = _repo_queue(git_repo)
    git_repo.worktree("s2")
    scenario(_lines(DONE_LEAD))
    leads = [_waiting_lead(tmp_path, "sess-wait", "s2"), _step(DONE_LEAD), _step(DONE_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads)
    stop_after(queue, cfg)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    runs = _runs(tmp_path, "lead")
    assert len(runs) == 3
    assert _body(queue, "s2") in str(runs[1]["prompt"])
    assert _body(queue, "s1") in str(runs[2]["prompt"])
    state = State.open(queue, cfg)
    assert state.section("s1").status == "done"
    assert state.section("s1").waits_on is None
    # The one ping is the stop's own: every stop sends one stopped ping.
    assert len(_pings(tmp_path)) == 1
    assert WOKEN in _texts(capsys.readouterr().out)


def test_a_waiting_section_stays_held_while_its_done_blockers_worktree_is_dirty_and_wakes_once_it_is_clean(
    cfg: Config,
    tmp_path: Path,
    git_repo: GitRepo,
    scenario: Callable[[list[str]], Path],
) -> None:
    # Breaks when: `_landed` takes a done blocker as landed though `git.clean` on its section
    # worktree is False, or never tests it again, so the waiter wakes early or never.
    queue = _repo_queue(git_repo)
    stray = git_repo.worktree("s2") / "stray.txt"
    stray.write_text("uncommitted\n")
    scenario(_lines(DONE_LEAD))
    leads = [_waiting_lead(tmp_path, "sess-wait", "s2"), _step(DONE_LEAD), _step(DONE_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads)
    state = State.open(queue, cfg)
    loop = _Background(queue, cfg)
    try:
        _until(lambda: State.open(queue, cfg).section("s2").status == "done")
        loop.wait_for_pass()
        assert loop.still_running()
        assert State.open(queue, cfg).section("s1").status == "waiting"
        assert len(_runs(tmp_path, "lead")) == 2
        stray.unlink()
        assert loop.finish() == ExitCode.QUEUE_EMPTY
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    runs = _runs(tmp_path, "lead")
    assert len(runs) == 3
    assert _body(queue, "s1") in str(runs[2]["prompt"])
    assert State.open(queue, cfg).section("s1").status == "done"


def test_a_waiting_section_wakes_only_after_every_recut_sibling_of_its_blocker_lands(
    cfg: Config,
    tmp_path: Path,
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
    stop_after: Callable[[Path, Config], None],
) -> None:
    # Breaks when: a blocker the divvyer recut away counts as landed (or unknown) at once, or
    # once its first `from:` sibling is done, so the waiter runs before s2b; or it never wakes.
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    siblings = tmp_path / "siblings.md"
    siblings.write_text(
        "section s1 | lead | steps: 1\n  s1 work\n"
        "section s2a | lead | steps: 1 | from: s2\n  s2a work\n"
        "section s2b | lead | steps: 1 | from: s2\n  s2b work\n"
    )
    scenario(_lines(DONE_LEAD))
    leads = [_waiting_lead(tmp_path, "sess-wait", "s2"), _step(RECUT_LEAD)] + [_step(DONE_LEAD)] * 3
    cfg = _sequenced(cfg, tmp_path, leads, recuts=[_step(DIVVYER_RUN, write=(siblings, queue))])
    stop_after(queue, cfg)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert len(_runs(tmp_path, "recut")) == 1
    runs = [str(r["prompt"]) for r in _runs(tmp_path, "lead")]
    assert len(runs) == 5
    assert "s1 work" in runs[0]
    assert "s2 work" in runs[1]
    assert "s2a work" in runs[2]
    assert "s2b work" in runs[3]
    assert "s1 work" in runs[4]
    state = State.open(queue, cfg)
    assert state.section("s1").status == "done"
    assert state.section("s1").waits_on is None
    assert len(_pings(tmp_path)) == 1
    assert WOKEN in _texts(capsys.readouterr().out)


@pytest.mark.parametrize("blocker", ["unknown", "self", "landed", "depends-on-the-section"])
def test_waiting_on_an_unknown_self_landed_or_dependent_blocker_parks_the_section_with_a_ping(
    blocker: str,
    cfg: Config,
    tmp_path: Path,
    scenario: Callable[[list[str]], Path],
    stop_after: Callable[[Path, Config], None],
) -> None:
    # Breaks when: `_wait` holds the section as waiting on a blocker that is not in the queue,
    # is the section itself, has already landed, or depends on the section, instead of parking
    # it for the owner with a ping and a reason.
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    waits_for = {"unknown": "s9", "self": "s1", "landed": "s2", "depends-on-the-section": "s2"}[blocker]
    if blocker == "landed":
        State.open(queue, cfg).mark_done("s2")
    if blocker == "depends-on-the-section":
        _with_depends(queue, {"s2": "s1"})
    scenario(_lines(DONE_LEAD))
    cfg = _sequenced(cfg, tmp_path, [_waiting_lead(tmp_path, "sess-wait", waits_for), _stop_lead(queue, cfg)])
    cfg = _record_and_stop_on_ping(cfg, queue, tmp_path)
    stop_after(queue, cfg)
    assert run(queue, cfg) == ExitCode.STOP_FILE
    assert len(_runs(tmp_path, "lead")) == 1
    assert _runs(tmp_path, "recut") == []
    section = State.open(queue, cfg).section("s1")
    assert section.status == "parked"
    assert section.question
    assert section.waits_on is None
    assert section.failures == 0
    # The last ping is the stop's own; the park's ping comes before it and carries its reason.
    parked = [p for p in _pings(tmp_path)[:-1] if section.question in p[0]]
    assert len(parked) == 1


def test_waiting_on_a_section_that_waits_on_it_parks_the_second_waiter_with_a_ping(
    cfg: Config,
    tmp_path: Path,
    scenario: Callable[[list[str]], Path],
    stop_after: Callable[[Path, Config], None],
) -> None:
    # Breaks when: `_wait` misses a cycle through `waits_on`, so s2 waits on s1 while s1 waits
    # on s2 and neither ever wakes.
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    scenario(_lines(DONE_LEAD))
    leads = [_waiting_lead(tmp_path, "sess-wait-1", "s2"), _waiting_lead(tmp_path, "sess-wait-2", "s1")]
    cfg = _sequenced(cfg, tmp_path, leads + [_stop_lead(queue, cfg)])
    cfg = _record_and_stop_on_ping(cfg, queue, tmp_path)
    stop_after(queue, cfg)
    assert run(queue, cfg) == ExitCode.STOP_FILE
    assert len(_runs(tmp_path, "lead")) == 2
    state = State.open(queue, cfg)
    assert state.section("s1").status == "waiting"
    assert state.section("s1").waits_on == "s2"
    cycled = state.section("s2")
    assert cycled.status == "parked"
    assert cycled.question
    assert cycled.waits_on is None
    assert cycled.failures == 0
    # The last ping is the stop's own; s2's park ping comes before it and carries its reason.
    parked = [p for p in _pings(tmp_path)[:-1] if cycled.question in p[0]]
    assert len(parked) == 1


@pytest.mark.parametrize("through", ["depends_on", "waits_on"])
def test_waiting_on_a_blocker_recut_out_of_the_queue_whose_recut_section_needs_the_waiter_parks_it_with_a_ping(
    through: str,
    cfg: Config,
    tmp_path: Path,
    scenario: Callable[[list[str]], Path],
    stop_after: Callable[[Path, Config], None],
) -> None:
    # Breaks when: `_wait` checks only the blocker's own `waits_on` and `depends_on`, so s1 is
    # set waiting on s2, which the divvyer recut into s2a (`from: s2`), though s2a depends on s1
    # or waits on s1: s2 then lands only after s1 does, and s1 waits forever with no ping.
    queue = _queue_of(tmp_path / "queue.md", "s2", "s1")
    recut = tmp_path / "recut.md"
    # The queue runs its first open section not blocked: s1 first where s2a depends on it, and
    # s2a first where it is to wait on s1.
    s1 = "section s1 | lead | steps: 1\n  s1 work\n"
    if through == "depends_on":
        recut.write_text(s1 + "section s2a | lead | steps: 1 | from: s2 | depends: s1\n  s2a work\n")
    else:
        recut.write_text("section s2a | lead | steps: 1 | from: s2\n  s2a work\n" + s1)
    scenario(_lines(DONE_LEAD))
    leads = [_step(RECUT_LEAD)]
    if through == "waits_on":
        leads.append(_waiting_lead(tmp_path, "sess-wait-2a", "s1"))
    leads += [_waiting_lead(tmp_path, "sess-wait-1", "s2"), _stop_lead(queue, cfg)]
    cfg = _sequenced(cfg, tmp_path, leads, recuts=[_step(DIVVYER_RUN, write=(recut, queue))])
    cfg = _record_and_stop_on_ping(cfg, queue, tmp_path)
    stop_after(queue, cfg)
    assert run(queue, cfg) == ExitCode.STOP_FILE
    assert len(_runs(tmp_path, "recut")) == 1
    runs = [str(r["prompt"]) for r in _runs(tmp_path, "lead")]
    assert len(runs) == len(leads) - 1
    assert "s1 work" in runs[-1]
    state = State.open(queue, cfg)
    cycled = state.section("s1")
    assert cycled.status == "parked"
    assert cycled.question
    assert cycled.waits_on is None
    assert cycled.failures == 0
    # The last ping is the stop's own; s1's park ping comes before it and carries its reason.
    parked = [p for p in _pings(tmp_path)[:-1] if cycled.question in p[0]]
    assert len(parked) == 1
# Order 17, behavior 5: run a lead with `resume` set to the section's `last_session`, or else
# `last_session_any`, and `report` set to the section's own `last_report`. A report from another
# section is never passed, even when `resume` comes from `last_session_any`.
# Order 17, behavior 6: 7. Append the run's spend to the ledger, record its session, and record
# `result.stream.result_text` with `set_last_report`; a run with no result text clears it.
# `getattr` with a default keeps a missing `last_report` or `set_last_report` an assertion
# failure, not an AttributeError.

# The result texts of the scripted leads, verbatim.
DONE_LEAD_REPORT = "Step committed.\nDONE"
NO_STATUS_LEAD_REPORT = "Prompt is too long"
RETIRED_LEAD_REPORT = "Step committed; retire flag found.\nRETIRED"

OWN_REPORT = "Step 1 of s1 committed at 4d5e6f.\nRETIRED"
OTHER_REPORT = "Step 3 of another section committed at 7a8b9c.\nRETIRED"


def _set_last_report(state: State, sid: str, report: str) -> None:
    setter = getattr(state, "set_last_report", None)
    assert setter is not None, "State.set_last_report"
    setter(sid, report)


def _last_report(queue: Path, cfg: Config, sid: str) -> object:
    return getattr(State.open(queue, cfg).section(sid), "last_report", "missing")


def test_the_lead_is_given_its_sections_own_last_report(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop passes no report, or another section's, though the section has its own.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first, other = _open_ids(queue)[:2]
    state = State.open(queue, cfg)
    state.set_last_session(first, "sess-own")
    _set_last_report(state, first, OWN_REPORT)
    state.set_last_session(other, "sess-other")
    _set_last_report(state, other, OTHER_REPORT)
    run(queue, _shimmed(cfg, tmp_path))
    prompt = str(_record(tmp_path, 0)["prompt"])
    assert "resume sess-own" in prompt
    assert OWN_REPORT in prompt
    assert OTHER_REPORT not in prompt


def test_a_report_from_another_section_is_never_passed_when_resume_comes_from_last_session_any(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop takes the report from the section whose session it resumes.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    other = _open_ids(queue)[1]
    state = State.open(queue, cfg)
    state.set_last_session(other, "sess-other")
    _set_last_report(state, other, OTHER_REPORT)
    run(queue, _shimmed(cfg, tmp_path))
    prompt = str(_record(tmp_path, 0)["prompt"])
    assert "resume sess-other" in prompt
    assert OTHER_REPORT not in prompt


def test_a_fresh_lead_after_a_retired_one_is_given_the_retired_leads_final_report(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop never records the result text, or never passes it to the next lead.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    _only_first_open(queue, cfg)
    cfg = _sequenced(cfg, tmp_path, [_step(RETIRED_LEAD), _step(DONE_SMALL_LEAD)])
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    runs = _runs(tmp_path, "lead")
    assert len(runs) == 2, f"{len(runs)} lead runs"
    assert RETIRED_LEAD_REPORT not in str(runs[0]["prompt"]), "report passed to the first lead"
    assert "resume sess-lead-3" in str(runs[1]["prompt"]), "resume after the retire"
    assert RETIRED_LEAD_REPORT in str(runs[1]["prompt"]), "report passed after the retire"


def test_each_lead_runs_result_text_is_recorded_as_its_sections_last_report(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop records no report, records it on another section, or alters it.
    queue = queue_file(M2)
    scenario(_lines(DONE_LEAD))
    run(queue, cfg)
    for sid in _open_ids(queue):
        assert _last_report(queue, cfg, sid) == DONE_LEAD_REPORT, sid


def test_a_failed_lead_runs_result_text_is_recorded_too(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the loop records the report only for a run that ends with a valid status.
    queue = queue_file(WORKBOARD)
    scenario(_lines(NO_STATUS_LEAD))
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    first = _open_ids(queue)[0]
    assert _last_report(queue, cfg, first) == NO_STATUS_LEAD_REPORT, "failed lead's report"
    assert _last_report(queue, cfg, _open_ids(queue)[1]) is None, "untouched section's report"


def test_a_run_with_no_result_text_clears_the_sections_last_report(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: a killed run, which has no result text, leaves the earlier lead's report in place.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    first = _only_first_open(queue, cfg)
    cfg = dataclasses.replace(cfg, context_limit=FIRST_CONTEXT - 200, hard_ceiling=FIRST_CONTEXT)
    cfg = _sequenced(cfg, tmp_path, [_step(RETIRED_LEAD), _step(DONE_LEAD)])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    runs = _runs(tmp_path, "lead")
    assert len(runs) == 3, f"{len(runs)} lead runs"
    assert RETIRED_LEAD_REPORT in str(runs[1]["prompt"]), "report passed after the retire"
    assert RETIRED_LEAD_REPORT not in str(runs[2]["prompt"]), "report passed after the kill"
    assert _last_report(queue, cfg, first) is None, "report left after the kill"


# A research run that fails (killed, exited nonzero, its result marked as an error, or used no
# tokens) is reported as failed with its error line, the last non-empty line of the run's stderr,
# else the error result's text, else "killed", else "used no tokens", else "exit N", in both the
# progress output and a ping; the lead then starts without a map (owner's behavior;
# relay-research-design.md:105, 110, 213, 247). The plan
# step's `then` command writes the run's stderr before the fake streams. NO_STATUS_LEAD's result
# is marked as an error with the text "Prompt is too long"; an empty scenario uses no tokens.
_STDERR = "import sys; sys.stderr.write(sys.argv[1])"
ERROR_RESULT_TEXT = "Prompt is too long"


def _stderr(text: str) -> list[str]:
    return [sys.executable, "-c", _STDERR, text]


_FAILED_RESEARCH = {
    "exit-nonzero-with-stderr": (
        _step(RESEARCH_RUN, exit=1, then=_stderr("warming up\nresearch crashed: reader died\n\n")),
        False,
        "research crashed: reader died",
    ),
    "error-result": (_step(NO_STATUS_LEAD), False, ERROR_RESULT_TEXT),
    "error-result-with-stderr": (
        _step(NO_STATUS_LEAD, then=_stderr("api overloaded, retry later\n")),
        False,
        "api overloaded, retry later",
    ),
    "exit-nonzero-bare": (_step(RESEARCH_RUN, exit=9), False, "exit 9"),
    "killed-with-stderr": (_step(RESEARCH_RUN, then=_stderr("reader pool exhausted\n")), True, "reader pool exhausted"),
    "no-tokens": (dict(_step(RESEARCH_RUN), scenario=os.devnull), False, "used no tokens"),
}


@pytest.mark.parametrize("how", list(_FAILED_RESEARCH))
def test_a_research_run_that_fails_reports_its_error_line_in_progress_and_a_ping_and_the_lead_starts_without_a_map(
    how: str,
    cfg: Config,
    tmp_path: Path,
    git_repo: GitRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a failed research run is reported only as "no usable map", its progress line or
    # ping lacks the error line, the error line is taken from the wrong source (not stderr's last
    # non-empty line first, then the error result's text, then "exit N"), a run that used no
    # tokens or whose result is an error counts as a success, or the lead does not start.
    step, killed, error = _FAILED_RESEARCH[how]
    _mapped_worktree(git_repo)
    queue = _research_queue(git_repo)
    _done_in_state(queue, cfg, "s2")
    _check_script(tmp_path, monkeypatch, 0)
    if killed:
        cfg = dataclasses.replace(cfg, context_limit=RESEARCH_CONTEXT - 50, hard_ceiling=RESEARCH_CONTEXT)
    fake = cfg.lead_command[0]
    cfg = _sequenced(cfg, tmp_path, [_step(DONE_SMALL_LEAD)])
    research = _plan(tmp_path, fake, "research", [step], False)
    cfg = dataclasses.replace(cfg, research_command=research)
    assert run(queue, cfg) == ExitCode.QUEUE_EMPTY
    assert len(_research_runs(tmp_path)) == 1
    leads = _runs(tmp_path, "lead")
    assert len(leads) == 1
    prompt = str(leads[0]["prompt"])
    assert "map s1 at" not in prompt
    assert "END MAP" not in prompt
    section = State.open(queue, cfg).section("s1")
    assert section.failures == 0
    assert section.status == "done"
    texts = _texts(capsys.readouterr().out)
    # The section's "mapping in <cwd>" line is set aside: pytest's tmp_path carries this test's name.
    finished = [t for t in texts if t.startswith("research s1: ") and not t.startswith("research s1: mapping in ")]
    reported = [t for t in finished if "fail" in t]
    assert len(reported) == 1, texts
    form = rf"research s1: failed: {re.escape(error)} \(\d+ tokens, \$\d+\.\d\d\); the lead starts without a map"
    assert re.fullmatch(form, reported[0]), texts
    assert not any(t.startswith("research s1: no usable map ") for t in texts), texts
    pings = [p[0] for p in _pings(tmp_path) if "research s1" in p[0] or "fail" in p[0]]
    assert pings == [f"relay {queue.name}: research s1 failed: {error}; the lead starts without a map"], _pings(tmp_path)
