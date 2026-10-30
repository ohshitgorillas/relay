"""The spend ledger."""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from relay.config import Config

if TYPE_CHECKING:
    from relay.backends.base import Capabilities
    from relay.agents import Agent
    from relay.check import CheckResult
    from relay.pricing import Usage


Kind = Literal["lead", "recut", "research", "ask", "design"]


@dataclass(frozen=True)
class Spend:
    tokens: int
    dollars: float


def _parse(chunk: bytes) -> tuple[dict, tuple[float, float, float]] | None:
    """The decoded line and its (time, tokens, dollars), or None when the line is unreadable."""
    try:
        entry = json.loads(chunk.decode())
        values = (entry["time"], entry["tokens"], entry["dollars"])
    except (ValueError, KeyError, TypeError, RecursionError):
        return None
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
    return entry, values


class Ledger:
    def __init__(self, path: Path):
        self._path = path

    def append(
        self,
        kind: Kind,
        section: str,
        session: str | None,
        spend: Spend,
        map_commit: str | None = None,  # the map the run's prompt carried; null when none
        agents: tuple["Agent", ...] = (),  # detail only; never added to the run's spend
        rung: int | None = None,  # the ladder rung; a line gains "rung" only when set
        *,
        basis: str = "reported",
        usage: tuple[Usage, ...] = (),
    ) -> None:
        entry = {
            "time": time.time(),
            "kind": kind,
            "section": section,
            "session": session,
            "tokens": spend.tokens,
            "dollars": spend.dollars,
            "basis": basis,
            "map": map_commit,
            "agents": [
                {
                    "name": a.name,
                    "task_id": a.task_id,
                    "total_tokens": a.context,
                    "models": a.models,
                    "efforts": a.efforts,
                    "cost_dollars": a.cost_dollars,
                    "cost_basis": a.cost_basis,
                    "cost_unavailable": a.cost_unavailable,
                }
                for a in agents
            ],
        }
        if rung is not None:
            entry["rung"] = rung
        if usage:
            entry["usage"] = [
                {
                    "thread": row.thread,
                    "model": row.model,
                    "input": row.input,
                    "cached_input": row.cached_input,
                    "output": row.output,
                }
                for row in usage
            ]
        self._write(entry)

    def _write(self, entry: dict) -> None:
        data = (json.dumps(entry) + "\n").encode()
        fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            if os.fstat(fd).st_size > 0 and not self._ends_with_newline():
                data = b"\n" + data
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)

    def append_check(self, section: str, result: "CheckResult") -> None:
        entry = {
            "time": time.time(),
            "kind": "check",
            "section": section,
            "session": None,
            "tokens": 0,
            "dollars": 0.0,
            "command": result.command,
            "exit": result.exit_code,
            "timed_out": result.timed_out,
            "verdict": result.verdict,
            "tail": result.tail,
            "log": str(result.log) if result.log is not None else None,
        }
        self._write(entry)

    def _ends_with_newline(self) -> bool:
        with open(self._path, "rb") as handle:
            handle.seek(-1, os.SEEK_END)
            return handle.read(1) == b"\n"

    def _lines(self) -> list[tuple[int, tuple[float, float, float] | None]]:
        """Every line as (1-based number, (time, tokens, dollars) or None when unreadable)."""
        return [
            (number, None if parsed is None else parsed[1])
            for number, parsed in ((n, _parse(c)) for n, c in enumerate(self._chunks(), 1))
        ]

    def _entries(self, since: float | None = None) -> Iterator[tuple[dict, int, float]]:
        """Each readable line once, as (entry, tokens, dollars); a `since` skips lines at or
        before it. The one place that decides which lines count toward a spend."""
        for chunk in self._chunks():
            parsed = _parse(chunk)
            if parsed is None:
                continue
            entry, (stamp, tokens, dollars) = parsed
            if since is not None and stamp <= since:
                continue
            yield entry, int(tokens), float(dollars)

    @staticmethod
    def _sum(entries: Iterator[tuple[dict, int, float]]) -> Spend:
        tokens = 0
        dollars = 0.0
        for _, add_tokens, add_dollars in entries:
            tokens += add_tokens
            dollars += add_dollars
        return Spend(tokens=tokens, dollars=dollars)

    def _chunks(self) -> list[bytes]:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return []
        chunks = raw.split(b"\n")
        if chunks[-1] == b"":
            chunks.pop()
        return chunks

    def sessions(self) -> list[tuple[str, str]]:
        """(section, session) of each readable line naming both, in the order written."""
        found = []
        for entry, _, _ in self._entries():
            section, session = entry.get("section"), entry.get("session")
            if isinstance(section, str) and isinstance(session, str):
                found.append((section, session))
        return found

    def total(self, since: float | None) -> Spend:
        return self._sum(self._entries(since))

    def over(
        self,
        cfg: Config,
        live: Spend,
        since: float | None,
        *,
        capabilities: Capabilities | None = None,
    ) -> Literal["tokens", "dollars"] | None:
        if capabilities is None:
            from relay.backends import get_backend

            capabilities = get_backend(cfg.backend).capabilities
        past = self.total(since)
        if (capabilities.tokens and cfg.token_budget is not None
                and past.tokens + live.tokens > cfg.token_budget):
            return "tokens"
        if (capabilities.dollars and cfg.dollar_budget is not None
                and past.dollars + live.dollars > cfg.dollar_budget):
            return "dollars"
        return None

    def section_spend(self, section: str) -> Spend:
        """Every readable line whose "section" is `section`, summed, across all time."""
        return self._sum(e for e in self._entries() if e[0].get("section") == section)

    def unreadable(self) -> list[int]:
        return [number for number, fields in self._lines() if fields is None]
