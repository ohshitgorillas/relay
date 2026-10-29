"""Adapter behavior from relay-backends-design.md, Modules."""

import json
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from relay.backends import get_backend, replay
from relay.backends.claude import ClaudeBackend
from relay.backends.codex import CodexBackend
from relay.backends.generic import GenericBackend
from relay.config import Config
from relay.errors import ConfigError
from relay.ledger import Spend
from relay.research import parse_map
from relay.runner import RunResult, run_failed
from relay.stream import StreamState


def _state() -> StreamState:
    return StreamState(None, 0, Spend(0, 0.0), None, False)


def test_codex_history_hint_identifies_native_history_and_report_handoff() -> None:
    # Breaks when the hint sends Codex IDs to Terminus or loses report handoff.
    hint = CodexBackend().resume_hint("prior-thread")
    assert "~/.codex/skills/deja/scripts/recall-session prior-thread" in hint
    assert "~/.claude/" not in hint
    assert "prior-thread" in hint
    assert "codex exec resume prior-thread" in hint
    assert "report" in hint.lower()
    assert "handoff" in hint.lower()
    assert "terminus" not in hint.lower()


def test_codex_thread_started_sets_session_id() -> None:
    # Breaks when thread.started fails to identify the current session.
    state = CodexBackend().parse(
        _state(), json.dumps({"type": "thread.started", "thread_id": "synthetic-thread"})
    )
    assert state.session_id == "synthetic-thread"


def test_codex_completed_message_supplies_final_text() -> None:
    # Breaks when completed messages lose their report text.
    state = CodexBackend().parse(_state(), json.dumps({
        "type": "item.completed",
        "item": {"id": "synthetic-message", "type": "agent_message", "text": "Done.\nReport."},
    }))
    assert state.result_text == "Done.\nReport."


def test_codex_final_file_overrides_message(tmp_path: Path) -> None:
    # Breaks when finish prefers the stream message over the run's output file.
    output = tmp_path / "unique-final.txt"
    output.write_text("Authoritative report.\n")
    state = StreamState("synthetic-thread", 17, Spend(30, 0.0), "stream report", False)
    state = CodexBackend().finish(state, output)
    assert state.result_text == "Authoritative report.\n"


@pytest.mark.parametrize("event", [
    {"type": "error", "message": "synthetic error"},
    {"type": "turn.failed", "error": {"message": "synthetic failure"}},
])
def test_codex_error_events_mark_failure(event: dict) -> None:
    # Breaks when failed runs are returned as successful reports.
    state = CodexBackend().parse(_state(), json.dumps(event))
    assert state.is_error is True


def test_codex_warning_items_leave_a_real_research_map_standing(fake_cfg: Config, tmp_path: Path) -> None:
    # Breaks when Codex's non-fatal warning items (ignored config keys, a clamped hook timeout)
    # mark the run failed, so a good research map is thrown away as "research failed".
    fixtures = Path(__file__).parent / "fixtures/codex-warnings"
    backend = CodexBackend()
    state = StreamState(None, 0, Spend(0, 0.0), None, False)
    for line in (fixtures / "research-stdout.jsonl").read_text().splitlines():
        state = backend.parse(state, line)
    assert state.is_error is False
    log = tmp_path / "20.jsonl"
    result = RunResult(0, False, replace(state, result_text=(fixtures / "research-final.txt").read_text()), log)
    assert run_failed(result) is False
    m = parse_map("s2", "abc123", result.stream.result_text, fake_cfg)
    assert m is not None
    assert m.files == ("docs/superpowers/specs/m2-launcher-kinds-design.md",)


def test_codex_captured_turn_usage_counts_cache_once_and_replay_is_idempotent() -> None:
    # Breaks when cached input or a repeated usage snapshot is added twice.
    backend = CodexBackend()
    lines = (Path(__file__).parent / "fixtures/codex-real/stdout.jsonl").read_text().splitlines()
    usage = next(line for line in lines if json.loads(line)["type"] == "turn.completed")
    state = StreamState(None, 73, Spend(0, 0.0), None, False)
    state = backend.parse(state, usage)
    assert state.spend.tokens == 27207
    assert state.context_tokens == 73
    assert backend.parse(state, usage) == state


