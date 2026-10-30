"""Claude Code backend interface."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from relay.backends.base import Capabilities, Launch
from relay.errors import ConfigError
from relay.stream import StreamState, feed

if TYPE_CHECKING:
    from relay.config import Config


CHILD_ENV: Mapping[str, str] = {"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0"}


class ClaudeBackend:
    capabilities = Capabilities(context=True, tokens=True, dollars=True, subagents=True, resume=True)

    def argv(self, role: str, cfg: Config, cwd: Path, output: Path) -> list[str]:
        if role == "lead":
            return list(cfg.lead_command)
        if role == "recut":
            return list(cfg.recut_command)
        if role in ("research", "ask"):
            return list(cfg.research_command)
        if role == "design":
            return list(cfg.design_command)
        raise ConfigError(f"unknown backend role {role!r}")

    def parse(self, state: StreamState, line: str) -> StreamState:
        return feed(state, line)

    def poll(self, state: StreamState) -> StreamState:
        return state

    def finish(self, state: StreamState, output: Path) -> StreamState:
        return state

    def resume_hint(self, session_id: str) -> str:
        return f"resume {session_id}"

    def launch(self, role: str, retire_flag: Path, run_dir: Path) -> Launch:
        return Launch(env=CHILD_ENV)
