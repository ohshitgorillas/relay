"""Red tests for Relay's ladder (design: docs/superpowers/specs/relay-ladder-design.md, Modules, `relay/ladder.py`; Order 4)."""

from __future__ import annotations

import builtins
import dataclasses
import io
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

import pytest

from relay.config import Config
from relay.ladder import (
    GUESS,
    DesignReport,
    cap_text,
    climb,
    decision_numbers,
    decisions_text,
    design_of,
    failed_text,
    lead_branch,
    parse_report,
    said,
    section_cap,
    split_reason,
)
from relay.queue import Section
from relay.state import SectionState

DESIGN = Path("/repo/docs/superpowers/specs/thing-design.md")
SID = "s3"


def _section(*, from_recut: bool, design_changed: bool) -> SectionState:
    return SectionState(
        status="open",
        failures=0,
        question=None,
        answer=None,
        last_session=None,
        from_recut=from_recut,
        design_changed=design_changed,
    )


# climb: rung 1


@pytest.mark.parametrize("design", [DESIGN, None], ids=["design", "no-design"])
def test_climb_recut_on_a_fresh_section_takes_rung_1(design: Path | None) -> None:
    # breaks when: a plain RECUT goes to the architect or to the owner instead of the divvyer's recut.
    climb_ = climb("RECUT", _section(from_recut=False, design_changed=False), design, SID)
    assert climb_.rung == 1


# climb: rung 2


@pytest.mark.parametrize(
    ("kind", "from_recut"),
    [("RECUT", True), ("DESIGN", False), ("DESIGN", True)],
    ids=["recut-from-recut", "design-fresh", "design-from-recut"],
)
def test_climb_takes_rung_2_with_a_design_and_no_design_change(kind: str, from_recut: bool) -> None:
    # breaks when: a recut section's second RECUT, or a DESIGN, parks for the owner or recuts again.
    climb_ = climb(kind, _section(from_recut=from_recut, design_changed=False), DESIGN, SID)  # type: ignore[arg-type]
    assert climb_.rung == 2


# climb: after a design change, a RECUT is recut again and a DESIGN gets another design change


@pytest.mark.parametrize("from_recut", [False, True], ids=["fresh", "from-recut"])
def test_climb_recuts_after_a_design_change(from_recut: bool) -> None:
    # breaks when: a section that had its design change is parked for the owner instead of recut.
    climb_ = climb("RECUT", _section(from_recut=from_recut, design_changed=True), DESIGN, SID)
    assert climb_.rung == 1


@pytest.mark.parametrize("from_recut", [False, True], ids=["fresh", "from-recut"])
def test_climb_changes_the_design_again_after_a_design_change(from_recut: bool) -> None:
    # breaks when: a second DESIGN on a section is parked for the owner instead of sent to the architect.
    climb_ = climb("DESIGN", _section(from_recut=from_recut, design_changed=True), DESIGN, SID)
    assert climb_.rung == 2


# climb: rung 3 when rung 2 has no design to amend


@pytest.mark.parametrize(
    ("kind", "from_recut"),
    [("RECUT", True), ("DESIGN", False), ("DESIGN", True)],
    ids=["recut-from-recut", "design-fresh", "design-from-recut"],
)
def test_climb_without_a_design_file_at_rung_2_takes_rung_3_and_names_specs(
    kind: str, from_recut: bool
) -> None:
    # docs/superpowers/specs/relay-codex-architect-design.md:64-66.
    # breaks when: rung 2 runs the architect with no design path, or rung 3 still says only
    # "the queue names none" instead of naming docs/superpowers/specs/.
    climb_ = climb(kind, _section(from_recut=from_recut, design_changed=False), None, SID)  # type: ignore[arg-type]
    assert climb_.rung == 3
    assert climb_.why == (
        "no design to amend: the queue names no design file under docs/superpowers/specs/"
    )


# split_reason


def test_split_reason_splits_problem_from_guess() -> None:
    # breaks when: the guess stays in the problem the architect is given.
    assert split_reason("the check fails on s4.2 | guess: retry the fetch") == (
        "the check fails on s4.2",
        "retry the fetch",
    )


