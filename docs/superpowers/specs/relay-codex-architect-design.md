Status: approved.

# Relay on Codex: briefs the architect can take, and an architect run that never parks over a crash

## Why

Under `--backend codex`, every role runs through `codex exec` (`relay/backends/codex.py:29-68`), the architect included (`relay/backends/codex.py:32`, `relay/config.py:74-77`). Relay's architect path has three defects in the tree and two causes no one has measured yet.

**Briefs that are not legal line by line.** The architect takes only `rulings <path>`, `<n>:`, `new:`, `lead <n>:`, `lead new:` and `approve:` lines. It ignores every other line as steering, and it rejects the brief outright when no legal line is left. Relay builds three architect briefs, and two of them carry lines in no legal form:
- `design_brief` (`relay/prompts.py:107-139`) appends the section's text as free lines after `approve:` (`relay/prompts.py:138`). Any owner answer that spans several lines becomes one `new:` line and then bare lines (`relay/prompts.py:131`).
- `design_retry_brief` (`relay/prompts.py:142-151`) gives its whole reason for the rerun as free prose after `approve:`. The architect ignores it, so the rerun is the first run again.
- `design_answer_brief` (`relay/prompts.py:154-163`) keeps only the numbered lines. Its fallback puts a multi-line answer on a single line in the same broken way.
- Nothing checks that the `rulings` path is a design file under `docs/superpowers/specs/`. `design_of` joins any queue head path onto the top (`relay/ladder.py:117-122`). A path outside that directory leaves the architect nothing legal, so every brief on it is rejected, the answer brief included.

The lead prompt also orders the map block into "every brief ... the architect's included" (`relay/prompts.py:63`). The map's rule paragraph and lines (`relay/research.py:112-119`) are in no legal form.

**A crashed architect parks the section.** A killed run, a nonzero exit or a backend error parks with `failed_text` (`relay/loop.py:693-698`, `relay/loop.py:723`). Only a clean run with no report is rerun and then handed back to the lead (`relay/loop.py:633-639`, `relay/loop.py:699-703`). Rejected and unapproved outcomes park too (`relay/loop.py:704-705`, `relay/loop.py:712-713`).

**Copies of the run-failure test.** `runner.run_failed` (`relay/runner.py:39-46`) is the one home. The architect path tests `killed`, `exit_code` and `is_error` itself twice, in `_no_report` (`relay/loop.py:667-669`) and in `_design_outcome` (`relay/loop.py:693-698`). `progress.design_finished` (`relay/progress.py:207-215`) words the same three cases. That makes 2 copies in the loop and 1 in progress.

**Unmeasured.**
- Why s2's architect rejected both briefs. The brief's evidence files lie outside this repository, so no one here has read them.
- How architect run 34 ended.
- What still calls the Anthropic judge. No code in this repository calls an Anthropic API or a judge (`grep -rni "judge\|anthropic" relay` matches only `relay/check.py:1`, `relay/check.py:50`, the word "judges"). Under Codex, every agent command Relay builds is `codex` (`relay/config.py:193-196`, `relay/config.py:74-77`). The one other command is the owner's ping tool, `claude-ping` (`relay/config.py:220`). Step 1 records what that tool and Codex's hooks call.

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

These replace `design_no_report` (`relay/progress.py:200-204`).

### `relay/loop.py` (changed): an architect run retries once, then hands back

```python
def _architect(queue, cfg, state, ledger, since, cwd, retire_flag, section, design, brief,
               problem, lead_log) -> None:
    """One run. When runner.run_failed(result) or report is None, and neither the section cap
    nor the budget is spent: progress.design_retrying, then one more run with
    design_retry_brief(brief, ladder.said(text), error_line(result) when run_failed else None).
    Then _design_outcome."""

def _design_outcome(queue, cfg, state, ledger, since, cwd, retire_flag, section, design,
                    problem, lead_log, result, report) -> None:
    """Decisions or unfiled lines: park with decisions_text, as now. Approved with none open:
    recut at rung 2, as now; a failed rung-2 recut parks as now. Every other outcome (run_failed,
    no report, rejected, not approved) parks nothing and records no failure:
    set_design_open(None), set_guidance(handback_text(what, said)), progress.design_handed_back.
    what: "it failed: <error_line>" | "it filed no report" | "it rejected the brief as
    steering" | "it did not approve the design"."""
```

`_no_report` (`relay/loop.py:667-669`) is removed. The outcome tests at `relay/loop.py:693-698` read `runner.run_failed` and `runner.error_line`.

No module is added. `relay/backends/codex.py`, `relay/runner.py` and `relay/config.py` change only if step 1 finds the cause of run 34's ending or of a judge call in them. That fix then comes back to this design as a ruling naming its home.

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| The line form of an architect brief | `relay/prompts.py` `_ruling` | an architect brief line built without it; free text after `approve:`; a multi-line value in a ruling line; replaces `relay/prompts.py:138`, `relay/prompts.py:146-151`, `relay/prompts.py:131` |
| Whether the queue's design can be amended | `relay/ladder.py` `design_of`, `SPECS` | a `docs/superpowers/specs` literal anywhere else |
| Whether an agent run failed, and its error line | `relay/runner.py` `run_failed`, `error_line` | testing `killed`, `exit_code` or `is_error` to judge a run; replaces `relay/loop.py:667-669`, `relay/loop.py:693-698`, `relay/progress.py:208-211` |
| Retry-then-hand-back for an architect run | `relay/loop.py` `_architect`, `_design_outcome` | parking a section over a crashed, reportless, rejected or unapproved architect run |
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
