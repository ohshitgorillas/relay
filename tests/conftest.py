"""Shared fixtures for Relay's tests (design: Test helpers)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

import pytest

from relay.config import Config

TESTS = Path(__file__).parent
FAKE_CLAUDE = TESTS / "fakes" / "fake_claude.py"
FIXTURES = TESTS / "fixtures"

# The documented default `check_outside` patterns, in order (design: `relay/config.py`).
DEFAULT_CHECK_OUTSIDE = [
    "command not found",
    "(?i)credit balance",
    "(?i)api[ _-]?key",
    "(?i)could not resolve host",
    "(?i)name resolution",
    "(?i)network is unreachable",
    "(?i)connection (refused|reset|timed out)",
]

# The owner's standing approval, the documented `design_approval` default
# (design: relay-ladder-design.md, `relay/config.py` (extended)).
STANDING_APPROVAL = (
    "I am sick and tired of this paperwork bullshit make it stop for the 5th fucking time"
)


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
        idle_ceiling=130_000,
        check_timeout=1800.0,
        check_outside=list(DEFAULT_CHECK_OUTSIDE),
        research_command=[fake, "--agent", "researcher"],
        map_max_lines=150,
        map_max_chars=12_000,
        design_command=[fake, "--agent", "architect"],
        section_dollar_cap=None,
        design_approval=STANDING_APPROVAL,
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


# Fixed identity and no hooks, so a commit here never reads the user's git config.
_GIT = [
    "git",
    "-c", "user.name=Relay Tests",
    "-c", "user.email=relay-tests@example.invalid",
    "-c", "commit.gpgsign=false",
    "-c", "core.hooksPath=/dev/null",
]


class GitRepo:
    """A temporary git repository on `main` with one commit and a worktree on `lead/s1`."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.worktrees: dict[str, Path] = {}

    def git(self, *args: str, cwd: Path | None = None) -> str:
        """Run git in `cwd` (default the main checkout) and return its stdout; raise on failure."""
        done = subprocess.run(
            [*_GIT, *args],
            cwd=cwd or self.root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout

    def rev(self, ref: str) -> str:
        """The object name `ref` points at."""
        return self.git("rev-parse", ref).strip()

    def commit(self, cwd: Path | None = None, message: str = "commit") -> str:
        """Make an empty commit in `cwd` and return its object name."""
        self.git("commit", "--allow-empty", "-q", "-m", message, cwd=cwd)
        return self.git("rev-parse", "HEAD", cwd=cwd).strip()

    def worktree(self, sid: str) -> Path:
        """Add a worktree beside the repository on a new branch `lead/<sid>` and return its real path."""
        path = self.root.parent / f"wt-{sid}"
        self.git("worktree", "add", "-q", "-b", f"lead/{sid}", str(path))
        self.worktrees[sid] = path.resolve()
        return self.worktrees[sid]


@pytest.fixture
def git_repo(tmp_path: Path) -> GitRepo:
    """A temporary git repository with a `lead/s1` worktree (design: Order 2)."""
    root = tmp_path / "repo"
    root.mkdir()
    repo = GitRepo(root)
    repo.git("init", "-q", "-b", "main")
    repo.commit(message="first")
    repo.worktree("s1")
    return repo
