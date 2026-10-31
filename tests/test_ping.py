"""Red tests for Relay's owner pings (design: Modules `relay/ping.py`; Order 11)."""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

from relay.config import Config
from relay.ping import needs_owner, ping, stopped

# A ping command that appends its argv (after the record path) as one JSON line to the record path.
from harness import RECORD as _RECORD


def _recording_cfg(cfg: Config, record: Path) -> Config:
    return dataclasses.replace(
        cfg, ping_command=[sys.executable, "-c", _RECORD, str(record), "{message}"]
    )


def _sent(record: Path) -> list[list[str]]:
    return [json.loads(line) for line in record.read_text().splitlines()]


def _prefixes(queue: Path) -> tuple[str, ...]:
    return (f"relay {queue.name}: ", f"relay {queue.stem}: ")


# Behavior 1: `relay/ping.py`: the one place an owner ping is worded and sent.


def test_ping_runs_ping_command_with_message_in_place(fake_cfg: Config, tmp_path: Path) -> None:
    record = tmp_path / "sent.jsonl"
    ping(_recording_cfg(fake_cfg, record), "section s3 parked")
    assert _sent(record) == [["section s3 parked"]]
    # "{message}" is replaced where it stands, so arguments after it keep their places.
    inner = tmp_path / "inner.jsonl"
    cfg = dataclasses.replace(
        fake_cfg,
        ping_command=[sys.executable, "-c", _RECORD, str(inner), "--title", "{message}", "--end"],
    )
    ping(cfg, "section s3 parked")
    assert _sent(inner) == [["--title", "section s3 parked", "--end"]]


def test_ping_passes_message_as_one_argument_unexpanded(fake_cfg: Config, tmp_path: Path) -> None:
    record = tmp_path / "sent.jsonl"
    message = 'it\'s "done"; $HOME * {x} `id`'
    ping(_recording_cfg(fake_cfg, record), message)
    assert _sent(record) == [[message]]


def test_ping_sends_once_per_call(fake_cfg: Config, tmp_path: Path) -> None:
    record = tmp_path / "sent.jsonl"
    cfg = _recording_cfg(fake_cfg, record)
    ping(cfg, "first")
    ping(cfg, "second")
    assert _sent(record) == [["first"], ["second"]]


def test_needs_owner_message_names_queue_section_and_question(
    fake_cfg: Config, tmp_path: Path
) -> None:
    record = tmp_path / "sent.jsonl"
    queue = tmp_path / "m2-rest.md"
    question = "Should the API keep v1 routes?"
    needs_owner(_recording_cfg(fake_cfg, record), queue, "s4.d2", question)
    sent = _sent(record)
    assert len(sent) == 1
    assert len(sent[0]) == 1
    message = sent[0][0]
    assert message.startswith(_prefixes(queue))
    assert "s4.d2" in message
    assert question in message


def test_stopped_message_names_queue_reason_and_detail(fake_cfg: Config, tmp_path: Path) -> None:
    record = tmp_path / "sent.jsonl"
    queue = tmp_path / "workboard.md"
    stopped(_recording_cfg(fake_cfg, record), queue, "FAILED_TWICE", "section s2 failed twice")
    sent = _sent(record)
    assert len(sent) == 1
    assert len(sent[0]) == 1
    message = sent[0][0]
    assert message.startswith(_prefixes(queue))
    assert "FAILED_TWICE" in message
    assert "section s2 failed twice" in message


# Behavior 2: a failed ping is logged to stderr, never raised.


def _failing_cfgs(cfg: Config, tmp_path: Path) -> dict[str, Config]:
    return {
        "nonzero": dataclasses.replace(
            cfg, ping_command=[sys.executable, "-c", "raise SystemExit(3)", "{message}"]
        ),
        "missing": dataclasses.replace(
            cfg, ping_command=[str(tmp_path / "no-such-ping"), "{message}"]
        ),
    }


@pytest.mark.parametrize("failure", ["nonzero", "missing"])
def test_failed_ping_is_logged_not_raised(
    failure: str, fake_cfg: Config, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    cfg = _failing_cfgs(fake_cfg, tmp_path)[failure]
    assert ping(cfg, "hello owner") is None
    assert capfd.readouterr().err.strip() != ""


@pytest.mark.parametrize("failure", ["nonzero", "missing"])
def test_failed_needs_owner_ping_is_logged_not_raised(
    failure: str, fake_cfg: Config, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    cfg = _failing_cfgs(fake_cfg, tmp_path)[failure]
    assert needs_owner(cfg, tmp_path / "queue.md", "s1", "Which port?") is None
    assert capfd.readouterr().err.strip() != ""


@pytest.mark.parametrize("failure", ["nonzero", "missing"])
def test_failed_stopped_ping_is_logged_not_raised(
    failure: str, fake_cfg: Config, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    cfg = _failing_cfgs(fake_cfg, tmp_path)[failure]
    assert stopped(cfg, tmp_path / "queue.md", "BUDGET", "token budget reached") is None
    assert capfd.readouterr().err.strip() != ""
