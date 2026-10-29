Status: approved.

# Relay on Codex: briefs the architect can take, and an architect run that never parks over a crash

## Why

Every Codex role uses `codex exec`, including the architect (`relay/backends/codex.py:29`). Architect briefs use `_ruling` (`relay/prompts.py:108`); the lead's map excludes architect briefs (`relay/prompts.py:59`), and `design_of` confines designs to the specs directory (`relay/ladder.py:123`). These contracts remain in force.

The architect retries a failed or reportless run once (`relay/loop.py:633`), then hands an unusable outcome back to its lead without recording a failure (`relay/loop.py:712`). A lead repeatedly asking for DESIGN can therefore spend forever without a budget or cap. `SectionState` has lead and check failure counts but no architect count (`relay/state.py:28`). The bound must survive loop passes and process restarts while preserving the initial retry and hand-back.

`runner.run_failed` is the shared failure predicate (`relay/runner.py:39`). Two copies remain in the loop, in lead and recut handling (`relay/loop.py:172`, `relay/loop.py:764`). Architect retry classification also repeats part of outcome classification (`relay/loop.py:669`, `relay/loop.py:674`). Failure classification stays in the runner; architect outcome policy stays in the loop. `_ruling` remains the single line-normalization home in prompts (`relay/prompts.py:108`).

The decisions-on-rerun test checks only a suffix of the recorded design path (`tests/test_loop.py:4754`); it must protect the exact decision destination. The README's trial command names the obsolete backends worktree (`README.md:114`).

## Modules

### `relay/prompts.py` (changed): every architect brief line is in a legal form

```python
def _ruling(marker: str, words: str) -> str:
    """`<marker> <words>` on one line: each run of whitespace in words, newlines included,
    becomes one space. Every line of design_brief, design_retry_brief and design_answer_brief
    is built here, the `rulings` line excepted."""

def design_brief(design, queue, section, problem, evidence, approval, answers=(), code=None) -> str:
    """`rulings <design>`; one `lead new:` line: the section, its Order steps, the problem, the
    evidence paths, where the lead's code is, then `Section text: <section.body>`, all through
    _ruling; one `new:` per owner answer through _ruling; `approve: <approval>`. No other line."""

def design_retry_brief(brief: str, said: str, error: str | None) -> str:
    """`brief` with one `lead new:` line inserted before its `approve:` line: the previous run
    on this brief filed no design change, why (error set: "it failed: <error>"; else "its final
    message had no BRIEF … END DESIGN block"), its final message `said`, and: make the design
    change, or file a report saying why none is needed. Built through _ruling."""

def design_answer_brief(design, numbers, answer, approval) -> str:
    """As now; the fallback `<n>:` or `new:` line goes through _ruling."""

def lead_prompt(..., guidance: str | None = None) -> str:
    """As now. The map paragraph says: put the block verbatim in every brief you send for this
    section except an architect's; an architect brief carries only its ruling lines. The
    guidance paragraph prints `guidance` as ladder.handback_text wrote it."""
```

### `relay/ladder.py` (changed): the design path the architect can amend, the hand-back text

```python
SPECS = Path("docs/superpowers/specs")

def design_of(design_line: str | None, top: Path) -> Path | None:
    """As now, and None when the resolved path is not a `.md` file directly under top/SPECS."""

def climb(kind, s, design, sid) -> Climb:
    """As now; rung 3's text for design None: "no design to amend: the queue names no design
    file under docs/superpowers/specs/"."""

def handback_text(what: str, said: str) -> str:
    """"Relay's architect filed no design change for this section's last DESIGN or RECUT
    (<what>). Its final message, as guidance: go on with the section, or end with RECUT: if its
    cut is wrong:\n<said>"."""
```

### `relay/progress.py` (changed)

```python
def design_retrying(sid: str, what: str) -> None: ...      # "design <sid>: <what>; running the architect again"
def design_handed_back(sid: str, what: str) -> None: ...   # "design <sid>: <what>; back to the lead with the architect's message"
def design_finished(sid: str, result: RunResult, report: DesignReport | None) -> None:
    """As now; runner.run_failed(result) words "failed: <runner.error_line(result)>" in place
    of its own killed and exit cases."""
```

The progress functions live at `relay/progress.py:221` and `relay/progress.py:225`; `design_finished` uses the shared failure predicate at `relay/progress.py:194`.

### `relay/state.py` (changed): persist architect failures independently of lead failures

```python
DESIGN_FAILURE_LIMIT = 2

@dataclass
class SectionState:
    # Existing fields remain; absent fields in old JSON load with these defaults.
    design_failures: int = 0
    design_failure: str | None = None

class State:
    def record_design_failure(self, sid: str, reason: str) -> int:
        """Atomically increment design_failures and store reason; return the new count."""

    def clear_design_failures(self, sid: str) -> None:
        """Atomically clear the count and reason for this section."""

    def set_answer(self, sid: str, answer: str) -> bool:
        """Existing answer behavior; an accepted answer also clears the architect count and
        reason in the same state write. A done section still rejects an answer unchanged."""

    def mark_done(self, sid: str) -> None:
        """Existing done behavior; clear the architect count and reason in the same write."""
```