def test_split_reason_strips_both_parts() -> None:
    # breaks when: the parts are returned unstripped.
    assert split_reason(f"  \n the problem  {GUESS}  the fix \n") == (
        "the problem",
        "the fix",
    )


def test_split_reason_cuts_at_the_first_guess() -> None:
    # breaks when: the text is cut at the last GUESS instead of the first.
    assert split_reason(f"problem{GUESS}fix one{GUESS}fix two") == (
        "problem",
        f"fix one{GUESS}fix two",
    )


def test_split_reason_cuts_at_the_guess_constant() -> None:
    # breaks when: the split matches a different separator than GUESS.
    assert GUESS == " | guess: "
    assert split_reason("problem | guess: fix") == ("problem", "fix")


# parse_report: rejected


def test_parse_report_rejected_first_line_gives_rejected() -> None:
    # breaks when: a REJECTED: STEERING report is not read as rejected.
    report = parse_report('REJECTED: STEERING\n"lead new: use a retry"\n')
    assert report is not None
    assert report.rejected is True


def test_parse_report_rejected_after_blank_lines_gives_rejected() -> None:
    # breaks when: leading blank lines hide the rejection.
    report = parse_report('\n\n  \nREJECTED: STEERING\n"approve: go"\n')
    assert report is not None
    assert report.rejected is True


# parse_report: the last BRIEF ... END DESIGN block; None when neither


def _block(unfiled: str) -> str:
    return (
        "BRIEF rulings docs/superpowers/specs/thing-design.md\n"
        "STATUS Status: approved.\n"
        "UNFILED\n"
        f"  {unfiled}\n"
        "END DESIGN\n"
    )


def test_parse_report_reads_a_brief_block() -> None:
    # breaks when: a BRIEF ... END DESIGN report is not found.
    report = parse_report("Some prose first.\n\n" + _block("the old relay/loop.py note"))
    assert report is not None
    assert report.rejected is False
    assert report.approved is True
    assert list(report.unfiled) == ["the old relay/loop.py note"]


def test_parse_report_a_status_not_approved_is_not_approved() -> None:
    # breaks when: approved is set whatever the STATUS line says.
    report = parse_report(
        _block("a gap").replace("STATUS Status: approved.", "STATUS Status: draft.")
    )
    assert report is not None
    assert report.rejected is False
    assert report.approved is False


def test_parse_report_reads_the_last_brief_block() -> None:
    # breaks when: the first block is read instead of the last.
    report = parse_report(
        _block("from the first block") + "\nmore prose\n\n" + _block("from the last block")
    )
    assert report is not None
    assert list(report.unfiled) == ["from the last block"]


def test_parse_report_none_gives_none() -> None:
    # breaks when: a missing result text is read as a report.
    assert parse_report(None) is None


def test_parse_report_text_without_rejection_or_block_gives_none() -> None:
    # breaks when: prose with no report is read as a report.
    assert parse_report("I amended the design and all is well.\nSTATUS Status: approved.\n") is None


def test_parse_report_brief_without_end_design_gives_none() -> None:
    # breaks when: a block with no END DESIGN line is read as a report.
    assert (
        parse_report("BRIEF rulings docs/x-design.md\nSTATUS Status: approved.\nUNFILED\n  a gap\n")
        is None
    )


# parse_report: UNFILED


def test_parse_report_unfiled_holds_each_indented_line_under_unfiled() -> None:
    # breaks when: UNFILED lines are dropped, merged or reworded, or lines of another heading leak in.
    text = (
        "BRIEF rulings docs/superpowers/specs/thing-design.md\n"
        "STATUS Status: approved.\n"
        "UNFILED\n"
        "  relay/cli.py prints the wrong word | a later step\n"
        "  the ledger has no rung for asks\n"
        "DECISIONS\n"
        "  1 | which cap | recommend: per section | alternative: per queue\n"
        "END DESIGN\n"
    )
    report = parse_report(text)
    assert report is not None
    # Each line is the indented line under its heading, as written, compared exactly: the
    # design's form `<n> | question | ...` starts at the text, so the indent is not kept.
    assert list(report.unfiled) == [
        "relay/cli.py prints the wrong word | a later step",
        "the ledger has no rung for asks",
    ]
    assert list(report.decisions) == [
        "1 | which cap | recommend: per section | alternative: per queue",
    ]


