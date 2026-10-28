Status: approved.

# Relay: an escalation ladder inside `relay go`, and waking a section that waits on another

## Why

When a lead ends `RECUT`, Relay has one move: the divvyer's recut (`relay/loop.py:127-129`). When a section from a recut asks again, Relay parks it and pings the owner (`relay/loop.py:121-126`). The owner then stops Relay, runs the architect and divvyer by hand, and restarts. Nothing in `relay/` runs the architect, reads a design path, caps a section's spend, or wakes a parked section. A section that waits on another can only park as `NEEDS-OWNER` (`relay/loop.py:130-133`), and it stays parked until the owner answers (`relay/loop.py:62-77`).

Copies and gaps this design closes. Line numbers are HEAD's `relay/loop.py`.

- **What happens after RECUT**: two branches decide it, `relay/loop.py:121-126` and `relay/loop.py:127-129`, with the rule hidden in an `elif` order. The choice of rung moves to one pure function.
- **Starting an agent run**: copies at `relay/loop.py:101-107` (lead) and `relay/loop.py:198-201` (recut). The research design's `_run` (`docs/superpowers/specs/relay-research-design.md`, Modules, `relay/loop.py`) replaces both. The architect run goes through that helper and gets no copy of its own.
- **Agent commands**: built only in `relay/config.py`. `recut_command` derives from `lead_command` at `relay/config.py:163`. The architect's command follows the same pattern.
- **Status words**: one list, `relay/status.py:6`, with text names at `relay/status.py:10`. The lead prompt prints the list from there (`relay/prompts.py:46-49`).
- **Run kinds**: `relay/ledger.py:20`. A ledger line carries no rung (`relay/ledger.py:56-63`). Nothing sums one section's spend: `total` sums every line (`relay/ledger.py:125-136`).
- **Budget retire**: one decision point, the watcher's `ledger.over` call (`relay/loop.py:157`; `relay/loop.py:170` in the working tree). A section cap retires at the same point.
- **Queue header fields**: read only at `relay/queue.py:63-74`. That code reads `depends:`, `from:` and `done`. The queue's head line `design <path> | order <path> | main <commit>` (`docs/baley-queue.md:1`, `docs/queue.md:1`) is skipped, because `parse_queue` starts at the first `section` line (`relay/queue.py:45-51`). A lead section's header names its design steps (`docs/baley-queue.md:2`, `steps: 1, 2, 3, 4, 5, 6`), and that field ends up in the title.
- **Held sections**: `blocked_by` (`relay/queue.py:98-110`) reads only the parked set the loop builds at `relay/loop.py:63`.
- **Lineage**: `from_recut` (`relay/state.py:35`) is set only by `_recut` (`relay/loop.py:208-212`).

This design builds on two approved designs. From the check design it uses `_park`, `_verify`, the `_watcher` that returns `_Watch`, and `CHECK_LIMIT` (`relay/state.py:20`). From the research design it uses `_run` and `_section_cwd`. Both designs' loop steps land before this design's loop step. The three-failed-checks park (`_verify`) is unchanged and is one of rung 3's limits.

### The architect's brief

