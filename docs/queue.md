design /Users/atom/dev/relay/docs/superpowers/specs/relay-loop-design.md | order /Users/atom/dev/relay/docs/superpowers/specs/relay-loop-design.md | main e9d466a
landed 6 | b8471fa
landed 7 | 0b59081
landed 8 | 7afb1a1
section s1.1 | lead | steps: 1 | size: lead: tokens: 1010049.9 seconds: 675.1 overruns: 0 refusals: 0
  s1.1.d1 | builder | steps: 1 | writes: pyproject.toml, relay/__init__.py, relay/errors.py, relay/config.py, relay/queue.py | size: builder: tokens: 339852.8 seconds: 190.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s1.1.d1
    resume d42a458d-dfda-44dd-bd05-46d347ff101d
    stub
    design: docs/superpowers/specs/relay-loop-design.md
    step: 1. Skeleton and stubs. `builder` (`stub` piece) writes `pyproject.toml` (package `relay`, console script `relay = relay.cli:main`, dev dependency `pytest`), `relay/__init__.py` and every module above, with the signatures raise-only.
    paths: pyproject.toml, relay/__init__.py, relay/errors.py, relay/config.py, relay/queue.py
    check: uv run python -c 'import relay.errors, relay.config, relay.queue'
  s1.1.d2 | builder | steps: 1 | writes: relay/state.py, relay/ledger.py, relay/stream.py, relay/runner.py | size: builder: tokens: 339852.8 seconds: 190.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s1.1.d2
    stub
    design: docs/superpowers/specs/relay-loop-design.md
    step: 1. Skeleton and stubs. `builder` (`stub` piece) writes `pyproject.toml` (package `relay`, console script `relay = relay.cli:main`, dev dependency `pytest`), `relay/__init__.py` and every module above, with the signatures raise-only.
    paths: relay/state.py, relay/ledger.py, relay/stream.py, relay/runner.py
    check: uv run python -c 'import relay.state, relay.ledger, relay.stream, relay.runner'
  s1.1.d3 | builder | steps: 1 | writes: relay/status.py, relay/prompts.py, relay/ping.py, relay/loop.py, relay/cli.py | size: builder: tokens: 339852.8 seconds: 190.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s1.1.d3
    stub
    design: docs/superpowers/specs/relay-loop-design.md
    step: 1. Skeleton and stubs. `builder` (`stub` piece) writes `pyproject.toml` (package `relay`, console script `relay = relay.cli:main`, dev dependency `pytest`), `relay/__init__.py` and every module above, with the signatures raise-only.
    paths: relay/status.py, relay/prompts.py, relay/ping.py, relay/loop.py, relay/cli.py
    check: uv run python -c 'import relay.status, relay.prompts, relay.ping, relay.loop, relay.cli'
section s1.2.1 | lead | steps: 2 | size: lead: tokens: 1014137.3 seconds: 677.4 overruns: 0 refusals: 0
  s1.2.1.d1 | test-writer | steps: 2 | writes: tests/conftest.py, tests/fakes/fake_claude.py, tests/fixtures/m2-rest-queue.md, tests/fixtures/workboard-queue.md, tests/test_helpers.py | size: test-writer: tokens: 548027.1 seconds: 164.1 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s1.2.1.d1
    resume d42a458d-dfda-44dd-bd05-46d347ff101d
    port
    design: docs/superpowers/specs/relay-loop-design.md Order 2
    files: tests/conftest.py, tests/fakes/fake_claude.py, tests/fixtures/m2-rest-queue.md, tests/fixtures/workboard-queue.md, tests/test_helpers.py
    view: stubgen .pyi of relay/config.py
