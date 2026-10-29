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
from typing import Callable

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
        time.sleep(SETTLE)
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
        time.sleep(SETTLE)
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
        time.sleep(SETTLE)
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
# is the fake's, from the scenario `RELAY_FAKE_SCENARIO` names. Given a fifth argument, the
# shim first creates that path, before it records anything.
_SHIM = r"""
import json, os, re, subprocess, sys, time
rec, fake, split, watch = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
if len(sys.argv) > 5:
    open(sys.argv[5], "a").close()
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


def _shimmed(cfg: Config, tmp_path: Path, split: int = 0, touch: Path | None = None) -> Config:
    """`cfg` with its lead behind the recording shim, recording to `<tmp_path>/records`; each
    lead creates `touch` as it starts, when given."""
    rec = tmp_path / "records"
    rec.mkdir(exist_ok=True)
    fake = cfg.lead_command[0]
    lead = [sys.executable, "-c", _SHIM, str(rec), fake, str(split), str(WATCH)]
    if touch is not None:
        lead.append(str(touch))
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
    entries = [json.loads(line) for line in (State.open(queue, cfg).stop_file.parent / "ledger.jsonl").read_text().splitlines()]
    assert len(entries) == n
    assert all(e["tokens"] == DONE_SPEND.tokens for e in entries)
    assert all(e["dollars"] == pytest.approx(DONE_SPEND.dollars) for e in entries)


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


# A section a recut made that itself ends RECUT is parked for the owner with the lead's reason,
# and gets no second recut.


def _queue_of(path: Path, *ids: str) -> Path:
    path.write_text("".join(f"section {sid} | lead | steps: 1\n  {sid} work\n" for sid in ids))
    return path


def test_a_section_from_a_recut_that_ends_recut_is_parked_with_the_reason_and_not_recut_again(
    cfg: Config, tmp_path: Path, scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: a recut section's RECUT runs the divvyer again, parks without the reason, or counts a failure.
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    recut = _queue_of(tmp_path / "recut.md", "s1.1", "s1.2", "s2")
    scenario(_lines(DONE_LEAD))
    leads = [_step(RECUT_LEAD), _step(RECUT_LEAD), _step(NO_STATUS_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads, recuts=[_step(DIVVYER_RUN, write=(recut, queue))])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert len(_runs(tmp_path, "recut")) == 1
    state = State.open(queue, cfg)
    parked = state.section("s1.1")
    assert parked.status == "parked"
    assert parked.question is not None and RECUT_REASON in parked.question
    assert parked.failures == 0
    assert state.section("s1.2").from_recut
    assert not state.section("s2").from_recut


def test_a_section_from_a_recut_that_ends_recut_pings_the_owner_with_the_reason_once_parked(
    cfg: Config, tmp_path: Path, scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: the parked recut section sends no needs-owner ping, or pings before it is parked.
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    recut = _queue_of(tmp_path / "recut.md", "s1.1", "s2")
    scenario(_lines(DONE_LEAD))
    record = tmp_path / "pings.jsonl"
    ping = [sys.executable, "-c", _RECORD_STATE, str(REPO), str(record), str(queue), str(cfg.state_root), "s1.1", "{message}"]
    cfg = dataclasses.replace(cfg, ping_command=ping)
    leads = [_step(RECUT_LEAD), _step(RECUT_LEAD), _step(NO_STATUS_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads, recuts=[_step(DIVVYER_RUN, write=(recut, queue))])
    run(queue, cfg)
    asked = [p for p in _pings(tmp_path) if RECUT_REASON in p[0]]
    assert len(asked) == 1
    message, status = asked[0]
    assert "s1.1" in message and "needs the owner" in message
    assert status == "parked"


def test_a_section_the_recut_left_in_place_that_ends_recut_is_still_recut(
    cfg: Config, tmp_path: Path, scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: every section of a recut queue is taken as a recut's, so an original section's RECUT is parked.
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    first = _queue_of(tmp_path / "first.md", "s1.1", "s2")
    second = _queue_of(tmp_path / "second.md", "s1.1", "s2.1")
    scenario(_lines(DONE_LEAD))
    leads = [_step(RECUT_LEAD), _step(DONE_LEAD), _step(RECUT_LEAD), _step(NO_STATUS_LEAD)]
    recuts = [_step(DIVVYER_RUN, write=(first, queue)), _step(DIVVYER_RUN, write=(second, queue))]
    cfg = _sequenced(cfg, tmp_path, leads, recuts=recuts)
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    assert len(_runs(tmp_path, "recut")) == 2
    state = State.open(queue, cfg)
    assert state.section("s2").status == "open"
    assert state.section("s2.1").from_recut


def test_a_recut_that_keeps_the_section_id_runs_it_on_under_that_id_and_parks_its_second_recut(
    cfg: Config, tmp_path: Path, scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: a section the recut rewrote in place under its own id is not taken as the recut's,
    # so its next RECUT runs the divvyer again instead of going to the owner.
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
    assert kept.question is not None and RECUT_REASON in kept.question
    assert kept.failures == 0
    assert "s1 work, paths widened" in str(_runs(tmp_path, "lead")[1]["prompt"])
    assert not state.section("s2").from_recut


def test_a_recut_that_splits_the_section_runs_the_child_ids_and_leaves_the_old_id_behind(
    cfg: Config, tmp_path: Path, scenario: Callable[[list[str]], Path]
) -> None:
    # Breaks when: after a real split the old id is still run or marked, or a child id is not the recut's.
    queue = _queue_of(tmp_path / "queue.md", "s1", "s2")
    split = _queue_of(tmp_path / "split.md", "s1.1", "s1.2", "s2")
    scenario(_lines(DONE_LEAD))
    leads = [_step(RECUT_LEAD), _step(DONE_LEAD), _step(NO_STATUS_LEAD)]
    cfg = _sequenced(cfg, tmp_path, leads, recuts=[_step(DIVVYER_RUN, write=(split, queue))])
    assert run(queue, cfg) == ExitCode.FAILED_TWICE
    state = State.open(queue, cfg)
    assert state.section("s1.1").from_recut and state.section("s1.1").status == "done"
    assert state.section("s1.2").from_recut
    assert not state.section("s1").from_recut
    assert "Section: s1.1" in str(_runs(tmp_path, "lead")[1]["prompt"])
    assert "Section: s1.2" in str(_runs(tmp_path, "lead")[2]["prompt"])


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
            time.sleep(SETTLE)
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
        time.sleep(SETTLE)
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
    assert _texts(captured.out) == [
        f"relay go {name}: started; no token budget, no dollar budget",
        f"lead {a}: started fresh",
        f"lead {a}: finished with no status line {_finished(NO_STATUS_SPEND)}",
        f"section {a}: failed (1 of 2)",
        f"lead {a}: started, resuming sess-lead-2",
        f"lead {a}: finished DONE {_finished(DONE_SPEND)}",
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
        f"waiting for answers on {b}",
        f"lead {b}: started, resuming sess-lead-5, with the owner's answer",
        f"lead {b}: finished DONE {_finished(DONE_SPEND)}",
        "<ping.stopped>",
        f"relay go {name}: ended {reason}: {detail} (exit {int(ExitCode.QUEUE_EMPTY)})",
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
        time.sleep(SETTLE)
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


def _until(condition: Callable[[], bool], timeout: float = 15.0) -> None:
    end = time.time() + timeout
    while not condition():
        assert time.time() < end, "condition never held"
        time.sleep(0.02)


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
        time.sleep(SETTLE)
        assert loop.still_running()
        time.sleep(SETTLE)
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
        time.sleep(SETTLE)
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
        time.sleep(SETTLE)
        assert loop.still_running()
        State.open(queue, cfg).set_answer(a, "Use port 8080.")
        _until(lambda: State.open(queue, cfg).section(a).status == "done")
        time.sleep(SETTLE)
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
        time.sleep(SETTLE)
        assert loop.still_running()
        State.open(queue, cfg).set_answer(a, "Use port 8080.")
        _until(lambda: len(_pings(tmp_path)) == 1)
        time.sleep(SETTLE)
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
