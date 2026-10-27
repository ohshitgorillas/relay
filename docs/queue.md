design docs/superpowers/specs/relay-loop-design.md | order docs/superpowers/specs/relay-loop-design.md | main d3db7df
section s1 | lead | steps: 1, 2 | size: lead: tokens: 970572.4 seconds: 674.4 overruns: 0 refusals: 0
  s1.d1 | builder | steps: 1 | writes: pyproject.toml, relay/__init__.py, relay/errors.py, relay/config.py, relay/queue.py | size: builder: tokens: 362532.9 seconds: 201.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s1.d1
    stub
    design: docs/superpowers/specs/relay-loop-design.md
    step: 1. Skeleton and stubs. `builder` (`stub` piece) writes `pyproject.toml` (package `relay`, console script `relay = relay.cli:main`, dev dependency `pytest`), `relay/__init__.py` and every module above, with the signatures raise-only.
    paths: pyproject.toml, relay/__init__.py, relay/errors.py, relay/config.py, relay/queue.py
    check: uv run python -c 'import relay.errors, relay.config, relay.queue'
  s1.d2 | builder | steps: 1 | writes: relay/state.py, relay/ledger.py, relay/stream.py, relay/runner.py | size: builder: tokens: 362532.9 seconds: 201.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s1.d2
    stub
    design: docs/superpowers/specs/relay-loop-design.md
    step: 1. Skeleton and stubs. `builder` (`stub` piece) writes `pyproject.toml` (package `relay`, console script `relay = relay.cli:main`, dev dependency `pytest`), `relay/__init__.py` and every module above, with the signatures raise-only.
    paths: relay/state.py, relay/ledger.py, relay/stream.py, relay/runner.py
    check: uv run python -c 'import relay.state, relay.ledger, relay.stream, relay.runner'
  s1.d3 | builder | steps: 1 | writes: relay/status.py, relay/prompts.py, relay/ping.py, relay/loop.py, relay/cli.py | size: builder: tokens: 362532.9 seconds: 201.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s1.d3
    stub
    design: docs/superpowers/specs/relay-loop-design.md
    step: 1. Skeleton and stubs. `builder` (`stub` piece) writes `pyproject.toml` (package `relay`, console script `relay = relay.cli:main`, dev dependency `pytest`), `relay/__init__.py` and every module above, with the signatures raise-only.
    paths: relay/status.py, relay/prompts.py, relay/ping.py, relay/loop.py, relay/cli.py
    check: uv run python -c 'import relay.status, relay.prompts, relay.ping, relay.loop, relay.cli'
  s1.d4 | test-writer | steps: 2 | writes: tests/conftest.py, tests/fakes/fake_claude.py, tests/fixtures/ | size: test-writer: tokens: 554338.8 seconds: 164.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s1.d4
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 2
    behavior: `tests/fakes/fake_claude.py` is an executable that reads its prompt on stdin.
    view: stubgen .pyi of relay/stream.py
    behavior: `tests/fixtures/` holds queue samples in the divvyer's `.md` format.
    view: stubgen .pyi of relay/queue.py
section s2 | lead | steps: 3, 4 | size: lead: tokens: 970572.4 seconds: 674.4 overruns: 0 refusals: 0
  s2.d1 | test-writer | steps: 3 | writes: tests/test_config.py | size: test-writer: tokens: 554338.8 seconds: 164.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s2.d1
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 3
    behavior: `relay/errors.py`: the one place for every Relay error type and process exit code.
    view: stubgen .pyi of relay/errors.py
    behavior: `relay/config.py`: loads `~/.config/relay/config.toml` and applies CLI overrides, giving one frozen `Config`.
    view: stubgen .pyi of relay/config.py
  s2.d2 | builder | steps: 4 | writes: relay/errors.py, relay/config.py | size: builder: tokens: 362532.9 seconds: 201.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s2.d2
    design: docs/superpowers/specs/relay-loop-design.md
    step: 4. Errors and config: build. `builder` writes `relay/errors.py` and `relay/config.py`.
    paths: relay/errors.py, relay/config.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_config.py
section s3 | lead | steps: 5, 6 | size: lead: tokens: 970572.4 seconds: 674.4 overruns: 0 refusals: 0
  s3.d1 | test-writer | steps: 5 | writes: tests/test_queue.py | size: test-writer: tokens: 554338.8 seconds: 164.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s3.d1
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 5
    behavior: `relay/queue.py`: parses the divvyer's `.md` queue into sections.
    view: stubgen .pyi of relay/queue.py
    behavior: ids that depend, transitively, on a parked id
    view: stubgen .pyi of relay/queue.py
  s3.d2 | builder | steps: 6 | writes: relay/queue.py | size: builder: tokens: 362532.9 seconds: 201.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s3.d2
    design: docs/superpowers/specs/relay-loop-design.md
    step: 6. Queue parser: build. `builder` writes `relay/queue.py`.
    paths: relay/queue.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_queue.py
