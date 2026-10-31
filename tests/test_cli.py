"""Red tests for Relay's command line (design: Modules, `relay/cli.py`; Order 13)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Iterator

import pytest

import relay.cli as cli_module
import relay.loop as loop_module
from relay.cli import main
from relay.config import Config
from relay.errors import ExitCode, LockedError, QueueFormatError, RelayError
from relay.ledger import Ledger, Spend
from relay.state import State
from tests.conftest import _GIT, GitRepo

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
    argv = [
        "go",
        str(queue),
        "--token-budget",
        "5000",
        "--dollar-budget",
        "2.5",
        "--context-limit",
        "60000",
    ]
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
    ids=[
        "no-command",
        "go-without-queue",
        "unknown-command",
        "non-number-budget",
        "answer-without-text",
    ],
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
            json.dumps(
                {
                    "kind": "lead",
                    "section": "s1.1.1",
                    "session": None,
                    "time": stamp,
                    "tokens": tokens,
                    "dollars": dollars,
                }
            )
            + "\n"
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
        AGENTS_LOG.read_text().splitlines()[0]
        + "\n"
        + json.dumps(
            {
                "type": "system",
                "subtype": "task_started",
                "task_id": "c1",
                "description": "Review",
                "subagent_type": "diff-reviewer",
                "task_type": "local_agent",
                "session_id": "sess-agents-1",
            }
        )
        + "\n"
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


# `relay ask <queue> <section> <question>` (relay-research design, Modules, `relay/cli.py` and
# `relay/loop.py` `ask`; Order 7): the answer printed, the session resumed, an `ask` ledger line;
# only the answer on stdout, its progress nowhere; ResearchError (exit 1) when the section has
# no research_session, the run fails or is killed, or there is no answer.

FIXTURES_DIR = Path(__file__).parent / "fixtures"
ASK_STREAM = "stream-ask.jsonl"  # session "sess-research-1", one assistant message, an ANSWER block
ASK_SESSION = "sess-research-1"
ASK_ANSWER = (
    "ANSWER\n"
    "relay/loop.py:208-213 | ask resumes the researcher under the research lock\n"
    "relay/cli.py:228 | _COMMANDS routes ask to _ask\n"
    "END ANSWER"
)
ASK_CONTEXT = 3 + 1200 + 5000  # the ask stream's one assistant message's context
ASK_SPEND = Spend(tokens=3 + 1200 + 5000 + 40, dollars=0.125)
# Session "sess-research-1", a successful result (is_error false) whose text holds no ANSWER block.
NO_ANSWER_STREAM = "stream-ask-no-answer.jsonl"
ASK_SID = "s2"
QUESTION = "Where does the ask command resume the researcher?"

# A research command that reads its prompt on stdin, appends `{"argv", "prompt"}` (argv after
# its own three arguments) as one JSON line to the record path, runs the fake `claude` on the
# same prompt with its stdout passed through, then exits with the given status.
_ASK_SHIM = """\
import json, subprocess, sys
record, fake, code = sys.argv[1], sys.argv[2], int(sys.argv[3])
prompt = sys.stdin.read()
with open(record, "a") as f:
    f.write(json.dumps({"argv": sys.argv[4:], "prompt": prompt}) + chr(10))
subprocess.run([fake], input=prompt, text=True, check=True)
sys.exit(code)
"""


# Two phases of one ask run whose context climbs, both in session "sess-research-1": the first an
# init and one message at CLIMB_FLAG_CONTEXT, the second one message at CLIMB_PAST_CONTEXT and a
# successful result holding ASK_ANSWER's block.
CLIMB_FLAG_STREAM = "stream-ask-climb-flag.jsonl"
CLIMB_PAST_STREAM = "stream-ask-climb-past.jsonl"
CLIMB_FLAG_CONTEXT = 3 + 1200 + 5000
CLIMB_PAST_CONTEXT = 3 + 1200 + 8000

# A research command that records its run as `_ASK_SHIM` does (argv after its own six arguments),
# runs the fake `claude` on the first stream, waits for the flag file, makes an empty commit with
# the given git argv, then runs the fake on the second stream.
_ASK_CLIMB_SHIM = """\
import json, os, subprocess, sys, time
record, fake, flag, first, second = sys.argv[1:6]
git = json.loads(sys.argv[6])
prompt = sys.stdin.read()
with open(record, "a") as f:
    f.write(json.dumps({"argv": sys.argv[7:], "prompt": prompt}) + chr(10))
def emit(stream):
    sys.stdout.flush()
    env = dict(os.environ, RELAY_FAKE_SCENARIO=stream)
    subprocess.run([fake], input="", text=True, env=env, check=True)
