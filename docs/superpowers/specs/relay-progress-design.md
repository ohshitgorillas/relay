Status: approved.

# Relay: progress lines for `relay go`

## Why

`relay go` writes nothing of its own to the terminal while it runs. `relay/loop.py` holds no `print` and no write to `sys.stdout` or `sys.stderr`; the only terminal writes in the package are `relay status`'s report (`relay/cli.py:80`, `relay/cli.py:85`, `relay/cli.py:86`, `relay/cli.py:90`), usage and error lines on stderr (`relay/cli.py:22`, `relay/cli.py:23`, `relay/cli.py:102`) and a failed ping's stderr line (`relay/ping.py:17`, `relay/ping.py:20`). The events the owner wants to see happen only in `relay/loop.py`: the run starts (`relay/loop.py:32`), a lead starts and finishes (`relay/loop.py:95`, `relay/loop.py:101`), a recut starts and finishes (`relay/loop.py:165`, `relay/loop.py:167`), a lead is asked to retire or killed (`relay/loop.py:128`, `relay/loop.py:132`, `relay/loop.py:134`), a section parks (`relay/loop.py:112`) or fails (`relay/loop.py:104`), the loop waits on parked sections (`relay/loop.py:69`), and the run ends (`relay/loop.py:38`, `relay/loop.py:40`).

No copy of progress output exists to count; this design gives it one home before any is written. The pings stay as they are: `relay/ping.py` and every call to it (`relay/loop.py:38`, `relay/loop.py:40`, `relay/loop.py:113`) are unchanged, and a progress line never replaces a ping.

A child's stderr is inherited by the terminal: `run_agent` passes no `stderr` to `Popen` (`relay/runner.py:101`). What `claude` writes there is unmeasured, and this design leaves the runner unchanged.

This design builds on the modules of `docs/superpowers/specs/relay-loop-design.md` and changes only `relay/loop.py` among them.

## Modules

`relay/progress.py`: the one place a `relay go` progress line is worded and written. Each line goes to `sys.stdout`, flushed at once, and starts with the local time as `HH:MM:SS `. Each function writes exactly one line. A question or reason is cut to its first line and to 120 characters, ending `…` when cut. A failed write (`OSError`, `BrokenPipeError` included) is swallowed, never raised: a closed terminal never stops the loop.

```python
from pathlib import Path
from typing import Literal
from relay.agents import Event
from relay.config import Config
from relay.runner import RunResult
from relay.status import LeadStatus

def started(queue: Path, cfg: Config) -> None: ...
# "relay go <queue name>: started; budget <N> tokens, $<D>" — each absent budget reads "no token budget" / "no dollar budget"

def lead_started(sid: str, resume: str | None, answered: bool) -> None: ...
# "lead <sid>: started, resuming <session>" or "lead <sid>: started fresh"; ", with the owner's answer" appended when answered

def lead_finished(sid: str, result: RunResult, status: LeadStatus | None) -> None: ...
# "lead <sid>: finished <outcome> (<tokens> tokens, $<dollars>)", the spend from result.stream.spend, dollars to 2 places.
# outcome: "killed" when result.killed; "exit <code>" when result.exit_code != 0; "with no status line" when status is None;
# else status.kind, followed by ": <text>" for RECUT. The first that holds, in that order.

def retiring(sid: str, why: Literal["context", "budget"], tokens: int) -> None: ...
# "lead <sid>: asked to retire at <tokens> context tokens" or "lead <sid>: asked to retire, budget spent"

def killing(sid: str, tokens: int) -> None: ...
# "lead <sid>: killed at <tokens> context tokens, past the hard ceiling"

def recut_started(sid: str, reason: str) -> None: ...
# "recut <sid>: started: <reason>"

def recut_finished(sid: str, result: RunResult, changed: bool) -> None: ...
# "recut <sid>: finished <outcome> (<tokens> tokens, $<dollars>)"; outcome "killed", "exit <code>", "with the queue unchanged" or "with the queue recut", the first that holds

def agent_event(who: Literal["lead", "recut"], sid: str, event: Event) -> None: ...
# "<who> <sid>: agent <name> started: <description> (<who> + <live> agents)" when a subagent starts;
# "<who> <sid>: agent <name> <status> in <time>, context <tokens>: <description> (<who> + <live> agents)" when it finishes.
# <status> is the finish status, "finished" when none was reported; "in <time>" reads "time unknown" when no duration was
# reported; <time> as `agents.duration` words it; "agent" for a live count of 1. The description is cut like a question.

def needs_answer(sid: str, question: str) -> None: ...
# "section <sid>: needs an answer: <question>"

def failed(sid: str, failures: int) -> None: ...
# "section <sid>: failed (<failures> of 2)"

def waiting(parked: list[str]) -> None: ...
# "waiting for answers on <id>, <id>"

def ended(queue: Path, code: int, reason: str, detail: str) -> None: ...
# "relay go <queue name>: ended <reason>: <detail> (exit <code>)"
```

