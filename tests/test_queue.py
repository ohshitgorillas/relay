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
