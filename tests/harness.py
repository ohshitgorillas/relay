"""Shared loop-test helpers."""

from __future__ import annotations

import json
import os
import shlex
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import pytest

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


class DrainRealChild:
    """Signal the run while its real child waits, then release that child."""

    def __init__(self, gate: Path, state: State) -> None:
        self.gate = gate
        self.state = state
        self.pid: int | None = None
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._body)
        self.thread.start()

    def _body(self) -> None:
        try:
            until(lambda: (self.gate / "ready").exists())
            until(lambda: bool((self.gate / "ready").read_text()))
            self.pid = int((self.gate / "ready").read_text())
            os.kill(os.getpid(), signal.SIGTERM)
            until(lambda: (live := self.state.live_run()) is not None and live.draining)
            os.kill(self.pid, 0)
        except BaseException as exc:
            self.error = exc
        finally:
            (self.gate / "release").touch()

    def finish(self) -> None:
        self.thread.join(16.0)
        assert not self.thread.is_alive(), "drain synchronization thread did not finish"
        if self.error is not None:
            raise self.error
        assert self.pid is not None
        with pytest.raises(ProcessLookupError):
            os.kill(self.pid, 0)


class DrainResearchLock:
    """Hold research's real lock until a drain is observed during acquisition."""

    def __init__(self, state: State, sid: str) -> None:
        self.state = state
        self.lock = state.research_lock
        self.sid = sid
        self.held = threading.Event()
        self.waiting = threading.Event()
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._body)
        self.thread.start()
        assert self.held.wait(15.0), "research lock holder did not acquire its lock"

    def _body(self) -> None:
        try:
            with self.lock(self.sid):
                self.held.set()
                assert self.waiting.wait(15.0), "run did not reach research lock acquisition"
                os.kill(os.getpid(), signal.SIGTERM)
                until(lambda: (live := self.state.live_run()) is not None and live.draining)
        except BaseException as exc:
            self.error = exc

    def finish(self) -> None:
        self.thread.join(16.0)
        assert not self.thread.is_alive(), "research lock holder did not finish"
        if self.error is not None:
            raise self.error


def request_drain() -> None:
    """Request a drain only after the run has safely armed its SIGTERM handler."""
    assert callable(signal.getsignal(signal.SIGTERM)), "run did not arm SIGTERM"
    signal.raise_signal(signal.SIGTERM)


def drain_after_role(role: str, *, during: bool = False):
    """Request drain after a child's return, or during its first stream callback."""
    def wrap(original):
        requested = False

        def finished(*args, **kwargs):
            nonlocal requested
            if during and kwargs.get("role", "lead") == role and not requested:
                arguments = list(args)
                callback = kwargs.get("on_event") if "on_event" in kwargs else arguments[4]

                def event(state):
                    nonlocal requested
                    if not requested:
                        requested = True
                        request_drain()
                    return callback(state)

                if "on_event" in kwargs:
                    kwargs["on_event"] = event
                else:
                    arguments[4] = event
                return original(*arguments, **kwargs)
            result = original(*args, **kwargs)
            if kwargs.get("role", "lead") == role and not requested:
                requested = True
                request_drain()
            return result

        return finished

    return wrap


def pings(tmp_path: Path) -> list[list[str]]:
    record = tmp_path / "pings.jsonl"
    if not record.exists():
        return []
    return [json.loads(line) for line in record.read_text().splitlines()]


def ledger_line(
    state: State,
    stamp: float,
    tokens: int,
    dollars: float,
    *,
    kind: str | None = None,
    section: str | None = None,
    session: str | None = None,
) -> dict:
    """Append one readable ledger line stamped `stamp`, with each of `kind`, `section`
    and `session` that is given, and return the line as written."""
    line: dict = {"time": stamp, "tokens": tokens, "dollars": dollars}
    for key, value in (("kind", kind), ("section", section), ("session", session)):
        if value is not None:
            line[key] = value
    path = state.stop_file.parent / "ledger.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(line) + "\n")
    return line


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
