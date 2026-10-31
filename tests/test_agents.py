"""Tests for `relay/agents.py`: a stream's `task_*` events folded into the subagents it spawned."""

from __future__ import annotations

import json
from pathlib import Path

from relay import agents
from relay.agents import Activity

FIXTURES = Path(__file__).parent / "fixtures"


def _fold(lines: list[str], activity: Activity = Activity()) -> Activity:
    for line in lines:
        event = json.loads(line)
        if event.get("type") == "system":
            activity = agents.feed(activity, event)
    return activity


def _fixture() -> Activity:
    return _fold((FIXTURES / "stream-agents.jsonl").read_text().splitlines())


def _started(task_id: str, name: str = "builder", description: str = "Build it") -> str:
    return json.dumps(
        {
            "type": "system",
            "subtype": "task_started",
            "task_id": task_id,
            "description": description,
            "subagent_type": name,
            "task_type": "local_agent",
        }
    )


def _finished(task_id: str, usage: dict | None = None, status: str = "completed") -> str:
    event = {"type": "system", "subtype": "task_notification", "task_id": task_id, "status": status}
    if usage is not None:
        event["usage"] = usage
    return json.dumps(event)


def test_only_local_agents_are_counted_and_background_shell_tasks_are_not() -> None:
    activity = _fixture()
    assert [(a.task_id, a.name) for a in activity.agents] == [
        ("a1", "builder"),
        ("a2", "test-writer"),
    ]


def test_a_finish_carries_its_reported_context_time_and_status() -> None:
    builder = _fixture().agents[0]
    assert (builder.context, builder.duration_ms, builder.status) == (21844, 36943, "completed")


def test_a_finish_without_usage_keeps_the_last_progress_usage() -> None:
    writer = _fixture().agents[1]
    assert (writer.context, writer.duration_ms, writer.status) == (41000, 95000, "failed")


def test_events_come_in_stream_order_with_the_subagents_live_after_each() -> None:
    events = _fixture().events
    assert [(e.kind, e.agent.task_id, e.live) for e in events] == [
        ("started", "a1", 1),
        ("started", "a2", 2),
        ("finished", "a1", 1),
        ("finished", "a2", 0),
    ]
    assert _fixture().live == frozenset()


def test_context_is_the_last_reported_size_not_a_sum() -> None:
    activity = _fold(
        [
            _started("a1"),
            _finished("a1", {"total_tokens": 20000, "duration_ms": 1000}),
            _started("a1"),
            _finished("a1", {"total_tokens": 26000, "duration_ms": 800}),
        ]
    )
    assert len(activity.agents) == 1
    agent = activity.agents[0]
    assert agent.context == 26000
    assert agent.duration_ms == 1000
    assert [e.kind for e in activity.events] == ["started", "finished", "started", "finished"]


def test_a_finish_for_an_agent_never_started_here_changes_nothing() -> None:
    activity = _fold([_finished("zz", {"total_tokens": 5, "duration_ms": 5})])
    assert activity == Activity()


def test_a_summary_counts_agents_sums_their_time_and_names_the_biggest_by_context() -> None:
    summary = agents.summarise(_fixture())
    assert summary.count == 2
    assert summary.duration_ms == 36943 + 95000
    assert summary.biggest is not None and summary.biggest.name == "test-writer"


def test_an_empty_summary_has_no_biggest() -> None:
    assert agents.summarise(Activity()) == agents.Summary(0, 0, None)


def test_merge_keeps_one_copy_of_an_agent_both_runs_hold_taken_from_the_later() -> None:
    first = _fold([_started("a1"), _finished("a1", {"total_tokens": 100, "duration_ms": 10})])
    later = _fold(
        [_started("a1"), _finished("a1", {"total_tokens": 300, "duration_ms": 30}), _started("a2")]
    )
    merged = agents.merge(first, later)
    assert [(a.task_id, a.context) for a in merged.agents] == [("a1", 300), ("a2", 0)]


def test_duration_reads_in_seconds_minutes_or_hours() -> None:
    assert agents.duration(36943) == "36.9s"
    assert agents.duration(177_000) == "2m57s"
    assert agents.duration(3_780_000) == "1h03m"


def test_measurements_keep_distinct_settings_and_replace_final_cost() -> None:
    # Breaks when measurements add cumulative costs, discard settings or change lifecycle.
    activity = _fold([_started("a1"), _started("a2")])
    before = activity
    activity = agents.measured(
        activity,
        "a1",
        models=("observed-one",),
        efforts=("high",),
        cost_dollars=0.7,
        cost_basis="api-estimate",
        cost_unavailable=None,
    )
    activity = agents.measured(
        activity,
        "a1",
        models=("unavailable", "observed-two", "observed-one"),
        efforts=("unavailable", "medium", "high"),
        cost_dollars=0.9,
        cost_basis="api-estimate",
        cost_unavailable=None,
    )
    agent = activity.agents[0]
    assert agent.models == ("observed-one", "unavailable", "observed-two")
    assert agent.efforts == ("high", "unavailable", "medium")
    assert (agent.cost_dollars, agent.cost_basis, agent.cost_unavailable) == (
        0.9,
        "api-estimate",
        None,
    )
    assert [a.task_id for a in activity.agents] == ["a1", "a2"]
    assert activity.live == before.live
    assert activity.events == before.events
    assert (
        agents.measured(
            activity,
            "a1",
            models=(),
            efforts=(),
            cost_dollars=None,
            cost_basis="none",
            cost_unavailable=None,
        ).agents[0]
        == agent
    )


