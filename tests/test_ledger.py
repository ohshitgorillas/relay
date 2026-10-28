"""Red tests for Relay's spend ledger (design: Modules `relay/ledger.py`; Order 7)."""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

import pytest

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
    # dollar_budget is None (no limit), so heavy dollar spend never trips `over`.
    ledger.append("lead", "s1", "sess-old", Spend(tokens=1_000, dollars=50.0))
    start = _tick()
    ledger.append("lead", "s2", "sess-new", Spend(tokens=10, dollars=75.0))
    idle = Spend(tokens=0, dollars=100.0)
    assert ledger.over(cfg, idle, start) is None
    assert ledger.over(cfg, idle, None) == "tokens"
    assert ledger.over(cfg, Spend(tokens=500, dollars=0.0), start) == "tokens"


def test_over_dollar_budget_ignores_runs_before_since(tmp_path: Path, fake_cfg: Config) -> None:
    cfg = dataclasses.replace(fake_cfg, token_budget=None, dollar_budget=1.0)
    ledger = Ledger(tmp_path / "ledger.jsonl")
    # token_budget is None (no limit), so heavy token spend never trips `over`.
    ledger.append("recut", "s1", None, Spend(tokens=1_000_000, dollars=5.0))
    start = _tick()
    ledger.append("lead", "s2", "sess-new", Spend(tokens=500_000, dollars=0.25))
    idle = Spend(tokens=2_000_000, dollars=0.0)
    assert ledger.over(cfg, idle, start) is None
    assert ledger.over(cfg, idle, None) == "dollars"
    assert ledger.over(cfg, Spend(tokens=0, dollars=3.0), start) == "dollars"


# Ledger recovery (design: Modules `relay/ledger.py`, the recovery list; Order 8a).


def _call(method, *args):
    """Call a ledger method; a raise on the file's content is a broken claim, so it fails as one."""
    try:
        return method(*args)
    except Exception as exc:  # noqa: BLE001 - any raise breaks "no ledger method raises"
        raise AssertionError(f"ledger method raised on the file's content: {type(exc).__name__}") from exc


def _raw(path: Path, text: str) -> None:
    """Add bytes to the ledger file by hand, the way a crash or a stray writer leaves them."""
    with path.open("ab") as handle:
        handle.write(text.encode())


def _budget_cfg(fake_cfg: Config) -> Config:
    return dataclasses.replace(fake_cfg, token_budget=100, dollar_budget=10.0)


# Each kind of unreadable line the design names. Where a kind still holds numbers, they are
# big enough that counting them would push any total past the budgets used below.
UNREADABLE = {
    "not-json": "this is not json",
    "cut-json": '{"time": NOW, "tokens": 1000000, "doll',
    "json-array": "[NOW, 1000000, 900.0]",
    "json-string": '"tokens 1000000"',
    "json-number": "1000000",
    "json-null": "null",
    "lacks-time": '{"tokens": 1000000, "dollars": 900.0}',
    "lacks-tokens": '{"time": NOW, "dollars": 900.0}',
    "lacks-dollars": '{"time": NOW, "tokens": 1000000}',
    "bool-time": '{"time": true, "tokens": 1000000, "dollars": 900.0}',
    "bool-tokens": '{"time": NOW, "tokens": true, "dollars": 900.0}',
    "bool-dollars": '{"time": NOW, "tokens": 1000000, "dollars": true}',
    "string-time": '{"time": "NOW", "tokens": 1000000, "dollars": 900.0}',
    "string-tokens": '{"time": NOW, "tokens": "1000000", "dollars": 900.0}',
    "string-dollars": '{"time": NOW, "tokens": 1000000, "dollars": "900.0"}',
    "null-tokens": '{"time": NOW, "tokens": null, "dollars": 900.0}',
    "list-dollars": '{"time": NOW, "tokens": 1000000, "dollars": [900.0]}',
}


def _unreadable_line(kind: str) -> str:
    return UNREADABLE[kind].replace("NOW", repr(time.time()))


