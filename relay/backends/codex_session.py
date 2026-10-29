"""Incremental Codex rollout telemetry."""
import json
import time
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from relay.errors import RelayError
from relay.ledger import Spend
from relay.stream import StreamState


class SessionReader:
    def __init__(self, home: Path, session_id: str):
        self.home, self.session_id = home, session_id
        self.path: Path | None = None
        self.offset = 0
        self.pending = b""
        self.observed = False
        self.model_context_window: int | None = None
        self._next_scan = 0.0
        try:
            self._valid_id = str(UUID(session_id)) == session_id
        except (ValueError, AttributeError):
            self._valid_id = False

    def _locate(self) -> None:
        if not self._valid_id or time.monotonic() < self._next_scan:
            return
        self._next_scan = time.monotonic() + 1.0
        for path in (self.home / "sessions").glob(f"**/*{self.session_id}*.jsonl"):
            try:
                with path.open("rb") as handle:
                    line = handle.readline(1024 * 1024)
                if not line.endswith(b"\n"):
                    continue
                meta = json.loads(line)
                if not isinstance(meta, dict):
                    continue
                payload = meta.get("payload")
                if (meta.get("type") == "session_meta" and isinstance(payload, dict)
                        and payload.get("id") == self.session_id):
                    self.path = path
                    return
            except OSError as exc:
                raise RelayError(f"cannot read Codex rollout telemetry {path}: {exc}") from exc
            except (ValueError, RecursionError):
                continue

    def poll(self, state: StreamState) -> StreamState:
        if self.path is None:
            self._locate()
        if self.path is None:
            return state
        try:
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                chunk = handle.read()
                self.offset = handle.tell()
        except OSError as exc:
            raise RelayError(f"cannot read Codex rollout telemetry {self.path}: {exc}") from exc
        lines = (self.pending + chunk).split(b"\n")
        self.pending = lines.pop()
        for line in lines:
            try:
                event = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if not isinstance(event, dict) or event.get("type") != "event_msg":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "token_count":
                continue
            info = payload.get("info")
            if not isinstance(info, dict):
                continue
            last, total = info.get("last_token_usage"), info.get("total_token_usage")
            if not isinstance(last, dict) or not isinstance(total, dict):
                continue
            context, spend = last.get("total_tokens"), total.get("total_tokens")
            if any(type(value) is not int or value < 0 for value in (context, spend)):
                continue
            window = info.get("model_context_window")
            if type(window) is int and window > 0:
                self.model_context_window = window
            self.observed = True
            state = replace(state, context_tokens=context,
                            spend=Spend(max(state.spend.tokens, spend), state.spend.dollars))
        return state
