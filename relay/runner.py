"""The one place a child process starts, streams, is killed and is reaped."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from relay.stream import StreamState

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
    raise NotImplementedError