section s2 | lead | steps: 3, 4 | size: lead: tokens: 971308.7 seconds: 672.0 overruns: 0 refusals: 0
  s2.d1 | test-writer | steps: 3 | writes: tests/test_config.py | size: test-writer: tokens: 553091.2 seconds: 164.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s2.d1
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 3
    behavior: `relay/errors.py`: the one place for every Relay error type and process exit code.
    view: stubgen .pyi of relay/errors.py
    behavior: `relay/config.py`: loads `~/.config/relay/config.toml` and applies CLI overrides, giving one frozen `Config`.
    view: stubgen .pyi of relay/config.py
  s2.d2 | builder | steps: 4 | writes: relay/errors.py, relay/config.py | size: builder: tokens: 358791.8 seconds: 198.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s2.d2
    design: docs/superpowers/specs/relay-loop-design.md
    step: 4. Errors and config: build. `builder` writes `relay/errors.py` and `relay/config.py`.
    paths: relay/errors.py, relay/config.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_config.py
section s3.1.1 | lead | steps: 5 | size: lead: tokens: 1033483.8 seconds: 679.8 overruns: 0 refusals: 0
  s3.1.1.d1 | test-writer | steps: 5 | writes: tests/test_queue.py | size: test-writer: tokens: 548800.6 seconds: 163.2 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s3.1.1.d1
    resume d9877a9d-6acc-4979-8d3c-f14004867d43
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 5
    behavior: False when the queue itself marks the section done
    view: stubgen .pyi of relay/queue.py
section s4.1 | lead | steps: 8a, 8b | size: lead: tokens: 1063606.3 seconds: 682.0 overruns: 0 refusals: 0
  s4.1.d1 | test-writer | steps: 8a | writes: tests/test_ledger.py | size: test-writer: tokens: 552672.8 seconds: 166.5 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/s4/docs/queue.md s4.1.d1
    resume 8100c9af-6f09-4c9b-9f34-8bf9c7dbd230
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 8a
    behavior: A corrupt or torn ledger never stops Relay and never needs a hand fix; no ledger method raises on the file's content.
    view: stubgen .pyi of relay/ledger.py
    behavior: If the file is non-empty and its last byte is not `\n`, `append` first writes `\n`, which closes off a line torn by a crash so the new entry starts on a line of its own.
    view: stubgen .pyi of relay/ledger.py
    behavior: `total`, `over` and `unreadable` treat a line as unreadable when it is not JSON, is not a JSON object, lacks `time`, `tokens` or `dollars`, or holds a `bool` or non-number in one of them.
    view: stubgen .pyi of relay/ledger.py
    behavior: An empty line is unreadable too. `total` and `over` skip unreadable lines and sum the rest.
    view: stubgen .pyi of relay/ledger.py
    behavior: 1-based numbers of the unreadable lines
    view: stubgen .pyi of relay/ledger.py
    behavior: Relay never rewrites, truncates or deletes the ledger.
    view: stubgen .pyi of relay/ledger.py
  s4.1.d2 | builder | steps: 8b | writes: relay/ledger.py | size: builder: tokens: 331697.9 seconds: 182.7 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/s4/docs/queue.md s4.1.d2
    design: docs/superpowers/specs/relay-loop-design.md
    step: 8b. Ledger recovery: build. `builder` writes `relay/ledger.py`: `append`, `total` and `over` as above, `unreadable`, and no `RelayError` raised on file content.
    paths: relay/ledger.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_ledger.py
