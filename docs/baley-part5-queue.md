design docs/superpowers/specs/relay-research-design.md | order docs/superpowers/specs/relay-research-design.md | main c50c456
section s1 | lead | steps: 1, 2, 3, 4 | size: lead: tokens: 1169121.2 seconds: 690.4 overruns: 0 refusals: 0
  s1.d1 | builder | steps: 1 | writes: relay/research.py, relay/git.py, relay/config.py, relay/state.py, relay/ledger.py, relay/errors.py, relay/prompts.py, relay/progress.py | size: builder: tokens: 283786.8 seconds: 149.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s1.d1
    stub
    design: docs/superpowers/specs/relay-research-design.md | Order 1
    paths: relay/research.py, relay/git.py, relay/config.py, relay/state.py, relay/ledger.py, relay/errors.py, relay/prompts.py, relay/progress.py
    check: uv run python -c "import relay.research, relay.git, relay.config, relay.state, relay.ledger, relay.errors, relay.prompts, relay.progress"
  s1.d2 | test-writer | steps: 2, 3 | writes: tests/conftest.py, tests/fakes/fake_claude.py, tests/fixtures/stream-research.jsonl, tests/fixtures/stream-ask.jsonl, tests/fixtures/research-map.txt, tests/test_research.py | size: test-writer: tokens: 622486.4 seconds: 190.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s1.d2
    red
    design: docs/superpowers/specs/relay-research-design.md | Order 2, 3
    behavior: there is no block, a line fits neither form, there is no entry, or the block is over
    view: stubgen .pyi of relay/research.py
    behavior: every path an entry or link names, sorted, no repeats
    view: stubgen .pyi of relay/research.py
    behavior: absent or over cfg.map_max_chars characters.
    view: stubgen .pyi of relay/research.py
  s1.d3 | test-writer | steps: 3 | writes: tests/test_research.py | size: test-writer: tokens: 622486.4 seconds: 190.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s1.d3
    red
    design: docs/superpowers/specs/relay-research-design.md | Order 3
    behavior: making the parent directory.
    view: stubgen .pyi of relay/research.py
    behavior: None when the file is missing, unreadable, names another
    view: stubgen .pyi of relay/research.py
    behavior: section, or its body no longer parses.
    view: stubgen .pyi of relay/research.py
    behavior: True unless git.changed(cwd, m.commit, m.files) is False.
    view: stubgen .pyi of relay/research.py
    behavior: to start from the map, open a named file only at the lines it gives, and, needing more,
    view: stubgen .pyi of relay/research.py
  s1.d4 | test-writer | steps: 3 | writes: tests/test_git.py, tests/test_config.py | size: test-writer: tokens: 622486.4 seconds: 190.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s1.d4
    red
    design: docs/superpowers/specs/relay-research-design.md | Order 3
    behavior: `git rev-parse HEAD` in `cwd`; None when git fails.
    view: stubgen .pyi of relay/git.py
    behavior: False on exit 0 with no output, True on exit 0 with output, None when git fails.
    view: stubgen .pyi of relay/git.py
    behavior: Both run git through `runner.capture`. Neither raises.
    view: stubgen .pyi of relay/git.py
    behavior: All three keys join `_KEYS`.
    view: stubgen .pyi of relay/config.py
    behavior: Research command, map caps and their defaults
    view: stubgen .pyi of relay/config.py
  s1.d5 | test-writer | steps: 3 | writes: tests/test_state.py, tests/test_ledger.py | size: test-writer: tokens: 622486.4 seconds: 190.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s1.d5
    red
    design: docs/superpowers/specs/relay-research-design.md | Order 3
    behavior: Researcher session, map path, research flag, research lock; dropping the map when the section is done
    view: stubgen .pyi of relay/state.py
    behavior: `mark_done` also calls the work of `drop_map`.
    view: stubgen .pyi of relay/state.py
    behavior: Run lines with map commit and agents' tokens
    view: stubgen .pyi of relay/ledger.py
    behavior: `_parse` is unchanged, so `total`, `over`, `unreadable` and `sessions` read the new lines as they read lead lines.
    view: stubgen .pyi of relay/ledger.py
  s1.d6 | builder | steps: 4 | writes: relay/git.py, relay/config.py | size: builder: tokens: 283786.8 seconds: 149.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s1.d6
    design: docs/superpowers/specs/relay-research-design.md | Order 4
    paths: relay/git.py, relay/config.py
    check: uv run python -m pytest tests/test_git.py tests/test_config.py
  s1.d7 | builder | steps: 4 | writes: relay/state.py, relay/ledger.py | size: builder: tokens: 283786.8 seconds: 149.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s1.d7
    design: docs/superpowers/specs/relay-research-design.md | Order 4
    paths: relay/state.py, relay/ledger.py
    check: uv run python -m pytest tests/test_state.py tests/test_ledger.py
  s1.d8 | builder | steps: 4 | writes: relay/research.py, relay/errors.py | size: builder: tokens: 283786.8 seconds: 149.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s1.d8
    design: docs/superpowers/specs/relay-research-design.md | Order 4
    paths: relay/research.py, relay/errors.py
    check: uv run python -m pytest tests/test_research.py tests/test_git.py tests/test_config.py tests/test_state.py tests/test_ledger.py
