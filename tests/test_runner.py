"""Red tests for Relay's child-process runner (design: Modules, `relay/runner.py`; Order 9).

Every child runs `fake_cfg.lead_command` (the fake `claude`) for its stream-json, wrapped
where a test needs it in a `/bin/sh -c` script that records PIDs or outlives the fake.
"""

from __future__ import annotations

import copy
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import pytest

from relay.config import Config
from relay.runner import CommandResult, RunResult, capture, run_agent, run_command
from relay.backends.base import Capabilities, Launch
from relay.backends.claude import ClaudeBackend
from relay.stream import StreamState
from relay.ledger import Spend
from dataclasses import replace
from relay.backends import replay
import relay.files as publication
import relay.runner as runner_module
from relay.errors import ExitCode

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("policy", ["default", True, False], ids=["default", "required", "optional"])
@pytest.mark.parametrize(
    ("exit_code", "killed", "backend_error", "tokens"),
    [(0, False, False, 0), (0, False, False, 17),
     (0, True, False, 0), (0, True, False, 17),
     (1, False, False, 0), (1, False, False, 17),
     (None, False, False, 17), (-15, False, False, 17),
     (0, False, True, 0), (0, False, True, 17)],
)
def test_shared_failure_predicate_preserves_explicit_token_policy(
    policy: str | bool, exit_code: int | None, killed: bool,
    backend_error: bool, tokens: int, tmp_path: Path,
) -> None:
    # Breaks when token policy changes other failures, or the default accepts zero tokens.
    stream = StreamState(None, 0, Spend(tokens, 0.0), "DONE", backend_error)
    result = RunResult(exit_code, killed, stream, tmp_path / "run.jsonl")
    options = {} if policy == "default" else {"require_tokens": policy}
    failed = runner_module.run_failed(result, **options)
    expected = killed or exit_code != 0 or backend_error or (tokens == 0 and policy is not False)
    assert failed is expected


