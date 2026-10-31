"""Adapter behavior from relay-backends-design.md, Modules."""

import json
import shlex
import subprocess
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from relay.backends import get_backend, replay
from relay.backends import _snapshot
from relay.backends.base import Launch
from relay.backends.claude import CHILD_ENV, ClaudeBackend
from relay.backends.codex import CodexBackend
from relay.backends.generic import GenericBackend
from relay.config import Config
from relay.errors import ConfigError
from relay.ledger import Spend
from relay.research import parse_map
from relay.retire_gate import REFUSAL
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
    state = CodexBackend().parse(
        _state(),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "synthetic-message",
                    "type": "agent_message",
                    "text": "Done.\nReport.",
                },
            }
        ),
    )
    assert state.result_text == "Done.\nReport."


def test_codex_final_file_overrides_message(tmp_path: Path) -> None:
    # Breaks when finish prefers the stream message over the run's output file.
    output = tmp_path / "unique-final.txt"
    output.write_text("Authoritative report.\n")
    state = StreamState("synthetic-thread", 17, Spend(30, 0.0), "stream report", False)
    state = CodexBackend().finish(state, output)
    assert state.result_text == "Authoritative report.\n"


@pytest.mark.parametrize(
    "event",
    [
        {"type": "error", "message": "synthetic error"},
        {"type": "turn.failed", "error": {"message": "synthetic failure"}},
    ],
)
def test_codex_error_events_mark_failure(event: dict) -> None:
    # Breaks when failed runs are returned as successful reports.
    state = CodexBackend().parse(_state(), json.dumps(event))
    assert state.is_error is True


def test_codex_warning_items_leave_a_real_research_map_standing(
    fake_cfg: Config, tmp_path: Path
) -> None:
    # Breaks when Codex's non-fatal warning items (ignored config keys, a clamped hook timeout)
    # mark the run failed, so a good research map is thrown away as "research failed".
    fixtures = Path(__file__).parent / "fixtures/codex-warnings"
    backend = CodexBackend()
    state = StreamState(None, 0, Spend(0, 0.0), None, False)
    for line in (fixtures / "research-stdout.jsonl").read_text().splitlines():
        state = backend.parse(state, line)
    assert state.is_error is False
    log = tmp_path / "20.jsonl"
    result = RunResult(
        0, False, replace(state, result_text=(fixtures / "research-final.txt").read_text()), log
    )
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


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        "null",
        "[]",
        '{"type":"future.event","usage":{"input_tokens":999}}',
        '{"type":"thread.started"}',
        '{"type":"item.completed","item":null}',
        '{"type":"turn.completed","usage":{"input_tokens":"bad"}}',
    ],
)
def test_codex_malformed_and_unknown_events_preserve_known_state(line: str) -> None:
    # Breaks when malformed or unknown events erase prior observations or raise.
    state = StreamState("known-thread", 17, Spend(30, 0.0), "known report", True)
    assert CodexBackend().parse(state, line) == state


def test_codex_finish_without_telemetry_is_explicit_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when a final report without rollout telemetry reports success.
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-home"))
    output = tmp_path / "final.txt"
    output.write_text("Completed report.")
    backend = CodexBackend()
    state = backend.parse(
        _state(),
        json.dumps(
            {
                "type": "thread.started",
                "thread_id": "01a1855b-7ba6-79d3-bf98-98c251634b5a",
            }
        ),
    )
    assert backend.finish(state, output).is_error is True


