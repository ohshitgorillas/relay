Status: approved.

# Relay: run the check, flat recuts, effort on a retry, idle retire

## Why

Relay takes a lead's `DONE` on its word: `relay/loop.py:119-120` marks the section done with nothing run. Every section's `check:` lines sit unread in the queue body (`docs/queue.md:14`, `docs/queue.md:51`; the Workboard queue spells it `done-check:`, `tests/fixtures/workboard-queue.md:19`), and no module in `relay/` parses them. A section's body holds one check line per dispatch, or none: `s1.2.1`, `s3.1.1` and `s7` have none (`docs/queue.md:29`, `docs/queue.md:52`, `docs/queue.md:158`), and Relay marks such a section done on the lead's `DONE`.

Copies and gaps this design closes:

- **Parking a section with a ping**: two copies of the same three calls, `state.park`, `ping.needs_owner`, `progress.needs_answer`, at `relay/loop.py:124-126` and `relay/loop.py:131-133`. This design adds three more parks (a check failing outside the code, a third failed check, a nested recut id), so the copy moves to one helper first.
- **Failure limits**: one limit, `FAILURE_LIMIT = 2` at `relay/state.py:19`, read at `relay/loop.py:176` and `relay/progress.py:110`. A second failure of any kind stops the whole run (`relay/loop.py:117-118`, `relay/loop.py:179-180`), so a three-failed-checks rule needs its own count beside it.
- **Retire and kill**: one decision point, the watcher at `relay/loop.py:153-168`, which sets the retire flag at `context_limit` and kills at `hard_ceiling`. The defaults are 100k and 2 × 100k (`relay/config.py:128-130`). The lead is told to look for the flag only "after a step's commit" (`relay/prompts.py:40`). A kill counts as a failure (`relay/loop.py:113`).
- **Process running**: `relay/runner.py:85-152` is the one place a child starts, and it has no timeout and no captured-output mode. `relay/ping.py:15` is the one allowed exception. Relay runs no `git` command today: it finds the repository by walking up for `.git` (`relay/loop.py:23-29`) and runs every lead and recut there (`relay/loop.py:50`).
- **Section worktrees**: the queue carries no worktree field (`relay/queue.py:63-74` reads only `depends:`, `from:` and `done` from a header). Leads put each section on its own worktree, branch `lead/<id>`: `git worktree list` shows `/Users/atom/dev/relay-wt/s1` on `lead/s1` through `relay-wt/s8` on `lead/s8`.
- **Recut ids**: `relay/loop.py:208-212` marks a kept id and each new id `from_recut`. Nothing checks how new ids are named, and the queue already carries nested ids from earlier recuts (`docs/queue.md:29` `s1.2.1`, `docs/queue.md:217` `s8.1.1`).
- **Effort**: Relay sets no effort. `relay/config.py:10-13` launches leads with no effort or model flag, so the effort rule lives in `lead.md` alone.
- **Ledger kinds**: `relay/ledger.py:45` takes only `"lead"` and `"recut"`. `_parse` at `relay/ledger.py:25-36` needs `time`, `tokens` and `dollars` on every line.

Nothing from Baley is installed or copied.

## Modules

### `relay/check.py` (new): runs a section's checks, judges the result, words the record

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from relay.config import Config
from relay.queue import Section

TAIL_LINES = 40          # lines kept from the end of the combined output
TAIL_CHARS = 4000        # and at most this many characters of them

Verdict = Literal["pass", "fail", "outside", "none"]


@dataclass(frozen=True)
class CheckResult:
    command: str | None      # the check line that decided the verdict; None when the section has none
    exit_code: int | None    # None when it timed out or none ran
    timed_out: bool
    tail: str                # the end of that command's output, TAIL_LINES / TAIL_CHARS
    log: Path | None         # the check log; None when none ran
    verdict: Verdict
    timeout: float | None = None  # the seconds limit the failing command ran under
                                  # (cfg.check_timeout) when it timed out; None when none timed out

    def __post_init__(self) -> None:
        """ValueError when timed_out is true and timeout is None."""


def run_checks(cfg: Config, section: Section, cwd: Path, log: Path) -> CheckResult:
    """Run each of section.checks in order in `cwd` through runner.run_command, appending all
    output to `log`, and stop at the first non-zero exit or timeout. verdict "none" when
    section.checks is empty; "pass" when all exit 0; otherwise classify() of the failing
    command. timeout is cfg.check_timeout on a timed-out command and None on every other result."""


def classify(cfg: Config, exit_code: int | None, timed_out: bool, tail: str) -> Literal["fail", "outside"]:
    """"outside" when exit_code is 126 or 127, or any pattern in cfg.check_outside matches tail
    (re.search); "fail" otherwise. A timeout with no pattern match is "fail"."""


