"""Red tests for Relay's research map and answer (design: Modules `relay/research.py`; Order 3)."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import relay.git
import relay.research
from relay.config import Config
from relay.research import Map, block, load, parse_answer, parse_map, save, stale
from tests.conftest import FIXTURES

if TYPE_CHECKING:
    from tests.conftest import GitRepo

SID = "s1"
COMMIT = "0123456789abcdef0123456789abcdef01234567"

# The researcher's final message from `tests/fixtures/research-map.txt`.
MAP_TEXT = (FIXTURES / "research-map.txt").read_text()

# Its block's lines from `MAP` to `END MAP`, both included.
MAP_LINES = MAP_TEXT[
    MAP_TEXT.index("MAP\n") : MAP_TEXT.index("END MAP") + len("END MAP")
].splitlines()

ANSWER_TEXT = (
    "Looked it up.\n"
    "\n"
    "ANSWER\n"
    "relay/git.py:12 | head runs git rev-parse HEAD in the section worktree\n"
    "END ANSWER\n"
)


def _without(text: str, line: str) -> str:
    """`text` with the one line `line` removed."""
    assert line + "\n" in text
    return text.replace(line + "\n", "", 1)


def _with_line_after(text: str, anchor: str, line: str) -> str:
    """`text` with `line` inserted after the line `anchor`."""
    assert anchor + "\n" in text
    return text.replace(anchor + "\n", anchor + "\n" + line + "\n", 1)


# --- parse_map: None when there is no block, a line fits neither form, there is no entry,
# or the block is over the caps (design: `relay/research.py` `parse_map`) ---


def test_the_fixture_map_parses(fake_cfg: Config) -> None:
    # Breaks when parse_map rejects a well-formed block with entries and links.
    m = parse_map(SID, COMMIT, MAP_TEXT, fake_cfg)
    assert m is not None
    assert m.sid == SID
    assert m.commit == COMMIT


def test_parse_map_none_without_result_text(fake_cfg: Config) -> None:
    # Breaks when a run with no result text yields a map.
    assert parse_map(SID, COMMIT, None, fake_cfg) is None


def test_parse_map_none_without_a_block(fake_cfg: Config) -> None:
    # Breaks when parse_map reads map lines that no `MAP` ... `END MAP` block holds.
    text = _without(_without(MAP_TEXT, "MAP"), "END MAP")
    assert parse_map(SID, COMMIT, text, fake_cfg) is None


def test_parse_map_none_when_the_block_never_closes(fake_cfg: Config) -> None:
    # Breaks when a `MAP` line with no closing `END MAP` line counts as a block.
    assert parse_map(SID, COMMIT, _without(MAP_TEXT, "END MAP"), fake_cfg) is None


def test_parse_map_none_when_the_block_never_opens(fake_cfg: Config) -> None:
    # Breaks when an `END MAP` line with no opening `MAP` line counts as a block.
    assert parse_map(SID, COMMIT, _without(MAP_TEXT, "MAP"), fake_cfg) is None


def test_parse_map_none_on_a_prose_line_among_entries(fake_cfg: Config) -> None:
    # Breaks when a line that is neither an entry nor a link is skipped instead of rejected.
    text = _with_line_after(
        MAP_TEXT,
        "relay/git.py:12 | head runs git rev-parse HEAD",
        "Read this file first.",
    )
    assert parse_map(SID, COMMIT, text, fake_cfg) is None


def test_parse_map_none_on_an_entry_without_a_line(fake_cfg: Config) -> None:
    # Breaks when an entry naming a path with no `:<line>` is accepted.
    text = _with_line_after(MAP_TEXT, "MAP", "relay/state.py | the state directory")
    assert parse_map(SID, COMMIT, text, fake_cfg) is None


def test_parse_map_none_on_an_entry_without_what_it_does(fake_cfg: Config) -> None:
    # Breaks when an entry missing its ` | <what it does>` part is accepted.
    text = _with_line_after(MAP_TEXT, "MAP", "relay/state.py:29-38")
    assert parse_map(SID, COMMIT, text, fake_cfg) is None


def test_parse_map_none_on_a_bad_line_among_links(fake_cfg: Config) -> None:
    # Breaks when only the entry lines are checked and a malformed line after `LINKS` passes.
    text = _with_line_after(
        MAP_TEXT, "LINKS", "relay/loop.py:101 calls relay/git.py:12"
    )
    assert parse_map(SID, COMMIT, text, fake_cfg) is None


def test_parse_map_none_without_an_entry(fake_cfg: Config) -> None:
    # Breaks when a block holding only links yields a map.
    text = MAP_TEXT
    for line in MAP_LINES[1:4]:
        text = _without(text, line)
    assert parse_map(SID, COMMIT, text, fake_cfg) is None


def test_parse_map_none_on_an_empty_block(fake_cfg: Config) -> None:
    # Breaks when a block with no lines between `MAP` and `END MAP` yields a map.
    text = MAP_TEXT
    for line in MAP_LINES[1:-1]:
        text = _without(text, line)
    assert parse_map(SID, COMMIT, text, fake_cfg) is None


def test_parse_map_judges_the_last_block(fake_cfg: Config) -> None:
    # Breaks when parse_map takes the first block, or any good block, rather than the last one.
    bad = _with_line_after(MAP_TEXT, "MAP", "Read this file first.")
    assert parse_map(SID, COMMIT, MAP_TEXT + "\n" + bad, fake_cfg) is None


def test_parse_map_takes_the_block_at_the_line_cap(fake_cfg: Config) -> None:
    # Breaks when the line cap rejects a block exactly cfg.map_max_lines lines long.
    cfg = dataclasses.replace(fake_cfg, map_max_lines=len(MAP_LINES))
    assert parse_map(SID, COMMIT, MAP_TEXT, cfg) is not None


def test_parse_map_none_over_the_line_cap(fake_cfg: Config) -> None:
    # Breaks when the line cap is not checked, or is not read from cfg.map_max_lines.
    cfg = dataclasses.replace(fake_cfg, map_max_lines=len(MAP_LINES) - 1)
    assert parse_map(SID, COMMIT, MAP_TEXT, cfg) is None


def test_parse_map_takes_the_block_at_the_char_cap(fake_cfg: Config) -> None:
    # Breaks when the character cap rejects a block exactly cfg.map_max_chars characters long.
    m = parse_map(SID, COMMIT, MAP_TEXT, fake_cfg)
    assert m is not None
    cfg = dataclasses.replace(fake_cfg, map_max_chars=len(m.body))
    assert parse_map(SID, COMMIT, MAP_TEXT, cfg) is not None


def test_parse_map_none_over_the_char_cap(fake_cfg: Config) -> None:
    # Breaks when the character cap is not checked, or is not read from cfg.map_max_chars.
    m = parse_map(SID, COMMIT, MAP_TEXT, fake_cfg)
    assert m is not None
    cfg = dataclasses.replace(fake_cfg, map_max_chars=len(m.body) - 1)
    assert parse_map(SID, COMMIT, MAP_TEXT, cfg) is None


# --- Map.files: every path an entry or link names, sorted, no repeats
# (design: `relay/research.py` `Map`) ---


def test_map_files_are_every_entry_and_link_path_sorted_once(fake_cfg: Config) -> None:
    # Breaks when files keep repeats, keep the researcher's order, drop link paths or keep line numbers.
    m = parse_map(SID, COMMIT, MAP_TEXT, fake_cfg)
    assert m is not None
    assert m.files == ("relay/git.py", "relay/loop.py", "relay/research.py")


def test_map_files_without_links_are_the_entry_paths(fake_cfg: Config) -> None:
    # Breaks when files are taken from somewhere other than the block's own lines.
    text = MAP_TEXT
    for line in MAP_LINES[4:6]:
        text = _without(text, line)
    m = parse_map(SID, COMMIT, text, fake_cfg)
    assert m is not None
    assert m.files == ("relay/git.py", "relay/research.py")


def test_map_files_take_both_ends_of_a_link(fake_cfg: Config) -> None:
    # Breaks when only one side of a link line contributes its path.
    text = _with_line_after(
        MAP_TEXT,
        "LINKS",
        "relay/state.py:209 -> relay/runner.py:133 | the runner touches the retire flag",
    )
    m = parse_map(SID, COMMIT, text, fake_cfg)
    assert m is not None
    assert m.files == (
        "relay/git.py",
        "relay/loop.py",
        "relay/research.py",
        "relay/runner.py",
        "relay/state.py",
    )


# --- parse_answer: None when absent or over cfg.map_max_chars characters
# (design: `relay/research.py` `parse_answer`) ---


def test_parse_answer_none_without_result_text(fake_cfg: Config) -> None:
    # Breaks when a run with no result text yields an answer.
    assert parse_answer(None, fake_cfg) is None


def test_parse_answer_none_without_a_block(fake_cfg: Config) -> None:
    # Breaks when text with no `ANSWER` ... `END ANSWER` block yields an answer.
    text = _without(_without(ANSWER_TEXT, "ANSWER"), "END ANSWER")
    assert parse_answer(text, fake_cfg) is None


def test_parse_answer_none_when_the_block_never_closes(fake_cfg: Config) -> None:
    # Breaks when an `ANSWER` line with no closing `END ANSWER` line counts as a block.
    assert parse_answer(_without(ANSWER_TEXT, "END ANSWER"), fake_cfg) is None


def test_parse_answer_none_on_a_map_alone(fake_cfg: Config) -> None:
    # Breaks when a `MAP` block is taken for an answer.
    assert parse_answer(MAP_TEXT, fake_cfg) is None


def test_parse_answer_takes_the_block_at_the_char_cap(fake_cfg: Config) -> None:
    # Breaks when the character cap rejects an answer exactly cfg.map_max_chars characters long.
    answer = parse_answer(ANSWER_TEXT, fake_cfg)
    assert answer is not None
    cfg = dataclasses.replace(fake_cfg, map_max_chars=len(answer))
    assert parse_answer(ANSWER_TEXT, cfg) == answer


def test_parse_answer_none_over_the_char_cap(fake_cfg: Config) -> None:
    # Breaks when the answer's cap is not checked, or is not read from cfg.map_max_chars.
    answer = parse_answer(ANSWER_TEXT, fake_cfg)
    assert answer is not None
    cfg = dataclasses.replace(fake_cfg, map_max_chars=len(answer) - 1)
    assert parse_answer(ANSWER_TEXT, cfg) is None


# --- save, load, stale and block (design: `relay/research.py` `save`, `load`, `stale`, `block`) ---


def _fixture_map(cfg: Config, sid: str = SID, commit: str = COMMIT) -> Map:
    """The map `tests/fixtures/research-map.txt` holds, for section `sid` at `commit`."""
    m = parse_map(sid, commit, MAP_TEXT, cfg)
    assert m is not None
    return m


# Behavior 1: save writes `map <sid> at <commit>` then m.body to `path` by temp file and
# os.replace, making the parent directory.


def test_save_writes_the_header_line_then_the_body(
    fake_cfg: Config, tmp_path: Path
) -> None:
    # Breaks when save drops or rewords the `map <sid> at <commit>` line, or alters the body.
    m = _fixture_map(fake_cfg)
    path = tmp_path / "s1.map"
    save(m, path)
    lines = path.read_text().splitlines()
    assert lines[0] == f"map {SID} at {COMMIT}"
    assert lines[1:] == m.body.splitlines()


def test_save_makes_the_parent_directory(fake_cfg: Config, tmp_path: Path) -> None:
    # Breaks when save expects the parent directory to exist already.
    m = _fixture_map(fake_cfg)
    path = tmp_path / "state" / "maps" / "s1.map"
    save(m, path)
    assert path.read_text().splitlines()[0] == f"map {SID} at {COMMIT}"


def test_save_moves_a_temp_file_into_place_with_os_replace(
    fake_cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when save writes the map file in place rather than by temp file and os.replace.
    m = _fixture_map(fake_cfg)
    path = tmp_path / "maps" / "s1.map"
    calls: list[tuple[Path, Path]] = []
    real = os.replace

    def spy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        calls.append((Path(src), Path(dst)))
        real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    save(m, path)
    assert len(calls) == 1
    src, dst = calls[0]
    assert dst == path
    assert src != path
    assert not src.exists()
    assert sorted(p.name for p in path.parent.iterdir()) == ["s1.map"]


def test_save_overwrites_a_map_already_there(fake_cfg: Config, tmp_path: Path) -> None:
    # Breaks when save appends to, or refuses to replace, an earlier map file.
    path = tmp_path / "s1.map"
    save(_fixture_map(fake_cfg, commit="1" * 40), path)
    save(_fixture_map(fake_cfg), path)
    lines = path.read_text().splitlines()
    assert lines[0] == f"map {SID} at {COMMIT}"
    assert lines.count("MAP") == 1


# Behaviors 2 and 3: load gives the map saved at `path`; None when the file is missing,
# unreadable, names another section, or its body no longer parses.


def test_load_gives_back_the_map_save_wrote(fake_cfg: Config, tmp_path: Path) -> None:
    # Breaks when load loses the section, the commit, the files or the body save wrote.
    m = _fixture_map(fake_cfg)
    path = tmp_path / "maps" / "s1.map"
    save(m, path)
    assert load(path, SID) == m


def test_load_none_when_the_file_is_missing(tmp_path: Path) -> None:
    # Breaks when a missing map file raises or yields a map.
    assert load(tmp_path / "maps" / "s1.map", SID) is None


def test_load_none_when_the_file_is_unreadable(
    fake_cfg: Config, tmp_path: Path
) -> None:
    # Breaks when an unreadable map file raises instead of giving None.
    path = tmp_path / "s1.map"
    save(_fixture_map(fake_cfg), path)
    path.chmod(0)
    try:
        assert load(path, SID) is None
    finally:
        path.chmod(0o600)


def test_load_none_when_the_path_is_a_directory(tmp_path: Path) -> None:
    # Breaks when a map path that cannot be read as a file raises instead of giving None.
    path = tmp_path / "s1.map"
    path.mkdir()
    assert load(path, SID) is None


def test_load_none_when_the_file_names_another_section(
    fake_cfg: Config, tmp_path: Path
) -> None:
    # Breaks when load ignores the section its header names.
    path = tmp_path / "s1.map"
    save(_fixture_map(fake_cfg), path)
    assert load(path, "s2") is None


def test_load_none_on_an_empty_file(tmp_path: Path) -> None:
    # Breaks when a file with no header line and no body yields a map.
    path = tmp_path / "s1.map"
    path.write_text("")
    assert load(path, SID) is None


def test_load_none_when_the_body_no_longer_parses(
    fake_cfg: Config, tmp_path: Path
) -> None:
    # Breaks when load trusts the saved body instead of parsing it again.
    path = tmp_path / "s1.map"
    save(_fixture_map(fake_cfg), path)
    path.write_text(_with_line_after(path.read_text(), "MAP", "Read this file first."))
    assert load(path, SID) is None


def test_load_none_when_the_body_has_no_entry(fake_cfg: Config, tmp_path: Path) -> None:
    # Breaks when a saved body holding only links passes as a map.
    path = tmp_path / "s1.map"
    save(_fixture_map(fake_cfg), path)
    text = path.read_text()
    for line in MAP_LINES[1:4]:
        text = _without(text, line)
    path.write_text(text)
    assert load(path, SID) is None


# Behavior 4: stale is True unless git.changed(cwd, m.commit, m.files) is False.


def _fake_changed(
    monkeypatch: pytest.MonkeyPatch, answer: bool | None
) -> list[tuple[Path, str, tuple[str, ...]]]:
    """Replace `git.changed` with a recorder answering `answer`, under every name
    `relay.git` or `relay.research` binds it to."""
    calls: list[tuple[Path, str, tuple[str, ...]]] = []

    def fake(cwd: Path, commit: str, paths: tuple[str, ...]) -> bool | None:
        calls.append((Path(cwd), commit, tuple(paths)))
        return answer

    real = relay.git.changed
    monkeypatch.setattr(relay.git, "changed", fake)
    for name, value in list(vars(relay.research).items()):
        if value is real:
            monkeypatch.setattr(relay.research, name, fake)
    return calls


@pytest.mark.parametrize(
    ("answer", "expected"),
    [(False, False), (True, True), (None, True)],
    ids=["unchanged", "changed", "git-failed"],
)
def test_stale_unless_changed_is_false(
    fake_cfg: Config,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: bool | None,
    expected: bool,
) -> None:
    # Breaks when stale trusts a map git could not check, or calls a changed map current.
    m = _fixture_map(fake_cfg)
    calls = _fake_changed(monkeypatch, answer)
    assert stale(m, tmp_path) is expected
    assert calls == [(tmp_path, COMMIT, m.files)]


def _tracked_map_files(git_repo: GitRepo, files: tuple[str, ...]) -> str:
    """Write and commit each of `files` in the fixture repository; return HEAD."""
    for name in files:
        path = git_repo.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{name}\n")
        git_repo.git("add", name)
    git_repo.git("commit", "-q", "-m", "mapped files")
    return git_repo.rev("HEAD")


def test_stale_false_when_the_mapped_files_are_as_at_the_commit(
    fake_cfg: Config, git_repo: GitRepo
) -> None:
    # Breaks when an unchanged repository makes the map stale.
    files = _fixture_map(fake_cfg).files
    commit = _tracked_map_files(git_repo, files)
    m = _fixture_map(fake_cfg, commit=commit)
    git_repo.commit(message="unrelated")
    assert stale(m, git_repo.root) is False


def test_stale_true_when_a_mapped_file_changed(
    fake_cfg: Config, git_repo: GitRepo
) -> None:
    # Breaks when stale does not compare the mapped files' working tree with the map's commit.
    files = _fixture_map(fake_cfg).files
    commit = _tracked_map_files(git_repo, files)
    m = _fixture_map(fake_cfg, commit=commit)
    (git_repo.root / files[0]).write_text("edited\n")
    assert stale(m, git_repo.root) is True


def test_stale_true_when_git_cannot_check_the_commit(
    fake_cfg: Config, git_repo: GitRepo
) -> None:
    # Breaks when a commit git does not know leaves the map current.
    files = _fixture_map(fake_cfg).files
    _tracked_map_files(git_repo, files)
    m = _fixture_map(fake_cfg, commit="0" * 40)
    assert stale(m, git_repo.root) is True


# Behavior 5: block is one paragraph telling the agent to start from the map, open a named
# file only at the lines it gives, and, needing more, say what in its report rather than
# search, since the lead asks the researcher; then `map <sid> at <commit>` and m.body.


def test_block_ends_with_the_header_line_and_the_body(fake_cfg: Config) -> None:
    # Breaks when block leaves out the header or the body, or puts anything after the body.
    m = _fixture_map(fake_cfg)
    lines = block(m).rstrip("\n").splitlines()
    body = m.body.rstrip("\n").splitlines()
    assert lines[-len(body) :] == body
    assert lines[-len(body) - 1] == f"map {SID} at {COMMIT}"


def test_block_opens_with_one_paragraph_of_usage_rule(fake_cfg: Config) -> None:
    # Breaks when block carries no usage paragraph, or splits it into more than one.
    m = _fixture_map(fake_cfg)
    text = block(m)
    rule = text[: text.index(f"map {SID} at {COMMIT}")].strip()
    assert rule
    assert "\n\n" not in rule
    assert "MAP" not in rule.splitlines()


def test_block_rule_says_start_from_the_map_and_report_rather_than_search(
    fake_cfg: Config,
) -> None:
    # Breaks when the paragraph drops the map, its lines, the report, the no-search rule or the researcher.
    m = _fixture_map(fake_cfg)
    text = block(m)
    rule = text[: text.index(f"map {SID} at {COMMIT}")].lower()
    for word in ("map", "line", "report", "search", "researcher"):
        assert word in rule, word


def test_block_names_the_section_and_commit_of_its_map(fake_cfg: Config) -> None:
    # Breaks when block's header line is fixed rather than taken from the map.
    m = _fixture_map(fake_cfg, sid="s7", commit="2" * 40)
    assert f"map s7 at {'2' * 40}" in block(m).splitlines()