def test_parse_report_without_unfiled_has_none() -> None:
    # breaks when: unfiled is filled from another heading.
    text = (
        "BRIEF rulings docs/superpowers/specs/thing-design.md\n"
        "STATUS Status: approved.\n"
        "DECISIONS\n"
        "  1 | which cap | recommend: per section | alternative: per queue\n"
        "  2 | which word | recommend: WAITING | alternative: HELD\n"
        "END DESIGN\n"
    )
    report = parse_report(text)
    assert report is not None
    assert report.unfiled == ()
    # Each decision is the indented line under DECISIONS, as written, compared exactly.
    assert list(report.decisions) == [
        "1 | which cap | recommend: per section | alternative: per queue",
        "2 | which word | recommend: WAITING | alternative: HELD",
    ]


# decision_numbers


def _report(*decisions: str) -> DesignReport:
    return DesignReport(rejected=False, approved=False, decisions=decisions, unfiled=())


def test_decision_numbers_reads_each_leading_number_in_order() -> None:
    # breaks when: numbers are sorted, dropped, or read from the wrong field.
    report = _report(
        "3 | which cap | recommend: per section | alternative: per queue",
        "1 | which word | recommend: WAITING | alternative: HELD",
        "12 | which home | recommend: ladder | alternative: loop",
    )
    assert decision_numbers(report) == (3, 1, 12)


def test_decision_numbers_of_no_decisions_is_empty() -> None:
    # breaks when: a report with no decisions yields a number.
    assert decision_numbers(_report()) == ()


# Pure: no I/O, no state writes, no git


def _ladder_section(sid: str = "s2", dollar_cap: float | None = None) -> Section:
    return Section(
        id=sid,
        title="Ladder",
        body="## Ladder\n",
        depends_on=(),
        open=True,
        dollar_cap=dollar_cap,
    )


DECISION_1 = "1 | which cap applies | recommend: per section | alternative: per queue"
DECISION_2 = "2 | which status word | recommend: WAITING | alternative: HELD"
UNFILED_1 = "relay/cli.py prints the wrong word | recommend: a later step | alternative: this step"

REPORT_TEXT = (
    "BRIEF rulings docs/superpowers/specs/thing-design.md\n"
    "STATUS Status: approved.\n"
    "DECISIONS\n"
    f"  {DECISION_1}\n"
    "UNFILED\n"
    f"  {UNFILED_1}\n"
    "END DESIGN\n"
)

# Each call into relay/ladder.py, given the fake config.
_LADDER_CALLS: list[tuple[str, Callable[[Config], Any]]] = [
    (
        "climb",
        lambda cfg: climb("DESIGN", _section(from_recut=False, design_changed=False), DESIGN, SID),
    ),
    ("split_reason", lambda cfg: split_reason(f"the problem{GUESS}the fix")),
    ("parse_report", lambda cfg: parse_report(REPORT_TEXT)),
    ("decision_numbers", lambda cfg: decision_numbers(_report(DECISION_1, DECISION_2))),
    (
        "design_of",
        lambda cfg: design_of("docs/superpowers/specs/thing-design.md", Path("/no-such-repo")),
    ),
    ("section_cap", lambda cfg: section_cap(cfg, _ladder_section(dollar_cap=5.0))),
    ("cap_text", lambda cfg: cap_text("s2", 3.0, 2.5)),
    (
        "decisions_text",
        lambda cfg: decisions_text(
            "s2",
            DESIGN,
            DesignReport(
                rejected=False, approved=True, decisions=(DECISION_1,), unfiled=(UNFILED_1,)
            ),
        ),
    ),
    ("failed_text", lambda cfg: failed_text("s2", DESIGN, "the architect exited 1")),
]

