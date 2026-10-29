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
from collections.abc import Callable
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


def _kill_and_reap(proc: subprocess.Popen) -> None:
    """Kill the child's whole process group, reap the child, and check the group is gone."""
    pgid = proc.pid
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
    log_path.with_suffix(".backend.json").write_text(
        json.dumps({"backend": cfg.backend if cfg else "claude"}) + "\n"
    )
    if cfg is not None:
        argv = backend.argv(role, cfg, cwd, output)
    state = StreamState(None, 0, Spend(0, 0.0), None, False)
    killed = False
    retired = False
    live: list[subprocess.Popen] = []
    previous: dict[int, object] = {}

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

    def on_signal(signum: int, _frame: object) -> None:
        if live:
            _kill_and_reap(live[0])
        signal.signal(signum, previous[signum])
        os.kill(os.getpid(), signum)

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, on_signal)
    try:
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
                            _kill_and_reap(proc)
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
                    _kill_and_reap(proc)
                    exit_code = None
                else:
                    exit_code = proc.wait()
                    if not group_cleaned:
                        _kill_and_reap(proc)
                state = backend.finish(state, output)
                snapshot()
            except BaseException:
                _kill_and_reap(proc)
                raise
            finally:
                if proc.stdin is not None:
                    proc.stdin.close()
                if proc.stdout is not None:
                    proc.stdout.close()
    finally:
        live.clear()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    return RunResult(exit_code=exit_code, killed=killed, stream=state, log=log_path)
