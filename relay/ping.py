"""The one place an owner ping is worded and sent."""

from pathlib import Path

from relay.config import Config


def ping(cfg: Config, message: str) -> None:
    raise NotImplementedError


def needs_owner(cfg: Config, queue: Path, sid: str, question: str) -> None:
    raise NotImplementedError


def stopped(cfg: Config, queue: Path, reason: str, detail: str) -> None:
    raise NotImplementedError
