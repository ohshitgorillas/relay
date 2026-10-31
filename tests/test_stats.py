"""Red tests for `relay/stats.py`: sizing figures per role and their text
(design: relay-stats-design.md, Modules `relay/stats.py`; Order 3)."""

from __future__ import annotations

import dataclasses
import random
from pathlib import Path

import pytest

from relay import stats
from relay.agents import Activity, Agent
from relay.config import Config
from relay.history import History, Run
from relay.ledger import Spend
from relay.stats import RoleStats, Sized
from relay.stream import StreamState

LIMIT = 100_000
CEILING = 200_000


@pytest.fixture
def cfg(fake_cfg: Config) -> Config:
    return dataclasses.replace(fake_cfg, context_limit=LIMIT, hard_ceiling=CEILING)


def _run(
    kind: str,
    result_text: str | None,
    peak: int,
    *,
    is_error: bool = False,
    section: str = "s1",
    session: str = "sess-1",
    agents: tuple[Agent, ...] = (),
) -> Run:
    stream = StreamState(
        session_id=session,
        context_tokens=peak,
        spend=Spend(tokens=0, dollars=0.0),
        result_text=result_text,
        is_error=is_error,
        activity=Activity(agents=agents),
        peak_context=peak,
    )
    return Run(
        kind=kind,
        section=section,
        session=session,
        log=Path(f"/runs/{session}.jsonl"),
        stream=stream,
    )


def _history(*runs: Run) -> History:
    return History(runs=tuple(runs), skipped_logs=0)


# Behavior 1: a top-level run's role is `Run.kind` and its peak `stream.peak_context`; it is an
# overrun when RETIRED ("retired"), when it has no result after reaching `cfg.hard_ceiling`
# ("killed"), or when its peak is at or above `cfg.context_limit` ("over context limit"). A lead
# run is finished only when it ended DONE; any other kind when it has a result and no error.


@pytest.mark.parametrize(
    ("kind", "result_text", "is_error", "peak", "overrun"),
    [
        ("lead", "Step committed.\nDONE", False, 40_000, None),
        ("lead", "Step committed.\nDONE", False, LIMIT - 1, None),
        ("lead", "Safe point reached.\nRETIRED", False, 30_000, "retired"),
        ("lead", None, False, CEILING, "killed"),
        ("lead", None, False, CEILING + 50_000, "killed"),
        ("lead", None, False, LIMIT, "over context limit"),
        ("lead", "Step committed.\nDONE", False, LIMIT, "over context limit"),
        ("recut", "Cut into three steps.", False, 20_000, None),
        ("research", "Map written.", False, LIMIT, "over context limit"),
        ("design", None, False, CEILING, "killed"),
    ],
    ids=[
        "lead-done",
        "lead-done-just-below-limit",
        "lead-retired",
        "lead-killed-at-ceiling",
        "lead-killed-past-ceiling",
        "lead-no-result-at-limit",
        "lead-done-at-limit",
        "recut-finished",
        "research-at-limit",
        "design-killed",
    ],
)
def test_a_top_level_run_is_sized_by_its_kind_session_and_peak(
    kind: str, result_text: str | None, is_error: bool, peak: int, overrun: str | None, cfg: Config
) -> None:
    # Breaks when: the role is not the ledger kind, the label not the session, the peak not
    # `peak_context`, a limit is compared with `>` instead of `>=`, "killed" is reported as
    # "over context limit", or a finished run is given a reason.
    run = _run(kind, result_text, peak, is_error=is_error, section="s2", session="sess-x")
    assert stats.sized(_history(run), cfg) == [
        Sized(role=kind, section="s2", label="sess-x", peak=peak, overrun=overrun)
    ]


