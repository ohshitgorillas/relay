"""Loads the Relay config file and applies CLI overrides into one frozen Config."""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from relay.errors import ConfigError

_DEFAULT_LEAD = [
    "claude", "-p", "--output-format", "stream-json", "--verbose", "--agent", "lead",
    "--permission-mode", "bypassPermissions",
]
_DEFAULT_CHECK_OUTSIDE = [
    "command not found",
    "(?i)credit balance",
    "(?i)api[ _-]?key",
    "(?i)could not resolve host",
    "(?i)name resolution",
    "(?i)network is unreachable",
    "(?i)connection (refused|reset|timed out)",
]


def _default_idle_ceiling(context_limit: int, hard_ceiling: int) -> int:
    return min(context_limit * 13 // 10, hard_ceiling - 1)


_STANDING_APPROVAL = (
    "I am sick and tired of this paperwork bullshit make it stop for the 5th fucking time"
)


@dataclass(frozen=True)
class Config:
    token_budget: int | None
    dollar_budget: float | None
    context_limit: int
    hard_ceiling: int
    poll_seconds: float
    lead_command: list[str]
    ping_command: list[str]
    state_root: Path
    idle_ceiling: int = 0  # 0 asks for the default, 13/10 of context_limit
    check_timeout: float = 1800
    check_outside: list[str] = field(default_factory=lambda: list(_DEFAULT_CHECK_OUTSIDE))
    recut_command: list[str] = field(default_factory=list)  # empty asks for the default
    research_command: list[str] = field(default_factory=list)  # empty asks for the default
    map_max_lines: int = 150
    map_max_chars: int = 12_000
    design_command: list[str] = field(default_factory=list)  # empty asks for the default
    section_dollar_cap: float | None = None  # positive; None is no cap
    design_approval: str = _STANDING_APPROVAL  # quoted on the architect's approve: line

    def __post_init__(self) -> None:
        if not self.design_command:
            object.__setattr__(self, "design_command", [*self.lead_command, "--agent", "architect"])
        if self.idle_ceiling == 0:
            object.__setattr__(
                self, "idle_ceiling", _default_idle_ceiling(self.context_limit, self.hard_ceiling)
            )
        if not self.recut_command:
            object.__setattr__(self, "recut_command", [*self.lead_command, "--agent", "divvyer"])
        if not self.research_command:
            object.__setattr__(
                self,
                "research_command",
                [*self.lead_command, "--agent", "researcher", "--model", "opus[1m]"],
            )


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
        "idle_ceiling",
        "check_timeout",
        "check_outside",
        "research_command",
        "map_max_lines",
        "map_max_chars",
        "design_command",
        "section_dollar_cap",
        "design_approval",
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


def _string(merged: dict[str, object], key: str, default: str | None) -> str | None:
    value = merged.get(key, default)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"config value {key!r} must be a non-empty string: {value!r}")
    return value


def _command(merged: dict[str, object], key: str, default: list[str]) -> list[str]:
    value = merged.get(key, default)
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"config value {key!r} must be a non-empty list of strings: {value!r}")
    return list(value)


def _patterns(merged: dict[str, object], key: str, default: list[str]) -> list[str]:
    value = merged.get(key, default)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"config value {key!r} must be a list of strings: {value!r}")
    for pattern in value:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError(f"config value {key!r} has a bad pattern {pattern!r}: {exc}") from exc
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
    idle_ceiling = _int(merged, "idle_ceiling", None) or 0
    check_timeout = _number(merged, "check_timeout", Config.check_timeout)
    assert check_timeout is not None
    poll_seconds = _number(merged, "poll_seconds", 30)
    assert poll_seconds is not None
    lead_command = _command(merged, "lead_command", list(_DEFAULT_LEAD))

    state_value = _string(merged, "state_root", None)
    state_root = (
        home / ".local" / "state" / "relay" if state_value is None else Path(state_value).expanduser()
    )

    map_max_lines = _int(merged, "map_max_lines", Config.map_max_lines)
    map_max_chars = _int(merged, "map_max_chars", Config.map_max_chars)
    assert map_max_lines is not None and map_max_chars is not None

    approval = _string(merged, "design_approval", _STANDING_APPROVAL)
    assert approval is not None

    cfg = Config(
        token_budget=_int(merged, "token_budget", None),
        dollar_budget=_number(merged, "dollar_budget", None),
        context_limit=context_limit,
        hard_ceiling=hard_ceiling,
        poll_seconds=poll_seconds,
        lead_command=lead_command,
        recut_command=(
            _command(merged, "recut_command", []) if "recut_command" in merged else []
        ),
        ping_command=_command(
            merged, "ping_command", [str(home / ".local" / "bin" / "claude-ping"), "relay", "{message}"]
        ),
        state_root=state_root,
        idle_ceiling=idle_ceiling,
        check_timeout=check_timeout,
        check_outside=_patterns(merged, "check_outside", list(_DEFAULT_CHECK_OUTSIDE)),
        research_command=(
            _command(merged, "research_command", []) if "research_command" in merged else []
        ),
        map_max_lines=map_max_lines,
        map_max_chars=map_max_chars,
        design_command=(
            _command(merged, "design_command", []) if "design_command" in merged else []
        ),
        section_dollar_cap=_number(merged, "section_dollar_cap", None),
        design_approval=approval,
    )
    if not cfg.context_limit < cfg.idle_ceiling < cfg.hard_ceiling:
        raise ConfigError(
            f"idle_ceiling ({cfg.idle_ceiling}) must lie between context_limit "
            f"({cfg.context_limit}) and hard_ceiling ({cfg.hard_ceiling})"
        )
    return cfg
