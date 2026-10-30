"""Incremental Codex rollout telemetry."""
import json
import time
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from relay.errors import RelayError
from relay.ledger import Spend
from relay.pricing import Usage
from relay.stream import StreamState


def _matching_rollouts(home: Path, session_id: str):
    try:
        if str(UUID(session_id)) != session_id:
            return
    except (ValueError, AttributeError):
        return
    for path in (home / "sessions").glob(f"**/*{session_id}*.jsonl"):
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
                    and payload.get("id") == session_id):
                yield path
        except OSError as exc:
            raise RelayError(f"cannot read Codex rollout telemetry {path}: {exc}") from exc
        except (ValueError, RecursionError):
            continue


def rollout_boundary(home: Path, session_id: str) -> dict[Path, int]:
    """Record matching rollout sizes before a resumed child can write to them."""
    sizes = {}
    for path in _matching_rollouts(home, session_id):
        try:
            sizes[path] = path.stat().st_size
        except OSError as exc:
            raise RelayError(f"cannot read Codex rollout telemetry {path}: {exc}") from exc
    return sizes


class SessionReader:
    usage: tuple[Usage, ...]
    models: tuple[str, ...]
    efforts: tuple[str, ...]
    children: tuple[str, ...]
    unavailable: str | None

    def __init__(self, home: Path, session_id: str, *, boundary: dict[Path, int] | None = None):
        self.home, self.session_id = home, session_id
        self.boundary = boundary
        self._readers: dict[Path, SessionReader] = {}
        self.path: Path | None = None
        self.offset = 0
        self.pending = b""
        self.observed = False
        self.usage = ()
        self.models = ()
        self.efforts = ()
        self.children = ()
        self.unavailable = "rollout telemetry missing"
        self._problems: list[str] = []
        self._model = "unavailable"
        self._effort = "unavailable"
        self._previous: dict | None = None
        self._previous_tokens: int | None = None
        self._tokens = 0
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
        self.path = next(_matching_rollouts(self.home, self.session_id), None)

    def poll(self, state: StreamState, *, force_scan: bool = False) -> StreamState:
        if self.boundary is not None:
            if force_scan or time.monotonic() >= self._next_scan:
                self._next_scan = time.monotonic() + 1.0
                for path in _matching_rollouts(self.home, self.session_id):
                    if path not in self._readers:
                        reader = SessionReader(self.home, self.session_id)
                        reader.path = path
                        boundary = self.boundary.get(path, 0)
                        if boundary:
                            # Consume the historical prefix only to establish counters.
                            # It must not enter this invocation's measurements.
                            try:
                                with path.open("rb") as handle:
                                    prefix = handle.read(boundary)
                            except OSError as exc:
                                raise RelayError(f"cannot read Codex rollout telemetry {path}: {exc}") from exc
                            for line in prefix.splitlines():
                                reader._event(line, state)
                            reader.offset = boundary
                            reader.usage = ()
                            reader.models = reader.efforts = reader.children = ()
                            reader._tokens = 0
                            reader.observed = False
                            reader._problems = []
                            reader.unavailable = "rollout telemetry missing"
                            if reader._previous is None or not prefix.endswith(b"\n"):
                                reader._problems.append("resume baseline unavailable")
                        elif self.boundary and path not in self.boundary:
                            # A newly discovered file in an existing thread may
                            # repeat historical totals; zero is not a baseline.
                            reader._problems.append("resume baseline unavailable for new rollout")
                        self._readers[path] = reader
            for reader in self._readers.values():
                state = reader.poll(state)
                self.observed = self.observed or reader.observed
                if reader.model_context_window is not None:
                    self.model_context_window = reader.model_context_window
            self.usage = tuple(row for reader in self._readers.values() for row in reader.usage)
            for name in ("models", "efforts", "children"):
                setattr(self, name, tuple(dict.fromkeys(
                    value for reader in self._readers.values() for value in getattr(reader, name)
                )))
            reasons = tuple(dict.fromkeys(
                reader.unavailable for reader in self._readers.values() if reader.unavailable
            ))
            self.unavailable = "; ".join(reasons) if reasons else "rollout telemetry missing"
            return replace(state, usage=self.usage,
                           spend=Spend(max(state.spend.tokens, sum(
                               reader._tokens for reader in self._readers.values()
                           )), state.spend.dollars))
        if force_scan:
            self._next_scan = 0.0
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
        if "incomplete rollout record" in self._problems:
            self._problems.remove("incomplete rollout record")
            self.unavailable = "; ".join(self._problems) or None
        for line in lines:
            state = self._event(line, state)
        if self.pending:
            self._problem("incomplete rollout record")
        return replace(state, usage=self.usage)

    def _problem(self, reason: str) -> None:
        if reason not in self._problems:
            self._problems.append(reason)
        self.unavailable = "; ".join(self._problems)

    def _event(self, line: bytes, state: StreamState) -> StreamState:
        try:
            event = json.loads(line)
        except (ValueError, RecursionError):
            self._problem("malformed rollout record")
            return state
        if not isinstance(event, dict):
            self._problem("malformed rollout record")
            return state
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return state
        if event.get("type") == "turn_context":
            self._model = payload.get("model") or "unavailable"
            self._effort = payload.get("effort") or "unavailable"
            if not isinstance(self._model, str):
                self._model = "unavailable"
            if not isinstance(self._effort, str):
                self._effort = "unavailable"
            self._settings()
        receivers = payload.get("receiver_thread_ids")
        if payload.get("type") == "collab_tool_call" and isinstance(receivers, list):
            self.children = tuple(dict.fromkeys(self.children + tuple(
                sid for sid in receivers if isinstance(sid, str) and sid
            )))
        if event.get("type") != "event_msg" or payload.get("type") != "token_count":
            return state
        info = payload.get("info")
        if not isinstance(info, dict):
            self._problem("incomplete token telemetry")
            return state
        last, total = info.get("last_token_usage"), info.get("total_token_usage")
        if not isinstance(total, dict):
            self._problem("incomplete token telemetry")
            return state
        spend = total.get("total_tokens")
        if type(spend) is not int or spend < 0:
            self._problem("invalid token counters")
            return state
        # Token-budget accounting depends only on its own cumulative counter,
        # not on the completeness of context or billable cache dimensions.
        token_delta = spend - (self._previous_tokens or 0)
        if token_delta < 0:
            self._problem("cumulative token counter reset; baseline unavailable")
        else:
            self._tokens += token_delta
            self._previous_tokens = spend
        state = replace(state, spend=Spend(max(state.spend.tokens, self._tokens), state.spend.dollars))
        context = last.get("total_tokens") if isinstance(last, dict) else None
        if type(context) is not int or context < 0:
            self._problem("invalid context token counter")
            return state
        self.observed = True
        window = info.get("model_context_window")
        if type(window) is int and window > 0:
            self.model_context_window = window
        self._settings()
        keys = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
        invalid = [key for key in keys if type(total.get(key)) is not int or total[key] < 0]
        if invalid:
            for key in invalid:
                self._problem(f"{key} count invalid or unavailable")
            return replace(state, context_tokens=context)
        previous = self._previous or dict.fromkeys(keys, 0)
        delta = {key: total[key] - previous[key] for key in keys}
        if any(value < 0 for value in delta.values()):
            self._problem("cumulative token counter reset; baseline unavailable")
            return replace(state, context_tokens=context)
        self._previous = {key: total[key] for key in keys}
        # The captured provider input includes cached reads, and output includes
        # reasoning. Neither component is added a second time.
        self._problem("billing rate regime unavailable")
        writes = total.get("cache_write_input_tokens")
        if type(writes) is not int or writes < 0 or writes:
            self._problem("cache-write duration/count unavailable")
        if self._model == "unavailable":
            self._problem("model setting unavailable")
        if any(delta.values()) or not self.usage:
            rows = list(self.usage)
            index = next((i for i, row in enumerate(rows) if row.model == self._model), None)
            old = rows[index] if index is not None else Usage(self.session_id, self._model, 0, 0, 0)
            row = replace(old, input=old.input + delta["input_tokens"],
                          cached_input=old.cached_input + delta["cached_input_tokens"],
                          output=old.output + delta["output_tokens"],
                          cache_write_30m=0 if writes == 0 else None,
                          cache_write_12h=0 if writes == 0 else None,
                          unavailable=self.unavailable)
            if index is None:
                rows.append(row)
            else:
                rows[index] = row
            self.usage = tuple(rows)
        return replace(state, context_tokens=context,
                       spend=Spend(max(state.spend.tokens, self._tokens), state.spend.dollars))

    def _settings(self) -> None:
        self.models = tuple(dict.fromkeys(self.models + (self._model,)))
        self.efforts = tuple(dict.fromkeys(self.efforts + (self._effort,)))