@pytest.mark.parametrize(
    ("kind", "result_text", "is_error"),
    [
        ("lead", "Too big.\nRECUT: three modules, not one step", False),
        ("lead", "Blocked.\nNEEDS-OWNER: Which port?", False),
        ("lead", "Still working on the step.", False),
        ("lead", None, False),
        ("research", "API error: overloaded", True),
        ("ask", None, False),
    ],
    ids=[
        "lead-recut",
        "lead-needs-owner",
        "lead-no-status",
        "lead-no-result",
        "research-error",
        "ask-no-result",
    ],
)
def test_a_top_level_run_neither_finished_nor_overrun_is_not_sized(
    kind: str, result_text: str | None, is_error: bool, cfg: Config
) -> None:
    # Breaks when: a lead run that did not end DONE, or another kind with no result or with an
    # error, is counted as finished or given an overrun reason.
    run = _run(kind, result_text, 30_000, is_error=is_error)
    assert stats.sized(_history(run), cfg) == []


# Behavior 2: a subagent's role is `Agent.name`, its peak `max(Agent.peak, Agent.context)`;
# finished when "completed" below the limit, an overrun when "stopped" or at or above the limit.


def _agent(
    status: str | None,
    peak: int,
    context: int,
    *,
    name: str = "builder",
    description: str = "Build s1.d1",
) -> Agent:
    return Agent(
        task_id=f"t-{description}",
        name=name,
        description=description,
        context=context,
        status=status,
        peak=peak,
    )


def _agents_sized(cfg: Config, *runs: Run) -> list[Sized]:
    return [item for item in stats.sized(_history(*runs), cfg) if item.role != "lead"]


@pytest.mark.parametrize(
    ("status", "peak", "context", "want_peak", "overrun"),
    [
        ("completed", 30_000, 20_000, 30_000, None),
        ("completed", 0, 25_000, 25_000, None),
        ("completed", LIMIT - 1, 10_000, LIMIT - 1, None),
        ("completed", LIMIT, 10_000, LIMIT, "over context limit"),
        ("completed", 0, LIMIT, LIMIT, "over context limit"),
        ("stopped", 40_000, 35_000, 40_000, "stopped"),
    ],
    ids=[
        "completed-peak",
        "completed-older-snapshot-context",
        "completed-just-below-limit",
        "completed-at-limit",
        "completed-context-at-limit",
        "stopped",
    ],
)
def test_a_subagent_is_sized_by_its_name_description_and_peak(
    status: str, peak: int, context: int, want_peak: int, overrun: str | None, cfg: Config
) -> None:
    # Breaks when: the role is not `Agent.name`, the label not its description, the section not
    # its run's, the peak is `context` alone or `peak` alone, the limit uses `>`, or a stopped
    # subagent is finished.
    parent = _run(
        "lead",
        "Too big.\nRECUT: split",
        5_000,
        section="s4",
        agents=(_agent(status, peak, context),),
    )
    assert _agents_sized(cfg, parent) == [
        Sized(role="builder", section="s4", label="Build s1.d1", peak=want_peak, overrun=overrun)
    ]


@pytest.mark.parametrize("status", [None, "failed", "running"])
def test_a_subagent_with_any_other_status_is_not_sized(status: str | None, cfg: Config) -> None:
    # Breaks when: a subagent neither completed nor stopped is counted as finished or overrun.
    parent = _run("lead", "Step committed.\nDONE", 5_000, agents=(_agent(status, 30_000, 20_000),))
    assert _agents_sized(cfg, parent) == []


def test_the_subagents_of_every_run_are_sized(cfg: Config) -> None:
    # Breaks when: only one run's subagents are read, or a subagent is skipped because its run
    # is itself neither finished nor overrun.
    first = _run(
        "lead",
        "Too big.\nRECUT: split",
        5_000,
        section="s1",
        session="sess-a",
        agents=(_agent("completed", 30_000, 0, name="test-writer", description="Red s1"),),
    )
    second = _run(
        "lead",
        "Step committed.\nDONE",
        5_000,
        section="s2",
        session="sess-b",
        agents=(_agent("stopped", 50_000, 0, name="builder", description="Build s2"),),
    )
    found = sorted(_agents_sized(cfg, first, second), key=lambda item: item.label)
    assert found == [
        Sized(role="builder", section="s2", label="Build s2", peak=50_000, overrun="stopped"),
        Sized(role="test-writer", section="s1", label="Red s1", peak=30_000, overrun=None),
    ]


# Behavior 3: `by_role(items) -> list[RoleStats]`, sorted by role name.


