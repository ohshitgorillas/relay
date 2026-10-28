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
