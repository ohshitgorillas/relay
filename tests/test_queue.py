"""Red tests for Relay's queue parser (design: Modules, `relay/queue.py`; Order 5)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from relay.errors import QueueFormatError
from relay.queue import Section, blocked_by, parse_queue

TESTS = Path(__file__).parent
FIXTURES = TESTS / "fixtures"

# Section ids as the divvyer writes them, in queue order, in each copied sample.
SAMPLE_IDS = {
    "workboard-queue.md": [
        "s1.1.1", "s1.1.2", "s1.2", "s2", "s3", "s4", "s5", "s6",
        "s7", "s8", "s9", "s10", "s11", "s12", "s13",
    ],
    "m2-rest-queue.md": ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9"],
}


def _section_text(name: str, sid: str) -> str:
    """The sample's lines from `section <sid> |` up to the next `section ` line or the end."""
    lines = (FIXTURES / name).read_text().splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith(f"section {sid} |"))
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("section ")),
        len(lines),
    )
    return "".join(lines[start:end])


def _section(sid: str, *depends_on: str) -> Section:
    return Section(id=sid, title=sid, body=f"section {sid}\n", depends_on=tuple(depends_on), open=True)


# Behavior 1: `relay/queue.py`: parses the divvyer's `.md` queue into sections.

@pytest.mark.parametrize("name", sorted(SAMPLE_IDS))
def test_parse_queue_returns_each_section_in_queue_order_with_its_divvyer_id(
    name: str, queue_file: Callable[[str], Path]
) -> None:
    sections = parse_queue(queue_file(name))
    assert all(isinstance(s, Section) for s in sections)
    assert [s.id for s in sections] == SAMPLE_IDS[name]


@pytest.mark.parametrize(
    ("name", "sid"),
    [
        ("workboard-queue.md", "s1.1.1"),
        ("workboard-queue.md", "s5"),
        ("workboard-queue.md", "s13"),
        ("m2-rest-queue.md", "s1"),
        ("m2-rest-queue.md", "s6"),
        ("m2-rest-queue.md", "s9"),
    ],
)
def test_parse_queue_keeps_each_sections_full_text_verbatim_as_its_body(
    name: str, sid: str, queue_file: Callable[[str], Path]
) -> None:
    sections = {s.id: s for s in parse_queue(queue_file(name))}
    assert sections[sid].body.strip("\n") == _section_text(name, sid).strip("\n")


def test_parse_queue_raises_queue_format_error_on_a_file_that_is_not_a_queue(
    tmp_path: Path,
) -> None:
    path = tmp_path / "not-a-queue.md"
    path.write_text("# Notes\n\nThis is prose, not a divvyer queue.\n")
    with pytest.raises(QueueFormatError):
        parse_queue(path)


# Behavior 3: ids that depend, transitively, on a parked id.

def test_blocked_by_is_empty_when_nothing_is_parked() -> None:
    sections = [_section("s1"), _section("s2", "s1"), _section("s3", "s2")]
    assert blocked_by(sections, set()) == set()


def test_blocked_by_holds_a_section_that_depends_directly_on_a_parked_id() -> None:
    sections = [_section("s1"), _section("s2", "s1"), _section("s3")]
    assert blocked_by(sections, {"s1"}) == {"s2"}


def test_blocked_by_follows_dependencies_transitively_and_leaves_out_the_rest() -> None:
    sections = [
        _section("s1"),
        _section("s2", "s1"),
        _section("s3", "s2"),
        _section("s4", "s3"),
        _section("s5"),
        _section("s6", "s5"),
    ]
    assert blocked_by(sections, {"s1"}) == {"s2", "s3", "s4"}


def test_blocked_by_follows_dependencies_transitively_when_dependents_come_first() -> None:
    sections = [
        _section("s6", "s5"),
        _section("s4", "s3"),
        _section("s3", "s2"),
        _section("s2", "s1"),
        _section("s5"),
        _section("s1"),
    ]
    assert blocked_by(sections, {"s1"}) == {"s2", "s3", "s4"}


def test_blocked_by_joins_the_dependents_of_every_parked_id() -> None:
    sections = [
        _section("s1"),
        _section("s2"),
        _section("s3", "s1"),
        _section("s4", "s2"),
        _section("s5", "s3", "s4"),
        _section("s6"),
    ]
    assert blocked_by(sections, {"s1", "s2"}) == {"s3", "s4", "s5"}


