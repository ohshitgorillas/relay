design docs/superpowers/specs/relay-handoff-design.md | order docs/superpowers/specs/relay-handoff-design.md | main a0ca2b7
section s1 | lead | steps: 1, 2 | size: lead: tokens: 1338146.4 seconds: 728.2 overruns: 0 refusals: 0
  s1.d1 | builder | steps: 1 | writes: relay/runner.py, relay/git.py, relay/handoff.py, relay/queue.py | size: builder: tokens: 276531.5 seconds: 145.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/handoff/docs/handoff-queue.md s1.d1
    stub
    design: docs/superpowers/specs/relay-handoff-design.md step 1
    writes: relay/runner.py, relay/git.py, relay/handoff.py, relay/queue.py
    check: uv run python -c 'import relay.runner, relay.git, relay.handoff, relay.queue'
  s1.d2 | builder | steps: 2 | writes: pyproject.toml, uv.lock | size: builder: tokens: 276531.5 seconds: 145.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/handoff/docs/handoff-queue.md s1.d2
    design: docs/superpowers/specs/relay-handoff-design.md step 2
    writes: pyproject.toml, uv.lock
    check: uv run ruff format --check .
section s2 | lead | steps: 3 | size: lead: tokens: 1338146.4 seconds: 728.2 overruns: 0 refusals: 0
  s2.d1 | test-writer | steps: 3 | writes: tests/harness.py, tests/conftest.py, tests/test_ping.py, tests/test_loop.py | size: test-writer: tokens: 628780.0 seconds: 197.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/handoff/docs/handoff-queue.md s2.d1
    port
    design: docs/superpowers/specs/relay-handoff-design.md step 3
    files: tests/harness.py, tests/conftest.py, tests/test_ping.py, tests/test_loop.py
    view: stubgen .pyi of relay/loop.py
    view: stubgen .pyi of relay/state.py
    view: stubgen .pyi of relay/ping.py
    check: uv run pytest tests/test_ping.py tests/test_loop.py
  s2.d2 | test-writer | steps: 3 | writes: tests/fakes/fake_runner.py, tests/conftest.py, tests/test_loop.py, tests/test_loop_pass.py, tests/test_loop_e2e.py | size: test-writer: tokens: 628780.0 seconds: 197.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/handoff/docs/handoff-queue.md s2.d2
    port
    design: docs/superpowers/specs/relay-handoff-design.md step 3
    files: tests/fakes/fake_runner.py, tests/conftest.py, tests/test_loop.py, tests/test_loop_pass.py, tests/test_loop_e2e.py
    view: stubgen .pyi of relay/loop.py
    view: stubgen .pyi of relay/runner.py
    view: stubgen .pyi of relay/stream.py
    view: stubgen .pyi of relay/state.py
    check: uv run pytest tests/test_loop.py tests/test_loop_pass.py tests/test_loop_e2e.py
  s2.d3 | test-writer | steps: 3 | writes: tests/test_loop.py, tests/test_loop_lead.py, tests/test_loop_e2e.py | size: test-writer: tokens: 628780.0 seconds: 197.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/handoff/docs/handoff-queue.md s2.d3
    port
    design: docs/superpowers/specs/relay-handoff-design.md step 3
    files: tests/test_loop.py, tests/test_loop_lead.py, tests/test_loop_e2e.py
    view: stubgen .pyi of relay/loop.py
    view: stubgen .pyi of relay/runner.py
    view: stubgen .pyi of relay/state.py
    check: uv run pytest tests/test_loop.py tests/test_loop_lead.py tests/test_loop_e2e.py
  s2.d4 | test-writer | steps: 3 | writes: tests/test_loop.py, tests/test_loop_status.py, tests/test_loop_e2e.py | size: test-writer: tokens: 628780.0 seconds: 197.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/handoff/docs/handoff-queue.md s2.d4
    port
    design: docs/superpowers/specs/relay-handoff-design.md step 3
    files: tests/test_loop.py, tests/test_loop_status.py, tests/test_loop_e2e.py
    view: stubgen .pyi of relay/loop.py
    view: stubgen .pyi of relay/state.py
    check: uv run pytest tests/test_loop.py tests/test_loop_status.py tests/test_loop_e2e.py
  s2.d5 | test-writer | steps: 3 | writes: tests/test_loop.py, tests/test_loop_progress.py, tests/test_loop_e2e.py | size: test-writer: tokens: 628780.0 seconds: 197.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/handoff/docs/handoff-queue.md s2.d5
    port
    design: docs/superpowers/specs/relay-handoff-design.md step 3
    files: tests/test_loop.py, tests/test_loop_progress.py, tests/test_loop_e2e.py
    view: stubgen .pyi of relay/loop.py
    view: stubgen .pyi of relay/progress.py
    check: uv run pytest tests/test_loop_pass.py tests/test_loop_lead.py tests/test_loop_status.py tests/test_loop_progress.py tests/test_loop_e2e.py tests/test_ping.py