The architect accepts a `rulings` brief that names the section's design file, because rung 2 amends an existing design. A `design` brief does not fit: it creates a new file, and it carries a task only in the owner's words or as a roadmap item. A rulings brief's legal lines are `lead new: <words>` for a gap the design leaves out, and one `approve: <the owner's words>`. The architect designs the fix itself from the problem it is given. Under the standing ruling of 26 Oct, an `approve:` line that quotes that ruling sets `Status: approved`.

A guess marked "free to ignore" does not work in this form. On the `lead new:` line, the guess becomes structure the architect builds. On a line of its own, it is a steering line that the architect ignores. So Relay leaves the guess out of the brief entirely.

The lead writes its reason as `<problem> | guess: <fix>`. Relay cuts the text at ` | guess: `. The architect gets the problem, the design step and the evidence paths. The guess reaches only the run log the lead wrote.

## Modules

### `relay/ladder.py` (new): choose the rung, split the lead's reason, read the architect's report, word the owner's text

Pure: no I/O, no state writes, no git.

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from relay.config import Config
from relay.queue import Section
from relay.state import SectionState

GUESS = " | guess: "
Rung = Literal[1, 2, 3]


@dataclass(frozen=True)
class Climb:
    rung: Rung
    why: str            # rung 3: the question parked for the owner; rungs 1 and 2: the progress text


def climb(kind: Literal["RECUT", "DESIGN"], s: SectionState, design: Path | None) -> Climb:
    """RECUT on a section that is neither from_recut nor design_changed: rung 1.
    RECUT on a from_recut section, or DESIGN, when not design_changed and design is not None: rung 2.
    design_changed: rung 3, "the ladder ran out: section <sid> already had its design change".
    design None at rung 2: rung 3, "no design to amend: the queue names none"."""


def split_reason(text: str) -> tuple[str, str | None]:
    """(problem, guess): the stripped text before the first GUESS and after it; (text.strip(), None)
    when GUESS is absent."""


@dataclass(frozen=True)
class DesignReport:
    rejected: bool                 # the first non-blank line is `REJECTED: STEERING`
    approved: bool                 # the STATUS line's text starts `Status: approved`
    decisions: tuple[str, ...]     # each indented line under DECISIONS, as written: `<n> | question | recommend: ... | alternative: ...`
    unfiled: tuple[str, ...]       # each indented line under UNFILED, as written


def parse_report(result_text: str | None) -> DesignReport | None:
    """The architect's report: `REJECTED: STEERING` first gives rejected=True. Otherwise the
    last block from a line starting `BRIEF ` to the line `END DESIGN`. None when neither is found."""


def decision_numbers(report: DesignReport) -> tuple[int, ...]:
    """The leading <n> of each decision line, in order."""


def design_of(design_line: str | None, top: Path) -> Path | None:
    """The queue head's design path (queue.queue_design), resolved against `top` when relative;
    None when design_line is None."""


def section_cap(cfg: Config, section: Section) -> float | None:
    """section.dollar_cap when set, else cfg.section_dollar_cap."""


def cap_text(sid: str, spent: float, cap: float) -> str:
    """"section <sid> spent $<spent:.2f> of its $<cap:.2f> cap; raise `cap:` in the queue or
    --section-dollar-cap to go on"."""


def decisions_text(sid: str, design: Path, report: DesignReport) -> str:
    """"the design change for <sid> in <design> needs a product choice:" then each decision
    and unfiled line verbatim, each with its recommendation and alternative."""


def failed_text(sid: str, design: Path, what: str) -> str:
    """"the design change for <sid> in <design> did not land: <what>"."""
```

It replaces the rung choice at `relay/loop.py:121-129`.

### `relay/queue.py` (extended): the queue's design, a section's steps and cap

```python
@dataclass(frozen=True)
class Section:
    ...                                  # existing fields, in their order
    steps: tuple[str, ...] = ()          # header field `steps: 1, 2`; the field stays in the title as written
    dollar_cap: float | None = None      # header field `cap: $5` or `cap: 5`, removed from the title; positive


def queue_design(path: Path) -> str | None:
    """The path after `design ` on the queue's first non-blank line, when that line starts
    `design ` and comes before the first section, up to the first ` | ` or the end of the line; None otherwise."""
```

A bad `cap:` value, one that is not a positive number, raises `QueueFormatError`.

### `relay/status.py` (extended): two status words

```python
Kind = Literal["DONE", "RECUT", "DESIGN", "WAITING", "NEEDS-OWNER", "RETIRED"]
TEXT_NAMES = {"RECUT": "reason", "DESIGN": "problem", "WAITING": "section id", "NEEDS-OWNER": "question"}
```

### `relay/state.py` (extended): lineage, an open design question, waiting

```python
SectionStatus = Literal["open", "done", "parked", "waiting"]

@dataclass
class SectionState:
    ...                                   # existing fields
    design_changed: bool = False          # this section had a design change, or a design-change recut made it
    design_open: str | None = None        # the design path whose product decision awaits the owner's answer
    waits_on: str | None = None           # the section id a waiting section waits for

class State:
    def mark_design_changed(self, sid: str) -> None: ...
    def set_design_open(self, sid: str, design: str | None) -> None: ...
    def wait(self, sid: str, blocker: str) -> None: ...   # status "waiting", waits_on blocker; no question
    def wake(self, sid: str) -> None: ...                 # status "open", waits_on None
```

`set_answer` also reopens a waiting section and clears `waits_on`. `mark_done` clears `design_open` and `waits_on`.

### `relay/ledger.py` (extended): the design kind, the rung, a section's spend

```python
Kind = Literal["lead", "recut", "research", "ask", "design"]

def append(self, kind, section, session, spend, map_commit=None, agents=(),
           rung: int | None = None) -> None:
    """As now; a line gains "rung" only when rung is not None."""

def section_spend(self, section: str) -> Spend:
    """Every readable line whose "section" is `section`, summed, across all time."""
```

Rung 1's recut line carries `rung: 1`. Rung 2's architect line (kind `design`) and its recut line both carry `rung: 2`. Rung 3 runs nothing and writes no line.

