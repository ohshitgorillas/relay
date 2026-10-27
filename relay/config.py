"""Loads the Relay config file and applies CLI overrides into one frozen Config."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    token_budget: int | None
    dollar_budget: float | None
    context_limit: int
    hard_ceiling: int
    poll_seconds: float
    lead_command: list[str]
    recut_command: list[str]
    ping_command: list[str]
    state_root: Path


def load_config(path: Path | None, overrides: dict[str, object]) -> Config:
    raise NotImplementedError