`relay/loop.py` calls these, and nothing else in it writes to the terminal:
- `run` calls `progress.started` after `state.lock()` succeeds, and `progress.ended` after each `ping.stopped`, the crash path included with reason `crashed` and code `ExitCode.ERROR`.
- `_run_section` calls `progress.lead_started` just before `run_agent`, with `answered` true when `take_answer` returned an answer, and `progress.lead_finished` once `parse_status` returns. On `NEEDS-OWNER` it calls `progress.needs_answer` beside `ping.needs_owner`. On every failure `record_failure` counts, the recut's included, it calls `progress.failed` with the new count.
- `_watcher` takes who runs (`lead` or `recut`) and the section id and calls `progress.retiring` the first time it returns `retire` in a run and `progress.killing` when it returns `kill`; it never repeats a line within one run. On each stream event it calls `progress.agent_event` once for every event in `stream.activity.events` it has not yet printed in this run, in order, for leads and recuts alike.
- `_recut` calls `progress.recut_started` before its `run_agent` and `progress.recut_finished` after it.
- `_loop` calls `progress.waiting` when it enters a wait and the parked set differs from the set it last printed; a wait that goes on prints nothing more.

`_fail` returns `(second, count)`, the count being what `record_failure` returned, so `progress.failed` gets the number `record_failure` returned; no failure count is kept in `relay/loop.py` or `relay/progress.py`.

Agent lines carry no cost: no stream event reports a cost for each subagent, and an estimate would read as a measurement. Background shell tasks (`task_type` other than `local_agent`) get no line.

`relay/progress.py` replaces nothing: no progress output exists in the tree.

Test helpers: progress tests read the lines with pytest's `capsys` and match each line after its `HH:MM:SS ` prefix. They use the `fake_cfg`, `queue_file` and `scenario` fixtures of `tests/conftest.py` and the stream fixtures in `tests/fixtures/`; no second fake agent is written.

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Wording and writing `relay go` progress lines | `relay/progress.py` | `print`, `sys.stdout` or `sys.stderr` in `relay/loop.py`, `relay/runner.py`, `relay/state.py`, `relay/ledger.py`, `relay/stream.py`, `relay/queue.py`, `relay/status.py` or `relay/prompts.py`; a progress line worded in any other module |
| Owner pings | `relay/ping.py`, unchanged | a progress function sending a ping, or `relay/ping.py` writing a progress line |
| Failure counts | `relay/state.py` (`record_failure`) | a failure count kept in `relay/loop.py` or `relay/progress.py` |
| `relay status` output and CLI error lines | `relay/cli.py` | `relay/cli.py` writing a `relay go` progress line |

## Order

1. Progress stub. `builder` (`stub` piece) writes `relay/progress.py` with every signature above raise-only.
2. Progress lines: red tests. `test-writer` writes `tests/test_progress.py`, covering each function's line, and `tests/test_loop.py`, covering the lines `relay go` writes, in order, for a run that starts, runs a lead to each outcome, recuts, parks a section, fails a section, waits and ends, and that the pings are unchanged.
3. Progress lines: build. `builder` writes `relay/progress.py` and `relay/loop.py`.