section s5 | lead | steps: 9, 10 | size: lead: tokens: 971308.7 seconds: 672.0 overruns: 0 refusals: 0
  s5.d1 | test-writer | steps: 9 | writes: tests/test_stream.py | size: test-writer: tokens: 553091.2 seconds: 164.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s5.d1
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 9
    behavior: `relay/stream.py`: reads the `claude -p --output-format stream-json` event lines.
    view: stubgen .pyi of relay/stream.py
    behavior: latest assistant message: input + cache_creation + cache_read
    view: stubgen .pyi of relay/stream.py
    behavior: running sum of usage; dollars filled from the result event
    view: stubgen .pyi of relay/stream.py
    behavior: ignores lines that are not JSON events
    view: stubgen .pyi of relay/stream.py
  s5.d2 | test-writer | steps: 9 | writes: tests/test_runner.py | size: test-writer: tokens: 553091.2 seconds: 164.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s5.d2
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 9
    behavior: `relay/runner.py`: the one place a child process starts, streams, is killed and is reaped.
    view: stubgen .pyi of relay/runner.py
    behavior: Each child runs in its own process group (`start_new_session=True`).
    view: stubgen .pyi of relay/runner.py
    behavior: It kills by process group, then checks with `os.waitpid` and `os.kill(pid, 0)` that the child is gone.
    view: stubgen .pyi of relay/runner.py
    behavior: It also installs SIGINT and SIGTERM handlers that kill the live child group before Relay exits.
    view: stubgen .pyi of relay/runner.py
    behavior: on_event returning "retire" creates retire_flag once; "kill" kills the group.
    view: stubgen .pyi of relay/runner.py
  s5.d3 | builder | steps: 10 | writes: relay/stream.py | size: builder: tokens: 358791.8 seconds: 198.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s5.d3
    design: docs/superpowers/specs/relay-loop-design.md
    step: 10. Stream and runner: build. `builder` writes `relay/stream.py` and `relay/runner.py`.
    paths: relay/stream.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_stream.py
  s5.d4 | builder | steps: 10 | writes: relay/runner.py | size: builder: tokens: 358791.8 seconds: 198.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s5.d4
    design: docs/superpowers/specs/relay-loop-design.md
    step: 10. Stream and runner: build. `builder` writes `relay/stream.py` and `relay/runner.py`.
    paths: relay/runner.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_stream.py tests/test_runner.py
section s6 | lead | steps: 11, 12 | size: lead: tokens: 971308.7 seconds: 672.0 overruns: 0 refusals: 0
  s6.d1 | test-writer | steps: 11 | writes: tests/test_status.py, tests/test_prompts.py | size: test-writer: tokens: 553091.2 seconds: 164.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s6.d1
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 11
    behavior: `relay/status.py`: parses the lead's final status line, which is the last non-empty line of the result text.
    view: stubgen .pyi of relay/status.py
    behavior: None = no valid status line, which counts as a failure
    view: stubgen .pyi of relay/status.py
    behavior: `relay/prompts.py`: builds every text Relay sends to an agent.
    view: stubgen .pyi of relay/prompts.py
    behavior: Holds: the queue path, the section id and body verbatim,
    view: stubgen .pyi of relay/prompts.py
    behavior: The divvyer's `recut` brief for that section, carrying the lead's reason and its run log path.
    view: stubgen .pyi of relay/prompts.py
  s6.d2 | test-writer | steps: 11 | writes: tests/test_ping.py | size: test-writer: tokens: 553091.2 seconds: 164.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s6.d2
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 11
    behavior: `relay/ping.py`: the one place an owner ping is worded and sent.
    view: stubgen .pyi of relay/ping.py
    behavior: a failed ping is logged to stderr, never raised
    view: stubgen .pyi of relay/ping.py
  s6.d3 | builder | steps: 12 | writes: relay/status.py, relay/prompts.py | size: builder: tokens: 358791.8 seconds: 198.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s6.d3
    design: docs/superpowers/specs/relay-loop-design.md
    step: 12. Status, prompts and ping: build. `builder` writes `relay/status.py`, `relay/prompts.py` and `relay/ping.py`.
    paths: relay/status.py, relay/prompts.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_status.py tests/test_prompts.py
  s6.d4 | builder | steps: 12 | writes: relay/ping.py | size: builder: tokens: 358791.8 seconds: 198.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s6.d4
    design: docs/superpowers/specs/relay-loop-design.md
    step: 12. Status, prompts and ping: build. `builder` writes `relay/status.py`, `relay/prompts.py` and `relay/ping.py`.
    paths: relay/ping.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_ping.py
