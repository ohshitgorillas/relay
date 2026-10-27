"""Loads the Relay config file and applies CLI overrides into one frozen Config."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from relay.errors import ConfigError

_DEFAULT_LEAD = [
    "claude", "-p", "--output-format", "stream-json", "--verbose",
    "--permission-mode", "bypassPermissions",
]
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


_KEYS = frozenset(
    {
        "token_budget",
        "dollar_budget",
        "context_limit",
        "hard_ceiling",
        "poll_seconds",
        "lead_command",
        "recut_command",
        "ping_command",
        "state_root",
    }
)


def _int(merged: dict[str, object], key: str, default: int | None) -> int | None:
    value = merged.get(key, default)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"config value {key!r} must be an integer: {value!r}")
    if value <= 0:
        raise ConfigError(f"config value {key!r} must be positive: {value!r}")
    return value


def _number(merged: dict[str, object], key: str, default: float | None) -> float | None:
    value = merged.get(key, default)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigError(f"config value {key!r} must be a number: {value!r}")
    if value <= 0:
        raise ConfigError(f"config value {key!r} must be positive: {value!r}")
    return value


def _command(merged: dict[str, object], key: str, default: list[str]) -> list[str]:
    value = merged.get(key, default)
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"config value {key!r} must be a non-empty list of strings: {value!r}")
    return list(value)


def _read(path: Path | None) -> dict[str, object]:
    if path is None:
        path = Path.home() / ".config" / "relay" / "config.toml"
        if not path.exists():
            return {}
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc


def load_config(path: Path | None, overrides: dict[str, object]) -> Config:
    data = _read(path)
    for key in (*data, *overrides):
        if key not in _KEYS:
            raise ConfigError(f"unknown config key {key!r}")
    merged = {**data, **{k: v for k, v in overrides.items() if v is not None}}
    home = Path.home()

    context_limit = _int(merged, "context_limit", 100_000)
    assert context_limit is not None
    hard_ceiling = _int(merged, "hard_ceiling", 2 * context_limit)
    assert hard_ceiling is not None
    if hard_ceiling <= context_limit:
        raise ConfigError(
            f"hard_ceiling ({hard_ceiling}) must exceed context_limit ({context_limit})"
        )
    poll_seconds = _number(merged, "poll_seconds", 30)
    assert poll_seconds is not None
    lead_command = _command(merged, "lead_command", list(_DEFAULT_LEAD))

    state_value = merged.get("state_root")
    if state_value is None:
        state_root = home / ".local" / "state" / "relay"
    elif isinstance(state_value, str) and state_value.strip():
        state_root = Path(state_value).expanduser()
    else:
        raise ConfigError(f"config value 'state_root' must be a non-empty string: {state_value!r}")

    return Config(
        token_budget=_int(merged, "token_budget", None),
        dollar_budget=_number(merged, "dollar_budget", None),
        context_limit=context_limit,
        hard_ceiling=hard_ceiling,
        poll_seconds=poll_seconds,
        lead_command=lead_command,
        recut_command=_command(merged, "recut_command", [*lead_command, "--agent", "divvyer"]),
        ping_command=_command(
            merged, "ping_command", [str(home / ".local" / "bin" / "claude-ping"), "{message}"]
        ),
        state_root=state_root,
    )
