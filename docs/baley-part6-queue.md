design docs/superpowers/specs/relay-ladder-design.md | order docs/superpowers/specs/relay-ladder-design.md | main 6566796
section s1 | lead | steps: 1 | size: lead: tokens: 1249071.4 seconds: 697.3 overruns: 0 refusals: 0
  s1.d1 | spiker | steps: 1 | writes: the scratchpad | size: spiker: tokens: 152837.2 seconds: 46.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s1.d1
    design: docs/superpowers/specs/relay-ladder-design.md | Order 1
section s2 | lead | steps: 2, 3, 4, 5 | size: lead: tokens: 1249071.4 seconds: 697.3 overruns: 0 refusals: 0
  s2.d1 | builder | steps: 2 | writes: relay/ladder.py, relay/queue.py, relay/status.py, relay/state.py, relay/ledger.py | size: builder: tokens: 287840.7 seconds: 151.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s2.d1
    stub
    design: docs/superpowers/specs/relay-ladder-design.md | Order 2
    paths: relay/ladder.py, relay/queue.py, relay/status.py, relay/state.py, relay/ledger.py
    check: uv run python -c "import relay.ladder, relay.queue, relay.status, relay.state, relay.ledger"
  s2.d2 | builder | steps: 2 | writes: relay/config.py, relay/git.py, relay/prompts.py, relay/progress.py | size: builder: tokens: 287840.7 seconds: 151.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s2.d2
    stub
    design: docs/superpowers/specs/relay-ladder-design.md | Order 2
    paths: relay/config.py, relay/git.py, relay/prompts.py, relay/progress.py
    check: uv run python -c "import relay.config, relay.git, relay.prompts, relay.progress"
  s2.d3 | test-writer | steps: 3 | writes: tests/fakes/fake_claude.py, tests/fixtures/ladder-design.md, tests/fixtures/stream-architect-approved.jsonl, tests/fixtures/stream-architect-decision.jsonl, tests/fixtures/stream-architect-rejected.jsonl | size: test-writer: tokens: 620607.5 seconds: 191.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s2.d3
    red
    design: docs/superpowers/specs/relay-ladder-design.md | Order 3
    behavior: When argv carries `--agent <name>` and `RELAY_FAKE_SCENARIO_<NAME>` is set (upper case, `-` as `_`), `fake_claude.py` emits that scenario. This replaces the researcher-only variable.
    view: stubgen .pyi of relay/config.py
    behavior: The fake appends each prompt it reads to the file `RELAY_FAKE_PROMPTS` names, when that is set.
    view: stubgen .pyi of relay/config.py
  s2.d4 | test-writer | steps: 3, 4 | writes: tests/fixtures/ladder-queue.md, tests/test_queue.py | size: test-writer: tokens: 620607.5 seconds: 191.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s2.d4
    red
    design: docs/superpowers/specs/relay-ladder-design.md | Order 3, 4
    behavior: The ladder queue holds a head `design` line, `steps:` and `cap:` fields, and sections that depend on each other.
    view: stubgen .pyi of relay/queue.py
    behavior: the field stays in the title as written
    view: stubgen .pyi of relay/queue.py
    behavior: removed from the title; positive
    view: stubgen .pyi of relay/queue.py
    behavior: The path after `design ` on the queue's first non-blank line, when that line starts
    view: stubgen .pyi of relay/queue.py
    behavior: `design ` and comes before the first section, up to the first ` | ` or the end of the line; None otherwise.
    view: stubgen .pyi of relay/queue.py
    behavior: A bad `cap:` value, one that is not a positive number, raises `QueueFormatError`.
    view: stubgen .pyi of relay/queue.py
  s2.d5 | test-writer | steps: 3, 4 | writes: tests/conftest.py, tests/test_config.py, tests/test_git.py | size: test-writer: tokens: 620607.5 seconds: 191.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s2.d5
    red
    design: docs/superpowers/specs/relay-ladder-design.md | Order 3, 4
    behavior: `fake_cfg` gains the three config fields.
    view: stubgen .pyi of relay/config.py
    behavior: __post_init__ and load_config as research_command's is
    view: stubgen .pyi of relay/config.py
    behavior: positive; None is no cap
    view: stubgen .pyi of relay/config.py
    behavior: the owner's words Relay quotes on the architect's approve: line
    view: stubgen .pyi of relay/config.py
    behavior: All three keys join `_KEYS`.
    view: stubgen .pyi of relay/config.py
    behavior: `git status --porcelain` in `cwd`: True on exit 0 with no output, False with output, None when git fails.
    view: stubgen .pyi of relay/git.py
  s2.d6 | test-writer | steps: 4 | writes: tests/test_ladder.py | size: test-writer: tokens: 620607.5 seconds: 191.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s2.d6
    red
    design: docs/superpowers/specs/relay-ladder-design.md | Order 4
    behavior: RECUT on a section that is neither from_recut nor design_changed: rung 1.
    view: stubgen .pyi of relay/ladder.py
    behavior: RECUT on a from_recut section, or DESIGN, when not design_changed and design is not None: rung 2.
    view: stubgen .pyi of relay/ladder.py
    behavior: design_changed: rung 3
    view: stubgen .pyi of relay/ladder.py
    behavior: design None at rung 2: rung 3
    view: stubgen .pyi of relay/ladder.py
    behavior: (problem, guess): the stripped text before the first GUESS and after it
    view: stubgen .pyi of relay/ladder.py
    behavior: The architect's report: `REJECTED: STEERING` first gives rejected=True. Otherwise the
    view: stubgen .pyi of relay/ladder.py
    behavior: last block from a line starting `BRIEF ` to the line `END DESIGN`. None when neither is found.
    view: stubgen .pyi of relay/ladder.py
    behavior: each indented line under UNFILED, as written
    view: stubgen .pyi of relay/ladder.py
    behavior: The leading <n> of each decision line, in order.
    view: stubgen .pyi of relay/ladder.py
  s2.d7 | test-writer | steps: 4 | writes: tests/test_ladder.py | size: test-writer: tokens: 620607.5 seconds: 191.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s2.d7
    red
    design: docs/superpowers/specs/relay-ladder-design.md | Order 4
    behavior: Pure: no I/O, no state writes, no git.
    view: stubgen .pyi of relay/ladder.py
    behavior: The queue head's design path (queue.queue_design), resolved against `top` when relative;
    view: stubgen .pyi of relay/ladder.py
    behavior: None when design_line is None.
    view: stubgen .pyi of relay/ladder.py
    behavior: section.dollar_cap when set, else cfg.section_dollar_cap.
    view: stubgen .pyi of relay/ladder.py
    behavior: Owner text for a cap, a decision or a failed design change
    view: stubgen .pyi of relay/ladder.py
    behavior: and unfiled line verbatim, each with its recommendation and alternative.
    view: stubgen .pyi of relay/ladder.py
  s2.d8 | test-writer | steps: 4 | writes: tests/test_status.py, tests/test_state.py | size: test-writer: tokens: 620607.5 seconds: 191.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s2.d8
    red
    design: docs/superpowers/specs/relay-ladder-design.md | Order 4
    behavior: two status words
    view: stubgen .pyi of relay/status.py
    behavior: this section had a design change, or a design-change recut made it
    view: stubgen .pyi of relay/state.py
    behavior: the design path whose product decision awaits the owner's answer
    view: stubgen .pyi of relay/state.py
    behavior: status "waiting", waits_on blocker; no question
    view: stubgen .pyi of relay/state.py
    behavior: status "open", waits_on None
    view: stubgen .pyi of relay/state.py
    behavior: `set_answer` also reopens a waiting section and clears `waits_on`. `mark_done` clears `design_open` and `waits_on`.
    view: stubgen .pyi of relay/state.py
  s2.d9 | test-writer | steps: 4 | writes: tests/test_ledger.py | size: test-writer: tokens: 620607.5 seconds: 191.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s2.d9
    red
    design: docs/superpowers/specs/relay-ladder-design.md | Order 4
    behavior: As now; a line gains "rung" only when rung is not None.
    view: stubgen .pyi of relay/ledger.py
    behavior: Every readable line whose "section" is `section`, summed, across all time.
    view: stubgen .pyi of relay/ledger.py
  s2.d10 | builder | steps: 5 | writes: relay/status.py, relay/state.py, relay/ledger.py | size: builder: tokens: 287840.7 seconds: 151.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s2.d10
    design: docs/superpowers/specs/relay-ladder-design.md | Order 5
    paths: relay/status.py, relay/state.py, relay/ledger.py
    check: uv run python -m pytest tests/test_status.py tests/test_state.py tests/test_ledger.py
  s2.d11 | builder | steps: 5 | writes: relay/config.py, relay/git.py | size: builder: tokens: 287840.7 seconds: 151.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s2.d11
    design: docs/superpowers/specs/relay-ladder-design.md | Order 5
    paths: relay/config.py, relay/git.py
    check: uv run python -m pytest tests/test_config.py tests/test_git.py
  s2.d12 | builder | steps: 5 | writes: relay/queue.py, relay/ladder.py | size: builder: tokens: 287840.7 seconds: 151.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s2.d12
    design: docs/superpowers/specs/relay-ladder-design.md | Order 5
    paths: relay/queue.py, relay/ladder.py
    check: uv run python -m pytest tests/test_queue.py tests/test_ladder.py tests/test_status.py tests/test_state.py tests/test_ledger.py tests/test_config.py tests/test_git.py
