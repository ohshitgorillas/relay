"""Red tests for Relay's loop (design: Modules `relay/loop.py`, its pass steps 1 to 7 and the lead's cwd; Order 13)."""

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