section s7 | lead | steps: 13 | size: lead: tokens: 971308.7 seconds: 672.0 overruns: 0 refusals: 0
  s7.d1 | test-writer | steps: 13 | writes: tests/test_loop.py | size: test-writer: tokens: 553091.2 seconds: 164.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s7.d1
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 13
    behavior: `relay/loop.py`: the state machine for one `relay go`.
    view: stubgen .pyi of relay/loop.py
    behavior: 1. If the stop file exists, stop with `STOP_FILE`.
    view: stubgen .pyi of relay/loop.py
    behavior: 2. If the ledger, summed since this `relay go` started, is over budget, stop with `BUDGET`.
    view: stubgen .pyi of relay/loop.py
    behavior: 3. Re-parse the queue. Pick the first section that is open in the queue, not `done` or `parked` in state, and not blocked by a parked section.
    view: stubgen .pyi of relay/loop.py
    behavior: 4. If no such section exists and nothing is parked, stop with `QUEUE_EMPTY`.
    view: stubgen .pyi of relay/loop.py
    behavior: 5. If no section is runnable but some are parked, wait, holding the lock: check every `poll_seconds` for the stop file (stop with `STOP_FILE`) or a `relay answer` on a parked section (start the next pass). The ping for each parked section went out when it parked; waiting sends none.
    view: stubgen .pyi of relay/loop.py
  s7.d2 | test-writer | steps: 13 | writes: tests/test_loop.py | size: test-writer: tokens: 553091.2 seconds: 164.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s7.d2
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 13
    behavior: 6. Otherwise, run a lead with `resume` set to the section's `last_session`, or else `last_session_any`. During the run, `on_event` returns:
    view: stubgen .pyi of relay/loop.py
    behavior: - `retire` once `context_tokens ≥ context_limit` or the live spend passes a budget;
    view: stubgen .pyi of relay/loop.py
    behavior: - `kill` at `hard_ceiling`.
    view: stubgen .pyi of relay/loop.py
    behavior: 7. Append the run's spend to the ledger and record its session.
    view: stubgen .pyi of relay/loop.py
    behavior: The lead and the recut run with `cwd` set to the git top level of the queue's directory.
    view: stubgen .pyi of relay/loop.py
  s7.d3 | test-writer | steps: 13 | writes: tests/test_loop.py | size: test-writer: tokens: 553091.2 seconds: 164.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s7.d3
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 13
    behavior: - DONE: `mark_done`.
    view: stubgen .pyi of relay/loop.py
    behavior: - RETIRED: run a fresh lead on the same section; this is no failure.
    view: stubgen .pyi of relay/loop.py
    behavior: - RECUT: run `recut_command` with `recut_brief`, append its spend to the ledger, and re-parse. A non-zero exit or an unchanged queue file counts as a failure of the section.
    view: stubgen .pyi of relay/loop.py
    behavior: - NEEDS-OWNER: `park`, then `ping.needs_owner`.
    view: stubgen .pyi of relay/loop.py
    behavior: - A missing status, non-zero exit or kill: `record_failure`. A second failure stops with `FAILED_TWICE`.
    view: stubgen .pyi of relay/loop.py
    behavior: After a budget-triggered retire, the pass ends with `BUDGET`. Every stop calls `ping.stopped` before returning.
    view: stubgen .pyi of relay/loop.py
  s7.d4 | test-writer | steps: 13 | writes: tests/test_cli.py | size: test-writer: tokens: 553091.2 seconds: 164.9 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s7.d4
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 13
    behavior: `relay/cli.py`: the `relay` console script.
    view: stubgen .pyi of relay/cli.py
    behavior: creates the stop file
    view: stubgen .pyi of relay/cli.py
    behavior: sets the answer, reopens the section
    view: stubgen .pyi of relay/cli.py
    behavior: `relay status` shows the rolling 7-day total (`since` = now minus 7 days) beside the all-time total.
    view: stubgen .pyi of relay/cli.py
section s8 | lead | steps: 14 | size: lead: tokens: 971308.7 seconds: 672.0 overruns: 0 refusals: 0
  s8.d1 | builder | steps: 14 | writes: relay/loop.py | size: builder: tokens: 358791.8 seconds: 198.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s8.d1
    design: docs/superpowers/specs/relay-loop-design.md
    step: 14. Loop and CLI: build. `builder` writes `relay/loop.py` and `relay/cli.py`.
    paths: relay/loop.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_loop.py
  s8.d2 | builder | steps: 14 | writes: relay/cli.py | size: builder: tokens: 358791.8 seconds: 198.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s8.d2
    design: docs/superpowers/specs/relay-loop-design.md
    step: 14. Loop and CLI: build. `builder` writes `relay/loop.py` and `relay/cli.py`.
    paths: relay/cli.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_loop.py tests/test_cli.py
