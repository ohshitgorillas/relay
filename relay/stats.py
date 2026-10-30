"""Sizing figures over run history, and their text."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from relay.agents import Agent
from relay.config import Config
from relay.history import History, Run
from relay.status import parse_status

_SHOWN = 5

Role = str  # a top-level run's ledger kind, or a subagent's type (`Agent.name`)


@dataclass(frozen=True)
class Sized:
    role: Role
    section: str
    label: str  # the run's session, or the subagent's description
    peak: int  # peak context of this one run
    overrun: str | None  # None when finished; else "retired", "killed", "stopped" or "over context limit"


@dataclass(frozen=True)
class RoleStats:
    role: Role
    finished: tuple[int, ...]  # peaks of finished runs
    overruns: tuple[Sized, ...]  # in the order they ran


def _top_level(run: Run, cfg: Config) -> Sized | None:
    stream = run.stream
    peak = stream.peak_context
    status = parse_status(stream.result_text)
    overrun: str | None = None
    if status is not None and status.kind == "RETIRED":
        overrun = "retired"
    elif stream.result_text is None and peak >= cfg.hard_ceiling:
        overrun = "killed"
    elif peak >= cfg.context_limit:
        overrun = "over context limit"
    elif run.kind == "lead":
        if status is None or status.kind != "DONE":
            return None
    elif stream.result_text is None or stream.is_error:
        return None
    return Sized(role=run.kind, section=run.section, label=run.session, peak=peak, overrun=overrun)


def _subagent(run: Run, agent: Agent, cfg: Config) -> Sized | None:
    peak = max(agent.peak, agent.context)
    if agent.status == "stopped":
        overrun: str | None = "stopped"
    elif peak >= cfg.context_limit:
        overrun = "over context limit"
    elif agent.status == "completed":
        overrun = None
    else:
        return None
    return Sized(role=agent.name, section=run.section, label=agent.description, peak=peak, overrun=overrun)


def sized(history: History, cfg: Config) -> list[Sized]:
    out: list[Sized] = []
    for run in history.runs:
        top = _top_level(run, cfg)
        if top is not None:
            out.append(top)
        for agent in run.stream.activity.agents:
            item = _subagent(run, agent, cfg)
            if item is not None:
                out.append(item)
    return out


def by_role(items: Iterable[Sized]) -> list[RoleStats]:
    finished: dict[Role, list[int]] = {}
    overruns: dict[Role, list[Sized]] = {}
    for item in items:
        finished.setdefault(item.role, [])
        overruns.setdefault(item.role, [])
        if item.overrun is None:
            finished[item.role].append(item.peak)
        else:
            overruns[item.role].append(item)
    return [
        RoleStats(role=role, finished=tuple(finished[role]), overruns=tuple(overruns[role]))
        for role in sorted(finished)
    ]


def lines(stats: list[RoleStats]) -> list[str]:
    out: list[str] = []
    for entry in stats:
        count = len(entry.finished)
        head = f"{entry.role}: {count} finished"
        if count:
            peaks = sorted(entry.finished)
            median = peaks[(count - 1) // 2]
            p90 = peaks[math.ceil(0.9 * count) - 1]
            head += f", peak context median {median}, p90 {p90}, max {peaks[-1]}"
        out.append(f"{head}; {len(entry.overruns)} overruns")
        if len(entry.overruns) > _SHOWN:
            out.append(f"  {entry.role}: {len(entry.overruns) - _SHOWN} earlier overruns not shown")
        for item in entry.overruns[-_SHOWN:]:
            out.append(f"  {item.role} overrun: {item.section} {item.label} peak {item.peak} ({item.overrun})")
    return out
