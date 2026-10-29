"""Codex exec protocol, generated role configuration and handoffs."""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from relay import agents
from relay.backends.base import Capabilities
from relay.backends.codex_session import SessionReader, rollout_boundary
from relay.errors import ConfigError
from relay.ledger import Spend
from relay.stream import StreamState

if TYPE_CHECKING:
    from relay.config import Config


class CodexBackend:
    capabilities = Capabilities(context=True, tokens=True, dollars=False, subagents=True, resume=True)

    def __init__(self) -> None:
        self.home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        self.reader: SessionReader | None = None

    def argv(self, role: str, cfg: Config, cwd: Path, output: Path) -> list[str]:
        filename = {
            "lead": "lead", "recut": "divvyer", "research": "researcher",
            "ask": "researcher", "design": "architect",
        }.get(role)
        if filename is None:
            raise ConfigError(f"unknown Codex role {role!r}")
        path = self.home / "agents" / f"{filename}.toml"
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise ConfigError(f"cannot read Codex role {path}: {exc}") from exc
        instructions = data.get("developer_instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            raise ConfigError(f"Codex role {path} requires developer_instructions")
        overrides = []
        for key in ("developer_instructions", "model", "model_reasoning_effort"):
            if key in data:
                if not isinstance(data[key], str) or not data[key].strip():
                    raise ConfigError(f"invalid Codex role setting {key!r} in {path}")
                overrides.extend(["-c", f"{key}={json.dumps(data[key], ensure_ascii=False)}"])
        features = data.get("features", {})
        if not isinstance(features, dict):
            raise ConfigError(f"invalid Codex role features in {path}")
        for key, value in features.items():
            if not isinstance(value, bool):
                raise ConfigError(f"invalid Codex role feature {key!r} in {path}")
            overrides.extend(["-c", f"features.{json.dumps(key)}={str(value).lower()}"])
        if role == "ask":
            command = cfg.research_command
            if len(command) < 2 or command[-2] != "--resume":
                raise ConfigError("Codex researcher follow-up requires a session to resume")
            self.reader = SessionReader(
                self.home, command[-1], boundary=rollout_boundary(self.home, command[-1])
            )
            return ["codex", "exec", "resume", "--json",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "-o", str(output), *overrides, command[-1], "-"]
        return ["codex", "exec", "--json", "--dangerously-bypass-approvals-and-sandbox",
                "-C", str(cwd), "-o", str(output), *overrides, "-"]

    def parse(self, state: StreamState, line: str) -> StreamState:
        try:
            event = json.loads(line)
        except (ValueError, RecursionError):
            return state
        if not isinstance(event, dict):
            return state
        kind = event.get("type")
        if kind == "thread.started":
            sid = event.get("thread_id")
            if state.session_id is None and isinstance(sid, str) and sid:
                return replace(state, session_id=sid)
        elif kind in ("error", "turn.failed"):
            return replace(state, is_error=True)
        elif kind == "turn.completed":
            usage = event.get("usage")
            if isinstance(usage, dict):
                counts = [usage.get(key) for key in ("input_tokens", "output_tokens")]
                if all(type(value) is int and value >= 0 for value in counts):
                    return replace(state, spend=Spend(max(state.spend.tokens, sum(counts)), state.spend.dollars))
        elif kind in ("item.started", "item.updated", "item.completed"):
            item = event.get("item")
            if not isinstance(item, dict):
                return state
            if item.get("type") == "agent_message" and kind == "item.completed":
                text = item.get("text")
                if isinstance(text, str):
                    return replace(state, result_text=text)
            if item.get("type") == "collab_tool_call":
                return replace(state, activity=self._activity(state.activity, item))
        return state

    @staticmethod
    def _activity(activity: agents.Activity, item: dict) -> agents.Activity:
        receivers, statuses = item.get("receiver_thread_ids"), item.get("agents_states")
        if not isinstance(receivers, list) or not isinstance(statuses, dict):
            return activity
        for sid in receivers:
            if not isinstance(sid, str):
                continue
            receiver = statuses.get(sid)
            if not isinstance(receiver, dict):
                continue
            status = receiver.get("status")
            if status not in ("pending_init", "running", "interrupted", "completed", "errored", "shutdown", "not_found"):
                continue
            known = next((a for a in activity.agents if a.task_id == sid), None)
            if known is None or (status in ("pending_init", "running") and sid not in activity.live):
                activity = agents.feed(activity, {
                    "subtype": "task_started", "task_id": sid, "task_type": "local_agent",
                    "description": item.get("prompt"), "subagent_type": "",
                })
            if status not in ("pending_init", "running") and sid in activity.live:
                activity = agents.feed(activity, {
                    "subtype": "task_notification", "task_id": sid, "status": status,
                })
        return activity

    def poll(self, state: StreamState) -> StreamState:
        if state.session_id:
            if self.reader is None or self.reader.session_id != state.session_id:
                boundary = self.reader.boundary if self.reader is not None else None
                self.reader = SessionReader(self.home, state.session_id, boundary=boundary)
        return self.reader.poll(state) if self.reader is not None else state

    def finish(self, state: StreamState, output: Path) -> StreamState:
        state = self.poll(state)
        if self.reader is not None:
            state = self.reader.poll(state, force_scan=True)
        if self.reader is None or not self.reader.observed:
            state = replace(state, is_error=True)
        try:
            return replace(state, result_text=output.read_text())
        except FileNotFoundError:
            return state
        except (OSError, UnicodeError):
            return replace(state, is_error=True)

    def resume_hint(self, session_id: str) -> str:
        return (f"Prior Codex thread: {session_id}. Native history continuation uses "
                f"`codex exec resume {session_id}`. This fresh thread uses the supplied "
                "report as its handoff.")
