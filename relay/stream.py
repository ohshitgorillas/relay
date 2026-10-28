"""Reads claude stream-json event lines."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

from relay.ledger import Spend


@dataclass
class StreamState:
    session_id: str | None
    context_tokens: int
    spend: Spend
    result_text: str | None
    is_error: bool
    seen_messages: frozenset[str] = frozenset()


def _count(usage: dict, key: str) -> int:
    value = usage.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def feed(state: StreamState, line: str) -> StreamState:
    try:
        event = json.loads(line)
    except (ValueError, RecursionError):
        return state
    if not isinstance(event, dict):
        return state
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        if state.session_id is None and isinstance(event.get("session_id"), str):
            return replace(state, session_id=event["session_id"])
    elif kind == "assistant":
        message = event.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        message_id = message.get("id") if isinstance(message, dict) else None
        if isinstance(usage, dict) and message_id not in state.seen_messages:
            context = (
                _count(usage, "input_tokens")
                + _count(usage, "cache_creation_input_tokens")
                + _count(usage, "cache_read_input_tokens")
            )
            tokens = context + _count(usage, "output_tokens")
            spend = Spend(tokens=state.spend.tokens + tokens, dollars=state.spend.dollars)
            seen = state.seen_messages | {message_id} if isinstance(message_id, str) else state.seen_messages
            return replace(state, context_tokens=context, spend=spend, seen_messages=seen)
    elif kind == "result":
        cost = event.get("total_cost_usd")
        dollars = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else 0.0
        text = event.get("result")
        return replace(
            state,
            result_text=text if isinstance(text, str) else None,
            is_error=bool(event.get("is_error", False)),
            spend=Spend(tokens=state.spend.tokens, dollars=dollars),
        )
    return state
