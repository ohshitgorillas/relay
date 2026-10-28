design docs/superpowers/specs/relay-check-design.md | order docs/superpowers/specs/relay-check-design.md | main 6566796
section s1 | lead | steps: 1, 2, 3, 4 | size: lead: tokens: 1136706.6 seconds: 687.7 overruns: 0 refusals: 0
  s1.d1 | builder | steps: 1 | writes: relay/runner.py, relay/git.py | size: builder: tokens: 291159.3 seconds: 157.5 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a5622a58b2d54d4b0/docs/baley-queue.md s1.d1
    stub
    design: docs/superpowers/specs/relay-check-design.md
    step: every new signature above, raise-only. New fields go in with their defaults.
    paths: relay/runner.py, relay/git.py
    check: uv run python -c 'import relay.runner, relay.git'
  s1.d2 | test-writer | steps: 2, 3 | writes: tests/test_runner.py, tests/test_git.py, tests/conftest.py | size: test-writer: tokens: 615500.8 seconds: 188.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a5622a58b2d54d4b0/docs/baley-queue.md s1.d2
    red
    design: docs/superpowers/specs/relay-check-design.md Order steps 2, 3
    behavior: Run `/bin/sh -c command` in its own session in `cwd`, stdout and stderr both appended to
    view: stubgen .pyi of relay/runner.py
    behavior: `log`, stdin from /dev/null, with no env= so the child inherits the environment `relay go`
    view: stubgen .pyi of relay/runner.py
    behavior: started with. At `timeout` seconds kill the group with _kill_and_reap. Signal handlers as in
    view: stubgen .pyi of relay/runner.py
    behavior: Run argv in `cwd`, return (exit code, stdout)
    view: stubgen .pyi of relay/runner.py
    behavior: The worktree `git worktree list --porcelain` (run in `repo`) shows on branch
    view: stubgen .pyi of relay/git.py
    behavior: {ref: object} from `git for-each-ref --format=%(refname) %(objectname) refs/heads` in
    view: stubgen .pyi of relay/git.py
    behavior: Covers every worktree's branch, since worktrees share refs.
    view: stubgen .pyi of relay/git.py
    behavior: Both run git through `runner.capture`. Neither raises on a git failure.
    view: stubgen .pyi of relay/git.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA -vv --assert=plain tests/test_runner.py tests/test_git.py
  s1.d3 | builder | steps: 4 | writes: relay/runner.py, relay/git.py | size: builder: tokens: 291159.3 seconds: 157.5 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a5622a58b2d54d4b0/docs/baley-queue.md s1.d3
    design: docs/superpowers/specs/relay-check-design.md
    step: 4. Core: build. `builder` writes `relay/config.py`, `relay/queue.py`, `relay/runner.py`, `relay/git.py`, `relay/state.py`, `relay/ledger.py` and `relay/cli.py` (`--idle-ceiling`).
    paths: relay/runner.py, relay/git.py
    check: uv run python -m pytest tests/test_runner.py tests/test_git.py
  s1.d4 | builder | steps: 1 | writes: relay/config.py, relay/queue.py | size: builder: tokens: 291159.3 seconds: 157.5 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a5622a58b2d54d4b0/docs/baley-queue.md s1.d4
    stub
    design: docs/superpowers/specs/relay-check-design.md
    step: every new signature above, raise-only. New fields go in with their defaults.
    paths: relay/config.py, relay/queue.py
    check: uv run python -c 'import relay.config, relay.queue'
  s1.d5 | test-writer | steps: 2, 3 | writes: tests/test_config.py, tests/test_queue.py, tests/conftest.py, tests/fixtures/check-queue.md | size: test-writer: tokens: 615500.8 seconds: 188.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a5622a58b2d54d4b0/docs/baley-queue.md s1.d5
    red
    design: docs/superpowers/specs/relay-check-design.md Order steps 2, 3
    behavior: # ConfigError unless context_limit < idle_ceiling < hard_ceiling
    view: stubgen .pyi of relay/config.py
    behavior: seconds per check command
    view: stubgen .pyi of relay/config.py
    behavior: # regexes; default below; ConfigError on a pattern re.compile rejects
    view: stubgen .pyi of relay/config.py
    behavior: All three keys join `_KEYS`.
    view: stubgen .pyi of relay/config.py
    behavior: each `check:` or `done-check:` line's command, in body order,
    view: stubgen .pyi of relay/queue.py
    behavior: # leading whitespace allowed, fenced blocks skipped
    view: stubgen .pyi of relay/queue.py
    behavior: the header field `from: <id>`, removed from the title
    view: stubgen .pyi of relay/queue.py
    behavior: A `from:` id must match `_ID`. It need not name a section still in the queue.
    view: stubgen .pyi of relay/queue.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA -vv --assert=plain tests/test_config.py tests/test_queue.py
  s1.d6 | builder | steps: 4 | writes: relay/config.py, relay/queue.py, relay/cli.py | size: builder: tokens: 291159.3 seconds: 157.5 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a5622a58b2d54d4b0/docs/baley-queue.md s1.d6
    design: docs/superpowers/specs/relay-check-design.md
    step: 4. Core: build. `builder` writes `relay/config.py`, `relay/queue.py`, `relay/runner.py`, `relay/git.py`, `relay/state.py`, `relay/ledger.py` and `relay/cli.py` (`--idle-ceiling`).
    paths: relay/config.py, relay/queue.py, relay/cli.py
    check: uv run python -m pytest tests/test_config.py tests/test_queue.py
  s1.d7 | builder | steps: 1 | writes: relay/state.py, relay/ledger.py, relay/check.py | size: builder: tokens: 291159.3 seconds: 157.5 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a5622a58b2d54d4b0/docs/baley-queue.md s1.d7
    stub
    design: docs/superpowers/specs/relay-check-design.md
    step: every new signature above, raise-only. New fields go in with their defaults.
    paths: relay/state.py, relay/ledger.py, relay/check.py
    check: uv run python -c 'import relay.state, relay.ledger, relay.check'
  s1.d8 | test-writer | steps: 3 | writes: tests/test_state.py, tests/test_ledger.py | size: test-writer: tokens: 615500.8 seconds: 188.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a5622a58b2d54d4b0/docs/baley-queue.md s1.d8
    red
    design: docs/superpowers/specs/relay-check-design.md Order step 3
    behavior: failed checks (verdict "fail"); never counts toward FAILURE_LIMIT
    view: stubgen .pyi of relay/state.py
    behavior: +1, sets check_feedback, returns the count
    view: stubgen .pyi of relay/state.py
    behavior: `mark_done` also clears `check_feedback` and `check_pending`. `set_answer` leaves `check_pending` as it is.
    view: stubgen .pyi of relay/state.py
    behavior: Written as append writes.
    view: stubgen .pyi of relay/ledger.py
    behavior: so `total`, `over` and `unreadable` read check lines unchanged.
    view: stubgen .pyi of relay/ledger.py
    behavior: `sessions()` skips them because their session is null.
    view: stubgen .pyi of relay/ledger.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA -vv --assert=plain tests/test_state.py tests/test_ledger.py
  s1.d9 | builder | steps: 4 | writes: relay/state.py, relay/ledger.py | size: builder: tokens: 291159.3 seconds: 157.5 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a5622a58b2d54d4b0/docs/baley-queue.md s1.d9
    design: docs/superpowers/specs/relay-check-design.md
    step: 4. Core: build. `builder` writes `relay/config.py`, `relay/queue.py`, `relay/runner.py`, `relay/git.py`, `relay/state.py`, `relay/ledger.py` and `relay/cli.py` (`--idle-ceiling`).
    paths: relay/state.py, relay/ledger.py
    check: uv run python -m pytest tests/test_state.py tests/test_ledger.py
