"""Red tests for running and judging a section's checks (design:
docs/superpowers/specs/relay-check-design.md, Modules `relay/check.py`; Order 5)."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from relay.check import CheckResult, classify, owner_text, run_checks
from relay.config import Config
from relay.queue import Section


def _section(*checks: str, sid: str = "s4") -> Section:
    return Section(
        id=sid,
        title="Check runner",
        body="## Check runner\n",
        depends_on=(),
        open=True,
        checks=checks,
    )


def _cwd(tmp_path: Path) -> Path:
    cwd = tmp_path / "worktree"
    cwd.mkdir()
    return cwd


def _log(tmp_path: Path) -> Path:
    return tmp_path / "7.check"


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line]


# Behavior 1: Run each of section.checks in order in `cwd` through runner.run_command,
# appending all


def test_each_check_runs_in_order(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: the checks run out of body order, or only the first or last one runs.
    log = _log(tmp_path)
    run_checks(
        fake_cfg,
        _section("echo first-check", "echo second-check", "echo third-check"),
        _cwd(tmp_path),
        log,
    )
    assert _lines(log.read_text()) == ["first-check", "second-check", "third-check"]


def test_each_check_runs_in_cwd(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: a check runs in Relay's own working directory or the repository root instead of `cwd`.
    cwd = _cwd(tmp_path)
    run_checks(
        fake_cfg,
        _section("touch made-by-first", "touch made-by-second"),
        cwd,
        _log(tmp_path),
    )
    assert (cwd / "made-by-first").exists()
    assert (cwd / "made-by-second").exists()


def test_a_check_inherits_the_environment_relay_started_with(
    tmp_path: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: the check is started with its own env= rather than the inherited environment.
    monkeypatch.setenv("RELAY_CHECK_TEST_MARK", "inherited-value-42")
    log = _log(tmp_path)
    run_checks(
        fake_cfg,
        _section('printf "%s\\n" "$RELAY_CHECK_TEST_MARK"'),
        _cwd(tmp_path),
        log,
    )
    assert "inherited-value-42" in log.read_text()


def test_a_check_is_bounded_by_the_configured_check_timeout(
    tmp_path: Path, fake_cfg: Config
) -> None:
    # Breaks when: run_checks starts the command with no timeout or one other than cfg.check_timeout.
    cfg = dataclasses.replace(fake_cfg, check_timeout=0.5)
    result = run_checks(cfg, _section("sleep 20"), _cwd(tmp_path), _log(tmp_path))
    assert result.timed_out is True
    assert result.exit_code is None
    assert result.command == "sleep 20"
    assert result.timeout == 0.5


def test_checks_that_all_exit_0_are_pass(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: a run whose every check exits 0 is reported fail, outside or none,
    # or its result does not name the check log.
    log = _log(tmp_path)
    result = run_checks(fake_cfg, _section("true", "echo fine", "exit 0"), _cwd(tmp_path), log)
    assert result.verdict == "pass"
    assert result.timed_out is False
    assert result.timeout is None
    assert result.log == log


def test_a_section_with_no_checks_is_none(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: an empty section.checks is reported pass or fail, or its result
    # names a command, an exit code, a timeout or a log though none ran.
    result = run_checks(fake_cfg, _section(), _cwd(tmp_path), _log(tmp_path))
    assert result.verdict == "none"
    assert result.command is None
    assert result.exit_code is None
    assert result.timed_out is False
    assert result.timeout is None
    assert result.log is None


def test_a_failing_result_names_the_check_log(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: a failing result's log is None or a path other than the `log` the checks ran into.
    log = _log(tmp_path)
    result = run_checks(fake_cfg, _section("echo failing; exit 1"), _cwd(tmp_path), log)
    assert result.verdict == "fail"
    assert result.log == log


# Behavior 2: output to `log`, and stop at the first non-zero exit.


def test_stdout_and_stderr_both_go_to_the_log(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: stderr is dropped or sent elsewhere instead of the log.
    log = _log(tmp_path)
    run_checks(
        fake_cfg,
        _section("echo on-stdout", "echo on-stderr >&2"),
        _cwd(tmp_path),
        log,
    )
    text = log.read_text()
    assert "on-stdout" in text
    assert "on-stderr" in text


def test_output_is_appended_to_the_log_not_written_over_it(
    tmp_path: Path, fake_cfg: Config
) -> None:
    # Breaks when: the log is opened for writing (truncated) rather than appended to.
    log = _log(tmp_path)
    log.write_text("an earlier pass\n")
    run_checks(fake_cfg, _section("echo this-pass"), _cwd(tmp_path), log)
    text = log.read_text()
    assert text.startswith("an earlier pass\n")
    assert "this-pass" in text


def test_checks_stop_at_the_first_non_zero_exit(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: checks after a failing one still run.
    cwd = _cwd(tmp_path)
    log = _log(tmp_path)
    run_checks(
        fake_cfg,
        _section("echo before-fail", "echo failing; exit 3", "touch after-fail"),
        cwd,
        log,
    )
    assert not (cwd / "after-fail").exists()
    assert _lines(log.read_text()) == ["before-fail", "failing"]


def test_a_failing_first_check_runs_no_other(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: a failing first check does not stop the rest.
    cwd = _cwd(tmp_path)
    run_checks(
        fake_cfg,
        _section("exit 1", "touch second-ran", "touch third-ran"),
        cwd,
        _log(tmp_path),
    )
    assert not (cwd / "second-ran").exists()
    assert not (cwd / "third-ran").exists()


def test_the_result_names_the_failing_command_and_its_exit(
    tmp_path: Path, fake_cfg: Config
) -> None:
    # Breaks when: the result carries the last or first command, or another exit code, rather than the failing one's.
    result = run_checks(
        fake_cfg,
        _section("true", "echo failing; exit 3", "exit 5"),
        _cwd(tmp_path),
        _log(tmp_path),
    )
    assert result.command == "echo failing; exit 3"
    assert result.exit_code == 3
    assert result.timed_out is False
    assert result.timeout is None


def test_a_timed_out_check_stops_the_rest(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: a check killed at the timeout is not treated as the failing command.
    cfg = dataclasses.replace(fake_cfg, check_timeout=0.5)
    cwd = _cwd(tmp_path)
    run_checks(cfg, _section("sleep 20", "touch after-timeout"), cwd, _log(tmp_path))
    assert not (cwd / "after-timeout").exists()


# Behavior 3: otherwise classify() of the failing command.


def test_a_plain_failure_is_fail(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: a non-zero exit with no outside pattern is reported pass, none or outside.
    cfg = dataclasses.replace(fake_cfg, check_outside=["quota exceeded"])
    result = run_checks(
        cfg, _section("echo 2 tests failed; exit 1"), _cwd(tmp_path), _log(tmp_path)
    )
    assert result.verdict == "fail"


@pytest.mark.parametrize("code", [126, 127])
def test_exit_126_or_127_is_outside(code: int, tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: run_checks reports a fail, not classify()'s "outside", for an exit 126 or 127.
    cfg = dataclasses.replace(fake_cfg, check_outside=[])
    result = run_checks(cfg, _section(f"exit {code}"), _cwd(tmp_path), _log(tmp_path))
    assert result.exit_code == code
    assert result.verdict == "outside"


def test_a_failing_output_matching_an_outside_pattern_is_outside(
    tmp_path: Path, fake_cfg: Config
) -> None:
    # Breaks when: run_checks ignores cfg.check_outside when it judges the failing command.
    cfg = dataclasses.replace(fake_cfg, check_outside=["quota exceeded"])
    result = run_checks(
        cfg,
        _section("echo 'error: quota exceeded for this key'; exit 1"),
        _cwd(tmp_path),
        _log(tmp_path),
    )
    assert result.verdict == "outside"


def test_only_the_failing_commands_output_is_judged(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: the whole log, an earlier passing command's output included, is matched against the patterns.
    cfg = dataclasses.replace(fake_cfg, check_outside=["quota exceeded"])
    result = run_checks(
        cfg,
        _section("echo 'warning: quota exceeded earlier'", "echo 1 test failed; exit 1"),
        _cwd(tmp_path),
        _log(tmp_path),
    )
    assert result.verdict == "fail"


def test_a_timed_out_check_with_no_pattern_match_is_fail(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: a timeout is reported outside or pass instead of classify()'s "fail".
    cfg = dataclasses.replace(fake_cfg, check_timeout=0.5, check_outside=["quota exceeded"])
    result = run_checks(cfg, _section("sleep 20"), _cwd(tmp_path), _log(tmp_path))
    assert result.verdict == "fail"


# Behavior 4: or any pattern in cfg.check_outside matches tail


def test_a_pattern_found_anywhere_in_the_tail_is_outside(fake_cfg: Config) -> None:
    # Breaks when: patterns are anchored at the tail's start (re.match) instead of searched for.
    cfg = dataclasses.replace(fake_cfg, check_outside=["quota exceeded"])
    tail = "running tests\n3 passed\nerror: quota exceeded for this key\nbye\n"
    assert classify(cfg, 1, False, tail) == "outside"


def test_any_one_of_several_patterns_is_enough(fake_cfg: Config) -> None:
    # Breaks when: only the first pattern is tried, or all must match.
    cfg = dataclasses.replace(fake_cfg, check_outside=["quota exceeded", "no route to host"])
    assert classify(cfg, 1, False, "fetch: no route to host\n") == "outside"


def test_patterns_are_regular_expressions(fake_cfg: Config) -> None:
    # Breaks when: a pattern is matched as a plain substring rather than a regex.
    cfg = dataclasses.replace(fake_cfg, check_outside=[r"connection (refused|reset)"])
    assert classify(cfg, 1, False, "pip: connection reset by peer\n") == "outside"


def test_inline_regex_flags_are_honoured(fake_cfg: Config) -> None:
    # Breaks when: a pattern's inline (?i) flag is stripped or the pattern escaped.
    cfg = dataclasses.replace(fake_cfg, check_outside=["(?i)credit balance"])
    assert classify(cfg, 1, False, "Your Credit Balance is too low\n") == "outside"


def test_no_pattern_matching_is_fail(fake_cfg: Config) -> None:
    # Breaks when: a non-zero exit with no pattern match is called outside.
    cfg = dataclasses.replace(fake_cfg, check_outside=["quota exceeded", "no route to host"])
    assert classify(cfg, 1, False, "FAILED tests/test_x.py::test_y\n") == "fail"


def test_the_patterns_are_the_configured_ones(fake_cfg: Config) -> None:
    # Breaks when: classify matches a built-in list instead of cfg.check_outside.
    cfg = dataclasses.replace(fake_cfg, check_outside=["quota exceeded"])
    assert classify(cfg, 1, False, "sh: foo: command not found\n") == "fail"


def test_an_empty_pattern_list_matches_nothing(fake_cfg: Config) -> None:
    # Breaks when: an empty check_outside falls back to a built-in list.
    cfg = dataclasses.replace(fake_cfg, check_outside=[])
    assert classify(cfg, 1, False, "could not resolve host: pypi.org\n") == "fail"


def test_a_timed_out_check_matching_a_pattern_is_outside(fake_cfg: Config) -> None:
    # Breaks when: a timeout is called "fail" without the patterns being tried.
    cfg = dataclasses.replace(fake_cfg, check_outside=["(?i)could not resolve host"])
    assert classify(cfg, None, True, "Could not resolve host: github.com\n") == "outside"


# Behavior 5: the end of that command's output, TAIL_LINES / TAIL_CHARS


def test_a_short_output_is_kept_whole_in_the_tail(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: the tail drops lines of an output already under the limits.
    result = run_checks(
        fake_cfg,
        _section("echo alpha; echo beta; echo gamma; exit 1"),
        _cwd(tmp_path),
        _log(tmp_path),
    )
    assert _lines(result.tail) == ["alpha", "beta", "gamma"]


def test_the_tail_is_the_last_40_lines(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: the tail keeps the first lines, more than 40 lines, or fewer.
    command = 'i=1; while [ "$i" -le 100 ]; do echo "line$i"; i=$((i+1)); done; exit 1'
    result = run_checks(fake_cfg, _section(command), _cwd(tmp_path), _log(tmp_path))
    assert _lines(result.tail) == [f"line{i}" for i in range(61, 101)]


def test_the_tail_is_at_most_4000_characters_from_the_end(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: 40 long lines are kept whole past 4000 characters, or the cut keeps the start.
    command = 'i=1; while [ "$i" -le 60 ]; do printf "%0200d\\n" "$i"; i=$((i+1)); done; exit 1'
    full = "".join(f"{i:0200d}\n" for i in range(1, 61))
    result = run_checks(fake_cfg, _section(command), _cwd(tmp_path), _log(tmp_path))
    tail = result.tail
    assert len(tail) <= 4000
    assert len(tail) >= 4000 - 201
    assert full.rstrip("\n").endswith(tail.rstrip("\n"))
    assert f"{60:0200d}" in tail


def test_the_tail_holds_only_that_commands_output(tmp_path: Path, fake_cfg: Config) -> None:
    # Breaks when: the tail is read from the end of the whole log, earlier output included.
    log = _log(tmp_path)
    log.write_text("an earlier pass\n")
    result = run_checks(
        fake_cfg,
        _section("echo passing-output", "echo failing-output; exit 1"),
        _cwd(tmp_path),
        log,
    )
    assert "failing-output" in result.tail
    assert "passing-output" not in result.tail
    assert "an earlier pass" not in result.tail


# Behavior 6: The question parked for the owner and pinged: the command, "exit <n>" or
# "timed out after <s>s", the failure count when verdict is "fail", the log path, then the tail.

LOG = Path("/state/relay/work-queue-md/runs/5.check")
TAIL = "FAILED tests/test_x.py::test_y - AssertionError\n== one failed ==\n"


def _result(**changes: object) -> CheckResult:
    if changes.get("timed_out") and "timeout" not in changes:
        changes["timeout"] = 1800.0
    result = CheckResult(
        command="make check",
        exit_code=1,
        timed_out=False,
        tail=TAIL,
        log=LOG,
        verdict="fail",
    )
    return dataclasses.replace(result, **changes)


def test_owner_text_holds_the_command_exit_log_and_tail() -> None:
    # Breaks when: the command, "exit <n>", the log path or the tail is left out.
    text = owner_text(_result(), 2)
    assert "make check" in text
    assert "exit 1" in text
    assert str(LOG) in text
    assert TAIL.rstrip("\n") in text


def test_owner_text_parts_come_in_order_with_the_tail_last() -> None:
    # Breaks when: the parts are reordered, or anything follows the tail.
    text = owner_text(_result(), 2)
    assert text.index("make check") < text.index("exit 1") < text.index(str(LOG))
    assert text.index(str(LOG)) < text.index(TAIL.rstrip("\n"))
    assert text.rstrip("\n").endswith(TAIL.rstrip("\n"))
    between = text[text.index("exit 1") + len("exit 1") : text.index(str(LOG))]
    assert re.search(r"\b2\b", between)


def test_owner_text_for_a_timeout_says_timed_out_after_seconds() -> None:
    # Breaks when: a timeout is worded "exit None" or without "timed out after <s>s",
    # or <s> is not the result's timeout written with %g.
    text = owner_text(_result(exit_code=None, timed_out=True), 1)
    assert "timed out after " in text
    assert "exit None" not in text
    after = text[text.index("timed out after ") + len("timed out after ") :]
    seconds = after.split("s", 1)[0]
    assert seconds.replace(".", "", 1).isdigit()
    assert seconds == "1800"


def test_owner_text_for_a_timeout_names_the_configured_check_timeout(
    tmp_path: Path, fake_cfg: Config
) -> None:
    # Breaks when: the seconds in "timed out after <s>s" are not cfg.check_timeout,
    # the limit the timed-out command ran under.
    cfg = dataclasses.replace(fake_cfg, check_timeout=0.5)
    result = run_checks(cfg, _section("sleep 20"), _cwd(tmp_path), _log(tmp_path))
    assert result.timeout == 0.5
    assert "timed out after 0.5s" in owner_text(result, 1)


def test_owner_text_holds_the_failure_count_on_a_fail() -> None:
    # Breaks when: the failure count is left out of a "fail" question, or the
    # question shows a number other than the count it was given.
    seven = owner_text(_result(verdict="fail"), 7)
    four = owner_text(_result(verdict="fail"), 4)
    assert "7" in seven
    assert re.search(r"\b7\b", seven)
    assert re.search(r"\b4\b", four)
    assert "7" not in four
    assert "4" not in seven


def test_owner_text_leaves_the_count_out_when_outside() -> None:
    # Breaks when: the failure count is shown on an "outside" question.
    text = owner_text(_result(verdict="outside", exit_code=127), 7)
    assert "exit 127" in text
    assert "7" not in text.replace("127", "")
