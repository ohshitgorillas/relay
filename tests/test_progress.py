"""Red tests for Relay's progress lines (design: docs/superpowers/specs/relay-progress-design.md, Modules `relay/progress.py`; Order 2).

Lines are read with pytest's `capsys` and matched after their `HH:MM:SS ` prefix (design: Test helpers).
"""

from __future__ import annotations

import dataclasses
import importlib
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable, Iterator, Literal

import pytest

from relay import progress
from relay.agents import Agent, Event
from relay.check import CheckResult
from relay.config import Config
from relay.ladder import DesignReport
from relay.ledger import Spend
from relay.research import Map
from relay.runner import RunResult
from relay.status import LeadStatus
from relay.stream import StreamState
from tests.conftest import FIXTURES

PREFIX = re.compile(r"^(\d{2}):(\d{2}):(\d{2}) ")


def _result(
    exit_code: int | None = 0,
    killed: bool = False,
    tokens: int = 1234,
    dollars: float = 1.5,
) -> RunResult:
    stream = StreamState(
        session_id="sess-1",
        context_tokens=0,
        spend=Spend(tokens=tokens, dollars=dollars),
        result_text=None,
        is_error=False,
    )
    return RunResult(
        exit_code=exit_code,
        killed=killed,
        stream=stream,
        log=Path("/nonexistent/1.jsonl"),
    )


def _check(**changes: object) -> CheckResult:
    result = CheckResult(
        command="make check",
        exit_code=0,
        timed_out=False,
        tail="ok\n",
        log=Path("/nonexistent/1.check"),
        verdict="pass",
    )
    return dataclasses.replace(result, **changes)


def _agent(**changes: object) -> Agent:
    agent = Agent("a1", "builder", "Build s2.d1 stub", context=21844, duration_ms=36943, status="completed")
    return dataclasses.replace(agent, **changes)


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    captured = capsys.readouterr()
    assert captured.err == ""
    return captured.out


def _line(capsys: pytest.CaptureFixture[str]) -> str:
    """The one line written, without its `HH:MM:SS ` prefix and newline."""
    out = _out(capsys)
    assert out.endswith("\n")
    assert out.count("\n") == 1
    match = PREFIX.match(out)
    assert match is not None
    return out[match.end() : -1]


# The researcher's map in `tests/fixtures/research-map.txt` (design: Homes, test fixtures): its
# body is the lines from `MAP` to `END MAP`, both included; its files every path an entry or link
# names, sorted, no repeats.
MAP_COMMIT = "0123456789abcdef0123456789abcdef01234567"
_MAP_TEXT = (FIXTURES / "research-map.txt").read_text()
MAP_BODY = _MAP_TEXT[_MAP_TEXT.index("MAP\n") : _MAP_TEXT.index("END MAP") + len("END MAP")]
MAP_FILES = ("relay/git.py", "relay/loop.py", "relay/research.py")


def _map(sid: str = "s1", commit: str = MAP_COMMIT) -> Map:
    return Map(sid=sid, commit=commit, files=MAP_FILES, body=MAP_BODY)


DESIGN = Path("/work/relay/docs/superpowers/specs/relay-ladder-design.md")


def _report(
    rejected: bool = False,
    approved: bool = False,
    decisions: tuple[str, ...] = (),
    unfiled: tuple[str, ...] = (),
) -> DesignReport:
    return DesignReport(rejected=rejected, approved=approved, decisions=decisions, unfiled=unfiled)


def _queues(queue: Path) -> tuple[str, ...]:
    return (queue.name, queue.stem)


def _calls(queue: Path, cfg: Config) -> list[tuple[str, Callable[[], None]]]:
    """One call of each progress function, with ordinary single-line arguments."""
    return [
        ("started", lambda: progress.started(queue, cfg)),
        ("lead_started", lambda: progress.lead_started("s1", "sess-9", True)),
        (
            "lead_finished",
            lambda: progress.lead_finished(
                "s1", _result(), LeadStatus(kind="DONE", text="")
            ),
        ),
        ("retiring", lambda: progress.retiring("s1", "context", 100_000)),
        ("killing", lambda: progress.killing("s1", 200_000)),
        ("recut_started", lambda: progress.recut_started("s1", "too big")),
        ("recut_finished", lambda: progress.recut_finished("s1", _result(), True)),
        ("agent_event", lambda: progress.agent_event("lead", "s1", Event("started", _agent(), 1))),
        ("needs_answer", lambda: progress.needs_answer("s1", "Which name?")),
        ("failed", lambda: progress.failed("s1", 1)),
        ("waiting", lambda: progress.waiting(["s1", "s2"])),
        ("ended", lambda: progress.ended(queue, 0, "done", "every section closed")),
        ("check_started", lambda: progress.check_started("s1", 2, Path("/work/wt/s1"))),
        ("check_finished", lambda: progress.check_finished("s1", _check())),
        ("check_failed", lambda: progress.check_failed("s1", 1)),
        ("retired_idle", lambda: progress.retired_idle("s1", 130_000)),
        ("research_started", lambda: progress.research_started("s1", Path("/work/wt/s1"))),
        ("research_finished", lambda: progress.research_finished("s1", _result(), _map())),
        ("map_reused", lambda: progress.map_reused("s1", _map())),
        (
            "design_started",
            lambda: progress.design_started("s1", DESIGN, ("6", "7"), "the design lacks a cap"),
        ),
        ("design_finished", lambda: progress.design_finished("s1", _result(), _report(approved=True))),
        ("section_waiting", lambda: progress.section_waiting("s1", "s2")),
        ("woken", lambda: progress.woken("s1", "s2")),
        ("design_retrying", lambda: progress.design_retrying("s1", "it filed no report")),
        ("design_handed_back", lambda: progress.design_handed_back("s1", "it filed no report")),
    ]