section s3 | lead | steps: 6, 7 | size: lead: tokens: 1249071.4 seconds: 697.3 overruns: 0 refusals: 0
  s3.d1 | test-writer | steps: 6 | writes: tests/test_prompts.py | size: test-writer: tokens: 620607.5 seconds: 191.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s3.d1
    red
    design: docs/superpowers/specs/relay-ladder-design.md | Order 6
    behavior: The tests cover the steering rule: `design_brief` carries the problem, the steps and the evidence paths, and the guess appears nowhere in it.
    view: stubgen .pyi of relay/prompts.py
    behavior: As now, plus a status rule. The text after RECUT: or DESIGN: is the problem: what fails,
    view: stubgen .pyi of relay/prompts.py
    behavior: its evidence, and the design step it is under. A fix the lead has in mind follows only after
    view: stubgen .pyi of relay/prompts.py
    behavior: ` | guess: `. DESIGN is for when the section's design lacks something no recut can supply.
    view: stubgen .pyi of relay/prompts.py
    behavior: WAITING: <id> is for when the section cannot go on until queue section <id> lands.
    view: stubgen .pyi of relay/prompts.py
    behavior: Three lines and nothing else:
    view: stubgen .pyi of relay/prompts.py
    behavior: `rulings <design>`. Then each answer line that starts `<n>:` with n in numbers, as written.
    view: stubgen .pyi of relay/prompts.py
    behavior: When there is none: `<n>: <answer>` when numbers has one entry, else `new: <answer>`.
    view: stubgen .pyi of relay/prompts.py
    behavior: As now, plus when design is set
    view: stubgen .pyi of relay/prompts.py
  s3.d2 | test-writer | steps: 6 | writes: tests/test_progress.py | size: test-writer: tokens: 620607.5 seconds: 191.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s3.d2
    red
    design: docs/superpowers/specs/relay-ladder-design.md | Order 6
    behavior: as now; DESIGN and WAITING show _cut(text) as RECUT does
    view: stubgen .pyi of relay/progress.py
    behavior: def retiring(sid: str, why: Literal["context", "budget", "cap"], tokens: int) -> None: ...
    view: stubgen .pyi of relay/progress.py
    behavior: def design_started(sid: str, design: Path, steps: tuple[str, ...], problem: str) -> None: ...
    view: stubgen .pyi of relay/progress.py
    behavior: def design_finished(sid: str, result: RunResult, report: DesignReport | None) -> None: ...
    view: stubgen .pyi of relay/progress.py
    behavior: def section_waiting(sid: str, blocker: str) -> None: ...
    view: stubgen .pyi of relay/progress.py
    behavior: def woken(sid: str, blocker: str) -> None: ...
    view: stubgen .pyi of relay/progress.py
    behavior: `agent_event` takes the widened `Kind`
    view: stubgen .pyi of relay/progress.py
  s3.d3 | builder | steps: 7 | writes: relay/prompts.py, relay/progress.py | size: builder: tokens: 287840.7 seconds: 151.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s3.d3
    design: docs/superpowers/specs/relay-ladder-design.md | Order 7
    paths: relay/prompts.py, relay/progress.py
    check: uv run python -m pytest tests/test_prompts.py tests/test_progress.py
