"""Reads claude stream-json event lines."""

from __future__ import annotations

from dataclasses import dataclass

from relay.ledger import Spend


@dataclass
class StreamState:
    session_id: str | None
    context_tokens: int
    spend: Spend
    result_text: str | None
    is_error: bool


def feed(state: StreamState, line: str) -> StreamState:
    raise NotImplementedError