def _item(
    role: str, peak: int, overrun: str | None = None, *, section: str = "s1", label: str = "sess-1"
) -> Sized:
    return Sized(role=role, section=section, label=label, peak=peak, overrun=overrun)


def test_by_role_groups_finished_peaks_and_overruns_sorted_by_role_name() -> None:
    # Breaks when: roles come out in first-seen order, an overrun's peak is counted as finished,
    # a finished peak is lost, or overruns are reordered.
    late = _item("lead", 150_000, "over context limit", section="s3", label="sess-c")
    early = _item("lead", 80_000, "retired", section="s2", label="sess-b")
    stopped = _item("builder", 40_000, "stopped", label="Build s1")
    items = [
        _item("test-writer", 12_000),
        early,
        _item("lead", 40_000),
        stopped,
        _item("builder", 9_000),
        _item("lead", 60_000),
        late,
    ]
    found = stats.by_role(items)
    assert [entry.role for entry in found] == ["builder", "lead", "test-writer"]
    assert [sorted(entry.finished) for entry in found] == [[9_000], [40_000, 60_000], [12_000]]
    assert [entry.overruns for entry in found] == [(stopped,), (early, late), ()]


def test_by_role_keeps_a_role_with_only_overruns() -> None:
    # Breaks when: a role with no finished run is dropped.
    stopped = _item("builder", 40_000, "stopped", label="Build s1")
    assert stats.by_role([stopped]) == [RoleStats(role="builder", finished=(), overruns=(stopped,))]


def test_by_role_of_nothing_is_empty() -> None:
    # Breaks when: an empty input yields a placeholder role.
    assert stats.by_role([]) == []


# Behavior 4: one line per role, `<role>: <n> finished, peak context median <m>, p90 <p>,
# max <x>; <k> overruns`.

# 21 peaks: positions 1-16 are 100..1600, 17-20 are 5000, 21 is 9000, so the median is 1100,
# the 90th percentile 5000 by any common rule, and the max 9000.
PEAKS = tuple([100 * n for n in range(1, 17)] + [5_000] * 4 + [9_000])


def _shuffled(values: tuple[int, ...]) -> tuple[int, ...]:
    out = list(values)
    random.Random(7).shuffle(out)
    return tuple(out)


def _overrun_line(item: Sized) -> str:
    return f"  {item.role} overrun: {item.section} {item.label} peak {item.peak} ({item.overrun})"


def test_a_role_line_gives_count_median_p90_max_and_overrun_count() -> None:
    # Breaks when: a figure is taken unsorted, the median or p90 is computed wrongly, the max is
    # wrong, or the line's wording or punctuation differs.
    overruns = (
        _item("lead", 120_000, "over context limit", section="s2", label="sess-b"),
        _item("lead", 80_000, "retired", section="s3", label="sess-c"),
    )
    found = stats.lines([RoleStats(role="lead", finished=_shuffled(PEAKS), overruns=overruns)])
    assert found[0] == "lead: 21 finished, peak context median 1100, p90 5000, max 9000; 2 overruns"


def test_a_role_with_no_overruns_prints_its_line_alone() -> None:
    # Breaks when: a zero overrun count is left out or an overrun line is printed for none.
    found = stats.lines([RoleStats(role="recut", finished=(7_000,), overruns=())])
    assert found == ["recut: 1 finished, peak context median 7000, p90 7000, max 7000; 0 overruns"]


def test_each_role_line_is_followed_by_its_own_overruns() -> None:
    # Breaks when: overruns are printed after all role lines, or under the wrong role.
    builder_over = _item("builder", 40_000, "stopped", label="Build s1")
    lead_over = _item("lead", 80_000, "retired", section="s2", label="sess-b")
    found = stats.lines(
        [
            RoleStats(role="builder", finished=(9_000,), overruns=(builder_over,)),
            RoleStats(role="lead", finished=(30_000,), overruns=(lead_over,)),
        ]
    )
    assert found == [
        "builder: 1 finished, peak context median 9000, p90 9000, max 9000; 1 overruns",
        "  builder overrun: s1 Build s1 peak 40000 (stopped)",
        "lead: 1 finished, peak context median 30000, p90 30000, max 30000; 1 overruns",
        "  lead overrun: s2 sess-b peak 80000 (retired)",
    ]


