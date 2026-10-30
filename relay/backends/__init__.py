"""Backend selection and historical run replay."""

import json
from pathlib import Path

from relay import agents
from relay.agents import Activity, Event
from relay.backends.base import Backend
from relay.errors import ConfigError
from relay.ledger import Spend
from relay.pricing import Usage
from relay.stream import StreamState


def get_backend(name: str) -> Backend:
    """Create an adapter whose resources belong to just one run."""
    if name == "claude":
        from relay.backends.claude import ClaudeBackend

        return ClaudeBackend()
    if name == "generic":
        from relay.backends.generic import GenericBackend

        return GenericBackend()
    if name == "codex":
        from relay.backends.codex import CodexBackend

        return CodexBackend()
    raise ConfigError(f"unknown backend {name!r}")


def _snapshot(path: Path) -> StreamState:
    """Restore JSON from asdict(StreamState), with sets encoded as lists."""
    try:
        data = json.loads(path.read_text())
        spend = Spend(**data["spend"])
        activity = data.get("activity", {})
        activity = Activity(
            agents=tuple(agents.restore_agent(agent) for agent in activity.get("agents", [])),
            live=frozenset(activity.get("live", [])),
            events=tuple(
                Event(event["kind"], agents.restore_agent(event["agent"]), event["live"])
                for event in activity.get("events", [])
            ),
        )
        return StreamState(
            **{
                **data,
                "spend": spend,
                "activity": activity,
                "seen_messages": frozenset(data.get("seen_messages", [])),
                "usage": tuple(Usage(**usage) for usage in data.get("usage", [])),
            }
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise ConfigError(f"cannot replay telemetry {path}: {exc}") from exc


def replay(log: Path) -> StreamState:
    """Replay saved observations, without polling a backend's live resources.

    Numbered logs use .backend.json metadata containing a backend name and an
    optional .telemetry.json final normalized snapshot. Unmarked logs are Claude.
    """
    metadata = log.with_suffix(".backend.json")
    name = "claude"
    if metadata.exists():
        try:
            name = json.loads(metadata.read_text())["backend"]
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            raise ConfigError(f"cannot read backend metadata {metadata}: {exc}") from exc
    backend = get_backend(name)
    telemetry = log.with_suffix(".telemetry.json")
    if telemetry.exists():
        return _snapshot(telemetry)
    state = StreamState(None, 0, Spend(0, 0.0), None, False)
    with log.open() as handle:
        for line in handle:
            state = backend.parse(state, line)
    return state