def _ledger_around(path: Path, bad: str) -> Ledger:
    """Readable line, the given line, readable line: lines 1 and 3 sum to 42 tokens, $0.75."""
    ledger = Ledger(path)
    ledger.append("lead", "s1", "sess-a", Spend(tokens=40, dollars=0.5))
    _raw(path, bad + "\n")
    ledger.append("recut", "s1", None, Spend(tokens=2, dollars=0.25))
    return ledger


# Behavior 1: A corrupt or torn ledger never stops Relay and never needs a hand fix; no
# ledger method raises on the file's content.


def test_no_ledger_method_raises_on_corrupt_or_torn_content(tmp_path: Path, fake_cfg: Config) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append("lead", "s1", "sess-a", Spend(tokens=5, dollars=0.5))
    for kind in UNREADABLE:
        _raw(path, _unreadable_line(kind) + "\n")
    _raw(path, "\n")
    _raw(path, '{"time": 1, "tok')
    cfg = _budget_cfg(fake_cfg)
    _call(ledger.total, None)
    _call(ledger.total, time.time() - 60)
    _call(ledger.over, cfg, Spend(tokens=0, dollars=0.0), None)
    _call(ledger.over, cfg, Spend(tokens=0, dollars=0.0), time.time() - 60)
    _call(ledger.append, "lead", "s2", "sess-b", Spend(tokens=1, dollars=0.0))
    _call(Ledger(path).total, None)


# Behavior 2: If the file is non-empty and its last byte is not `\n`, `append` first writes
# `\n`, which closes off a line torn by a crash so the new entry starts on a line of its own.


