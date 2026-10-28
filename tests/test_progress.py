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
from typing import Callable, Iterator

import pytest

from relay import progress
from relay.agents import Agent, Event
from relay.config import Config
from relay.ledger import Spend
from relay.runner import RunResult
from relay.status import LeadStatus
from relay.stream import StreamState

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
