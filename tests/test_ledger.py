"""Red tests for Relay's spend ledger (design: Modules `relay/ledger.py`; Order 7)."""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

from relay.config import Config
from relay.ledger import Ledger, Spend


def _stamps(entry: dict, lo: float, hi: float) -> list[float]:
    """Every number in a ledger line that is a POSIX time taken between `lo` and `hi`."""
    return [
        value
        for value in entry.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool) and lo <= value <= hi
    ]


def _tick() -> float:
    """A POSIX time strictly after every earlier append and strictly before every later one."""
    time.sleep(0.02)
    now = time.time()
    time.sleep(0.02)
    return now


# Behavior 1: It appends one JSON line per finished run (lead or recut), stamped with its
# POSIX time, to `<state dir>/ledger.jsonl`.


def test_append_writes_one_json_line_per_run_stamped_with_posix_time(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    before = time.time()
    ledger.append("lead", "s1", "sess-a", Spend(tokens=11, dollars=0.5))
    ledger.append("recut", "s1", None, Spend(tokens=7, dollars=0.25))
    after = time.time()
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        entry = json.loads(line)
        assert isinstance(entry, dict)
        assert len(_stamps(entry, before, after)) >= 1


def test_append_adds_to_an_existing_ledger_file(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    Ledger(path).append("lead", "s1", "sess-a", Spend(tokens=100, dollars=1.5))
    first = path.read_text()
    second = Ledger(path)
    second.append("lead", "s2", "sess-b", Spend(tokens=20, dollars=0.25))
    second.append("recut", "s2", None, Spend(tokens=3, dollars=0.0))
    text = path.read_text()
    assert text.startswith(first)
    assert len(text.splitlines()) == 3
    assert Ledger(path).total(None) == Spend(tokens=123, dollars=1.75)


def test_total_sums_lead_and_recut_runs(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append("lead", "s1", "sess-a", Spend(tokens=40, dollars=0.5))
    ledger.append("recut", "s1", None, Spend(tokens=2, dollars=0.125))
    ledger.append("lead", "s1", "sess-b", Spend(tokens=8, dollars=0.25))
    assert ledger.total(None) == Spend(tokens=50, dollars=0.875)


# Behavior 2: Budgets count only the current `relay go`: the loop passes its own start
# time as `since`.


def test_total_since_counts_only_runs_stamped_after_it(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append("lead", "s1", "sess-old", Spend(tokens=1_000, dollars=4.0))
    ledger.append("recut", "s1", None, Spend(tokens=500, dollars=2.0))
    start = _tick()
    ledger.append("lead", "s2", "sess-new", Spend(tokens=30, dollars=0.5))
    ledger.append("recut", "s2", None, Spend(tokens=5, dollars=0.25))
    assert ledger.total(start) == Spend(tokens=35, dollars=0.75)
    assert ledger.total(None) == Spend(tokens=1_535, dollars=6.75)


def test_total_since_now_is_empty(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append("lead", "s1", "sess-old", Spend(tokens=1_000, dollars=4.0))
    start = _tick()
    assert ledger.total(start) == Spend(tokens=0, dollars=0.0)


def test_over_token_budget_ignores_runs_before_since(tmp_path: Path, fake_cfg: Config) -> None:
    cfg = dataclasses.replace(fake_cfg, token_budget=100, dollar_budget=None)
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append("lead", "s1", "sess-old", Spend(tokens=1_000, dollars=0.0))
    start = _tick()
    ledger.append("lead", "s2", "sess-new", Spend(tokens=10, dollars=0.0))
    idle = Spend(tokens=0, dollars=0.0)
    assert ledger.over(cfg, idle, start) is None
    assert ledger.over(cfg, idle, None) == "tokens"
    assert ledger.over(cfg, Spend(tokens=500, dollars=0.0), start) == "tokens"


def test_over_dollar_budget_ignores_runs_before_since(tmp_path: Path, fake_cfg: Config) -> None:
    cfg = dataclasses.replace(fake_cfg, token_budget=None, dollar_budget=1.0)
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append("recut", "s1", None, Spend(tokens=0, dollars=5.0))
    start = _tick()
    ledger.append("lead", "s2", "sess-new", Spend(tokens=0, dollars=0.25))
    idle = Spend(tokens=0, dollars=0.0)
    assert ledger.over(cfg, idle, start) is None
    assert ledger.over(cfg, idle, None) == "dollars"
    assert ledger.over(cfg, Spend(tokens=0, dollars=3.0), start) == "dollars"
