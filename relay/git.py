"""The one place Relay asks git anything."""

from __future__ import annotations

from pathlib import Path

from relay import runner

_TIMEOUT = 30.0


def section_worktree(repo: Path, sid: str) -> Path | None:
    """The worktree on branch refs/heads/lead/<sid>, or None when there is none or git fails."""
    code, out = runner.capture(["git", "worktree", "list", "--porcelain"], repo, _TIMEOUT)
    if code != 0:
        return None
    wanted = f"branch refs/heads/lead/{sid}"
    path: Path | None = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree ") :])
        elif line == wanted and path is not None:
            return path
    return None


def heads(repo: Path) -> dict[str, str]:
    """{ref: object} for every branch under refs/heads; {} when git fails."""
    code, out = runner.capture(
        ["git", "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads"], repo, _TIMEOUT
    )
    if code != 0:
        return {}
    found: dict[str, str] = {}
    for line in out.splitlines():
        ref, _, obj = line.partition(" ")
        if ref and obj:
            found[ref] = obj
    return found