emit(first)
end = time.time() + 10
while time.time() < end and not os.path.exists(flag):
    time.sleep(0.02)
time.sleep(0.2)
subprocess.run([*git, "commit", "--allow-empty", "-q", "-m", "ask step"], stdin=subprocess.DEVNULL, check=True)
emit(second)
"""


def _ask_config(
    home: Path,
    cfg: Config,
    record: Path,
    exit_code: int = 0,
    research: list[str] | None = None,
    **overrides: int,
) -> None:
    """Rewrite the fake home's config file with `cfg`'s values, `overrides` on top, and a
    research command that records each run to `record` and exits `exit_code` (or `research`)."""
    if research is None:
        research = [
            sys.executable,
            "-c",
            _ASK_SHIM,
            str(record),
            cfg.lead_command[0],
            str(exit_code),
        ]
    values: dict[str, object] = {
        "context_limit": cfg.context_limit,
        "hard_ceiling": cfg.hard_ceiling,
        "poll_seconds": cfg.poll_seconds,
        "map_max_chars": cfg.map_max_chars,
    }
    values.update(overrides)
    text = "".join(f"{key} = {value}\n" for key, value in values.items())
    (home / ".config" / "relay" / "config.toml").write_text(
        text
        + f"lead_command = {_toml_list(cfg.lead_command)}\n"
        + f"recut_command = {_toml_list(cfg.recut_command)}\n"
        + f"ping_command = {_toml_list(cfg.ping_command)}\n"
        + f"research_command = {_toml_list(research)}\n"
        + f"state_root = {json.dumps(str(cfg.state_root))}\n"
    )


def _asks(record: Path) -> list[dict[str, object]]:
    if not record.exists():
        return []
    return [json.loads(line) for line in record.read_text().splitlines()]


def _ledger_entries(queue: Path, cfg: Config) -> list[dict[str, object]]:
    path = State.open(queue, cfg).ledger_path
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def asked(
    queue: Path,
    home: Path,
    fake_cfg: Config,
    tmp_path: Path,
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Section s2 with a researcher session, the ask stream scripted, the shim research command
    configured; returns the shim's record path."""
    monkeypatch.chdir(tmp_path)
    record = tmp_path / "ask-record.jsonl"
    _ask_config(home, fake_cfg, record)
    State.open(queue, fake_cfg).set_research_session(ASK_SID, ASK_SESSION)
    scenario((FIXTURES_DIR / ASK_STREAM).read_text().splitlines())
    return record