# Every way to open or change a file, or to start a process such as git.
_IO_TARGETS: list[tuple[Any, str]] = [
    (builtins, "open"),
    (io, "open"),
    (os, "open"),
    (os, "replace"),
    (os, "rename"),
    (os, "mkdir"),
    (os, "makedirs"),
    (os, "unlink"),
    (os, "remove"),
    (os, "system"),
    (subprocess, "Popen"),
]


def _spy(calls: list[str], name: str, real: Any) -> Any:
    def spied(*args: Any, **kwargs: Any) -> Any:
        calls.append(name)
        return real(*args, **kwargs)

    return spied


@pytest.mark.parametrize("call", [c for _, c in _LADDER_CALLS], ids=[n for n, _ in _LADDER_CALLS])
def test_ladder_functions_open_no_file_and_start_no_process(
    call: Callable[[Config], Any], fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    # breaks when: a ladder function reads the design or queue file, writes state, or runs git.
    calls: list[str] = []
    with monkeypatch.context() as m:
        for target, name in _IO_TARGETS:
            m.setattr(target, name, _spy(calls, f"{target.__name__}.{name}", getattr(target, name)))
        call(fake_cfg)
    assert calls == []


# design_of


def test_design_of_resolves_a_relative_design_against_top() -> None:
    # breaks when: a relative design path is returned as is, or joined to the cwd instead of `top`.
    assert design_of("docs/superpowers/specs/ladder-design.md", Path("/no-such-repo")) == Path(
        "/no-such-repo/docs/superpowers/specs/ladder-design.md"
    )


def test_design_of_returns_an_absolute_design_directly_under_top_specs() -> None:
    # breaks when: an absolute design line naming a `.md` file directly under top/SPECS is
    # rejected as outside the specs directory, or is rewritten rather than returned.
    design = "/no-such-repo/docs/superpowers/specs/ladder-design.md"
    assert design_of(design, Path("/no-such-repo")) == Path(design)


def test_design_of_none_is_none() -> None:
    # breaks when: a queue with no design line yields a path, such as `top` itself.
    assert design_of(None, Path("/no-such-repo")) is None


# Codex architect design (docs/superpowers/specs/relay-codex-architect-design.md, Modules
# `relay/ladder.py`; Order 3): `design_of` is "As now, and None when the resolved path is not a
# `.md` file directly under top/SPECS", SPECS being `docs/superpowers/specs`.


@pytest.mark.parametrize(
    "design_line",
    [
        "docs/thing-design.md",
        "docs/superpowers/thing-design.md",
        "docs/superpowers/specs/older/thing-design.md",
        "docs/superpowers/specs/thing-design.txt",
        "docs/superpowers/specs/../thing-design.md",
        "/elsewhere/docs/superpowers/specs/thing-design.md",
        "/no-such-repo/docs/thing-design.md",
    ],
    ids=[
        "under-docs",
        "under-superpowers",
        "nested-under-specs",
        "not-markdown",
        "climbs-out-of-specs",
        "absolute-in-another-repo",
        "absolute-in-top-outside-specs",
    ],
)
def test_design_of_a_path_not_directly_under_the_specs_directory_is_none(
    design_line: str,
) -> None:
    # breaks when: design_of returns a path for a queue design line whose file is outside
    # top/docs/superpowers/specs/, nested below it, or not a `.md` file.
    assert design_of(design_line, Path("/no-such-repo")) is None


# section_cap


@pytest.mark.parametrize(
    ("section_dollar_cap", "dollar_cap", "expected"),
    [
        (2.5, 5.0, 5.0),
        (9.0, 1.0, 1.0),
        (None, 4.0, 4.0),
        (2.5, None, 2.5),
        (None, None, None),
    ],
    ids=["section-above-config", "section-below-config", "section-only", "config-only", "neither"],
)
def test_section_cap_takes_the_section_cap_else_the_config_cap(
    fake_cfg: Config,
    section_dollar_cap: float | None,
    dollar_cap: float | None,
    expected: float | None,
) -> None:
    # breaks when: the config cap wins over a section's `cap:`, the smaller cap is taken, or an unset section cap ignores the config.
    cfg = dataclasses.replace(fake_cfg, section_dollar_cap=section_dollar_cap)
    assert section_cap(cfg, _ladder_section(dollar_cap=dollar_cap)) == expected


# Owner text: the cap, a failed design change, a decision


def test_cap_text_names_spend_and_cap_to_the_cent() -> None:
    # breaks when: the cap text is reworded, or spend and cap are not shown with two decimals.
    assert cap_text("s2", 3.457, 2.5) == (
        "section s2 spent $3.46 of its $2.50 cap; raise `cap:` in the queue or "
        "--section-dollar-cap to go on"
    )


def test_failed_text_names_section_design_and_what_failed() -> None:
    # breaks when: the failed design change text is reworded or drops what failed.
    assert failed_text("s2", DESIGN, "the architect exited 1") == (
        f"the design change for s2 in {DESIGN} did not land: the architect exited 1"
    )


def test_decisions_text_opens_with_section_and_design() -> None:
    # breaks when: the decision text's opening is reworded or names the wrong section or design.
    report = DesignReport(rejected=False, approved=True, decisions=(DECISION_1,), unfiled=())
    assert decisions_text("s2", DESIGN, report).startswith(
        f"the design change for s2 in {DESIGN} needs a product choice:"
    )


# Each decision and unfiled line verbatim, with its recommendation and alternative


def test_decisions_text_carries_each_decision_verbatim_in_order() -> None:
    # breaks when: a decision is dropped, reworded, cut before its alternative, or reordered.
    report = DesignReport(
        rejected=False, approved=True, decisions=(DECISION_1, DECISION_2), unfiled=()
    )
    text = decisions_text("s2", DESIGN, report)
    assert DECISION_1 in text
    assert DECISION_2 in text
    assert text.index(DECISION_1) < text.index(DECISION_2)


def test_decisions_text_carries_each_unfiled_line_verbatim() -> None:
    # breaks when: unfiled lines are left out of the owner's text, or cut before their recommendation and alternative.
    report = DesignReport(
        rejected=False, approved=True, decisions=(DECISION_1,), unfiled=(UNFILED_1,)
    )
    text = decisions_text("s2", DESIGN, report)
    assert DECISION_1 in text
    assert UNFILED_1 in text


def test_decisions_text_with_only_unfiled_lines_carries_them() -> None:
    # breaks when: the lines are read from decisions alone, so an unfiled-only report shows nothing.
    report = DesignReport(rejected=False, approved=True, decisions=(), unfiled=(UNFILED_1,))
    assert UNFILED_1 in decisions_text("s2", DESIGN, report)


# The architect's unparsed final message for the owner, and the lead's code location.


def test_said_quotes_a_short_message_whole_and_a_long_one_by_its_end() -> None:
    # Breaks when: an architect message without a report is not quoted to the owner (Gauntlet s2,
    # run 29: a bare END DESIGN parked as "the architect filed no report"), or a long one is cut
    # from its end, where the reason is, or not cut at all.
    assert said("  Blocked: no findings.\n\nEND DESIGN\n") == "Blocked: no findings.\n\nEND DESIGN"
    assert said(None) == "(nothing)"
    long = "x" * 5000 + "the reason"
    quoted = said(long)
    assert quoted.endswith("the reason")
    assert quoted.startswith("…")
    assert len(quoted) <= 1501


def test_lead_branch_reads_the_last_branch_line_of_the_lead_report() -> None:
    # Breaks when: the lead's branch and worktree are not taken from its report's BRANCH line,
    # an earlier BRANCH line wins, or a report with none gives one.
    report = "BRANCH lead/old /tmp/old\nSLICE q s2\nBRANCH lead/m2-images /Users/a/gauntlet-wt/m2 images\nEND LEAD"
    assert lead_branch(report) == ("lead/m2-images", Path("/Users/a/gauntlet-wt/m2 images"))
    assert lead_branch("DONE") is None
    assert lead_branch(None) is None