def test_codex_receiver_status_and_duplicate_updates() -> None:
    # Breaks when tool completion completes running receivers or duplicates events.
    backend = CodexBackend()
    item = {
        "id": "synthetic-collab",
        "type": "collab_tool_call",
        "tool": "spawn_agent",
        "sender_thread_id": "sender",
        "receiver_thread_ids": ["receiver"],
        "prompt": "Synthetic task",
        "status": "completed",
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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    filename: str,
) -> None:
    # Breaks when launch drops role settings, changes quoting or resumes a thread.
    home = tmp_path / "codex"
    agents = home / "agents"
    agents.mkdir(parents=True)
    role_text = 'developer_instructions = "Keep \\"quoted\\" instructions.\\nSecond line."\n'
    role_text += 'model = "synthetic-model"\nmodel_reasoning_effort = "high"\n'
    role_text += "[features]\nmulti_agent = true\nweb_search_request = false\n"
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
    assert argv[-1] == 'Keep "quoted" instructions.\nSecond line.'
    assert parsed["model"] == "synthetic-model"
    assert parsed["model_reasoning_effort"] == "high"
    assert parsed["features"]["multi_agent"] is True
    assert parsed["features"]["web_search_request"] is False
    # Breaks when an override replaces the features table instead of one key.
    override_keys = [tomllib.loads(override.split("=", 1)[0] + "= true") for override in overrides]
    assert {"features": {"multi_agent": True}} in override_keys
    assert {"features": {"web_search_request": True}} in override_keys
    assert {"features": True} not in override_keys


@pytest.mark.parametrize(
    "role,filename",
    [
        ("lead", "lead"),
        ("recut", "divvyer"),
        ("research", "researcher"),
        ("design", "architect"),
    ],
)
def test_codex_role_instructions_stay_out_of_config_sub_agents_inherit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    filename: str,
) -> None:
    # Breaks when role instructions ride a config override: Codex hands every
    # session override to a spawned built-in agent such as `worker`, which then
    # takes the lead's role as its own and refuses its brief.
    agents = tmp_path / "agents"
    agents.mkdir()
    instructions = f"You are the {filename}; you write no code."
    (agents / f"{filename}.toml").write_text(
        f"developer_instructions = {json.dumps(instructions)}\n"
    )
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    argv = CodexBackend().argv(role, _config(tmp_path), tmp_path, tmp_path / "out")
    overrides = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-c"]
    assert not any(instructions in arg for arg in overrides)
    assert "developer_instructions" not in tomllib.loads("\n".join(overrides))
    # The instructions open the root thread's own prompt; stdin follows as the brief.
    assert argv[-1] == instructions


@pytest.mark.parametrize("content", [None, "not valid = [", "developer_instructions = 42"])
def test_codex_missing_or_invalid_roles_fail_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str | None,
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
    return Config(
        None, None, 100_000, 200_000, 30, ["custom-lead", "--flag"], ["custom-recut"], [], tmp_path
    )


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
    assert ClaudeBackend().argv("lead", cfg, tmp_path, tmp_path / "out") == cfg.lead_command


def test_generic_has_no_telemetry() -> None:
    # Breaks when generic advertises unsupported budget or context telemetry.
    backend = GenericBackend()
    assert backend.capabilities.context is False
    assert backend.capabilities.tokens is False
    assert backend.capabilities.dollars is False
    assert backend.capabilities.subagents is False
    assert backend.parse(_state(), "plain stdout").spend == Spend(0, 0.0)


def test_snapshot_restores_usage_and_old_and_new_agent_measurements(tmp_path: Path) -> None:
    # Breaks when replay loses saved usage, zero costs or old-snapshot unavailable defaults.
    snapshot = json.loads((Path(__file__).parent / "fixtures/cache-cost/snapshot.json").read_text())
    log = tmp_path / "saved.jsonl"
    log.write_text("")
    log.with_suffix(".backend.json").write_text(json.dumps({"backend": "codex"}))
    path = log.with_suffix(".telemetry.json")
    old_snapshot = dict(snapshot)
    old_snapshot.pop("usage")
    old_snapshot["activity"] = {
        "agents": [snapshot["activity"]["agents"][1]],
        "events": [],
        "live": [],
    }
    path.write_text(json.dumps(old_snapshot))
    old_state = _snapshot(path)
    assert old_state.usage == ()
    assert old_state.activity.agents[0].cost_dollars is None
    assert old_state.activity.agents[0].cost_unavailable
    assert replay(log) == old_state
    path.write_text(json.dumps(snapshot))
    state = _snapshot(path)
    assert len(state.usage) == 1
    usage = state.usage[0]
    assert type(usage).__name__ == "Usage"
    assert (usage.thread, usage.model, usage.input, usage.cached_input, usage.output) == (
        "saved-worker",
        "retired-model",
        120,
        70,
        9,
    )
    assert (usage.cache_write_30m, usage.cache_write_12h, usage.unavailable) == (
        20,
        None,
        "12h writes unknown",
    )
    assert state.spend == Spend(129, 0.875)
    measured, old = state.activity.agents
    assert measured.models == ("retired-model", "unavailable")
    assert measured.efforts == ("high", "unavailable")
    assert (measured.cost_dollars, measured.cost_basis, measured.cost_unavailable) == (
        0.0,
        "reported",
        None,
    )
    assert old.models == old.efforts == ()
    assert (old.cost_dollars, old.cost_basis, old.cost_unavailable) == (
        None,
        "none",
        "not reported",
    )
    assert state.activity.events[0].agent == measured
    assert replay(log) == state


