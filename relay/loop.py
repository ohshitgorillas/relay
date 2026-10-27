"""The state machine for one `relay go`."""

from pathlib import Path

from relay.config import Config


def run(queue: Path, cfg: Config) -> int:
    raise NotImplementedError
