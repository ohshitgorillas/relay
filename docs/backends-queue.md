design docs/superpowers/specs/relay-backends-design.md | order docs/superpowers/specs/relay-backends-design.md | main 26a33a7
landed 1 | cb6f8d5

section s1a | lead | steps: 2, 3, 4, 5, 6, 7 | size: calibration: remaining repairs and two shared recovery pieces; smaller than stopped s1; lead: tokens: 1360985.8 seconds: 735.3 overruns: 0 refusals: 0 | from: s1
  s1a.d1 | builder | steps: 2 | writes: relay/backends/codex_session.py | size: calibration: remaining rollout I/O repair only; builder: tokens: 273978.9 seconds: 145.0 overruns: 0 refusals: 0 | from: s1
    queue docs/backends-queue.md s1a.d1
    resume 01a185d5-6c2f-70b0-981a-608c800a30ac
    design: docs/superpowers/specs/relay-backends-design.md; Order: Codex adapter and rollout reader
    paths: relay/backends/codex_session.py
    check: uv run pytest tests/test_codex_session.py
  s1a.d2 | builder | steps: 3 | writes: relay/files.py | size: calibration: stub/red/build with s1a.d3-s1a.d4 is one commit piece | from: s1
    queue docs/backends-queue.md s1a.d2
    stub
    design: docs/superpowers/specs/relay-backends-design.md; Order: Shared atomic publication
    paths: relay/files.py
    check: uv run python -c 'import relay.files'
  s1a.d3 | test-writer | steps: 7 | writes: tests/test_files.py, tests/test_state.py, tests/test_runner.py | size: calibration: publication and existing consumers; test-writer: tokens: 626340.9 seconds: 198.6 overruns: 0 refusals: 0 | from: s1
    queue docs/backends-queue.md s1a.d3
    red
    design: docs/superpowers/specs/relay-backends-design.md; Order: Atomic publication and recovery tests
    behavior: `relay/files.py` owns atomic byte publication and temporary-file cleanup, replacing the mechanisms at `relay/runner.py:111` and `relay/state.py:75`. It creates a unique temporary file beside the destination, writes all bytes, flushes and fsyncs, closes, then replaces the destination atomically. Cleanup removes its temporary file on success or exception. Errors propagate; failed publication cannot return success. An optional permission mode lets queue recovery preserve the pre-invocation queue's mode; absent that argument, retain the existing private-file creation semantics. Serialization, state locking and recovery policy stay with the callers.
    view: stubgen .pyi of relay/files.py
    behavior: `relay/files.py` owns atomic byte publication and temporary-file cleanup, replacing the mechanisms at `relay/runner.py:111` and `relay/state.py:75`. It creates a unique temporary file beside the destination, writes all bytes, flushes and fsyncs, closes, then replaces the destination atomically. Cleanup removes its temporary file on success or exception. Errors propagate; failed publication cannot return success. An optional permission mode lets queue recovery preserve the pre-invocation queue's mode; absent that argument, retain the existing private-file creation semantics. Serialization, state locking and recovery policy stay with the callers.
    view: stubgen .pyi of relay/state.py
    behavior: Publish every telemetry snapshot through the shared atomic publication helper. Readers see the preceding complete snapshot or the new complete snapshot; interruption before replacement preserves the preceding snapshot. Runner owns snapshot serialization and publication timing for every backend. Replay reads the published snapshot and never depends on a temporary file.
    view: stubgen .pyi of relay/runner.py
  s1a.d4 | builder | steps: 3 | writes: relay/files.py, relay/runner.py, relay/state.py | size: calibration: helper and two existing consumers; builder: tokens: 273978.9 seconds: 145.0 overruns: 0 refusals: 0 | from: s1
    queue docs/backends-queue.md s1a.d4
    design: docs/superpowers/specs/relay-backends-design.md; Order: Shared atomic publication
    paths: relay/files.py, relay/runner.py, relay/state.py
    check: uv run pytest tests/test_files.py tests/test_state.py tests/test_runner.py
  s1a.d5 | test-writer | steps: 7 | writes: tests/test_loop.py | size: calibration: rollback transaction; test-writer: tokens: 626340.9 seconds: 198.6 overruns: 0 refusals: 0 | from: s1
    queue docs/backends-queue.md s1a.d5
    red
    design: docs/superpowers/specs/relay-backends-design.md; Order: Atomic publication and recovery tests
    behavior: `relay/loop.py` owns the recut transaction at `_recut` (`relay/loop.py:190`). Before invoking the divvyer, retain the queue's exact bytes and permission mode and parse the original sections. A killed invocation, nonzero exit or backend error restores those bytes through `atomic_write` before any attempt to parse the failed output, including malformed, empty or missing output. Report the failed recut with no accepted change and use the existing failure counter and second-failure return. A nominally successful invocation must yield a parseable, changed queue; malformed, empty or missing output and unchanged sections restore the original and take that same failure branch. Accept and mark recut sections only after validation. An invocation exception restores the original before re-raising; a restoration error propagates and stops the loop, never allowing a next pass over failed output. Existing budget, parking, recut-origin and failure-count branches remain intact. Relay never authors, rewrites or marks queue sections itself; this byte-for-byte rollback is its narrow restoration exception. Reflect that exception in the parser's ownership documentation and README.
    view: stubgen .pyi of relay/loop.py
  s1a.d6 | builder | steps: 4 | writes: relay/loop.py, relay/queue.py | size: calibration: rollback transaction and ownership documentation; builder: tokens: 273978.9 seconds: 145.0 overruns: 0 refusals: 0 | from: s1
    queue docs/backends-queue.md s1a.d6
    design: docs/superpowers/specs/relay-backends-design.md; Order: Failed recut recovery
    paths: relay/loop.py, relay/queue.py
    check: uv run pytest tests/test_loop.py tests/test_queue.py
  s1a.d7 | builder | steps: 5 | writes: relay/runner.py, relay/loop.py | size: calibration: remaining finalization outcome repairs only; builder: tokens: 273978.9 seconds: 145.0 overruns: 0 refusals: 0 | from: s1
    queue docs/backends-queue.md s1a.d7
    design: docs/superpowers/specs/relay-backends-design.md; Order: Runtime integration
    paths: relay/runner.py, relay/loop.py
    check: uv run pytest tests/test_runner.py tests/test_loop.py

section s1b | lead | steps: 8 | size: calibration: documentation only; lead: tokens: 1360985.8 seconds: 735.3 overruns: 0 refusals: 0 | from: s1
  s1b.d1 | builder | steps: 8 | writes: README.md | size: calibration: documentation only | from: s1
    queue docs/backends-queue.md s1b.d1
    design: docs/superpowers/specs/relay-backends-design.md; Order: User documentation
    paths: README.md
    check: uv run pytest
