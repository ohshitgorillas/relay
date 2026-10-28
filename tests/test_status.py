"""Red tests for Relay's lead status-line parser (design: Modules `relay/status.py`; Order 11).

The status contract the lead is given (design: Modules `relay/prompts.py`): the last line is
exactly one of "DONE", "RECUT: <reason>", "NEEDS-OWNER: <question>", "RETIRED".
"""

from __future__ import annotations

from relay.status import KINDS, TEXT_NAMES, LeadStatus, parse_status


# Behavior 1: `relay/status.py`: parses the lead's final status line, which is the last
# non-empty line of the result text.


def test_done_on_the_last_line_is_parsed() -> None:
    # Breaks when: parse_status does not recognise a final "DONE" line.
    status = parse_status("Step committed.\nDONE")
    assert isinstance(status, LeadStatus)
    assert status.kind == "DONE"


def test_retired_on_the_last_line_is_parsed() -> None:
    # Breaks when: parse_status does not recognise a final "RETIRED" line.
    status = parse_status("Safe point reached after the commit.\nRETIRED")
    assert isinstance(status, LeadStatus)
    assert status.kind == "RETIRED"


def test_recut_carries_its_reason_as_text() -> None:
    # Breaks when: the RECUT reason is dropped or not taken from after "RECUT: ".
    status = parse_status("Section is too big.\nRECUT: three modules, not one step")
    assert status == LeadStatus(kind="RECUT", text="three modules, not one step")


def test_needs_owner_carries_its_question_as_text() -> None:
    # Breaks when: the NEEDS-OWNER question is dropped or not taken from after "NEEDS-OWNER: ".
    status = parse_status("Blocked on a product choice.\nNEEDS-OWNER: Ship the CLI under the name relay?")
    assert status == LeadStatus(kind="NEEDS-OWNER", text="Ship the CLI under the name relay?")


def test_text_keeps_every_word_after_the_kind_including_colons() -> None:
    # Breaks when: the text is cut at a later ": " instead of taking all words after "KIND: ".
    status = parse_status("NEEDS-OWNER: Port: 8080 or 9090?")
    assert status == LeadStatus(kind="NEEDS-OWNER", text="Port: 8080 or 9090?")


def test_trailing_empty_lines_are_skipped() -> None:
    # Breaks when: parse_status reads the literal last line instead of the last non-empty one.
    status = parse_status("Step committed.\nDONE\n\n\n")
    assert isinstance(status, LeadStatus)
    assert status.kind == "DONE"


def test_a_status_word_before_the_last_non_empty_line_is_not_the_status() -> None:
    # Breaks when: parse_status searches every line for a status instead of reading only the last.
    assert parse_status("DONE\nThen I kept going and changed my mind.") is None


def test_only_the_last_status_line_counts_when_several_appear() -> None:
    # Breaks when: parse_status takes the first status line rather than the last non-empty line.
    status = parse_status("RECUT: earlier thought\nDONE")
    assert isinstance(status, LeadStatus)
    assert status.kind == "DONE"


# Behavior 2: None = no valid status line, which counts as a failure.


def test_no_result_text_gives_none() -> None:
    # Breaks when: parse_status invents a status for a run with no result text.
    assert parse_status(None) is None


def test_empty_result_text_gives_none() -> None:
    # Breaks when: an empty result text is taken as a status.
    assert parse_status("") is None


def test_result_text_of_only_empty_lines_gives_none() -> None:
    # Breaks when: parse_status falls back to some status when no non-empty line exists.
    assert parse_status("\n\n\n") is None


def test_an_unknown_status_word_gives_none() -> None:
    # Breaks when: parse_status accepts a word outside DONE, RECUT, NEEDS-OWNER, RETIRED.
    assert parse_status("Work finished.\nFAILED: tests are red") is None


def test_plain_prose_last_line_gives_none() -> None:
    # Breaks when: parse_status treats any last line as a status.
    assert parse_status("I committed the step and everything is green.") is None


def test_recut_without_a_reason_gives_none() -> None:
    # Breaks when: a RECUT with no reason is accepted, though the reason is required.
    assert parse_status("Too big.\nRECUT") is None


def test_recut_with_an_empty_reason_gives_none() -> None:
    # Breaks when: "RECUT: " with nothing after it is accepted as a reason.
    assert parse_status("Too big.\nRECUT: ") is None


def test_needs_owner_without_a_question_gives_none() -> None:
    # Breaks when: a NEEDS-OWNER with no question is accepted, though the question is required.
    assert parse_status("Blocked.\nNEEDS-OWNER") is None


def test_needs_owner_with_an_empty_question_gives_none() -> None:
    # Breaks when: "NEEDS-OWNER: " with nothing after it is accepted as a question.
    assert parse_status("Blocked.\nNEEDS-OWNER: ") is None


def test_a_lowercase_status_word_gives_none() -> None:
    # Breaks when: parse_status matches the status words case-insensitively; the line must be exactly one of them.
    assert parse_status("Step committed.\ndone") is None


def test_done_followed_by_extra_words_gives_none() -> None:
    # Breaks when: parse_status matches a prefix, so "DONE ..." with more words still counts as DONE.
    assert parse_status("Step committed.\nDONE except the tests still fail") is None


def test_retired_followed_by_extra_words_gives_none() -> None:
    # Breaks when: parse_status matches a prefix, so "RETIRED ..." with more words still counts as RETIRED.
    assert parse_status("Context is heavy.\nRETIRED early") is None


# Relay's ladder (design: docs/superpowers/specs/relay-ladder-design.md, Modules `relay/status.py`; Order 4).
# Behavior 1: two status words. `Kind` gains DESIGN and WAITING; TEXT_NAMES names DESIGN's text
# "problem" and WAITING's "section id".


def test_design_and_waiting_are_status_words() -> None:
    # Breaks when: either word is missing from the one list of status words.
    assert "DESIGN" in KINDS
    assert "WAITING" in KINDS


def test_design_text_is_named_problem_and_waiting_text_section_id() -> None:
    # Breaks when: TEXT_NAMES lacks either word or names its text otherwise.
    assert TEXT_NAMES.get("DESIGN") == "problem"
    assert TEXT_NAMES.get("WAITING") == "section id"


def test_the_earlier_text_names_are_kept() -> None:
    # Breaks when: adding the two words drops or renames RECUT's or NEEDS-OWNER's text.
    assert TEXT_NAMES.get("RECUT") == "reason"
    assert TEXT_NAMES.get("NEEDS-OWNER") == "question"


def test_design_carries_its_problem_as_text() -> None:
    # Breaks when: parse_status does not recognise a final "DESIGN: <problem>" line.
    status = parse_status("The design has no step for it.\nDESIGN: no module owns the cache; Order 3")
    assert status == LeadStatus(kind="DESIGN", text="no module owns the cache; Order 3")


def test_waiting_carries_its_section_id_as_text() -> None:
    # Breaks when: parse_status does not recognise a final "WAITING: <id>" line.
    status = parse_status("I need s2's API first.\nWAITING: s2.d1")
    assert status == LeadStatus(kind="WAITING", text="s2.d1")


def test_design_without_a_problem_gives_none() -> None:
    # Breaks when: a DESIGN with no problem is accepted, though DESIGN names a text.
    assert parse_status("Stuck.\nDESIGN") is None
    assert parse_status("Stuck.\nDESIGN: ") is None


def test_waiting_without_a_section_id_gives_none() -> None:
    # Breaks when: a WAITING with no section id is accepted, though WAITING names a text.
    assert parse_status("Stuck.\nWAITING") is None
    assert parse_status("Stuck.\nWAITING: ") is None