def outcome_text(result: CheckResult) -> str:
    """The one wording of how a check ended: "timed out after <s>s" (s is result.timeout, %g)
    when result.timed_out, else "exit <n>"."""


def owner_text(result: CheckResult, failures: int) -> str:
    """The question parked for the owner and pinged: the command, outcome_text(result), the
    failure count when verdict is "fail", the log path, then the tail."""
```

`outcome_text` is the only wording of a check's ending. `owner_text`, `prompts.check_feedback` and `progress.check_finished` call it; `relay/prompts.py` and `relay/progress.py` import it from `relay.check` at run time.

It replaces nothing. Checks have never run in Relay.

### `relay/git.py` (new): the one place Relay asks git anything

```python
from pathlib import Path


def section_worktree(repo: Path, sid: str) -> Path | None:
    """The worktree `git worktree list --porcelain` (run in `repo`) shows on branch
    refs/heads/lead/<sid>, or None when there is none or git fails."""


def heads(repo: Path) -> dict[str, str]:
    """{ref: object} from `git for-each-ref --format=%(refname) %(objectname) refs/heads` in
    `repo`; {} when git fails. Covers every worktree's branch, since worktrees share refs."""
```

Both run git through `runner.capture`. Neither raises on a git failure.

### `relay/runner.py` (extended): a timed command and a captured command

```python
@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None    # None when killed at the timeout
    timed_out: bool


def run_command(command: str, cwd: Path, log: Path, timeout: float) -> CommandResult:
    """Run `/bin/sh -c command` in its own session in `cwd`, stdout and stderr both appended to
    `log`, stdin from /dev/null, with no env= so the child inherits the environment `relay go`
    started with. At `timeout` seconds kill the group with _kill_and_reap. Signal handlers as in
    run_agent: SIGINT/SIGTERM kill the group first."""


def capture(argv: list[str], cwd: Path, timeout: float) -> tuple[int | None, str]:
    """Run argv in `cwd`, return (exit code, stdout); (None, "") on OSError or timeout,
    the group killed and reaped."""
```

`run_agent` is unchanged.

### `relay/queue.py` (extended): check lines and the recut note

```python
@dataclass(frozen=True)
class Section:
    id: str
    title: str
    body: str
    depends_on: tuple[str, ...]
    open: bool
    checks: tuple[str, ...] = ()     # each `check:` or `done-check:` line's command, in body order,
                                     # leading whitespace allowed, fenced blocks skipped
    came_from: str | None = None     # the header field `from: <id>`, removed from the title
```

A `from:` id must match `_ID`. It need not name a section still in the queue.

### `relay/state.py` (extended): the check count and a pending check

```python
CHECK_LIMIT = 3

@dataclass
class SectionState:
    status: SectionStatus
    failures: int
    question: str | None
    answer: str | None
    last_session: str | None
    from_recut: bool = False
    check_failures: int = 0          # failed checks (verdict "fail"); never counts toward FAILURE_LIMIT
    check_feedback: str | None = None  # the failing check text the next lead prompt carries
    check_pending: bool = False      # parked on an "outside" verdict: the next pass reruns the check, no lead

class State:
    def record_check_failure(self, sid: str, feedback: str) -> int: ...   # +1, sets check_feedback, returns the count
    def take_check_feedback(self, sid: str) -> str | None: ...
    def set_check_pending(self, sid: str, pending: bool) -> None: ...
    def check_log(self, run_log: Path) -> Path: ...                       # run_log.with_suffix(".check"): runs/<n>.check
```

`mark_done` also clears `check_feedback` and `check_pending`. `set_answer` leaves `check_pending` as it is.

### `relay/ledger.py` (extended): a check line

```python
def append_check(self, section: str, result: "CheckResult") -> None:
    """One line: time, kind "check", section, session null, tokens 0, dollars 0.0, command,
    exit (int or null), timed_out, verdict, tail, log (str or null). Written as append writes."""
```

`tokens` and `dollars` are 0, so `total`, `over` and `unreadable` read check lines unchanged. `sessions()` skips them because their session is null.

### `relay/config.py` (extended): three keys

```python
def _default_idle_ceiling(context_limit: int, hard_ceiling: int) -> int:
    """min(context_limit * 13 // 10, hard_ceiling - 1): the one idle-ceiling default."""


@dataclass(frozen=True)
class Config:
    ...                         # existing fields, in their order
    idle_ceiling: int = 0       # always an int; 0 means unset
    check_timeout: float = 1800 # seconds per check command
    check_outside: list[str] = field(default_factory=lambda: list(_DEFAULT_CHECK_OUTSIDE))

    def __post_init__(self) -> None:
        """When idle_ceiling is 0, set it to _default_idle_ceiling(context_limit, hard_ceiling).
        No range check: a Config built in code is not range-checked."""