def test_snapshot_uses_shared_agent_restoration_for_inventory_and_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when either saved inventory or saved event records bypass shared restoration.
    from relay import agents

    saved = json.loads((Path(__file__).parent / "fixtures/cache-cost/snapshot.json").read_text())
    path = tmp_path / "saved.json"
    path.write_text(json.dumps(saved))
    seen = []
    restore = agents.restore_agent

    def observed(value: dict) -> agents.Agent:
        seen.append(value["task_id"])
        return restore(value)

    monkeypatch.setattr(agents, "restore_agent", observed)
    state = _snapshot(path)
    assert seen.count("saved-worker") == 2
    assert seen.count("old-worker") == 1
    assert len(state.activity.agents) == 2
    assert len(state.activity.events) == 1


def _normalized_readers(monkeypatch: pytest.MonkeyPatch, observations: dict):
    """Synthetic normalized records; these do not claim additional Codex wire fields."""
    from relay.backends.codex_session import SessionReader

    instances = []
    polls = []

    class ObservedReader(SessionReader):
        def __init__(self, home: Path, session_id: str, *, boundary=None):
            super().__init__(home, session_id, boundary=boundary)
            self.sid = session_id
            self.usage = ()
            self.models = ()
            self.efforts = ()
            self.children = ()
            self.unavailable = None
            self.observed = False
            self.model_context_window = 258400
            instances.append(session_id)

        def poll(self, state: StreamState, *, force_scan: bool = False) -> StreamState:
            polls.append((self.sid, force_scan))
            record = observations[self.sid]
            self.usage = record.get("usage", ())
            self.models = record.get("models", ())
            self.efforts = record.get("efforts", ())
            self.children = record.get("children", ())
            self.unavailable = record.get("unavailable")
            self.observed = record.get("observed", True)
            return replace(state, context_tokens=record.get("context", 0))

    monkeypatch.setattr("relay.backends.codex.SessionReader", ObservedReader)
    return instances, polls


def _receiver(
    backend: CodexBackend, state: StreamState, ids: list[str], statuses: dict
) -> StreamState:
    """Synthetic collaboration item using the backend design's documented schema."""
    return backend.parse(
        state,
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "synthetic-metering",
                    "type": "collab_tool_call",
                    "tool": "spawn_agent",
                    "sender_thread_id": state.session_id,
                    "receiver_thread_ids": ids,
                    "prompt": "Synthetic normalized billing",
                    "status": "completed",
                    "agents_states": {
                        sid: {"status": status, "message": None} for sid, status in statuses.items()
                    },
                },
            }
        ),
    )


def test_codex_registry_polls_descendants_once_and_breaks_cycles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when descendant discovery bypasses the reader registry or a cycle creates readers again.
    root, child, grandchild = "root", "child", "grandchild"
    observations = {
        root: {"context": 120, "children": (child,)},
        child: {"context": 800, "children": (grandchild,)},
        grandchild: {"context": 900, "children": (root, child)},
    }
    instances, polls = _normalized_readers(monkeypatch, observations)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    backend = CodexBackend()
    state = backend.parse(_state(), json.dumps({"type": "thread.started", "thread_id": root}))
    state = _receiver(backend, state, [child], {child: "running"})
    state = backend.poll(state)
    state = backend.poll(state)
    assert sorted(instances) == sorted([root, child, grandchild])
    assert all(sum(sid == thread for sid, _ in polls) >= 2 for thread in observations)
    assert state.context_tokens == 120
    assert [agent.task_id for agent in state.activity.agents] == [child, grandchild]


