"""Batch-3 adapter disabling, using a synthetic hooks.json fixture."""

import json
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from relay.backends.codex import CodexBackend
from relay.codex_launch import adapter_args
from relay.config import Config


@pytest.fixture
def hooks_home(tmp_path: Path) -> Path:
    home = tmp_path / 'codex "native" λ'
    home.mkdir()
    fixture = Path(__file__).parent / "fixtures/codex-native/hooks.json"
    (home / "hooks.json").write_bytes(fixture.read_bytes())
    return home


def _expected_states(home: Path) -> dict[str, dict[str, bool]]:
    source = home / "hooks.json"
    return {
        f"{source}:pre_tool_use:0:1": {"enabled": False},
        f"{source}:pre_tool_use:1:0": {"enabled": False},
        f"{source}:user_prompt_submit:0:0": {"enabled": False},
    }


def test_adapter_keys_match_source_and_leave_other_hooks_alone(hooks_home: Path) -> None:
    # Breaks when event names or original indices change, or unrelated hooks are disabled.
    source = hooks_home / "hooks.json"
    before = source.read_bytes()

    args = adapter_args(hooks_home)

    assert len(args) == 2
    assert args[0] == "-c"
    assert tomllib.loads(args[1]) == {"hooks": {"state": _expected_states(hooks_home)}}
    assert source.read_bytes() == before


def test_missing_hooks_file_gives_no_args(tmp_path: Path) -> None:
    # Breaks when an unconfigured Codex home requires a hook file or gains overrides.
    assert adapter_args(tmp_path / "missing-home") == []


def test_hooks_without_adapter_give_no_args(hooks_home: Path) -> None:
    # Breaks when a file containing only native hooks changes the launch.
    path = hooks_home / "hooks.json"
    data = json.loads(path.read_text())
    path.write_text(json.dumps({"hooks": {"SessionStart": data["hooks"]["SessionStart"]}}))

    assert adapter_args(hooks_home) == []


def test_inherited_codex_home_selects_hooks_file(
    hooks_home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when adapter selection ignores the run's inherited CODEX_HOME.
    monkeypatch.setenv("CODEX_HOME", str(hooks_home))

    args = adapter_args()

    assert tomllib.loads(args[1])["hooks"]["state"] == _expected_states(hooks_home)


def test_default_codex_home_selects_user_hooks(
    hooks_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when an unset CODEX_HOME stops defaulting to ~/.codex/hooks.json.
    user = tmp_path / "synthetic-user"
    home = user / ".codex"
    home.mkdir(parents=True)
    (home / "hooks.json").write_bytes((hooks_home / "hooks.json").read_bytes())
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: user))

    args = adapter_args()

    assert tomllib.loads(args[1])["hooks"]["state"] == _expected_states(home)


@pytest.mark.parametrize("role,filename", [
    ("lead", "lead"),
    ("recut", "divvyer"),
    ("research", "researcher"),
    ("design", "architect"),
    ("ask", "researcher"),
])
def test_every_codex_launch_disables_adapter_before_prompt(
    hooks_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    fake_cfg: Config, role: str, filename: str,
) -> None:
    # Breaks when any fresh or resumed role omits the override or puts it after the prompt.
    agents = hooks_home / "agents"
    agents.mkdir()
    instructions = "Synthetic role instructions."
    (agents / f"{filename}.toml").write_text(
        f"developer_instructions = {json.dumps(instructions)}\n"
    )
    monkeypatch.setenv("CODEX_HOME", str(hooks_home))
    cfg = replace(fake_cfg, backend="codex", research_command=["codex", "--resume", "synthetic-thread"])

    argv = CodexBackend().argv(role, cfg, tmp_path, tmp_path / "out")

    overrides = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-c"]
    assert len(overrides) == 1
    assert tomllib.loads(overrides[0])["hooks"]["state"] == _expected_states(hooks_home)
    assert argv.index("-c") < len(argv) - 2
    assert argv[-1] == ("-" if role == "ask" else instructions)
    assert "--dangerously-bypass-approvals-and-sandbox" in argv
