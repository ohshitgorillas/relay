"""The one place Relay asks git anything."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from relay import runner
from relay.state import queue_id

_TIMEOUT = 30.0


@dataclass(frozen=True)
class SectionWorktree:
    branch: str
    path: Path


def section_branch(queue: Path, sid: str) -> str:
    """The queue-qualified lead branch for this section."""
    return f"lead/{queue_id(queue)}/{sid}"


def section_path(repo: Path, queue: Path, sid: str) -> Path:
    """The queue-qualified section worktree location beside the repository."""
    return repo.parent / (repo.name + "-wt") / queue_id(queue) / sid


def section_worktree(
    repo: Path,
    queue: Path,
    sid: str,
    recorded: SectionWorktree | None = None,
) -> SectionWorktree | None:
    """Validate a binding or discover this queue's qualified branch."""
    wanted = section_branch(queue, sid)
    if recorded is not None:
        if re.match(r"lead/[0-9a-f]{64}/", recorded.branch) and recorded.branch != wanted:
            return None
        wanted = recorded.branch
    code, out = runner.capture(["git", "worktree", "list", "--porcelain"], repo, _TIMEOUT)
    if code != 0:
        return None
    for record in out.split("\n\n"):
        fields = record.splitlines()
        paths = [Path(line[len("worktree ") :]) for line in fields if line.startswith("worktree ")]
        branches = [
            line[len("branch refs/heads/") :]
            for line in fields
            if line.startswith("branch refs/heads/")
        ]
        if len(paths) != 1 or branches != [wanted] or "detached" in fields:
            continue
        path = paths[0]
        path = path.resolve()
        if not path.is_dir():
            continue
        if recorded is None or path == recorded.path.resolve():
            return SectionWorktree(wanted, path)
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


def head(cwd: Path) -> str | None:
    """`git rev-parse HEAD` in `cwd`; None when git fails."""
    code, out = runner.capture(["git", "rev-parse", "HEAD"], cwd, _TIMEOUT)
    if code != 0:
        return None
    return out.strip() or None


def clean(cwd: Path) -> bool | None:
    """`git status --porcelain` in `cwd`: True on exit 0 with no output, False with output, None when git fails."""
    code, out = runner.capture(["git", "status", "--porcelain"], cwd, _TIMEOUT)
    if code != 0:
        return None
    return not out.strip()