def test_runner_telemetry_uses_shared_publication_and_replays_final_snapshot(
    fake_cfg: Config, tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when runner bypasses shared publication or replay ignores the finalized snapshot.
    calls = []
    original = publication.atomic_write

    def publish(path, data, *, mode=None):
        calls.append((path, data))
        json.loads(data)
        path.write_bytes(data)

    for name, value in list(vars(runner_module).items()):
        if value is original:
            monkeypatch.setattr(runner_module, name, publish)
    monkeypatch.setattr(publication, "atomic_write", publish)
    command = [sys.executable, "-c", "print('wire answer')"]
    backend = PollingBackend(command)
    result = run_agent(command, "", tmp_path, run_dir, _go, tmp_path / "retire",
                       backend=backend, cfg=replace(fake_cfg, backend="generic"))
    assert calls, "runner bypassed shared atomic publication"
    snapshots = [(path, data) for path, data in calls if b"final answer" in data]
    assert snapshots
    assert all(path.parent == run_dir for path, _ in snapshots)
    assert replay(result.log) == result.stream

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
    seen: list[StreamState] = []

    def on_event(state: StreamState) -> str:
        seen.append(copy.deepcopy(state))
        return "go"

    result = run_agent(fake, "p\n", tmp_path, run_dir, on_event, tmp_path / "retire")
    # Design callback contract: quiet polls may repeat the last snapshot.
    # Each line still changes state (session, three context sizes, the result),
    # so callbacks must expose the transitions even with duplicates between them.
    assert len(seen) >= 2
    assert sum(before != after for before, after in zip(seen, seen[1:])) >= len(LINES) - 1
    assert result.stream == seen[-1]
    # Breaks when a parsed observation is omitted or delivered out of order,
    # including when an initial quiet callback masks the missing transition.
    observations: list[tuple[str | None, int, str | None]] = []
    for state in seen:
        observation = (state.session_id, state.context_tokens, state.result_text)
        if not observations or observation != observations[-1]:
            observations.append(observation)
    if observations[0] == (None, 0, None):
        observations = observations[1:]
    assert observations == [
        ("sess-r", 0, None),
        ("sess-r", 10, None),
        ("sess-r", 20, None),
        ("sess-r", 30, None),
        ("sess-r", 30, "DONE"),
    ]


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


class PollingBackend:
    capabilities = Capabilities(True, True, False, False)

    def __init__(self, command: list[str]) -> None:
        self.command = command
        self.outputs: list[Path] = []
        self.finished = False

    def argv(self, role: str, cfg: Config, cwd: Path, output: Path) -> list[str]:
        self.outputs.append(output)
        return self.command

    def parse(self, state: StreamState, line: str) -> StreamState:
        return replace(state, result_text="stream answer")

    def poll(self, state: StreamState) -> StreamState:
        return replace(state, context_tokens=321, spend=Spend(654, 0.0))

    def finish(self, state: StreamState, output: Path) -> StreamState:
        self.finished = True
        return replace(self.poll(state), result_text="final answer")

    def resume_hint(self, session_id: str) -> str:
        return f"previous thread {session_id}"

    def launch(self, role: str, retire_flag: Path, run_dir: Path) -> Launch:
        return Launch()


def test_backend_poll_reaches_callback_while_stdout_is_quiet(
    fake_cfg: Config, tmp_path: Path, run_dir: Path
) -> None:
    # Breaks when quiet stdout prevents backend polling or callback-driven killing.
    pidfile = tmp_path / "quiet-pid"
    completed = tmp_path / "quiet-completed"
    command = [
        sys.executable, "-c",
        "import os, sys, time; from pathlib import Path; "
        "Path(sys.argv[1]).write_text(str(os.getpid())); "
        "time.sleep(2); Path(sys.argv[2]).touch()",
        str(pidfile), str(completed),
    ]

    class DelayedPollingBackend(PollingBackend):
        polls = 0

        def poll(self, state: StreamState) -> StreamState:
            self.polls += 1
            if self.polls == 1 or not pidfile.exists():
                return state
            return super().poll(state)

    backend = DelayedPollingBackend(command)
    seen: list[int] = []

    def watch(state: StreamState) -> str:
        seen.append(state.context_tokens)
        return "kill" if state.context_tokens == 321 else "go"

    try:
        result = run_agent(command, "handoff", tmp_path, run_dir, watch,
                           tmp_path / "retire", backend=backend, cfg=fake_cfg)
    finally:
        _cleanup(pidfile)
    assert pidfile.exists()
    assert _gone_within(_pid(pidfile))
    assert not completed.exists()
    assert seen[0] != 321
    assert 321 in seen
    assert result.killed is True
    assert backend.finished is True
    assert result.stream.context_tokens == 321


def test_backend_finish_and_unique_output_are_used_for_every_run(
    fake_cfg: Config, tmp_path: Path, run_dir: Path
) -> None:
    # Breaks when finish is skipped, its state is discarded, outputs are reused,
    # or finish receives another run's output.
    command = [sys.executable, "-c", "print('wire answer')"]
    finished_texts: list[str] = []

    class OutputReadingBackend(PollingBackend):
        def argv(self, role: str, cfg: Config, cwd: Path, output: Path) -> list[str]:
            command = super().argv(role, cfg, cwd, output)
            output.write_text(f"output for run {len(self.outputs)}")
            return command

        def finish(self, state: StreamState, output: Path) -> StreamState:
            finished_texts.append(output.read_text())
            return super().finish(state, output)

    backend = OutputReadingBackend(command)
    results = [run_agent(command, "handoff", tmp_path, run_dir, _go,
                         tmp_path / "retire", backend=backend, cfg=fake_cfg)
               for _ in range(2)]
    assert len(backend.outputs) == 2
    assert backend.outputs[0] != backend.outputs[1]
    assert all(path.parent == run_dir for path in backend.outputs)
    assert all(result.stream.result_text == "final answer" for result in results)
    assert all(result.stream.spend == Spend(654, 0.0) for result in results)
    assert finished_texts == ["output for run 1", "output for run 2"]


# relay-run-overhead-design.md, Modules `relay/backends/base.py` and Homes: one launch
# description per backend child, `Backend.launch`, applied once in `runner.run_agent`.
# The child is the fake `claude`, which records its argv and env in `RELAY_FAKE_LAUNCH`.


class LaunchingBackend(PollingBackend):
    """A backend whose every child gets `described`, recording each `launch` call."""

    def __init__(self, command: list[str], described: Launch) -> None:
        super().__init__(command)
        self.described = described
        self.launches: list[tuple[str, Path, Path]] = []

    def launch(self, role: str, retire_flag: Path, run_dir: Path) -> Launch:
        self.launches.append((role, retire_flag, run_dir))
        return self.described


def _launched(path: Path) -> list[dict[str, Any]]:
    """Each run the fake `claude` recorded: its argv and env."""
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_run_agent_gives_the_child_the_launch_env_merged_over_relays_environment(
    fake: list[str], fake_cfg: Config, tmp_path: Path, run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when run_agent ignores Launch.env, replaces os.environ with it instead of
    # merging over it, or sets it in Relay's own environment.
    record = tmp_path / "launch.jsonl"
    monkeypatch.setenv("RELAY_FAKE_LAUNCH", str(record))
    monkeypatch.setenv("RELAY_LAUNCH_INHERITED", "from relay 3a9f")
    monkeypatch.setenv("RELAY_LAUNCH_OVERRIDDEN", "from relay")
    monkeypatch.delenv("RELAY_LAUNCH_ADDED", raising=False)
    described = Launch(env={"RELAY_LAUNCH_OVERRIDDEN": "from launch",
                            "RELAY_LAUNCH_ADDED": "added 51c0"})
    backend = LaunchingBackend(fake, described)
    run_agent(fake, "p\n", tmp_path, run_dir, _go, tmp_path / "retire",
              backend=backend, cfg=fake_cfg)
    [seen] = _launched(record)
    assert seen["env"].get("RELAY_LAUNCH_ADDED") == "added 51c0"
    assert seen["env"].get("RELAY_LAUNCH_OVERRIDDEN") == "from launch"
    assert seen["env"].get("RELAY_LAUNCH_INHERITED") == "from relay 3a9f"
    assert seen["env"].get("PATH") == os.environ["PATH"]
    assert os.environ["RELAY_LAUNCH_OVERRIDDEN"] == "from relay"
    assert "RELAY_LAUNCH_ADDED" not in os.environ


def test_run_agent_adds_the_launch_extra_argv_to_the_childs_argv(
    fake: list[str], fake_cfg: Config, tmp_path: Path, run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when run_agent drops Launch.extra_argv, splits it, or reorders it.
    record = tmp_path / "launch.jsonl"
    monkeypatch.setenv("RELAY_FAKE_LAUNCH", str(record))
    extra = ("--launch-flag", "value 8e2d", "--second")
    backend = LaunchingBackend(fake, Launch(extra_argv=extra))
    run_agent(fake, "p\n", tmp_path, run_dir, _go, tmp_path / "retire",
              backend=backend, cfg=fake_cfg)
    [seen] = _launched(record)
    argv = seen["argv"]
    runs = [tuple(argv[i:i + len(extra)]) for i in range(len(argv) - len(extra) + 1)]
    assert extra in runs


@pytest.mark.parametrize("role", ["lead", "recut"])
def test_run_agent_asks_the_backend_for_one_launch_per_child(
    role: str, fake: list[str], fake_cfg: Config, tmp_path: Path, run_dir: Path,
) -> None:
    # Breaks when run_agent skips Backend.launch, calls it more than once for a child, or
    # passes it another role, retire flag or run directory.
    retire = tmp_path / "retire"
    backend = LaunchingBackend(fake, Launch())
    run_agent(fake, "p\n", tmp_path, run_dir, _go, retire,
              backend=backend, cfg=fake_cfg, role=role)
    assert backend.launches == [(role, retire, run_dir)]
    run_agent(fake, "p\n", tmp_path, run_dir, _go, retire,
              backend=backend, cfg=fake_cfg, role=role)
    assert backend.launches == [(role, retire, run_dir), (role, retire, run_dir)]


@pytest.mark.parametrize("role", ["lead", "recut"])
def test_a_claude_child_runs_with_the_print_background_wait_ceiling_off(
    role: str, fake: list[str], fake_cfg: Config, tmp_path: Path, run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when the Claude child of any role starts without CHILD_ENV, so the CLI stops a
    # print-mode session's background agents 10 minutes after its last turn.
    record = tmp_path / "launch.jsonl"
    monkeypatch.setenv("RELAY_FAKE_LAUNCH", str(record))
    monkeypatch.delenv("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", raising=False)
    run_agent(fake, "p\n", tmp_path, run_dir, _go, tmp_path / "retire",
              backend=ClaudeBackend(), cfg=fake_cfg, role=role)
    [seen] = _launched(record)
    assert seen["env"].get("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS") == "0"
    assert "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS" not in os.environ


def test_replay_restores_runner_telemetry_beside_legacy_claude_logs(
    fake_cfg: Config, tmp_path: Path, run_dir: Path,
) -> None:
    # Breaks when runner telemetry is lost or metadata-free Claude logs stop replaying.
    command = [sys.executable, "-c", "print('wire answer')"]
    backend = PollingBackend(command)
    cfg = replace(fake_cfg, backend="generic")
    result = run_agent(command, "handoff", tmp_path, run_dir, _go,
                       tmp_path / "retire", backend=backend, cfg=cfg)

    restored = replay(result.log)
    assert restored.context_tokens == 321
    assert restored.spend == Spend(654, 0.0)
    assert restored.result_text == "final answer"
    legacy = run_dir / "legacy.jsonl"
    legacy.write_text("\n".join(LINES) + "\n")
    historical = replay(legacy)
    assert historical.session_id == "sess-r"
    assert historical.result_text == "DONE"


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


def test_direct_exit_cleans_inherited_stdout_and_drains_buffered_output(
    tmp_path: Path, run_dir: Path,
) -> None:
    # Breaks when inherited stdout postpones cleanup until descendant EOF.
    pidfile = tmp_path / "direct-pid"
    grandfile = tmp_path / "inherited-pid"
    expired = tmp_path / "descendant-expired"
    wire = "\n".join(LINES[:-1] + [LINES[-1].replace("DONE", "DONE λ")])
    script = """
import os, signal, sys, time
from pathlib import Path
signal.alarm(8)
Path(sys.argv[1]).write_text(str(os.getpid()))
pid = os.fork()
if pid == 0:
    signal.alarm(8)
    time.sleep(4)
    Path(sys.argv[3]).touch()
    os._exit(0)
Path(sys.argv[2]).write_text(str(pid))
sys.stdout.buffer.write(sys.argv[4].encode())
sys.stdout.buffer.flush()
os._exit(7)
"""
    try:
        result = run_agent(
            [sys.executable, "-c", script, str(pidfile), str(grandfile), str(expired), wire],
            "", tmp_path, run_dir, _go, tmp_path / "retire",
        )
        assert not expired.exists(), "descendant-held stdout delayed cleanup until natural exit"
        assert result.exit_code == 7
        assert result.killed is False
        assert result.log.read_text().splitlines() == wire.splitlines()
        assert result.stream.result_text == "DONE λ"
        assert _gone_within(_pid(grandfile))
    finally:
        _cleanup(grandfile, pidfile)
        for path in (pidfile, grandfile):
            if path.exists():
                pid = _pid(path)
                assert _gone_within(pid)
                proof = subprocess.run(["ps", "-p", str(pid)], capture_output=True, text=True)
                assert proof.returncode == 1, proof.stdout


@pytest.mark.parametrize("interrupt", [False, True], ids=["concurrent-reader", "interrupted-writer"])
def test_telemetry_publication_preserves_complete_snapshots(
    interrupt: bool, fake_cfg: Config, tmp_path: Path, run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when telemetry truncates the published inode or exposes partial writes.
    first = "published-first-observation"
    second = "published-second-observation"
    published: list[Path] = []
    preceding: list[bytes] = []
    observed: list[bytes] = []
    temporary: list[Path] = []
    readers: list[object] = []
    pidfile = tmp_path / "snapshot-pid"
    command = [sys.executable, "-c",
               "import os,time; from pathlib import Path; "
               "Path('snapshot-pid').write_text(str(os.getpid())); time.sleep(0.7)"]

    class SnapshotBackend(PollingBackend):
        def poll(self, state: StreamState) -> StreamState:
            if not published:
                for path in run_dir.iterdir():
                    if path.is_file() and first.encode() in path.read_bytes():
                        published.append(path)
                        preceding.append(path.read_bytes())
                        readers.append(path.open("rb"))
                        break
            return replace(state, result_text=second if published else first)

        def finish(self, state: StreamState, output: Path) -> StreamState:
            return self.poll(state)

    def observe_publication(original: Callable[..., object]) -> Callable[..., object]:
        def publish(source: object, destination: object, *args: object, **kwargs: object) -> object:
            if published and not observed and Path(destination) == published[0]:
                candidate = Path(source)
                assert candidate != published[0]
                assert candidate.parent == published[0].parent
                contents = candidate.read_text()
                json.loads(contents)
                assert second in contents
                temporary.append(candidate)
                observed.append(published[0].read_bytes())
                if interrupt:
                    raise OSError("snapshot-write-interrupted")
            return original(source, destination, *args, **kwargs)
        return publish

    monkeypatch.setattr(os, "replace", observe_publication(os.replace))
    monkeypatch.setattr(os, "rename", observe_publication(os.rename))
    failure = None
    try:
        try:
            run_agent(command, "", tmp_path, run_dir, _go, tmp_path / "retire",
                      backend=SnapshotBackend(command), cfg=fake_cfg)
        except OSError as exc:
            failure = exc
        assert published, "no first telemetry snapshot was published"
        assert observed, "no second telemetry snapshot was written"
        assert all(value == preceding[0] for value in observed)
        readers[0].seek(0)
        assert readers[0].read() == preceding[0]
        if interrupt:
            assert str(failure) == "snapshot-write-interrupted"
            assert published[0].read_bytes() == preceding[0]
            assert all(not path.exists() for path in temporary)
        else:
            assert failure is None
            assert second in published[0].read_text()
            json.loads(published[0].read_text())
    finally:
        for reader in readers:
            reader.close()
        _cleanup(pidfile)
        if pidfile.exists():
            pid = _pid(pidfile)
            assert _gone_within(pid)
            proof = subprocess.run(["ps", "-p", str(pid)], capture_output=True, text=True)
            assert proof.returncode == 1, proof.stdout
# ---------------------------------------------------------------------------------------
# `run_command` and `capture` (design relay-check-design.md: Modules, `relay/runner.py`; Order 3).


def _q(value: object) -> str:
    return shlex.quote(str(value))


def _log(tmp_path: Path, text: str = "earlier line\n") -> Path:
    """A check log that already holds `text`, so appending can be told from overwriting."""
    log = tmp_path / "check.log"
    log.write_text(text)
    return log


# Behavior 1 (relay-check): Run `/bin/sh -c command` in its own session in `cwd`, stdout and
# stderr both appended to `log`.


def test_run_command_runs_command_as_a_shell_script_and_reports_its_exit_code(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    ok = run_command("x=one; echo \"$x\" | tr o O", tmp_path, log, 30)
    assert isinstance(ok, CommandResult)
    assert ok.exit_code == 0
    assert ok.timed_out is False
    bad = run_command("true && exit 3", tmp_path, log, 30)
    assert bad.exit_code == 3
    assert bad.timed_out is False
    assert log.read_text() == "earlier line\nOne\n"


def test_run_command_runs_the_shell_in_cwd(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    log = _log(tmp_path)
    run_command("pwd -P", work, log, 30)
    assert log.read_text() == f"earlier line\n{work.resolve()}\n"


def test_run_command_starts_the_shell_in_its_own_session_and_group(tmp_path: Path) -> None:
    log = _log(tmp_path, "")
    # The shell records its own PID: a lone simple command may be exec'd in place of the
    # shell, so the probe's parent need not be the shell.
    probe = "import os; print(os.getpgrp(), os.getsid(0))"
    run_command(f"echo $$; {_q(sys.executable)} -c {_q(probe)}", tmp_path, log, 30)
    shell, pgrp, sid = (int(word) for word in log.read_text().split())
    assert pgrp == shell
    assert sid == shell
    assert pgrp != os.getpgrp()
    assert sid != os.getsid(0)


def test_run_command_appends_stdout_and_stderr_to_log_in_order_and_prints_neither(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    log = _log(tmp_path)
    capfd.readouterr()
    run_command("echo out-1; echo err-1 >&2; echo out-2; echo err-2 >&2", tmp_path, log, 30)
    run_command("echo again", tmp_path, log, 30)
    captured = capfd.readouterr()
    assert log.read_text() == "earlier line\nout-1\nerr-1\nout-2\nerr-2\nagain\n"
    for word in ("out-1", "err-1", "again"):
        assert word not in captured.out
        assert word not in captured.err


# Behavior 2 (relay-check): `log`, stdin from /dev/null, with no env= so the child inherits
# the environment `relay go` started with.


def test_run_command_gives_the_child_dev_null_as_stdin(tmp_path: Path) -> None:
    log = _log(tmp_path, "")
    probe = (
        "import os, stat; a = os.fstat(0); b = os.stat('/dev/null'); "
        "print(stat.S_ISCHR(a.st_mode) and a.st_rdev == b.st_rdev)"
    )
    result = run_command(f"{_q(sys.executable)} -c {_q(probe)}; cat; echo read-all", tmp_path,
                         log, 30)
    assert result.exit_code == 0
    assert result.timed_out is False
    assert log.read_text() == "True\nread-all\n"


def test_run_command_child_inherits_relays_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RELAY_CHECK_MARK", "inherited value 7c1e")
    log = _log(tmp_path, "")
    probe = "import json, os; print(json.dumps(dict(os.environ)))"
    run_command(f"{_q(sys.executable)} -c {_q(probe)}", tmp_path, log, 30)
    seen = json.loads(log.read_text())
    assert seen["RELAY_CHECK_MARK"] == "inherited value 7c1e"
    assert seen["PATH"] == os.environ["PATH"]
    assert seen["HOME"] == os.environ["HOME"]
    for name, value in os.environ.items():
        if name not in {"PWD", "OLDPWD", "SHLVL", "_"}:
            assert seen.get(name) == value, name


# Behavior 3 (relay-check): At `timeout` seconds kill the group with _kill_and_reap. Signal
# handlers as in run_agent: SIGINT/SIGTERM kill the group first.

# Records the shell's PID in $1 and a 30-second grandchild's PID in $2, then waits on it.
SLOW = 'sleep 30 & echo $! > {grand}; echo $$ > {pid}; wait'
SLOW_STUBBORN = "trap '' TERM INT HUP; " + SLOW


@pytest.mark.parametrize("script", [SLOW, SLOW_STUBBORN], ids=["plain", "ignores-sigterm"])
def test_run_command_kills_and_reaps_the_whole_group_at_timeout(
    script: str, tmp_path: Path
) -> None:
    pidfile = tmp_path / "pid"
    grandfile = tmp_path / "grandchild"
    log = _log(tmp_path)
    start = time.monotonic()
    try:
        result = run_command(script.format(grand=_q(grandfile), pid=_q(pidfile)), tmp_path, log,
                             1.0)
        took = time.monotonic() - start
        assert result.timed_out is True
        assert result.exit_code is None
        assert 1.0 <= took < 20
        shell = _pid(pidfile)
        assert not _alive(shell)
        with pytest.raises(ChildProcessError):
            os.waitpid(shell, os.WNOHANG)
        assert _gone_within(_pid(grandfile))
    finally:
        _cleanup(grandfile, pidfile)


def test_run_command_that_ends_before_timeout_is_not_timed_out(tmp_path: Path) -> None:
    log = _log(tmp_path)
    result = run_command("sleep 0.2; echo finished; exit 5", tmp_path, log, 20)
    assert result.timed_out is False
    assert result.exit_code == 5
    assert log.read_text() == "earlier line\nfinished\n"


COMMAND_DRIVER = """
import json, sys
from pathlib import Path
from relay.runner import run_command

a = json.loads(sys.argv[1])
run_command(a["command"], Path(a["cwd"]), Path(a["log"]), 120)
"""


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM], ids=["SIGINT", "SIGTERM"])
def test_a_signal_to_relay_kills_the_running_command_group(signum: int, tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    grandfile = tmp_path / "grandchild"
    marker = tmp_path / "running"
    command = SLOW.format(grand=_q(grandfile), pid=_q(pidfile)).replace(
        "; wait", f"; touch {_q(marker)}; wait"
    )
    args = {"command": command, "cwd": str(tmp_path), "log": str(_log(tmp_path))}
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(REPO), env.get("PYTHONPATH", "")) if p)
    with open(tmp_path / "driver.out", "wb") as out:
        driver = subprocess.Popen(
            [sys.executable, "-c", COMMAND_DRIVER, json.dumps(args)],
            cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
        )
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and driver.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists(), "the command never started"
        shell = _pid(pidfile)
        grandchild = _pid(grandfile)
        assert _alive(grandchild)
        driver.send_signal(signum)
        driver.wait(timeout=15)
        assert _gone_within(shell)
        assert _gone_within(grandchild)
    finally:
        if driver.poll() is None:
            driver.kill()
            driver.wait()
        _cleanup(grandfile, pidfile)


# Behavior 4 (relay-check): Run argv in `cwd`, return (exit code, stdout); (None, "") on OSError
# or timeout, the group killed and reaped.


def test_capture_returns_the_exit_code_and_stdout_alone(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    probe = (
        "import os, sys; print(os.getcwd()); print('second'); "
        "sys.stderr.write('stderr-only 41d2\\n'); sys.exit(4)"
    )
    capfd.readouterr()
    code, out = capture([sys.executable, "-c", probe], work, 30)
    assert code == 4
    assert out == f"{work.resolve()}\nsecond\n"
    assert "stderr-only 41d2" not in capfd.readouterr().out


def test_capture_runs_argv_without_a_shell(tmp_path: Path) -> None:
    code, out = capture(["/bin/echo", "$HOME", "a;b", "*"], tmp_path, 30)
    assert code == 0
    assert out == "$HOME a;b *\n"


@pytest.mark.parametrize(
    "argv_cwd",
    ["missing-program", "missing-cwd"],
)
def test_capture_gives_none_and_empty_on_oserror(argv_cwd: str, tmp_path: Path) -> None:
    if argv_cwd == "missing-program":
        argv, cwd = [str(tmp_path / "no-such-program")], tmp_path
    else:
        argv, cwd = ["/bin/echo", "hi"], tmp_path / "no-such-dir"
    assert capture(argv, cwd, 30) == (None, "")


def test_capture_kills_and_reaps_the_group_at_timeout(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    grandfile = tmp_path / "grandchild"
    script = "echo partial; " + SLOW.format(grand=_q(grandfile), pid=_q(pidfile))
    start = time.monotonic()
    try:
        assert capture(["/bin/sh", "-c", script], tmp_path, 1.0) == (None, "")
        assert time.monotonic() - start < 20
        shell = _pid(pidfile)
        assert not _alive(shell)
        with pytest.raises(ChildProcessError):
            os.waitpid(shell, os.WNOHANG)
        assert _gone_within(_pid(grandfile))
    finally:
        _cleanup(grandfile, pidfile)


# ---------------------------------------------------------------------------------------
# A child Relay starts is signalled and reaped exactly once, even when a SIGINT or SIGTERM
# lands partway through Relay's kill of it, whether the earlier signal handler raises or
# returns; Relay never signals or waits on a group or pid it has already reaped.

# Runs one kill of a child in a fresh interpreter, with `os.kill`, `os.killpg` and
# `os.waitpid` wrapped to record every call in order. `a["signum"]` is raised in Relay at
# the first such call after the kill's first signal ("grace": the child ignores SIGTERM, so
# Relay is in its grace wait) or inside the reaping `waitpid` right after it returns
# ("reaped": while Relay's kill is still running). The handler installed before Relay's
# raises or returns per `a["earlier"]`.
KILL_DRIVER = """
import json, os, signal, sys
from pathlib import Path

a = json.loads(sys.argv[1])
signum = a["signum"]
pidfile = Path(a["pidfile"])
events = []
state = {"killing": False, "reaped": False, "landed": False}
real_kill, real_killpg, real_waitpid = os.kill, os.killpg, os.waitpid


class Earlier(Exception):
    pass


def earlier(signo, frame):
    events.append(["earlier", signo])
    if a["earlier"] == "raises":
        raise Earlier(signo)


def child():
    try:
        return int(pidfile.read_text().strip())
    except (OSError, ValueError):
        return None


def land():
    due = state["reaped"] if a["moment"] == "reaped" else state["killing"]
    if due and not state["landed"]:
        state["landed"] = True
        events.append(["landed", a["moment"]])
        signal.raise_signal(signum)


def note_signal(target, sig):
    if sig != 0 and abs(target) == child():
        state["killing"] = True


def kill(pid, sig):
    land()
    events.append(["kill", pid, sig])
    note_signal(pid, sig)
    return real_kill(pid, sig)


def killpg(pgid, sig):
    land()
    events.append(["killpg", pgid, sig])
    note_signal(pgid, sig)
    return real_killpg(pgid, sig)


def waitpid(pid, options):
    land()
    entry = ["waitpid", pid, options, None]
    events.append(entry)
    try:
        got = real_waitpid(pid, options)
    except BaseException as exc:
        entry[3] = type(exc).__name__
        raise
    entry[3] = got[0]
    if got[0] != 0 and got[0] == child():
        state["reaped"] = True
        events.append(["reaped", got[0]])
        land()
    return got


signal.signal(signal.SIGINT, earlier)
signal.signal(signal.SIGTERM, earlier)
# Wrapped before Relay (and `subprocess`) is imported, so a reference taken at import time
# is the wrapper too.
os.kill, os.killpg, os.waitpid = kill, killpg, waitpid
import relay.runner as runner

outcome = "returned"
try:
    cwd = Path(a["cwd"])
    if a["entry"] == "run_command":
        runner.run_command(a["command"], cwd, Path(a["log"]), 0.5)
    elif a["entry"] == "capture":
        runner.capture(["/bin/sh", "-c", a["command"]], cwd, 0.5)
    else:
        runner.run_agent(a["argv"], "p\\n", cwd, Path(a["run_dir"]), lambda s: "kill",
                         Path(a["retire"]))
except BaseException as exc:
    outcome = type(exc).__name__
finally:
    os.kill, os.killpg, os.waitpid = real_kill, real_killpg, real_waitpid
    Path(a["out"]).write_text(json.dumps({"events": events, "outcome": outcome}))
"""


def _on(events: list[list[Any]], child: int) -> list[list[Any]]:
    """The recorded kill, killpg and waitpid calls whose pid or group is `child`."""
    return [
        event for event in events
        if event[0] in {"kill", "killpg", "waitpid"} and abs(event[1]) == child
    ]


@pytest.mark.parametrize("earlier", ["raises", "returns"])
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM], ids=["SIGINT", "SIGTERM"])
@pytest.mark.parametrize("moment", ["grace", "reaped"])
@pytest.mark.parametrize("entry", ["run_agent", "run_command", "capture"])
def test_a_signal_landing_mid_kill_leaves_the_child_signalled_and_reaped_once(
    entry: str,
    moment: str,
    signum: int,
    earlier: str,
    fake: list[str],
    tmp_path: Path,
    run_dir: Path,
) -> None:
    pidfile = tmp_path / "pid"
    grandfile = tmp_path / "grandchild"
    out = tmp_path / "kill.json"
    # In the grace wait the child must outlast SIGTERM; after the reap it need not.
    stubborn = moment == "grace"
    args = {
        "entry": entry,
        "moment": moment,
        "signum": int(signum),
        "earlier": earlier,
        "pidfile": str(pidfile),
        "cwd": str(tmp_path),
        "log": str(_log(tmp_path)),
        "run_dir": str(run_dir),
        "retire": str(tmp_path / "retire"),
        "out": str(out),
        "command": (SLOW_STUBBORN if stubborn else SLOW).format(
            grand=_q(grandfile), pid=_q(pidfile)
        ),
        "argv": _sh(STUBBORN if stubborn else LONG, pidfile, grandfile, fake[0]),
    }
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(REPO), env.get("PYTHONPATH", "")) if p)
    with open(tmp_path / "driver.out", "wb") as log:
        driver = subprocess.Popen(
            [sys.executable, "-c", KILL_DRIVER, json.dumps(args)],
            cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        )
    try:
        driver.wait(timeout=60)
        assert out.exists(), "the driver ended without recording the kill"
        record = json.loads(out.read_text())
        events = record["events"]
        # Relay kills the group first, then the earlier handler decides how Relay goes on.
        assert record["outcome"] == ("Earlier" if earlier == "raises" else "returned")
        child = _pid(pidfile)
        kinds = [event[0] for event in events]
        assert "landed" in kinds, "the signal never landed during the kill"
        # Reaped exactly once.
        assert kinds.count("reaped") == 1
        landed, reaped = kinds.index("landed"), kinds.index("reaped")
        if moment == "grace":
            assert landed < reaped
        else:
            assert landed > reaped
        # Signalled once: each signal of the kill sent once, however many handlers ran.
        sent = [event[2] for event in _on(events, child) if event[0] != "waitpid" and event[2] != 0]
        assert sent
        for sig in set(sent):
            assert sent.count(sig) == 1
        # Nothing after the reap signals or waits on the reaped pid or its group.
        after = _on(events[reaped + 1 :], child)
        assert [event for event in after if event[0] == "waitpid"] == []
        assert [event for event in after if event[0] != "waitpid" and event[2] != 0] == []
        assert _gone_within(child)
        assert _gone_within(_pid(grandfile))
    finally:
        if driver.poll() is None:
            driver.kill()
            driver.wait()
        _cleanup(grandfile, pidfile)


# Graceful drain contract: relay-drain-design.md, Modules / relay.runner.py.


@pytest.mark.parametrize("exceptional", [False, True], ids=["return", "exception"])
def test_drain_first_term_sets_the_switch_once_and_restores_handlers(exceptional: bool) -> None:
    # Breaks when arming changes SIGINT, calls the callback too early, loses the request,
    # or leaves its SIGTERM handler installed after either normal or exceptional exit.
    requested = []
    previous = signal.getsignal(signal.SIGTERM)
    interrupt = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    try:
        try:
            with runner_module.drain_armed(lambda: requested.append("draining")) as switch:
                assert switch.requested is False
                assert requested == []
                assert signal.getsignal(signal.SIGINT) is interrupt
                signal.raise_signal(signal.SIGTERM)
                assert switch.requested is True
                assert requested == ["draining"]
                with pytest.raises(KeyboardInterrupt):
                    signal.raise_signal(signal.SIGTERM)
                assert requested == ["draining"]
                if exceptional:
                    raise ValueError("leave the armed run")
        except ValueError:
            assert exceptional
        assert signal.getsignal(signal.SIGTERM) == signal.SIG_IGN
        assert signal.getsignal(signal.SIGINT) is interrupt
    finally:
        signal.signal(signal.SIGTERM, previous)


def test_drain_pause_returns_when_requested_instead_of_waiting_the_whole_interval() -> None:
    # Breaks when a parked run sleeps its full poll interval after a drain request.
    previous = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    timer = None
    try:
        with runner_module.drain_armed(lambda: None) as switch:
            timer = threading.Timer(0.05, os.kill, args=(os.getpid(), signal.SIGTERM))
            timer.start()
            started = time.monotonic()
            switch.pause(10)
            assert switch.requested is True
            assert time.monotonic() - started < 1.5
            started = time.monotonic()
            switch.pause(10)
            assert time.monotonic() - started < 0.5
    finally:
        if timer is not None:
            timer.cancel()
            timer.join(2)
        signal.signal(signal.SIGTERM, previous)


def test_unrequested_drain_pause_waits_for_its_interval() -> None:
    # Breaks when pauses return early without a request.
    switch = runner_module.DrainSwitch()
    started = time.monotonic()
    switch.pause(1.05)
    assert time.monotonic() - started >= 1.04
    assert switch.requested is False


def test_drain_arming_off_the_main_thread_installs_no_handlers() -> None:
    # Breaks when threaded loop callers try to install a process-wide signal handler.
    before = signal.getsignal(signal.SIGTERM)
    observations = []
    errors = []

    def worker() -> None:
        try:
            with runner_module.drain_armed(lambda: observations.append("callback")) as switch:
                observations.append(switch.requested)
                switch.pause(0)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(2)
    assert not thread.is_alive()
    assert errors == []
    assert observations == [False]
    assert signal.getsignal(signal.SIGTERM) is before


@pytest.mark.parametrize("missing", [False, True], ids=["live", "already-gone"])
def test_signal_drain_sends_term_and_tolerates_a_run_that_just_exited(
    monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
    # Breaks when stop sends the wrong signal, targets a group, or races a finished run.
    sent = []

    def record(pid, signum):
        sent.append((pid, signum))
        if missing:
            raise ProcessLookupError("run finished")

    monkeypatch.setattr(os, "kill", record)
    runner_module.signal_drain(73591)
    assert sent == [(73591, signal.SIGTERM)]


def test_signal_drain_preserves_other_signalling_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # Breaks when stop conceals permission errors as an already-finished run.
    def denied(pid, signum):
        raise PermissionError("cannot signal that run")

    monkeypatch.setattr(os, "kill", denied)
    with pytest.raises(PermissionError, match="cannot signal that run"):
        runner_module.signal_drain(73591)


# This driver invokes the real runner and existing fake; the test body sends each signal.
DRAIN_DRIVER = DRIVER.replace(
    "from relay.runner import run_agent",
    "from relay.runner import run_agent, drain_armed\nfrom relay.errors import ExitCode",
).replace(
    '\nrun_agent(a["argv"]',
    '\nwith drain_armed(lambda: Path(a["requested"]).touch()):\n    result = run_agent(a["argv"]',
) + '\nPath(a["completed"]).write_text(json.dumps({"exit": result.exit_code, "killed": result.killed, "text": result.stream.result_text}))\nsys.exit(ExitCode.DRAINED)\n'


@pytest.mark.parametrize("force", [None, signal.SIGTERM, signal.SIGINT], ids=["finish", "second-term", "ctrl-c"])
def test_first_term_preserves_the_running_group_and_force_stops_it(
    force: int | None, fake: list[str], tmp_path: Path, run_dir: Path
) -> None:
    # Breaks when the group guard kills on the first TERM, loses the normal result,
    # or fails to kill the live group on a second TERM or Ctrl-C while draining.
    pidfile = tmp_path / "pid"
    grandfile = tmp_path / "grandchild"
    marker = tmp_path / "streaming"
    requested = tmp_path / "draining"
    completed = tmp_path / "completed"
    argv = (
        _sh('echo $$ > "$1"; "$2"; sleep 1', pidfile, fake[0])
        if force is None
        else _sh(LONG, pidfile, grandfile, fake[0])
    )
    args = {
        "argv": argv, "cwd": str(tmp_path), "run_dir": str(run_dir),
        "retire": str(tmp_path / "retire"), "marker": str(marker),
        "requested": str(requested), "completed": str(completed),
    }
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(REPO), env.get("PYTHONPATH", "")) if p)
    with (tmp_path / "drain-driver.out").open("wb") as out:
        driver = subprocess.Popen(
            [sys.executable, "-c", DRAIN_DRIVER, json.dumps(args)], cwd=REPO, env=env,
            stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
        )
    try:
        deadline = time.monotonic() + 10
        while (not marker.exists() or not pidfile.exists()) and driver.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists() and pidfile.exists(), "armed runner never started its child"
        child = _pid(pidfile)
        assert _alive(child)
        driver.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + 5
        while not requested.exists() and driver.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert requested.exists(), "first TERM did not request a drain"
        assert _alive(child), "first TERM killed the running child"
        assert not (tmp_path / "retire").exists()
        if force is not None:
            grandchild = _pid(grandfile)
            assert _alive(grandchild)
            driver.send_signal(force)
        driver.wait(timeout=10)
        assert _gone_within(child)
        if force is None:
            assert driver.returncode == ExitCode.DRAINED == 6
            assert json.loads(completed.read_text()) == {"exit": 0, "killed": False, "text": "DONE"}
        else:
            assert not completed.exists()
            assert _gone_within(grandchild)
    finally:
        if driver.poll() is None:
            driver.kill()
            driver.wait(timeout=5)
        _cleanup(grandfile, pidfile)