def load_config(path: Path | None, overrides: dict[str, object]) -> Config:
    """As now. An unset idle_ceiling reaches Config as 0 (a set one is a positive int, as _int
    requires). After the Config is built, ConfigError unless
    context_limit < cfg.idle_ceiling < hard_ceiling; load_config is the only range check.
    ConfigError on a check_outside pattern re.compile rejects."""
```

With context_limit 100000 and hard_ceiling 120000 and no idle_ceiling, idle_ceiling is 119999 and the config loads. At the defaults (100000, 200000) it is 130000.

Default `check_outside`: `command not found`, `(?i)credit balance`, `(?i)api[ _-]?key`, `(?i)could not resolve host`, `(?i)name resolution`, `(?i)network is unreachable`, `(?i)connection (refused|reset|timed out)`. All three keys join `_KEYS`. `relay go` gains `--idle-ceiling`.

### `relay/prompts.py` (extended)

```python
def lead_prompt(queue, section, resume, answer, retire_flag, check_feedback: str | None = None) -> str:
    """As now, plus, when check_feedback is set: "Relay ran this section's check after your DONE
    and it failed. Fix the section and end with DONE again:" and the feedback verbatim."""

def check_feedback(result: "CheckResult") -> str:
    """The command, check.outcome_text(result), the log path and the tail, for the lead."""
```

### `relay/progress.py` (extended)

```python
def check_started(sid: str, command_count: int, cwd: Path) -> None: ...   # "check <sid>: running <n> check(s) in <cwd>"
def check_finished(sid: str, result: CheckResult) -> None: ...            # "check <sid>: passed" | "failed: <outcome_text>" | "<outcome_text>" on a timeout | "outside the code: <outcome_text>" | "none to run"
def check_failed(sid: str, failures: int) -> None: ...                    # "section <sid>: check failed (<n> of 3)"
def retired_idle(sid: str, tokens: int) -> None: ...                      # "lead <sid>: retired at <tokens> context tokens, no commit since the retire flag"
```

### `relay/loop.py` (changed)

```python
@dataclass
class _Watch:
    on_event: Callable[[StreamState], Literal["go", "retire", "kill"]]
    budget_hit: bool = False
    idle_retired: bool = False

def _watcher(cfg, ledger, since, who, sid, repo: Path) -> _Watch:
    """As now, plus: when the retire flag first goes up (context or budget), snapshot
    git.heads(repo). On an event at context >= cfg.idle_ceiling with the flag up, compare
    git.heads(repo) with the snapshot. When they are equal, set idle_retired, call
    progress.retired_idle and return "kill". The hard_ceiling kill keeps its order and meaning."""

def _park(cfg: Config, queue: Path, state: State, sid: str, question: str) -> None:
    """state.park, ping.needs_owner, progress.needs_answer: the one park."""

def _verify(cfg, queue, state, ledger, cwd, section, run_log: Path) -> None:
    """Run the checks in git.section_worktree(cwd, sid) or else cwd, logging to
    state.check_log(run_log), then ledger.append_check and progress.check_finished. pass: mark_done.
    none (the section has no check line): mark_done on the lead's DONE, the ledger line carrying
    verdict "none" and the progress line "none to run". fail:
    record_check_failure(prompts.check_feedback(result)), progress.check_failed, and at
    CHECK_LIMIT or more _park(owner_text). outside: set_check_pending(True) and _park(owner_text).
    The section stays open on a fail below the limit, so the next pass resumes its lead."""