@pytest.mark.parametrize("billed_writes,expected", [(False, 0.00253), (True, 0.00311)])
def test_codex_finish_forces_last_read_and_prices_each_model_without_double_billing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    billed_writes: bool,
    expected: float,
) -> None:
    # Breaks when final enrichment uses stale cumulative rows, full input rates or only the last model.
    from relay.backends.codex_session import Usage

    root, child = "root", "child"
    observations = {
        root: {"context": 120},
        child: {
            "usage": (Usage(child, "gpt-6-astra", 100, 50, 10),),
            "models": ("gpt-6-astra",),
            "efforts": ("high",),
        },
    }
    instances, polls = _normalized_readers(monkeypatch, observations)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    backend = CodexBackend()
    state = backend.parse(_state(), json.dumps({"type": "thread.started", "thread_id": root}))
    state = _receiver(backend, state, [child], {child: "completed"})
    state = backend.poll(state)
    latest = (
        Usage(child, "gpt-6.1-sol", 1000, 600, 100, 100, 50)
        if billed_writes
        else Usage(child, "gpt-6.1-sol", 1000, 800, 100)
    )
    observations[child] = {
        "usage": (Usage(child, "gpt-6-astra", 100, 50, 10), latest),
        "models": ("gpt-6-astra", "gpt-6.1-sol"),
        "efforts": ("high", "medium"),
    }
    output = tmp_path / "final.txt"
    output.write_text("Completed synthetic report.")
    final = backend.finish(state, output)
    (worker,) = final.activity.agents
    assert worker.cost_dollars == pytest.approx(expected)
    assert worker.cost_basis == "api-estimate"
    assert worker.cost_unavailable is None
    assert worker.models == ("gpt-6-astra", "gpt-6.1-sol")
    assert worker.efforts == ("high", "medium")
    assert (root, True) in polls and (child, True) in polls
    again = backend.finish(final, output)
    assert again.activity.agents == final.activity.agents
    assert sorted(instances) == [child, root]


def test_codex_missing_receiver_status_still_enters_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when discovery requires a receiver status and silently omits that thread.
    _normalized_readers(
        monkeypatch,
        {
            "root": {},
            "child": {"observed": False, "unavailable": "rollout missing"},
        },
    )
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    backend = CodexBackend()
    state = backend.parse(_state(), json.dumps({"type": "thread.started", "thread_id": "root"}))
    state = _receiver(backend, state, ["child"], {})
    final = backend.finish(state, tmp_path / "absent-final")
    assert [agent.task_id for agent in final.activity.agents] == ["child"]
    (worker,) = final.activity.agents
    assert worker.cost_dollars is None
    assert worker.cost_unavailable


@pytest.mark.parametrize("problem", ["running", "missing", "malformed", "incomplete"])
def test_codex_partial_final_measurements_keep_inventory_with_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    # Breaks when a partial or unfinished thread's observed usage is presented as its final cost.
    from relay.backends.codex_session import Usage

    child = {
        "usage": (Usage("child", "gpt-6.1-sol", 1000, 800, 100),),
        "models": ("gpt-6.1-sol",),
        "efforts": ("high",),
    }
    if problem != "running":
        child["unavailable"] = f"{problem} telemetry"
    if problem == "missing":
        child.update(usage=(), observed=False)
    _normalized_readers(monkeypatch, {"root": {}, "child": child})
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    backend = CodexBackend()
    state = backend.parse(_state(), json.dumps({"type": "thread.started", "thread_id": "root"}))
    state = _receiver(
        backend, state, ["child"], {"child": "running" if problem == "running" else "completed"}
    )
    final = backend.finish(state, tmp_path / "absent-final")
    assert [agent.task_id for agent in final.activity.agents] == ["child"]
    (worker,) = final.activity.agents
    assert worker.cost_dollars is None
    assert worker.cost_unavailable
    assert worker.models == ("gpt-6.1-sol",)


