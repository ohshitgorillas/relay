"""Red tests for Relay's command line (design: Modules, `relay/cli.py`; Order 13)."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Callable

import pytest

import relay.cli as cli_module
import relay.loop as loop_module
from relay.cli import main
from relay.config import Config
from relay.errors import ExitCode, LockedError, QueueFormatError, RelayError
from relay.ledger import Ledger, Spend
from relay.state import State

QUEUE = "workboard-queue.md"
DAY = 24 * 60 * 60


def _toml_list(items: list[str]) -> str:
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_cfg: Config) -> Path:
    """A fake home whose `~/.config/relay/config.toml` holds `fake_cfg`'s values."""
    path = tmp_path / "home"
    config_dir = path / ".config" / "relay"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(
        f"context_limit = {fake_cfg.context_limit}\n"
        f"hard_ceiling = {fake_cfg.hard_ceiling}\n"
        f"poll_seconds = {fake_cfg.poll_seconds}\n"
        f"lead_command = {_toml_list(fake_cfg.lead_command)}\n"
        f"recut_command = {_toml_list(fake_cfg.recut_command)}\n"
        f"ping_command = {_toml_list(fake_cfg.ping_command)}\n"
        f"state_root = {json.dumps(str(fake_cfg.state_root))}\n"
    )
    monkeypatch.setenv("HOME", str(path))
    return path


@pytest.fixture
def queue(queue_file: Callable[[str], Path], home: Path) -> Path:
    return queue_file(QUEUE)


def _exit(argv: list[str] | None) -> int:
    """`main`'s exit status, whether it returns it or raises `SystemExit` with it."""
    try:
        return main(argv)
    except SystemExit as stop:
        # As the interpreter maps it: no code is status 0, a non-int code is status 1.
        if stop.code is None:
            return 0
        return stop.code if isinstance(stop.code, int) else 1


def _patch_run(monkeypatch: pytest.MonkeyPatch, fake: Callable[[Path, Config], int]) -> None:
    """Swap `relay.loop.run` for `fake`, however `relay.cli` reaches it."""
    real = loop_module.run
    for name, value in list(vars(cli_module).items()):
        if value is real:
            monkeypatch.setattr(cli_module, name, fake)
    monkeypatch.setattr(loop_module, "run", fake)


def _recording_run(calls: list[tuple[Path, Config]], code: int) -> Callable[[Path, Config], int]:
    def run(queue: Path, cfg: Config) -> int:
        calls.append((Path(queue), cfg))
        return code

    return run


def _raising_run(error: Exception) -> Callable[[Path, Config], int]:
    def run(queue: Path, cfg: Config) -> int:
        raise error

    return run


def _section_line(out: str, sid: str) -> str:
    """The one output line naming section `sid` as a whole id."""
    pattern = re.compile(rf"(?<![\w.]){re.escape(sid)}(?![\w.])")
    lines = [line for line in out.splitlines() if pattern.search(line)]
    assert len(lines) == 1, lines
    return lines[0]


def _number(out: str, value: str) -> bool:
    """True when `out` shows a number equal to `value`; a decimal `value` may be shown to any
    precision from two places on, so it matches within half a cent."""
    want = float(value)
    tolerance = 0.005 + 1e-9 if "." in value else 0.0
    return any(
        abs(float(shown) - want) <= tolerance
        for shown in re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.]*\d)", out)
    )


# Behavior 1: `relay/cli.py`: the `relay` console script.


def test_go_runs_the_loop_on_the_queue_with_the_config_file_and_returns_its_exit_code(
    queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, Config]] = []
    _patch_run(monkeypatch, _recording_run(calls, ExitCode.FAILED_TWICE))
    assert _exit(["go", str(queue)]) == 5
    assert len(calls) == 1
    ran_queue, cfg = calls[0]
    assert ran_queue.resolve() == queue.resolve()
    assert cfg.state_root == fake_cfg.state_root
    assert cfg.lead_command == fake_cfg.lead_command
    assert cfg.context_limit == 100_000
    assert cfg.token_budget is None
    assert cfg.dollar_budget is None


