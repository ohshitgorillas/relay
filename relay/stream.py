"""Reads claude stream-json event lines."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace

from relay import agents
from relay.ledger import Spend
from relay.pricing import Usage


@dataclass
class StreamState:
    session_id: str | None
    context_tokens: int
    spend: Spend
    result_text: str | None
    is_error: bool
    seen_messages: frozenset[str] = frozenset()
    activity: agents.Activity = agents.Activity()
    usage: tuple[Usage, ...] = ()
    peak_context: int = 0


def _count(usage: dict, key: str) -> int:
    value = usage.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _task_measurements(activity: agents.Activity, event: dict) -> agents.Activity:
    task_id = event.get("task_id")
    if not isinstance(task_id, str) or event.get("subtype") not in {
        "task_started", "task_progress", "task_notification",
    }:
        return activity
    model, effort = event.get("model"), event.get("effort")
    cost = None
    reason = None
    if event.get("subtype") == "task_notification" and "total_cost_usd" in event:
        value = event["total_cost_usd"]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                if math.isfinite(value) and value >= 0:
                    cost = float(value)
            except OverflowError:
                pass
        if cost is None:
            reason = "invalid reported final cost"
    return agents.measured(
        activity, task_id,
        models=(model,) if isinstance(model, str) and model else (),
        efforts=(effort,) if isinstance(effort, str) and effort else (),
        cost_dollars=cost, cost_basis="reported" if cost is not None else "none",
        cost_unavailable=reason,
    )


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
    elif kind == "system":
        activity = agents.feed(state.activity, event)
        activity = _task_measurements(activity, event)
        if activity is not state.activity:
            return replace(state, activity=activity)
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
            if isinstance(event.get("parent_tool_use_id"), str):
                return replace(state, spend=spend, seen_messages=seen)
            return replace(
                state, context_tokens=context, spend=spend, seen_messages=seen,
                peak_context=max(state.peak_context, context),
            )
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
