"""Red tests for Relay's errors and config (design: Modules `relay/errors.py`, `relay/config.py`; Order 3)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from relay.config import Config, load_config
from relay.errors import (
    ConfigError,
    ExitCode,
    LockedError,
    QueueFormatError,
    RelayError,
)

DEFAULT_LEAD = [
    "claude", "-p", "--output-format", "stream-json", "--verbose",
    "--permission-mode", "bypassPermissions",
]


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake home directory, so `~` never reaches the real one."""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    return path


def _toml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


# Behavior 1: `relay/errors.py`: the one place for every Relay error type and process exit code.


def test_bad_config_raises_config_error_with_usage_exit(tmp_path: Path, home: Path) -> None:
    path = _toml(tmp_path, "context_limit = [unclosed\n")
    with pytest.raises(ConfigError) as excinfo:
        load_config(path, {})
    assert isinstance(excinfo.value, RelayError)
    assert excinfo.value.exit_code == 2
    assert excinfo.value.exit_code == ExitCode.USAGE


def test_error_types_carry_documented_exit_codes() -> None:
    assert issubclass(RelayError, Exception)
    assert RelayError.exit_code == 1
    assert RelayError("x").exit_code == 1
    for cls in (ConfigError, QueueFormatError, LockedError):
        assert issubclass(cls, RelayError)
        assert cls.exit_code == 2
        assert cls("x").exit_code == 2


def test_exit_codes_have_documented_values() -> None:
    assert ExitCode.QUEUE_EMPTY == 0
    assert ExitCode.ERROR == 1
    assert ExitCode.USAGE == 2
    assert ExitCode.BUDGET == 3
    assert ExitCode.STOP_FILE == 4
    assert ExitCode.FAILED_TWICE == 5
    assert ExitCode.INTERRUPTED == 130


# Behavior 2: `relay/config.py`: loads `~/.config/relay/config.toml` and applies CLI overrides,
# giving one frozen `Config`.


def test_empty_config_gives_documented_defaults(tmp_path: Path, home: Path) -> None:
    cfg = load_config(_toml(tmp_path, ""), {})
    assert isinstance(cfg, Config)
    assert cfg.token_budget is None
    assert cfg.dollar_budget is None
    assert cfg.context_limit == 100_000
    assert cfg.hard_ceiling == 200_000
    assert cfg.poll_seconds == 30
    assert cfg.lead_command == DEFAULT_LEAD
    assert cfg.recut_command == DEFAULT_LEAD + ["--agent", "divvyer"]
    assert cfg.ping_command in (
        ["~/.local/bin/claude-ping", "{message}"],
        [str(home / ".local" / "bin" / "claude-ping"), "{message}"],
    )
    assert cfg.state_root == home / ".local" / "state" / "relay"


def test_no_path_reads_home_config_toml(home: Path) -> None:
    config_dir = home / ".config" / "relay"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("token_budget = 12345\npoll_seconds = 2.5\n")
    cfg = load_config(None, {})
    assert cfg.token_budget == 12345
    assert cfg.poll_seconds == 2.5


def test_file_values_are_loaded(tmp_path: Path, home: Path) -> None:
    path = _toml(
        tmp_path,
        "token_budget = 500000\n"
        "dollar_budget = 7.5\n"
        "context_limit = 80000\n"
        "hard_ceiling = 90000\n"
        "poll_seconds = 1.0\n"
        'lead_command = ["my-claude", "-p"]\n'
        'recut_command = ["my-recut"]\n'
        'ping_command = ["notify", "{message}"]\n'
        f'state_root = "{tmp_path / "st"}"\n',
    )
    cfg = load_config(path, {})
    assert cfg.token_budget == 500_000
    assert cfg.dollar_budget == 7.5
    assert cfg.context_limit == 80_000
    assert cfg.hard_ceiling == 90_000
    assert cfg.poll_seconds == 1.0
    assert cfg.lead_command == ["my-claude", "-p"]
    assert cfg.recut_command == ["my-recut"]
    assert cfg.ping_command == ["notify", "{message}"]
    assert cfg.state_root == tmp_path / "st"


def test_hard_ceiling_defaults_to_twice_file_context_limit(tmp_path: Path, home: Path) -> None:
    cfg = load_config(_toml(tmp_path, "context_limit = 50000\n"), {})
    assert cfg.context_limit == 50_000
    assert cfg.hard_ceiling == 100_000


def test_recut_command_defaults_to_lead_command_plus_divvyer(tmp_path: Path, home: Path) -> None:
    cfg = load_config(_toml(tmp_path, 'lead_command = ["my-claude", "-p"]\n'), {})
    assert cfg.recut_command == ["my-claude", "-p", "--agent", "divvyer"]


def test_overrides_beat_file_values(tmp_path: Path, home: Path) -> None:
    path = _toml(tmp_path, "token_budget = 1000\ndollar_budget = 2.0\ncontext_limit = 40000\n")
    cfg = load_config(path, {"token_budget": 9000, "dollar_budget": 3.5, "context_limit": 70000})
    assert cfg.token_budget == 9000
    assert cfg.dollar_budget == 3.5
    assert cfg.context_limit == 70_000


def test_override_context_limit_moves_default_hard_ceiling(tmp_path: Path, home: Path) -> None:
    cfg = load_config(_toml(tmp_path, ""), {"context_limit": 60000})
    assert cfg.context_limit == 60_000
    assert cfg.hard_ceiling == 120_000


def test_override_leaves_other_values_alone(tmp_path: Path, home: Path) -> None:
    path = _toml(tmp_path, "poll_seconds = 4.0\n")
    cfg = load_config(path, {"token_budget": 10})
    assert cfg.token_budget == 10
    assert cfg.poll_seconds == 4.0
    assert cfg.context_limit == 100_000


def test_loaded_config_is_frozen(tmp_path: Path, home: Path) -> None:
    cfg = load_config(_toml(tmp_path, ""), {})
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.context_limit = 1  # type: ignore[misc]


def test_wrong_type_in_file_raises_config_error(tmp_path: Path, home: Path) -> None:
    path = _toml(tmp_path, 'context_limit = "lots"\n')
    with pytest.raises(ConfigError):
        load_config(path, {})


def test_bad_cli_override_raises_config_error(tmp_path: Path, home: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(_toml(tmp_path, ""), {"token_budget": "many"})
