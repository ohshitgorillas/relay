"""Plain stdout backend interface."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from relay.backends.base import Capabilities
from relay.errors import ConfigError
from relay.stream import StreamState

if TYPE_CHECKING:
    from relay.config import Config


class GenericBackend:
    capabilities = Capabilities(context=False, tokens=False, dollars=False, subagents=False)

    def argv(self, role: str, cfg: Config, cwd: Path, output: Path) -> list[str]:
        if role == "lead":
            return list(cfg.lead_command)
        if role == "recut":
            return list(cfg.recut_command)
        raise ConfigError(f"unknown backend role {role!r}")

    def parse(self, state: StreamState, line: str) -> StreamState:
        return replace(state, result_text=(state.result_text or "") + line)

    def poll(self, state: StreamState) -> StreamState:
        return state

    def finish(self, state: StreamState, output: Path) -> StreamState:
        return replace(state, result_text=state.result_text or "")

    def resume_hint(self, session_id: str) -> str:
        return ""
