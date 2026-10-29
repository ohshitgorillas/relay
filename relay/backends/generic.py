"""Plain stdout backend interface."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from relay.backends.base import Capabilities
from relay.stream import StreamState

if TYPE_CHECKING:
    from relay.config import Config


class GenericBackend:
    capabilities = Capabilities(context=False, tokens=False, dollars=False, subagents=False)

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