NAMES = [
    "started",
    "lead_started",
    "lead_finished",
    "retiring",
    "killing",
    "recut_started",
    "recut_finished",
    "agent_event",
    "needs_answer",
    "failed",
    "waiting",
    "ended",
    "check_started",
    "check_finished",
    "check_failed",
    "retired_idle",
    "research_started",
    "research_finished",
    "map_reused",
    "design_started",
    "design_finished",
    "section_waiting",
    "woken",
    "design_retrying",
    "design_handed_back",
]


def _call(
    name: str, queue_file: Callable[[str], Path], cfg: Config
) -> Callable[[], None]:
    return dict(_calls(queue_file("workboard-queue.md"), cfg))[name]


class _Stdout:
    """A stand-in for `sys.stdout` that records each write and flush in order."""

    def __init__(
        self, fail: BaseException | None = None, fail_on: str = "write"
    ) -> None:
        self.events: list[tuple[str, str]] = []
        self.fail = fail
        self.fail_on = fail_on

    def write(self, text: str) -> int:
        self.events.append(("write", text))
        if self.fail is not None and self.fail_on == "write":
            raise self.fail
        return len(text)

    def flush(self) -> None:
        self.events.append(("flush", ""))
        if self.fail is not None and self.fail_on == "flush":
            raise self.fail

    def text(self) -> str:
        return "".join(text for kind, text in self.events if kind == "write")


# Behavior 1: `relay/progress.py`: the one place a `relay go` progress line is worded and
# written. Each line starts with the local time as `HH:MM:SS ` (design: Modules).


@pytest.fixture(params=["XYZ-14", "ABC+12"], ids=["utc-plus-14", "utc-minus-12"])
def far_host_zone(request: pytest.FixtureRequest) -> Iterator[str]:
    """Run the host in a zone (POSIX `TZ`) 12 or more hours from UTC from before `relay.progress`
    is imported: the module is imported afresh under that zone, so one that reads its zone once at
    import sees it as surely as one that reads it on every call. The host zone and a fresh import
    under it are restored afterwards."""
    saved = os.environ.get("TZ")
    os.environ["TZ"] = request.param
    time.tzset()
    try:
        importlib.reload(progress)
        yield request.param
    finally:
        if saved is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved
        time.tzset()
        importlib.reload(progress)


