"""Turns a state directory into its runs: each ledger line paired with its replayed run log."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from relay import agents
from relay.backends import replay
from relay.errors import ConfigError
from relay.ledger import Ledger
from relay.state import State
from relay.stream import StreamState


@dataclass(frozen=True)
class Run:
    kind: str  # the ledger line's "kind": lead, recut, research, ask, design
    section: str
    session: str
    log: Path
    stream: StreamState  # replayed from `log`


@dataclass(frozen=True)
class History:
    runs: tuple[Run, ...]  # in the order they ran
    skipped_logs: int  # logs that could not be replayed


def read(state: State, ledger: Ledger) -> History:
    """Each ledger line naming a session, paired with the run log it made.

    Runs are numbered and ledgered in the order they ran, so a session the ledger names
    more than once pairs its logs with its ledger lines in that order.
    """
    lines: dict[str, list[tuple[str, str]]] = {}
    for entry in ledger.entries():
        section, session = entry.get("section"), entry.get("session")
        if isinstance(section, str) and isinstance(session, str):
            kind = entry.get("kind")
            lines.setdefault(session, []).append((kind if isinstance(kind, str) else "", section))
    runs: list[Run] = []
    skipped = 0
    for log in state.run_logs():
        try:
            stream = replay(log)
        except (OSError, ConfigError):
            skipped += 1
            continue
        session = stream.session_id or ""
        owners = lines.get(session)
        if not owners:
            continue
        kind, section = owners.pop(0) if len(owners) > 1 else owners[0]
        runs.append(Run(kind=kind, section=section, session=session, log=log, stream=stream))
    return History(runs=tuple(runs), skipped_logs=skipped)


def activity_by_section(history: History) -> dict[str, agents.Activity]:
    found: dict[str, agents.Activity] = {}
    for run in history.runs:
        found[run.section] = agents.merge(found.get(run.section, agents.Activity()), run.stream.activity)
    return found
