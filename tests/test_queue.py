"""Red tests for Relay's queue parser (design: Modules, `relay/queue.py`; Order 5)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from relay.errors import QueueFormatError
from relay.queue import Section, blocked_by, parse_queue, queue_design

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


# The ladder (design: relay-ladder-design.md, Modules `relay/queue.py`; Order 3, 4).

LADDER = "ladder-queue.md"
LADDER_HEAD = (
    "design docs/superpowers/specs/ladder-design.md"
    " | order docs/superpowers/specs/ladder-design.md | main 1234567\n"
)
SIZE = "size: lead: tokens: 900000.0 seconds: 600.0 overruns: 0 refusals: 0"


def _ladder_variant(queue_file: Callable[[str], Path], old: str, new: str) -> Path:
    """The ladder queue with its one `old` text replaced by `new`, written beside it."""
    path = queue_file(LADDER)
    text = path.read_text()
    assert text.count(old) == 1
    variant = path.with_name("ladder-queue-variant.md")
    variant.write_text(text.replace(old, new))
    return variant


def _ladder_sections(path: Path) -> dict[str, Section]:
    return {s.id: s for s in parse_queue(path)}


# Behavior 1: the ladder queue holds a head `design` line, `steps:` and `cap:` fields, and
# sections that depend on each other.


def test_the_ladder_queue_holds_a_design_head_steps_caps_and_dependent_sections(
    queue_file: Callable[[str], Path],
) -> None:
    path = queue_file(LADDER)
    assert queue_design(path) == "docs/superpowers/specs/ladder-design.md"
    sections = _ladder_sections(path)
    assert list(sections) == ["s1", "s2", "s3"]
    assert sections["s1"].steps == ("1", "2")
    assert sections["s2"].steps == ("3",)
    assert sections["s1"].dollar_cap == 5.0
    assert sections["s2"].dollar_cap == 2.5
    assert sections["s3"].dollar_cap is None
    assert sections["s1"].depends_on == ()
    assert sections["s2"].depends_on == ("s1",)
    assert sections["s3"].depends_on == ("s2",)


# Behavior 2: `steps: 1, 2`; the field stays in the title as written.


def test_steps_hold_each_step_of_the_header_steps_field_in_order(
    queue_file: Callable[[str], Path],
) -> None:
    sections = _ladder_sections(queue_file(LADDER))
    assert sections["s1"].steps == ("1", "2")
    assert sections["s3"].steps == ("4",)


def test_the_steps_field_stays_in_the_title_as_written(
    queue_file: Callable[[str], Path],
) -> None:
    sections = _ladder_sections(queue_file(LADDER))
    assert sections["s1"].steps == ("1", "2")
    assert "steps: 1, 2" in sections["s1"].title
    assert sections["s3"].title == f"lead | steps: 4 | {SIZE}"


def test_steps_are_empty_for_a_header_with_no_steps_field(
    queue_file: Callable[[str], Path],
) -> None:
    path = _ladder_variant(
        queue_file, "section s3 | lead | steps: 4 | depends:", "section s3 | lead | depends:"
    )
    sections = _ladder_sections(path)
    assert sections["s3"].steps == ()
    assert sections["s1"].steps == ("1", "2")


# Behavior 3: `cap: $5` or `cap: 5`, removed from the title; positive.


def test_dollar_cap_reads_a_cap_written_with_a_dollar_sign(
    queue_file: Callable[[str], Path],
) -> None:
    assert _ladder_sections(queue_file(LADDER))["s1"].dollar_cap == 5.0


def test_dollar_cap_reads_a_cap_written_without_a_dollar_sign(
    queue_file: Callable[[str], Path],
) -> None:
    path = _ladder_variant(queue_file, "cap: $5", "cap: 5")
    sections = _ladder_sections(path)
    assert sections["s1"].dollar_cap == 5.0
    assert sections["s2"].dollar_cap == 2.5


def test_dollar_cap_is_none_without_a_cap_field(queue_file: Callable[[str], Path]) -> None:
    sections = _ladder_sections(queue_file(LADDER))
    assert sections["s3"].dollar_cap is None
    assert sections["s1"].dollar_cap is not None


def test_the_cap_field_is_removed_from_the_title(queue_file: Callable[[str], Path]) -> None:
    sections = _ladder_sections(queue_file(LADDER))
    plain = _ladder_sections(_ladder_variant(queue_file, " | cap: $5", ""))
    assert sections["s1"].dollar_cap == 5.0
    assert plain["s1"].dollar_cap is None
    assert "cap:" not in sections["s1"].title
    assert sections["s1"].title == plain["s1"].title
    assert sections["s1"].title == f"lead | steps: 1, 2 | {SIZE}"
    assert sections["s2"].title == f"lead | steps: 3 | {SIZE}"


@pytest.mark.parametrize("value", ["0", "$0", "0.0"])
def test_a_cap_that_is_not_positive_raises_queue_format_error(
    value: str, queue_file: Callable[[str], Path]
) -> None:
    path = _ladder_variant(queue_file, "cap: $5", f"cap: {value}")
    with pytest.raises(QueueFormatError):
        parse_queue(path)


# Behaviors 4 and 5: the path after `design ` on the queue's first non-blank line, when that
# line starts `design ` and comes before the first section, up to the first ` | ` or the end
# of the line; None otherwise.


def test_queue_design_is_the_head_path_up_to_the_first_separator(
    queue_file: Callable[[str], Path],
) -> None:
    assert queue_design(queue_file(LADDER)) == "docs/superpowers/specs/ladder-design.md"


def test_queue_design_reads_an_absolute_head_path(queue_file: Callable[[str], Path]) -> None:
    path = queue_file("check-queue.md")
    assert queue_design(path) == (
        "/tmp/relay-check-fixture/docs/superpowers/specs/check-fixture-design.md"
    )


def test_queue_design_skips_blank_lines_before_the_head_line(
    queue_file: Callable[[str], Path],
) -> None:
    path = _ladder_variant(queue_file, LADDER_HEAD, "\n  \n" + LADDER_HEAD)
    assert queue_design(path) == "docs/superpowers/specs/ladder-design.md"


def test_queue_design_runs_to_the_end_of_a_head_line_with_no_separator(
    queue_file: Callable[[str], Path],
) -> None:
    path = _ladder_variant(
        queue_file, LADDER_HEAD, "design docs/superpowers/specs/other-design.md\n"
    )
    assert queue_design(path) == "docs/superpowers/specs/other-design.md"


def test_queue_design_is_none_without_a_head_line(queue_file: Callable[[str], Path]) -> None:
    path = _ladder_variant(queue_file, LADDER_HEAD, "")
    assert queue_design(path) is None


def test_queue_design_is_none_when_the_design_line_comes_after_the_first_section(
    queue_file: Callable[[str], Path],
) -> None:
    path = _ladder_variant(queue_file, LADDER_HEAD, "")
    path.write_text(path.read_text() + LADDER_HEAD)
    assert queue_design(path) is None


def test_queue_design_is_none_when_the_first_non_blank_line_is_not_the_design_line(
    queue_file: Callable[[str], Path],
) -> None:
    path = _ladder_variant(queue_file, LADDER_HEAD, "# Queue\n" + LADDER_HEAD)
    assert queue_design(path) is None


def test_queue_design_is_none_when_the_first_line_does_not_start_with_design_and_a_space(
    queue_file: Callable[[str], Path],
) -> None:
    path = _ladder_variant(queue_file, LADDER_HEAD, "designs" + LADDER_HEAD[len("design") :])
    assert queue_design(path) is None


# Behavior 6: a bad `cap:` value, one that is not a positive number, raises QueueFormatError.


@pytest.mark.parametrize("value", ["-3", "$-3", "five", "$", "5 dollars"])
def test_a_cap_that_is_not_a_positive_number_raises_queue_format_error(
    value: str, queue_file: Callable[[str], Path]
) -> None:
    path = _ladder_variant(queue_file, "cap: $5", f"cap: {value}")
    with pytest.raises(QueueFormatError):
        parse_queue(path)