section s2 | lead | steps: 5, 6 | size: lead: tokens: 1169121.2 seconds: 690.4 overruns: 0 refusals: 0
  s2.d1 | test-writer | steps: 5 | writes: tests/test_prompts.py | size: test-writer: tokens: 622486.4 seconds: 190.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s2.d1
    red
    design: docs/superpowers/specs/relay-research-design.md | Order 5
    behavior: Lead-facing map wording, research and ask briefs
    view: stubgen .pyi of relay/prompts.py
    behavior: As now, plus, when map_block is set
    view: stubgen .pyi of relay/prompts.py
    behavior: The queue path, the section id and body, the caps cfg.map_max_lines and
    view: stubgen .pyi of relay/prompts.py
    behavior: The question, the ANSWER / END ANSWER form, the cap cfg.map_max_chars, the flag rule.
    view: stubgen .pyi of relay/prompts.py
  s2.d2 | test-writer | steps: 5 | writes: tests/test_progress.py | size: test-writer: tokens: 622486.4 seconds: 190.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s2.d2
    red
    design: docs/superpowers/specs/relay-research-design.md | Order 5
    behavior: Progress lines for research
    view: stubgen .pyi of relay/progress.py
    behavior: def agent_event(who: Literal["lead", "recut", "research", "ask"], sid: str, event: Event) -> None: ...
    view: stubgen .pyi of relay/progress.py
  s2.d3 | builder | steps: 6 | writes: relay/prompts.py, relay/progress.py | size: builder: tokens: 283786.8 seconds: 149.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s2.d3
    design: docs/superpowers/specs/relay-research-design.md | Order 6
    paths: relay/prompts.py, relay/progress.py
    check: uv run python -m pytest tests/test_prompts.py tests/test_progress.py
section s3 | lead | steps: 7, 8 | size: lead: tokens: 1169121.2 seconds: 690.4 overruns: 0 refusals: 0
  s3.d1 | test-writer | steps: 7 | writes: tests/test_loop.py | size: test-writer: tokens: 622486.4 seconds: 190.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s3.d1
    red
    design: docs/superpowers/specs/relay-research-design.md | Order 7
    behavior: research before a lead, its map in the lead prompt, the lead's ledger line carrying the map commit and agents;
    view: stubgen .pyi of relay/loop.py
    behavior: no research on a `check_pending` pass;
    view: stubgen .pyi of relay/loop.py
    behavior: reuse after a retire with the mapped files unchanged, refresh after one changed, both in the section worktree;
    view: stubgen .pyi of relay/loop.py
  s3.d2 | test-writer | steps: 7 | writes: tests/test_loop.py | size: test-writer: tokens: 622486.4 seconds: 190.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s3.d2
    red
    design: docs/superpowers/specs/relay-research-design.md | Order 7
    behavior: a failed, killed or over-cap research: the lead starts without a map, no failure counted;
    view: stubgen .pyi of relay/loop.py
    behavior: the research run's own flag, the lead's flag untouched;
    view: stubgen .pyi of relay/loop.py
    behavior: the map dropped on `DONE` and on a recut that removes the section;
    view: stubgen .pyi of relay/loop.py
  s3.d3 | test-writer | steps: 7 | writes: tests/test_cli.py | size: test-writer: tokens: 622486.4 seconds: 190.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s3.d3
    red
    design: docs/superpowers/specs/relay-research-design.md | Order 7
    behavior: `relay ask`: the answer printed, the session resumed, an `ask` ledger line
    view: stubgen .pyi of relay/cli.py
    behavior: `relay ask` prints only the answer on stdout; its progress goes nowhere.
    view: stubgen .pyi of relay/cli.py
    behavior: ResearchError when the section has no research_session, the run
    view: stubgen .pyi of relay/cli.py
  s3.d4 | builder | steps: 8 | writes: relay/loop.py | size: builder: tokens: 283786.8 seconds: 149.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s3.d4
    design: docs/superpowers/specs/relay-research-design.md | Order 8
    paths: relay/loop.py
    check: uv run python -m pytest tests/test_loop.py
  s3.d5 | builder | steps: 8 | writes: relay/loop.py, relay/cli.py | size: builder: tokens: 283786.8 seconds: 149.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-ad0ce764b584e37a0/docs/baley-part5-queue.md s3.d5
    design: docs/superpowers/specs/relay-research-design.md | Order 8
    paths: relay/loop.py, relay/cli.py
    check: uv run python -m pytest
