#!/usr/bin/env python3
"""Fake `claude` CLI for Relay's tests.

Reads its prompt on stdin, then emits the scripted stream-json lines of the
scenario file named by `RELAY_FAKE_SCENARIO`. When argv carries `--agent <name>`
and `RELAY_FAKE_SCENARIO_<NAME>` is set (upper case, `-` as `_`), it emits that
scenario instead. When `RELAY_FAKE_PROMPTS` is set, it appends each prompt it
reads to the file that variable names. When `RELAY_FAKE_LAUNCH` is set, it appends
one JSON line per run to the file that variable names: its `argv` (after the
program name) and its whole `env`.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _agent(argv: list[str]) -> str | None:
    """The name after `--agent` in argv, or None when argv carries no `--agent <name>`."""
    for i, arg in enumerate(argv[:-1]):
        if arg == "--agent":
            return argv[i + 1]
    return None


def _scenario_path(argv: list[str]) -> Path:
    """The named agent's own scenario when its variable is set, else the shared one."""
    agent = _agent(argv)
    if agent is not None:
        own = os.environ.get("RELAY_FAKE_SCENARIO_" + agent.upper().replace("-", "_"))
        if own:
            return Path(own)
    return Path(os.environ["RELAY_FAKE_SCENARIO"])


def main() -> int:
    """Read the prompt on stdin, then write the scenario's lines to stdout; return the exit status."""
    prompt = sys.stdin.read()
    prompts = os.environ.get("RELAY_FAKE_PROMPTS")
    if prompts:
        with Path(prompts).open("a") as log:
            log.write(prompt)
    launch = os.environ.get("RELAY_FAKE_LAUNCH")
    if launch:
        with Path(launch).open("a") as log:
            log.write(json.dumps({"argv": sys.argv[1:], "env": dict(os.environ)}) + "\n")
    scenario = _scenario_path(sys.argv[1:])
    gate = os.environ.get("RELAY_FAKE_GATE")
    if gate:
        gate_path = Path(gate)
        (gate_path / "ready").write_text(str(os.getpid()))
        end = time.monotonic() + 15.0
        while not (gate_path / "release").exists():
            if time.monotonic() >= end:
                raise TimeoutError("fake child was not released")
            time.sleep(0.02)
    for line in scenario.read_text().splitlines():
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    if gate:
        (Path(gate) / "finished").touch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
