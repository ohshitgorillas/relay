"""The one place a child process starts, streams, is killed and is reaped."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from relay.ledger import Spend
from relay.stream import StreamState, feed

_GRACE_SECONDS = 2.0


@dataclass(frozen=True)
class RunResult:
    exit_code: int | None
    killed: bool
    stream: StreamState
    log: Path


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None
    timed_out: bool


def _next_number(run_dir: Path) -> int:
    numbers = [int(p.stem) for p in run_dir.glob("*.jsonl") if p.stem.isdigit()]
    return max(numbers, default=0) + 1


def _signal_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except (ProcessLookupError, PermissionError):
        pass


def _reap(pid: int) -> None:
    """Reap the child with `os.waitpid`, whether or not it has already been reaped."""
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass


# Groups whose SIGTERM is already out: a kill that a signal handler or guard interrupts is
# finished by the next `_kill_and_reap` of the same child, without a second grace period.
_termed: set[int] = set()


def _kill_and_reap(proc: subprocess.Popen) -> None:
    """Kill the child's whole process group, reap the child, and check the group is gone.

    A call that finds the group's SIGTERM already sent (a kill under way, interrupted by a
    signal) skips straight to the SIGKILL, the reap and the check.
    """
    pgid = proc.pid
    try:
        if pgid not in _termed:
            _termed.add(pgid)
            _signal_group(pgid, signal.SIGTERM)
            deadline = time.monotonic() + _GRACE_SECONDS
            while proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
        _signal_group(pgid, signal.SIGKILL)
        _reap(pgid)
        deadline = time.monotonic() + _GRACE_SECONDS
        while True:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return
            except PermissionError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError(f"process group {pgid} survived its kill")
            _signal_group(pgid, signal.SIGKILL)
            time.sleep(0.02)
    finally:
        _termed.discard(pgid)


def _kill_live(live: list[subprocess.Popen]) -> None:
    """Kill and reap the live child. It stays in `live` until its kill ends, so a guard that
    fires mid-kill finds it and finishes that kill rather than starting another."""
    if live:
        proc = live[0]
        try:
            _kill_and_reap(proc)
        finally:
            if proc in live:
                live.remove(proc)


def run_agent(
    argv: list[str],
    stdin_text: str,
    cwd: Path,
    run_dir: Path,
    on_event: Callable[[StreamState], Literal["go", "retire", "kill"]],
    retire_flag: Path,
) -> RunResult:
    number = _next_number(run_dir)
    log_path = run_dir / f"{number}.jsonl"
    pid_path = run_dir / f"{number}.pid"
    stderr_path = run_dir / f"{number}.stderr"
    state = StreamState(None, 0, Spend(0, 0.0), None, False)
    killed = False
    retired = False

    live: list[subprocess.Popen] = []

    # Handlers go in before the child starts.
    with _group_guard(live):
        stderr_file = None
        try:
            stderr_file = stderr_path.open("wb")
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr_file,
                text=True,
                start_new_session=True,
            )
            live.append(proc)
            try:
                pid_path.write_text(f"{proc.pid}\n")
                try:
                    assert proc.stdin is not None
                    proc.stdin.write(stdin_text)
                    proc.stdin.close()
                except BrokenPipeError:
                    pass
                assert proc.stdout is not None
                with log_path.open("w") as log:
                    for raw in proc.stdout:
                        line = raw.rstrip("\n")
                        log.write(line + "\n")
                        log.flush()
                        state = feed(state, line)
                        verdict = on_event(state)
                        if verdict == "kill":
                            killed = True
                            break
                        if verdict == "retire" and not retired:
                            retired = True
                            retire_flag.touch()
                if killed:
                    _kill_live(live)
                    exit_code = None
                else:
                    exit_code = proc.wait()
                    _kill_live(live)  # sweep stragglers in the group
            finally:
                if proc.stdout is not None:
                    proc.stdout.close()
        finally:
            if stderr_file is not None:
                stderr_file.close()
    return RunResult(exit_code=exit_code, killed=killed, stream=state, log=log_path)


@contextmanager
def _group_guard(live: list[subprocess.Popen]) -> Iterator[None]:
    """While active, SIGINT/SIGTERM kill the live child's group first, then re-raise the signal.

    An exception leaving the block also kills and reaps the live child's group.
    """
    previous: dict[int, object] = {}

    def on_signal(signum: int, _frame: object) -> None:
        _kill_live(live)
        signal.signal(signum, previous[signum])
        os.kill(os.getpid(), signum)

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, on_signal)
    try:
        yield
    except BaseException:
        _kill_live(live)
        raise
    finally:
        live.clear()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def run_command(command: str, cwd: Path, log: Path, timeout: float) -> CommandResult:
    """Run `/bin/sh -c command` in `cwd`, output appended to `log`, killed at `timeout`."""
    live: list[subprocess.Popen] = []
    with _group_guard(live), log.open("ab") as out:
        proc = subprocess.Popen(
            ["/bin/sh", "-c", command],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        live.append(proc)
        try:
            exit_code: int | None = proc.wait(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            exit_code, timed_out = None, True
        _kill_live(live)  # the group dies with the shell, or at the timeout
    return CommandResult(exit_code=exit_code, timed_out=timed_out)


def capture(argv: list[str], cwd: Path, timeout: float) -> tuple[int | None, str]:
    """Run argv in `cwd`, return (exit code, stdout); (None, "") on OSError or timeout."""
    live: list[subprocess.Popen] = []
    with _group_guard(live):
        try:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
        except OSError:
            return None, ""
        live.append(proc)
        try:
            try:
                out, _ = proc.communicate(timeout=timeout)
                result: tuple[int | None, str] = (proc.returncode, out)
            except subprocess.TimeoutExpired:
                result = (None, "")
            _kill_live(live)
        finally:
            if proc.stdout is not None:
                proc.stdout.close()
    return result