def test_go_passes_budget_and_context_limit_options_as_overrides(
    queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, Config]] = []
    _patch_run(monkeypatch, _recording_run(calls, ExitCode.BUDGET))
    argv = ["go", str(queue), "--token-budget", "5000", "--dollar-budget", "2.5", "--context-limit", "60000"]
    assert _exit(argv) == 3
    assert len(calls) == 1
    cfg = calls[0][1]
    assert cfg.token_budget == 5000
    assert cfg.dollar_budget == 2.5
    assert cfg.context_limit == 60_000
    assert cfg.state_root == fake_cfg.state_root


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (LockedError("another relay go holds this queue"), 2),
        (QueueFormatError("queue does not parse"), 2),
        (RelayError("something failed"), 1),
    ],
    ids=["locked", "queue-format", "relay-error"],
)
def test_a_relay_error_becomes_its_exit_code(
    error: RelayError, code: int, queue: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_run(monkeypatch, _raising_run(error))
    assert _exit(["go", str(queue)]) == code


def test_a_bad_config_file_exits_with_usage(queue: Path, home: Path) -> None:
    (home / ".config" / "relay" / "config.toml").write_text("context_limit = [unclosed\n")
    assert _exit(["status", str(queue)]) == ExitCode.USAGE


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["go"],
        ["launch", "queue.md"],
        ["go", "QUEUE", "--token-budget", "lots"],
        ["answer", "QUEUE", "s2"],
    ],
    ids=["no-command", "go-without-queue", "unknown-command", "non-number-budget", "answer-without-text"],
)
def test_bad_arguments_exit_with_usage_and_never_run_the_loop(
    argv: list[str], queue: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, Config]] = []
    _patch_run(monkeypatch, _recording_run(calls, ExitCode.QUEUE_EMPTY))
    argv = [str(queue) if arg == "QUEUE" else arg for arg in argv]
    assert _exit(argv) == ExitCode.USAGE
    assert calls == []


def test_main_with_no_argv_reads_the_command_line(
    queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["relay", "stop", str(queue)])
    assert _exit(None) == 0
    assert State.open(queue, fake_cfg).stop_file.exists()


# Behavior 2: creates the stop file


def test_stop_creates_the_queues_stop_file(queue: Path, fake_cfg: Config) -> None:
    assert not State.open(queue, fake_cfg).stop_file.exists()
    assert _exit(["stop", str(queue)]) == 0
    assert State.open(queue, fake_cfg).stop_file.exists()


def test_stop_by_relative_path_creates_the_same_stop_file(
    queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(queue.parent)
    assert _exit(["stop", queue.name]) == 0
    assert State.open(queue.resolve(), fake_cfg).stop_file.exists()


def test_stop_works_while_a_relay_go_holds_the_lock(queue: Path, fake_cfg: Config) -> None:
    holder = State.open(queue, fake_cfg)
    holder.lock()
    assert _exit(["stop", str(queue)]) == 0
    assert holder.stop_file.exists()


def test_stop_never_edits_the_queue_and_never_runs_the_loop(
    queue: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, Config]] = []
    _patch_run(monkeypatch, _recording_run(calls, ExitCode.QUEUE_EMPTY))
    before = queue.read_bytes()
    assert _exit(["stop", str(queue)]) == 0
    assert queue.read_bytes() == before
    assert calls == []


# Behavior 3: sets the answer, reopens the section


def test_answer_sets_the_answer_and_reopens_a_parked_section(queue: Path, fake_cfg: Config) -> None:
    State.open(queue, fake_cfg).park("s2", "Which port should the server use?")
    assert _exit(["answer", str(queue), "s2", "Use port 8080."]) == 0
    section = State.open(queue, fake_cfg).section("s2")
    assert section.status == "open"
    assert section.answer == "Use port 8080."


def test_answer_leaves_other_sections_alone(queue: Path, fake_cfg: Config) -> None:
    state = State.open(queue, fake_cfg)
    state.park("s2", "Which port?")
    state.park("s3", "Which host?")
    assert _exit(["answer", str(queue), "s2", "Port 8080."]) == 0
    other = State.open(queue, fake_cfg).section("s3")
    assert other.status == "parked"
    assert other.question == "Which host?"
    assert other.answer is None


def test_answer_works_while_a_relay_go_holds_the_lock(queue: Path, fake_cfg: Config) -> None:
    holder = State.open(queue, fake_cfg)
    holder.park("s2", "Which port?")
    holder.lock()
    assert _exit(["answer", str(queue), "s2", "Port 8080."]) == 0
    section = State.open(queue, fake_cfg).section("s2")
    assert section.status == "open"
    assert section.answer == "Port 8080."


