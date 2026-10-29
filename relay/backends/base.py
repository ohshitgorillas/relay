"""Shared backend contract and capability declarations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from relay.stream import StreamState

if TYPE_CHECKING:
    from relay.config import Config


@dataclass(frozen=True)
class Capabilities:
    context: bool
    tokens: bool
    dollars: bool
    subagents: bool
    resume: bool = False


class Backend(Protocol):
    capabilities: Capabilities

    def argv(self, role: str, cfg: Config, cwd: Path, output: Path) -> list[str]:
        raise NotImplementedError

    def parse(self, state: StreamState, line: str) -> StreamState:
        raise NotImplementedError

    def poll(self, state: StreamState) -> StreamState:
        raise NotImplementedError

    def finish(self, state: StreamState, output: Path) -> StreamState:
        raise NotImplementedError

    def resume_hint(self, session_id: str) -> str:
        raise NotImplementedError
