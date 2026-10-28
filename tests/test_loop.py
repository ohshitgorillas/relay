"""Red tests for Relay's loop (design: Modules `relay/loop.py`, its pass steps 1 to 8, its stops and the lead's cwd; Order 13)."""

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
from relay.ledger import Ledger, Spend
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


# Behaviors 7 to 11 (pass steps 6 and 7, and the lead's cwd) watch each lead through a
# recording shim put in front of the fake `claude`. The shim reads the lead's prompt on stdin
# and writes `{"cwd", "prompt", "appeared"}` to `<record dir>/run-<n>.json`, n counting from 0.
# It then runs the fake on the scenario's first `split` lines, and, when `split` is above 0,
# watches for up to WATCH seconds for a path the prompt names that did not exist when the lead
# started (the retire flag), before running the fake on the rest. Every stream line it emits
# is the fake's, from the scenario `RELAY_FAKE_SCENARIO` names.
_SHIM = r"""
import json, os, re, subprocess, sys, time
rec, fake, split, watch = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
prompt = sys.stdin.read()
runs = [n for n in os.listdir(rec) if n.startswith("run-") and n.endswith(".json")]
out = os.path.join(rec, "run-%d.json" % len(runs))
def save(appeared):
    with open(out + ".part", "w") as f:
        json.dump({"cwd": os.getcwd(), "prompt": prompt, "appeared": appeared}, f)
    os.replace(out + ".part", out)
save([])
paths = sorted({p.rstrip(".,;:)") for p in re.findall(r"/[^\s`'\"<>]+", prompt)})
before = {p for p in paths if os.path.exists(p)}
lines = open(os.environ["RELAY_FAKE_SCENARIO"]).read().splitlines()
def emit(part, name):
    path = os.path.join(rec, name)
    with open(path, "w") as f:
        f.write("".join(line + "\n" for line in part))
    env = dict(os.environ, RELAY_FAKE_SCENARIO=path)
    sys.stdout.flush()
    subprocess.run([fake], stdin=subprocess.DEVNULL, env=env, check=True)
if split > 0:
    emit(lines[:split], "part-1.txt")
    appeared = []
    end = time.time() + watch
    while not appeared and time.time() < end:
        appeared = [p for p in paths if p not in before and os.path.exists(p)]
        time.sleep(0.02)
    save(appeared)
    emit(lines[split:], "part-2.txt")
else:
    emit(lines, "part-1.txt")
"""

# Seconds the shim watches for the retire flag.
WATCH = 1.0

# In DONE_LEAD, the first assistant message (line 1) leaves context_tokens at 3 + 1200 + 5000
# and spend.tokens at 3 + 1200 + 5000 + 40; the second (line 3) leaves context_tokens at
# 7 + 100 + 900 and adds 7 + 100 + 900 + 25 to the spend; the result adds 0.4321 dollars.
FIRST_CONTEXT = 3 + 1200 + 5000
FIRST_SPEND = 3 + 1200 + 5000 + 40
DONE_SPEND = Spend(tokens=(3 + 1200 + 5000 + 40) + (7 + 100 + 900 + 25), dollars=0.4321)
# In NO_STATUS_LEAD, one assistant message and a result without total_cost_usd.
NO_STATUS_SPEND = Spend(tokens=5 + 0 + 2000 + 10, dollars=0.0)


def _shimmed(cfg: Config, tmp_path: Path, split: int = 0) -> Config:
    """`cfg` with its lead behind the recording shim, recording to `<tmp_path>/records`."""
    rec = tmp_path / "records"
    rec.mkdir(exist_ok=True)
    fake = cfg.lead_command[0]
    lead = [sys.executable, "-c", _SHIM, str(rec), fake, str(split), str(WATCH)]
    return dataclasses.replace(cfg, lead_command=lead)


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


# Behaviors of pass step 8, the budget-triggered retire and the stops (s7.d3) script each
# lead and recut run through a sequencing shim put in front of the fake `claude`. The shim
# reads the prompt on stdin and writes `{"cwd", "prompt"}` to `<record dir>/run-<n>.json`,
# n counting from 0. Run n takes the plan's step n (the last step once the plan runs out,
# or step n modulo the plan's length when it cycles): it copies the step's `write` source
# over its target when the step has one, runs the fake on the step's scenario file and exits
# with the step's exit code. Every stream line it emits is the fake's, from `tests/fixtures/`.
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


def _step(name: str, exit: int = 0, write: tuple[Path, Path] | None = None) -> dict[str, object]:
    """One run of the plan: the fixture scenario `name`, its exit code, and a file to copy over another first."""
    return {
        "scenario": str(FIXTURES / name),
        "exit": exit,
        "write": [str(write[0]), str(write[1])] if write else None,
    }


def _plan(tmp_path: Path, fake: str, role: str, steps: list[dict[str, object]], cycle: bool) -> list[str]:
    rec = tmp_path / "plans" / role
    rec.mkdir(parents=True, exist_ok=True)
    return [sys.executable, "-c", _SEQ, str(rec), fake, json.dumps({"steps": steps, "cycle": cycle})]


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


# Behavior 4 (s7.d3): - NEEDS-OWNER: `park`, then `ping.needs_owner`.


def test_needs_owner_parks_the_section_with_its_question_and_the_loop_goes_on(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: NEEDS-OWNER does not park, parks without the question, or counts a failure.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    ids = _open_ids(queue)
    blocked = blocked_by(parse_queue(queue), {ids[0]})
    expected = next(sid for sid in ids[1:] if sid not in blocked)
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


@pytest.mark.parametrize(
    "budget",
    [{"token_budget": RETIRED_SPEND.tokens - 1}, {"dollar_budget": 0.1}],
    ids=["tokens", "dollars"],
)
def test_a_budget_triggered_retire_ends_the_pass_with_budget_and_runs_no_fresh_lead(
    cfg: Config,
    tmp_path: Path,
    queue_file: Callable[[str], Path],
    scenario: Callable[[list[str]], Path],
    budget: dict[str, object],
) -> None:
    # Breaks when: a lead retired on budget is followed by a fresh lead like any RETIRED.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    _only_first_open(queue, cfg)
    cfg = dataclasses.replace(cfg, **budget)
    cfg = _sequenced(cfg, tmp_path, [_step(RETIRED_LEAD), _step(DONE_SMALL_LEAD)])
    assert run(queue, cfg) == ExitCode.BUDGET
    assert len(_runs(tmp_path, "lead")) == 1


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


def test_a_stop_file_while_waiting_sends_one_stopped_ping(
    cfg: Config, tmp_path: Path, queue_file: Callable[[str], Path], scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the STOP_FILE stop from the wait returns without calling ping.stopped.
    queue = queue_file(WORKBOARD)
    scenario(_lines(DONE_LEAD))
    state = _park_all_but_done(queue, cfg, _open_ids(queue)[0])
    loop = _Background(queue, cfg)
    try:
        time.sleep(SETTLE)
        assert loop.still_running()
        State.open(queue, cfg).stop_file.touch()
        assert loop.finish(timeout=5.0) == ExitCode.STOP_FILE
    finally:
        state.stop_file.touch()
        loop.thread.join(15)
    pings = _pings(tmp_path)
    assert len(pings) == 1
    assert pings[0][0].startswith("relay ")
