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


# Ladder design, Order 3: when argv carries `--agent <name>` and
# `RELAY_FAKE_SCENARIO_<NAME>` is set (upper case, `-` as `_`), the fake emits that
# scenario.


def _fake_env(**extra: str) -> dict[str, str]:
    """The test process's environment with no `RELAY_FAKE_*` variable, plus `extra`."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("RELAY_FAKE_")}
    env.update(extra)
    return env


def _run_fake_argv(
    args: list[str], prompt: str, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(FAKE_CLAUDE), *args],
        input=prompt, capture_output=True, text=True, env=env, timeout=30,
    )


def test_fake_claude_emits_the_named_agents_scenario_over_the_shared_one(
    tmp_path: Path,
) -> None:
    shared = _write_scenario(tmp_path / "shared.jsonl", SCRIPT_A)
    architect = _write_scenario(tmp_path / "architect.jsonl", SCRIPT_B)
    env = _fake_env(
        RELAY_FAKE_SCENARIO=str(shared), RELAY_FAKE_SCENARIO_ARCHITECT=str(architect)
    )
    done = _run_fake_argv(["--agent", "architect"], "design s1\n", env)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == SCRIPT_B
    # Another agent, whose own variable is not set, still gets the shared scenario.
    done = _run_fake_argv(["--agent", "divvyer"], "recut s1\n", env)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == SCRIPT_A


def test_fake_claude_names_the_agents_variable_upper_case_with_dash_as_underscore(
    tmp_path: Path,
) -> None:
    writer = _write_scenario(tmp_path / "writer.jsonl", SCRIPT_B)
    env = _fake_env(RELAY_FAKE_SCENARIO_TEST_WRITER=str(writer))
    done = _run_fake_argv(["--agent", "test-writer"], "red s1\n", env)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == SCRIPT_B


def test_fake_claude_finds_the_agent_flag_among_other_arguments(tmp_path: Path) -> None:
    shared = _write_scenario(tmp_path / "shared.jsonl", SCRIPT_A)
    researcher = _write_scenario(tmp_path / "researcher.jsonl", SCRIPT_B)
    env = _fake_env(
        RELAY_FAKE_SCENARIO=str(shared), RELAY_FAKE_SCENARIO_RESEARCHER=str(researcher)
    )
    done = _run_fake_argv(
        ["-p", "--output-format", "stream-json", "--agent", "researcher", "--verbose"],
        "research s1\n",
        env,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == SCRIPT_B


# Ladder design, Order 3: the fake appends each prompt it reads to the file
# `RELAY_FAKE_PROMPTS` names, when that is set.


def test_fake_claude_appends_each_prompt_it_reads_to_the_prompts_file(
    tmp_path: Path,
) -> None:
    shared = _write_scenario(tmp_path / "shared.jsonl", SCRIPT_A)
    prompts = tmp_path / "prompts.txt"
    prompts.write_text("earlier prompt\n")
    env = _fake_env(RELAY_FAKE_SCENARIO=str(shared), RELAY_FAKE_PROMPTS=str(prompts))
    first = "You are a lead\nSection s1.\n"
    second = "design s1: amending Order 3\n"
    assert _run_fake_argv([], first, env).returncode == 0
    assert _run_fake_argv(["--agent", "architect"], second, env).returncode == 0
    text = prompts.read_text()
    # Appended, never overwritten: what the file held stays at its head.
    assert text.startswith("earlier prompt\n")
    at_first = text.find(first)
    at_second = text.find(second)
    assert at_first >= len("earlier prompt\n"), text
    assert at_second >= at_first + len(first), text


# Behavior 4: `tests/fixtures/` holds queue samples in the divvyer's `.md` format.

@pytest.mark.parametrize("name", sorted(QUEUE_SAMPLES))
def test_fixture_queue_sample_parses_into_its_sections(name: str) -> None:
    sections = parse_queue(FIXTURES / name)
    assert [s.id for s in sections] == QUEUE_SAMPLES[name]


# Ladder design, Order 3: the architect streams `tests/fixtures/stream-architect-*.jsonl`,
# whose final reports are, in turn, an approved design, one awaiting an owner product
# decision, and a `REJECTED: STEERING` refusal, in the report form `parse_report` reads
# (design: Modules, `relay/ladder.py`, `DesignReport` and `parse_report`).


def _final_report(name: str) -> str:
    """The `result` text of the stream fixture's last event, which must be its result."""
    events = [json.loads(line) for line in (FIXTURES / name).read_text().splitlines()]
    assert events[0]["type"] == "system" and events[0]["subtype"] == "init", name
    last = events[-1]
    assert last["type"] == "result" and last["is_error"] is False, name
    assert isinstance(last["result"], str), name
    return last["result"]


