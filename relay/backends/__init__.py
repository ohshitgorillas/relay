"""Backend selection and historical run replay."""

from pathlib import Path

from relay.backends.base import Backend
from relay.stream import StreamState


def get_backend(name: str) -> Backend:
    raise NotImplementedError


def replay(log: Path) -> StreamState:
    raise NotImplementedError