The counter counts completed unusable architect cycles, not child invocations. A cycle is the initial run plus its one permitted retry. A final killed, failed, zero-token, reportless, rejected or unapproved outcome increments it once. A successful run returning decisions, unfiled questions or approval is usable progress and clears it before the corresponding park or recut. An approval followed by a failed recut remains the recut policy's concern. Lead runs, lead retirement, guidance consumption, restarts and ordinary recuts do not clear it. Counters belong to section IDs, not the whole queue; newly cut IDs start at zero. Existing lead `failures` stays independent.

### `relay/loop.py` (changed): retry once, hand back once, then stop repeated failure

```python
def _architect(queue, cfg, state, ledger, since, cwd, retire_flag, section, design, brief,
               problem, lead_log) -> _Stop | None:
    """One run. When runner.run_failed(result) or report is None, and neither the section cap
    nor the budget is spent: progress.design_retrying, then one more run with
    design_retry_brief(brief, ladder.said(text), error_line(result) when run_failed else None).
    Return _design_outcome's stop or None."""

def _design_outcome(queue, cfg, state, ledger, since, cwd, retire_flag, section, design,
                    problem, lead_log, result, report) -> _Stop | None:
    """Decisions or unfiled lines: park with decisions_text, as now. Approved with none open:
    recut at rung 2, as now; a failed rung-2 recut parks as now. Every other outcome (run_failed,
    no report, rejected, not approved) parks nothing and records one architect cycle failure.
    Below DESIGN_FAILURE_LIMIT: set_design_open(None), set_guidance(handback_text(what, said)),
    progress.design_handed_back. At the limit: return _design_failed_stop, with no new lead.
    A usable outcome clears the architect failure count before parking or recutting.
    what: "it failed: <error_line>" | "it filed no report" | "it rejected the brief as
    steering" | "it did not approve the design"."""

def _design_failed_stop(sid: str, count: int, reason: str | None) -> _Stop:
    """ExitCode.FAILED_TWICE (5), reason 'architect failed repeatedly', detail identifying
    section, count, last failure and recovery: fix the cause, then relay answer to retry."""

def _design_change(...) -> _Stop | None: ...
def _design_answer(...) -> _Stop | None: ...
def _climb(...) -> _Stop | None: ...
def _run_section(...) -> _Stop | None: ...
```

Propagate the architect stop through both DESIGN/RECUT and answered-decision paths to `run`, whose existing stop ping and progress ending remain the only stop emission (`relay/loop.py:45`). Before launching research, lead or architect work for a runnable section, `_run_section` checks its persisted count and returns the same stop at the limit. Restarting `go` therefore spends nothing until an explicit answer clears the bound. The section stays open, with no product-choice park. Stop-file and global-budget precedence at the loop boundary remains unchanged (`relay/loop.py:69`).

Remove redundant architect outcome classification while retaining the distinction between retryable failed/reportless runs and rejected/unapproved hand-backs. Replace the lead and recut copies of run failure detection with `run_failed`; status absence and the existing idle-retirement exception remain lead-specific. Remove obsolete helpers, unreachable branches and imports made dead by this change. In prompts, retain `_ruling` as the sole normalization implementation and remove any obsolete duplicate construction reached by this cleanup; preserve all brief content and public signatures. No new prompt framework is needed.

No module is added. `relay/backends/codex.py`, `relay/runner.py` and `relay/config.py` change only if step 1 finds the cause of run 34's ending or of a judge call in them. That fix then comes back to this design as a ruling naming its home.

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| The line form of an architect brief | `relay/prompts.py` `_ruling` | duplicate normalization; free text after `approve:`; a multi-line value in a ruling line |
| Whether the queue's design can be amended | `relay/ladder.py` `design_of`, `SPECS` | a `docs/superpowers/specs` literal anywhere else |
| Whether an agent run failed, and its error line | `relay/runner.py` `run_failed`, `error_line` | copied run failure predicates at `relay/loop.py:172` and `relay/loop.py:764` |
| Retry-then-hand-back for an architect run | `relay/loop.py` `_architect`, `_design_outcome` | parking a section over a crashed, reportless, rejected or unapproved architect run |
| Architect cycle count, reason and atomic resets | `relay/state.py` | an in-memory counter in loop; reusing lead failure counts; clearing on a fresh process |
| Architect failure stop and propagation | `relay/loop.py` `_design_failed_stop` and existing `_Stop` returns | a new exception or direct ping in architect handling; launching at the persisted limit |
| Exit codes and owner stop notification | existing `relay/errors.py` `ExitCode.FAILED_TWICE`, `relay/ping.py` `stopped`, `relay/progress.py` `ended` | literal exit codes or copied ping/progress implementations |
| The hand-back text a lead gets | `relay/ladder.py` `handback_text` | guidance worded in `loop.py` or `prompts.py` |
| Map block placement rule for leads | `relay/prompts.py` `lead_prompt` | a map block in any brief Relay builds for the architect |
| Agent commands per backend | `relay/config.py` | a `claude` argv on the Codex path anywhere |

## Order

