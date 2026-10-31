"""Red tests for Relay's research map and answer (design: Modules `relay/research.py`; Order 3)."""

from __future__ import annotations

import dataclasses
import hashlib
import os
from pathlib import Path

import pytest

import relay.research
from relay.config import Config
from relay.research import (
    UNKNOWN,
    Map,
    block,
    changed,
    digest,
    load,
    parse_answer,
    parse_map,
    parse_refresh,
    save,
    split,
    stamp,
)
from tests.conftest import FIXTURES

SID = "s1"
COMMIT = "0123456789abcdef0123456789abcdef01234567"

# The researcher's final message from `tests/fixtures/research-map.txt`.
MAP_TEXT = (FIXTURES / "research-map.txt").read_text()

# Its block's lines from `MAP` to `END MAP`, both included.
MAP_LINES = MAP_TEXT[
    MAP_TEXT.index("MAP\n") : MAP_TEXT.index("END MAP") + len("END MAP")
].splitlines()

# That block's text from `MAP` through `END MAP`, with no newline after it.
MAP_BLOCK = "\n".join(MAP_LINES)

# The result text cut off right after `END MAP`, so its block is exactly MAP_BLOCK whether
# or not a newline after `END MAP` would count as part of the block.
MAP_TEXT_UNENDED = MAP_TEXT[: MAP_TEXT.index("END MAP") + len("END MAP")]

ANSWER_TEXT = (
    "Looked it up.\n"
    "\n"
    "ANSWER\n"
    "relay/git.py:12 | head runs git rev-parse HEAD in the section worktree\n"
    "END ANSWER\n"
)

# Its block's lines from `ANSWER` to `END ANSWER`, both included, with no newline after.
ANSWER_BLOCK = (
    "ANSWER\nrelay/git.py:12 | head runs git rev-parse HEAD in the section worktree\nEND ANSWER"
)

# The answer's result text cut off right after `END ANSWER`.
ANSWER_TEXT_UNENDED = ANSWER_TEXT.removesuffix("\n")


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
    assert m.body.splitlines() == MAP_LINES


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
    text = _with_line_after(MAP_TEXT, "LINKS", "relay/loop.py:101 calls relay/git.py:12")
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


def test_parse_map_takes_a_good_last_block_after_a_bad_one(fake_cfg: Config) -> None:
    # Breaks when parse_map rejects the text because an earlier block is malformed, or reads
    # lines from the first `MAP` to the last `END MAP`.
    bad = "MAP\nrelay/state.py:1 | the state directory\nRead this file first.\nEND MAP\n"
    m = parse_map(SID, COMMIT, bad + "\n" + MAP_TEXT, fake_cfg)
    assert m is not None
    assert m.files == ("relay/git.py", "relay/loop.py", "relay/research.py")
    assert m.body.splitlines() == MAP_LINES


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
    cfg = dataclasses.replace(fake_cfg, map_max_chars=len(MAP_BLOCK))
    assert parse_map(SID, COMMIT, MAP_TEXT_UNENDED, cfg) is not None


def test_parse_map_none_over_the_char_cap(fake_cfg: Config) -> None:
    # Breaks when the character cap is not checked, or is not read from cfg.map_max_chars.
    cfg = dataclasses.replace(fake_cfg, map_max_chars=len(MAP_BLOCK) - 1)
    assert parse_map(SID, COMMIT, MAP_TEXT_UNENDED, cfg) is None


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


def test_parse_answer_gives_the_block_from_answer_to_end_answer(
    fake_cfg: Config,
) -> None:
    # Breaks when parse_answer returns the whole result text, or drops the `ANSWER` or
    # `END ANSWER` line.
    answer = parse_answer(ANSWER_TEXT, fake_cfg)
    assert answer is not None
    assert answer.splitlines() == ANSWER_BLOCK.splitlines()