section s2 | lead | steps: 5, 6 | size: lead: tokens: 1136706.6 seconds: 687.7 overruns: 0 refusals: 0
  s2.d1 | builder | steps: 5 | writes: relay/prompts.py, relay/progress.py | size: builder: tokens: 291159.3 seconds: 157.5 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a5622a58b2d54d4b0/docs/baley-queue.md s2.d1
    stub
    design: docs/superpowers/specs/relay-check-design.md
    step: every new signature above, raise-only. New fields go in with their defaults.
    paths: relay/prompts.py, relay/progress.py
    check: uv run python -c 'import relay.prompts, relay.progress'
  s2.d2 | test-writer | steps: 5 | writes: tests/test_check.py, tests/test_prompts.py, tests/test_progress.py | size: test-writer: tokens: 615500.8 seconds: 188.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a5622a58b2d54d4b0/docs/baley-queue.md s2.d2
    red
    design: docs/superpowers/specs/relay-check-design.md Order step 5
    behavior: Run each of section.checks in order in `cwd` through runner.run_command, appending all
    view: stubgen .pyi of relay/check.py
    behavior: output to `log`, and stop at the first non-zero exit.
    view: stubgen .pyi of relay/check.py
    behavior: or any pattern in cfg.check_outside matches tail
    view: stubgen .pyi of relay/check.py
    behavior: the end of that command's output, TAIL_LINES / TAIL_CHARS
    view: stubgen .pyi of relay/check.py
    behavior: The question parked for the owner and pinged: the command,
    view: stubgen .pyi of relay/check.py
    behavior: As now, plus, when check_feedback is set:
    view: stubgen .pyi of relay/prompts.py
    behavior: the log path and the tail, for the lead.
    view: stubgen .pyi of relay/prompts.py
    behavior: Progress lines for checks and idle retire
    view: stubgen .pyi of relay/progress.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA -vv --assert=plain tests/test_check.py tests/test_prompts.py tests/test_progress.py
  s2.d3 | builder | steps: 6 | writes: relay/check.py, relay/prompts.py, relay/progress.py | size: builder: tokens: 291159.3 seconds: 157.5 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/.claude/worktrees/agent-a5622a58b2d54d4b0/docs/baley-queue.md s2.d3
    design: docs/superpowers/specs/relay-check-design.md
    step: 6. Check, prompts, progress: build. `builder` writes `relay/check.py`, `relay/prompts.py` and `relay/progress.py`.
    paths: relay/check.py, relay/prompts.py, relay/progress.py
    check: uv run python -m pytest tests/test_check.py tests/test_prompts.py tests/test_progress.py
