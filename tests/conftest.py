"""Shared fixtures for Relay's tests (design: Test helpers)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from relay.config import Config

TESTS = Path(__file__).parent
FAKE_CLAUDE = TESTS / "fakes" / "fake_claude.py"
FIXTURES = TESTS / "fixtures"


@pytest.fixture
def fake_cfg(tmp_path: Path) -> Config:
    """A `Config` whose commands point at `tests/fakes/fake_claude.py`, with `state_root` under `tmp_path`."""
    fake = str(FAKE_CLAUDE)
    return Config(
        token_budget=None,
        dollar_budget=None,
        context_limit=100_000,
        hard_ceiling=200_000,
        poll_seconds=0.05,
        lead_command=[fake],
        recut_command=[fake, "--agent", "divvyer"],
        ping_command=[fake, "{message}"],
        state_root=tmp_path / "state",
    )


@pytest.fixture
def queue_file(tmp_path: Path) -> Callable[[str], Path]:
    """Return a writer: given a file name under `tests/fixtures/`, it writes that queue under `tmp_path` and returns its path."""

    def write(name: str) -> Path:
        path = tmp_path / name
        path.write_bytes((FIXTURES / name).read_bytes())
        return path

    return write


@pytest.fixture
def scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[list[str]], Path]:
    """Return a writer: given stream-json lines, it writes a scenario file under `tmp_path`, names it in `RELAY_FAKE_SCENARIO` and returns its path."""
    count = 0

    def write(lines: list[str]) -> Path:
        nonlocal count
        count += 1
        path = tmp_path / f"scenario-{count}.jsonl"
        path.write_text("".join(line + "\n" for line in lines))
        monkeypatch.setenv("RELAY_FAKE_SCENARIO", str(path))
        return path

    return write