def test_measurement_does_not_discover_an_unseen_agent() -> None:
    # Breaks when enrichment invents an agent or lifecycle event.
    activity = _fold([_started("known")])
    assert (
        agents.measured(
            activity,
            "unseen",
            models=("observed",),
            efforts=("high",),
            cost_dollars=0.1,
            cost_basis="reported",
            cost_unavailable=None,
        )
        == activity
    )


def test_restore_distinguishes_unmeasured_from_known_zero_and_restores_tuples() -> None:
    # Breaks when old snapshots imply a zero cost or JSON lists are not restored.
    old = agents.restore_agent({"task_id": "old", "name": "builder", "description": "old"})
    assert old.models == old.efforts == ()
    assert (old.cost_dollars, old.cost_basis, old.cost_unavailable) == (
        None,
        "none",
        "not reported",
    )
    zero = agents.restore_agent(
        {
            "task_id": "zero",
            "name": "builder",
            "description": "zero",
            "models": ["observed"],
            "efforts": ["unavailable"],
            "cost_dollars": 0.0,
            "cost_basis": "reported",
            "cost_unavailable": None,
        }
    )
    assert zero.models == ("observed",)
    assert zero.efforts == ("unavailable",)
    assert (zero.cost_dollars, zero.cost_basis, zero.cost_unavailable) == (0.0, "reported", None)


def test_resumed_merge_preserves_measurements_with_later_lifecycle() -> None:
    # Breaks when later-run lifecycle replacement erases earlier measured metadata.
    first = Activity(
        (
            agents.Agent(
                "a1",
                "builder",
                "first",
                100,
                10,
                "completed",
                ("observed-one",),
                ("high",),
                0.25,
                "reported",
                None,
            ),
        )
    )
    later = _fold(
        [
            _started("a1", description="resumed"),
            _finished("a1", {"total_tokens": 300, "duration_ms": 30}),
            _started("a2"),
        ]
    )
    merged = agents.merge(first, later)
    assert [a.task_id for a in merged.agents] == ["a1", "a2"]
    agent = merged.agents[0]
    assert (agent.description, agent.context, agent.duration_ms, agent.status) == (
        "resumed",
        300,
        30,
        "completed",
    )
    assert (agent.models, agent.efforts, agent.cost_dollars, agent.cost_basis) == (
        ("observed-one",),
        ("high",),
        0.25,
        "reported",
    )


def test_repeated_task_notifications_keep_one_measured_inventory_row() -> None:
    # Breaks when repeated lifecycle notifications erase measurements or add costs.
    activity = _fold([_started("a1")])
    activity = agents.measured(
        activity,
        "a1",
        models=("observed",),
        efforts=("high",),
        cost_dollars=0.4,
        cost_basis="reported",
        cost_unavailable=None,
    )
    activity = _fold([_finished("a1"), _finished("a1")], activity)
    assert len(activity.agents) == 1
    assert activity.agents[0].cost_dollars == 0.4
    assert activity.agents[0].models == ("observed",)
    assert activity.live == frozenset()


# `Agent.peak` (relay-stats-design.md, Modules `relay/agents.py` (extended); Order 1).


def test_peak_is_the_largest_total_tokens_reported_while_context_is_the_last() -> None:
    # Breaks when: `peak` is not kept, follows the last report down, or sums the reports.
    activity = _fold(
        [
            _started("a1"),
            _finished("a1", {"total_tokens": 30000, "duration_ms": 1000}),
            _started("a1"),
            _finished("a1", {"total_tokens": 20000, "duration_ms": 800}),
        ]
    )
    agent = activity.agents[0]
    assert (agent.peak, agent.context) == (30000, 20000)


def test_peak_rises_with_a_larger_later_report() -> None:
    # Breaks when: `peak` keeps only the first report.
    activity = _fold(
        [
            _started("a1"),
            _finished("a1", {"total_tokens": 20000, "duration_ms": 1000}),
            _started("a1"),
            _finished("a1", {"total_tokens": 26000, "duration_ms": 800}),
        ]
    )
    assert activity.agents[0].peak == 26000


def test_an_agent_with_no_reported_usage_has_peak_zero() -> None:
    # Breaks when: `peak` defaults to anything but 0.
    assert _fold([_started("a1")]).agents[0].peak == 0
    assert agents.Agent("a1", "builder", "Build it").peak == 0


def test_restore_reads_peak_when_present_and_otherwise_leaves_it_zero() -> None:
    # Breaks when: a saved peak is dropped on restore, or an older snapshot invents one.
    saved = agents.restore_agent(
        {
            "task_id": "a1",
            "name": "builder",
            "description": "new",
            "context": 20000,
            "peak": 30000,
        }
    )
    old = agents.restore_agent(
        {"task_id": "a2", "name": "builder", "description": "old", "context": 20000}
    )
    assert (saved.peak, saved.context) == (30000, 20000)
    assert (old.peak, old.context) == (0, 20000)