### `relay/config.py` (extended): three keys

```python
_STANDING_APPROVAL = "I am sick and tired of this paperwork bullshit make it stop for the 5th fucking time"

@dataclass(frozen=True)
class Config:
    ...                                    # existing fields, in their order
    design_command: list[str] | None = None   # default [*lead_command, "--agent", "architect"], set in
                                              # __post_init__ and load_config as research_command's is
    section_dollar_cap: float | None = None   # positive; None is no cap
    design_approval: str = _STANDING_APPROVAL # the owner's words Relay quotes on the architect's approve: line
```

All three keys join `_KEYS`. `relay go` gains `--section-dollar-cap`. A section's `cap:` overrides `section_dollar_cap` for that section.

### `relay/git.py` (extended)

```python
def clean(cwd: Path) -> bool | None:
    """`git status --porcelain` in `cwd`: True on exit 0 with no output, False with output, None when git fails."""
```

### `relay/prompts.py` (extended)

```python
def lead_prompt(...) -> str:
    """As now, plus a status rule. The text after RECUT: or DESIGN: is the problem: what fails,
    its evidence, and the design step it is under. A fix the lead has in mind follows only after
    ` | guess: `. DESIGN is for when the section's design lacks something no recut can supply.
    WAITING: <id> is for when the section cannot go on until queue section <id> lands."""

def design_brief(design: Path, queue: Path, section: Section, problem: str, evidence: list[Path],
                 approval: str) -> str:
    """Three lines and nothing else:
    `rulings <design>`
    `lead new: Section <sid> of the queue at <queue>, under this design's Order <section.steps,
     joined ", "; "steps unnamed" when empty>, cannot go on: <problem> Evidence: <paths, joined ", ">.`
    `approve: <approval>`"""

def design_answer_brief(design: Path, numbers: tuple[int, ...], answer: str, approval: str) -> str:
    """`rulings <design>`. Then each answer line that starts `<n>:` with n in numbers, as written.
    When there is none: `<n>: <answer>` when numbers has one entry, else `new: <answer>`.
    Then `approve: <approval>`."""

def recut_brief(queue, section, reason, lead_log, design: Path | None = None) -> str:
    """As now, plus when design is set: "The design <design> was amended for this problem. Cut this
    section's work again from it, its new Order steps included.""""
```

The guess never reaches `design_brief` or `recut_brief`: `loop.py` passes only `split_reason(...)[0]`.

### `relay/progress.py` (extended)

```python
def lead_finished(...) -> None: ...    # as now; DESIGN and WAITING show _cut(text) as RECUT does
def retiring(sid: str, why: Literal["context", "budget", "cap"], tokens: int) -> None: ...  # "cap": "lead <sid>: asked to retire, section cap spent"
def design_started(sid: str, design: Path, steps: tuple[str, ...], problem: str) -> None: ...   # "design <sid>: amending <design> Order <steps>: <problem cut>"
def design_finished(sid: str, result: RunResult, report: DesignReport | None) -> None: ...      # "design <sid>: finished approved | with <n> decision(s) for the owner | rejected | with no report | killed | exit <n> <spend>"
def section_waiting(sid: str, blocker: str) -> None: ...   # "section <sid>: waiting on <blocker>"
def woken(sid: str, blocker: str) -> None: ...             # "section <sid>: woken, <blocker> landed"
```

`agent_event` takes the widened `Kind`, so an architect's subagents print `design <sid>: agent ...`, the same way a lead's do.

### `relay/loop.py` (changed)