# Behavior 5: a role with no finished run prints `0 finished` and no figures; its overruns
# follow, newest last.


def test_a_role_with_no_finished_run_prints_0_finished_and_no_figures() -> None:
    # Breaks when: an empty role prints figures (or crashes computing them), or its overruns
    # are dropped or reordered.
    overruns = (
        _item("builder", 40_000, "stopped", section="s1", label="Build s1"),
        _item("builder", 110_000, "over context limit", section="s2", label="Build s2"),
        _item("builder", 50_000, "stopped", section="s3", label="Build s3"),
    )
    found = stats.lines([RoleStats(role="builder", finished=(), overruns=overruns)])
    assert found[0].startswith("builder: 0 finished")
    for word in ("median", "p90", "max"):
        assert word not in found[0]
    assert found[1:] == [_overrun_line(item) for item in overruns]


# Behavior 6: each overrun line is `  <role> overrun: <section> <label> peak <n> (<reason>)`.


@pytest.mark.parametrize(
    ("role", "section", "label", "peak", "reason", "line"),
    [
        (
            "lead",
            "s2",
            "sess-b",
            80_000,
            "retired",
            "  lead overrun: s2 sess-b peak 80000 (retired)",
        ),
        (
            "lead",
            "s5",
            "sess-k",
            210_000,
            "killed",
            "  lead overrun: s5 sess-k peak 210000 (killed)",
        ),
        (
            "builder",
            "s1",
            "Build s1.d1",
            40_000,
            "stopped",
            "  builder overrun: s1 Build s1.d1 peak 40000 (stopped)",
        ),
        (
            "test-writer",
            "s3.2",
            "Red s3.2",
            100_000,
            "over context limit",
            "  test-writer overrun: s3.2 Red s3.2 peak 100000 (over context limit)",
        ),
    ],
    ids=["retired", "killed", "stopped", "over-context-limit"],
)
def test_an_overrun_line_names_section_label_peak_and_reason(
    role: str, section: str, label: str, peak: int, reason: str, line: str
) -> None:
    # Breaks when: the indent, field order, wording or parentheses of an overrun line differ.
    item = _item(role, peak, reason, section=section, label=label)
    found = stats.lines([RoleStats(role=role, finished=(), overruns=(item,))])
    assert found[1:] == [line]


# Behavior 7: more than five overruns print `  <role>: <j> earlier overruns not shown` and the
# last five; numbers are bare integers.


def _overruns(count: int) -> tuple[Sized, ...]:
    return tuple(
        _item("lead", 100_000 + n, "over context limit", section=f"s{n}", label=f"sess-{n}")
        for n in range(1, count + 1)
    )


def test_more_than_five_overruns_show_the_newest_five_after_a_count_of_the_rest() -> None:
    # Breaks when: all overruns are printed, the oldest five are kept, or the count line is
    # missing, misplaced or miscounted.
    overruns = _overruns(7)
    found = stats.lines([RoleStats(role="lead", finished=(), overruns=overruns)])
    assert found[1:] == [
        "  lead: 2 earlier overruns not shown",
        *[_overrun_line(item) for item in overruns[2:]],
    ]


def test_exactly_five_overruns_are_all_shown_with_no_count_line() -> None:
    # Breaks when: the cut is at fewer than five, or a count line says 0 not shown.
    overruns = _overruns(5)
    found = stats.lines([RoleStats(role="lead", finished=(), overruns=overruns)])
    assert found[1:] == [_overrun_line(item) for item in overruns]


def test_numbers_are_bare_integers() -> None:
    # Breaks when: a figure is printed with separators, a unit suffix or decimals.
    over = _item("lead", 1_234_567, "killed", section="s9", label="sess-z")
    found = stats.lines([RoleStats(role="lead", finished=(123_456,), overruns=(over,))])
    assert found == [
        "lead: 1 finished, peak context median 123456, p90 123456, max 123456; 1 overruns",
        "  lead overrun: s9 sess-z peak 1234567 (killed)",
    ]
