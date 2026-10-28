"""Red tests for Relay's git queries (design: Modules, `relay/git.py`; Order 3).

The repositories come from the `git_repo` fixture in `tests/conftest.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import relay.git
import relay.runner
from relay.git import heads, section_worktree

if TYPE_CHECKING:
    from conftest import GitRepo

PORCELAIN = (
    "worktree /nowhere/main\n"
    "HEAD 1111111111111111111111111111111111111111\n"
    "branch refs/heads/main\n"
    "\n"
    "worktree /nowhere/wt-s10\n"
    "HEAD 2222222222222222222222222222222222222222\n"
    "branch refs/heads/lead/s10\n"
    "\n"
    "worktree /nowhere/wt-s4\n"
    "HEAD 3333333333333333333333333333333333333333\n"
    "branch refs/heads/lead/s4\n"
    "\n"
    "worktree /nowhere/detached\n"
    "HEAD 4444444444444444444444444444444444444444\n"
    "detached\n"
    "\n"
)

FOR_EACH_REF = (
    "refs/heads/lead/s4 3333333333333333333333333333333333333333\n"
    "refs/heads/main 1111111111111111111111111111111111111111\n"
)

# What git may still print before exiting non-zero: a worktree on lead/s1 and its head, so
# an implementation that parses stdout whatever the exit status finds a worktree and heads.
S1_PORCELAIN = (
    "worktree /nowhere/wt-s1\n"
    "HEAD 5555555555555555555555555555555555555555\n"
    "branch refs/heads/lead/s1\n"
    "\n"
)
S1_FOR_EACH_REF = "refs/heads/lead/s1 5555555555555555555555555555555555555555\n"


def _fake_capture(
    monkeypatch: pytest.MonkeyPatch, answer: tuple[int | None, str]
) -> list[tuple[list[str], Path, float]]:
    """Replace `runner.capture` with a recorder answering `answer`.

    Every name in `relay.git` bound to `runner.capture` is replaced too, whatever that name
    is, so the fake holds however `relay.git` imports it.
    """
    calls: list[tuple[list[str], Path, float]] = []

    def fake(argv: list[str], cwd: Path, timeout: float) -> tuple[int | None, str]:
        calls.append((list(argv), Path(cwd), timeout))
        return answer

    real = relay.runner.capture
    monkeypatch.setattr(relay.runner, "capture", fake)
    for name, value in list(vars(relay.git).items()):
        if value is real:
            monkeypatch.setattr(relay.git, name, fake)
    return calls


# Behavior 5: The worktree `git worktree list --porcelain` (run in `repo`) shows on branch
# refs/heads/lead/<sid>, or None when there is none or git fails.


def test_section_worktree_is_the_worktree_on_lead_sid(git_repo: GitRepo) -> None:
    found = section_worktree(git_repo.root, "s1")
    assert found is not None
    assert Path(found).resolve() == git_repo.worktrees["s1"]


def test_section_worktree_picks_the_branch_of_that_sid_among_several(git_repo: GitRepo) -> None:
    git_repo.worktree("s10")
    git_repo.worktree("s2")
    for sid in ("s1", "s10", "s2"):
        found = section_worktree(git_repo.root, sid)
        assert found is not None
        assert Path(found).resolve() == git_repo.worktrees[sid]


def test_section_worktree_answers_the_same_when_run_in_a_worktree(git_repo: GitRepo) -> None:
    git_repo.worktree("s2")
    found = section_worktree(git_repo.worktrees["s1"], "s2")
    assert found is not None
    assert Path(found).resolve() == git_repo.worktrees["s2"]


@pytest.mark.parametrize("sid", ["s9", "s", "s1.1", "1"])
def test_section_worktree_is_none_when_no_worktree_is_on_that_branch(
    git_repo: GitRepo, sid: str
) -> None:
    git_repo.worktree("s10")
    assert section_worktree(git_repo.root, sid) is None


def test_section_worktree_is_none_for_a_branch_no_worktree_has_checked_out(
    git_repo: GitRepo,
) -> None:
    git_repo.git("branch", "lead/s3")
    assert section_worktree(git_repo.root, "s3") is None


def test_section_worktree_parses_the_porcelain_capture_returns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_capture(monkeypatch, (0, PORCELAIN))
    assert section_worktree(tmp_path, "s4") == Path("/nowhere/wt-s4")
    assert section_worktree(tmp_path, "s10") == Path("/nowhere/wt-s10")
    assert section_worktree(tmp_path, "s1") is None
    assert calls
    for argv, cwd, _timeout in calls:
        assert argv[0] == "git"
        assert argv[1:] == ["worktree", "list", "--porcelain"]
        assert cwd == tmp_path


# Behavior 6: {ref: object} from `git for-each-ref --format=%(refname) %(objectname) refs/heads`
# in `repo`; {} when git fails.


def test_heads_maps_every_branch_to_its_object(git_repo: GitRepo) -> None:
    git_repo.git("branch", "lead/s3")
    assert heads(git_repo.root) == {
        "refs/heads/main": git_repo.rev("refs/heads/main"),
        "refs/heads/lead/s1": git_repo.rev("refs/heads/lead/s1"),
        "refs/heads/lead/s3": git_repo.rev("refs/heads/lead/s3"),
    }


def test_heads_leaves_out_refs_outside_refs_heads(git_repo: GitRepo) -> None:
    git_repo.git("tag", "v1")
    git_repo.git("update-ref", "refs/remotes/origin/main", "HEAD")
    assert set(heads(git_repo.root)) == {"refs/heads/main", "refs/heads/lead/s1"}


def test_heads_parses_the_for_each_ref_capture_returns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_capture(monkeypatch, (0, FOR_EACH_REF))
    assert heads(tmp_path) == {
        "refs/heads/lead/s4": "3" * 40,
        "refs/heads/main": "1" * 40,
    }
    assert len(calls) == 1
    argv, cwd, _timeout = calls[0]
    assert argv == ["git", "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads"]
    assert cwd == tmp_path


# Behavior 7: Covers every worktree's branch, since worktrees share refs.


def test_heads_sees_a_commit_made_in_a_section_worktree(git_repo: GitRepo) -> None:
    before = heads(git_repo.root)
    made = git_repo.commit(cwd=git_repo.worktrees["s1"], message="lead work")
    after = heads(git_repo.root)
    assert after["refs/heads/lead/s1"] == made
    assert after["refs/heads/lead/s1"] != before["refs/heads/lead/s1"]
    assert after["refs/heads/main"] == before["refs/heads/main"]


def test_heads_is_the_same_run_in_any_worktree(git_repo: GitRepo) -> None:
    git_repo.worktree("s2")
    git_repo.commit(cwd=git_repo.worktrees["s2"], message="s2 work")
    from_main = heads(git_repo.root)
    assert set(from_main) == {"refs/heads/main", "refs/heads/lead/s1", "refs/heads/lead/s2"}
    assert heads(git_repo.worktrees["s1"]) == from_main
    assert heads(git_repo.worktrees["s2"]) == from_main


# Behavior 8: Both run git through `runner.capture`. Neither raises on a git failure.


@pytest.mark.parametrize(
    "answer",
    [
        (128, ""),
        (None, ""),
        (128, S1_PORCELAIN),
        (1, S1_FOR_EACH_REF),
        (128, S1_PORCELAIN + S1_FOR_EACH_REF),
    ],
    ids=[
        "git-error",
        "oserror-or-timeout",
        "git-error-printing-a-worktree",
        "git-error-printing-a-head",
        "git-error-printing-both",
    ],
)
def test_a_failed_capture_gives_none_and_empty_heads(
    monkeypatch: pytest.MonkeyPatch, git_repo: GitRepo, answer: tuple[int | None, str]
) -> None:
    calls = _fake_capture(monkeypatch, answer)
    # The real repository has a lead/s1 worktree, so only the capture's answer can give None.
    assert section_worktree(git_repo.root, "s1") is None
    assert heads(git_repo.root) == {}
    assert len(calls) >= 2
    assert all(argv[0] == "git" and cwd == git_repo.root for argv, cwd, _t in calls)


def test_neither_raises_outside_a_repository(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert section_worktree(plain, "s1") is None
    assert heads(plain) == {}


def test_neither_raises_on_a_directory_that_does_not_exist(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert section_worktree(missing, "s1") is None
    assert heads(missing) == {}