def test_append_closes_off_a_torn_last_line(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append("lead", "s1", "sess-a", Spend(tokens=40, dollars=0.5))
    torn = '{"time": 1, "tokens": 9'
    _raw(path, torn)
    before = path.read_text()
    start = time.time()
    _call(ledger.append, "lead", "s1", "sess-b", Spend(tokens=7, dollars=0.25))
    end = time.time()
    text = path.read_text()
    assert text.startswith(before + "\n")
    assert text.endswith("\n")
    lines = text.splitlines()
    assert len(lines) == 3
    assert lines[1] == torn
    entry = json.loads(lines[2])
    assert isinstance(entry, dict)
    assert len(_stamps(entry, start, end)) >= 1


def test_append_onto_a_file_holding_only_a_torn_line(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    _raw(path, '{"time": 1')
    ledger = Ledger(path)
    _call(ledger.append, "recut", "s1", None, Spend(tokens=3, dollars=0.125))
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert lines[0] == '{"time": 1'
    assert isinstance(json.loads(lines[1]), dict)
    assert _call(ledger.total, None) == Spend(tokens=3, dollars=0.125)


def test_entries_appended_after_a_torn_line_are_all_counted(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append("lead", "s1", "sess-a", Spend(tokens=40, dollars=0.5))
    _raw(path, '{"time": 1, "tokens": 1000000, "dollars": 9')
    _call(ledger.append, "lead", "s1", "sess-b", Spend(tokens=7, dollars=0.25))
    _call(ledger.append, "recut", "s1", None, Spend(tokens=3, dollars=0.125))
    assert _call(Ledger(path).total, None) == Spend(tokens=50, dollars=0.875)


# Behavior 3: `total`, `over` and `unreadable` treat a line as unreadable when it is not
# JSON, is not a JSON object, lacks `time`, `tokens` or `dollars`, or holds a `bool` or
# non-number in one of them.


@pytest.mark.parametrize("kind", list(UNREADABLE))
def test_total_skips_each_unreadable_line_kind(tmp_path: Path, kind: str) -> None:
    ledger = _ledger_around(tmp_path / "ledger.jsonl", _unreadable_line(kind))
    assert _call(ledger.total, None) == Spend(tokens=42, dollars=0.75)


@pytest.mark.parametrize("kind", list(UNREADABLE))
def test_over_skips_each_unreadable_line_kind(tmp_path: Path, fake_cfg: Config, kind: str) -> None:
    cfg = _budget_cfg(fake_cfg)
    ledger = _ledger_around(tmp_path / "ledger.jsonl", _unreadable_line(kind))
    assert _call(ledger.over, cfg, Spend(tokens=0, dollars=0.0), None) is None
    assert _call(ledger.over, cfg, Spend(tokens=0, dollars=0.0), time.time() - 60) is None


# Behavior 4: An empty line is unreadable too. `total` and `over` skip unreadable lines and
# sum the rest.


def test_total_and_over_skip_an_empty_line(tmp_path: Path, fake_cfg: Config) -> None:
    ledger = _ledger_around(tmp_path / "ledger.jsonl", "")
    assert _call(ledger.total, None) == Spend(tokens=42, dollars=0.75)
    assert _call(ledger.over, _budget_cfg(fake_cfg), Spend(tokens=0, dollars=0.0), None) is None


def test_total_sums_every_readable_line_around_unreadable_ones(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    _raw(path, "garbage\n")
    ledger.append("lead", "s1", "sess-a", Spend(tokens=60, dollars=4.0))
    _raw(path, "\n" + _unreadable_line("bool-dollars") + "\n")
    ledger.append("recut", "s1", None, Spend(tokens=50, dollars=7.0))
    _raw(path, "[1]\n")
    ledger.append("lead", "s2", "sess-b", Spend(tokens=5, dollars=0.5))
    assert _call(ledger.total, None) == Spend(tokens=115, dollars=11.5)


def test_total_since_skips_unreadable_lines(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append("lead", "s1", "sess-old", Spend(tokens=1_000, dollars=4.0))
    start = _tick()
    _raw(path, _unreadable_line("lacks-dollars") + "\n")
    ledger.append("lead", "s2", "sess-new", Spend(tokens=30, dollars=0.5))
    _raw(path, "not json\n")
    assert _call(ledger.total, start) == Spend(tokens=30, dollars=0.5)


def test_over_sums_readable_lines_past_unreadable_ones(tmp_path: Path, fake_cfg: Config) -> None:
    cfg = _budget_cfg(fake_cfg)
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append("lead", "s1", "sess-a", Spend(tokens=60, dollars=1.0))
    _raw(path, "not json\n\n")
    ledger.append("lead", "s1", "sess-b", Spend(tokens=50, dollars=1.0))
    assert _call(ledger.over, cfg, Spend(tokens=0, dollars=0.0), None) == "tokens"


def test_over_dollars_sums_readable_lines_past_unreadable_ones(tmp_path: Path, fake_cfg: Config) -> None:
    cfg = _budget_cfg(fake_cfg)
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append("lead", "s1", "sess-a", Spend(tokens=1, dollars=6.0))
    _raw(path, _unreadable_line("lacks-time") + "\n")
    ledger.append("recut", "s1", None, Spend(tokens=1, dollars=6.0))
    assert _call(ledger.over, cfg, Spend(tokens=0, dollars=0.0), None) == "dollars"


# Behavior 6: Relay never rewrites, truncates or deletes the ledger.


def _corrupt_ledger(path: Path) -> Ledger:
    ledger = Ledger(path)
    ledger.append("lead", "s1", "sess-a", Spend(tokens=5, dollars=0.5))
    _raw(path, "not json\n\n" + _unreadable_line("bool-tokens") + "\n")
    ledger.append("recut", "s1", None, Spend(tokens=3, dollars=0.25))
    _raw(path, '{"time": 1, "tok')
    return ledger


def test_reads_leave_every_ledger_byte_in_place(tmp_path: Path, fake_cfg: Config) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = _corrupt_ledger(path)
    original = path.read_bytes()
    _call(ledger.total, None)
    _call(ledger.total, time.time() - 60)
    _call(ledger.over, _budget_cfg(fake_cfg), Spend(tokens=0, dollars=0.0), None)
    assert path.read_bytes() == original


def test_append_keeps_every_existing_byte_of_a_corrupt_ledger(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = _corrupt_ledger(path)
    original = path.read_bytes()
    _call(ledger.append, "lead", "s2", "sess-b", Spend(tokens=1, dollars=0.0))
    _call(ledger.append, "recut", "s2", None, Spend(tokens=1, dollars=0.0))
    after = path.read_bytes()
    assert after.startswith(original + b"\n")
    assert len(after.splitlines()) == len(original.splitlines()) + 2


# `unreadable` (design: Modules `relay/ledger.py`, `Ledger.unreadable` and the recovery
# list; Order 8a).


def _mixed_ledger(path: Path) -> Ledger:
    """Lines 1, 3, 4, 6 and 8 unreadable (8 torn, with no closing newline); 2, 5 and 7 readable."""
    ledger = Ledger(path)
    _raw(path, "garbage\n")
    ledger.append("lead", "s1", "sess-a", Spend(tokens=60, dollars=4.0))
    _raw(path, "\n" + _unreadable_line("bool-dollars") + "\n")
    ledger.append("recut", "s1", None, Spend(tokens=50, dollars=7.0))
    _raw(path, "[1]\n")
    ledger.append("lead", "s2", "sess-b", Spend(tokens=5, dollars=0.5))
    _raw(path, '{"time": 1, "tok')
    return ledger


# Behavior: 1-based numbers of the unreadable lines.


def test_unreadable_is_empty_when_the_file_is_absent(tmp_path: Path) -> None:
    assert Ledger(tmp_path / "ledger.jsonl").unreadable() == []


def test_unreadable_is_empty_for_a_clean_ledger(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append("lead", "s1", "sess-a", Spend(tokens=40, dollars=0.5))
    ledger.append("recut", "s1", None, Spend(tokens=2, dollars=0.25))
    assert ledger.unreadable() == []


@pytest.mark.parametrize("kind", list(UNREADABLE))
def test_unreadable_names_each_unreadable_line_kind_by_its_number(tmp_path: Path, kind: str) -> None:
    ledger = _ledger_around(tmp_path / "ledger.jsonl", _unreadable_line(kind))
    assert ledger.unreadable() == [2]


def test_unreadable_names_an_empty_line(tmp_path: Path) -> None:
    ledger = _ledger_around(tmp_path / "ledger.jsonl", "")
    assert ledger.unreadable() == [2]


def test_unreadable_lists_one_based_numbers_in_file_order(tmp_path: Path) -> None:
    ledger = _mixed_ledger(tmp_path / "ledger.jsonl")
    assert ledger.unreadable() == [1, 3, 4, 6, 8]


def test_unreadable_keeps_a_closed_off_torn_line_at_its_number(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append("lead", "s1", "sess-a", Spend(tokens=40, dollars=0.5))
    _raw(path, '{"time": 1, "tokens": 9')
    ledger.append("lead", "s1", "sess-b", Spend(tokens=7, dollars=0.25))
    ledger.append("recut", "s1", None, Spend(tokens=3, dollars=0.125))
    assert Ledger(path).unreadable() == [2]


# Behavior: A corrupt or torn ledger never stops Relay and never needs a hand fix; no
# ledger method raises on the file's content.


def test_unreadable_never_raises_on_corrupt_or_torn_content(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    for kind in UNREADABLE:
        _raw(path, _unreadable_line(kind) + "\n")
    _raw(path, "\n")
    _raw(path, '{"time": 1, "tok')
    assert _call(ledger.unreadable) == list(range(1, len(UNREADABLE) + 3))


# Behavior: Relay never rewrites, truncates or deletes the ledger.


def test_unreadable_leaves_every_ledger_byte_in_place(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = _mixed_ledger(path)
    original = path.read_bytes()
    _call(ledger.unreadable)
    _call(ledger.unreadable)
    assert path.read_bytes() == original


# Behavior: If the file is non-empty and its last byte is not `\n`, `append` first writes
# `\n`, which closes off a line torn by a crash so the new entry starts on a line of its own.


def test_append_onto_an_empty_file_writes_no_leading_newline(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_bytes(b"")
    ledger = Ledger(path)
    ledger.append("lead", "s1", "sess-a", Spend(tokens=4, dollars=0.5))
    text = path.read_text()
    assert not text.startswith("\n")
    assert len(text.splitlines()) == 1
    assert ledger.unreadable() == []