def test_parse_answer_takes_the_last_block(fake_cfg: Config) -> None:
    # Breaks when parse_answer takes the first of two blocks, or spans from the first
    # `ANSWER` to the last `END ANSWER`.
    first = "ANSWER\nrelay/state.py:1 | an earlier answer\nEND ANSWER\n"
    answer = parse_answer(first + "\n" + ANSWER_TEXT, fake_cfg)
    assert answer is not None
    assert answer.splitlines() == ANSWER_BLOCK.splitlines()


def test_parse_answer_takes_the_block_at_the_char_cap(fake_cfg: Config) -> None:
    # Breaks when the character cap rejects an answer exactly cfg.map_max_chars characters long.
    cfg = dataclasses.replace(fake_cfg, map_max_chars=len(ANSWER_BLOCK))
    answer = parse_answer(ANSWER_TEXT_UNENDED, cfg)
    assert answer is not None
    assert answer.splitlines() == ANSWER_BLOCK.splitlines()


def test_parse_answer_none_over_the_char_cap(fake_cfg: Config) -> None:
    # Breaks when the answer's cap is not checked, or is not read from cfg.map_max_chars.
    cfg = dataclasses.replace(fake_cfg, map_max_chars=len(ANSWER_BLOCK) - 1)
    assert parse_answer(ANSWER_TEXT_UNENDED, cfg) is None


# --- save, load, stale and block (design: `relay/research.py` `save`, `load`, `stale`, `block`) ---


def _fixture_map(cfg: Config, sid: str = SID, commit: str = COMMIT) -> Map:
    """The map `tests/fixtures/research-map.txt` holds, for section `sid` at `commit`."""
    m = parse_map(sid, commit, MAP_TEXT, cfg)
    assert m is not None
    return m


# Behavior 1: save writes `map <sid> at <commit>` then m.body to `path` by temp file and
# os.replace, making the parent directory.


def test_save_writes_the_header_line_then_the_body(fake_cfg: Config, tmp_path: Path) -> None:
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
    # Breaks when save writes the map file in place rather than by temp file and os.replace,
    # removes the old map before the new one is whole, or leaves its temp file behind.
    path = tmp_path / "maps" / "s1.map"
    save(_fixture_map(fake_cfg, commit="1" * 40), path)
    old_text = path.read_text()
    old_inode = path.stat().st_ino
    seen: list[tuple[Path, Path, str, str]] = []
    real_replace = os.replace

    def spy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        # At the rename, the map's name still holds the old map whole and the temp file
        # already holds the new one whole.
        seen.append((Path(src), Path(dst), Path(dst).read_text(), Path(src).read_text()))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    for name, value in list(vars(relay.research).items()):
        if value is real_replace:
            monkeypatch.setattr(relay.research, name, spy)
    fd = os.open(path, os.O_RDONLY)
    try:
        save(_fixture_map(fake_cfg), path)
        # The old file stays whole: a new file takes its name rather than being written over.
        assert os.pread(fd, len(old_text) + 1, 0).decode() == old_text
    finally:
        os.close(fd)
    assert path.stat().st_ino != old_inode
    assert path.read_text().splitlines()[0] == f"map {SID} at {COMMIT}"
    assert sorted(p.name for p in path.parent.iterdir()) == ["s1.map"]
    # One os.replace, from a separate temp path onto the map's name.
    assert len(seen) == 1
    src, dst, dst_text, src_text = seen[0]
    assert dst.resolve() == path.resolve()
    assert src.resolve() != path.resolve()
    assert dst_text == old_text
    assert src_text == path.read_text()


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


def test_load_none_when_the_file_is_unreadable(fake_cfg: Config, tmp_path: Path) -> None:
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


def test_load_none_when_the_file_names_another_section(fake_cfg: Config, tmp_path: Path) -> None:
    # Breaks when load ignores the section its header names.
    path = tmp_path / "s1.map"
    save(_fixture_map(fake_cfg), path)
    assert load(path, "s2") is None


