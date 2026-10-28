"""The spend ledger."""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from relay.config import Config

if TYPE_CHECKING:
    from relay.check import CheckResult


@dataclass(frozen=True)
class Spend:
    tokens: int
    dollars: float


def _parse(chunk: bytes) -> tuple[float, float, float] | None:
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
    return values


class Ledger:
    def __init__(self, path: Path):
        self._path = path

    def append(
        self,
        kind: Literal["lead", "recut"],
        section: str,
        session: str | None,
        spend: Spend,
    ) -> None:
        entry = {
            "time": time.time(),
            "kind": kind,
            "section": section,
            "session": session,
            "tokens": spend.tokens,
            "dollars": spend.dollars,
        }
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
        raise NotImplementedError

    def _ends_with_newline(self) -> bool:
        with open(self._path, "rb") as handle:
            handle.seek(-1, os.SEEK_END)
            return handle.read(1) == b"\n"

    def _lines(self) -> list[tuple[int, tuple[float, float, float] | None]]:
        """Every line as (1-based number, (time, tokens, dollars) or None when unreadable)."""
        return [(number, _parse(chunk)) for number, chunk in enumerate(self._chunks(), 1)]

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
        for chunk in self._chunks():
            if _parse(chunk) is None:
                continue
            entry = json.loads(chunk.decode())
            section, session = entry.get("section"), entry.get("session")
            if isinstance(section, str) and isinstance(session, str):
                found.append((section, session))
        return found

    def total(self, since: float | None) -> Spend:
        tokens = 0
        dollars = 0.0
        for _, fields in self._lines():
            if fields is None:
                continue
            stamp, add_tokens, add_dollars = fields
            if since is not None and stamp <= since:
                continue
            tokens += int(add_tokens)
            dollars += float(add_dollars)
        return Spend(tokens=tokens, dollars=dollars)

    def over(
        self, cfg: Config, live: Spend, since: float | None
    ) -> Literal["tokens", "dollars"] | None:
        past = self.total(since)
        if cfg.token_budget is not None and past.tokens + live.tokens > cfg.token_budget:
            return "tokens"
        if cfg.dollar_budget is not None and past.dollars + live.dollars > cfg.dollar_budget:
            return "dollars"
        return None

    def unreadable(self) -> list[int]:
        return [number for number, fields in self._lines() if fields is None]