def test_the_approved_architect_stream_reports_an_approved_design_with_nothing_open() -> None:
    # breaks when: parse_report misses the STATUS line inside the BRIEF ... END DESIGN block.
    from relay.ladder import DesignReport, parse_report

    report = parse_report(_final_report("stream-architect-approved.jsonl"))
    assert report == DesignReport(rejected=False, approved=True, decisions=(), unfiled=())


def test_the_decision_architect_stream_reports_an_unapproved_design_with_two_decisions() -> None:
    # breaks when: parse_report drops the indented lines under DECISIONS.
    from relay.ladder import decision_numbers, parse_report

    report = parse_report(_final_report("stream-architect-decision.jsonl"))
    assert report is not None
    assert report.rejected is False
    assert report.approved is False
    assert len(report.decisions) == 2
    for line in report.decisions:
        assert "| recommend: " in line and "| alternative: " in line, line
    # Each decision is the indented line under DECISIONS, as written, compared exactly.
    assert report.decisions == (
        "1 | Should two() return 2 when one.py is absent? | recommend: no, fail loudly"
        " | alternative: return 2",
        "2 | Should three() ship in this release? | recommend: yes"
        " | alternative: hold it for the next",
    )
    assert report.unfiled == ()
    assert decision_numbers(report) == (1, 2)


def test_the_rejected_architect_stream_reports_a_steering_refusal() -> None:
    # breaks when: parse_report looks only for a BRIEF block and misses `REJECTED: STEERING`.
    from relay.ladder import parse_report

    report = parse_report(_final_report("stream-architect-rejected.jsonl"))
    assert report is not None
    assert report.rejected is True
    assert report.approved is False


# Two more streams, so each design-report outcome `_design_outcome` acts on has its own:
# a design that is not approved with nothing open, and one with an UNFILED line open
# (design: Modules, `relay/loop.py`, `_design_outcome`).


def test_the_unapproved_architect_stream_reports_a_design_not_approved_with_nothing_open() -> None:
    # breaks when: parse_report sets approved from any STATUS line, not only `Status: approved`.
    from relay.ladder import DesignReport, parse_report

    report = parse_report(_final_report("stream-architect-unapproved.jsonl"))
    assert report == DesignReport(rejected=False, approved=False, decisions=(), unfiled=())


def test_the_unfiled_architect_stream_reports_one_unfiled_line_and_no_decision() -> None:
    # breaks when: parse_report drops the indented lines under UNFILED.
    from relay.ladder import decision_numbers, parse_report

    report = parse_report(_final_report("stream-architect-unfiled.jsonl"))
    assert report is not None
    assert report.rejected is False
    assert report.approved is False
    assert report.decisions == ()
    assert decision_numbers(report) == ()
    # The unfiled line is the indented line under UNFILED, as written, compared exactly.
    assert report.unfiled == (
        "1 | Who owns one.py once both sections use it? | recommend: section s1"
        " | alternative: a new shared section",
    )


def test_each_design_report_outcome_has_its_own_architect_stream() -> None:
    # breaks when: two streams report the same outcome, or one outcome has no stream.
    from relay.ladder import parse_report

    def outcome(name: str) -> str:
        report = parse_report(_final_report(name))
        assert report is not None, name
        if report.rejected:
            return "steering refusal"
        if report.decisions:
            return "decisions"
        if report.unfiled:
            return "unfiled"
        return "approved" if report.approved else "not approved"

    names = sorted(p.name for p in FIXTURES.glob("stream-architect-*.jsonl"))
    outcomes = sorted(outcome(name) for name in names)
    assert outcomes == sorted(
        ["approved", "decisions", "unfiled", "not approved", "steering refusal"]
    )