section s4 | lead | steps: 7, 8 | size: lead: tokens: 970572.4 seconds: 674.4 overruns: 0 refusals: 0
  s4.d1 | test-writer | steps: 7 | writes: tests/test_state.py | size: test-writer: tokens: 554338.8 seconds: 164.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s4.d1
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 7
    behavior: `relay/state.py`: Relay's own record for one queue, kept under `state_root/<slug of the queue's absolute path>/`. It holds per-section status, failure counts, parked questions, owner answers, the last session id per section, the stop file and the lock. Every write goes through a temp file and `os.replace`.
    view: stubgen .pyi of relay/state.py
  s4.d2 | test-writer | steps: 7 | writes: tests/test_ledger.py | size: test-writer: tokens: 554338.8 seconds: 164.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s4.d2
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 7
    behavior: `relay/ledger.py`: the spend ledger. It appends one JSON line per finished run (lead or recut) to `<state dir>/ledger.jsonl` and sums it against the budgets.
    view: stubgen .pyi of relay/ledger.py
  s4.d3 | builder | steps: 8 | writes: relay/state.py, relay/ledger.py | size: builder: tokens: 362532.9 seconds: 201.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s4.d3
    design: docs/superpowers/specs/relay-loop-design.md
    step: 8. State and ledger: build. `builder` writes `relay/state.py` and `relay/ledger.py`.
    paths: relay/state.py, relay/ledger.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_state.py tests/test_ledger.py
section s5 | lead | steps: 9, 10 | size: lead: tokens: 970572.4 seconds: 674.4 overruns: 0 refusals: 0
  s5.d1 | test-writer | steps: 9 | writes: tests/test_stream.py | size: test-writer: tokens: 554338.8 seconds: 164.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s5.d1
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 9
    behavior: `relay/stream.py`: reads the `claude -p --output-format stream-json` event lines. This is the only code that knows that schema.
    view: stubgen .pyi of relay/stream.py
  s5.d2 | test-writer | steps: 9 | writes: tests/test_runner.py | size: test-writer: tokens: 554338.8 seconds: 164.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s5.d2
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 9
    behavior: `relay/runner.py`: the one place a child process starts, streams, is killed and is reaped. Each child runs in its own process group (`start_new_session=True`). The runner records the child's PID in `<run_dir>/<n>.pid`. It kills by process group, then checks with `os.waitpid` and `os.kill(pid, 0)` that the child is gone. It also installs SIGINT and SIGTERM handlers that kill the live child group before Relay exits.
    view: stubgen .pyi of relay/runner.py
  s5.d3 | builder | steps: 10 | writes: relay/stream.py | size: builder: tokens: 362532.9 seconds: 201.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s5.d3
    design: docs/superpowers/specs/relay-loop-design.md
    step: 10. Stream and runner: build. `builder` writes `relay/stream.py` and `relay/runner.py`.
    paths: relay/stream.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_stream.py
  s5.d4 | builder | steps: 10 | writes: relay/runner.py | size: builder: tokens: 362532.9 seconds: 201.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s5.d4
    design: docs/superpowers/specs/relay-loop-design.md
    step: 10. Stream and runner: build. `builder` writes `relay/stream.py` and `relay/runner.py`.
    paths: relay/runner.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_stream.py tests/test_runner.py
section s6 | lead | steps: 11, 12 | size: lead: tokens: 970572.4 seconds: 674.4 overruns: 0 refusals: 0
  s6.d1 | test-writer | steps: 11 | writes: tests/test_status.py, tests/test_prompts.py, tests/test_ping.py | size: test-writer: tokens: 554338.8 seconds: 164.8 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s6.d1
    red
    design: docs/superpowers/specs/relay-loop-design.md Order 11
    behavior: `relay/status.py`: parses the lead's final status line, which is the last non-empty line of the result text.
    view: stubgen .pyi of relay/status.py
    behavior: `relay/prompts.py`: builds every text Relay sends to an agent.
    view: stubgen .pyi of relay/prompts.py
    behavior: `relay/ping.py`: the one place an owner ping is worded and sent.
    view: stubgen .pyi of relay/ping.py
  s6.d2 | builder | steps: 12 | writes: relay/status.py, relay/prompts.py, relay/ping.py | size: builder: tokens: 362532.9 seconds: 201.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay/docs/queue.md s6.d2
    design: docs/superpowers/specs/relay-loop-design.md
    step: 12. Status, prompts and ping: build. `builder` writes `relay/status.py`, `relay/prompts.py` and `relay/ping.py`.
    paths: relay/status.py, relay/prompts.py, relay/ping.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_status.py tests/test_prompts.py tests/test_ping.py