section s4 | lead | steps: 8, 9 | size: lead: tokens: 1249071.4 seconds: 697.3 overruns: 0 refusals: 0
  s4.d1 | test-writer | steps: 8 | writes: tests/test_loop.py | size: test-writer: tokens: 620607.5 seconds: 191.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s4.d1
    red
    design: docs/superpowers/specs/relay-ladder-design.md | Order 8
    behavior: rung 1: a recut as now, and its ledger line;
    view: stubgen .pyi of relay/loop.py
    behavior: rung 2 from `RECUT` on a recut section and from `DESIGN`: the architect's brief holds no guess, the divvyer is briefed with the design, the new sections run in the same `relay go`, and the `design` and `recut` ledger lines carry rung 2;
    view: stubgen .pyi of relay/loop.py
  s4.d2 | builder | steps: 9 | writes: relay/loop.py | size: builder: tokens: 287840.7 seconds: 151.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s4.d2
    design: docs/superpowers/specs/relay-ladder-design.md | Order 9
    step: `RECUT` and `DESIGN` go to `_climb`. This replaces `relay/loop.py:121-129`.
    paths: relay/loop.py
    check: uv run python -m pytest tests/test_loop.py
  s4.d3 | test-writer | steps: 8 | writes: tests/test_loop.py | size: test-writer: tokens: 620607.5 seconds: 191.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s4.d3
    red
    design: docs/superpowers/specs/relay-ladder-design.md | Order 8
    behavior: rung 3: a second design change in the lineage, no design line, a rejected or unapproved report, a decision parked with its recommendation and then resumed by `relay answer`, a section over its queue cap or `--section-dollar-cap`, and a mid-run retire at the cap;
    view: stubgen .pyi of relay/loop.py
    behavior: the third failed check still parks;
    view: stubgen .pyi of relay/loop.py
  s4.d4 | builder | steps: 9 | writes: relay/loop.py | size: builder: tokens: 287840.7 seconds: 151.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s4.d4
    design: docs/superpowers/specs/relay-ladder-design.md | Order 9
    step: Before any agent run: over `ladder.section_cap` by `ledger.section_spend`, `_park(cap_text)`.
    step: A section with `design_open` and an answer runs `_design_answer`, and no lead runs.
    step: The lead's `_run` passes the section cap to `_watcher`.
    paths: relay/loop.py
    check: uv run python -m pytest tests/test_loop.py
  s4.d5 | test-writer | steps: 8 | writes: tests/test_loop.py | size: test-writer: tokens: 620607.5 seconds: 191.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s4.d5
    red
    design: docs/superpowers/specs/relay-ladder-design.md | Order 8
    behavior: auto-wake: `WAITING` holds the section with no ping; it wakes after the blocker is done with a clean worktree, and wakes after the blocker's recut siblings land; an unknown, self, landed or cyclic blocker parks.
    view: stubgen .pyi of relay/loop.py
  s4.d6 | builder | steps: 9 | writes: relay/loop.py | size: builder: tokens: 287840.7 seconds: 151.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s4.d6
    design: docs/superpowers/specs/relay-ladder-design.md | Order 9
    step: `_wake` runs at the start of each pass, after the queue is parsed.
    step: `blocked_by` takes the parked and waiting ids together.
    step: With nothing runnable, the loop waits while any section is parked or waiting, as it waits on parked ones now. `progress.waiting` names them.
    step: `WAITING` goes to `_wait`.
    paths: relay/loop.py
    check: uv run python -m pytest tests/test_loop.py
  s4.d7 | test-writer | steps: 8 | writes: tests/test_cli.py | size: test-writer: tokens: 620607.5 seconds: 191.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s4.d7
    red
    design: docs/superpowers/specs/relay-ladder-design.md | Order 8
    behavior: `relay go` gains `--section-dollar-cap` (float), which becomes the `section_dollar_cap` override.
    view: stubgen .pyi of relay/cli.py
    behavior: `relay status` prints a waiting section
    view: stubgen .pyi of relay/cli.py
  s4.d8 | builder | steps: 9 | writes: relay/cli.py | size: builder: tokens: 287840.7 seconds: 151.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a7bfdb0aa1bc23506/docs/baley-part6-queue.md s4.d8
    design: docs/superpowers/specs/relay-ladder-design.md | Order 9
    paths: relay/cli.py
    check: uv run python -m pytest
