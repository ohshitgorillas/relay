"""Folds a stream's `task_*` events into the subagents it spawned."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal


@dataclass(frozen=True)
class Agent:
    task_id: str
    name: str  # the subagent type, such as `builder`
    description: str
    context: int = 0  # the last `total_tokens` reported: the agent's context size, not a sum
    duration_ms: int | None = None  # the largest reported; a continued agent reports again
    status: str | None = None  # the last finish status: completed, failed or stopped


@dataclass(frozen=True)
class Event:
    kind: Literal["started", "finished"]
    agent: Agent
    live: int  # subagents live after this event, the lead not counted


@dataclass(frozen=True)
class Activity:
    agents: tuple[Agent, ...] = ()  # every agent seen, in the order it first started
    live: frozenset[str] = frozenset()
    events: tuple[Event, ...] = ()


@dataclass(frozen=True)
class Summary:
    count: int
    duration_ms: int
    biggest: Agent | None


def _text(event: dict, key: str) -> str:
    value = event.get(key)
    return value if isinstance(value, str) else ""


def _int(usage: object, key: str) -> int | None:
    value = usage.get(key) if isinstance(usage, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _with_usage(agent: Agent, usage: object) -> Agent:
    context = _int(usage, "total_tokens")
    duration = _int(usage, "duration_ms")
    if context is not None:
        agent = replace(agent, context=context)
    if duration is not None:
        agent = replace(agent, duration_ms=max(duration, agent.duration_ms or 0))
    return agent


def feed(activity: Activity, event: dict) -> Activity:
    """`activity` after one parsed `system` event; events that are not an agent's change nothing."""
    subtype = event.get("subtype")
    task_id = event.get("task_id")
    if not isinstance(task_id, str):
        return activity
    known = {agent.task_id: index for index, agent in enumerate(activity.agents)}
    agents = list(activity.agents)
    if subtype == "task_started":
        if event.get("task_type") != "local_agent":
            return activity
        if task_id in known:
            agent = agents[known[task_id]]
        else:
            agent = Agent(task_id, _text(event, "subagent_type"), _text(event, "description"))
            agents.append(agent)
        live = activity.live | {task_id}
        return Activity(
            tuple(agents), live, activity.events + (Event("started", agent, len(live)),)
        )
    if task_id not in known:
        return activity
    index = known[task_id]
    if subtype == "task_progress":
        agents[index] = _with_usage(agents[index], event.get("usage"))
        return replace(activity, agents=tuple(agents))
    if subtype == "task_notification":
        agent = _with_usage(agents[index], event.get("usage"))
        agent = replace(agent, status=_text(event, "status") or None)
        agents[index] = agent
        if task_id not in activity.live:
            return replace(activity, agents=tuple(agents))
        live = activity.live - {task_id}
        return Activity(
            tuple(agents), live, activity.events + (Event("finished", agent, len(live)),)
        )
    return activity


def merge(first: Activity, later: Activity) -> Activity:
    """Two runs' agents as one: an agent both hold is taken from `later`, where it ran last."""
    ids = {agent.task_id for agent in later.agents}
    kept = tuple(agent for agent in first.agents if agent.task_id not in ids)
    return Activity(kept + later.agents, later.live, first.events + later.events)


def summarise(activity: Activity) -> Summary:
    agents = activity.agents
    biggest = max(agents, key=lambda agent: agent.context, default=None)
    return Summary(
        count=len(agents),
        duration_ms=sum(agent.duration_ms or 0 for agent in agents),
        biggest=biggest,
    )


def duration(ms: int) -> str:
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m{rest:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"