def test_load_none_on_an_empty_file(tmp_path: Path) -> None:
    # Breaks when a file with no header line and no body yields a map.
    path = tmp_path / "s1.map"
    path.write_text("")
    assert load(path, SID) is None


def test_load_none_when_the_body_no_longer_parses(fake_cfg: Config, tmp_path: Path) -> None:
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


# Content-based freshness replaces the former commit-based stale tests
# (relay-research-reuse-design.md, Modules relay/research.py).


def _materialize_map(m: Map, cwd: Path) -> tuple[str, ...]:
    """Write distinct bytes for each mapped path and return their known SHA256 digests."""
    hashes = []
    for name in m.files:
        path = cwd / name
        path.parent.mkdir(parents=True, exist_ok=True)
        content = f"mapped bytes for {name}\n".encode()
        path.write_bytes(content)
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
        hashes.append(hashlib.sha256(content).hexdigest())
    return tuple(hashes)


def test_digest_hashes_file_bytes_without_decoding(tmp_path: Path) -> None:
    # Breaks when digest hashes a name, metadata, or decoded text rather than raw bytes.
    content = b"\x00\xff\r\nraw\x80"
    (tmp_path / "binary").write_bytes(content)
    assert digest(tmp_path, "binary") == hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize("kind", ["missing", "directory", "unreadable"])
def test_digest_unknown_when_a_path_is_not_a_readable_file(tmp_path: Path, kind: str) -> None:
    # Breaks when a missing, non-regular, or unreadable path raises or gains a reusable digest.
    assert UNKNOWN == "-"
    path = tmp_path / "source"
    if kind == "directory":
        path.mkdir()
    elif kind == "unreadable":
        path.write_bytes(b"private")
        path.chmod(0)
    try:
        assert digest(tmp_path, "source") == UNKNOWN
    finally:
        if kind == "unreadable":
            path.chmod(0o600)


def test_stamp_aligns_digests_with_every_mapped_path(fake_cfg: Config, tmp_path: Path) -> None:
    # Breaks when stamping misses link-only files, misorders digests, or changes map text.
    m = _fixture_map(fake_cfg)
    hashes = _materialize_map(m, tmp_path)
    stamped = stamp(m, tmp_path, 2_000_000_000)
    assert stamped == dataclasses.replace(m, digests=hashes)
    assert m.digests == ()


@pytest.mark.parametrize("mtime_ns", [2_000_000_000, 2_000_000_001])
def test_stamp_marks_files_touched_during_research_unknown(
    fake_cfg: Config, tmp_path: Path, mtime_ns: int
) -> None:
    # Breaks when a file edited at or after the research start gets certified as mapped.
    m = _fixture_map(fake_cfg)
    hashes = list(_materialize_map(m, tmp_path))
    os.utime(tmp_path / m.files[1], ns=(mtime_ns, mtime_ns))
    hashes[1] = UNKNOWN
    assert stamp(m, tmp_path, 2_000_000_000).digests == tuple(hashes)


def test_stamp_marks_missing_mapped_files_unknown(fake_cfg: Config, tmp_path: Path) -> None:
    # Breaks when a map can certify a file absent from the worktree after research.
    m = _fixture_map(fake_cfg)
    hashes = list(_materialize_map(m, tmp_path))
    (tmp_path / m.files[-1]).unlink()
    hashes[-1] = UNKNOWN
    assert stamp(m, tmp_path, 2_000_000_000).digests == tuple(hashes)


def test_changed_reuses_identical_content_in_another_checkout_without_git(
    fake_cfg: Config, tmp_path: Path
) -> None:
    # Breaks when freshness depends on HEAD, a checkout's identity, tracking, or file mtimes.
    m = _fixture_map(fake_cfg, commit="unresolvable-commit")
    first = tmp_path / "main"
    second = tmp_path / "lead"
    hashes = _materialize_map(m, first)
    _materialize_map(m, second)
    for name in m.files:
        os.utime(second / name, ns=(9_000_000_000, 9_000_000_000))
    (second / "unrelated").write_text("unmapped new file")
    assert changed(dataclasses.replace(m, digests=hashes), second) == frozenset()


