"""The one place a child process starts, streams, is killed and is reaped."""

from __future__ import annotations

import codecs
import json
import os
import selectors
import signal
import subprocess
import threading
import time
import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from relay.stream import StreamState
from relay.ledger import Spend
from relay.files import atomic_write

if TYPE_CHECKING:
    from relay.backends.base import Backend
    from relay.config import Config

_GRACE_SECONDS = 2.0


@dataclass(frozen=True)
class RunResult:
    exit_code: int | None
    killed: bool
    stream: StreamState
    log: Path


def run_failed(result: RunResult) -> bool:
    """Killed, exited nonzero, its result marked an error, or no tokens used."""
    return (
        result.killed
        or result.exit_code != 0
        or result.stream.is_error
        or result.stream.spend.tokens == 0
    )


def error_line(result: RunResult) -> str:
    """The last non-empty line of the run's stderr, else the error result's text, else the cause: killed, no tokens, "exit N"."""
    try:
        lines = result.log.with_suffix(".stderr").read_text(errors="replace").splitlines()
    except OSError:
        lines = []
    for line in reversed(lines):
        if line.strip():
            return line.strip()
    text = (result.stream.result_text or "").strip()
    if result.stream.is_error and text:
        return text
    if result.killed:
        return "killed"
    if result.stream.spend.tokens == 0 and result.exit_code == 0:
        return "used no tokens"
    return f"exit {result.exit_code}"


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


@contextmanager
def _signals_deferred() -> Iterator[None]:
    """Hold SIGINT and SIGTERM back, so a guard's handler runs only before or after the block,
    never between its steps. A handler left pending runs as the block ends. Off the main
    thread, where no guard handler is installed, it holds nothing."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    held = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, held)


def _reap(proc: subprocess.Popen) -> None:
    """Reap the child with `os.waitpid` and record that on `proc`, so `Popen` never waits on
    the reaped pid again. Whether or not it has already been reaped is harmless. The reap and
    its record are one step: no guard's handler sees the pid reaped but unrecorded."""
    with _signals_deferred():
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
    reaped elsewhere raises `ChildProcessError`. The reap and its record are one step: no
    guard's handler sees the pid reaped but unrecorded."""
    with _signals_deferred():
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
    resumes to find it reaped. The SIGKILL and the reap run with SIGINT and SIGTERM held.
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
            if not alive or _leader_reaped(proc) or time.monotonic() >= deadline:
                break
            time.sleep(0.02)
    # The SIGKILL, the reap and the record of both are one step: a guard's handler runs before
    # it (and finishes the kill, which this call then finds) or after it (and finds it done),
    # so neither signal nor reap is repeated. The record is read once the signals are held.
    with _signals_deferred():
        if _stage[proc] >= _REAPED:
            return
        leader_reaped = _leader_reaped(proc)
        _signal_held(proc, signal.SIGKILL)
        if not leader_reaped:
            _reap(proc)
        _stage[proc] = _REAPED
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
    *,
    backend: Backend | None = None,
    cfg: Config | None = None,
    role: str = "lead",
) -> RunResult:
    from relay.backends import get_backend

    backend = backend if backend is not None else get_backend(cfg.backend if cfg else "claude")
    run_dir.mkdir(parents=True, exist_ok=True)
    number = _next_number(run_dir)
    log_path = run_dir / f"{number}.jsonl"
    output = run_dir / f"{number}.final.txt"
    telemetry = log_path.with_suffix(".telemetry.json")
    if cfg is not None:
        argv = backend.argv(role, cfg, cwd, output)
    atomic_write(
        log_path.with_suffix(".backend.json"),
        (json.dumps({"backend": cfg.backend if cfg else "claude"}) + "\n").encode(),
    )
    state = StreamState(None, 0, Spend(0, 0.0), None, False)
    killed = False
    retired = False
    live: list[subprocess.Popen] = []

    def snapshot() -> None:
        payload = json.dumps(asdict(state), default=list) + "\n"
        atomic_write(telemetry, payload.encode("utf-8"))

    def observe() -> None:
        nonlocal state, killed, retired
        state = backend.poll(state)
        snapshot()
        verdict = on_event(state)
        if verdict == "kill":
            killed = True
        elif verdict == "retire" and not retired:
            retired = True
            retire_flag.touch()

    # Handlers go in before the child starts.
    with _group_guard(live):
        with log_path.with_suffix(".stderr").open("wb") as stderr_file:
            proc = subprocess.Popen(
                argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=stderr_file, start_new_session=True,
            )
            live.append(proc)
            try:
                log_path.with_suffix(".pid").write_text(f"{proc.pid}\n")
                assert proc.stdin is not None and proc.stdout is not None
                # Multiplex prompt writes too: a child may write stdout before it reads stdin.
                pending = memoryview(stdin_text.encode())
                decoder = codecs.getincrementaldecoder("utf-8")("replace")
                buffered = ""
                stdout_open = True
                group_cleaned = False
                with selectors.DefaultSelector() as selector, log_path.open("wb") as log:
                    os.set_blocking(proc.stdout.fileno(), False)
                    os.set_blocking(proc.stdin.fileno(), False)
                    selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
                    if pending:
                        selector.register(proc.stdin, selectors.EVENT_WRITE, "stdin")
                    else:
                        proc.stdin.close()
                    while stdout_open or proc.poll() is None:
                        if proc.poll() is not None and not group_cleaned:
                            # Descendants can retain stdout after the child exits.
                            # Clean them up before draining the remaining pipe data.
                            _kill_live(live)
                            group_cleaned = True
                        ready = selector.select(0.1)
                        if not ready:
                            observe()
                        for key, _events in ready:
                            if key.data == "stdin":
                                try:
                                    written = os.write(key.fd, pending[:65536])
                                    pending = pending[written:]
                                except BrokenPipeError:
                                    pending = pending[:0]
                                if not pending:
                                    selector.unregister(proc.stdin)
                                    proc.stdin.close()
                                continue
                            chunk = os.read(key.fd, 65536)
                            if chunk:
                                log.write(chunk)
                                log.flush()
                                buffered += decoder.decode(chunk)
                            else:
                                selector.unregister(proc.stdout)
                                stdout_open = False
                                buffered += decoder.decode(b"", final=True)
                            while "\n" in buffered:
                                line, buffered = buffered.split("\n", 1)
                                state = backend.parse(state, line + "\n")
                                observe()
                                if killed:
                                    break
                            if not stdout_open and buffered and not killed:
                                state = backend.parse(state, buffered)
                                buffered = ""
                                observe()
                            if killed:
                                break
                        if killed:
                            break
                if killed:
                    _kill_live(live)
                    exit_code = None
                else:
                    exit_code = proc.wait()
                    if not group_cleaned:
                        _kill_live(live)
                state = backend.finish(state, output)
                snapshot()
            except BaseException:
                _kill_live(live)
                raise
            finally:
                if proc.stdin is not None:
                    proc.stdin.close()
                if proc.stdout is not None:
                    proc.stdout.close()
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
