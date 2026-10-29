"""Codex rollout reader interface."""

from pathlib import Path

from relay.stream import StreamState


class SessionReader:
    def __init__(self, home: Path, session_id: str):
        raise NotImplementedError

    def poll(self, state: StreamState) -> StreamState:
        raise NotImplementedError