```

`_run_section` changes in four places:

- A section with `check_pending` runs `_verify` and no lead. The run log is the section's last lead log, `state.run_dir / "<n>.jsonl"` for the highest-numbered run the ledger files under the section. When there is none, the check log is `runs/check-<sid>.check`, built in `state.py`.
- `DONE` calls `_verify` in place of `mark_done`.
- A run with `idle_retired` set is handled as `RETIRED`. It records no failure.
- `take_check_feedback` feeds `lead_prompt`.

`_recut` treats a recut as failed, through `_fail` as an unchanged queue is now, when any id it adds starts with `<section.id>.`. The rest of `_recut` is unchanged: `relay/loop.py:208-212` keeps a non-split recut's id and marks it `from_recut`.

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Choosing, running and judging a section's checks; the outside-the-code rule; the owner's check text; how a check ended (`outcome_text`) | `relay/check.py` | running a check, matching `check_outside` or reading an exit code as pass or fail in any other module; wording a check's exit or timeout ("exit <n>", "timed out ...") anywhere but `outcome_text` |
| Git queries: section worktree, branch heads | `relay/git.py` | a `git` argv anywhere else; finding a worktree by path convention |
| Child processes, timeouts, output capture | `relay/runner.py` | `subprocess`, `os.kill`, `signal` elsewhere (`ping.py:15` keeps its one call) |
| `check:` / `done-check:` lines and the `from:` note | `relay/queue.py` | regex-matching a section body for check lines anywhere else |
| Check count, feedback, pending flag, check log path | `relay/state.py` | `CHECK_LIMIT` written elsewhere; a path joined onto `run_dir` elsewhere |
| Check lines in the ledger | `relay/ledger.py` (`append_check`) | writing a check result to `ledger.jsonl` anywhere else |
| Idle ceiling, check timeout, outside patterns, and their defaults; the idle-ceiling default (`_default_idle_ceiling`) and its range check (`load_config`) | `relay/config.py` | a 130k, a 13/10, a timeout or a pattern literal anywhere else; a second idle-ceiling default; a range check in `Config.__post_init__` or outside `load_config` |
| Parking with a ping | `relay/loop.py` `_park` | `state.park` called anywhere but `_park`; replaces `relay/loop.py:124-126` and `relay/loop.py:131-133` |
| Retire, idle retire and kill | `relay/loop.py` `_watcher` | a retire or kill verdict decided anywhere else |
| Check text for the lead | `relay/prompts.py` | lead-facing check wording in `loop.py` or `check.py` |
| Progress lines for checks and idle retire | `relay/progress.py` | printing them anywhere else |
| Recut naming and the `from:` note's format | `/Users/atom/.claude/agents/divvyer.md` (written), `relay/queue.py` (read) | a second statement of the naming rule |
| Retry effort and the test-writer floor | `/Users/atom/.claude/agents/lead.md` | an effort flag in `relay/config.py`, which sets none |
| Test fakes and fixtures | `tests/conftest.py`, `tests/fakes/fake_claude.py`, `tests/fixtures/` | an ad hoc git repo or check queue built inside a test file |

## Order

1. Stubs. `builder` (`stub` piece) writes `relay/check.py` and `relay/git.py`, and adds to `relay/runner.py`, `relay/queue.py`, `relay/state.py`, `relay/ledger.py`, `relay/config.py`, `relay/prompts.py` and `relay/progress.py` every new signature above, raise-only. New fields go in with their defaults.
2. Test helpers. `test-writer` writes `tests/conftest.py` and `tests/fixtures/check-queue.md`. `fake_cfg` gains the three config fields. A fixture makes a temporary git repository with a `lead/<id>` worktree. The fixture queue holds sections with several checks, with none, and with a `from:` note.
3. Core: red tests. `test-writer` writes `tests/test_config.py`, `tests/test_queue.py`, `tests/test_runner.py`, `tests/test_git.py`, `tests/test_state.py` and `tests/test_ledger.py`.
4. Core: build. `builder` writes `relay/config.py`, `relay/queue.py`, `relay/runner.py`, `relay/git.py`, `relay/state.py`, `relay/ledger.py` and `relay/cli.py` (`--idle-ceiling`).
5. Check, prompts, progress: red tests. `test-writer` writes `tests/test_check.py`, `tests/test_prompts.py` and `tests/test_progress.py`.
6. Check, prompts, progress: build. `builder` writes `relay/check.py`, `relay/prompts.py` and `relay/progress.py`.
7. Loop: red tests. `test-writer` writes `tests/test_loop.py` and `tests/test_cli.py`. The tests cover:
   - a check on `DONE`: pass, fail and resume with the output, the third fail parking, outside parking and rerunning on the next pass with no lead, and a section with no check;
   - the check inheriting `relay go`'s environment;
   - the ledger line and the check log;
   - idle retire with and without a commit, and the 200k kill unchanged;
   - a nested recut id failing the recut.
8. Loop: build. `builder` writes `relay/loop.py`, with `_park` replacing `relay/loop.py:124-126` and `relay/loop.py:131-133`. The step ends with the full suite green.
9. Recut naming rule. `general-purpose` writes `/Users/atom/.claude/agents/divvyer.md`:
   - A recut that splits a section makes flat siblings: the parent's id with the next free letter (`s4` gives `s4a`, `s4b`; `s4a` gives the next free letters) or the next free section number. Never `<id>.<n>`.
   - Each sibling's header carries the field `from: <parent id>`.
   - A recut that does not split keeps the id.
   - Relay parks a section after 3 failed checks and does not send it to a recut.
10. Retry effort rule. `general-purpose` writes `/Users/atom/.claude/agents/lead.md`:
    - Every agent keeps its file's `effort: medium`.
    - When a lead re-sends a task after a failed check or a rejected review, that one retry runs at high effort, and the next send returns to the default.
    - `test-writer` never runs below Opus at medium effort.
    - A lead resumed by Relay with check feedback re-sends the failing step under this rule.
