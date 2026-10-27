"""Red tests for Relay's test helpers (design: Test helpers; Order 2).

The fixtures are requested through `request.getfixturevalue` inside each test,
so that a fixture that is not built yet fails the test rather than erroring it.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
from pathlib import Path

import pytest

from relay.config import Config
from relay.queue import parse_queue

TESTS = Path(__file__).parent
FAKE_CLAUDE = TESTS / "fakes" / "fake_claude.py"
FIXTURES = TESTS / "fixtures"

# Section ids as the divvyer writes them in each copied queue sample.
QUEUE_SAMPLES = {
    "workboard-queue.md": [
        "s1.1.1", "s1.1.2", "s1.2", "s2", "s3", "s4", "s5", "s6",
        "s7", "s8", "s9", "s10", "s11", "s12", "s13",
    ],
    "m2-rest-queue.md": ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9"],
}

SCRIPT_A = [
    json.dumps({"type": "system", "subtype": "init", "session_id": "sess-a"}),
    json.dumps({"type": "result", "subtype": "success", "result": "DONE",
                "is_error": False, "total_cost_usd": 0.5}),
]
SCRIPT_B = [
    json.dumps({"type": "system", "subtype": "init", "session_id": "sess-b"}),
    json.dumps({"type": "result", "subtype": "success", "result": "RETIRED",
                "is_error": False, "total_cost_usd": 1.25}),
]


def _write_scenario(path: Path, lines: list[str]) -> Path:
    path.write_text("".join(line + "\n" for line in lines))
    return path


def _run_fake(scenario_path: Path, prompt: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, RELAY_FAKE_SCENARIO=str(scenario_path))
    return subprocess.run(
        [sys.executable, str(FAKE_CLAUDE)],
        input=prompt, capture_output=True, text=True, env=env, timeout=30,
    )


# Behavior 1: `tests/fakes/fake_claude.py` is an executable that reads its prompt on stdin.

def test_fake_claude_runs_as_a_command_given_its_prompt_on_stdin(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    # Config commands name the fake as argv[0], so it must run with no interpreter in front.
    assert os.access(FAKE_CLAUDE, os.X_OK), "fake_claude.py lacks the executable bit"
    path = _write_scenario(tmp_path / "a.jsonl", SCRIPT_A)
    env = dict(os.environ, RELAY_FAKE_SCENARIO=str(path))
    done = subprocess.run(
        [str(FAKE_CLAUDE)],
        input="You are a lead\n", capture_output=True, text=True, env=env, timeout=30,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == SCRIPT_A
    # It stands in for the recut command (`--agent divvyer` after argv[0]) and the ping
    # command (the message after argv[0]), so it must read stdin and emit its scenario
    # whatever arguments follow.
    cfg = request.getfixturevalue("fake_cfg")
    ping_argv = [arg.replace("{message}", "s1 DONE") for arg in cfg.ping_command]
    for argv in (cfg.recut_command, ping_argv):
        done = subprocess.run(
            argv, input="recut s1\n", capture_output=True, text=True, env=env, timeout=30,
        )
        assert done.returncode == 0, (argv, done.stderr)
        assert done.stdout.splitlines() == SCRIPT_A, argv


def test_fake_claude_waits_for_its_whole_prompt_on_stdin(tmp_path: Path) -> None:
    path = _write_scenario(tmp_path / "a.jsonl", SCRIPT_A)
    env = dict(os.environ, RELAY_FAKE_SCENARIO=str(path))
    proc = subprocess.Popen(
        [sys.executable, str(FAKE_CLAUDE)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )
    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(b"You are a lead\n")
        proc.stdin.flush()
        ready, _, _ = select.select([proc.stdout], [], [], 1.0)
        assert ready == [], "fake_claude wrote or exited before its prompt's stdin closed"
        proc.stdin.close()
        out = proc.stdout.read().decode()
        assert proc.wait(timeout=30) == 0
        assert out.splitlines() == SCRIPT_A
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


# Behavior 2: it emits scripted stream-json lines taken from a scenario file named by
# `RELAY_FAKE_SCENARIO`.

def test_fake_claude_emits_the_scenario_lines_in_order(tmp_path: Path) -> None:
    path = _write_scenario(tmp_path / "a.jsonl", SCRIPT_A)
    done = _run_fake(path, "You are a lead\n")
    assert done.returncode == 0
    assert done.stdout.splitlines() == SCRIPT_A


def test_fake_claude_reads_the_scenario_the_variable_names(tmp_path: Path) -> None:
    first = _write_scenario(tmp_path / "a.jsonl", SCRIPT_A)
    second = _write_scenario(tmp_path / "b.jsonl", SCRIPT_B)
    assert _run_fake(second, "You are a lead\n").stdout.splitlines() == SCRIPT_B
    assert _run_fake(first, "You are a lead\n").stdout.splitlines() == SCRIPT_A


# Behavior 3: `tests/conftest.py` holds the fixtures `fake_cfg`, `queue_file` and `scenario`.

def test_fake_cfg_is_a_config_whose_commands_point_at_the_fake(
    request: pytest.FixtureRequest,
) -> None:
    cfg = request.getfixturevalue("fake_cfg")
    assert isinstance(cfg, Config)
    # The commands run with their argv as given, so the fake must be the program itself.
    for argv in (cfg.lead_command, cfg.recut_command, cfg.ping_command):
        assert argv[0] == str(FAKE_CLAUDE), argv


def test_fake_cfg_keeps_state_root_under_tmp_path(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    cfg = request.getfixturevalue("fake_cfg")
    assert cfg.state_root.is_relative_to(tmp_path)


@pytest.mark.parametrize("name", sorted(QUEUE_SAMPLES))
def test_queue_file_writes_the_named_fixture_queue(
    request: pytest.FixtureRequest, tmp_path: Path, name: str
) -> None:
    write_queue = request.getfixturevalue("queue_file")
    path = write_queue(name)
    assert path.is_relative_to(tmp_path)
    assert path.read_bytes() == (FIXTURES / name).read_bytes()


def test_scenario_writes_the_lines_and_names_the_file_for_the_fake(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    write_scenario = request.getfixturevalue("scenario")
    path = write_scenario(SCRIPT_B)
    assert path.is_relative_to(tmp_path)
    assert path.read_text().splitlines() == SCRIPT_B
    assert os.environ["RELAY_FAKE_SCENARIO"] == str(path)


# Behavior 4: `tests/fixtures/` holds queue samples in the divvyer's `.md` format.

@pytest.mark.parametrize("name", sorted(QUEUE_SAMPLES))
def test_fixture_queue_sample_parses_into_its_sections(name: str) -> None:
    sections = parse_queue(FIXTURES / name)
    assert [s.id for s in sections] == QUEUE_SAMPLES[name]