def test_changed_reports_only_changed_mapped_files_including_link_endpoints(
    fake_cfg: Config, tmp_path: Path
) -> None:
    # Breaks when one edit invalidates everything, a link-only path is ignored, or mtime hides edits.
    m = _fixture_map(fake_cfg)
    hashes = _materialize_map(m, tmp_path)
    link_path = "relay/loop.py"
    before = (tmp_path / link_path).stat().st_mtime_ns
    (tmp_path / link_path).write_text("changed link target\n")
    os.utime(tmp_path / link_path, ns=(before, before))
    (tmp_path / m.files[-1]).unlink()
    assert changed(dataclasses.replace(m, digests=hashes), tmp_path) == frozenset(
        {link_path, m.files[-1]}
    )


def test_changed_never_reuses_unknown_digests(fake_cfg: Config, tmp_path: Path) -> None:
    # Breaks when UNKNOWN compares equal to a missing file's UNKNOWN and appears current.
    m = _fixture_map(fake_cfg)
    hashes = list(_materialize_map(m, tmp_path))
    hashes[0] = UNKNOWN
    hashes[1] = UNKNOWN
    (tmp_path / m.files[1]).unlink()
    assert changed(dataclasses.replace(m, digests=tuple(hashes)), tmp_path) == frozenset(
        m.files[:2]
    )


def test_legacy_map_loads_but_requires_all_files_to_be_remapped(
    fake_cfg: Config, tmp_path: Path
) -> None:
    # Breaks when old map files fail to load, or receive unwarranted freshness without digests.
    m = _fixture_map(fake_cfg)
    _materialize_map(m, tmp_path)
    path = tmp_path / "legacy.map"
    path.write_text(f"map {SID} at {COMMIT}\n{m.body}\n")
    legacy = load(path, SID)
    assert legacy is not None
    assert legacy.digests == ()
    assert changed(legacy, tmp_path) == frozenset(m.files)


def test_save_and_load_preserve_per_file_digests(fake_cfg: Config, tmp_path: Path) -> None:
    # Breaks when persistence drops, reorders, or omits a digest or puts it inside the MAP block.
    m = _fixture_map(fake_cfg)
    hashes = _materialize_map(m, tmp_path)
    stamped = dataclasses.replace(m, digests=hashes)
    path = tmp_path / "stamped.map"
    save(stamped, path)
    assert path.read_text().splitlines() == [
        f"map {SID} at {COMMIT}",
        *[f"file {value} {name}" for name, value in zip(m.files, hashes, strict=True)],
        *m.body.splitlines(),
    ]
    assert load(path, SID) == stamped


@pytest.mark.parametrize("bad", ["malformed", "missing", "extra", "duplicate", "invalid-digest"])
def test_load_rejects_invalid_digest_metadata(fake_cfg: Config, tmp_path: Path, bad: str) -> None:
    # Breaks when partial, duplicate, malformed, or mismatched metadata can certify a saved map.
    m = _fixture_map(fake_cfg)
    records = [f"file {'a' * 64} {name}" for name in m.files]
    if bad == "malformed":
        records[0] = "file missing-path"
    elif bad == "missing":
        records.pop()
    elif bad == "extra":
        records.append(f"file {'b' * 64} unrelated.py")
    elif bad == "duplicate":
        records.append(records[0])
    else:
        records[0] = f"file not-a-digest {m.files[0]}"
    path = tmp_path / "broken.map"
    path.write_text("\n".join([f"map {SID} at {COMMIT}", *records, m.body, ""]))
    assert load(path, SID) is None


