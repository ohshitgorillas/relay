design docs/superpowers/specs/relay-drain-design.md | order docs/superpowers/specs/relay-drain-design.md | main 544fd92
section s1 | lead | steps: 1, 2 | size: calibration: one remaining builder dispatch; inherit completed runner red tests and state implementation; verify returned checks, review both steps, run gates and commit
  s1.d3 | builder | steps: 1 | writes: relay/runner.py, relay/errors.py | size: builder: tokens: 277430.9 seconds: 146.1 overruns: 0 refusals: 0
    queue docs/drain-queue.md s1.d3
    resume 01a18adb-4094-7221-8f68-4f80052ffb60
    design: docs/superpowers/specs/relay-drain-design.md
    step: 1
    paths: relay/runner.py, relay/errors.py
    check: uv run python -m pytest -q tests/test_runner.py
section s2 | lead | steps: 3 | size: lead: tokens: 1390669.3 seconds: 741.1 overruns: 0 refusals: 0
  s2.d1 | builder | steps: 3 | writes: relay/loop.py, relay/progress.py | size: builder: tokens: 277430.9 seconds: 146.1 overruns: 0 refusals: 0
    queue docs/drain-queue.md s2.d1
    stub
    design: docs/superpowers/specs/relay-drain-design.md
    step: 3
    paths: relay/loop.py, relay/progress.py
    check: uv run python -c 'import relay.loop, relay.progress'
  s2.d2 | test-writer | steps: 3 | writes: tests/test_loop.py, tests/harness.py, tests/fakes/fake_claude.py | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/drain-queue.md s2.d2
    red
    design: docs/superpowers/specs/relay-drain-design.md, Order step 3
    behavior: `run` wraps the whole run in `drain_armed(on_request)`, entered before `state.lock()`. After the lock it calls `state.publish_run(os.getpid())`, and in a `finally` it calls `state.clear_run()`. `on_request` calls `state.mark_draining()` and `progress.draining()`. `publish_run` follows `state.lock()` directly, so a stale `run.json`, left only by a run that was SIGKILLed, is overwritten before anything is dispatched; a new run always starts not draining, and a drain leaves nothing behind that a restart obeys except the `Pending` records it set. The switch is threaded to `_loop` and `_run_section` and read at these boundaries, and only there:
    view: stubgen .pyi of relay/loop.py
    behavior: | Top of each pass, before the stop file | `relay/loop.py:70` | return `_drained()` |
    view: stubgen .pyi of relay/loop.py
    behavior: | Parked or waiting wait | `relay/loop.py:93` | `drain.pause(cfg.poll_seconds)` replaces `time.sleep`; the next pass top returns `_drained()` |
    view: stubgen .pyi of relay/loop.py
    behavior: | After the cap and architect-failure checks, before a pending dispatch, the design-answer `take_answer` or research | `relay/loop.py:121` | return `_drained()` |
    view: stubgen .pyi of relay/loop.py
    behavior: | After research, before `take_answer`, `take_check_feedback`, `take_guidance` and the lead | `relay/loop.py:130-150` | return `_drained()`; nothing has been taken |
    view: stubgen .pyi of relay/loop.py
    behavior: `relay/progress.py`: `draining()` prints
    view: stubgen .pyi of relay/progress.py
    check: uv run python -m pytest -q tests/test_loop.py
  s2.d3 | test-writer | steps: 3 | writes: tests/test_loop.py, tests/harness.py, tests/fakes/fake_claude.py | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/drain-queue.md s2.d3
    red
    design: docs/superpowers/specs/relay-drain-design.md, Order step 3
    behavior: | Lead `RECUT`/`DESIGN`, before `_climb` | `relay/loop.py:185` | `set_pending(climb)`, return `_drained()` |
    view: stubgen .pyi of relay/loop.py
    behavior: | Architect failed or reportless, before the retry | `relay/loop.py:666` | `set_pending(design-retry)` with the built retry brief, return `_drained()` |
    view: stubgen .pyi of relay/loop.py
    behavior: | Architect approved, before the rung-2 recut | `relay/loop.py:747` | `set_pending(design-recut)` after `set_design_open(None)` and `mark_design_changed`, return `_drained()` |
    view: stubgen .pyi of relay/loop.py
    behavior: Everything the finished child's result causes without starting an agent runs as it does now: the ledger line, last session, report and log, failure counts, `DONE`'s checks, `WAITING`, `NEEDS-OWNER` and rung-3 parks, pings. A section stop the finishing work returns (`FAILED_TWICE`, `BUDGET`) is returned as is; otherwise the next boundary returns `_drained()`. A drain never retires or kills the running child; its watcher keeps its usual limits.
    view: stubgen .pyi of relay/loop.py
    behavior: `_run_section` takes a section's `Pending` at `relay/loop.py:121`, after that boundary and before the design-answer branch, and runs `_resume_pending` in place of research and a lead. The over-cap and failure checks in `_design_change` and `_architect` still apply inside it.
    view: stubgen .pyi of relay/loop.py
    behavior: A signal that lands after a boundary's check and before the child starts lets that child start; it is then the running agent and finishes and is recorded as above. No state is taken without its dispatch following, so the window loses nothing.
    view: stubgen .pyi of relay/loop.py
    check: uv run python -m pytest -q tests/test_loop.py
  s2.d4 | builder | steps: 3 | writes: relay/loop.py, relay/progress.py | size: builder: tokens: 277430.9 seconds: 146.1 overruns: 0 refusals: 0
    queue docs/drain-queue.md s2.d4
    design: docs/superpowers/specs/relay-drain-design.md
    step: 3
    paths: relay/loop.py, relay/progress.py
    check: uv run python -m pytest -q tests/test_loop.py
section s3 | lead | steps: 4, 5 | size: lead: tokens: 1390669.3 seconds: 741.1 overruns: 0 refusals: 0
  s3.d1 | test-writer | steps: 4 | writes: tests/test_cli.py | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/drain-queue.md s3.d1
    red
    design: docs/superpowers/specs/relay-drain-design.md, Order step 4
    behavior: `relay/cli.py`: `_stop` calls `state.live_run()`; with a live run whose pid is not its own it calls `runner.signal_drain(pid)` and touches no stop file; with none it touches `STOP` as now.
    view: stubgen .pyi of relay/cli.py
    behavior: A second `relay stop` on a draining run sends the second SIGTERM and stops it at once.
    view: stubgen .pyi of relay/cli.py
    behavior: as its first line when `live_run()` says draining, and nothing new otherwise.
    view: stubgen .pyi of relay/cli.py
    check: uv run python -m pytest -q tests/test_cli.py
  s3.d2 | builder | steps: 4 | writes: relay/cli.py | size: builder: tokens: 277430.9 seconds: 146.1 overruns: 0 refusals: 0
    queue docs/drain-queue.md s3.d2
    design: docs/superpowers/specs/relay-drain-design.md
    step: 4
    paths: relay/cli.py
    check: uv run python -m pytest -q tests/test_cli.py
  s3.d3 | builder | steps: 5 | writes: README.md | size: builder: tokens: 277430.9 seconds: 146.1 overruns: 0 refusals: 0
    queue docs/drain-queue.md s3.d3
    design: docs/superpowers/specs/relay-drain-design.md
    step: 5
    paths: README.md
    check: grep -n -e 'run.json' -e 'drain' README.md