def test_blocked_by_does_not_count_a_parked_id_that_depends_on_nothing_parked() -> None:
    sections = [_section("s1"), _section("s2"), _section("s3", "s2")]
    assert blocked_by(sections, {"s1"}) == set()


# Check lines and the recut note (design: relay-check-design.md, Modules `relay/queue.py`;
# Order 3). Behavior: each `check:` or `done-check:` line's command, in body order.


def _check_sections(queue_file: Callable[[str], Path]) -> dict[str, Section]:
    return {s.id: s for s in parse_queue(queue_file("check-queue.md"))}


def test_checks_hold_each_check_and_done_check_command_in_body_order(
    queue_file: Callable[[str], Path],
) -> None:
    sections = _check_sections(queue_file)
    assert sections["s1"].checks == (
        "uv run python -m pytest tests/test_one.py",
        "make check && echo ok",
        "python3 -c 'print(1)'",
    )
    assert sections["s4a"].checks == ("uv run python -m pytest tests/test_four.py",)


def test_checks_are_empty_for_a_section_with_no_check_line(
    queue_file: Callable[[str], Path],
) -> None:
    sections = _check_sections(queue_file)
    assert list(sections) == ["s1", "s2", "s4a"]
    assert sections["s2"].checks == ()
    assert sections["s1"].checks != ()


# Behavior: leading whitespace allowed, fenced blocks skipped.


def test_checks_take_an_indented_line_and_one_at_the_line_start(
    queue_file: Callable[[str], Path],
) -> None:
    checks = _check_sections(queue_file)["s1"].checks
    assert "uv run python -m pytest tests/test_one.py" in checks
    assert "python3 -c 'print(1)'" in checks


def test_checks_skip_lines_inside_a_fenced_block(queue_file: Callable[[str], Path]) -> None:
    checks = _check_sections(queue_file)["s1"].checks
    assert "make check && echo ok" in checks
    assert "echo inside a fence" not in checks
    assert "echo inside a fence too" not in checks
    assert len(checks) == 3


# Behavior: the header field `from: <id>`, removed from the title.


def test_came_from_is_the_header_from_id_and_it_is_removed_from_the_title(
    queue_file: Callable[[str], Path],
) -> None:
    path = queue_file("check-queue.md")
    section = {s.id: s for s in parse_queue(path)}["s4a"]
    assert section.came_from == "s4"
    assert "from:" not in section.title
    # The same queue with s4a's whole `from: s4` field cut from its header: the title the
    # parser gives that header is s4a's title with the field removed and nothing else.
    header = "section s4a | lead | steps: 4 | from: s4 | size: "
    text = path.read_text()
    assert text.count(header) == 1
    without = path.with_name("check-queue-without-from.md")
    without.write_text(text.replace(header, "section s4a | lead | steps: 4 | size: "))
    plain = {s.id: s for s in parse_queue(without)}["s4a"]
    assert plain.came_from is None
    assert plain.title
    assert section.title == plain.title
    # docs/superpowers/specs/relay-loop-design.md: every header field but `depends:` and
    # `done` is kept in `title`, joined by ` | `; relay-check-design.md: `from:` is removed.
    assert section.title == (
        "lead | steps: 4 | size: lead: tokens: 900000.0 seconds: 600.0 overruns: 0 refusals: 0"
    )


def test_came_from_is_none_without_a_from_field(queue_file: Callable[[str], Path]) -> None:
    sections = _check_sections(queue_file)
    assert sections["s4a"].came_from == "s4"
    assert sections["s1"].came_from is None
    assert sections["s2"].came_from is None


# Behavior: A `from:` id must match `_ID`. It need not name a section still in the queue.


def test_a_from_id_need_not_name_a_section_in_the_queue(
    queue_file: Callable[[str], Path],
) -> None:
    sections = _check_sections(queue_file)
    assert "s4" not in sections
    assert sections["s4a"].came_from == "s4"


def test_a_from_value_that_is_not_an_id_raises_queue_format_error(
    queue_file: Callable[[str], Path],
) -> None:
    with pytest.raises(QueueFormatError):
        parse_queue(queue_file("check-queue-bad-from.md"))