def test_split_preserves_entry_order_and_only_links_with_two_unchanged_ends(
    fake_cfg: Config,
) -> None:
    # Breaks when split drops duplicate entries on kept files or retains a link touching an edit.
    m = _fixture_map(fake_cfg)
    hashes = tuple(hashlib.sha256(name.encode()).hexdigest() for name in m.files)
    m = dataclasses.replace(m, digests=hashes)
    kept = split(m, frozenset({"relay/git.py"}))
    assert kept is not None
    assert kept.body.splitlines() == ["MAP", MAP_LINES[1], MAP_LINES[3], "END MAP"]
    assert kept.files == ("relay/research.py",)
    assert kept.digests == (hashes[m.files.index("relay/research.py")],)
    assert kept.sid == m.sid
    assert kept.commit == m.commit


def test_split_keeps_links_when_both_ends_are_unchanged(fake_cfg: Config) -> None:
    # Breaks when split drops all links rather than just those incident to changed files.
    m = _fixture_map(fake_cfg)
    hashes = tuple(hashlib.sha256(name.encode()).hexdigest() for name in m.files)
    kept = split(dataclasses.replace(m, digests=hashes), frozenset({"relay/research.py"}))
    assert kept is not None
    assert kept.body.splitlines() == ["MAP", MAP_LINES[2], "LINKS", MAP_LINES[5], "END MAP"]
    assert kept.files == ("relay/git.py", "relay/loop.py")
    assert kept.digests == hashes[:2]


def test_split_returns_none_when_no_entry_survives(fake_cfg: Config) -> None:
    # Breaks when a residual link-only or empty map prevents a necessary full map.
    m = _fixture_map(fake_cfg)
    assert split(m, frozenset({"relay/git.py", "relay/research.py"})) is None


def test_parse_refresh_merges_entries_then_links_without_old_digests(
    fake_cfg: Config,
) -> None:
    # Breaks when refresh loses kept lines, reorders their groups, or keeps obsolete digests.
    m = _fixture_map(fake_cfg)
    kept = dataclasses.replace(m, digests=tuple("a" * 64 for _name in m.files))
    refresh = "MAP\nnew.py:8 | new code\nLINKS\nnew.py:8 -> relay/git.py:12 | calls head\nEND MAP"
    merged = parse_refresh(kept, "next-commit", frozenset({"old.py"}), refresh, fake_cfg)
    assert merged is not None
    assert merged.body.splitlines() == [
        "MAP",
        *MAP_LINES[1:4],
        "new.py:8 | new code",
        "LINKS",
        MAP_LINES[5],
        "new.py:8 -> relay/git.py:12 | calls head",
        "END MAP",
    ]
    assert merged.files == ("new.py", *m.files)
    assert merged.sid == SID
    assert merged.commit == "next-commit"
    assert merged.digests == ()


@pytest.mark.parametrize(
    "refresh",
    [
        "MAP\nEND MAP",
        "MAP\nLINKS\nnew.py:1 -> relay/git.py:12 | dependency\nEND MAP",
    ],
)
def test_parse_refresh_accepts_no_entry_when_kept_entries_remain(
    fake_cfg: Config, refresh: str
) -> None:
    # Breaks when a no-entry refresh is rejected or loses/reorders kept entries and links.
    kept = _fixture_map(fake_cfg)
    merged = parse_refresh(kept, "new", frozenset({"removed.py"}), refresh, fake_cfg)
    assert merged is not None
    assert merged.body.splitlines() == [
        *MAP_LINES[:-1],
        *(["new.py:1 -> relay/git.py:12 | dependency"] if "LINKS" in refresh.splitlines() else []),
        "END MAP",
    ]
    for entry in MAP_LINES[1:4]:
        assert entry in merged.body.splitlines()
    assert "removed.py" not in merged.files
    assert ("new.py" in merged.files) is ("new.py" in refresh)
    if "LINKS" in refresh.splitlines():
        assert "new.py:1 -> relay/git.py:12 | dependency" in merged.body.splitlines()


