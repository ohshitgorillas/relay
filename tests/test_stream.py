"""Red tests for Relay's stream-json reader (design: Modules `relay/stream.py`; Order 9).

The stream-json lines come from `tests/fixtures/` (design: Homes, test fakes and fixtures).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from relay.ledger import Spend
from relay.stream import StreamState, feed

FIXTURES = Path(__file__).parent / "fixtures"

# tests/fixtures/stream-lead.jsonl, by line:
#   0 init, session "sess-lead-1"
#   1 assistant msg_01: input 3, cache_creation 1200, cache_read 5000, output 40
#   2 user tool result
#   3 assistant msg_02: input 7, cache_creation 100, cache_read 900, output 25
#   4 result: success, "Step committed.\nDONE", total_cost_usd 0.4321
# tests/fixtures/stream-error.jsonl, by line:
#   0 init, session "sess-lead-2"
#   1 assistant msg_11: input 5, cache_creation 0, cache_read 2000, output 10
#   2 result: is_error true, "Prompt is too long", no total_cost_usd


def _lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text().splitlines()


def _fresh() -> StreamState:
    return StreamState(
        session_id=None, context_tokens=0, spend=Spend(tokens=0, dollars=0.0),
        result_text=None, is_error=False,
    )


def _feed_all(state: StreamState, lines: list[str]) -> StreamState:
    for line in lines:
        state = feed(state, line)
    return state


def _fields(state: StreamState) -> dict:
    return dataclasses.asdict(state)


# Behavior 1: `relay/stream.py`: reads the `claude -p --output-format stream-json` event lines.


def test_session_id_comes_from_the_init_event() -> None:
    # Breaks when: feed does not take session_id from the system init event.
    state = feed(_fresh(), _lines("stream-lead.jsonl")[0])
    assert state.session_id == "sess-lead-1"


def test_session_id_is_the_init_events_even_when_later_events_name_another() -> None:
    # Breaks when: feed copies session_id from every event that carries one.
    init, *rest = _lines("stream-error.jsonl")
    others = []
    for line in rest:
        event = json.loads(line)
        event["session_id"] = "sess-other"
        others.append(json.dumps(event))
    state = _feed_all(_fresh(), [init, *others])
    assert state.session_id == "sess-lead-2"


def test_result_text_and_is_error_are_unset_before_the_result_event() -> None:
    # Breaks when: an assistant or user event's text is taken as the result text.
    state = _feed_all(_fresh(), _lines("stream-lead.jsonl")[:4])
    assert state.result_text is None
    assert state.is_error is False


def test_result_text_comes_from_the_result_event() -> None:
    # Breaks when: feed does not take result_text from the result event's text.
    state = _feed_all(_fresh(), _lines("stream-lead.jsonl"))
    assert state.result_text == "Step committed.\nDONE"
    assert state.is_error is False


def test_is_error_comes_from_an_error_result_event() -> None:
    # Breaks when: feed ignores the result event's is_error.
    state = _feed_all(_fresh(), _lines("stream-error.jsonl"))
    assert state.is_error is True
    assert state.result_text == "Prompt is too long"


# Behavior 2: latest assistant message: input + cache_creation + cache_read


def test_context_tokens_are_input_plus_cache_creation_plus_cache_read() -> None:
    # Breaks when: output tokens are counted, or either cache count is left out.
    state = _feed_all(_fresh(), _lines("stream-lead.jsonl")[:2])
    assert state.context_tokens == 3 + 1200 + 5000


def test_context_tokens_follow_the_latest_assistant_message() -> None:
    # Breaks when: context_tokens sums assistant messages or keeps the largest one.
    state = _feed_all(_fresh(), _lines("stream-lead.jsonl")[:4])
    assert state.context_tokens == 7 + 100 + 900


def test_context_tokens_are_not_changed_by_the_result_event() -> None:
    # Breaks when: the result event's usage is taken as the latest assistant message.
    state = _feed_all(_fresh(), _lines("stream-lead.jsonl"))
    assert state.context_tokens == 7 + 100 + 900


# Behavior 3: running sum of usage; dollars filled from the result event


def test_spend_tokens_count_input_output_and_both_caches() -> None:
    # Breaks when: any of the four usage counts is left out of spend.tokens.
    state = _feed_all(_fresh(), _lines("stream-lead.jsonl")[:2])
    assert state.spend.tokens == 3 + 1200 + 5000 + 40


def test_spend_tokens_are_a_running_sum_over_assistant_messages() -> None:
    # Breaks when: spend.tokens holds only the latest message's usage.
    state = _feed_all(_fresh(), _lines("stream-lead.jsonl")[:4])
    assert state.spend.tokens == (3 + 1200 + 5000 + 40) + (7 + 100 + 900 + 25)


def test_dollars_stay_zero_before_the_result_event() -> None:
    # Breaks when: dollars are filled from anything but the result event.
    state = _feed_all(_fresh(), _lines("stream-lead.jsonl")[:4])
    assert state.spend.dollars == 0.0


def test_the_result_event_fills_dollars_and_adds_no_tokens() -> None:
    # Breaks when: total_cost_usd is not read into spend.dollars, or the result event's
    # usage (the run's cumulative total) is added on top of the running sum.
    state = _feed_all(_fresh(), _lines("stream-lead.jsonl"))
    assert state.spend.dollars == 0.4321
    assert state.spend.tokens == (3 + 1200 + 5000 + 40) + (7 + 100 + 900 + 25)


def test_dollars_are_zero_when_the_result_event_has_no_cost() -> None:
    # Breaks when: a result event without total_cost_usd raises or sets a non-zero cost.
    state = _feed_all(_fresh(), _lines("stream-error.jsonl"))
    assert state.spend.dollars == 0.0
    assert state.spend.tokens == 5 + 0 + 2000 + 10


# Behavior 4: ignores lines that are not JSON events

NOT_EVENTS = [
    "",
    "   ",
    "not json",
    "Error: something went wrong",
    '{"type": "assistant", "message": ',
    "[1, 2]",
    "42",
    '"text"',
    "null",
    "true",
    '{"no_type": 1}',
]


@pytest.mark.parametrize("line", NOT_EVENTS)
def test_a_line_that_is_not_a_json_event_leaves_the_state_unchanged(line: str) -> None:
    # Breaks when: feed raises on, or takes any value from, a line that is not a JSON event.
    state = _feed_all(_fresh(), _lines("stream-lead.jsonl")[:2])
    before = _fields(state)
    assert _fields(feed(state, line)) == before


@pytest.mark.parametrize("line", NOT_EVENTS)
def test_a_line_that_is_not_a_json_event_leaves_a_fresh_state_unchanged(line: str) -> None:
    # Breaks when: feed raises on, or takes any value from, a line that is not a JSON event.
    assert _fields(feed(_fresh(), line)) == _fields(_fresh())


def test_lines_that_are_not_json_events_between_events_change_nothing() -> None:
    # Breaks when: a stray line between events resets or skews the running state.
    lines = _lines("stream-lead.jsonl")
    clean = _feed_all(_fresh(), lines)
    mixed = []
    for line in lines:
        mixed.extend(["not json", line, ""])
    assert _fields(_feed_all(_fresh(), mixed)) == _fields(clean)


def test_claude_task_measurements_preserve_reported_zero_and_run_total() -> None:
    # Breaks when agent costs replace aggregate spend or parent settings leak into workers.
    state = _feed_all(_fresh(), _lines("cache-cost/claude-agent-measurements.jsonl"))
    measured, unmeasured = state.activity.agents
    assert measured.models == ("worker-model",)
    assert measured.efforts == ("high",)
    assert (measured.cost_dollars, measured.cost_basis, measured.cost_unavailable) == (0.0, "reported", None)
    assert unmeasured.models == unmeasured.efforts == ()
    assert unmeasured.cost_dollars is None
    assert unmeasured.cost_basis == "none"
    assert unmeasured.cost_unavailable
    assert state.spend.dollars == 0.75
    assert state.usage == ()


def test_claude_task_positive_final_cost_preserves_reported_charge_and_run_total() -> None:
    # Breaks when valid positive worker charges are replaced with known zero.
    lines = _lines("cache-cost/claude-agent-measurements.jsonl")
    completion = json.loads(lines[2])
    completion["total_cost_usd"] = 0.125
    lines[2] = json.dumps(completion)
    state = _feed_all(_fresh(), lines)
    measured, unmeasured = state.activity.agents
    assert measured.cost_dollars == 0.125
    assert measured.cost_basis == "reported"
    assert measured.cost_unavailable is None
    assert unmeasured.cost_dollars is None
    assert state.spend.dollars == 0.75


@pytest.mark.parametrize("bad_cost", [-0.1, True, "0.3", float("inf"), float("nan")])
def test_claude_invalid_task_cost_never_becomes_a_final_measurement(bad_cost: object) -> None:
    # Breaks when explicitly associated invalid billing values become final numeric costs.
    lines = _lines("cache-cost/claude-agent-measurements.jsonl")[:2]
    lines.append(json.dumps({
        "type": "system", "subtype": "task_notification", "task_id": "synthetic-worker",
        "status": "completed", "model": "worker-model", "effort": "high",
        "total_cost_usd": bad_cost,
    }))
    agent = _feed_all(_fresh(), lines).activity.agents[0]
    assert agent.models == ("worker-model",)
    assert agent.efforts == ("high",)
    assert agent.cost_dollars is None
    assert agent.cost_basis == "none"
    assert agent.cost_unavailable


def test_claude_progress_cost_is_not_a_final_cost_and_missing_settings_stay_unknown() -> None:
    # Breaks when partial usage becomes final billing or unknown turn settings are guessed.
    lines = _lines("cache-cost/claude-agent-measurements.jsonl")[:2]
    lines.append(json.dumps({
        "type": "system", "subtype": "task_progress", "task_id": "synthetic-worker",
        "model": "unavailable", "effort": "unavailable", "total_cost_usd": 0.2,
        "usage": {"total_tokens": 900},
    }))
    agent = _feed_all(_fresh(), lines).activity.agents[0]
    assert agent.models == ("worker-model", "unavailable")
    assert agent.efforts == ("high", "unavailable")
    assert agent.context == 900
    assert agent.cost_dollars is None
    assert agent.cost_unavailable


# Run overhead (design: docs/superpowers/specs/relay-run-overhead-design.md, Modules
# `relay/stream.py`; Order 1). tests/fixtures/stream-subagent-context.jsonl, by line:
#   0 init, session "sess-sub-1"
#   1 assistant msg_31, parent_tool_use_id null: input 2, cache_creation 500, cache_read 1500, output 30
#   2 assistant msg_32, parent_tool_use_id "toolu_31": input 50, cache_creation 20000, cache_read 80000, output 100
#   3 assistant msg_33, parent_tool_use_id null: input 4, cache_creation 100, cache_read 2400, output 15
#   4 assistant msg_34, parent_tool_use_id "toolu_31": input 6, cache_creation 0, cache_read 90000, output 50
#   5 result: success, "Step committed.\nDONE", total_cost_usd 0.9

SUBAGENT = "stream-subagent-context.jsonl"
MAIN_FIRST_CONTEXT = 2 + 500 + 1500
MAIN_LAST_CONTEXT = 4 + 100 + 2400
MAIN_FIRST_SPEND = 2 + 500 + 1500 + 30
SUB_FIRST_SPEND = 50 + 20000 + 80000 + 100
MAIN_LAST_SPEND = 4 + 100 + 2400 + 15
SUB_LAST_SPEND = 6 + 0 + 90000 + 50


# Behavior: measures the main thread's context only. Subagent usage still counts toward spend.


def test_a_subagent_event_adds_its_usage_to_spend_without_setting_context_tokens() -> None:
    # Breaks when: a subagent's usage is dropped from spend.tokens, or its context is taken
    # as context_tokens.
    state = _feed_all(_fresh(), _lines(SUBAGENT)[:3])
    assert state.context_tokens == MAIN_FIRST_CONTEXT
    assert state.spend.tokens == MAIN_FIRST_SPEND + SUB_FIRST_SPEND


def test_a_subagent_message_is_seen_without_setting_context_tokens() -> None:
    # Breaks when: a subagent event is left out of seen_messages, or sets context_tokens.
    state = _feed_all(_fresh(), _lines(SUBAGENT)[:3])
    assert state.context_tokens == MAIN_FIRST_CONTEXT
    assert "msg_32" in state.seen_messages


def test_a_whole_run_spends_every_message_and_measures_only_the_main_thread() -> None:
    # Breaks when: the run's spend leaves out subagent turns, context_tokens ends at the
    # last subagent event's context, or peak_context is never set or is taken from a subagent
    # event (design: Modules `relay/stream.py`, peak_context is the largest context_tokens seen
    # in the run; a subagent event leaves it unchanged).
    state = _feed_all(_fresh(), _lines(SUBAGENT))
    assert state.context_tokens == MAIN_LAST_CONTEXT
    assert state.spend.tokens == MAIN_FIRST_SPEND + SUB_FIRST_SPEND + MAIN_LAST_SPEND + SUB_LAST_SPEND
    assert state.spend.dollars == 0.9
    assert state.peak_context == max(MAIN_FIRST_CONTEXT, MAIN_LAST_CONTEXT)


# Behavior: the main thread's latest context; subagent events never set it


def test_a_subagent_event_before_any_main_thread_event_leaves_context_tokens_at_zero() -> None:
    # Breaks when: a subagent event sets context_tokens while the main thread has none yet.
    lines = _lines(SUBAGENT)
    state = _feed_all(_fresh(), [lines[0], lines[2]])
    assert state.context_tokens == 0


def test_a_subagent_event_after_the_main_threads_latest_leaves_context_tokens_unchanged() -> None:
    # Breaks when: the last subagent event's context replaces the main thread's latest.
    before = _feed_all(_fresh(), _lines(SUBAGENT)[:4])
    after = feed(before, _lines(SUBAGENT)[4])
    assert after.context_tokens == MAIN_LAST_CONTEXT