```python
def _climb(queue, cfg, state, ledger, since, cwd, section, kind: Literal["RECUT", "DESIGN"],
           text: str, lead: RunResult) -> _Stop | None:
    """ladder.climb(kind, state.section(sid), design). Rung 1: _recut with rung 1, and on failure
    _fail (the second failure returns _failed_twice). Rung 2: _design_change with the problem from
    split_reason. Rung 3: _park(climb.why)."""

def _design_change(queue, cfg, state, ledger, since, cwd, section, design: Path, problem: str,
                   lead_log: Path) -> None:
    """Over the section cap: _park(cap_text). Otherwise run design_command through _run (kind
    "design", rung 2) with design_brief(design, queue, section, problem, [lead_log, the section's
    last check log when one exists], cfg.design_approval) in _git_top(design.parent), then
    progress.design_finished and _design_outcome."""

def _design_answer(queue, cfg, state, ledger, since, cwd, section, answer: str) -> None:
    """For a section with design_open: run the architect with design_answer_brief(design_open,
    the open decision numbers, answer, cfg.design_approval), then _design_outcome. The open
    numbers are read from the section's parked question, which decisions_text wrote."""

def _design_outcome(queue, cfg, state, ledger, since, cwd, section, design: Path, problem: str,
                    lead_log: Path, result: RunResult, report: DesignReport | None) -> None:
    """Killed, non-zero exit, no report, rejected, or not approved: _park(failed_text).
    Decisions or unfiled lines: set_design_open(design) and _park(decisions_text).
    Approved with none open: set_design_open(None), mark_design_changed(sid), then _recut with
    design and rung 2. A failed rung-2 recut parks with failed_text and records no failure."""

def _recut(queue, cfg, state, ledger, since, cwd, retire_flag, section, reason, lead,
           design: Path | None = None, rung: Literal[1, 2] = 1) -> bool:
    """As now through _run (kind "recut", rung), with recut_brief(..., design). Returns True when
    the recut failed, and records nothing itself: the caller decides between _fail and _park.
    Every id it adds or keeps is marked from_recut, and design_changed too when design is set."""

def _landed(blocker: str, sections: list[Section], state: State, cwd: Path) -> bool:
    """A blocker still in the queue has landed when it is done in state or marked done in the
    queue, and git.clean on its section worktree is not False (with no worktree, done is enough).
    A blocker gone from the queue has landed when every section whose came_from names it has
    landed, or when there is no such section."""

def _wake(sections: list[Section], state: State, cwd: Path) -> None:
    """For each waiting section whose waits_on has landed: state.wake and progress.woken. No ping."""

def _wait(queue, cfg, state, sections, section, blocker: str) -> None:
    """WAITING. The blocker is unknown, is the section itself, has already landed, or waits on
    the section through waits_on or depends_on: _park with the reason. Otherwise state.wait
    and progress.section_waiting, with no ping."""
```

`_loop` changes in three places:

- `_wake` runs at the start of each pass, after the queue is parsed.
- `blocked_by` takes the parked and waiting ids together.
- With nothing runnable, the loop waits while any section is parked or waiting, as it waits on parked ones now. `progress.waiting` names them.

`_run_section` changes in five places:

- Before any agent run: over `ladder.section_cap` by `ledger.section_spend`, `_park(cap_text)`.
- A section with `design_open` and an answer runs `_design_answer`, and no lead runs.
- `RECUT` and `DESIGN` go to `_climb`. This replaces `relay/loop.py:121-129`.
- `WAITING` goes to `_wait`.
- The lead's `_run` passes the section cap to `_watcher`.

`_watcher` takes `cap: float | None`. On an event where `ledger.section_spend(sid).dollars + stream.spend.dollars > cap`, it returns `"retire"` with `progress.retiring(sid, "cap", ...)`, the same way the budget does. The next pass parks the section through the cap test.

### `relay/cli.py` (extended)

`relay go` gains `--section-dollar-cap` (float), which becomes the `section_dollar_cap` override. `relay status` prints a waiting section as `<id>  waiting on <blocker>`.

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Which rung a RECUT or DESIGN takes; one design change per lineage | `relay/ladder.py` `climb` | testing `from_recut` or `design_changed` to choose a move anywhere else; replaces `relay/loop.py:121-129` |
| Splitting problem from guess | `relay/ladder.py` `split_reason`, `GUESS` | a `" | guess: "` literal or a second split anywhere else |
| Reading the architect's report | `relay/ladder.py` `parse_report` | matching `REJECTED`, `STATUS`, `DECISIONS` or `END DESIGN` anywhere else |
| Owner text for a cap, a decision or a failed design change | `relay/ladder.py` | wording them in `loop.py` |
| The cap that applies to a section | `relay/ladder.py` `section_cap` | reading `dollar_cap` or `section_dollar_cap` anywhere else |
| The architect's brief and the owner's answer brief; the problem / guess / WAITING rule for leads | `relay/prompts.py` | brief text in `loop.py` or `ladder.py`; the guess in any brief |
| Running the architect, ledgering it | `relay/loop.py` `_run` | `run_agent` or `ledger.append` called anywhere else |
| When a design change runs, and acting on its report | `relay/loop.py` `_design_change`, `_design_answer`, `_design_outcome` | an architect run started anywhere else |
| Waking a waiting section; when a blocker has landed | `relay/loop.py` `_wake`, `_landed` | a second landed test |
| Parking with a ping | `relay/loop.py` `_park` | `state.park` called anywhere else; waiting never pings |
| Retire on budget, context or section cap | `relay/loop.py` `_watcher` | a retire decided anywhere else |
| The queue's design line, `steps:`, `cap:` | `relay/queue.py` | reading the queue file anywhere else |
| Status words | `relay/status.py` `Kind`, `TEXT_NAMES` | a status word literal list elsewhere |
| Lineage, open design, waiting | `relay/state.py` | `"waiting"` set anywhere but `wait` |
| Rung and section spend in the ledger | `relay/ledger.py` | summing a section's lines anywhere else |
| Design command, section cap default, the standing approval words | `relay/config.py` | an `"architect"` literal or the approval words anywhere else |
| Worktree cleanliness | `relay/git.py` `clean` | a `git status` argv anywhere else |
| Ladder, waiting and design progress lines | `relay/progress.py` | printing them anywhere else |
| Test fakes and fixtures | `tests/conftest.py`, `tests/fakes/fake_claude.py`, `tests/fixtures/` | an ad hoc architect stream, design file or ladder queue built inside a test file |