def test_answer_never_edits_the_queue(queue: Path, fake_cfg: Config) -> None:
    State.open(queue, fake_cfg).park("s2", "Which port?")
    before = queue.read_bytes()
    assert _exit(["answer", str(queue), "s2", "Port 8080."]) == 0
    assert queue.read_bytes() == before


def test_answer_to_a_section_relay_marked_done_is_dropped_and_said(
    queue: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: an answer reopens a done section, so the next `relay go` resumes its lead.
    State.open(queue, fake_cfg).mark_done("s2")
    assert _exit(["answer", str(queue), "s2", "Port 8080."]) == 0
    section = State.open(queue, fake_cfg).section("s2")
    assert section.status == "done"
    assert section.answer is None
    assert capsys.readouterr().err == "relay: section s2 is done; answer dropped\n"


def test_answer_to_a_section_the_queue_marks_done_is_dropped_and_said(
    queue: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    text = queue.read_text()
    header = next(line for line in text.splitlines() if line.startswith("section s2 |"))
    queue.write_text(text.replace(header, header + " | done"))
    assert _exit(["answer", str(queue), "s2", "Port 8080."]) == 0
    assert State.open(queue, fake_cfg).section("s2").answer is None
    assert capsys.readouterr().err == "relay: section s2 is done; answer dropped\n"


# Behavior 4: `relay status` shows the rolling 7-day total (`since` = now minus 7 days)
# beside the all-time total.


def _ledger_path(queue: Path, cfg: Config) -> Path:
    """The queue's ledger: `<state dir>/ledger.jsonl`."""
    return State.open(queue, cfg).stop_file.parent / "ledger.jsonl"


def _write_entries(path: Path, entries: list[tuple[float, int, float]]) -> None:
    path.write_text(
        "".join(
            json.dumps({"kind": "lead", "section": "s1.1.1", "session": None,
                        "time": stamp, "tokens": tokens, "dollars": dollars}) + "\n"
            for stamp, tokens, dollars in entries
        )
    )


def test_status_shows_the_rolling_7_day_total_beside_the_all_time_total(
    queue: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    now = time.time()
    _write_entries(
        _ledger_path(queue, fake_cfg),
        [(now - 8 * DAY, 456, 2.5), (now - 6 * DAY, 100, 0.125), (now - 3600, 23, 0.125)],
    )
    assert _exit(["status", str(queue)]) == 0
    out = capsys.readouterr().out
    assert _number(out, "123")
    assert _number(out, "0.25")
    assert _number(out, "579")
    assert _number(out, "2.75")


def test_status_7_day_total_counts_an_entry_appended_now(
    queue: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _ledger_path(queue, fake_cfg)
    _write_entries(path, [(time.time() - 30 * DAY, 500, 4.5)])
    Ledger(path).append("lead", "s1.1.1", "sess-1", Spend(tokens=371, dollars=0.375))
    assert _exit(["status", str(queue)]) == 0
    out = capsys.readouterr().out
    assert _number(out, "371")
    assert _number(out, "0.375")
    assert _number(out, "871")
    assert _number(out, "4.875")


def test_status_prints_each_sections_state(
    queue: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    state = State.open(queue, fake_cfg)
    state.mark_done("s2")
    state.park("s3", "Which port?")
    assert _exit(["status", str(queue)]) == 0
    out = capsys.readouterr().out
    assert "done" in _section_line(out, "s2")
    assert "parked" in _section_line(out, "s3")
    assert "open" in _section_line(out, "s4")


def test_status_names_the_ledger_and_its_unreadable_lines_as_skipped(
    queue: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _ledger_path(queue, fake_cfg)
    now = time.time()
    _write_entries(path, [(now - 60, 10, 0.5)])
    with path.open("a") as ledger:
        ledger.write("not json\n")
        ledger.write(json.dumps({"time": now, "tokens": 5, "dollars": 0.25}) + "\n")
        ledger.write(json.dumps({"time": now, "tokens": 5}) + "\n")
    assert _exit(["status", str(queue)]) == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if str(path) in line]
    assert len(lines) == 1, lines
    rest = lines[0].replace(str(path), " ")
    assert "skip" in rest.lower()
    assert _number(rest, "2")
    assert _number(rest, "4")
    assert not _number(rest, "3")


def test_status_with_a_readable_ledger_prints_no_skipped_line(
    queue: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _ledger_path(queue, fake_cfg)
    now = time.time()
    # Totals 25 tokens and 1.25 dollars, so no total reads as a line number 1 or 2.
    _write_entries(path, [(now - 60, 10, 0.5), (now - 30, 15, 0.75)])
    assert _exit(["status", str(queue)]) == 0
    out = capsys.readouterr().out
    assert "skip" not in out.lower()
    # A line may name the ledger, but none names it with line numbers as if some were skipped.
    for line in out.splitlines():
        if str(path) in line:
            rest = line.replace(str(path), " ")
            assert not _number(rest, "1") and not _number(rest, "2"), line


# `relay status` adds, per section, the subagents its runs spawned: count, total time and the
# biggest by context, from the run logs the ledger files under that section.

AGENTS_LOG = Path(__file__).parent / "fixtures" / "stream-agents.jsonl"


def test_status_summarises_each_sections_subagents_from_its_run_logs(
    queue: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    state = State.open(queue, fake_cfg)
    state.run_dir.mkdir(parents=True)
    (state.run_dir / "1.jsonl").write_bytes(AGENTS_LOG.read_bytes())
    Ledger(state.ledger_path).append("lead", "s2", "sess-agents-1", Spend(tokens=1, dollars=0.25))
    assert _exit(["status", str(queue)]) == 0
    out = capsys.readouterr().out
    line = _section_line(out, "s2")
    assert "2 agents" in line
    assert "2m11s" in line  # 36.9s + 95.0s
    assert "biggest test-writer at context 41000" in line
    assert "agent" not in _section_line(out, "s3")


def test_status_files_a_resumed_sessions_runs_under_each_section_in_turn(
    queue: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    state = State.open(queue, fake_cfg)
    state.run_dir.mkdir(parents=True)
    (state.run_dir / "1.jsonl").write_bytes(AGENTS_LOG.read_bytes())
    (state.run_dir / "2.jsonl").write_text(
        AGENTS_LOG.read_text().splitlines()[0] + "\n"
        + json.dumps({"type": "system", "subtype": "task_started", "task_id": "c1",
                      "description": "Review", "subagent_type": "diff-reviewer",
                      "task_type": "local_agent", "session_id": "sess-agents-1"}) + "\n"
    )
    ledger = Ledger(state.ledger_path)
    ledger.append("lead", "s2", "sess-agents-1", Spend(tokens=1, dollars=0.0))
    ledger.append("lead", "s3", "sess-agents-1", Spend(tokens=1, dollars=0.0))
    assert _exit(["status", str(queue)]) == 0
    out = capsys.readouterr().out
    assert "2 agents" in _section_line(out, "s2")
    assert "1 agent," in _section_line(out, "s3")


# `relay go` gains `--idle-ceiling` (relay-check design, Modules, `relay/config.py`).


def test_go_passes_the_idle_ceiling_option_as_an_override(
    queue: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: `relay go` has no `--idle-ceiling`, or drops it so the default 130000 holds.
    calls: list[tuple[Path, Config]] = []
    _patch_run(monkeypatch, _recording_run(calls, ExitCode.QUEUE_EMPTY))
    assert _exit(["go", str(queue), "--idle-ceiling", "150000"]) == ExitCode.QUEUE_EMPTY
    assert len(calls) == 1
    cfg = calls[0][1]
    assert cfg.idle_ceiling == 150_000
    assert cfg.context_limit == 100_000
    assert cfg.hard_ceiling == 200_000


@pytest.mark.parametrize(
    "value",
    ["100000", "200000", "lots"],
    ids=["at-context-limit", "at-hard-ceiling", "non-number"],
)
def test_go_with_an_idle_ceiling_out_of_range_exits_with_usage_and_never_runs_the_loop(
    value: str, queue: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: the `--idle-ceiling` override skips `load_config`'s range check
    # (context_limit < idle_ceiling < hard_ceiling), or a non-number reaches the loop.
    calls: list[tuple[Path, Config]] = []
    _patch_run(monkeypatch, _recording_run(calls, ExitCode.QUEUE_EMPTY))
    assert _exit(["go", str(queue), "--idle-ceiling", value]) == ExitCode.USAGE
    assert calls == []
