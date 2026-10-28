"""The one place Relay asks git anything."""

from __future__ import annotations

from pathlib import Path


def section_worktree(repo: Path, sid: str) -> Path | None:
    """The worktree on branch refs/heads/lead/<sid>, or None when there is none or git fails."""
    raise NotImplementedError


def heads(repo: Path) -> dict[str, str]:
    """{ref: object} for every branch under refs/heads; {} when git fails."""
    raise NotImplementedError