No role file changes. The lead learns the problem / guess form and `DESIGN` and `WAITING` from Relay's lead prompt. The architect and the divvyer take the briefs above as they stand. The list of agent files to copy to Opal gains nothing.

## Order

1. Brief form, run against the real architect. `spiker` writes the scratchpad. It copies `docs/superpowers/specs/relay-check-design.md` into a scratch git repository under `docs/superpowers/specs/`. It runs the real architect there twice on the `design_brief` form above, with the HQPTuner s4.2 problem, which names what fails, the evidence and the Order step:
   - once as designed;
   - once with an added line, `lead's guess, free to ignore: <the fix>`.

   For each run it records the report's first line and its `STATUS`, `RULINGS`, `IGNORED` and `DECISIONS` lines. It also records whether the design's text names the guessed fix.
2. Stubs. `builder` (`stub` piece) writes `relay/ladder.py`, and adds every new signature above, raise-only, to `relay/queue.py`, `relay/status.py`, `relay/state.py`, `relay/ledger.py`, `relay/config.py`, `relay/git.py`, `relay/prompts.py` and `relay/progress.py`. New fields go in with their defaults.
3. Test helpers. `test-writer` writes `tests/conftest.py`, `tests/fakes/fake_claude.py`, `tests/fixtures/ladder-queue.md`, `tests/fixtures/ladder-design.md`, `tests/fixtures/stream-architect-approved.jsonl`, `tests/fixtures/stream-architect-decision.jsonl` and `tests/fixtures/stream-architect-rejected.jsonl`.
   - `fake_cfg` gains the three config fields.
   - When argv carries `--agent <name>` and `RELAY_FAKE_SCENARIO_<NAME>` is set (upper case, `-` as `_`), `fake_claude.py` emits that scenario. This replaces the researcher-only variable.
   - The fake appends each prompt it reads to the file `RELAY_FAKE_PROMPTS` names, when that is set.
   - The ladder queue holds a head `design` line, `steps:` and `cap:` fields, and sections that depend on each other.
4. Core: red tests. `test-writer` writes `tests/test_ladder.py`, `tests/test_queue.py`, `tests/test_status.py`, `tests/test_state.py`, `tests/test_ledger.py`, `tests/test_config.py` and `tests/test_git.py`.
5. Core: build. `builder` writes `relay/ladder.py`, `relay/queue.py`, `relay/status.py`, `relay/state.py`, `relay/ledger.py`, `relay/config.py` and `relay/git.py`.
6. Prompts, progress: red tests. `test-writer` writes `tests/test_prompts.py` and `tests/test_progress.py`. The tests cover the steering rule: `design_brief` carries the problem, the steps and the evidence paths, and the guess appears nowhere in it.
7. Prompts, progress: build. `builder` writes `relay/prompts.py` and `relay/progress.py`.
8. Loop, CLI: red tests. `test-writer` writes `tests/test_loop.py` and `tests/test_cli.py`. The tests cover:
   - rung 1: a recut as now, and its ledger line;
   - rung 2 from `RECUT` on a recut section and from `DESIGN`: the architect's brief holds no guess, the divvyer is briefed with the design, the new sections run in the same `relay go`, and the `design` and `recut` ledger lines carry rung 2;
   - rung 3: a second design change in the lineage, no design line, a rejected or unapproved report, a decision parked with its recommendation and then resumed by `relay answer`, a section over its queue cap or `--section-dollar-cap`, and a mid-run retire at the cap;
   - the third failed check still parks;
   - auto-wake: `WAITING` holds the section with no ping; it wakes after the blocker is done with a clean worktree, and wakes after the blocker's recut siblings land; an unknown, self, landed or cyclic blocker parks.
9. Loop, CLI: build. `builder` writes `relay/loop.py` and `relay/cli.py`. This step comes after the check and research designs' loop steps. The step ends with the full suite green.
