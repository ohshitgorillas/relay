"""The one place an owner ping is worded and sent."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from relay.config import Config


def ping(cfg: Config, message: str) -> None:
    argv = [arg.replace("{message}", message) for arg in cfg.ping_command]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as exc:
        print(f"relay: ping failed: {exc}", file=sys.stderr)
        return
    if result.returncode != 0:
        print(
            f"relay: ping failed (exit {result.returncode}): {result.stderr.strip()}",
            file=sys.stderr,
        )


def needs_owner(cfg: Config, queue: Path, sid: str, question: str) -> None:
    ping(cfg, f"relay {queue.name}: section {sid} needs the owner: {question}")


def stopped(cfg: Config, queue: Path, reason: str, detail: str) -> None:
    ping(cfg, f"relay {queue.name}: stopped {reason}: {detail}")


def research_failed(cfg: Config, queue: Path, sid: str, error: str) -> None:
    ping(cfg, f"relay {queue.name}: research {sid} failed: {error}; the lead starts without a map")