@pytest.mark.parametrize("line", [
    "not json", "null", "[]", '{"type":"future.event","usage":{"input_tokens":999}}',
    '{"type":"thread.started"}', '{"type":"item.completed","item":null}',
    '{"type":"turn.completed","usage":{"input_tokens":"bad"}}',
])
def test_codex_malformed_and_unknown_events_preserve_known_state(line: str) -> None:
    # Breaks when malformed or unknown events erase prior observations or raise.
    state = StreamState("known-thread", 17, Spend(30, 0.0), "known report", True)
    assert CodexBackend().parse(state, line) == state


def test_codex_finish_without_telemetry_is_explicit_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when a final report without rollout telemetry reports success.
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-home"))
    output = tmp_path / "final.txt"
    output.write_text("Completed report.")
    backend = CodexBackend()
    state = backend.parse(_state(), json.dumps({
        "type": "thread.started", "thread_id": "01a1855b-7ba6-79d3-bf98-98c251634b5a",
    }))
    assert backend.finish(state, output).is_error is True


def test_codex_receiver_status_and_duplicate_updates() -> None:
    # Breaks when tool completion completes running receivers or duplicates events.
    backend = CodexBackend()
    item = {
        "id": "synthetic-collab", "type": "collab_tool_call", "tool": "spawn_agent",
        "sender_thread_id": "sender", "receiver_thread_ids": ["receiver"],
        "prompt": "Synthetic task", "status": "completed",
        "agents_states": {"receiver": {"status": "running", "message": None}},
    }
    line = json.dumps({"type": "item.completed", "item": item})
    state = backend.parse(_state(), line)
    assert state.activity.live == frozenset({"receiver"})
    assert [a.task_id for a in state.activity.agents] == ["receiver"]
    assert [e.kind for e in state.activity.events] == ["started"]
    assert backend.parse(state, line).activity == state.activity
    item["agents_states"]["receiver"] = {"status": "completed", "message": "Done"}
    line = json.dumps({"type": "item.completed", "item": item})
    state = backend.parse(state, line)
    assert state.activity.live == frozenset()
    assert [e.kind for e in state.activity.events] == ["started", "finished"]
    assert backend.parse(state, line).activity == state.activity


@pytest.mark.parametrize("role,filename", [("lead", "lead"), ("recut", "divvyer")])
def test_codex_role_overrides_and_fresh_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str, filename: str,
) -> None:
    # Breaks when launch drops role settings, changes quoting or resumes a thread.
    home = tmp_path / "codex"
    agents = home / "agents"
    agents.mkdir(parents=True)
    role_text = 'developer_instructions = "Keep \\"quoted\\" instructions.\\nSecond line."\n'
    role_text += 'model = "synthetic-model"\nmodel_reasoning_effort = "high"\n'
    role_text += '[features]\nmulti_agent = true\nweb_search_request = false\n'
    (agents / f"{filename}.toml").write_text(role_text)
    monkeypatch.setenv("CODEX_HOME", str(home))
    output = tmp_path / "final output.txt"
    argv = CodexBackend().argv(role, _config(tmp_path), tmp_path, output)
    assert argv[:2] == ["codex", "exec"]
    assert "--json" in argv
    assert "--dangerously-bypass-approvals-and-sandbox" in argv
    assert argv[argv.index("-C") + 1] == str(tmp_path)
    assert argv[argv.index("-o") + 1] == str(output)
    assert "resume" not in argv
    overrides = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-c"]
    parsed = tomllib.loads("\n".join(overrides))
    assert parsed["developer_instructions"] == 'Keep "quoted" instructions.\nSecond line.'
    assert parsed["model"] == "synthetic-model"
    assert parsed["model_reasoning_effort"] == "high"
    assert parsed["features"]["multi_agent"] is True
    assert parsed["features"]["web_search_request"] is False
    # Breaks when an override replaces the features table instead of one key.
    override_keys = [
        tomllib.loads(override.split("=", 1)[0] + "= true")
        for override in overrides
    ]
    assert {"features": {"multi_agent": True}} in override_keys
    assert {"features": {"web_search_request": True}} in override_keys
    assert {"features": True} not in override_keys


@pytest.mark.parametrize("content", [None, "not valid = [", "developer_instructions = 42"])
def test_codex_missing_or_invalid_roles_fail_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str | None,
) -> None:
    # Breaks when unavailable or invalid role configuration silently launches.
    agents = tmp_path / "agents"
    agents.mkdir()
    if content is not None:
        (agents / "lead.toml").write_text(content)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    with pytest.raises(ConfigError):
        CodexBackend().argv("lead", _config(tmp_path), tmp_path, tmp_path / "out")


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