def test_ask_prints_the_answer_and_exits_0(
    asked: Path, queue: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: `relay ask` is not a command, prints nothing, or prints the result's prose
    # around the ANSWER block, or the block without its ANSWER / END ANSWER lines.
    assert _exit(["ask", str(queue), ASK_SID, QUESTION]) == 0
    assert capsys.readouterr().out.rstrip("\n") == ASK_ANSWER


def test_ask_resumes_the_sections_research_session_with_the_question(
    asked: Path, queue: Path
) -> None:
    # Breaks when: ask starts a fresh researcher, resumes another section's or the lead's
    # session, or leaves the question out of the brief.
    assert _exit(["ask", str(queue), ASK_SID, QUESTION]) == 0
    runs = _asks(asked)
    assert len(runs) == 1
    assert runs[0]["argv"][-2:] == ["--resume", ASK_SESSION]
    assert QUESTION in str(runs[0]["prompt"])


def test_ask_appends_one_ask_ledger_line_for_the_section_and_its_spend(
    asked: Path, queue: Path, fake_cfg: Config
) -> None:
    # Breaks when: the ask run is not ledgered, is ledgered under another kind or section, or
    # its spend, session, map or agents are dropped.
    assert _exit(["ask", str(queue), ASK_SID, QUESTION]) == 0
    entries = _ledger_entries(queue, fake_cfg)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["kind"] == "ask"
    assert entry["section"] == ASK_SID
    assert entry["session"] == ASK_SESSION
    assert entry["tokens"] == ASK_SPEND.tokens
    assert entry["dollars"] == ASK_SPEND.dollars
    assert "map" in entry and entry["map"] is None
    assert entry.get("agents") == []


def test_ask_works_while_a_relay_go_holds_the_lock(
    asked: Path, queue: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: ask takes the `relay go` lock, so it fails while the lead that asks runs.
    holder = State.open(queue, fake_cfg)
    holder.lock()
    assert _exit(["ask", str(queue), ASK_SID, QUESTION]) == 0
    assert capsys.readouterr().out.rstrip("\n") == ASK_ANSWER


def test_ask_prints_only_the_answer_and_no_progress(
    asked: Path, queue: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: ask's run writes progress lines (agent events, started or finished lines)
    # to stdout or stderr.
    assert _exit(["ask", str(queue), ASK_SID, QUESTION]) == 0
    captured = capsys.readouterr()
    assert captured.out == ASK_ANSWER + "\n"
    assert captured.err == ""


def test_ask_with_no_research_session_exits_1_and_runs_nothing(
    queue: Path,
    home: Path,
    fake_cfg: Config,
    tmp_path: Path,
    scenario: Callable[[list[str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: ask with no researcher to resume starts one anyway, exits 0 or another code,
    # or prints an answer.
    monkeypatch.chdir(tmp_path)
    record = tmp_path / "ask-record.jsonl"
    _ask_config(home, fake_cfg, record)
    State.open(queue, fake_cfg).set_research_session("s3", ASK_SESSION)
    scenario((FIXTURES_DIR / ASK_STREAM).read_text().splitlines())
    assert _exit(["ask", str(queue), ASK_SID, QUESTION]) == 1
    assert capsys.readouterr().out == ""
    assert _asks(record) == []
    assert [e for e in _ledger_entries(queue, fake_cfg) if e.get("kind") == "ask"] == []


def test_ask_whose_run_exits_non_zero_exits_1_and_prints_no_answer(
    asked: Path, queue: Path, home: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: a failed ask run's ANSWER block is still printed, or ask exits 0.
    _ask_config(home, fake_cfg, asked, exit_code=1)
    assert _exit(["ask", str(queue), ASK_SID, QUESTION]) == 1
    assert len(_asks(asked)) == 1
    assert capsys.readouterr().out == ""


# `relay ask` whose researcher run fails (relay-research design, `relay/loop.py` `ask`; Order 13):
# exit 1 and "the researcher for section <sid> failed: <runner.error_line(result)>", the error line
# the last non-empty line of the run's stderr, else the error result's text, else "used no tokens",
# else "exit N" (`relay/runner.py` `error_line`). The shim records its run as `_ASK_SHIM` does
# (argv after its own four arguments), runs the fake `claude`, writes its fourth argument to
# stderr and exits with its third.
_ASK_STDERR_SHIM = """\
import json, subprocess, sys
record, fake, code, err = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
prompt = sys.stdin.read()
with open(record, "a") as f:
    f.write(json.dumps({"argv": sys.argv[5:], "prompt": prompt}) + chr(10))
subprocess.run([fake], input=prompt, text=True, check=True)
sys.stderr.write(err)
sys.exit(code)
"""

ERROR_STREAM = "stream-error.jsonl"  # a result with is_error set and the text "Prompt is too long"

# (exit code, stderr, scenario lines or None for the ask stream, error line)
_FAILED_ASKS: dict[str, tuple[int, str, list[str] | None, str]] = {
    "exit-nonzero-with-stderr": (
        1,
        "warming up\nresearcher crashed: reader died\n\n",
        None,
        "researcher crashed: reader died",
    ),
    "exit-nonzero-bare": (3, "", None, "exit 3"),
    "error-result": (
        0,
        "",
        (FIXTURES_DIR / ERROR_STREAM).read_text().splitlines(),
        "Prompt is too long",
    ),
    "error-result-with-stderr": (
        0,
        "api overloaded, retry later\n",
        (FIXTURES_DIR / ERROR_STREAM).read_text().splitlines(),
        "api overloaded, retry later",
    ),
    "no-tokens": (0, "", [], "used no tokens"),
}


@pytest.mark.parametrize("how", list(_FAILED_ASKS))
def test_ask_whose_researcher_run_fails_exits_1_and_names_its_error_line(
    how: str,
    asked: Path,
    queue: Path,
    home: Path,
    fake_cfg: Config,
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a failed ask run exits 0, prints an answer, is reported as "no answer" or
    # without its error line, or its error line comes from the wrong source or in the wrong order
    # (all of stderr rather than its last non-empty line, the error result's text ahead of
    # stderr, "exit N" for an error result or a run that used no tokens).
    code, err, lines, error = _FAILED_ASKS[how]
    research = [
        sys.executable,
        "-c",
        _ASK_STDERR_SHIM,
        str(asked),
        fake_cfg.lead_command[0],
        str(code),
        err,
    ]
    _ask_config(home, fake_cfg, asked, research=research)
    if lines is not None:
        scenario(lines)
    assert _exit(["ask", str(queue), ASK_SID, QUESTION]) == 1
    assert len(_asks(asked)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    message = f"the researcher for section {ASK_SID} failed: {error}"
    named = [line for line in captured.err.splitlines() if "researcher" in line or "fail" in line]
    assert len(named) == 1, captured.err
    assert named[0].endswith(message), captured.err


@pytest.fixture
def repo_queue(
    asked: Path, queue: Path, fake_cfg: Config, git_repo: GitRepo, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """The queue copied into `git_repo`'s main checkout, the git top level its runs take as cwd,
    with s2's researcher session set as `asked` sets it; the test's cwd is that checkout."""
    path = git_repo.root / queue.name
    path.write_bytes(queue.read_bytes())
    State.open(path, fake_cfg).set_research_session(ASK_SID, ASK_SESSION)
    monkeypatch.chdir(git_repo.root)
    return path


def _climbing_ask(queue: Path, cfg: Config, record: Path, git: list[str]) -> list[str]:
    """A research command running `_ASK_CLIMB_SHIM` on the two climbing streams, waiting for the
    queue's research flag for s2, then committing with `git`."""
    return [
        sys.executable,
        "-c",
        _ASK_CLIMB_SHIM,
        str(record),
        cfg.lead_command[0],
        str(State.open(queue, cfg).research_flag(ASK_SID)),
        str(FIXTURES_DIR / CLIMB_FLAG_STREAM),
        str(FIXTURES_DIR / CLIMB_PAST_STREAM),
        json.dumps(git),
    ]


def test_ask_whose_run_is_killed_at_the_hard_ceiling_exits_1_and_prints_no_answer(
    asked: Path,
    repo_queue: Path,
    home: Path,
    fake_cfg: Config,
    git_repo: GitRepo,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the hard ceiling does not watch an ask run, or a killed run's answer is used.
    # The run commits after the retire flag goes up, so the idle ceiling cannot kill it; without
    # the hard-ceiling kill it runs on to its answer and exits 0.
    queue = repo_queue
    research = _climbing_ask(queue, fake_cfg, asked, [*_GIT, "-C", str(git_repo.root)])
    _ask_config(
        home,
        fake_cfg,
        asked,
        research=research,
        context_limit=CLIMB_FLAG_CONTEXT - 200,
        idle_ceiling=CLIMB_PAST_CONTEXT - 100,
        hard_ceiling=CLIMB_PAST_CONTEXT,
    )
    first = git_repo.rev("main")
    assert _exit(["ask", str(queue), ASK_SID, QUESTION]) == 1
    assert len(_asks(asked)) == 1
    assert capsys.readouterr().out == ""
    assert git_repo.rev("main") != first


def test_ask_whose_run_idles_past_the_idle_ceiling_exits_1_and_prints_no_answer(
    asked: Path,
    repo_queue: Path,
    home: Path,
    fake_cfg: Config,
    git_repo: GitRepo,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the idle ceiling does not watch an ask run (relay-research design, Modules,
    # `relay/config.py`: context_limit, idle_ceiling and hard_ceiling watch a research run
    # unchanged), or a killed run's answer is used. The run makes no commit after the retire
    # flag goes up and its context stays below the hard ceiling; without the idle kill it runs
    # on to its answer and exits 0. Breaks too when the idle kill's retire line (relay-check
    # design, `_watcher` calls `progress.retired_idle`) reaches stdout or stderr: an ask's
    # progress goes nowhere (relay-research design, `relay/progress.py`).
    queue = repo_queue
    no_commit = [sys.executable, "-c", "pass"]
    research = _climbing_ask(queue, fake_cfg, asked, no_commit)
    _ask_config(
        home,
        fake_cfg,
        asked,
        research=research,
        context_limit=CLIMB_FLAG_CONTEXT - 200,
        idle_ceiling=CLIMB_PAST_CONTEXT - 100,
        hard_ceiling=CLIMB_PAST_CONTEXT + 1000,
    )
    assert _exit(["ask", str(queue), ASK_SID, QUESTION]) == 1
    assert len(_asks(asked)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    progress = tuple(f"{who} {ASK_SID}:" for who in ("lead", "recut", "research", "ask"))
    assert [line for line in captured.err.splitlines() if line.startswith(progress)] == []


def test_ask_whose_run_commits_after_the_flag_runs_past_the_idle_ceiling_to_its_answer(
    asked: Path,
    repo_queue: Path,
    home: Path,
    fake_cfg: Config,
    git_repo: GitRepo,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the watcher kills an ask run as soon as its retire flag goes up, or at the
    # idle ceiling although the run committed after the flag (relay-check design, `_watcher`:
    # the idle kill needs the heads unchanged since the flag; relay-research design,
    # `relay/config.py`: the ceilings watch a research run unchanged). The run's context passes
    # idle_ceiling and stays below hard_ceiling, so it runs on to its answer and exits 0, and
    # its progress goes nowhere (relay-research design, `relay/progress.py`).
    queue = repo_queue
    research = _climbing_ask(queue, fake_cfg, asked, [*_GIT, "-C", str(git_repo.root)])
    _ask_config(
        home,
        fake_cfg,
        asked,
        research=research,
        context_limit=CLIMB_FLAG_CONTEXT - 200,
        idle_ceiling=CLIMB_PAST_CONTEXT - 100,
        hard_ceiling=CLIMB_PAST_CONTEXT + 1000,
    )
    first = git_repo.rev("main")
    assert _exit(["ask", str(queue), ASK_SID, QUESTION]) == 0
    assert len(_asks(asked)) == 1
    captured = capsys.readouterr()
    assert captured.out == ASK_ANSWER + "\n"
    assert captured.err == ""
    assert git_repo.rev("main") != first


def test_ask_whose_result_holds_no_answer_exits_1(
    asked: Path,
    queue: Path,
    scenario: Callable[[list[str]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a result with no ANSWER block exits 0, or prints its prose as the answer.
    # The result is a success (is_error false), so the run itself does not fail.
    scenario((FIXTURES_DIR / NO_ANSWER_STREAM).read_text().splitlines())
    assert _exit(["ask", str(queue), ASK_SID, QUESTION]) == 1
    assert len(_asks(asked)) == 1
    assert capsys.readouterr().out == ""


def test_ask_whose_answer_is_over_map_max_chars_exits_1(
    asked: Path, queue: Path, home: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: the answer's cap is not cfg.map_max_chars, so an over-cap answer is printed.
    _ask_config(home, fake_cfg, asked, map_max_chars=len(ASK_ANSWER) - 1)
    assert _exit(["ask", str(queue), ASK_SID, QUESTION]) == 1
    assert capsys.readouterr().out == ""


# `relay go` gains `--section-dollar-cap` (float), which becomes the `section_dollar_cap`
# override; `relay status` prints a waiting section as `<id>  waiting on <blocker>`
# (relay-ladder design, Modules, `relay/cli.py` (extended); Order 8).


@pytest.mark.parametrize(
    ("value", "cap"),
    [("2.5", 2.5), ("5", 5.0)],
    ids=["decimal", "whole"],
)
def test_go_passes_the_section_dollar_cap_option_as_an_override(
    value: str, cap: float, queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: `relay go` has no `--section-dollar-cap`, drops it so the default None holds,
    # or passes it as a string rather than a float.
    calls: list[tuple[Path, Config]] = []
    _patch_run(monkeypatch, _recording_run(calls, ExitCode.QUEUE_EMPTY))
    assert _exit(["go", str(queue), "--section-dollar-cap", value]) == ExitCode.QUEUE_EMPTY
    assert len(calls) == 1
    cfg = calls[0][1]
    assert cfg.section_dollar_cap == cap
    assert isinstance(cfg.section_dollar_cap, float)
    assert cfg.dollar_budget is None
    assert cfg.state_root == fake_cfg.state_root


def test_status_prints_a_waiting_section_with_its_blocker(
    queue: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: status prints a waiting section as open or parked, or leaves out the
    # section it waits on.
    State.open(queue, fake_cfg).wait("s3", "s2")
    assert _exit(["status", str(queue)]) == 0
    out = capsys.readouterr().out
    assert "s3  waiting on s2" in _section_line(out, "s3")
    assert "open" in _section_line(out, "s4")


# `relay stop` signals a live run and `relay status` shows draining (relay-drain design, Modules,
# `relay/cli.py`; Order 4): `_stop` calls `state.live_run()`; with a live run whose pid is not its
# own it calls `runner.signal_drain(pid)` and touches no stop file; with none it touches `STOP`.


def _dead_pid() -> int:
    """The pid of a child that has exited and been reaped, so no live process is signalled."""
    child = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(child.stdout)


def _record_drains(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Swap `relay.runner.signal_drain` for a recorder, however `relay.cli` reaches it; returns
    the pids it is called with, in order."""
    import relay.runner as runner_module

    calls: list[int] = []

    def signal_drain(pid: int) -> None:
        calls.append(pid)

    real = runner_module.signal_drain
    for name, value in list(vars(cli_module).items()):
        if value is real:
            monkeypatch.setattr(cli_module, name, signal_drain)
    monkeypatch.setattr(runner_module, "signal_drain", signal_drain)
    return calls


def _live_run(queue: Path, cfg: Config, pid: int) -> State:
    """A `relay go` stand-in: holds the queue's lock and publishes `pid` as its run."""
    holder = State.open(queue, cfg)
    holder.lock()
    holder.publish_run(pid)
    return holder


def test_stop_on_a_live_run_signals_its_pid_and_touches_no_stop_file(
    queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: `relay stop` still only touches STOP while a run is live, signals another pid,
    # or touches STOP as well as signalling.
    calls = _record_drains(monkeypatch)
    pid = _dead_pid()
    holder = _live_run(queue, fake_cfg, pid)
    _exit(["stop", str(queue)])
    assert calls == [pid]
    assert not holder.stop_file.exists()


def test_stop_with_a_stale_run_record_and_a_free_lock_touches_stop_and_signals_nothing(
    queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: `_stop` trusts `run.json` without the lock probe, so a SIGKILLed run's stale
    # record is signalled and no stop file is left; or, once a run holds the lock and publishes
    # itself, `_stop` still only touches STOP.
    calls = _record_drains(monkeypatch)
    State.open(queue, fake_cfg).publish_run(_dead_pid())
    assert _exit(["stop", str(queue)]) == 0
    assert calls == []
    assert State.open(queue, fake_cfg).stop_file.exists()
    live = _dead_pid()
    holder = _live_run(queue, fake_cfg, live)  # bound, so its lock stays held through the stop
    _exit(["stop", str(queue)])
    assert calls == [live]
    del holder


def test_stop_with_the_lock_held_but_no_run_record_touches_stop_and_signals_nothing(
    queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: `_stop` signals on the lock alone, with no live-run record to name a pid; or,
    # once the holder publishes its run, `_stop` still only touches STOP.
    calls = _record_drains(monkeypatch)
    holder = State.open(queue, fake_cfg)
    holder.lock()
    assert _exit(["stop", str(queue)]) == 0
    assert calls == []
    assert holder.stop_file.exists()
    pid = _dead_pid()
    holder.publish_run(pid)
    _exit(["stop", str(queue)])
    assert calls == [pid]


def test_stop_never_signals_its_own_pid(
    queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: `_stop` signals a live run whose pid is its own, sending SIGTERM to itself;
    # or does not signal once the record names another pid.
    calls = _record_drains(monkeypatch)
    holder = _live_run(queue, fake_cfg, os.getpid())
    _exit(["stop", str(queue)])
    assert calls == []
    other = _dead_pid()
    holder.publish_run(other)
    _exit(["stop", str(queue)])
    assert calls == [other]


# A second `relay stop` on a draining run sends the second SIGTERM and stops it at once.


def test_a_second_stop_on_a_draining_run_signals_it_again(
    queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: `_stop` skips a run already draining, or falls back to STOP for it, so the
    # second SIGTERM that stops the run at once is never sent.
    calls = _record_drains(monkeypatch)
    pid = _dead_pid()
    holder = _live_run(queue, fake_cfg, pid)
    _exit(["stop", str(queue)])
    holder.mark_draining()  # as the run's first-SIGTERM `on_request` does
    _exit(["stop", str(queue)])
    assert calls == [pid, pid]
    assert not holder.stop_file.exists()


# `_status` prints `run: draining since HH:MM (pid N)` as its first line when `live_run()` says
# draining, and nothing new otherwise.


@pytest.fixture
def utc() -> Iterator[None]:
    """Local time is UTC for the test, so HH:MM reads the same in any zone."""
    saved = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    try:
        yield
    finally:
        if saved is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = saved
        time.tzset()


def _status_lines(queue: Path, capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert _exit(["status", str(queue)]) == 0
    return capsys.readouterr().out.splitlines()


def test_status_of_a_draining_run_opens_with_its_draining_line(
    queue: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str], utc: None
) -> None:
    # Breaks when: status leaves the draining line out, prints it below the section states,
    # shows another time or pid, or changes the rest of its output.
    before = _status_lines(queue, capsys)
    pid = _dead_pid()
    holder = _live_run(queue, fake_cfg, pid)
    holder.mark_draining()
    live = holder.live_run()
    assert live is not None and live.draining_since is not None
    since = time.strftime("%H:%M", time.gmtime(live.draining_since))
    lines = _status_lines(queue, capsys)
    assert lines[0] == f"run: draining since {since} (pid {pid})"
    assert lines[1:] == before


def test_status_of_a_live_run_not_draining_prints_nothing_new(
    queue: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str], utc: None
) -> None:
    # Breaks when: status prints a run line for a live run that is not draining; or prints no
    # draining line once that run starts draining.
    before = _status_lines(queue, capsys)
    pid = _dead_pid()
    holder = _live_run(queue, fake_cfg, pid)
    assert _status_lines(queue, capsys) == before
    holder.mark_draining()
    live = holder.live_run()
    assert live is not None and live.draining_since is not None
    since = time.strftime("%H:%M", time.gmtime(live.draining_since))
    assert _status_lines(queue, capsys) == [f"run: draining since {since} (pid {pid})", *before]


def test_status_with_a_stale_draining_record_and_a_free_lock_prints_nothing_new(
    queue: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str], utc: None
) -> None:
    # Breaks when: status reads `run.json` without the lock probe, so a dead run's draining
    # record is shown as a live drain; or shows no drain once a live run holds the lock.
    before = _status_lines(queue, capsys)
    stale = State.open(queue, fake_cfg)
    stale.publish_run(_dead_pid())
    stale.mark_draining()
    assert _status_lines(queue, capsys) == before
    pid = _dead_pid()
    holder = _live_run(queue, fake_cfg, pid)
    holder.mark_draining()
    live = holder.live_run()
    assert live is not None and live.draining_since is not None
    since = time.strftime("%H:%M", time.gmtime(live.draining_since))
    assert _status_lines(queue, capsys)[0] == f"run: draining since {since} (pid {pid})"


# `relay stats` (relay-stats design, Modules `relay/cli.py`): takes no arguments, reads every
# state directory under `state_root`, prints `stats.lines(...)` and returns QUEUE_EMPTY.

SECOND_QUEUE = "check-queue.md"


def _stats_log(state: State, number: int, session: str, context: int, result: str) -> None:
    """Write run log `<number>.jsonl`: one run of `session` whose main thread reached `context`
    tokens of context and whose result text is `result`."""
    lines = [
        {
            "type": "system",
            "subtype": "init",
            "session_id": session,
            "cwd": "/work",
            "model": "claude-opus",
            "tools": ["Bash"],
        },
        {
            "type": "assistant",
            "message": {
                "id": f"msg-{session}",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "Working."}],
                "usage": {
                    "input_tokens": 2,
                    "cache_creation_input_tokens": 1_000,
                    "cache_read_input_tokens": context - 1_002,
                    "output_tokens": 30,
                },
            },
            "parent_tool_use_id": None,
            "session_id": session,
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "duration_ms": 500,
            "num_turns": 1,
            "result": result,
            "session_id": session,
            "total_cost_usd": 0.01,
            "usage": {"input_tokens": 1, "output_tokens": 2},
        },
    ]
    state.run_dir.mkdir(parents=True, exist_ok=True)
    (state.run_dir / f"{number}.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines)
    )


def _stats_runs(state: State, runs: list[tuple[str, str, str, int, str]]) -> None:
    """Log and ledger each `(kind, section, session, context, result)` run in the order given."""
    ledger = Ledger(state.ledger_path)
    for number, (kind, section, session, context, result) in enumerate(runs, start=1):
        _stats_log(state, number, session, context, result)
        ledger.append(kind, section, session, Spend(tokens=1, dollars=0.0))


def _two_queues(
    queue: Path, queue_file: Callable[[str], Path], fake_cfg: Config
) -> tuple[State, State]:
    first = State.open(queue, fake_cfg)
    _stats_runs(
        first,
        [
            ("lead", "s1.1.1", "sess-a1", 40_000, "Step committed.\nDONE"),
            ("recut", "s3", "sess-a2", 7_000, "Cut into two steps."),
        ],
    )
    second = State.open(queue_file(SECOND_QUEUE), fake_cfg)
    _stats_runs(
        second,
        [
            ("lead", "s1", "sess-b1", 60_000, "Step committed.\nDONE"),
            ("lead", "s2", "sess-b2", 90_000, "Safe point.\nRETIRED"),
            ("lead", "s3", "sess-b3", 80_000, "Safe point.\nRETIRED"),
            ("lead", "s4", "sess-b4", 60_000, "Step committed.\nDONE"),
        ],
    )
    return first, second


def test_stats_prints_each_roles_line_over_every_queue_under_the_state_root(
    queue: Path,
    queue_file: Callable[[str], Path],
    fake_cfg: Config,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: `stats` reads one state directory only, sizes runs by ledger tokens, prints
    # roles unsorted, prints a skipped line with nothing skipped, or exits other than QUEUE_EMPTY.
    _two_queues(queue, queue_file, fake_cfg)
    assert _exit(["stats"]) == ExitCode.QUEUE_EMPTY
    assert capsys.readouterr().out.splitlines() == [
        "lead: 3 finished, peak context median 60000, p90 60000, max 60000; 2 overruns",
        "  lead overrun: s2 sess-b2 peak 90000 (retired)",
        "  lead overrun: s3 sess-b3 peak 80000 (retired)",
        "recut: 1 finished, peak context median 7000, p90 7000, max 7000; 0 overruns",
    ]


def _interleaved_runs(runs: list[tuple[State, str, str, str, int, str]]) -> None:
    """Log and ledger each `(state, kind, section, session, context, result)` run in the order
    given, each strictly later than the one before, numbering each state's logs from 1."""
    numbers: dict[Path, int] = {}
    for state, kind, section, session, context, result in runs:
        time.sleep(0.01)
        numbers[state.run_dir] = numbers.get(state.run_dir, 0) + 1
        _stats_log(state, numbers[state.run_dir], session, context, result)
        Ledger(state.ledger_path).append(kind, section, session, Spend(tokens=1, dollars=0.0))


def test_stats_prints_a_roles_newest_five_overruns_last_in_the_order_they_ran_across_queues(
    queue: Path,
    queue_file: Callable[[str], Path],
    fake_cfg: Config,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: `stats` joins whole state directories one after another, in either order,
    # instead of keeping runs in the order they ran across every queue, so a role's overruns
    # from two queues print out of order or the wrong five are shown.
    first = State.open(queue, fake_cfg)
    second = State.open(queue_file(SECOND_QUEUE), fake_cfg)
    _interleaved_runs(
        [
            (first, "lead", "s1", "sess-a1", 81_000, "Safe point.\nRETIRED"),
            (second, "lead", "s1", "sess-b1", 82_000, "Safe point.\nRETIRED"),
            (first, "lead", "s2", "sess-a2", 83_000, "Safe point.\nRETIRED"),
            (second, "lead", "s2", "sess-b2", 84_000, "Safe point.\nRETIRED"),
            (first, "lead", "s3", "sess-a3", 85_000, "Safe point.\nRETIRED"),
            (second, "lead", "s3", "sess-b3", 86_000, "Safe point.\nRETIRED"),
            (first, "lead", "s4", "sess-a4", 87_000, "Safe point.\nRETIRED"),
            (second, "lead", "s4", "sess-b4", 50_000, "Step committed.\nDONE"),
        ]
    )
    assert _exit(["stats"]) == ExitCode.QUEUE_EMPTY
    assert capsys.readouterr().out.splitlines() == [
        "lead: 1 finished, peak context median 50000, p90 50000, max 50000; 7 overruns",
        "  lead: 2 earlier overruns not shown",
        "  lead overrun: s2 sess-a2 peak 83000 (retired)",
        "  lead overrun: s2 sess-b2 peak 84000 (retired)",
        "  lead overrun: s3 sess-a3 peak 85000 (retired)",
        "  lead overrun: s3 sess-b3 peak 86000 (retired)",
        "  lead overrun: s4 sess-a4 peak 87000 (retired)",
    ]


def test_stats_ends_with_the_count_of_unreadable_run_logs(
    queue: Path,
    queue_file: Callable[[str], Path],
    fake_cfg: Config,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: an unreadable log stops `stats`, is not counted, or its line is not last.
    _, second = _two_queues(queue, queue_file, fake_cfg)
    _stats_log(second, 5, "sess-gone", 10_000, "Step committed.\nDONE")
    unreadable = second.run_dir / "5.jsonl"
    os.chmod(unreadable, 0)
    try:
        code = _exit(["stats"])
    finally:
        os.chmod(unreadable, 0o644)
    assert code == ExitCode.QUEUE_EMPTY
    out = capsys.readouterr().out.splitlines()
    assert out[-1] == "skipped 1 unreadable run logs"
    assert out[0] == "lead: 3 finished, peak context median 60000, p90 60000, max 60000; 2 overruns"


def test_stats_with_no_state_directory_says_so_and_exits_queue_empty(
    home: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: a missing state root raises, prints nothing, or exits other than QUEUE_EMPTY.
    assert not fake_cfg.state_root.exists()
    assert _exit(["stats"]) == ExitCode.QUEUE_EMPTY
    assert capsys.readouterr().out.splitlines() == [f"no runs under {fake_cfg.state_root}"]


def test_stats_with_an_empty_state_root_says_so_and_exits_queue_empty(
    home: Path, fake_cfg: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: a state root holding no state directory prints empty stats instead.
    fake_cfg.state_root.mkdir(parents=True)
    assert _exit(["stats"]) == ExitCode.QUEUE_EMPTY
    assert capsys.readouterr().out.splitlines() == [f"no runs under {fake_cfg.state_root}"]


def test_stats_takes_no_arguments(home: Path) -> None:
    # Breaks when: `stats` accepts a stray argument instead of exiting with usage.
    assert _exit(["stats", "extra"]) == ExitCode.USAGE


def test_stats_with_a_bad_config_file_exits_through_the_relay_error_handler(home: Path) -> None:
    # Breaks when: a config error from `stats` escapes `main` instead of becoming its exit code.
    (home / ".config" / "relay" / "config.toml").write_text("context_limit = [unclosed\n")
    assert _exit(["stats"]) == ExitCode.USAGE