section s3 | lead | steps: 4, 5 | size: lead: tokens: 1338146.4 seconds: 728.2 overruns: 0 refusals: 0
  s3.d1 | test-writer | steps: 4 | writes: tests/test_runner.py, tests/test_git.py | size: test-writer: tokens: 628780.0 seconds: 197.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/handoff/docs/handoff-queue.md s3.d1
    red
    design: docs/superpowers/specs/relay-handoff-design.md step 4
    behavior: Runs argv in its own process group, waits for it, and kills and reaps the group on SIGINT, SIGTERM or an exception, as run_agent does.
    view: stubgen .pyi of relay/runner.py
    behavior: stdout and stderr together, verbatim
    view: stubgen .pyi of relay/runner.py
    behavior: the nearest ancestor holding a `.git` (a file in a worktree, a dir in a main checkout), or directory itself
    view: stubgen .pyi of relay/git.py
    behavior: `git symbolic-ref --short HEAD`
    view: stubgen .pyi of relay/git.py
    behavior: `git rev-parse --short HEAD`
    view: stubgen .pyi of relay/git.py
    behavior: `git log --oneline since..HEAD`, newest first
    view: stubgen .pyi of relay/git.py
    check: uv run pytest tests/test_runner.py tests/test_git.py
  s3.d2 | builder | steps: 5 | writes: relay/runner.py, relay/git.py, relay/loop.py | size: builder: tokens: 276531.5 seconds: 145.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/handoff/docs/handoff-queue.md s3.d2
    design: docs/superpowers/specs/relay-handoff-design.md step 5
    writes: relay/runner.py, relay/git.py, relay/loop.py
    check: uv run pytest tests/test_runner.py tests/test_git.py tests/test_loop_lead.py
section s4 | lead | steps: 6, 7 | size: lead: tokens: 1338146.4 seconds: 728.2 overruns: 0 refusals: 0
  s4.d1 | test-writer | steps: 6 | writes: tests/test_queue.py, tests/test_handoff.py, tests/fixtures/ | size: test-writer: tokens: 628780.0 seconds: 197.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/handoff/docs/handoff-queue.md s4.d1
    red
    design: docs/superpowers/specs/relay-handoff-design.md step 6
    behavior: It is read from a header field `check: <command>`, and that field is taken out of `title`.
    view: stubgen .pyi of relay/queue.py
    behavior: `render` gives these parts, in this order:
    view: stubgen .pyi of relay/handoff.py
    behavior: The report verbatim, under a heading that names it the previous lead's final report.
    view: stubgen .pyi of relay/handoff.py
    behavior: When there is no report, a line saying the previous lead left none.
    view: stubgen .pyi of relay/handoff.py
    behavior: The branch, and each commit the run made.
    view: stubgen .pyi of relay/handoff.py
    behavior: Each live agent's task id, type and description, with a line saying its report never reached the lead.
    view: stubgen .pyi of relay/handoff.py
    behavior: The run log path.
    view: stubgen .pyi of relay/handoff.py
    behavior: The failed check's tail, when there is one.
    view: stubgen .pyi of relay/handoff.py
    behavior: `render` never returns an empty string.
    view: stubgen .pyi of relay/handoff.py
    check: uv run pytest tests/test_queue.py tests/test_handoff.py
  s4.d2 | builder | steps: 7 | writes: relay/queue.py, relay/handoff.py | size: builder: tokens: 276531.5 seconds: 145.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/handoff/docs/handoff-queue.md s4.d2
    design: docs/superpowers/specs/relay-handoff-design.md step 7
    writes: relay/queue.py, relay/handoff.py
    check: uv run pytest tests/test_queue.py tests/test_handoff.py