@pytest.mark.parametrize(
    "refresh",
    [
        None,
        "No map",
        "MAP\nnew.py:1 | never closed",
        "MAP\nbad prose\nEND MAP",
        "MAP\nLINKS\nnot a link\nEND MAP",
        "MAP\nrelay/research.py:99 | conflicts with kept entry\nEND MAP",
    ],
)
def test_parse_refresh_rejects_absent_malformed_or_conflicting_blocks(
    fake_cfg: Config, refresh: str | None
) -> None:
    # Breaks when a failed partial response or an attempt to overwrite kept entries is merged.
    assert (
        parse_refresh(_fixture_map(fake_cfg), "new", frozenset({"changed.py"}), refresh, fake_cfg)
        is None
    )


def test_parse_refresh_uses_the_last_complete_block(fake_cfg: Config) -> None:
    # Breaks when a valid earlier refresh masks the final malformed block.
    text = "MAP\nnew.py:1 | first\nEND MAP\nMAP\ninvalid final\nEND MAP"
    assert (
        parse_refresh(_fixture_map(fake_cfg), "new", frozenset({"changed.py"}), text, fake_cfg)
        is None
    )


@pytest.mark.parametrize("limit", ["lines", "chars"])
def test_parse_refresh_checks_caps_on_the_merged_map(fake_cfg: Config, limit: str) -> None:
    # Breaks when each component fits but their combined map exceeds either configured cap.
    kept = _fixture_map(fake_cfg)
    text = "MAP\nnew.py:1 | added code\nEND MAP"
    expected = "\n".join(
        [
            "MAP",
            *MAP_LINES[1:4],
            "new.py:1 | added code",
            "LINKS",
            MAP_LINES[5],
            "END MAP",
        ]
    )
    size = len(expected.splitlines()) if limit == "lines" else len(expected)
    field = "map_max_lines" if limit == "lines" else "map_max_chars"
    exact = dataclasses.replace(fake_cfg, **{field: size})
    short = dataclasses.replace(fake_cfg, **{field: size - 1})
    merged = parse_refresh(kept, "new", frozenset({"changed.py"}), text, exact)
    assert merged is not None
    assert merged.body == expected
    assert parse_refresh(kept, "new", frozenset({"changed.py"}), text, short) is None


# Behavior 5: block is `map <sid> at <commit>` and m.body, with no instruction lines
# (docs/superpowers/specs/relay-run-overhead-design.md:75, :132).


def test_block_ends_with_the_header_line_and_the_body(fake_cfg: Config) -> None:
    # Breaks when block leaves out the header or the body, or puts anything after the body.
    m = _fixture_map(fake_cfg)
    lines = block(m).rstrip("\n").splitlines()
    body = m.body.rstrip("\n").splitlines()
    assert lines[-len(body) :] == body
    assert lines[-len(body) - 1] == f"map {SID} at {COMMIT}"


def test_block_names_the_section_and_commit_of_its_map(fake_cfg: Config) -> None:
    # Breaks when block's header line is fixed rather than taken from the map.
    m = _fixture_map(fake_cfg, sid="s7", commit="2" * 40)
    assert f"map s7 at {'2' * 40}" in block(m).splitlines()


def test_save_places_queue_provenance_before_file_records(fake_cfg: Config, tmp_path: Path) -> None:
    # Breaks when storage drops provenance or places it among file records or map text.
    original = _fixture_map(fake_cfg)
    hashes = _materialize_map(original, tmp_path)
    m = dataclasses.replace(original, queue="a" * 64, digests=hashes)
    path = tmp_path / "owned.map"
    save(m, path)
    assert path.read_text().splitlines() == [
        f"map {SID} at {COMMIT}",
        f"queue {m.queue}",
        *[f"file {value} {name}" for name, value in zip(m.files, hashes, strict=True)],
        *m.body.splitlines(),
    ]


