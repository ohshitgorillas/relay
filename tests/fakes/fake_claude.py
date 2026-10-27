#!/usr/bin/env python3
"""Fake `claude` CLI for Relay's tests.

Reads its prompt on stdin, then emits the scripted stream-json lines of the
scenario file named by `RELAY_FAKE_SCENARIO`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    """Read the prompt on stdin, then write the scenario's lines to stdout; return the exit status."""
    sys.stdin.read()
    scenario = Path(os.environ["RELAY_FAKE_SCENARIO"])
    for line in scenario.read_text().splitlines():
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
