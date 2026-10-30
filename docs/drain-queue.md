design docs/superpowers/specs/relay-drain-design.md | order docs/superpowers/specs/relay-drain-design.md | main 544fd92
section s1 | lead | steps: 1, 2 | size: calibration: one remaining builder dispatch; inherit completed runner red tests and state implementation; verify returned checks, review both steps, run gates and commit
  s1.d3 | builder | steps: 1 | writes: relay/runner.py, relay/errors.py | size: builder: tokens: 277430.9 seconds: 146.1 overruns: 0 refusals: 0
    queue docs/drain-queue.md s1.d3
    resume 01a18adb-4094-7221-8f68-4f80052ffb60
    design: docs/superpowers/specs/relay-drain-design.md
    step: 1
    paths: relay/runner.py, relay/errors.py
    check: uv run python -m pytest -q tests/test_runner.py
section s2 | lead | steps: 3 | size: calibration: inherit committed implementation 8935c7d and returned code and test review rounds; complete post-preparation boundary red coverage and finding fix, independently verify, run gates and commit
  s2.d5 | test-writer | steps: 3 | writes: tests/test_loop.py, tests/harness.py, tests/fakes/fake_claude.py | size: calibration: remaining post-blocking dispatch boundaries and input preservation only; test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/drain-queue.md s2.d5
    resume 01a18b0d-3c51-7453-b404-d69c823b2085
    red
    design: docs/superpowers/specs/relay-drain-design.md, Order step 3
    behavior: A signal that lands after the final boundary check and before the child starts lets that child start; it is then the running agent and finishes and is recorded as above. Blocking preparation, including waiting for the researcher lock, is outside this window and requires a fresh check afterward. Place blocking preparation before consumption of dispatch inputs where possible; if a later check holds back already-consumed work, retain its input or restore its pending record before returning drained. No answer, guidance, feedback or pending dispatch is lost. Every same-cause dispatch path follows this rule.
    view: stubgen .pyi of relay/loop.py
  s2.d6 | builder | steps: 3 | writes: relay/loop.py | size: calibration: remaining post-blocking boundary finding fix and explicit switch threading only; builder: tokens: 277430.9 seconds: 146.1 overruns: 0 refusals: 0
    queue docs/drain-queue.md s2.d6
    design: docs/superpowers/specs/relay-drain-design.md
    step: 3
    paths: relay/loop.py
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