@pytest.mark.parametrize("with_digests", [False, True])
def test_load_restores_queue_without_exposing_metadata_to_agents(
    fake_cfg: Config, tmp_path: Path, with_digests: bool
) -> None:
    # Breaks when loading loses ownership, rejects old maps, or exposes storage metadata.
    original = _fixture_map(fake_cfg)
    hashes = _materialize_map(original, tmp_path) if with_digests else ()
    original = dataclasses.replace(original, digests=hashes)
    records = [f"file {value} {name}" for name, value in zip(original.files, hashes)]
    path = tmp_path / "owned.map"
    path.write_text("\n".join([f"map {SID} at {COMMIT}", *records, original.body, ""]))
    legacy = load(path, SID)
    assert legacy == original
    assert legacy.queue is None
    key = "b" * 64
    path.write_text(
        "\n".join([f"map {SID} at {COMMIT}", f"queue {key}", *records, original.body, ""])
    )
    restored = load(path, SID)
    assert restored == dataclasses.replace(original, queue=key)
    assert block(restored) == block(original)


@pytest.mark.parametrize(
    "records",
    [
        "queue",
        "queue ",
        "queue not-a-queue-id",
        f"queue {'c' * 63}",
        f"queue {'g' * 64}",
        f"queue {'c' * 64} extra",
        f"queue {'c' * 64}\nqueue {'c' * 64}",
        f"queue {'c' * 64}\nqueue {'d' * 64}",
    ],
    ids=[
        "no-value",
        "empty",
        "not-digest",
        "short",
        "non-hex",
        "extra-token",
        "duplicate",
        "two-owners",
    ],
)
def test_load_rejects_malformed_or_duplicate_queue_records(
    fake_cfg: Config, tmp_path: Path, records: str
) -> None:
    # Breaks when malformed ownership or multiple provenance records are silently accepted.
    m = _fixture_map(fake_cfg)
    path = tmp_path / "invalid-owner.map"
    path.write_text(f"map {SID} at {COMMIT}\n{records}\n{m.body}\n")
    assert load(path, SID) is None


def test_split_retains_queue_provenance(fake_cfg: Config) -> None:
    # Breaks when keeping unchanged entries strips the owner of their research map.
    original = _fixture_map(fake_cfg)
    m = dataclasses.replace(original, queue="d" * 64)
    kept = split(m, frozenset({"relay/git.py"}))
    assert kept is not None
    assert kept.queue == m.queue
    assert kept.sid == m.sid
    assert kept.commit == m.commit


def test_refresh_retains_queue_provenance(fake_cfg: Config) -> None:
    # Breaks when a partial map refresh loses its kept map's queue owner.
    original = _fixture_map(fake_cfg)
    kept = dataclasses.replace(original, queue="e" * 64)
    merged = parse_refresh(
        kept,
        "next-commit",
        frozenset({"new.py"}),
        "MAP\nnew.py:8 | refreshed code\nEND MAP",
        fake_cfg,
    )
    assert merged is not None
    assert merged.queue == kept.queue
    assert merged.sid == kept.sid
    assert merged.commit == "next-commit"


# Run overhead design (docs/superpowers/specs/relay-run-overhead-design.md, Modules
# `relay/research.py`; Order 4): `block()` is the map's header and body, with no instruction
# lines: f"{_header(m.sid, m.commit)}\n{m.body}\n" and nothing else.


def test_block_is_the_header_line_and_the_body_and_nothing_else(fake_cfg: Config) -> None:
    # Breaks when block puts any instruction line before the header, or anything after the body.
    m = _fixture_map(fake_cfg)
    assert block(m) == f"map {SID} at {COMMIT}\n{m.body}\n"


def test_block_is_only_header_and_body_for_another_section_and_commit(
    fake_cfg: Config,
) -> None:
    # Breaks when block adds text for some maps, or fixes its header rather than taking the map's.
    m = _fixture_map(fake_cfg, sid="s7", commit="2" * 40)
    assert block(m) == f"map s7 at {'2' * 40}\n{m.body}\n"
