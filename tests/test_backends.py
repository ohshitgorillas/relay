"""Adapter behavior from relay-backends-design.md, Modules."""

from pathlib import Path

import pytest

from relay.backends import get_backend, replay
from relay.backends.claude import ClaudeBackend
from relay.backends.generic import GenericBackend
from relay.config import Config
from relay.errors import ConfigError
from relay.ledger import Spend
from relay.stream import StreamState


def _state() -> StreamState:
    return StreamState(None, 0, Spend(0, 0.0), None, False)


def _config(tmp_path: Path) -> Config:
    return Config(None, None, 100_000, 200_000, 30,
                  ["custom-lead", "--flag"], ["custom-recut"], [], tmp_path)


def test_registry_selects_fresh_adapters() -> None:
    # Breaks when selection reuses an adapter's per-run resources.
    for name, kind in (("claude", ClaudeBackend), ("generic", GenericBackend)):
        first, second = get_backend(name), get_backend(name)
        assert isinstance(first, kind)
        assert isinstance(second, kind)
        assert first is not second


def test_registry_rejects_unknown_backend() -> None:
    # Breaks when an unknown selection silently falls back to Claude.
    with pytest.raises(ConfigError):
        get_backend("unrecognized-backend")


def test_legacy_replay_uses_claude_stream(tmp_path: Path) -> None:
    # Breaks when an unmarked historical log stops using Claude semantics.
    log = tmp_path / "1.jsonl"
    log.write_text((Path(__file__).parent / "fixtures/stream-lead.jsonl").read_text())
    state = replay(log)
    assert state.session_id == "sess-lead-1"
    assert state.context_tokens == 1007
    assert state.spend == Spend(7275, 0.4321)
    assert state.result_text == "Step committed.\nDONE"
    assert state.is_error is False


def test_claude_preserves_stream_observations() -> None:
    # Breaks when the adapter loses context, cumulative spend or final text.
    backend = ClaudeBackend()
    state = _state()
    lines = (Path(__file__).parent / "fixtures/stream-lead.jsonl").read_text().splitlines()
    for line in lines:
        state = backend.parse(state, line)
    assert state.session_id == "sess-lead-1"
    assert state.context_tokens == 1007
    assert state.spend == Spend(7275, 0.4321)
    assert state.result_text == "Step committed.\nDONE"
    assert state.is_error is False


def test_claude_preserves_error_result() -> None:
    # Breaks when a Claude error result becomes a successful report.
    backend = ClaudeBackend()
    state = _state()
    lines = (Path(__file__).parent / "fixtures/stream-error.jsonl").read_text().splitlines()
    for line in lines:
        state = backend.parse(state, line)
    assert state.is_error is True
    assert state.result_text == "Prompt is too long"
    assert state.spend == Spend(2015, 0.0)


def test_claude_poll_finish_and_handoff_preserve_observations(tmp_path: Path) -> None:
    # Breaks when poll/finish replaces stream results or changes the legacy hint.
    backend = ClaudeBackend()
    state = StreamState("old-thread", 321, Spend(654, 1.5), "report", True)
    output = tmp_path / "output"
    output.write_text("unrelated text")
    assert backend.poll(state) == state
    assert backend.finish(state, output) == state
    assert backend.resume_hint("old-thread") == "resume old-thread"


def test_generic_preserves_stdout_and_line_breaks(tmp_path: Path) -> None:
    # Breaks when generic stdout is JSON-decoded, stripped or reordered.
    backend = GenericBackend()
    state = _state()
    for line in ("  report\n", "\n", '{"type":"result"}\n', "last"):
        state = backend.parse(state, line)
    state = backend.finish(backend.poll(state), tmp_path / "absent")
    assert state.result_text == '  report\n\n{"type":"result"}\nlast'
    assert state.context_tokens == 0
    assert state.spend == Spend(0, 0.0)
    assert state.session_id is None
    assert state.is_error is False


def test_generic_uses_explicit_role_commands(tmp_path: Path) -> None:
    # Breaks when generic launch appends Claude flags or ignores the recut command.
    backend = GenericBackend()
    cfg = _config(tmp_path)
    assert backend.argv("lead", cfg, tmp_path, tmp_path / "out") == cfg.lead_command
    assert backend.argv("recut", cfg, tmp_path, tmp_path / "out") == cfg.recut_command


def test_generic_has_no_telemetry() -> None:
    # Breaks when generic advertises unsupported budget or context telemetry.
    backend = GenericBackend()
    assert backend.capabilities.context is False
    assert backend.capabilities.tokens is False
    assert backend.capabilities.dollars is False
    assert backend.capabilities.subagents is False
    assert backend.parse(_state(), "plain stdout").spend == Spend(0, 0.0)
