"""The one place a child process starts, streams, is killed and is reaped."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from relay.stream import StreamState


@dataclass(frozen=True)
class RunResult:
    exit_code: int | None
    killed: bool
    stream: StreamState
    log: Path


def run_agent(
    argv: list[str],
    stdin_text: str,
    cwd: Path,
    run_dir: Path,
    on_event: Callable[[StreamState], Literal["go", "retire", "kill"]],
    retire_flag: Path,
) -> RunResult:
    raise NotImplementedError
