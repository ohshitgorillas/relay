"""Shared fixtures for Relay's tests (design: Test helpers)."""

from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

import pytest

from relay.config import Config
from harness import RECORD
from fakes.fake_runner import FakeRunner

TESTS = Path(__file__).parent
FAKE_CLAUDE = TESTS / "fakes" / "fake_claude.py"
FIXTURES = TESTS / "fixtures"


@pytest.fixture
def fake_run(monkeypatch):
    import relay.loop
    import relay.runner
    fake = FakeRunner([])
    original = relay.runner.run_agent
    for name, module in list(sys.modules.items()):
        if name.startswith('relay') and getattr(module, 'run_agent', None) is original:
            monkeypatch.setattr(module, 'run_agent', fake)
    stat = os.stat

    def observed_stat(path, *args, **kwargs):
        thread = threading.current_thread()
        stop_file = getattr(thread, '_relay_stop_file', None)
        try:
            return stat(path, *args, **kwargs)
        finally:
            if stop_file is not None and str(path) == str(stop_file):
                thread._relay_polls = getattr(thread, '_relay_polls', 0) + 1

    monkeypatch.setattr(os, 'stat', observed_stat)
    return fake


@pytest.fixture
def loop_cfg(fake_cfg: Config, tmp_path: Path, fake_run, git_template: Path) -> Config:
    """A loop config with recorded pings and a temporary git work tree."""
    shutil.copytree(git_template / '.git', tmp_path / '.git')
    record = tmp_path / "pings.jsonl"
    return dataclasses.replace(fake_cfg, ping_command=[sys.executable, "-c", RECORD, str(record), "{message}"])


@pytest.fixture(scope='session')
def git_template(tmp_path_factory) -> Path:
    """Initialize once; every test still receives an independent git directory."""
    path = tmp_path_factory.mktemp('git-template')
    subprocess.run(['git', 'init', '-q', '--template=', str(path)], check=True)
    return path


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
