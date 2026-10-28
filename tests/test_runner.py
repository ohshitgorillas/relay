"""Red tests for Relay's child-process runner (design: Modules, `relay/runner.py`; Order 9).

Every child runs `fake_cfg.lead_command` (the fake `claude`) for its stream-json, wrapped
where a test needs it in a `/bin/sh -c` script that records PIDs or outlives the fake.
"""

from __future__ import annotations

import copy
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

import pytest

from relay.config import Config
from relay.runner import RunResult, run_agent

REPO = Path(__file__).resolve().parents[1]

LINES = [
    json.dumps({"type": "system", "subtype": "init", "session_id": "sess-r"}),
    json.dumps({"type": "assistant", "session_id": "sess-r", "message": {
        "id": "m1", "role": "assistant", "content": [{"type": "text", "text": "one"}],
        "usage": {"input_tokens": 10, "output_tokens": 5,
                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}}),
    json.dumps({"type": "assistant", "session_id": "sess-r", "message": {
        "id": "m2", "role": "assistant", "content": [{"type": "text", "text": "two"}],
        "usage": {"input_tokens": 20, "output_tokens": 5,
                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}}),
    json.dumps({"type": "assistant", "session_id": "sess-r", "message": {
        "id": "m3", "role": "assistant", "content": [{"type": "text", "text": "three"}],
        "usage": {"input_tokens": 30, "output_tokens": 5,
                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}}),
    json.dumps({"type": "result", "subtype": "success", "result": "DONE", "is_error": False,
                "total_cost_usd": 0.5, "session_id": "sess-r"}),
]

# Records the shell's PID in $1 and a 30-second grandchild's PID in $2, runs the fake ($3),
# then waits on the grandchild: a child that outlives its stream unless it is killed.
LONG = 'sleep 30 & echo $! > "$2"; echo $$ > "$1"; "$3"; wait'
# The same, ignoring SIGTERM, SIGINT and SIGHUP (the grandchild inherits the ignore).
STUBBORN = "trap '' TERM INT HUP; " + LONG


def _go(_state: object) -> str:
    return "go"


def _sh(script: str, *args: object) -> list[str]:
    return ["/bin/sh", "-c", script, "sh", *(str(a) for a in args)]


def _pid(path: Path) -> int:
    return int(path.read_text().strip())


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _gone_within(pid: int, seconds: float = 5.0) -> bool:
    """True once `pid` no longer exists; an orphan's zombie is reaped by launchd, so allow a moment."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return not _alive(pid)


def _cleanup(*paths: Path) -> None:
    """Kill, by recorded PID, any process a failing test left behind."""
    for path in paths:
        if path.exists():
            try:
                os.kill(_pid(path), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    path = tmp_path / "state" / "runs"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def fake(fake_cfg: Config, scenario: Callable[[list[str]], Path]) -> list[str]:
    """The fake `claude` argv, primed to emit LINES."""
    scenario(LINES)
    return list(fake_cfg.lead_command)


# Behavior 1: `relay/runner.py`: the one place a child process starts, streams, is killed
# and is reaped.


def test_run_agent_streams_every_line_verbatim_to_a_numbered_log_in_run_dir(
    fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    result = run_agent(fake, "You are a lead\n", tmp_path, run_dir, _go, tmp_path / "retire")
    assert isinstance(result, RunResult)
    assert result.log.parent == run_dir
    assert result.log.suffix == ".jsonl"
    assert result.log.stem.isdigit()
    assert result.log.read_text().splitlines() == LINES


def test_run_agent_gives_the_child_stdin_text_and_runs_it_in_cwd(
    fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    prompt = tmp_path / "prompt.txt"
    where = tmp_path / "pwd.txt"
    work = tmp_path / "work"
    work.mkdir()
    argv = _sh('pwd -P > "$2"; tee "$1" | "$3"', prompt, where, fake[0])
    stdin_text = "You are a lead\nqueue q.md\nsection s1\n"
    result = run_agent(argv, stdin_text, work, run_dir, _go, tmp_path / "retire")
    assert prompt.read_text() == stdin_text
    assert Path(where.read_text().strip()) == work.resolve()
    assert result.log.read_text().splitlines() == LINES


def test_run_agent_reports_the_exit_code_of_a_child_that_ends_on_its_own(
    fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    ok = run_agent(fake, "p\n", tmp_path, run_dir, _go, tmp_path / "retire")
    assert ok.exit_code == 0
    assert ok.killed is False
    bad = run_agent(_sh('"$1"; exit 3', fake[0]), "p\n", tmp_path, run_dir, _go, tmp_path / "retire")
    assert bad.exit_code == 3
    assert bad.killed is False
    assert bad.log != ok.log


def test_run_agent_reaps_the_child_before_it_returns(
    fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    pidfile = tmp_path / "pid"
    argv = _sh('echo $$ > "$1"; "$2"', pidfile, fake[0])
    run_agent(argv, "p\n", tmp_path, run_dir, _go, tmp_path / "retire")
    pid = _pid(pidfile)
    # A child left unreaped is a zombie: it would still answer signal 0.
    assert not _alive(pid)
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)


def test_on_event_is_given_the_stream_state_fed_up_to_each_line_and_the_result_carries_it(
    fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    seen: list[object] = []

    def on_event(state: object) -> str:
        seen.append(copy.deepcopy(state))
        return "go"

    result = run_agent(fake, "p\n", tmp_path, run_dir, on_event, tmp_path / "retire")
    # Every line of LINES changes the state (session, three context sizes, the result),
    # so a state fed line by line differs from one event to the next.
    assert len(seen) >= 2
    for before, after in zip(seen, seen[1:]):
        assert before != after
    assert result.stream == seen[-1]


def test_run_result_stream_is_fed_from_this_childs_lines(
    fake_cfg: Config, scenario: Callable[[list[str]], Path], tmp_path: Path, run_dir: Path
) -> None:
    fake = list(fake_cfg.lead_command)
    scenario(LINES)
    first = run_agent(fake, "p\n", tmp_path, run_dir, _go, tmp_path / "retire")
    again = run_agent(fake, "p\n", tmp_path, run_dir, _go, tmp_path / "retire")
    scenario([line.replace("sess-r", "sess-other") for line in LINES])
    other = run_agent(fake, "p\n", tmp_path, run_dir, _go, tmp_path / "retire")
    assert first.stream == again.stream
    # Only the session id differs, so a stream that was never fed would match here.
    assert other.stream != first.stream


def test_run_agent_records_the_child_pid_in_a_pid_file_named_like_its_log(
    fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    pidfile = tmp_path / "pid"
    argv = _sh('echo $$ > "$1"; "$2"', pidfile, fake[0])
    records: list[tuple[str, str]] = []

    def on_event(_state: object) -> str:
        records.extend((p.stem, p.read_text().strip()) for p in sorted(run_dir.glob("*.pid")))
        return "go"

    result = run_agent(argv, "p\n", tmp_path, run_dir, on_event, tmp_path / "retire")
    child = str(_pid(pidfile))
    assert records
    assert set(records) == {(result.log.stem, child)}


# Behavior 2: Each child runs in its own process group (`start_new_session=True`).


def test_run_agent_starts_the_child_in_a_new_session_and_process_group(
    fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    ids = tmp_path / "ids"
    pidfile = tmp_path / "pid"
    probe = "import os; print(os.getpgrp(), os.getsid(0))"
    argv = _sh('"$1" -c "$2" > "$3"; echo $$ > "$4"; "$5"',
               sys.executable, probe, ids, pidfile, fake[0])
    run_agent(argv, "p\n", tmp_path, run_dir, _go, tmp_path / "retire")
    pid = _pid(pidfile)
    pgrp, sid = (int(word) for word in ids.read_text().split())
    assert pgrp == pid
    assert sid == pid
    assert pgrp != os.getpgrp()
    assert sid != os.getsid(0)


# Behavior 3: It kills by process group, then checks with `os.waitpid` and
# `os.kill(pid, 0)` that the child is gone.


@pytest.mark.parametrize("script", [LONG, STUBBORN], ids=["plain", "ignores-sigterm"])
def test_kill_takes_the_whole_process_group_and_the_child_is_gone_on_return(
    script: str, fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    pidfile = tmp_path / "pid"
    grandfile = tmp_path / "grandchild"
    argv = _sh(script, pidfile, grandfile, fake[0])
    try:
        result = run_agent(argv, "p\n", tmp_path, run_dir, lambda _s: "kill", tmp_path / "retire")
        assert result.killed is True
        assert result.exit_code is None
        child = _pid(pidfile)
        # Reaped and gone the moment run_agent returns: no zombie answers signal 0.
        assert not _alive(child)
        with pytest.raises(ChildProcessError):
            os.waitpid(child, os.WNOHANG)
        # The grandchild shares the child's group, so the group kill takes it too.
        assert _gone_within(_pid(grandfile))
    finally:
        _cleanup(grandfile, pidfile)


# Behavior 4: It also installs SIGINT and SIGTERM handlers that kill the live child group
# before Relay exits.

DRIVER = """
import json, sys
from pathlib import Path
from relay.runner import run_agent

a = json.loads(sys.argv[1])
marker = Path(a["marker"])

def on_event(state):
    marker.touch()
    return "go"

run_agent(a["argv"], "p\\n", Path(a["cwd"]), Path(a["run_dir"]), on_event, Path(a["retire"]))
"""


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM], ids=["SIGINT", "SIGTERM"])
def test_a_signal_to_relay_kills_the_live_child_group_before_relay_exits(
    signum: int, fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    pidfile = tmp_path / "pid"
    grandfile = tmp_path / "grandchild"
    marker = tmp_path / "streaming"
    args = {
        "argv": _sh(LONG, pidfile, grandfile, fake[0]),
        "cwd": str(tmp_path),
        "run_dir": str(run_dir),
        "retire": str(tmp_path / "retire"),
        "marker": str(marker),
    }
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(REPO), env.get("PYTHONPATH", "")) if p)
    with open(tmp_path / "driver.out", "wb") as out:
        driver = subprocess.Popen(
            [sys.executable, "-c", DRIVER, json.dumps(args)],
            cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
        )
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and driver.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists(), "Relay never streamed an event from the child"
        child = _pid(pidfile)
        grandchild = _pid(grandfile)
        assert _alive(grandchild)
        driver.send_signal(signum)
        driver.wait(timeout=15)
        assert _gone_within(child)
        assert _gone_within(grandchild)
    finally:
        if driver.poll() is None:
            driver.kill()
            driver.wait()
        _cleanup(grandfile, pidfile)


# Behavior 5: on_event returning "retire" creates retire_flag once; "kill" kills the group.


def test_retire_creates_retire_flag_and_lets_the_child_finish(
    fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    flag = tmp_path / "retire"
    result = run_agent(fake, "p\n", tmp_path, run_dir, lambda _s: "retire", flag)
    assert flag.exists()
    assert result.killed is False
    assert result.exit_code == 0
    assert result.log.read_text().splitlines() == LINES


def test_go_neither_creates_retire_flag_nor_kills(
    fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    flag = tmp_path / "retire"
    seen: list[bool] = []

    def on_event(_state: object) -> str:
        seen.append(flag.exists())
        return "go"

    result = run_agent(fake, "p\n", tmp_path, run_dir, on_event, flag)
    assert seen
    assert not any(seen)
    assert not flag.exists()
    assert result.killed is False
    assert result.exit_code == 0
    assert result.log.read_text().splitlines() == LINES


def test_retire_creates_retire_flag_only_once_per_run(
    fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    flag = tmp_path / "retire"
    seen: list[bool] = []

    def on_event(_state: object) -> str:
        seen.append(flag.exists())
        if len(seen) == 2 and flag.exists():
            flag.unlink()
        return "retire"

    run_agent(fake, "p\n", tmp_path, run_dir, on_event, flag)
    assert len(seen) >= 3
    assert seen[0] is False
    assert seen[1] is True
    # Removed after it was created once, it is never created again, though "retire" kept coming.
    assert seen[2:] == [False] * (len(seen) - 2)
    assert not flag.exists()


def test_kill_ends_a_long_child_at_once_and_reports_it_killed(
    fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    pidfile = tmp_path / "pid"
    grandfile = tmp_path / "grandchild"
    calls: list[int] = []

    def on_event(_state: object) -> str:
        calls.append(1)
        return "kill"

    start = time.monotonic()
    try:
        result = run_agent(_sh(LONG, pidfile, grandfile, fake[0]), "p\n", tmp_path, run_dir,
                           on_event, tmp_path / "retire")
        assert time.monotonic() - start < 20
        assert result.killed is True
        assert result.exit_code is None
        assert len(calls) >= 1
        assert not (tmp_path / "retire").exists()
    finally:
        _cleanup(grandfile, pidfile)


# Behavior 6: the child's stderr never reaches Relay's own stderr, and is kept in a
# `<n>.stderr` file beside the run's `<n>.jsonl` stream log.

# Writes the bytes of the hex string $2 to stderr with the Python at $1, then runs the fake ($3).
NOISY = '"$1" -c "import sys; sys.stderr.buffer.write(bytes.fromhex(sys.argv[1]))" "$2"; "$3"'

# Reads its prompt, then writes each scenario line to stdout, each followed on stderr by
# argv[1] and a newline: stderr interleaved with the stream.
INTERLEAVED = """
import os, sys
sys.stdin.read()
for line in open(os.environ["RELAY_FAKE_SCENARIO"]).read().splitlines():
    sys.stdout.write(line + "\\n")
    sys.stdout.flush()
    sys.stderr.write(sys.argv[1] + "\\n")
    sys.stderr.flush()
"""

# Writes argv[1] bytes of stderr in 64 KiB chunks; SIGALRM ends a writer still blocked after
# 20 seconds, so a capture that never drains fails the run instead of hanging the test.
FLOOD = """
import signal, sys
signal.alarm(20)
left = int(sys.argv[1])
while left:
    n = min(left, 65536)
    sys.stderr.buffer.write(b"e" * n)
    sys.stderr.buffer.flush()
    left -= n
"""
FLOOD_BYTES = 4 * 1024 * 1024


def _stderr_file(result: RunResult) -> Path:
    return result.log.with_name(result.log.stem + ".stderr")


def test_nothing_the_child_writes_to_stderr_reaches_relays_stderr(
    fake: list[str], tmp_path: Path, run_dir: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    marker = "child-stderr-marker-7f3a"
    argv = _sh(NOISY, sys.executable, (marker + "\n").encode().hex(), fake[0])
    capfd.readouterr()
    result = run_agent(argv, "p\n", tmp_path, run_dir, _go, tmp_path / "retire")
    captured = capfd.readouterr()
    assert result.exit_code == 0
    assert marker not in captured.err
    assert marker not in captured.out


def test_every_byte_of_the_childs_stderr_is_kept_in_a_stderr_file_named_like_its_log(
    fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    first_bytes = b"warn: one\n\xff\x00 not utf-8\r\nlast line, no newline"
    second_bytes = b"second child only\n"
    first = run_agent(_sh(NOISY, sys.executable, first_bytes.hex(), fake[0]), "p\n",
                      tmp_path, run_dir, _go, tmp_path / "retire")
    second = run_agent(_sh(NOISY, sys.executable, second_bytes.hex(), fake[0]), "p\n",
                       tmp_path, run_dir, _go, tmp_path / "retire")
    assert first.log != second.log
    for result, written in ((first, first_bytes), (second, second_bytes)):
        kept = run_dir / f"{result.log.stem}.stderr"
        assert kept.parent == result.log.parent
        assert kept.is_file()
        assert kept.read_bytes() == written


@pytest.mark.parametrize("order", ["before-stream", "after-stream"])
def test_a_child_flooding_its_stderr_runs_to_completion_with_its_stream_unchanged(
    order: str, fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    clean = run_agent(fake, "p\n", tmp_path, run_dir, _go, tmp_path / "retire")
    if order == "before-stream":
        script = '"$1" -c "$2" "$3" || exit 9; "$4"'
    else:
        script = '"$4" || exit 8; "$1" -c "$2" "$3" || exit 9'
    argv = _sh(script, sys.executable, FLOOD, FLOOD_BYTES, fake[0])
    start = time.monotonic()
    result = run_agent(argv, "p\n", tmp_path, run_dir, _go, tmp_path / "retire")
    assert time.monotonic() - start < 20
    assert result.exit_code == 0
    assert result.killed is False
    assert result.log.read_text().splitlines() == LINES
    assert result.stream == clean.stream
    assert _stderr_file(result).is_file()
    assert _stderr_file(result).read_bytes() == b"e" * FLOOD_BYTES


def test_stream_log_stdout_and_stream_state_are_unchanged_when_the_child_also_writes_stderr(
    fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    clean = run_agent(fake, "p\n", tmp_path, run_dir, _go, tmp_path / "retire")
    # Stream-json on stderr: a stderr line fed to the stream or logged would change both.
    noise = json.dumps({"type": "system", "subtype": "init", "session_id": "sess-stderr"})
    seen: list[object] = []

    def on_event(state: object) -> str:
        seen.append(copy.deepcopy(state))
        return "go"

    result = run_agent([sys.executable, "-c", INTERLEAVED, noise], "p\n", tmp_path, run_dir,
                       on_event, tmp_path / "retire")
    assert result.exit_code == 0
    assert result.killed is False
    assert result.log.read_text().splitlines() == LINES
    assert result.stream == clean.stream
    assert seen
    assert seen[-1] == clean.stream
    assert _stderr_file(result).is_file()
    assert _stderr_file(result).read_text().splitlines() == [noise] * len(LINES)
