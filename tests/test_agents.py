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
    return json.dumps({
        "type": "system", "subtype": "task_started", "task_id": task_id,
        "description": description, "subagent_type": name, "task_type": "local_agent",
    })


def _finished(task_id: str, usage: dict | None = None, status: str = "completed") -> str:
    event = {"type": "system", "subtype": "task_notification", "task_id": task_id, "status": status}
    if usage is not None:
        event["usage"] = usage
    return json.dumps(event)


def test_only_local_agents_are_counted_and_background_shell_tasks_are_not() -> None:
    activity = _fixture()
    assert [(a.task_id, a.name) for a in activity.agents] == [("a1", "builder"), ("a2", "test-writer")]


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
    activity = _fold([
        _started("a1"),
        _finished("a1", {"total_tokens": 20000, "duration_ms": 1000}),
        _started("a1"),
        _finished("a1", {"total_tokens": 26000, "duration_ms": 800}),
    ])
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
    later = _fold([_started("a1"), _finished("a1", {"total_tokens": 300, "duration_ms": 30}), _started("a2")])
    merged = agents.merge(first, later)
    assert [(a.task_id, a.context) for a in merged.agents] == [("a1", 300), ("a2", 0)]


def test_duration_reads_in_seconds_minutes_or_hours() -> None:
    assert agents.duration(36943) == "36.9s"
    assert agents.duration(177_000) == "2m57s"
    assert agents.duration(3_780_000) == "1h03m"
