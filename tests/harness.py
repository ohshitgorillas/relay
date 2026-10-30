"""Shared loop-test helpers."""

from __future__ import annotations

import json
import shlex
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from relay.config import Config
from relay.loop import run
from relay.state import State

RECORD = "import sys, json; f = open(sys.argv[1], 'a'); f.write(json.dumps(sys.argv[2:]) + chr(10)); f.close()"


def checked_queue(path: Path, record: Path, *sids: str) -> Path:
    """Write sections whose checks record their actual working directory."""
    script = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.open('a').write(str(pathlib.Path.cwd().resolve())+'\\n')"
    command = shlex.join([sys.executable, "-c", script, str(record)])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(
        f"section {sid} | lead | steps: 1\n  {sid} work\n  done-check: {command}\n"
        for sid in sids
    ))
    return path


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
        self.thread._relay_stop_file = State.open(queue, cfg).stop_file
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

    def wait_for_pass(self) -> None:
        """Wait for two further checks of this queue's stop file."""
        target = getattr(self.thread, '_relay_polls', 0) + 2
        until(lambda: getattr(self.thread, '_relay_polls', 0) >= target or not self.still_running())

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
