"""The spend ledger."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from relay.config import Config
from relay.errors import RelayError


@dataclass(frozen=True)
class Spend:
    tokens: int
    dollars: float


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
        with open(self._path, "a") as handle:
            handle.write(json.dumps(entry) + "\n")

    def total(self, since: float | None) -> Spend:
        tokens = 0
        dollars = 0.0
        try:
            text = self._path.read_text()
        except FileNotFoundError:
            return Spend(tokens=0, dollars=0.0)
        for number, line in enumerate(text.splitlines(), 1):
            where = f"{self._path}:{number}"
            try:
                entry = json.loads(line)
                stamp = entry["time"]
                add_tokens = entry["tokens"]
                add_dollars = entry["dollars"]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise RelayError(f"corrupt ledger line {where}: {exc!r}") from exc
            numbers = (stamp, add_tokens, add_dollars)
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in numbers):
                raise RelayError(f"corrupt ledger line {where}: non-numeric field")
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
