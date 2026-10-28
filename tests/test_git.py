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


# The research design's git queries (design: relay-research-design.md, Modules `relay/git.py`
# (extended); Order 3). The repositories come from the `git_repo` fixture in `tests/conftest.py`.

HEAD_OBJECT = "6" * 40


def _tracked(git_repo: GitRepo, files: dict[str, str]) -> str:
    """Write `files` into the main checkout, commit them through the fixture and return HEAD."""
    for name, text in files.items():
        path = git_repo.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        git_repo.git("add", name)
    git_repo.git("commit", "-q", "-m", "tracked files")
    return git_repo.rev("HEAD")


# Behavior 1: `git rev-parse HEAD` in `cwd`; None when git fails.


def test_head_is_the_commit_head_points_at(git_repo: GitRepo) -> None:
    assert relay.git.head(git_repo.root) == git_repo.rev("HEAD")
    made = git_repo.commit(message="second")
    assert relay.git.head(git_repo.root) == made


def test_head_is_taken_in_cwd_so_a_worktree_gives_its_own_commit(git_repo: GitRepo) -> None:
    main_head = git_repo.rev("HEAD")
    made = git_repo.commit(cwd=git_repo.worktrees["s1"], message="lead work")
    assert relay.git.head(git_repo.worktrees["s1"]) == made
    assert relay.git.head(git_repo.root) == main_head
    assert made != main_head


def test_head_runs_git_rev_parse_head_in_cwd_through_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_capture(monkeypatch, (0, HEAD_OBJECT + "\n"))
    assert relay.git.head(tmp_path) == HEAD_OBJECT
    assert len(calls) == 1
    argv, cwd, _timeout = calls[0]
    assert argv == ["git", "rev-parse", "HEAD"]
    assert cwd == tmp_path


@pytest.mark.parametrize(
    "answer",
    [(128, ""), (None, ""), (128, HEAD_OBJECT + "\n"), (1, HEAD_OBJECT)],
    ids=["git-error", "oserror-or-timeout", "git-error-printing-a-head", "exit-1-printing-a-head"],
)
def test_head_is_none_when_the_capture_fails(
    monkeypatch: pytest.MonkeyPatch, git_repo: GitRepo, answer: tuple[int | None, str]
) -> None:
    calls = _fake_capture(monkeypatch, answer)
    # The real repository has a HEAD, so only the capture's answer can give None.
    assert relay.git.head(git_repo.root) is None
    assert calls
    assert all(argv[0] == "git" and cwd == git_repo.root for argv, cwd, _t in calls)


