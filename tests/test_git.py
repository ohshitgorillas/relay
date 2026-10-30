"""Red tests for Relay's git queries (design: Modules, `relay/git.py`; Order 3).

The repositories come from the `git_repo` fixture in `tests/conftest.py`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import relay.git
import relay.runner
import relay.state
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


# Queue worktree design, Modules `relay/git.py`: only the exact qualified branch
# is discovered without an explicit binding; git failure still yields None.


def test_section_worktree_is_the_worktree_on_lead_sid(git_repo: GitRepo) -> None:
    queue = git_repo.root / "queue.md"
    expected = git_repo.worktree("s1", queue=queue)
    found = section_worktree(git_repo.root, queue, "s1")
    assert found is not None
    assert found.path.resolve() == expected


def test_section_worktree_picks_the_branch_of_that_sid_among_several(git_repo: GitRepo) -> None:
    queue = git_repo.root / "queue.md"
    expected = {sid: git_repo.worktree(sid, queue=queue) for sid in ("s1", "s10", "s2")}
    for sid in ("s1", "s10", "s2"):
        found = section_worktree(git_repo.root, queue, sid)
        assert found is not None
        assert found.path.resolve() == expected[sid]


def test_section_worktree_answers_the_same_when_run_in_a_worktree(git_repo: GitRepo) -> None:
    queue = git_repo.root / "queue.md"
    first = git_repo.worktree("s1", queue=queue)
    second = git_repo.worktree("s2", queue=queue)
    found = section_worktree(first, queue, "s2")
    assert found is not None
    assert found.path.resolve() == second


@pytest.mark.parametrize("sid", ["s9", "s", "s1.1", "1"])
def test_section_worktree_is_none_when_no_worktree_is_on_that_branch(
    git_repo: GitRepo, sid: str
) -> None:
    queue = git_repo.root / "queue.md"
    git_repo.worktree("s10", queue=queue)
    assert section_worktree(git_repo.root, queue, sid) is None


def test_section_worktree_is_none_for_a_branch_no_worktree_has_checked_out(
    git_repo: GitRepo,
) -> None:
    queue = git_repo.root / "queue.md"
    git_repo.git("branch", relay.git.section_branch(queue, "s3"))
    assert section_worktree(git_repo.root, queue, "s3") is None


def test_section_worktree_parses_the_porcelain_capture_returns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    queue = tmp_path / "queue.md"
    identity = hashlib.sha256(str(queue.resolve()).encode()).hexdigest()
    for name in ("main", "wt-s4", "wt-s10", "detached"):
        (tmp_path / name).mkdir()
    porcelain = PORCELAIN.replace("/nowhere/", f"{tmp_path}/").replace(
        "refs/heads/lead/", f"refs/heads/lead/{identity}/"
    )
    calls = _fake_capture(monkeypatch, (0, porcelain))
    assert section_worktree(tmp_path, queue, "s4") == relay.git.SectionWorktree(
        f"lead/{identity}/s4", tmp_path / "wt-s4"
    )
    assert section_worktree(tmp_path, queue, "s10") == relay.git.SectionWorktree(
        f"lead/{identity}/s10", tmp_path / "wt-s10"
    )
    assert section_worktree(tmp_path, queue, "s1") is None
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
    queue = git_repo.root / "queue.md"
    git_repo.worktree("s1", queue=queue)
    identity = hashlib.sha256(str(queue.resolve()).encode()).hexdigest()
    answer = (answer[0], answer[1].replace("refs/heads/lead/", f"refs/heads/lead/{identity}/"))
    calls = _fake_capture(monkeypatch, answer)
    # A qualified worktree exists, so only the capture's answer can give None.
    assert section_worktree(git_repo.root, queue, "s1") is None
    assert heads(git_repo.root) == {}
    assert len(calls) >= 2
    assert all(argv[0] == "git" and cwd == git_repo.root for argv, cwd, _t in calls)


def test_neither_raises_outside_a_repository(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert section_worktree(plain, tmp_path / "queue.md", "s1") is None
    assert heads(plain) == {}


def test_neither_raises_on_a_directory_that_does_not_exist(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert section_worktree(missing, tmp_path / "queue.md", "s1") is None
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


# The reuse design retires git.changed; head still runs only through capture.


def test_head_runs_git_only_through_capture(
    monkeypatch: pytest.MonkeyPatch, git_repo: GitRepo
) -> None:
    calls = _fake_capture(monkeypatch, (0, HEAD_OBJECT + "\n"))
    assert relay.git.head(git_repo.root) == HEAD_OBJECT
    assert len(calls) == 1
    assert [argv[:2] for argv, _cwd, _t in calls] == [["git", "rev-parse"]]


def test_head_does_not_raise_on_any_git_failure(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    for cwd in (plain, tmp_path / "missing"):
        assert relay.git.head(cwd) is None


# The ladder design's git query (design: relay-ladder-design.md, Modules `relay/git.py`
# (extended); Order 4). The repositories come from the `git_repo` fixture in `tests/conftest.py`.
# Behavior 6: `git status --porcelain` in `cwd`: True on exit 0 with no output, False with
# output, None when git fails.


def test_clean_is_true_for_a_worktree_with_nothing_to_report(git_repo: GitRepo) -> None:
    _tracked(git_repo, {"a.txt": "a\n"})
    assert relay.git.clean(git_repo.root) is True
    assert relay.git.clean(git_repo.worktrees["s1"]) is True


def test_clean_is_false_for_an_edited_tracked_file(git_repo: GitRepo) -> None:
    _tracked(git_repo, {"a.txt": "a\n"})
    (git_repo.root / "a.txt").write_text("a edited\n")
    assert relay.git.clean(git_repo.root) is False


def test_clean_is_false_for_an_untracked_file(git_repo: GitRepo) -> None:
    (git_repo.root / "new.txt").write_text("new\n")
    assert relay.git.clean(git_repo.root) is False


def test_clean_is_false_for_a_staged_change(git_repo: GitRepo) -> None:
    (git_repo.root / "staged.txt").write_text("staged\n")
    git_repo.git("add", "staged.txt")
    assert relay.git.clean(git_repo.root) is False


def test_clean_is_taken_in_cwd_so_each_worktree_answers_for_itself(git_repo: GitRepo) -> None:
    (git_repo.worktrees["s1"] / "dirty.txt").write_text("dirty\n")
    assert relay.git.clean(git_repo.worktrees["s1"]) is False
    assert relay.git.clean(git_repo.root) is True


def test_clean_runs_git_status_porcelain_in_cwd_through_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_capture(monkeypatch, (0, ""))
    assert relay.git.clean(tmp_path) is True
    assert len(calls) == 1
    argv, cwd, _timeout = calls[0]
    assert argv == ["git", "status", "--porcelain"]
    assert cwd == tmp_path


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ((0, ""), True),
        ((0, " M a.txt\n"), False),
        ((0, "?? new.txt\nA  staged.txt\n"), False),
    ],
    ids=["exit-0-no-output", "exit-0-one-line", "exit-0-two-lines"],
)
def test_clean_reads_exit_0_output_from_the_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answer: tuple[int, str], expected: bool
) -> None:
    _fake_capture(monkeypatch, answer)
    assert relay.git.clean(tmp_path) is expected


@pytest.mark.parametrize(
    "answer",
    [(128, ""), (None, ""), (128, " M a.txt\n"), (1, "")],
    ids=["git-error", "oserror-or-timeout", "git-error-printing-a-line", "exit-1-no-output"],
)
def test_clean_is_none_when_the_capture_fails(
    monkeypatch: pytest.MonkeyPatch, git_repo: GitRepo, answer: tuple[int | None, str]
) -> None:
    calls = _fake_capture(monkeypatch, answer)
    # The real main checkout is clean, so only the capture's answer can give None.
    assert relay.git.clean(git_repo.root) is None
    assert calls
    assert all(argv[0] == "git" and cwd == git_repo.root for argv, cwd, _t in calls)


def test_clean_is_none_outside_a_repository(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert relay.git.clean(plain) is None


def test_clean_is_none_on_a_directory_that_does_not_exist(tmp_path: Path) -> None:
    assert relay.git.clean(tmp_path / "missing") is None


# Queue worktree design, Modules `relay/git.py`: truncating or independently
# slugging queue identities would make this test fail.
def test_qualified_branch_uses_full_resolved_queue_identity(tmp_path: Path) -> None:
    queue = tmp_path / "queue..with invalid ref characters.md"
    identity = hashlib.sha256(str(queue.resolve()).encode()).hexdigest()
    assert relay.git.section_branch(queue, "s1") == f"lead/{identity}/s1"
    assert relay.git.section_branch(tmp_path / "unused" / ".." / queue.name, "s1") == (
        f"lead/{identity}/s1"
    )
    other = tmp_path / "other" / queue.name
    other_identity = hashlib.sha256(str(other.resolve()).encode()).hexdigest()
    assert relay.git.section_branch(other, "s1") == f"lead/{other_identity}/s1"
    assert identity != other_identity


# Recomputing an otherwise correct hash outside state.queue_id would break this
# controlled identity's propagation into both names and worktree selection.
def test_worktree_names_and_lookup_use_the_shared_queue_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    queue = tmp_path / "queue.md"
    identity = "b" * 64

    def controlled_identity(path: Path) -> str:
        assert path == queue
        return identity

    original = relay.state.queue_id
    monkeypatch.setattr(relay.state, "queue_id", controlled_identity)
    for name, value in list(vars(relay.git).items()):
        if value is original:
            monkeypatch.setattr(relay.git, name, controlled_identity)

    branch = f"lead/{identity}/s1"
    path = tmp_path.parent / (tmp_path.name + "-wt") / identity / "s1"
    path.mkdir(parents=True)
    _fake_capture(
        monkeypatch,
        (0, f"worktree {path}\nHEAD {'1' * 40}\nbranch refs/heads/{branch}\n\n"),
    )
    assert relay.git.section_branch(queue, "s1") == branch
    assert relay.git.section_path(tmp_path, queue, "s1") == path
    assert section_worktree(tmp_path, queue, "s1") == relay.git.SectionWorktree(branch, path)


# A second lookup or accepting a prefix branch would break this exact selection.
def test_qualified_lookup_reads_porcelain_once_through_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    queue = tmp_path / "queue.md"
    identity = hashlib.sha256(str(queue.resolve()).encode()).hexdigest()
    branch = f"lead/{identity}/s1"
    path = tmp_path / "owned tree"
    path.mkdir()
    calls = _fake_capture(
        monkeypatch,
        (
            0,
            f"worktree {tmp_path}\nHEAD {'1' * 40}\nbranch refs/heads/main\n\n"
            f"worktree {path}\nHEAD {'2' * 40}\nbranch refs/heads/{branch}\n\n",
        ),
    )
    assert section_worktree(tmp_path, queue, "s1") == relay.git.SectionWorktree(branch, path)
    assert len(calls) == 1
    argv, cwd, _timeout = calls[0]
    assert argv == ["git", "worktree", "list", "--porcelain"]
    assert cwd == tmp_path


# Accepting bindings by path alone, branch alone, or foreign qualified ownership
# would break these rejections.
@pytest.mark.parametrize(
    "mismatch",
    ["path", "branch", "split-records", "detached", "missing", "foreign-queue", "foreign-section"],
)
def test_explicit_binding_requires_the_owned_branch_and_resolved_path_together(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mismatch: str
) -> None:
    queue = tmp_path / "queue.md"
    identity = hashlib.sha256(str(queue.resolve()).encode()).hexdigest()
    branch = f"lead/{identity}/s1"
    path = tmp_path / "owned"
    path.mkdir()
    listed_path = path
    listed_branch = branch
    if mismatch in {"path", "split-records"}:
        listed_path = tmp_path
    elif mismatch == "branch":
        listed_branch = "custom/changed"
    elif mismatch == "missing":
        path = tmp_path / "stale"
        listed_path = path
    elif mismatch == "foreign-queue":
        foreign = hashlib.sha256(str((tmp_path / "other.md").resolve()).encode()).hexdigest()
        branch = listed_branch = f"lead/{foreign}/s1"
    elif mismatch == "foreign-section":
        branch = listed_branch = f"lead/{identity}/s2"
    branch_line = "detached" if mismatch == "detached" else f"branch refs/heads/{listed_branch}"
    output = f"worktree {listed_path}\nHEAD {'1' * 40}\n{branch_line}\n\n"
    if mismatch == "split-records":
        output += f"worktree {path}\nHEAD {'2' * 40}\nbranch refs/heads/custom/changed\n\n"
    _fake_capture(
        monkeypatch,
        (0, output),
    )
    assert section_worktree(tmp_path, queue, "s1", relay.git.SectionWorktree(branch, path)) is None


# Trusting partial stdout from failed git would break this rejection.
@pytest.mark.parametrize("returncode", [1, 128, None])
def test_queue_lookup_rejects_partial_output_when_git_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, returncode: int | None
) -> None:
    queue = tmp_path / "queue.md"
    identity = hashlib.sha256(str(queue.resolve()).encode()).hexdigest()
    branch = f"lead/{identity}/s1"
    _fake_capture(
        monkeypatch,
        (returncode, f"worktree {tmp_path}\nHEAD {'1' * 40}\nbranch refs/heads/{branch}\n\n"),
    )
    assert section_worktree(tmp_path, queue, "s1") is None
    assert section_worktree(tmp_path, queue, "s1", relay.git.SectionWorktree(branch, tmp_path)) is None


# Reading another repository's worktree list would make this foreign binding pass.
def test_explicit_binding_does_not_adopt_a_worktree_from_another_repository(
    git_repo: GitRepo, tmp_path: Path
) -> None:
    other = tmp_path / "other-repository"
    other.mkdir()
    git_repo.git("init", "-q", "-b", "main", str(other))
    queue = other / "queue.md"
    recorded = relay.git.SectionWorktree("lead/s1", git_repo.worktrees["s1"])
    assert section_worktree(other, queue, "s1", recorded) is None


# Requiring a literal path spelling instead of resolving aliases would reject this binding.
def test_explicit_legacy_binding_resolves_path_aliases(git_repo: GitRepo) -> None:
    path = git_repo.worktrees["s1"]
    recorded = relay.git.SectionWorktree("lead/s1", path / ".." / path.name)
    assert section_worktree(git_repo.root, git_repo.root / "queue.md", "s1", recorded) == (
        relay.git.SectionWorktree("lead/s1", path)
    )


# Requiring legacy branches to be renamed, or preferring qualified discovery over
# an explicit legacy binding, would break this compatibility claim.
@pytest.mark.parametrize("legacy", ["lead/s1", "custom/old-work"])
def test_recorded_legacy_branch_stays_usable_beside_a_qualified_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, legacy: str
) -> None:
    queue = tmp_path / "queue.md"
    identity = hashlib.sha256(str(queue.resolve()).encode()).hexdigest()
    qualified = f"lead/{identity}/s1"
    path = tmp_path / "old-location"
    path.mkdir()
    _fake_capture(
        monkeypatch,
        (
            0,
            f"worktree {path}\nHEAD {'1' * 40}\nbranch refs/heads/{legacy}\n\n"
            f"worktree {tmp_path}\nHEAD {'2' * 40}\nbranch refs/heads/{qualified}\n\n",
        ),
    )
    recorded = relay.git.SectionWorktree(legacy, path)
    assert section_worktree(tmp_path, queue, "s1", recorded) == recorded


# Guessing ownership from a bare sid, queue basename, worktree basename, or the
# sole listed worktree would break these no-binding rejections.
@pytest.mark.parametrize(
    "candidate",
    ["lead/s1", "lead/queue/s1", "custom/s1", "foreign-queue", "foreign-section"],
)
def test_unrecorded_lookup_accepts_no_legacy_or_foreign_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, candidate: str
) -> None:
    queue = tmp_path / "queue.md"
    identity = hashlib.sha256(str(queue.resolve()).encode()).hexdigest()
    if candidate == "foreign-queue":
        foreign = hashlib.sha256(
            str((tmp_path / "elsewhere" / queue.name).resolve()).encode()
        ).hexdigest()
        candidate = f"lead/{foreign}/s1"
    elif candidate == "foreign-section":
        candidate = f"lead/{identity}/s10"
    path = tmp_path / "s1"
    path.mkdir()
    _fake_capture(
        monkeypatch,
        (0, f"worktree {path}\nHEAD {'1' * 40}\nbranch refs/heads/{candidate}\n\n"),
    )
    assert section_worktree(tmp_path, queue, "s1") is None
