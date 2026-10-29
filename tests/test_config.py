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
from tests.conftest import DEFAULT_CHECK_OUTSIDE, STANDING_APPROVAL

DEFAULT_LEAD = [
    "claude", "-p", "--output-format", "stream-json", "--verbose", "--agent", "lead",
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
        ["~/.local/bin/claude-ping", "relay", "{message}"],
        [str(home / ".local" / "bin" / "claude-ping"), "relay", "{message}"],
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
    # relay-check-design.md, Modules `relay/config.py`: ConfigError unless
    # context_limit < idle_ceiling < hard_ceiling, so these ceilings name an idle_ceiling
    # between them (the 13/10 default, 104000, would lie above hard_ceiling).
    path = _toml(
        tmp_path,
        "token_budget = 500000\n"
        "dollar_budget = 7.5\n"
        "context_limit = 80000\n"
        "idle_ceiling = 85000\n"
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
    assert cfg.idle_ceiling == 85_000
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


def test_backend_defaults_preserve_claude_commands(tmp_path: Path, home: Path) -> None:
    # Breaks when backend selection changes legacy default commands.
    cfg = load_config(_toml(tmp_path, ""), {})
    assert cfg.backend == "claude"
    assert cfg.lead_command == DEFAULT_LEAD
    assert cfg.recut_command == DEFAULT_LEAD + ["--agent", "divvyer"]
    try:
        explicit = load_config(_toml(tmp_path, 'backend = "claude"\n'), {})
    except ConfigError as exc:
        assert False, str(exc)
    assert explicit == cfg


def test_generic_requires_explicit_command(tmp_path: Path, home: Path) -> None:
    # Breaks when generic silently launches the default Claude command.
    with pytest.raises(ConfigError):
        load_config(_toml(tmp_path, 'backend = "generic"\n'), {})
    try:
        cfg = load_config(_toml(tmp_path, 'backend = "generic"\nlead_command = ["worker"]\n'), {})
    except ConfigError as exc:
        assert False, str(exc)
    assert cfg.lead_command == ["worker"]


def test_generic_recut_defaults_without_claude_flags(tmp_path: Path, home: Path) -> None:
    # Breaks when generic recut inherits Claude's agent flag.
    try:
        cfg = load_config(_toml(tmp_path, 'backend = "generic"\nlead_command = ["worker", "--plain"]\n'), {})
    except ConfigError as exc:
        assert False, str(exc)
    assert cfg.backend == "generic"
    assert cfg.lead_command == ["worker", "--plain"]
    assert cfg.recut_command == ["worker", "--plain"]


def test_backend_override_selects_generic_defaults(tmp_path: Path, home: Path) -> None:
    # Breaks when CLI backend selection is ignored during command defaulting.
    try:
        cfg = load_config(_toml(tmp_path, 'backend = "claude"\nlead_command = ["worker"]\n'), {"backend": "generic"})
    except ConfigError as exc:
        assert False, str(exc)
    assert cfg.backend == "generic"
    assert cfg.recut_command == ["worker"]


@pytest.mark.parametrize("backend", ["unknown", 123])
def test_invalid_backend_is_config_error(tmp_path: Path, home: Path, backend: object) -> None:
    # Breaks when invalid backend selections survive config validation.
    with pytest.raises(ConfigError):
        load_config(_toml(tmp_path, ""), {"backend": backend})
    try:
        cfg = load_config(_toml(tmp_path, ""), {"backend": "claude"})
    except ConfigError as exc:
        assert False, str(exc)
    assert cfg.backend == "claude"
# The check keys (design: relay-check-design.md, Modules `relay/config.py`; Order 3).
# Behavior: ConfigError unless context_limit < idle_ceiling < hard_ceiling.

CEILINGS = "context_limit = 100000\nhard_ceiling = 200000\n"


def _load_ok(path: Path, overrides: dict[str, object]) -> Config:
    """load_config on a config the design accepts: a ConfigError here is a failed claim."""
    try:
        return load_config(path, overrides)
    except ConfigError as exc:
        raise AssertionError(f"documented config rejected: {exc}") from exc


def test_idle_ceiling_defaults_to_thirteen_tenths_of_context_limit(
    tmp_path: Path, home: Path
) -> None:
    assert _load_ok(_toml(tmp_path, ""), {}).idle_ceiling == 130_000
    cfg = _load_ok(_toml(tmp_path, "context_limit = 50001\n"), {})
    assert cfg.idle_ceiling == 65_001
    cfg = _load_ok(_toml(tmp_path, ""), {"context_limit": 60000})
    assert cfg.idle_ceiling == 78_000


def test_idle_ceiling_between_context_limit_and_hard_ceiling_is_loaded(
    tmp_path: Path, home: Path
) -> None:
    path = _toml(tmp_path, CEILINGS + "idle_ceiling = 100001\n")
    assert _load_ok(path, {}).idle_ceiling == 100_001
    path = _toml(tmp_path, CEILINGS + "idle_ceiling = 199999\n")
    assert _load_ok(path, {}).idle_ceiling == 199_999


@pytest.mark.parametrize("idle", [99_999, 100_000, 200_000, 250_000])
def test_idle_ceiling_outside_context_limit_and_hard_ceiling_raises_config_error(
    tmp_path: Path, home: Path, idle: int
) -> None:
    assert _load_ok(_toml(tmp_path, CEILINGS + "idle_ceiling = 150000\n"), {}).idle_ceiling == 150_000
    path = _toml(tmp_path, CEILINGS + f"idle_ceiling = {idle}\n")
    with pytest.raises(ConfigError):
        load_config(path, {})


@pytest.mark.parametrize("idle", [100_000, 200_000])
def test_idle_ceiling_override_at_a_bound_raises_config_error(
    tmp_path: Path, home: Path, idle: int
) -> None:
    path = _toml(tmp_path, "")
    assert _load_ok(path, {"idle_ceiling": 150_000}).idle_ceiling == 150_000
    with pytest.raises(ConfigError):
        load_config(path, {"idle_ceiling": idle})


def test_default_idle_ceiling_is_capped_one_below_hard_ceiling(
    tmp_path: Path, home: Path
) -> None:
    # relay-check-design.md, `relay/config.py` (extended): the default is
    # min(context_limit * 13 // 10, hard_ceiling - 1); with context_limit 100000,
    # hard_ceiling 120000 and no idle_ceiling, idle_ceiling is 119999 and the config loads.
    path = _toml(tmp_path, "context_limit = 100000\nhard_ceiling = 120000\n")
    assert _load_ok(path, {}).idle_ceiling == 119_999


# Behavior: seconds per check command.


def test_check_timeout_defaults_to_1800_seconds_and_is_read_from_the_file(
    tmp_path: Path, home: Path
) -> None:
    assert _load_ok(_toml(tmp_path, ""), {}).check_timeout == 1800
    assert _load_ok(_toml(tmp_path, "check_timeout = 42.5\n"), {}).check_timeout == 42.5


def test_check_timeout_override_beats_the_file(tmp_path: Path, home: Path) -> None:
    path = _toml(tmp_path, "check_timeout = 42.5\n")
    assert _load_ok(path, {"check_timeout": 7.25}).check_timeout == 7.25


def test_check_timeout_of_the_wrong_type_raises_config_error(tmp_path: Path, home: Path) -> None:
    assert _load_ok(_toml(tmp_path, "check_timeout = 60.0\n"), {}).check_timeout == 60.0
    with pytest.raises(ConfigError):
        load_config(_toml(tmp_path, 'check_timeout = "half an hour"\n'), {})


# Behavior: regexes; default below; ConfigError on a pattern re.compile rejects.


def test_check_outside_defaults_to_the_documented_patterns_and_is_read_from_the_file(
    tmp_path: Path, home: Path
) -> None:
    assert _load_ok(_toml(tmp_path, ""), {}).check_outside == DEFAULT_CHECK_OUTSIDE
    path = _toml(tmp_path, "check_outside = ['quota exceeded', '(?i)rate limit']\n")
    assert _load_ok(path, {}).check_outside == ["quota exceeded", "(?i)rate limit"]


@pytest.mark.parametrize("pattern", ["(unclosed", "[a-", "*leading"])
def test_check_outside_pattern_re_compile_rejects_raises_config_error(
    tmp_path: Path, home: Path, pattern: str
) -> None:
    assert _load_ok(_toml(tmp_path, "check_outside = ['fine']\n"), {}).check_outside == ["fine"]
    path = _toml(tmp_path, f"check_outside = ['fine', '{pattern}']\n")
    with pytest.raises(ConfigError):
        load_config(path, {})


def test_check_outside_bad_pattern_override_raises_config_error(
    tmp_path: Path, home: Path
) -> None:
    path = _toml(tmp_path, "")
    assert _load_ok(path, {"check_outside": ["fine"]}).check_outside == ["fine"]
    with pytest.raises(ConfigError):
        load_config(path, {"check_outside": ["(unclosed"]})


# Behavior: All three keys join `_KEYS`.


def test_all_three_check_keys_are_read_from_the_file(tmp_path: Path, home: Path) -> None:
    path = _toml(
        tmp_path,
        "idle_ceiling = 150000\ncheck_timeout = 90.0\ncheck_outside = ['offline']\n",
    )
    cfg = _load_ok(path, {})
    assert cfg.idle_ceiling == 150_000
    assert cfg.check_timeout == 90.0
    assert cfg.check_outside == ["offline"]


def test_all_three_check_keys_take_overrides_over_the_file(tmp_path: Path, home: Path) -> None:
    path = _toml(
        tmp_path,
        "idle_ceiling = 150000\ncheck_timeout = 90.0\ncheck_outside = ['offline']\n",
    )
    cfg = _load_ok(
        path, {"idle_ceiling": 160000, "check_timeout": 12.0, "check_outside": ["down"]}
    )
    assert cfg.idle_ceiling == 160_000
    assert cfg.check_timeout == 12.0
    assert cfg.check_outside == ["down"]


# The research keys (design: relay-research-design.md, Modules `relay/config.py` (extended);
# Order 3).

RESEARCH_TAIL = ["--agent", "researcher", "--model", "opus[1m]"]
RESEARCH_KEYS = (
    'research_command = ["my-research", "-p"]\nmap_max_lines = 40\nmap_max_chars = 3000\n'
)


def _direct(**fields: object) -> Config:
    """A `Config` built directly, its required fields at the documented defaults."""
    base: dict[str, object] = {
        "token_budget": None,
        "dollar_budget": None,
        "context_limit": 100_000,
        "hard_ceiling": 200_000,
        "poll_seconds": 30,
        "lead_command": ["my-claude", "-p"],
        "recut_command": ["my-recut"],
        "ping_command": ["notify", "{message}"],
        "state_root": Path("/nowhere/state"),
        "idle_ceiling": 130_000,
    }
    base.update(fields)
    return Config(**base)  # type: ignore[arg-type]


# Behavior 4: All three keys join `_KEYS`.


def test_all_three_research_keys_are_read_from_the_file(tmp_path: Path, home: Path) -> None:
    cfg = _load_ok(_toml(tmp_path, RESEARCH_KEYS), {})
    assert cfg.research_command == ["my-research", "-p"]
    assert cfg.map_max_lines == 40
    assert cfg.map_max_chars == 3000


def test_all_three_research_keys_take_overrides_over_the_file(
    tmp_path: Path, home: Path
) -> None:
    cfg = _load_ok(
        _toml(tmp_path, RESEARCH_KEYS),
        {"research_command": ["other-research"], "map_max_lines": 7, "map_max_chars": 900},
    )
    assert cfg.research_command == ["other-research"]
    assert cfg.map_max_lines == 7
    assert cfg.map_max_chars == 900


def test_research_overrides_apply_over_an_empty_file(tmp_path: Path, home: Path) -> None:
    cfg = _load_ok(
        _toml(tmp_path, ""),
        {"research_command": ["other-research"], "map_max_lines": 7, "map_max_chars": 900},
    )
    assert cfg.research_command == ["other-research"]
    assert cfg.map_max_lines == 7
    assert cfg.map_max_chars == 900


def test_research_keys_leave_the_other_keys_alone(tmp_path: Path, home: Path) -> None:
    cfg = _load_ok(_toml(tmp_path, RESEARCH_KEYS + "poll_seconds = 4.0\n"), {})
    assert cfg.poll_seconds == 4.0
    assert cfg.lead_command == DEFAULT_LEAD
    assert cfg.recut_command == DEFAULT_LEAD + ["--agent", "divvyer"]
    assert cfg.map_max_lines == 40


# Behavior 5: Research command, map caps and their defaults.


def test_empty_config_gives_the_documented_research_defaults(tmp_path: Path, home: Path) -> None:
    cfg = _load_ok(_toml(tmp_path, ""), {})
    assert cfg.research_command == DEFAULT_LEAD + RESEARCH_TAIL
    assert cfg.map_max_lines == 150
    assert cfg.map_max_chars == 12_000


def test_research_command_defaults_to_the_file_lead_command_plus_researcher(
    tmp_path: Path, home: Path
) -> None:
    cfg = _load_ok(_toml(tmp_path, 'lead_command = ["my-claude", "-p"]\n'), {})
    assert cfg.research_command == ["my-claude", "-p"] + RESEARCH_TAIL


def test_research_command_defaults_to_an_overridden_lead_command_plus_researcher(
    tmp_path: Path, home: Path
) -> None:
    cfg = _load_ok(
        _toml(tmp_path, 'lead_command = ["my-claude", "-p"]\n'),
        {"lead_command": ["cli-claude"]},
    )
    assert cfg.research_command == ["cli-claude"] + RESEARCH_TAIL


def test_research_command_from_the_file_is_not_given_the_researcher_tail(
    tmp_path: Path, home: Path
) -> None:
    path = _toml(
        tmp_path, 'lead_command = ["my-claude"]\nresearch_command = ["my-research"]\n'
    )
    assert _load_ok(path, {}).research_command == ["my-research"]


def test_config_built_directly_defaults_research_command_from_its_lead_command() -> None:
    cfg = _direct()
    assert cfg.research_command == ["my-claude", "-p"] + RESEARCH_TAIL
    assert cfg.map_max_lines == 150
    assert cfg.map_max_chars == 12_000


def test_config_built_directly_defaults_only_a_research_command_it_was_not_given() -> None:
    assert _direct(lead_command=["cli-claude"]).research_command == ["cli-claude"] + RESEARCH_TAIL
    assert _direct(research_command=["mine"]).research_command == ["mine"]


@pytest.mark.parametrize("key", ["map_max_lines", "map_max_chars"])
@pytest.mark.parametrize("value", ["0", "-1", '"many"', "2.5"])
def test_a_map_cap_in_the_file_that_is_not_a_positive_integer_raises_config_error(
    tmp_path: Path, home: Path, key: str, value: str
) -> None:
    assert getattr(_load_ok(_toml(tmp_path, f"{key} = 1\n"), {}), key) == 1
    with pytest.raises(ConfigError):
        load_config(_toml(tmp_path, f"{key} = {value}\n"), {})


@pytest.mark.parametrize("key", ["map_max_lines", "map_max_chars"])
@pytest.mark.parametrize("value", [0, -1, "many", 2.5])
def test_a_map_cap_override_that_is_not_a_positive_integer_raises_config_error(
    tmp_path: Path, home: Path, key: str, value: object
) -> None:
    path = _toml(tmp_path, "")
    assert getattr(_load_ok(path, {key: 1}), key) == 1
    with pytest.raises(ConfigError):
        load_config(path, {key: value})


def test_research_command_of_the_wrong_type_raises_config_error(
    tmp_path: Path, home: Path
) -> None:
    assert _load_ok(_toml(tmp_path, 'research_command = ["r"]\n'), {}).research_command == ["r"]
    with pytest.raises(ConfigError):
        load_config(_toml(tmp_path, 'research_command = "my-research"\n'), {})


# The ladder keys (design: relay-ladder-design.md, Modules `relay/config.py` (extended);
# Order 4).

ARCHITECT_TAIL = ["--agent", "architect"]
LADDER_KEYS = (
    'design_command = ["my-architect", "-p"]\n'
    "section_dollar_cap = 12.5\n"
    'design_approval = "Approved, in my own words."\n'
)


# Behavior 2: __post_init__ and load_config as research_command's is.


def test_design_command_defaults_to_the_file_lead_command_plus_architect_unless_the_file_names_one(
    tmp_path: Path, home: Path
) -> None:
    assert _load_ok(_toml(tmp_path, ""), {}).design_command == DEFAULT_LEAD + ARCHITECT_TAIL
    cfg = _load_ok(_toml(tmp_path, 'lead_command = ["my-claude", "-p"]\n'), {})
    assert cfg.design_command == ["my-claude", "-p", "--agent", "architect"]
    path = _toml(tmp_path, 'lead_command = ["my-claude"]\ndesign_command = ["my-architect"]\n')
    assert _load_ok(path, {}).design_command == ["my-architect"]


def test_design_command_defaults_to_an_overridden_lead_command_plus_architect_unless_one_is_given(
    tmp_path: Path, home: Path
) -> None:
    path = _toml(tmp_path, 'lead_command = ["my-claude", "-p"]\n')
    cfg = _load_ok(path, {"lead_command": ["cli-claude"]})
    assert cfg.design_command == ["cli-claude", "--agent", "architect"]
    cfg = _load_ok(path, {"lead_command": ["cli-claude"], "design_command": ["cli-architect"]})
    assert cfg.design_command == ["cli-architect"]


def test_config_built_directly_defaults_only_a_design_command_it_was_not_given(
    tmp_path: Path, home: Path
) -> None:
    assert _direct().design_command == ["my-claude", "-p", "--agent", "architect"]
    assert _direct(lead_command=["cli-claude"]).design_command == [
        "cli-claude",
        "--agent",
        "architect",
    ]
    assert _direct(design_command=["mine"]).design_command == ["mine"]
    # load_config builds its Config the same way: a design_command it reads is kept as given.
    path = _toml(tmp_path, 'design_command = ["mine"]\n')
    assert _load_ok(path, {}).design_command == ["mine"]


def test_design_command_of_the_wrong_type_raises_config_error(tmp_path: Path, home: Path) -> None:
    assert _load_ok(_toml(tmp_path, 'design_command = ["a"]\n'), {}).design_command == ["a"]
    with pytest.raises(ConfigError):
        load_config(_toml(tmp_path, 'design_command = "my-architect"\n'), {})


# Behavior 3: positive; None is no cap.


def test_section_dollar_cap_is_none_by_default_and_a_positive_one_is_loaded(
    tmp_path: Path, home: Path
) -> None:
    assert _direct().section_dollar_cap is None
    assert _load_ok(_toml(tmp_path, ""), {}).section_dollar_cap is None
    path = _toml(tmp_path, "section_dollar_cap = 0.25\n")
    assert _load_ok(path, {}).section_dollar_cap == 0.25


def test_a_positive_section_dollar_cap_override_is_loaded(tmp_path: Path, home: Path) -> None:
    path = _toml(tmp_path, "")
    assert _load_ok(path, {"section_dollar_cap": 40.0}).section_dollar_cap == 40.0


@pytest.mark.parametrize("value", ["0.0", "-1.5", '"many"'])
def test_a_section_dollar_cap_in_the_file_that_is_not_positive_raises_config_error(
    tmp_path: Path, home: Path, value: str
) -> None:
    assert _load_ok(_toml(tmp_path, "section_dollar_cap = 2.5\n"), {}).section_dollar_cap == 2.5
    with pytest.raises(ConfigError):
        load_config(_toml(tmp_path, f"section_dollar_cap = {value}\n"), {})


@pytest.mark.parametrize("value", [0.0, -1.5, "many"])
def test_a_section_dollar_cap_override_that_is_not_positive_raises_config_error(
    tmp_path: Path, home: Path, value: object
) -> None:
    path = _toml(tmp_path, "")
    assert _load_ok(path, {"section_dollar_cap": 2.5}).section_dollar_cap == 2.5
    with pytest.raises(ConfigError):
        load_config(path, {"section_dollar_cap": value})


# Behavior 4: the owner's words Relay quotes on the architect's approve: line.


def test_design_approval_defaults_to_the_owners_standing_words(tmp_path: Path, home: Path) -> None:
    assert _direct().design_approval == STANDING_APPROVAL
    assert _load_ok(_toml(tmp_path, ""), {}).design_approval == STANDING_APPROVAL
    path = _toml(tmp_path, 'design_approval = "Approved."\n')
    assert _load_ok(path, {}).design_approval == "Approved."


def test_design_approval_of_the_wrong_type_raises_config_error(tmp_path: Path, home: Path) -> None:
    assert _load_ok(_toml(tmp_path, 'design_approval = "Yes."\n'), {}).design_approval == "Yes."
    with pytest.raises(ConfigError):
        load_config(_toml(tmp_path, "design_approval = 5\n"), {})


# Behavior 5: All three keys join `_KEYS`.


def test_all_three_ladder_keys_are_read_from_the_file(tmp_path: Path, home: Path) -> None:
    cfg = _load_ok(_toml(tmp_path, LADDER_KEYS), {})
    assert cfg.design_command == ["my-architect", "-p"]
    assert cfg.section_dollar_cap == 12.5
    assert cfg.design_approval == "Approved, in my own words."


def test_all_three_ladder_keys_take_overrides_over_the_file(tmp_path: Path, home: Path) -> None:
    cfg = _load_ok(
        _toml(tmp_path, LADDER_KEYS),
        {"design_command": ["other-architect"], "section_dollar_cap": 3.0, "design_approval": "Go."},
    )
    assert cfg.design_command == ["other-architect"]
    assert cfg.section_dollar_cap == 3.0
    assert cfg.design_approval == "Go."


def test_ladder_overrides_apply_over_an_empty_file(tmp_path: Path, home: Path) -> None:
    cfg = _load_ok(
        _toml(tmp_path, ""),
        {"design_command": ["other-architect"], "section_dollar_cap": 3.0, "design_approval": "Go."},
    )
    assert cfg.design_command == ["other-architect"]
    assert cfg.section_dollar_cap == 3.0
    assert cfg.design_approval == "Go."


def test_ladder_keys_leave_the_other_keys_alone(tmp_path: Path, home: Path) -> None:
    cfg = _load_ok(_toml(tmp_path, LADDER_KEYS + "poll_seconds = 4.0\n"), {})
    assert cfg.poll_seconds == 4.0
    assert cfg.lead_command == DEFAULT_LEAD
    assert cfg.research_command == DEFAULT_LEAD + RESEARCH_TAIL
    assert cfg.section_dollar_cap == 12.5
