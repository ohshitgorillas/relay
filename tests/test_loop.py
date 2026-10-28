"""Red tests for Relay's loop (design: Modules `relay/loop.py`, its pass steps 1 to 5; Order 13)."""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import pytest

from relay.config import Config
from relay.errors import ExitCode, LockedError
from relay.loop import run
from relay.queue import blocked_by, parse_queue
from relay.state import State

FIXTURES = Path(__file__).parent / "fixtures"
WORKBOARD = "workboard-queue.md"
M2 = "m2-rest-queue.md"

# The scripted lead whose result ends "DONE" (session "sess-lead-1"), and the one whose
# result carries no status line (session "sess-lead-2").
DONE_LEAD = "stream-lead.jsonl"
NO_STATUS_LEAD = "stream-error.jsonl"

# A ping command that appends its argv (after the record path) as one JSON line to the record path.
_RECORD = "import sys, json; f = open(sys.argv[1], 'a'); f.write(json.dumps(sys.argv[2:]) + chr(10)); f.close()"

# Long enough for many `poll_seconds` (0.05 in `fake_cfg`) to pass.
SETTLE = 0.5


def _lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text().splitlines()


@pytest.fixture
def cfg(fake_cfg: Config, tmp_path: Path) -> Config:
    """`fake_cfg` with its pings recorded to `<tmp_path>/pings.jsonl`, and `tmp_path` a git work tree."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    record = tmp_path / "pings.jsonl"
    return dataclasses.replace(fake_cfg, ping_command=[sys.executable, "-c", _RECORD, str(record), "{message}"])


def _pings(tmp_path: Path) -> list[list[str]]:
    record = tmp_path / "pings.jsonl"
    if not record.exists():
        return []
    return [json.loads(line) for line in record.read_text().splitlines()]


def _open_ids(queue: Path) -> list[str]:
    """Ids of the sections the queue itself leaves open, in queue order."""
    return [s.id for s in parse_queue(queue) if s.open]


def _ledger_line(state: State, stamp: float, tokens: int, dollars: float) -> None:
    """Append one readable ledger line stamped `stamp` to `<state dir>/ledger.jsonl`."""
    path = state.stop_file.parent / "ledger.jsonl"
    with path.open("a") as f:
        f.write(json.dumps({"time": stamp, "tokens": tokens, "dollars": dollars}) + "\n")


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


class _Background:
    """One `run` on a daemon thread, so a test can act while the loop waits."""

    def __init__(self, queue: Path, cfg: Config) -> None:
        self.result: int | None = None
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._body, args=(queue, cfg), daemon=True)
        self.thread.start()

    def _body(self, queue: Path, cfg: Config) -> None:
        try:
            self.result = run(queue, cfg)
        except BaseException as exc:  # carried to the test thread
            self.error = exc

    def still_running(self) -> bool:
        """True while `run` has not returned; re-raises what `run` raised."""
        if self.thread.is_alive():
            return True
        if self.error is not None:
            raise self.error
        return False

    def finish(self, timeout: float = 15.0) -> int | None:
        self.thread.join(timeout)
        assert not self.thread.is_alive(), "run did not return"
        if self.error is not None:
            raise self.error
        return self.result


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
    run(queue, cfg)
    first = _open_ids(queue)[0]
    assert _ran_on(queue, cfg, "sess-lead-2") == {first}
    state = State.open(queue, cfg)
    assert state.section(first).failures >= 1
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


@pytest.mark.parametrize("name", [WORKBOARD, M2])
def test_a_parked_section_and_every_section_it_blocks_are_passed_over(
    name: str, cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(name)
    scenario(_lines(NO_STATUS_LEAD))
    ids = _open_ids(queue)
    parked = ids[0]
    State.open(queue, cfg).park(parked, "Which port should the server use?")
    blocked = blocked_by(parse_queue(queue), {parked})
    expected = next(sid for sid in ids if sid != parked and sid not in blocked)
    run(queue, cfg)
    assert _ran_on(queue, cfg, "sess-lead-2") == {expected}
    assert State.open(queue, cfg).section(parked).status == "parked"


def test_a_section_parked_mid_queue_is_passed_over_for_the_next_unblocked_one(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(WORKBOARD)
    scenario(_lines(NO_STATUS_LEAD))
    ids = _open_ids(queue)
    state = State.open(queue, cfg)
    state.mark_done(ids[0])
    state.park(ids[1], "Keep the v1 routes?")
    blocked = blocked_by(parse_queue(queue), {ids[1]})
    expected = next(sid for sid in ids[2:] if sid not in blocked)
    run(queue, cfg)
    assert _ran_on(queue, cfg, "sess-lead-2") == {expected}


def test_each_pass_re_parses_the_queue(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(WORKBOARD)
    scenario(_lines(NO_STATUS_LEAD))
    parked = _open_ids(queue)[0]
    state = _park_all_but_done(queue, cfg, parked)
    loop = _Background(queue, cfg)
    try:
        time.sleep(SETTLE)
        assert loop.still_running()
        queue.write_bytes((FIXTURES / M2).read_bytes())
        State.open(queue, cfg).set_answer(parked, "Use port 8080.")
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
        time.sleep(SETTLE)
        assert loop.still_running()
        assert State.open(queue, cfg).section(parked).status == "parked"
        assert State.open(queue, cfg).section(parked).last_session is None
    finally:
        state.stop_file.touch()
        loop.thread.join(15)


def test_a_stop_file_created_while_waiting_stops_with_stop_file(
    cfg: Config, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    parked = _open_ids(queue)[0]
    state = _park_all_but_done(queue, cfg, parked)
    loop = _Background(queue, cfg)
    try:
        time.sleep(SETTLE)
        assert loop.still_running()
        State.open(queue, cfg).stop_file.touch()
        assert loop.finish(timeout=5.0) == ExitCode.STOP_FILE
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
        time.sleep(SETTLE)
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
        time.sleep(SETTLE)
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
        time.sleep(SETTLE)
        assert loop.still_running()
        time.sleep(SETTLE)
        assert loop.still_running()
        assert _pings(tmp_path) == []
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
