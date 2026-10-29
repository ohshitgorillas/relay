"""Shared loop-test helpers."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

from relay.config import Config
from relay.loop import run
from relay.state import State

RECORD = "import sys, json; f = open(sys.argv[1], 'a'); f.write(json.dumps(sys.argv[2:]) + chr(10)); f.close()"


def pings(tmp_path: Path) -> list[list[str]]:
    record = tmp_path / "pings.jsonl"
    if not record.exists():
        return []
    return [json.loads(line) for line in record.read_text().splitlines()]


def ledger_line(state: State, stamp: float, tokens: int, dollars: float) -> None:
    """Append one readable ledger line stamped `stamp`."""
    path = state.stop_file.parent / "ledger.jsonl"
    with path.open("a") as f:
        f.write(json.dumps({"time": stamp, "tokens": tokens, "dollars": dollars}) + "\n")


class Background:
    """One `run` on a daemon thread, so a test can act while the loop waits."""

    def __init__(self, queue: Path, cfg: Config) -> None:
        self.result: int | None = None
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._body, args=(queue, cfg), daemon=True)
        self.thread.start()

    def _body(self, queue: Path, cfg: Config) -> None:
        try:
            self.result = run(queue, cfg)
        except BaseException as exc:
            self.error = exc

    def still_running(self) -> bool:
        if self.thread.is_alive():
            return True
        if self.error is not None:
            raise self.error
        return False

    def finish(self, timeout: float = 15.0) -> int | None:
        self.thread.join(timeout)
        assert not self.thread.is_alive(), "run did not return"
        if self.error is not None:
            raise self.error
        return self.result


def until(condition: Callable[[], bool], timeout: float = 15.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "condition never held"
        time.sleep(0.02)
