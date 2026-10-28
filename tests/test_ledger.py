"""Red tests for Relay's spend ledger (design: Modules `relay/ledger.py`; Order 7)."""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

import pytest

from relay import agents
from relay.check import CheckResult
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
    _call(ledger.sessions)


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
    # Hand-written lines the recovery list calls readable, in shapes `append` itself may not write:
    # integer `dollars`, float `tokens`, integer `time`, and an object with no keys but the three.
    now = time.time()
    _raw(tmp_path / "ledger.jsonl", json.dumps({"time": now, "tokens": 5, "dollars": 1}) + "\n")
    _raw(tmp_path / "ledger.jsonl", json.dumps({"time": now, "tokens": 2.5, "dollars": 0.125}) + "\n")
    _raw(tmp_path / "ledger.jsonl", json.dumps({"time": int(now), "tokens": 1, "dollars": 0}) + "\n")
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
    # The `sess-b` entry starts a line of its own after the torn one, so it is counted.
    assert len(path.read_text().splitlines()) == 4
    assert _call(Ledger(path).total, None) == Spend(tokens=50, dollars=0.875)
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


# `sessions`: the (section, session) of each readable line, so run logs can be filed by section.


def test_sessions_lists_section_and_session_in_the_order_written(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append("lead", "s1", "sess-a", Spend(tokens=1, dollars=0.0))
    ledger.append("recut", "s1", "sess-b", Spend(tokens=1, dollars=0.0))
    ledger.append("lead", "s2", "sess-a", Spend(tokens=1, dollars=0.0))
    assert ledger.sessions() == [("s1", "sess-a"), ("s1", "sess-b"), ("s2", "sess-a")]


def test_sessions_skips_unreadable_lines_and_lines_without_a_session(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append("lead", "s1", None, Spend(tokens=1, dollars=0.0))
    _raw(path, '{"time": 1, "tok\n')
    ledger.append("lead", "s2", "sess-b", Spend(tokens=1, dollars=0.0))
    assert ledger.sessions() == [("s2", "sess-b")]


def test_sessions_of_a_missing_ledger_is_empty(tmp_path: Path) -> None:
    assert Ledger(tmp_path / "ledger.jsonl").sessions() == []


# Relay's check (design: docs/superpowers/specs/relay-check-design.md, Modules `relay/ledger.py`
# `append_check`; Order 3).


def _check(verdict: str = "fail", exit_code: int | None = 1) -> CheckResult:
    """A check result of the given verdict, shaped as the design's `CheckResult` fields say."""
    if verdict == "none":
        return CheckResult(command=None, exit_code=None, timed_out=False, tail="", log=None, verdict="none")
    return CheckResult(
        command="make test",
        exit_code=exit_code,
        timed_out=exit_code is None,
        tail="FAILED tests/test_a.py::test_a\n",
        log=Path("/state/runs/3.check"),
        verdict=verdict,
        timeout=1800.0 if exit_code is None else None,
    )


# Behavior 4: Written as append writes.


def test_append_check_adds_one_json_line_after_the_existing_ones(tmp_path: Path) -> None:
    # Breaks when: `append_check` rewrites the file, or writes other than one stamped JSON line.
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append("lead", "s1", "sess-a", Spend(tokens=40, dollars=0.5))
    first = path.read_bytes()
    before = time.time()
    ledger.append_check("s1", _check())
    after = time.time()
    text = path.read_bytes()
    assert text.startswith(first)
    assert text.endswith(b"\n")
    lines = text.decode().splitlines()
    assert len(lines) == 2
    entry = json.loads(lines[1])
    assert isinstance(entry, dict)
    assert len(_stamps(entry, before, after)) >= 1


# The `append_check` docstring: "One line: time, kind "check", section, session null, tokens 0,
# dollars 0.0, command, exit (int or null), timed_out, verdict, tail, log (str or null)."
CHECK_LINE_CASES = {
    "fail": ("s1", "fail", 1),
    "pass": ("s2", "pass", 0),
    "outside": ("s3a", "outside", 127),
    "timed-out": ("s1", "fail", None),
    "none": ("s4", "none", None),
}


@pytest.mark.parametrize("case", list(CHECK_LINE_CASES))
def test_append_check_line_holds_each_field_of_the_result_and_section(tmp_path: Path, case: str) -> None:
    # Breaks when: a check line drops or misnames a field, writes the wrong section, kind or
    # session, stringifies `exit` or `log`, or holds spend other than 0 tokens and $0.
    section, verdict, exit_code = CHECK_LINE_CASES[case]
    result = _check(verdict, exit_code)
    path = tmp_path / "ledger.jsonl"
    before = time.time()
    Ledger(path).append_check(section, result)
    after = time.time()
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert isinstance(entry, dict)
    assert isinstance(entry["time"], (int, float)) and not isinstance(entry["time"], bool)
    assert before <= entry["time"] <= after
    assert entry["kind"] == "check"
    assert entry["section"] == section
    assert "session" in entry and entry["session"] is None
    assert entry["tokens"] == 0 and not isinstance(entry["tokens"], bool)
    assert entry["dollars"] == 0.0 and not isinstance(entry["dollars"], bool)
    assert entry["verdict"] == verdict
    assert entry["tail"] == result.tail
    assert entry["timed_out"] is result.timed_out
    if verdict == "none":
        assert "command" in entry and entry["command"] is None
        assert "exit" in entry and entry["exit"] is None
        assert "log" in entry and entry["log"] is None
        assert entry["timed_out"] is False
        assert entry["tail"] == ""
        return
    assert entry["command"] == "make test"
    if exit_code is None:
        assert "exit" in entry and entry["exit"] is None
        assert entry["timed_out"] is True
    else:
        assert type(entry["exit"]) is int and entry["exit"] == exit_code
        assert entry["timed_out"] is False
    assert entry["log"] == "/state/runs/3.check"


def test_append_check_creates_a_missing_ledger(tmp_path: Path) -> None:
    # Breaks when: `append_check` needs the file to exist first.
    path = tmp_path / "ledger.jsonl"
    Ledger(path).append_check("s1", _check("pass", 0))
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    assert isinstance(json.loads(lines[0]), dict)


def test_append_check_closes_off_a_torn_last_line(tmp_path: Path) -> None:
    # Breaks when: `append_check` skips the `\n` that `append` writes after a torn line.
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append("lead", "s1", "sess-a", Spend(tokens=40, dollars=0.5))
    torn = '{"time": 1, "tokens": 9'
    _raw(path, torn)
    before = path.read_text()
    ledger.append_check("s1", _check())
    text = path.read_text()
    assert text.startswith(before + "\n")
    lines = text.splitlines()
    assert len(lines) == 3
    assert lines[1] == torn
    assert isinstance(json.loads(lines[2]), dict)


def test_append_check_keeps_every_existing_byte_of_a_corrupt_ledger(tmp_path: Path) -> None:
    # Breaks when: `append_check` truncates or rewrites a corrupt ledger.
    path = tmp_path / "ledger.jsonl"
    ledger = _corrupt_ledger(path)
    original = path.read_bytes()
    ledger.append_check("s2", _check("outside", 127))
    ledger.append_check("s2", _check("none"))
    after = path.read_bytes()
    assert after.startswith(original + b"\n")
    assert len(after.splitlines()) == len(original.splitlines()) + 2


# Behavior 5: so `total`, `over` and `unreadable` read check lines unchanged.


def _ledger_with_checks(path: Path) -> Ledger:
    """Seven lines: two runs summing to 42 tokens, $0.75, and a check line of each verdict."""
    ledger = Ledger(path)
    ledger.append("lead", "s1", "sess-a", Spend(tokens=40, dollars=0.5))
    ledger.append_check("s1", _check("fail", 1))
    ledger.append_check("s1", _check("outside", 127))
    ledger.append("recut", "s1", None, Spend(tokens=2, dollars=0.25))
    ledger.append_check("s1", _check("fail", None))
    ledger.append_check("s2", _check("none"))
    ledger.append_check("s1", _check("pass", 0))
    return ledger


def test_total_counts_check_lines_as_no_spend(tmp_path: Path) -> None:
    # Breaks when: a check line adds tokens or dollars to the total.
    ledger = _ledger_with_checks(tmp_path / "ledger.jsonl")
    assert _call(ledger.total, None) == Spend(tokens=42, dollars=0.75)


def test_total_since_counts_check_lines_after_it_as_no_spend(tmp_path: Path) -> None:
    # Breaks when: a check line stamped after `since` adds spend to the total.
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append("lead", "s1", "sess-old", Spend(tokens=1_000, dollars=4.0))
    start = _tick()
    ledger.append_check("s1", _check())
    ledger.append("lead", "s2", "sess-new", Spend(tokens=30, dollars=0.5))
    ledger.append_check("s2", _check("pass", 0))
    assert _call(ledger.total, start) == Spend(tokens=30, dollars=0.5)


def test_over_counts_check_lines_as_no_spend(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: check lines push `over` past a budget the runs stay under, or hide one they pass.
    cfg = dataclasses.replace(fake_cfg, token_budget=43, dollar_budget=0.76)
    ledger = _ledger_with_checks(tmp_path / "ledger.jsonl")
    assert _call(ledger.over, cfg, Spend(tokens=0, dollars=0.0), None) is None
    assert _call(ledger.over, cfg, Spend(tokens=2, dollars=0.0), None) == "tokens"
    assert _call(ledger.over, cfg, Spend(tokens=0, dollars=0.25), None) == "dollars"


def test_unreadable_reads_check_lines_as_readable(tmp_path: Path) -> None:
    # Breaks when: a check line lacks `time`, `tokens` or `dollars`, or holds a non-number in one.
    path = tmp_path / "ledger.jsonl"
    ledger = _ledger_with_checks(path)
    assert _call(ledger.unreadable) == []
    _raw(path, "not json\n")
    ledger.append_check("s1", _check())
    assert _call(ledger.unreadable) == [8]


# Behavior 6: `sessions()` skips them because their session is null.


def test_sessions_skips_check_lines(tmp_path: Path) -> None:
    # Breaks when: a check line is listed as a (section, session) pair.
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append_check("s1", _check())
    ledger.append("lead", "s1", "sess-a", Spend(tokens=1, dollars=0.0))
    ledger.append_check("s1", _check("pass", 0))
    ledger.append("lead", "s2", "sess-b", Spend(tokens=1, dollars=0.0))
    ledger.append_check("s2", _check("none"))
    assert _call(ledger.sessions) == [("s1", "sess-a"), ("s2", "sess-b")]


def test_sessions_of_a_ledger_of_only_check_lines_is_empty(tmp_path: Path) -> None:
    # Breaks when: `sessions()` lists a check line with a null session.
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append_check("s1", _check())
    ledger.append_check("s1", _check("outside", 127))
    assert _call(ledger.sessions) == []


# Relay's research (design: docs/superpowers/specs/relay-research-design.md, Modules
# `relay/ledger.py`; Order 3).
# Behavior 3: Run lines with map commit and agents' tokens.

RUN_KINDS = ["lead", "recut", "research", "ask"]


def _subagents() -> tuple:
    """The two subagents of the agents fixture stream: builder a1 at 21844 tokens, test-writer
    a2 at 41000, folded as `relay/agents.py` folds a run's stream."""
    activity = agents.Activity()
    for line in (Path(__file__).parent / "fixtures" / "stream-agents.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event.get("type") == "system":
            activity = agents.feed(activity, event)
    return tuple(activity.agents)


SUBAGENT_RECORDS = [
    {"name": "builder", "task_id": "a1", "total_tokens": 21844},
    {"name": "test-writer", "task_id": "a2", "total_tokens": 41000},
]


@pytest.mark.parametrize("kind", RUN_KINDS)
def test_a_run_line_carries_its_kind_map_commit_and_each_subagents_tokens(tmp_path: Path, kind: str) -> None:
    # Breaks when: a run line drops the map commit or the agents, names their fields otherwise,
    # or a research or ask run is refused or written under another kind.
    path = tmp_path / "ledger.jsonl"
    Ledger(path).append(kind, "s1", "sess-a", Spend(tokens=40, dollars=0.5), "4f2a9c1", _subagents())
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["kind"] == kind
    assert entry.get("map") == "4f2a9c1"
    assert entry.get("agents") == SUBAGENT_RECORDS


@pytest.mark.parametrize("kind", RUN_KINDS)
def test_a_run_line_with_no_map_and_no_agents_holds_null_and_an_empty_list(tmp_path: Path, kind: str) -> None:
    # Breaks when: a run without a map omits `map` or writes other than null, or omits `agents`.
    path = tmp_path / "ledger.jsonl"
    Ledger(path).append(kind, "s1", "sess-a", Spend(tokens=40, dollars=0.5))
    entry = json.loads(path.read_text().splitlines()[0])
    assert entry["kind"] == kind
    assert "map" in entry and entry["map"] is None
    assert entry.get("agents") == []


def test_a_run_line_by_keyword_keeps_the_map_and_agents_given(tmp_path: Path) -> None:
    # Breaks when: `map_commit` and `agents` are not the keyword names, or are swapped.
    path = tmp_path / "ledger.jsonl"
    Ledger(path).append(
        "research", "s2", "sess-r", Spend(tokens=9, dollars=0.125), agents=_subagents()[:1], map_commit=None
    )
    entry = json.loads(path.read_text().splitlines()[0])
    assert "map" in entry and entry["map"] is None
    assert entry.get("agents") == SUBAGENT_RECORDS[:1]


# Behavior 4: `_parse` is unchanged, so `total`, `over`, `unreadable` and `sessions` read the
# new lines as they read lead lines.


def _new_shape(path: Path) -> None:
    """Every line in the file is a run line of the new form, holding `map` and `agents`, so the
    reads below are of the new lines and not of lead lines without them."""
    for line in path.read_text().splitlines():
        entry = json.loads(line)
        assert "map" in entry and isinstance(entry.get("agents"), list)


def _ledger_with_research(path: Path) -> Ledger:
    """Four run lines, one of each kind, with maps and agents: 52 tokens, $1.875."""
    ledger = Ledger(path)
    ledger.append("lead", "s1", "sess-lead", Spend(tokens=40, dollars=0.5), "4f2a9c1", _subagents())
    ledger.append("research", "s1", "sess-research", Spend(tokens=7, dollars=1.0), "4f2a9c1", _subagents())
    ledger.append("ask", "s1", "sess-research", Spend(tokens=3, dollars=0.25), None, _subagents()[1:])
    ledger.append("recut", "s1", "sess-recut", Spend(tokens=2, dollars=0.125), "4f2a9c1", ())
    _new_shape(path)
    return ledger


def test_total_sums_research_and_ask_lines_as_it_sums_lead_lines(tmp_path: Path) -> None:
    # Breaks when: a research or ask line, or one carrying a map or agents, is skipped or its
    # subagents' tokens are added to the run's own.
    ledger = _ledger_with_research(tmp_path / "ledger.jsonl")
    assert _call(ledger.total, None) == Spend(tokens=52, dollars=1.875)


def test_total_since_counts_only_research_and_ask_lines_after_it(tmp_path: Path) -> None:
    # Breaks when: a research or ask line's time is not read as a lead line's is.
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append("research", "s1", "sess-old", Spend(tokens=1_000, dollars=4.0), "4f2a9c1", _subagents())
    start = _tick()
    ledger.append("research", "s2", "sess-new", Spend(tokens=30, dollars=0.5), "9b0d3e7", _subagents())
    ledger.append("ask", "s2", "sess-new", Spend(tokens=5, dollars=0.25), None, ())
    _new_shape(path)
    assert _call(ledger.total, start) == Spend(tokens=35, dollars=0.75)


def test_over_counts_research_and_ask_lines(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: research or ask spend escapes the budgets.
    cfg = dataclasses.replace(fake_cfg, token_budget=53, dollar_budget=1.9)
    ledger = _ledger_with_research(tmp_path / "ledger.jsonl")
    assert _call(ledger.over, cfg, Spend(tokens=0, dollars=0.0), None) is None
    assert _call(ledger.over, cfg, Spend(tokens=2, dollars=0.0), None) == "tokens"
    assert _call(ledger.over, cfg, Spend(tokens=0, dollars=0.125), None) == "dollars"


def test_unreadable_reads_lines_with_a_map_and_agents_as_readable(tmp_path: Path) -> None:
    # Breaks when: a line with `map` or `agents` is counted unreadable.
    path = tmp_path / "ledger.jsonl"
    ledger = _ledger_with_research(path)
    assert _call(ledger.unreadable) == []
    _raw(path, "not json\n")
    ledger.append("ask", "s1", "sess-research", Spend(tokens=1, dollars=0.0), None, _subagents())
    assert _call(ledger.unreadable) == [5]


def test_sessions_lists_research_and_ask_lines_in_the_order_written(tmp_path: Path) -> None:
    # Breaks when: `sessions()` skips research or ask lines, or lines carrying a map or agents.
    ledger = _ledger_with_research(tmp_path / "ledger.jsonl")
    assert _call(ledger.sessions) == [
        ("s1", "sess-lead"),
        ("s1", "sess-research"),
        ("s1", "sess-research"),
        ("s1", "sess-recut"),
    ]
