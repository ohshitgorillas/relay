"""The retire gate from relay-run-overhead-design.md, Modules `relay/retire_gate.py`."""

import io
import json
import sys
from pathlib import Path

import pytest

from relay.retire_gate import REFUSAL, main

# A PreToolUse event as the Claude CLI hands it to a hook on stdin.
_EVENT = (
    json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "builder", "prompt": "Build step 3."},
        }
    )
    + "\n"
)


def _stdin(monkeypatch: pytest.MonkeyPatch) -> io.TextIOWrapper:
    stdin = io.TextIOWrapper(io.BytesIO(_EVENT.encode()), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", stdin)
    return stdin


def test_raised_flag_refuses_the_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when an Agent call goes through after the retire flag is up, the refusal
    # is not on stderr where the CLI shows a blocking hook's reason, or it stops telling
    # the lead to dispatch nothing new, wait for running agents and end RETIRED.
    flag = tmp_path / "retire"
    flag.write_text("")
    _stdin(monkeypatch)
    assert main([str(flag)]) == 2
    out, err = capsys.readouterr()
    assert err.rstrip("\n") == (
        "Relay's retire flag is up: dispatch nothing new, wait for running agents, end with RETIRED."
    )
    assert err.rstrip("\n") == REFUSAL
    assert out == ""


def test_absent_flag_lets_the_dispatch_through(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when a lead whose retire flag is down is refused a dispatch, or the gate
    # looks at some file other than argv[0].
    (tmp_path / "other-flag").write_text("")
    _stdin(monkeypatch)
    assert main([str(tmp_path / "retire")]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out == ""


@pytest.mark.parametrize("raised", [True, False], ids=["raised", "absent"])
def test_hook_stdin_is_read_whole_and_discarded(
    raised: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when the gate leaves the hook's stdin unread, or echoes any of it back.
    flag = tmp_path / "retire"
    if raised:
        flag.write_text("")
    stdin = _stdin(monkeypatch)
    main([str(flag)])
    assert stdin.read() == ""
    out, err = capsys.readouterr()
    assert "builder" not in out + err
    assert "PreToolUse" not in out + err