def test_head_is_none_outside_a_repository(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert relay.git.head(plain) is None


def test_head_is_none_on_a_directory_that_does_not_exist(tmp_path: Path) -> None:
    assert relay.git.head(tmp_path / "missing") is None


# Behavior 2: `git diff --name-only <commit> -- <paths>` in `cwd`, which compares the working
# tree: False on exit 0 with no output, True on exit 0 with output, None when git fails.


def test_changed_is_false_when_the_paths_match_the_commit(git_repo: GitRepo) -> None:
    commit = _tracked(git_repo, {"a.txt": "a\n", "src/b.py": "b\n"})
    assert relay.git.changed(git_repo.root, commit, ("a.txt",)) is False
    assert relay.git.changed(git_repo.root, commit, ("a.txt", "src/b.py")) is False
    assert relay.git.changed(git_repo.root, commit, ("src",)) is False


def test_changed_is_true_for_an_uncommitted_edit_in_the_working_tree(git_repo: GitRepo) -> None:
    commit = _tracked(git_repo, {"a.txt": "a\n", "src/b.py": "b\n"})
    (git_repo.root / "src" / "b.py").write_text("b edited\n")
    assert relay.git.changed(git_repo.root, commit, ("src/b.py",)) is True
    assert relay.git.changed(git_repo.root, commit, ("a.txt", "src/b.py")) is True
    assert relay.git.changed(git_repo.root, commit, ("src",)) is True


def test_changed_looks_only_at_the_paths_named(git_repo: GitRepo) -> None:
    commit = _tracked(git_repo, {"a.txt": "a\n", "src/b.py": "b\n"})
    (git_repo.root / "src" / "b.py").write_text("b edited\n")
    assert relay.git.changed(git_repo.root, commit, ("a.txt",)) is False


def test_changed_is_true_for_a_path_committed_since_the_commit(git_repo: GitRepo) -> None:
    commit = _tracked(git_repo, {"a.txt": "a\n", "src/b.py": "b\n"})
    _tracked(git_repo, {"a.txt": "a again\n"})
    assert relay.git.changed(git_repo.root, commit, ("a.txt",)) is True
    assert relay.git.changed(git_repo.root, commit, ("src/b.py",)) is False


def test_changed_compares_the_working_tree_of_cwd(git_repo: GitRepo) -> None:
    commit = _tracked(git_repo, {"a.txt": "a\n"})
    git_repo.worktree("s2")
    (git_repo.worktrees["s2"] / "a.txt").write_text("edited in s2\n")
    assert relay.git.changed(git_repo.worktrees["s2"], commit, ("a.txt",)) is True
    assert relay.git.changed(git_repo.root, commit, ("a.txt",)) is False


def test_changed_runs_git_diff_name_only_in_cwd_through_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_capture(monkeypatch, (0, ""))
    assert relay.git.changed(tmp_path, HEAD_OBJECT, ("a.txt", "src")) is False
    assert len(calls) == 1
    argv, cwd, _timeout = calls[0]
    assert argv == ["git", "diff", "--name-only", HEAD_OBJECT, "--", "a.txt", "src"]
    assert cwd == tmp_path


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ((0, ""), False),
        ((0, "a.txt\n"), True),
        ((0, "a.txt\nsrc/b.py\n"), True),
    ],
    ids=["exit-0-no-output", "exit-0-one-path", "exit-0-two-paths"],
)
def test_changed_reads_exit_0_output_from_the_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answer: tuple[int, str], expected: bool
) -> None:
    _fake_capture(monkeypatch, answer)
    assert relay.git.changed(tmp_path, HEAD_OBJECT, ("a.txt", "src/b.py")) is expected


@pytest.mark.parametrize(
    "answer",
    [(128, ""), (None, ""), (128, "a.txt\n"), (1, "a.txt\n")],
    ids=["git-error", "oserror-or-timeout", "git-error-printing-a-path", "exit-1-printing-a-path"],
)
def test_changed_is_none_when_the_capture_fails(
    monkeypatch: pytest.MonkeyPatch, git_repo: GitRepo, answer: tuple[int | None, str]
) -> None:
    commit = git_repo.rev("HEAD")
    calls = _fake_capture(monkeypatch, answer)
    assert relay.git.changed(git_repo.root, commit, ("a.txt",)) is None
    assert calls
    assert all(argv[0] == "git" and cwd == git_repo.root for argv, cwd, _t in calls)


def test_changed_is_none_for_a_commit_git_does_not_know(git_repo: GitRepo) -> None:
    _tracked(git_repo, {"a.txt": "a\n"})
    assert relay.git.changed(git_repo.root, "0" * 40, ("a.txt",)) is None


def test_changed_is_none_outside_a_repository(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert relay.git.changed(plain, HEAD_OBJECT, ("a.txt",)) is None


def test_changed_is_none_on_a_directory_that_does_not_exist(tmp_path: Path) -> None:
    assert relay.git.changed(tmp_path / "missing", HEAD_OBJECT, ("a.txt",)) is None


# Behavior 3: Both run git through `runner.capture`. Neither raises.


def test_head_and_changed_run_git_only_through_capture(
    monkeypatch: pytest.MonkeyPatch, git_repo: GitRepo
) -> None:
    calls = _fake_capture(monkeypatch, (0, HEAD_OBJECT + "\n"))
    assert relay.git.head(git_repo.root) == HEAD_OBJECT
    assert len(calls) == 1
    assert relay.git.changed(git_repo.root, HEAD_OBJECT, ("a.txt",)) is True
    assert len(calls) == 2
    assert [argv[:2] for argv, _cwd, _t in calls] == [["git", "rev-parse"], ["git", "diff"]]


def test_neither_head_nor_changed_raises_on_any_git_failure(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    for cwd in (plain, tmp_path / "missing"):
        assert relay.git.head(cwd) is None
        assert relay.git.changed(cwd, "not-a-commit", ("a.txt",)) is None