@pytest.mark.parametrize("name", NAMES)
def test_each_line_starts_with_the_local_time_of_the_zone_the_host_runs_in(
    name: str,
    far_host_zone: str,
    queue_file: Callable[[str], Path],
    fake_cfg: Config,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a function writes no time prefix, a UTC time, a time not as HH:MM:SS, or a
    # time in a zone other than the one the host ran in when the module was imported.
    call = _call(name, queue_file, fake_cfg)
    before = time.time()
    call()
    after = time.time()
    out = _out(capsys)
    match = PREFIX.match(out)
    assert match is not None
    stamp = out[:8]
    local = {time.strftime("%H:%M:%S", time.localtime(t)) for t in (before, after)}
    utc = {time.strftime("%H:%M:%S", time.gmtime(t)) for t in (before, after)}
    # The zone is 12 or more hours from UTC, so the local and UTC clocks never read alike.
    assert not local & utc
    assert stamp not in utc
    assert min(local) <= stamp <= max(local) or stamp in local


# Behavior 2: Each line goes to `sys.stdout`, flushed at once.


@pytest.mark.parametrize("name", NAMES)
def test_each_line_goes_to_stdout_and_is_flushed(
    name: str,
    queue_file: Callable[[str], Path],
    fake_cfg: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when: the line goes to stderr or another stream, or is left in the buffer unflushed.
    call = _call(name, queue_file, fake_cfg)
    out = _Stdout()
    err = _Stdout()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    call()
    assert err.text() == ""
    assert PREFIX.match(out.text()) is not None
    assert out.text().endswith("\n")
    writes = [i for i, (kind, _) in enumerate(out.events) if kind == "write"]
    flushes = [i for i, (kind, _) in enumerate(out.events) if kind == "flush"]
    assert writes
    assert flushes
    assert max(flushes) > max(writes)


# Behavior 3: Each function writes exactly one line.


@pytest.mark.parametrize("name", NAMES)
def test_each_function_writes_exactly_one_line(
    name: str,
    queue_file: Callable[[str], Path],
    fake_cfg: Config,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a function writes no line, two lines, or a line without its newline.
    _call(name, queue_file, fake_cfg)()
    out = _out(capsys)
    assert out.endswith("\n")
    assert out.count("\n") == 1


def test_a_multi_line_question_still_writes_one_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: needs_answer writes the question's later lines as more terminal lines.
    progress.needs_answer(
        "s4", "Which name?\nThe CLI ships under it.\nAnswer by Friday."
    )
    out = _out(capsys)
    assert out.count("\n") == 1


def test_a_multi_line_reason_still_writes_one_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: recut_started writes the reason's later lines as more terminal lines.
    progress.recut_started("s4", "three modules, not one step\nsee the plan")
    out = _out(capsys)
    assert out.count("\n") == 1


# Behavior 4: A question or reason is cut to its first line and to 120 characters, ending `…`
# when cut.


def _is_cut(shown: str, full: str) -> bool:
    """`shown` is `full` cut to 120 characters ending `…` (the `…` within or after the 120)."""
    return shown in (full[:119] + "…", full[:120] + "…")


def test_a_question_is_cut_to_its_first_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the question's second line reaches the progress line.
    progress.needs_answer("s4", "Which name?\nThe CLI ships under it.")
    line = _line(capsys)
    assert line in (
        "section s4: needs an answer: Which name?",
        "section s4: needs an answer: Which name?…",
    )


def test_a_reason_is_cut_to_its_first_line(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: the reason's second line reaches the progress line.
    progress.recut_started("s4", "three modules, not one step\nsee the plan")
    line = _line(capsys)
    assert line in (
        "recut s4: started: three modules, not one step",
        "recut s4: started: three modules, not one step…",
    )


def test_a_long_question_is_cut_to_120_characters_ending_ellipsis(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a question over 120 characters is written whole, or cut without its `…`.
    question = "".join(f"word{i:03d} " for i in range(40))
    progress.needs_answer("s4", question)
    line = _line(capsys)
    head = "section s4: needs an answer: "
    assert line.startswith(head)
    assert _is_cut(line[len(head) :], question)


def test_a_long_reason_is_cut_to_120_characters_ending_ellipsis(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a reason over 120 characters is written whole, or cut without its `…`.
    reason = "".join(f"part{i:03d} " for i in range(40))
    progress.recut_started("s4", reason)
    line = _line(capsys)
    head = "recut s4: started: "
    assert line.startswith(head)
    assert _is_cut(line[len(head) :], reason)


def test_a_long_first_line_is_cut_after_dropping_later_lines(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the 120-character cut is taken over the whole text rather than its first line.
    first = "x" * 200
    progress.needs_answer("s4", first + "\nsecond line")
    line = _line(capsys)
    head = "section s4: needs an answer: "
    assert line.startswith(head)
    assert _is_cut(line[len(head) :], first)


def test_a_question_of_exactly_120_characters_is_not_cut(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the cut fires at 120 characters instead of over them, or `…` is added uncut.
    question = "q" * 119 + "?"
    progress.needs_answer("s4", question)
    assert _line(capsys) == "section s4: needs an answer: " + question


def test_a_short_reason_is_not_cut(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: `…` is appended to a reason that needed no cut.
    progress.recut_started("s4", "too big")
    assert _line(capsys) == "recut s4: started: too big"


# Behavior 5: A failed write (`OSError`, `BrokenPipeError` included) is swallowed, never raised:
# a closed terminal never stops the loop.


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize(
    ("fail", "fail_on"),
    [
        (BrokenPipeError(32, "Broken pipe"), "write"),
        (OSError(5, "Input/output error"), "write"),
        (BrokenPipeError(32, "Broken pipe"), "flush"),
        (OSError(5, "Input/output error"), "flush"),
    ],
    ids=[
        "broken-pipe-on-write",
        "oserror-on-write",
        "broken-pipe-on-flush",
        "oserror-on-flush",
    ],
)
def test_a_failed_write_is_swallowed(
    name: str,
    fail: BaseException,
    fail_on: str,
    queue_file: Callable[[str], Path],
    fake_cfg: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when: an OSError or BrokenPipeError from writing or flushing stdout escapes the function.
    call = _call(name, queue_file, fake_cfg)
    stdout = _Stdout(fail=fail, fail_on=fail_on)
    monkeypatch.setattr(sys, "stdout", stdout)
    assert call() is None
    assert stdout.events


# Behavior 6: def started(queue: Path, cfg: Config) -> None: ...
# "relay go <queue name>: started; budget <N> tokens, $<D>" — each absent budget reads
# "no token budget" / "no dollar budget"


def test_started_names_both_budgets(
    queue_file: Callable[[str], Path],
    fake_cfg: Config,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the queue name, the token budget or the dollar budget is missing or misworded.
    queue = queue_file("workboard-queue.md")
    cfg = dataclasses.replace(fake_cfg, token_budget=500000, dollar_budget=12.25)
    progress.started(queue, cfg)
    line = _line(capsys)
    assert line in tuple(
        f"relay go {q}: started; budget 500000 tokens, $12.25" for q in _queues(queue)
    )


def test_started_with_no_budgets_says_so(
    queue_file: Callable[[str], Path],
    fake_cfg: Config,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: an absent budget is shown as "None" or left out instead of "no ... budget".
    queue = queue_file("workboard-queue.md")
    progress.started(queue, fake_cfg)
    line = _line(capsys)
    assert any(line.startswith(f"relay go {q}: started; ") for q in _queues(queue))
    assert "no token budget" in line
    assert "no dollar budget" in line
    assert "None" not in line
    assert line.endswith("no dollar budget")


def test_started_with_only_a_token_budget(
    queue_file: Callable[[str], Path],
    fake_cfg: Config,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the dollar budget's absence is not worded "no dollar budget" beside a token budget.
    queue = queue_file("workboard-queue.md")
    progress.started(queue, dataclasses.replace(fake_cfg, token_budget=750000))
    line = _line(capsys)
    assert any(line.startswith(f"relay go {q}: started; ") for q in _queues(queue))
    assert "750000 tokens" in line
    assert "no token budget" not in line
    assert line.endswith(", no dollar budget")


def test_started_with_only_a_dollar_budget(
    queue_file: Callable[[str], Path],
    fake_cfg: Config,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the token budget's absence is not worded "no token budget" beside a dollar budget.
    queue = queue_file("workboard-queue.md")
    progress.started(queue, dataclasses.replace(fake_cfg, dollar_budget=12.25))
    line = _line(capsys)
    assert any(line.startswith(f"relay go {q}: started; ") for q in _queues(queue))
    assert "no token budget, " in line
    assert line.endswith("$12.25")
    assert "no dollar budget" not in line


# Behavior 7: def lead_started(sid: str, resume: str | None, answered: bool) -> None: ...
# "lead <sid>: started, resuming <session>" or "lead <sid>: started fresh"; ", with the
# owner's answer" appended when answered


def test_lead_started_fresh(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a lead with no session to resume is not reported "started fresh".
    progress.lead_started("s1.2", None, False)
    assert _line(capsys) == "lead s1.2: started fresh"


def test_lead_started_resuming(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: the resumed session id is missing or the wording differs.
    progress.lead_started("s1.2", "sess-77", False)
    assert _line(capsys) == "lead s1.2: started, resuming sess-77"


def test_lead_started_fresh_with_the_owners_answer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: an answered fresh start omits ", with the owner's answer".
    progress.lead_started("s1.2", None, True)
    assert _line(capsys) == "lead s1.2: started fresh, with the owner's answer"


def test_lead_started_resuming_with_the_owners_answer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: an answered resume omits ", with the owner's answer" or puts it before the session.
    progress.lead_started("s1.2", "sess-77", True)
    assert (
        _line(capsys) == "lead s1.2: started, resuming sess-77, with the owner's answer"
    )


# Behavior 8: def lead_finished(sid: str, result: RunResult, status: LeadStatus | None) -> None: ...
# "lead <sid>: finished <outcome> (<tokens> tokens, $<dollars>)", spend from
# result.stream.spend, dollars to 2 places; outcome "killed" / "exit <code>" / "with no status
# line" / status.kind (": <text>" for RECUT), the first that holds, in that order.


def test_lead_finished_done(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a DONE lead's outcome or spend is misworded, or dollars not shown to 2 places.
    progress.lead_finished(
        "s2", _result(tokens=4321, dollars=1.5), LeadStatus(kind="DONE", text="")
    )
    assert _line(capsys) == "lead s2: finished DONE (4321 tokens, $1.50)"


def test_lead_finished_retired(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a RETIRED lead's outcome is not its status kind.
    progress.lead_finished(
        "s2", _result(tokens=10, dollars=0.1234), LeadStatus(kind="RETIRED", text="")
    )
    assert _line(capsys) == "lead s2: finished RETIRED (10 tokens, $0.12)"


def test_lead_finished_needs_owner_shows_only_the_kind(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the NEEDS-OWNER question is appended, which only RECUT's reason is.
    status = LeadStatus(kind="NEEDS-OWNER", text="Which name?")
    progress.lead_finished("s2", _result(tokens=7, dollars=2.0), status)
    assert _line(capsys) == "lead s2: finished NEEDS-OWNER (7 tokens, $2.00)"


def test_lead_finished_recut_shows_its_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a RECUT outcome drops ": <text>".
    status = LeadStatus(kind="RECUT", text="three modules, not one step")
    progress.lead_finished("s2", _result(tokens=99, dollars=0.25), status)
    assert (
        _line(capsys)
        == "lead s2: finished RECUT: three modules, not one step (99 tokens, $0.25)"
    )


def test_lead_finished_with_no_status_line(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a clean exit with no status line is not worded "with no status line".
    progress.lead_finished("s2", _result(exit_code=0, tokens=5, dollars=0.0), None)
    assert _line(capsys) == "lead s2: finished with no status line (5 tokens, $0.00)"


def test_lead_finished_non_zero_exit_beats_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a non-zero exit is reported by its status kind instead of "exit <code>".
    progress.lead_finished(
        "s2",
        _result(exit_code=3, tokens=5, dollars=0.5),
        LeadStatus(kind="DONE", text=""),
    )
    assert _line(capsys) == "lead s2: finished exit 3 (5 tokens, $0.50)"


def test_lead_finished_non_zero_exit_with_no_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: "with no status line" is checked ahead of a non-zero exit.
    progress.lead_finished("s2", _result(exit_code=1, tokens=5, dollars=0.5), None)
    assert _line(capsys) == "lead s2: finished exit 1 (5 tokens, $0.50)"


def test_lead_finished_killed_beats_everything(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a killed lead is reported by its exit code or status instead of "killed".
    result = _result(exit_code=None, killed=True, tokens=250000, dollars=3.75)
    progress.lead_finished("s2", result, LeadStatus(kind="DONE", text=""))
    assert _line(capsys) == "lead s2: finished killed (250000 tokens, $3.75)"


def test_lead_finished_killed_with_no_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a killed lead with no status reads "exit None" or "with no status line".
    progress.lead_finished(
        "s2", _result(exit_code=None, killed=True, tokens=1, dollars=0.0), None
    )
    assert _line(capsys) == "lead s2: finished killed (1 tokens, $0.00)"


# Behavior 9: def retiring(sid: str, why: Literal["context", "budget"], tokens: int) -> None: ...
# "lead <sid>: asked to retire at <tokens> context tokens" or "lead <sid>: asked to retire, budget spent"


def test_retiring_for_context(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a context retirement omits the context token count or is misworded.
    progress.retiring("s3", "context", 100250)
    assert _line(capsys) == "lead s3: asked to retire at 100250 context tokens"


def test_retiring_for_budget(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a budget retirement is worded as a context one or shows the token count.
    progress.retiring("s3", "budget", 4200)
    assert _line(capsys) == "lead s3: asked to retire, budget spent"


# Behavior 10: def killing(sid: str, tokens: int) -> None: ...
# "lead <sid>: killed at <tokens> context tokens, past the hard ceiling"


def test_killing(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: the kill line omits the context token count or the hard ceiling.
    progress.killing("s3", 200001)
    assert (
        _line(capsys)
        == "lead s3: killed at 200001 context tokens, past the hard ceiling"
    )


# Behavior 11: def recut_started(sid: str, reason: str) -> None: ...
# "recut <sid>: started: <reason>"


def test_recut_started_names_the_section_and_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the recut start line drops the section id or the reason, or is misworded.
    progress.recut_started("s5.1", "two leads needed")
    assert _line(capsys) == "recut s5.1: started: two leads needed"


# Behavior 12: def recut_finished(sid: str, result: RunResult, changed: bool) -> None: ...
# "recut <sid>: finished <outcome> (<tokens> tokens, $<dollars>)"; outcome "killed", "exit <code>",
# "with the queue unchanged" or "with the queue recut", the first that holds


def test_recut_finished_with_the_queue_recut(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a clean recut that changed the queue is misworded, or its spend is not shown to 2 places.
    progress.recut_finished("s5", _result(tokens=3456, dollars=0.7), True)
    assert (
        _line(capsys) == "recut s5: finished with the queue recut (3456 tokens, $0.70)"
    )


def test_recut_finished_with_the_queue_unchanged(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a clean recut that left the queue alone is reported as recut.
    progress.recut_finished("s5", _result(tokens=12, dollars=0.004), False)
    assert (
        _line(capsys)
        == "recut s5: finished with the queue unchanged (12 tokens, $0.00)"
    )


def test_recut_finished_non_zero_exit_beats_changed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a recut that exited non-zero is reported by whether the queue changed.
    progress.recut_finished("s5", _result(exit_code=2, tokens=8, dollars=1.0), True)
    assert _line(capsys) == "recut s5: finished exit 2 (8 tokens, $1.00)"


def test_recut_finished_non_zero_exit_with_queue_unchanged(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: "with the queue unchanged" is checked ahead of a non-zero exit.
    progress.recut_finished("s5", _result(exit_code=1, tokens=8, dollars=1.0), False)
    assert _line(capsys) == "recut s5: finished exit 1 (8 tokens, $1.00)"


def test_recut_finished_killed_beats_everything(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a killed recut is reported by its exit code or the queue's state instead of "killed".
    result = _result(exit_code=None, killed=True, tokens=210000, dollars=4.5)
    progress.recut_finished("s5", result, True)
    assert _line(capsys) == "recut s5: finished killed (210000 tokens, $4.50)"


def test_recut_finished_killed_with_queue_unchanged(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a killed recut that left the queue alone reads "exit None" or "with the queue unchanged".
    result = _result(exit_code=None, killed=True, tokens=1, dollars=0.0)
    progress.recut_finished("s5", result, False)
    assert _line(capsys) == "recut s5: finished killed (1 tokens, $0.00)"


@pytest.mark.parametrize("changed", [True, False], ids=["recut", "unchanged"])
@pytest.mark.parametrize("exit_code", [-9, 137, 1, 0], ids=["sigkill", "137", "1", "0"])
def test_recut_finished_killed_whatever_its_exit_code(
    exit_code: int, changed: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: "killed" is read from the exit code (None, -9) rather than result.killed, so a
    # killed recut that came back with a code reads "exit <code>" or a queue outcome.
    result = _result(exit_code=exit_code, killed=True, tokens=42, dollars=0.5)
    progress.recut_finished("s5", result, changed)
    assert _line(capsys) == "recut s5: finished killed (42 tokens, $0.50)"


# Behavior 13: def needs_answer(sid: str, question: str) -> None: ...
# "section <sid>: needs an answer: <question>"


def test_needs_answer_names_the_section_and_question(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the line drops the section id or the question, or is misworded.
    progress.needs_answer("s6.2", "Ship under relay or baton?")
    assert _line(capsys) == "section s6.2: needs an answer: Ship under relay or baton?"


# Behavior 14: def failed(sid: str, failures: int) -> None: ...
# "section <sid>: failed (<failures> of 2)"


@pytest.mark.parametrize("failures", [1, 2])
def test_failed_shows_the_count_of_two(
    failures: int, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: the failure count is missing, fixed, or not shown "of 2".
    progress.failed("s7", failures)
    assert _line(capsys) == f"section s7: failed ({failures} of 2)"


# Behavior 15: def waiting(parked: list[str]) -> None: ...
# "waiting for answers on <id>, <id>"


def test_waiting_on_one_section(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a single parked id is misworded or carries a stray separator.
    progress.waiting(["s8"])
    assert _line(capsys) == "waiting for answers on s8"


def test_waiting_on_several_sections_lists_them_comma_separated(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: parked ids are dropped, reordered, or joined other than by ", ".
    progress.waiting(["s8", "s2.1", "s9"])
    assert _line(capsys) == "waiting for answers on s8, s2.1, s9"


# Behavior 16: def ended(queue: Path, code: int, reason: str, detail: str) -> None: ...
# "relay go <queue name>: ended <reason>: <detail> (exit <code>)"


def test_ended_names_queue_reason_detail_and_code(
    queue_file: Callable[[str], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the queue name, reason, detail or exit code is missing or misworded.
    queue = queue_file("workboard-queue.md")
    progress.ended(queue, 3, "crashed", "KeyError: 's1'")
    line = _line(capsys)
    assert line in tuple(
        f"relay go {q}: ended crashed: KeyError: 's1' (exit 3)" for q in _queues(queue)
    )


def test_ended_with_code_zero(
    queue_file: Callable[[str], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a clean end omits "(exit 0)" or shows another code.
    queue = queue_file("m2-rest-queue.md")
    progress.ended(queue, 0, "done", "every section closed")
    line = _line(capsys)
    assert line in tuple(
        f"relay go {q}: ended done: every section closed (exit 0)"
        for q in _queues(queue)
    )


# `agent_event`: one line when a lead or recut's subagent starts or finishes, with the count live.


def test_agent_started_names_the_agent_its_description_and_the_count_live(
    capsys: pytest.CaptureFixture[str],
) -> None:
    progress.agent_event("lead", "s2", Event("started", _agent(), 2))
    assert _line(capsys) == "lead s2: agent builder started: Build s2.d1 stub (lead + 2 agents)"


def test_agent_finished_shows_status_time_and_context_but_no_cost(
    capsys: pytest.CaptureFixture[str],
) -> None:
    progress.agent_event("lead", "s2", Event("finished", _agent(), 1))
    line = _line(capsys)
    assert line == (
        "lead s2: agent builder completed in 36.9s, context 21844: Build s2.d1 stub (lead + 1 agent)"
    )
    assert "$" not in line


def test_agent_finished_without_a_reported_time_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    agent = _agent(duration_ms=None, status="stopped", context=0)
    progress.agent_event("recut", "s3", Event("finished", agent, 0))
    assert _line(capsys) == (
        "recut s3: agent builder stopped time unknown, context 0: Build s2.d1 stub (recut + 0 agents)"
    )


# Check design (docs/superpowers/specs/relay-check-design.md, Modules `relay/progress.py`;
# Order 5). Behavior 9: Progress lines for checks and idle retire


@pytest.mark.parametrize("count", [1, 3])
def test_check_started_names_the_section_count_and_cwd(
    count: int, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: the section id, the number of checks or the directory is missing or misworded.
    progress.check_started("s4", count, Path("/work/relay-wt/s4"))
    noun = "check" if count == 1 else "checks"
    assert _line(capsys) in (
        f"check s4: running {count} check(s) in /work/relay-wt/s4",
        f"check s4: running {count} {noun} in /work/relay-wt/s4",
    )


def test_check_finished_passed(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a passing check is not reported "passed".
    progress.check_finished("s4", _check(verdict="pass", exit_code=0))
    assert _line(capsys) == "check s4: passed"


def test_check_finished_failed_shows_the_exit(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a failed check omits its exit code or is misworded.
    progress.check_finished("s4", _check(verdict="fail", exit_code=2))
    assert _line(capsys) == "check s4: failed: exit 2"


def test_check_finished_timed_out(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a timed-out check reads "failed: exit None" or "failed: <outcome_text>"
    # instead of "<outcome_text>", or its limit is not worded "timed out after <s>s" with s as %g
    # (docs/superpowers/specs/relay-check-design.md:68 and :220).
    progress.check_finished(
        "s4", _check(verdict="fail", exit_code=None, timed_out=True, timeout=1800.0)
    )
    assert _line(capsys) == "check s4: timed out after 1800s"


def test_check_finished_outside_the_code(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: an outside verdict is reported as a plain failure or drops its exit code.
    progress.check_finished("s4", _check(verdict="outside", exit_code=127))
    assert _line(capsys) == "check s4: outside the code: exit 127"


def test_check_finished_none_to_run(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a section with no check line is reported passed or failed.
    result = _check(command=None, exit_code=None, tail="", log=None, verdict="none")
    progress.check_finished("s4", result)
    assert _line(capsys) == "check s4: none to run"


@pytest.mark.parametrize("failures", [1, 2, 3])
def test_check_failed_shows_the_count_of_three(
    failures: int, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: the check failure count is missing, fixed, or not shown "of 3".
    progress.check_failed("s4", failures)
    assert _line(capsys) == f"section s4: check failed ({failures} of 3)"


def test_retired_idle_names_the_tokens_and_no_commit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the idle retire line omits the context token count or is misworded.
    progress.retired_idle("s4", 131072)
    assert _line(capsys) == (
        "lead s4: retired at 131072 context tokens, no commit since the retire flag"
    )


# Research design (docs/superpowers/specs/relay-research-design.md, Modules `relay/progress.py`;
# Order 5). Behavior 1: Progress lines for research. Each also joins NAMES above, so it starts with
# the local time, goes to stdout flushed, writes one line and swallows a failed write.


def test_research_started_names_the_section_and_cwd(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: the section id or the directory is missing, or the line is not
    # "research <sid>: mapping in <cwd>".
    progress.research_started("s4.2", Path("/work/relay-wt/s4.2"))
    assert _line(capsys) == "research s4.2: mapping in /work/relay-wt/s4.2"


def test_research_finished_with_a_map_counts_its_lines_and_files(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the map's line count (its body, MAP to END MAP), its file count, its commit or
    # the run's spend is missing or misworded.
    assert len(MAP_BODY.splitlines()) == 7
    progress.research_finished("s4", _result(tokens=5678, dollars=0.9), _map("s4"))
    assert _line(capsys) == (
        f"research s4: map of 7 lines, 3 files at {MAP_COMMIT} (5678 tokens, $0.90)"
    )


def test_research_finished_counts_the_maps_own_files(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the file count is fixed or counted from the body's lines rather than m.files.
    m = dataclasses.replace(_map("s4"), files=("relay/git.py",))
    progress.research_finished("s4", _result(tokens=1, dollars=0.0), m)
    assert _line(capsys) == f"research s4: map of 7 lines, 1 files at {MAP_COMMIT} (1 tokens, $0.00)"


def test_research_finished_without_a_map_says_the_lead_starts_without_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a run with no usable map is not worded "no usable map", drops its spend, or
    # omits "; the lead starts without one".
    progress.research_finished("s4", _result(tokens=4321, dollars=1.5), None)
    assert _line(capsys) == (
        "research s4: no usable map (4321 tokens, $1.50); the lead starts without one"
    )


@pytest.mark.parametrize(
    ("exit_code", "killed", "tokens", "error_text", "error"),
    [
        (None, True, 9, None, "killed"),
        (2, False, 9, None, "exit 2"),
        (0, False, 9, "Prompt is too long", "Prompt is too long"),
        (0, False, 0, None, "used no tokens"),
    ],
    ids=["killed", "exit-2", "error-result", "no-tokens"],
)
def test_research_finished_after_a_failed_run_names_its_error_line(
    exit_code: int | None,
    killed: bool,
    tokens: int,
    error_text: str | None,
    error: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A failed run (killed, exit nonzero, is_error set, or 0 tokens) is reported as failed with
    # runner.error_line; this run's log has no readable stderr (relay-research-design.md:105,
    # 110, 213).
    # Breaks when: a failed research run is reported as "no usable map", its error line is
    # missing or taken in the wrong order, or the line drops its spend or "; the lead starts
    # without a map".
    result = _result(exit_code=exit_code, killed=killed, tokens=tokens, dollars=0.25)
    if error_text is not None:
        stream = dataclasses.replace(result.stream, result_text=error_text, is_error=True)
        result = dataclasses.replace(result, stream=stream)
    progress.research_finished("s4", result, None)
    assert _line(capsys) == (
        f"research s4: failed: {error} ({tokens} tokens, $0.25); the lead starts without a map"
    )


def test_map_reused_names_the_section_and_commit(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: the section id or the map's commit is missing, or the line is not
    # "research <sid>: map at <commit> still current, reused".
    progress.map_reused("s4", _map("s4", commit="feedface" * 5))
    assert _line(capsys) == f"research s4: map at {'feedface' * 5} still current, reused"


# Research design, behavior 2: `agent_event(who: Literal["lead", "recut", "research", "ask"], ...)`.
# The design's `relay/progress.py` section: "`relay ask` prints only the answer on stdout; its
# progress goes nowhere."


@pytest.mark.parametrize("kind", ["started", "finished"])
def test_an_ask_runs_agent_events_print_nothing(
    kind: Literal["started", "finished"], capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: agent_event writes a line for an ask run's subagent, so `relay ask` prints more
    # than its answer.
    progress.agent_event("ask", "s4", Event(kind, _agent(name="reader"), 1))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# Research design, behavior 3: an idle-ceiling retire line is labelled with the run's kind (lead,
# research or ask) as the retire and kill lines are, and an ask run's idle retire line goes
# nowhere: "`relay ask` prints only the answer on stdout; its progress goes nowhere."


def test_an_ask_runs_idle_retire_line_prints_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: retired_idle writes a line for an ask run, so `relay ask` prints more than its
    # answer on stdout.
    progress.retired_idle("s4", 131072, who="ask")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# Ladder design (docs/superpowers/specs/relay-ladder-design.md, Modules `relay/progress.py`;
# Order 6). The new lines also join NAMES above, so each starts with the local time, goes to
# stdout flushed, writes one line and swallows a failed write.
#
# Behavior 1: `lead_finished` as now; DESIGN and WAITING show _cut(text) as RECUT does.


def test_lead_finished_design_shows_its_problem(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a DESIGN outcome drops ": <text>", as NEEDS-OWNER's does.
    status = LeadStatus(kind="DESIGN", text="the design names no cap for a section")
    progress.lead_finished("s2", _result(tokens=99, dollars=0.25), status)
    assert _line(capsys) == (
        "lead s2: finished DESIGN: the design names no cap for a section (99 tokens, $0.25)"
    )


def test_lead_finished_waiting_shows_the_section_it_waits_on(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a WAITING outcome drops ": <section id>".
    status = LeadStatus(kind="WAITING", text="s1.2")
    progress.lead_finished("s2", _result(tokens=7, dollars=2.0), status)
    assert _line(capsys) == "lead s2: finished WAITING: s1.2 (7 tokens, $2.00)"


@pytest.mark.parametrize("kind", ["DESIGN", "WAITING"])
def test_lead_finished_cuts_a_design_or_waiting_text_to_its_first_line(
    kind: Literal["DESIGN", "WAITING"], capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: the text's later lines reach the progress line, or the text is shown uncut.
    status = LeadStatus(kind=kind, text="first line of it\nsecond line of it")
    progress.lead_finished("s2", _result(tokens=5, dollars=0.5), status)
    assert _line(capsys) in (
        f"lead s2: finished {kind}: first line of it (5 tokens, $0.50)",
        f"lead s2: finished {kind}: first line of it… (5 tokens, $0.50)",
    )


@pytest.mark.parametrize("kind", ["DESIGN", "WAITING"])
def test_lead_finished_cuts_a_long_design_or_waiting_text_to_120_characters(
    kind: Literal["DESIGN", "WAITING"], capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: a text over 120 characters is shown whole, or cut without its `…`.
    text = "".join(f"part{i:03d} " for i in range(40))
    progress.lead_finished("s2", _result(tokens=5, dollars=0.5), LeadStatus(kind=kind, text=text))
    line = _line(capsys)
    head = f"lead s2: finished {kind}: "
    tail = " (5 tokens, $0.50)"
    assert line.startswith(head)
    assert line.endswith(tail)
    assert _is_cut(line[len(head) : -len(tail)], text)


# Behavior 2: def retiring(sid, why: Literal["context", "budget", "cap"], tokens) -> None: ...
# "cap": "lead <sid>: asked to retire, section cap spent"


def test_retiring_for_the_section_cap(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a cap retirement is worded as a budget or context one, or shows the token count.
    progress.retiring("s3", "cap", 4200)
    assert _line(capsys) == "lead s3: asked to retire, section cap spent"


# Behavior 3: def design_started(sid, design: Path, steps: tuple[str, ...], problem: str) -> None: ...
# "design <sid>: amending <design> Order <steps>: <problem cut>"


def test_design_started_names_the_section_design_steps_and_problem(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the section id, the design path, a step or the problem is missing or misworded.
    # The design gives only "Order <steps>", so the separator between steps is left open.
    progress.design_started("s4", DESIGN, ("6", "7"), "the design names no cap for a section")
    line = _line(capsys)
    head = f"design s4: amending {DESIGN} Order "
    tail = ": the design names no cap for a section"
    assert line.startswith(head)
    assert line.endswith(tail)
    steps = line[len(head) : -len(tail)]
    assert steps.startswith("6")
    assert steps.endswith("7")
    assert len(steps) > 2


def test_design_started_with_one_step(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a single step carries a stray separator.
    progress.design_started("s4", DESIGN, ("3",), "no wake for a waiting section")
    assert _line(capsys) == f"design s4: amending {DESIGN} Order 3: no wake for a waiting section"


def test_design_started_cuts_the_problem_to_its_first_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the problem's later lines reach the progress line.
    progress.design_started("s4", DESIGN, ("6",), "no cap for a section\nsee the run log")
    assert _line(capsys) in (
        f"design s4: amending {DESIGN} Order 6: no cap for a section",
        f"design s4: amending {DESIGN} Order 6: no cap for a section…",
    )


def test_design_started_cuts_a_long_problem_to_120_characters(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a problem over 120 characters is shown whole, or cut without its `…`.
    problem = "".join(f"word{i:03d} " for i in range(40))
    progress.design_started("s4", DESIGN, ("6",), problem)
    line = _line(capsys)
    head = f"design s4: amending {DESIGN} Order 6: "
    assert line.startswith(head)
    assert _is_cut(line[len(head) :], problem)


# Behavior 4: def design_finished(sid, result: RunResult, report: DesignReport | None) -> None: ...
# "design <sid>: finished approved | with <n> decision(s) for the owner | rejected | with no report
# | killed | exit <n> <spend>"


def test_design_finished_approved(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: an approved design change is misworded, or its spend is missing or not to 2 places.
    progress.design_finished("s4", _result(tokens=3456, dollars=0.7), _report(approved=True))
    assert _line(capsys) == "design s4: finished approved (3456 tokens, $0.70)"


@pytest.mark.parametrize("count", [1, 2])
def test_design_finished_with_decisions_counts_them(
    count: int, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: a report with decisions is not worded "with <n> decision(s) for the owner", or
    # the count is fixed rather than read from the report.
    decisions = tuple(
        f"{n} | which name? | recommend: relay | alternative: baton" for n in range(1, count + 1)
    )
    progress.design_finished("s4", _result(tokens=12, dollars=1.0), _report(decisions=decisions))
    noun = "decision" if count == 1 else "decisions"
    assert _line(capsys) in (
        f"design s4: finished with {count} decision(s) for the owner (12 tokens, $1.00)",
        f"design s4: finished with {count} {noun} for the owner (12 tokens, $1.00)",
    )


def test_design_finished_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a rejected brief is reported as approved, as decisions, or with no report.
    progress.design_finished("s4", _result(tokens=8, dollars=0.25), _report(rejected=True))
    assert _line(capsys) == "design s4: finished rejected (8 tokens, $0.25)"


def test_design_finished_with_no_report(capsys: pytest.CaptureFixture[str]) -> None:
    # Breaks when: a clean exit with no report is not worded "with no report".
    progress.design_finished("s4", _result(exit_code=0, tokens=5, dollars=0.0), None)
    assert _line(capsys) == "design s4: finished with no report (5 tokens, $0.00)"


# Behavior 5: def section_waiting(sid: str, blocker: str) -> None: ...
# "section <sid>: waiting on <blocker>"


def test_section_waiting_names_the_section_and_its_blocker(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the section id or the blocker is missing, swapped or misworded.
    progress.section_waiting("s5.2", "s3.1")
    assert _line(capsys) == "section s5.2: waiting on s3.1"


# Behavior 6: def woken(sid: str, blocker: str) -> None: ...
# "section <sid>: woken, <blocker> landed"


def test_woken_names_the_section_and_the_blocker_that_landed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: the section id or the blocker is missing, swapped or misworded.
    progress.woken("s5.2", "s3.1")
    assert _line(capsys) == "section s5.2: woken, s3.1 landed"


# Codex architect design (docs/superpowers/specs/relay-codex-architect-design.md, Modules
# `relay/progress.py`; Order 3). The new lines also join NAMES above, so each starts with the
# local time, goes to stdout flushed, writes one line and swallows a failed write.

# def design_retrying(sid: str, what: str) -> None: ...
# "design <sid>: <what>; running the architect again"
# what (Modules `relay/loop.py`): "it failed: <error_line>" | "it filed no report"


@pytest.mark.parametrize("what", ["it failed: killed", "it filed no report"])
def test_design_retrying_names_the_section_and_why_the_architect_runs_again(
    what: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: the section id or `what` is missing or swapped, or the line does not end
    # "; running the architect again".
    progress.design_retrying("s4", what)
    assert _line(capsys) == f"design s4: {what}; running the architect again"


# def design_handed_back(sid: str, what: str) -> None: ...
# "design <sid>: <what>; back to the lead with the architect's message"
# what (Modules `relay/loop.py`): "it failed: <error_line>" | "it filed no report" | "it rejected
# the brief as steering" | "it did not approve the design"


@pytest.mark.parametrize(
    "what",
    [
        "it failed: exit 2",
        "it filed no report",
        "it rejected the brief as steering",
        "it did not approve the design",
    ],
)
def test_design_handed_back_names_the_section_and_why_the_lead_gets_it_back(
    what: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when: the section id or `what` is missing or swapped, or the line does not end
    # "; back to the lead with the architect's message".
    progress.design_handed_back("s4", what)
    assert _line(capsys) == f"design s4: {what}; back to the lead with the architect's message"


# def design_finished(sid, result: RunResult, report: DesignReport | None) -> None:
# "As now; runner.run_failed(result) words "failed: <runner.error_line(result)>" in place of its
# own killed and exit cases." A failed run is killed, exits nonzero or ends in a backend error
# (Why: "tests `killed`, `exit_code` and `is_error`"); the error lines are those of
# test_research_finished_after_a_failed_run_names_its_error_line, for a log with no stderr.


@pytest.mark.parametrize(
    ("exit_code", "killed", "error_text", "error"),
    [
        (None, True, None, "killed"),
        (2, False, None, "exit 2"),
        (0, False, "Prompt is too long", "Prompt is too long"),
    ],
    ids=["killed", "exit-2", "error-result"],
)
def test_design_finished_after_a_failed_run_names_its_error_line(
    exit_code: int | None,
    killed: bool,
    error_text: str | None,
    error: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Breaks when: a failed architect run reads "killed", "exit <n>" or "with no report" instead
    # of "failed: <error line>", or the line drops its spend.
    result = _result(exit_code=exit_code, killed=killed, tokens=9, dollars=0.25)
    if error_text is not None:
        stream = dataclasses.replace(result.stream, result_text=error_text, is_error=True)
        result = dataclasses.replace(result, stream=stream)
    progress.design_finished("s4", result, None)
    assert _line(capsys) == f"design s4: finished failed: {error} (9 tokens, $0.25)"