# relay-run-overhead-design.md, Modules `relay/backends/claude.py`, `relay/backends/codex.py`
# and `relay/backends/generic.py`: each backend's launch description for its child.


@pytest.mark.parametrize("role", ["lead", "recut"])
def test_claude_launch_gives_every_role_the_child_env(role: str, tmp_path: Path) -> None:
    # Breaks when a Claude child of any role launches without
    # CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0, or with other variables beside it.
    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    launch = ClaudeBackend().launch(role, tmp_path / "retire", run_dir)
    assert dict(launch.env) == {"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0"}
    assert dict(launch.env) == dict(CHILD_ENV)


@pytest.mark.parametrize("backend", [CodexBackend, GenericBackend], ids=["codex", "generic"])
@pytest.mark.parametrize("role", ["lead", "recut"])
def test_codex_and_generic_launch_add_nothing(backend: type, role: str, tmp_path: Path) -> None:
    # Breaks when a Codex or generic child is given extra argv or env, Claude's included.
    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    assert backend().launch(role, tmp_path / "retire", run_dir) == Launch()


# relay-run-overhead-design.md, Modules `relay/backends/claude.py` and `relay/retire_gate.py`:
# the retire gate `ClaudeBackend.launch` installs for a lead.

_ROOT = Path(__file__).parent.parent
_EVENT = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": {}})


def _agent_hook_commands(settings: Path) -> list[list[str]]:
    hooks = json.loads(settings.read_text())["hooks"]["PreToolUse"]
    return [
        shlex.split(hook["command"])
        for entry in hooks
        if entry["matcher"] == "Agent"
        for hook in entry["hooks"]
        if hook["type"] == "command"
    ]


def test_claude_lead_launch_installs_the_retire_gate_settings(tmp_path: Path) -> None:
    # Breaks when a lead launches without its settings file, or the file's Agent hook
    # does not run relay.retire_gate on this run's retire flag.
    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    flag = tmp_path / "retire"
    launch = ClaudeBackend().launch("lead", flag, run_dir)
    settings = run_dir / "retire-gate.settings.json"
    assert launch.extra_argv == ("--settings", str(settings))
    assert dict(launch.env) == dict(CHILD_ENV)
    assert _agent_hook_commands(settings) == [
        [sys.executable, "-m", "relay.retire_gate", str(flag)]
    ]


def test_claude_retire_gate_is_for_the_lead_alone(tmp_path: Path) -> None:
    # Breaks when the lead goes without the retire gate, or a role other than lead
    # is given it or a settings file.
    lead_dir, recut_dir = tmp_path / "lead-runs", tmp_path / "recut-runs"
    lead_dir.mkdir()
    recut_dir.mkdir()
    lead = ClaudeBackend().launch("lead", tmp_path / "retire", lead_dir)
    recut = ClaudeBackend().launch("recut", tmp_path / "retire", recut_dir)
    assert lead.extra_argv == ("--settings", str(lead_dir / "retire-gate.settings.json"))
    assert recut.extra_argv == ()
    assert list(recut_dir.iterdir()) == []


@pytest.mark.parametrize("raised,code", [(True, 2), (False, 0)], ids=["raised", "absent"])
def test_installed_retire_gate_command_refuses_only_once_the_flag_is_up(
    raised: bool,
    code: int,
    tmp_path: Path,
) -> None:
    # Breaks when the hook command the lead's settings name does not exit 2 with the
    # refusal once the flag is up, or blocks a dispatch while the flag is down.
    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    flag = tmp_path / "retire"
    ClaudeBackend().launch("lead", flag, run_dir)
    if raised:
        flag.write_text("")
    settings = run_dir / "retire-gate.settings.json"
    assert settings.is_file()
    (command,) = _agent_hook_commands(settings)
    done = subprocess.run(
        command,
        cwd=_ROOT,
        input=_EVENT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == code
    assert done.stderr.rstrip("\n") == (REFUSAL if raised else "")