1. Evidence. `spiker` writes the scratchpad. Read `runs/33.final.txt`, `runs/34.jsonl`, `runs/34.stderr`, `ledger.jsonl` and `state.json` under `/Users/atom/.local/state/relay/Users-atom-dev-gauntlet-docs-queue.md-cfed25fb7feb4a1a/`, and the rollout `/Users/atom/.codex/sessions/2026/10/29/rollout-2026-10-29T01-00-19-01a186ac-9483-73c2-a7ef-471642e2035c.jsonl`. Record:
   - every message Codex gave the architect before its first reply (developer instructions, injected user messages, Relay's brief), and the rejection's `steers:` and `breaks:` lines;
   - the queue's `design` head line and whether its path lies under `docs/superpowers/specs/`;
   - run 34's last stdout events, the tail of its stderr, its exit and the ledger line it left;
   - which process on the Codex path, `claude-ping` and Codex hooks included, calls the Anthropic judge.
2. Stubs. `builder` (`stub` piece) writes `relay/prompts.py` (`_ruling`, `design_retry_brief`'s new signature), `relay/ladder.py` (`SPECS`, `handback_text`) and `relay/progress.py` (`design_retrying`, `design_handed_back`), raise-only.
3. Briefs, ladder, progress: red tests. `test-writer` writes `tests/test_prompts.py`, `tests/test_ladder.py` and `tests/test_progress.py`. The tests cover:
   - every line of each architect brief is `rulings `, `<n>: `, `new: `, `lead new: ` or `approve: `, with multi-line problems, answers and section text;
   - the retry reason sits in a `lead new:` line before `approve:`;
   - `design_of` is None for a design path outside `docs/superpowers/specs/`;
   - the lead prompt's map rule excludes architect briefs;
   - the new progress lines.
4. Briefs, ladder, progress: build. `builder` writes `relay/prompts.py`, `relay/ladder.py` and `relay/progress.py`.
5. Loop and Codex path: red tests. `test-writer` writes `tests/test_loop.py` and `tests/test_config.py`. The tests cover:
   - a killed, nonzero-exit or backend-error architect run reruns once with its error line in the brief, then goes back to the lead with guidance, no park, no failure;
   - a reportless run does the same;
   - a rejected or unapproved run goes back to the lead with no park;
   - decisions still park;
   - no rerun when the cap or budget is spent;
   - under backend `codex`, the lead, recut, research and design commands all start with `codex`.
6. Loop: build. `builder` writes `relay/loop.py`. The step ends with the full suite green.
7. Docs. `builder` writes `README.md`: the design change's hand-back on a failed, reportless, rejected or unapproved architect run, and the queue's `design` line naming a file under `docs/superpowers/specs/`.
8. Architect failure state stubs. `builder` writes `relay/state.py`: the two defaulted `SectionState` fields, `DESIGN_FAILURE_LIMIT`, and raise-only `State.record_design_failure` and `State.clear_design_failures` signatures. Existing methods keep their implementations until step 10. Done-check: `uv run pytest tests/test_state.py`.
9. Architect failure bound: red tests. `test-writer` writes `tests/test_state.py` and `tests/test_loop.py`, using the documented state interfaces and existing test helpers. Cover repeated architect failure on the same section without any budget or cap; the first cycle's retry and lead hand-back; the second cycle's architect-specific stop, ping and exit 5; all unusable outcomes; unchanged lead failure accounting; persistence across reopen and restart; no agent launch when restarting at the bound; explicit `relay answer` recovery; reset on usable architect progress and on completion; independent section counts; and old state without the added fields. Exercise both design requests and answered-decision handling. Preserve budget and cap stops that occur before the failure bound; replace the budget-only assumption in `tests/test_loop.py:4475` with the bounded contract. Done-check: `uv run pytest tests/test_state.py tests/test_loop.py` (new bound behaviors red before step 10).
10. Architect failure bound: build. `builder` writes `relay/state.py` and `relay/loop.py`: implement the persistent counter, reset transitions, stop propagation and restart guard above, using existing exit, ping and progress homes. Done-check: `uv run pytest tests/test_state.py tests/test_loop.py`.
11. Operator documentation. `builder` writes `README.md`: document the architect cycle limit, persistent restart refusal, successful-progress and answer resets, exit 5, and the trial command `uv run --project ~/dev/relay-wt/codex-fix relay go ~/dev/gauntlet/docs/queue.md --backend codex`. Replace the statements that budgets alone bound architect failure. Done-check: `git diff --check`.
12. Review backlog: test contract. `test-writer` writes `tests/test_loop.py`: tighten the decisions-on-rerun test so it protects the exact recorded design destination and decision state, preserving the product-choice park after the retry and the absence of a false hand-back. Done-check: `uv run pytest tests/test_loop.py -k rerun_files_decisions`.
13. Review backlog: shared helpers. `builder` writes `relay/loop.py` and `relay/prompts.py`: remove dead and duplicated code under the Modules contracts, including the copied run failure predicates, while retaining the supported brief content and retry behavior. Done-check: `uv run pytest tests/test_loop.py tests/test_prompts.py`.
