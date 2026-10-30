"""Red tests for `relay/history.py`: a state directory turned into its runs
(design: relay-stats-design.md, Modules `relay/history.py`; Order 1)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

import pytest

from harness import ledger_line
from relay import history
from relay.config import Config
from relay.ledger import Ledger
from relay.state import State

QUEUE = "workboard-queue.md"


@pytest.fixture
def state(queue_file: Callable[[str], Path], fake_cfg: Config) -> State:
    state = State.open(queue_file(QUEUE), fake_cfg)
    state.run_dir.mkdir(parents=True, exist_ok=True)
    return state


def _log(state: State, number: int, session: str) -> Path:
    """Write run log `<number>.jsonl`: one finished run of `session`."""
    path = state.run_dir / f"{number}.jsonl"
    lines = [
        {"type": "system", "subtype": "init", "session_id": session, "cwd": "/work",
         "model": "claude-opus", "tools": ["Bash"]},
        {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 500,
         "num_turns": 1, "result": "Step committed.\nDONE", "session_id": session,
         "total_cost_usd": 0.01, "usage": {"input_tokens": 1, "output_tokens": 2}},
    ]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


def _line(state: State, kind: str, section: str, session: str | None = None) -> None:
    ledger_line(state, 1_700_000_000.0, 10, 0.1, kind=kind, section=section, session=session)


def _runs(found: history.History) -> list[tuple[str, str, str, str]]:
    return [(run.kind, run.section, run.session, run.log.name) for run in found.runs]


def test_a_session_the_ledger_names_twice_is_paired_with_its_logs_in_the_order_they_ran(
    state: State,
) -> None:
    # Breaks when: pairing gives every line of a session its first (or last) log, or takes
    # the logs in name order, so 10.jsonl and 11.jsonl come before 9.jsonl.
    _log(state, 9, "sess-a")
    _log(state, 10, "sess-b")
    _log(state, 11, "sess-a")
    _line(state, "lead", "s1", "sess-a")
    _line(state, "recut", "s1", "sess-b")
    _line(state, "lead", "s2", "sess-a")
    found = history.read(state, Ledger(state.ledger_path))
    assert _runs(found) == [
        ("lead", "s1", "sess-a", "9.jsonl"),
        ("recut", "s1", "sess-b", "10.jsonl"),
        ("lead", "s2", "sess-a", "11.jsonl"),
    ]
    assert [run.log for run in found.runs] == [
        state.run_dir / "9.jsonl", state.run_dir / "10.jsonl", state.run_dir / "11.jsonl",
    ]
    assert found.skipped_logs == 0


def test_a_log_that_cannot_be_read_is_skipped_and_counted(state: State) -> None:
    # Breaks when: an unreadable log raises out of `read`, is paired as a run, or is not counted.
    _log(state, 1, "sess-a")
    unreadable = _log(state, 2, "sess-gone")
    _log(state, 3, "sess-b")
    os.chmod(unreadable, 0)
    try:
        _line(state, "lead", "s1", "sess-a")
        _line(state, "lead", "s2", "sess-b")
        found = history.read(state, Ledger(state.ledger_path))
    finally:
        os.chmod(unreadable, 0o644)
    assert _runs(found) == [
        ("lead", "s1", "sess-a", "1.jsonl"),
        ("lead", "s2", "sess-b", "3.jsonl"),
    ]
    assert found.skipped_logs == 1


def test_a_ledger_line_with_no_session_is_no_run(state: State) -> None:
    # Breaks when: a sessionless line, such as a `check` line, is made a run or takes a log.
    _log(state, 1, "sess-a")
    _line(state, "check", "s1")
    _line(state, "lead", "s1", "sess-a")
    _line(state, "recut", "s2")
    found = history.read(state, Ledger(state.ledger_path))
    assert _runs(found) == [("lead", "s1", "sess-a", "1.jsonl")]
    assert found.skipped_logs == 0
