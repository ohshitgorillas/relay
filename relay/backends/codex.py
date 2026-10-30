"""Codex exec protocol, generated role configuration and handoffs."""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import replace
from pathlib import Path

from relay import agents
from relay.backends.base import Capabilities
from relay.backends.codex_session import SessionReader, rollout_boundary
from relay.codex_launch import adapter_args
from relay.config import Config
from relay.errors import ConfigError
from relay.ledger import Spend
from relay.pricing import Unpriced, dollars
from relay.stream import StreamState

class CodexBackend:
    capabilities = Capabilities(context=True, tokens=True, dollars=False, subagents=True, resume=True)

    def __init__(self) -> None:
        self.home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        self.reader: SessionReader | None = None
        self.readers: dict[str, SessionReader] = {}
        self._config = Config(None, None, 100_000, 200_000, 30, [], [], [], self.home)

    def argv(self, role: str, cfg: Config, cwd: Path, output: Path) -> list[str]:
        self._config = cfg
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
        # The instructions open the prompt rather than ride `-c developer_instructions`:
        # a spawned built-in agent such as `worker` inherits every session override,
        # so it would take this role's instructions as its own.
        overrides = adapter_args(self.home)
        for key in ("model", "model_reasoning_effort"):
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
        # With a prompt argument, Codex appends piped stdin, the brief, as a `<stdin>` block.
        return ["codex", "exec", "--json", "--dangerously-bypass-approvals-and-sandbox",
                "-C", str(cwd), "-o", str(output), *overrides, instructions]

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
        if not isinstance(receivers, list):
            return activity
        statuses = statuses if isinstance(statuses, dict) else {}
        for sid in receivers:
            if not isinstance(sid, str) or not sid:
                continue
            receiver = statuses.get(sid)
            status = receiver.get("status") if isinstance(receiver, dict) else None
            known = next((a for a in activity.agents if a.task_id == sid), None)
            if known is None or (status in ("pending_init", "running") and sid not in activity.live):
                activity = agents.feed(activity, {
                    "subtype": "task_started", "task_id": sid, "task_type": "local_agent",
                    "description": item.get("prompt"), "subagent_type": "",
                })
            if status in ("interrupted", "completed", "errored", "shutdown", "not_found"):
                activity = agents.feed(activity, {
                    "subtype": "task_notification", "task_id": sid, "status": status,
                })
        return activity

    def poll(self, state: StreamState) -> StreamState:
        return self._poll(state, force_scan=False)

    def _poll(self, state: StreamState, *, force_scan: bool) -> StreamState:
        if state.session_id:
            if self.reader is None or self.reader.session_id != state.session_id:
                boundary = self.reader.boundary if self.reader is not None else None
                self.reader = SessionReader(self.home, state.session_id, boundary=boundary)
            self.readers[state.session_id] = self.reader
        if self.reader is None:
            return state
        state = self.reader.poll(state, force_scan=force_scan)
        pending = [agent.task_id for agent in state.activity.agents]
        pending.extend(self.reader.children)
        visited = {state.session_id}
        usage = list(self.reader.usage)
        activity = state.activity
        while pending:
            sid = pending.pop(0)
            if sid in visited:
                continue
            visited.add(sid)
            if not any(agent.task_id == sid for agent in activity.agents):
                activity = self._activity(activity, {"receiver_thread_ids": [sid]})
            reader = self.readers.get(sid)
            if reader is None:
                reader = self.readers[sid] = SessionReader(self.home, sid)
            # Workers must not overwrite the lead's latest context or spend.
            reader.poll(StreamState(sid, 0, Spend(0, 0.0), None, False), force_scan=force_scan)
            pending.extend(reader.children)
            usage.extend(reader.usage)
            cost = None
            reason = reader.unavailable
            agent = next(agent for agent in activity.agents if agent.task_id == sid)
            if sid in activity.live or agent.status in (None, "pending_init", "running"):
                reason = reason or "thread is still running or final status unavailable"
            elif not reader.observed or not reader.usage:
                reason = reason or "final rollout usage missing"
            elif not force_scan:
                reason = reason or "final telemetry read pending"
            elif reason is None:
                try:
                    cost = dollars(self._config, reader.usage)
                except Unpriced as exc:
                    reason = str(exc)
            activity = agents.measured(
                activity, sid, models=reader.models, efforts=reader.efforts,
                cost_dollars=cost, cost_basis="api-estimate" if cost is not None else "none",
                cost_unavailable=reason,
            )
        return replace(state, activity=activity, usage=tuple(usage))

    def finish(self, state: StreamState, output: Path) -> StreamState:
        state = self._poll(state, force_scan=True)
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
