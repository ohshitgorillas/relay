"""The one place a child process starts, streams, is killed and is reaped."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
import weakref
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


def _reap(proc: subprocess.Popen) -> None:
    """Reap the child with `os.waitpid` and record that on `proc`, so `Popen` never waits on
    the reaped pid again. Whether or not it has already been reaped is harmless."""
    try:
        _, status = os.waitpid(proc.pid, 0)
        code = os.waitstatus_to_exitcode(status)
    except ChildProcessError:
        code = 0  # reaped elsewhere; `Popen` records the same
    if proc.returncode is None:
        proc.returncode = code


def _leader_reaped(proc: subprocess.Popen) -> bool:
    """Whether the leader has been reaped, asked of the kernel rather than of `returncode`.

    `Popen` sets `returncode` only after its own `waitpid` returns, so a signal guard that fires
    in between sees `None` for a leader already gone. A non-blocking `waitpid` cannot be fooled:
    a leader still running yields nothing, a zombie is reaped here and recorded, and a leader
    reaped elsewhere raises `ChildProcessError`."""
    if proc.returncode is not None:
        return True
    try:
        pid, status = os.waitpid(proc.pid, os.WNOHANG)
    except ChildProcessError:
        return True
    if pid == 0:
        return False
    proc.returncode = os.waitstatus_to_exitcode(status)
    return True


def _signal_held(proc: subprocess.Popen, signum: int) -> None:
    """Signal the child's group only while its leader is unreaped (the pgid cannot be reused)
    or while stragglers still hold it. This is the one place a kill's signals are decided."""
    if _leader_reaped(proc) and not _group_alive(proc.pid):
        return
    _signal_group(proc.pid, signum)


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


# How far each child's kill has got. A kill that a signal guard interrupts is finished by the
# guard's nested call, and the interrupted outer call is told by this record, so the child is
# signalled and reaped exactly once and nothing touches its pid or group after the reap.
_TERMED, _REAPED = 1, 2
_stage: weakref.WeakKeyDictionary[subprocess.Popen, int] = weakref.WeakKeyDictionary()


def _kill_and_reap(proc: subprocess.Popen) -> None:
    """Kill the child's whole process group, reap the child, and check the group is gone.

    A group is signalled only while its leader is unreaped (its pgid cannot be reused) or
    while stragglers still hold it. A call that finds the SIGTERM already sent (a kill under
    way, interrupted by a signal) skips straight to the SIGKILL, the reap and the check; a
    call that finds the child reaped returns at once, and so does an interrupted call that
    resumes to find it reaped.
    """
    pgid = proc.pid
    if _stage.get(proc, 0) < _TERMED:
        _stage[proc] = _TERMED
        _signal_held(proc, signal.SIGTERM)
        deadline = time.monotonic() + _GRACE_SECONDS
        while True:
            # The probe comes first: a nested kill that lands here ends this one.
            alive = _group_alive(pgid)
            if _stage[proc] >= _REAPED:
                return
            if not alive or proc.poll() is not None or time.monotonic() >= deadline:
                break
            time.sleep(0.02)
    if _stage[proc] >= _REAPED:
        return
    if not _leader_reaped(proc):
        _signal_group(pgid, signal.SIGKILL)
        _reap(proc)
        _stage[proc] = _REAPED
    else:
        # The leader is already reaped; only stragglers can still be in the group.
        _stage[proc] = _REAPED
        _signal_held(proc, signal.SIGKILL)
    deadline = time.monotonic() + _GRACE_SECONDS
    while _group_alive(pgid):
        if time.monotonic() >= deadline:
            raise RuntimeError(f"process group {pgid} survived its kill")
        time.sleep(0.02)


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
