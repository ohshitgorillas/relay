"""Red tests for Relay's research map and answer (design: Modules `relay/research.py`; Order 3)."""

from __future__ import annotations

import dataclasses

from relay.config import Config
from relay.research import parse_answer, parse_map
from tests.conftest import FIXTURES

SID = "s1"
COMMIT = "0123456789abcdef0123456789abcdef01234567"

# The researcher's final message from `tests/fixtures/research-map.txt`.
MAP_TEXT = (FIXTURES / "research-map.txt").read_text()

# Its block's lines from `MAP` to `END MAP`, both included.
MAP_LINES = MAP_TEXT[MAP_TEXT.index("MAP\n") : MAP_TEXT.index("END MAP") + len("END MAP")].splitlines()

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
    text = _with_line_after(MAP_TEXT, "relay/git.py:12 | head runs git rev-parse HEAD", "Read this file first.")
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
        MAP_TEXT, "LINKS", "relay/state.py:209 -> relay/runner.py:133 | the runner touches the retire flag"
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