section s5 | lead | steps: 8, 9 | size: lead: tokens: 1338146.4 seconds: 728.2 overruns: 0 refusals: 0
  s5.d1 | builder | steps: 9 | writes: relay/progress.py | size: builder: tokens: 276531.5 seconds: 145.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/handoff/docs/handoff-queue.md s5.d1
    stub
    design: docs/superpowers/specs/relay-handoff-design.md step 9
    writes: relay/progress.py
    check: uv run python -c 'import relay.progress'
  s5.d2 | test-writer | steps: 8 | writes: tests/test_loop_lead.py, tests/test_loop_status.py, tests/test_loop_progress.py | size: test-writer: tokens: 628780.0 seconds: 197.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/handoff/docs/handoff-queue.md s5.d2
    red
    design: docs/superpowers/specs/relay-handoff-design.md step 8
    behavior: Step 6 records `git.head(cwd)` before the lead starts.
    view: stubgen .pyi of relay/loop.py
    behavior: Step 7 stores `handoff.render(handoff.build(...))` through `set_last_report` whenever the run has a session, so every next lead gets a handoff.
    view: stubgen .pyi of relay/loop.py
    behavior: A run with no session still leaves the old one in place.
    view: stubgen .pyi of relay/loop.py
    behavior: Step 8 DONE: when `section.check` is set, the loop first runs `runner.run_command(["/bin/sh", "-c", section.check], cwd)`.
    view: stubgen .pyi of relay/loop.py
    behavior: Any other exit counts as a failure: `record_failure`, with the check's output tail
    view: stubgen .pyi of relay/loop.py
    behavior: so the next lead starts from the failing lines.
    view: stubgen .pyi of relay/loop.py
    behavior: A section without `check` is marked done as today.
    view: stubgen .pyi of relay/loop.py
    behavior: These are the terminal lines for the section check.
    view: stubgen .pyi of relay/progress.py
    check: uv run pytest tests/test_loop_lead.py tests/test_loop_status.py tests/test_loop_progress.py
  s5.d3 | test-writer | steps: 8 | writes: tests/test_prompts.py | size: test-writer: tokens: 628780.0 seconds: 197.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/handoff/docs/handoff-queue.md s5.d3
    red
    design: docs/superpowers/specs/relay-handoff-design.md step 8
    behavior: The `report` parameter becomes `handoff`, the rendered text, set under the same heading rule.
    view: stubgen .pyi of relay/prompts.py
    behavior: The prompt names the branch and adds four contracts:
    view: stubgen .pyi of relay/prompts.py
    behavior: Commit only on that branch, in the working directory Relay started the lead in. Never switch branches, never make a worktree.
    view: stubgen .pyi of relay/prompts.py
    behavior: Never end, with any status, while a worker the lead started is still running. Wait for its report first.
    view: stubgen .pyi of relay/prompts.py
    behavior: A step's done-check runs only that step's tests.
    view: stubgen .pyi of relay/prompts.py
    behavior: Relay runs the section's full suite after DONE. The lead does not run it.
    view: stubgen .pyi of relay/prompts.py
    check: uv run pytest tests/test_prompts.py
  s5.d4 | builder | steps: 9 | writes: relay/loop.py, relay/prompts.py, relay/progress.py | size: builder: tokens: 276531.5 seconds: 145.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/handoff/docs/handoff-queue.md s5.d4
    design: docs/superpowers/specs/relay-handoff-design.md step 9
    writes: relay/loop.py, relay/prompts.py, relay/progress.py
    check: uv run pytest tests/test_loop_lead.py tests/test_loop_status.py tests/test_loop_progress.py tests/test_prompts.py
