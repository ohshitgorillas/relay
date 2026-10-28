design /Users/atom/dev/relay-wt/progress/docs/superpowers/specs/relay-progress-design.md | order /Users/atom/dev/relay-wt/progress/docs/superpowers/specs/relay-progress-design.md | main 935a90e
section s1 | lead | steps: 1, 2 | size: lead: tokens: 1080209.0 seconds: 684.7 overruns: 0 refusals: 0
  s1.d1 | builder | steps: 1 | writes: relay/progress.py | size: builder: tokens: 312692.0 seconds: 170.3 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/progress/docs/progress-queue.md s1.d1
    stub
    design: docs/superpowers/specs/relay-progress-design.md
    step: 1. Progress stub. `builder` (`stub` piece) writes `relay/progress.py` with every signature above raise-only.
    paths: relay/progress.py
    check: uv run python -c 'import relay.progress'
  s1.d2 | test-writer | steps: 2 | writes: tests/test_progress.py | size: test-writer: tokens: 564157.2 seconds: 168.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/progress/docs/progress-queue.md s1.d2
    red
    design: docs/superpowers/specs/relay-progress-design.md Order 2
    behavior: `relay/progress.py`: the one place a `relay go` progress line is worded and written.
    view: stubgen .pyi of relay/progress.py
    behavior: Each line goes to `sys.stdout`, flushed at once
    view: stubgen .pyi of relay/progress.py
    behavior: Each function writes exactly one line.
    view: stubgen .pyi of relay/progress.py
    behavior: A question or reason is cut to its first line
    view: stubgen .pyi of relay/progress.py
    behavior: a closed terminal never stops the loop.
    view: stubgen .pyi of relay/progress.py
    behavior: def started(queue: Path, cfg: Config) -> None: ...
    view: stubgen .pyi of relay/progress.py
    behavior: def lead_started(sid: str, resume: str | None, answered: bool) -> None: ...
    view: stubgen .pyi of relay/progress.py
    behavior: def lead_finished(sid: str, result: RunResult, status: LeadStatus | None) -> None: ...
    view: stubgen .pyi of relay/progress.py
    behavior: def retiring(sid: str, why: Literal["context", "budget"], tokens: int) -> None: ...
    view: stubgen .pyi of relay/progress.py
    behavior: def killing(sid: str, tokens: int) -> None: ...
    view: stubgen .pyi of relay/progress.py
  s1.d3 | test-writer | steps: 2 | writes: tests/test_progress.py | size: test-writer: tokens: 564157.2 seconds: 168.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/progress/docs/progress-queue.md s1.d3
    red
    design: docs/superpowers/specs/relay-progress-design.md Order 2
    behavior: def recut_started(sid: str, reason: str) -> None: ...
    view: stubgen .pyi of relay/progress.py
    behavior: def recut_finished(sid: str, result: RunResult, changed: bool) -> None: ...
    view: stubgen .pyi of relay/progress.py
    behavior: def needs_answer(sid: str, question: str) -> None: ...
    view: stubgen .pyi of relay/progress.py
    behavior: def failed(sid: str, failures: int) -> None: ...
    view: stubgen .pyi of relay/progress.py
    behavior: def waiting(parked: list[str]) -> None: ...
    view: stubgen .pyi of relay/progress.py
    behavior: def ended(queue: Path, code: int, reason: str, detail: str) -> None: ...
    view: stubgen .pyi of relay/progress.py
  s1.d4 | test-writer | steps: 2 | writes: tests/test_loop.py | size: test-writer: tokens: 564157.2 seconds: 168.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/progress/docs/progress-queue.md s1.d4
    red
    design: docs/superpowers/specs/relay-progress-design.md Order 2
    behavior: `relay/loop.py` calls these, and nothing else in it writes to the terminal:
    view: stubgen .pyi of relay/loop.py
    behavior: `run` calls `progress.started` after `state.lock()` succeeds, and `progress.ended` after each `ping.stopped`
    view: stubgen .pyi of relay/loop.py
    behavior: `_run_section` calls `progress.lead_started` just before `run_agent`
    view: stubgen .pyi of relay/loop.py
    behavior: On `NEEDS-OWNER` it calls `progress.needs_answer` beside `ping.needs_owner`.
    view: stubgen .pyi of relay/loop.py
    behavior: On every failure `record_failure` counts, the recut's included, it calls `progress.failed` with the new count.
    view: stubgen .pyi of relay/loop.py
  s1.d5 | test-writer | steps: 2 | writes: tests/test_loop.py | size: test-writer: tokens: 564157.2 seconds: 168.6 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/progress/docs/progress-queue.md s1.d5
    red
    design: docs/superpowers/specs/relay-progress-design.md Order 2
    behavior: `_watcher` takes the section id and calls `progress.retiring` the first time it returns `retire` in a run and `progress.killing` when it returns `kill`; it never repeats a line within one run.
    view: stubgen .pyi of relay/loop.py
    behavior: `_recut` calls `progress.recut_started` before its `run_agent` and `progress.recut_finished` after it.
    view: stubgen .pyi of relay/loop.py
    behavior: `_loop` calls `progress.waiting` when it enters a wait and the parked set differs from the set it last printed; a wait that goes on prints nothing more.
    view: stubgen .pyi of relay/loop.py
    behavior: a progress line never replaces a ping.
    view: stubgen .pyi of relay/loop.py
section s2 | lead | steps: 3 | size: lead: tokens: 1080209.0 seconds: 684.7 overruns: 0 refusals: 0
  s2.d1 | builder | steps: 3 | writes: relay/progress.py | size: builder: tokens: 312692.0 seconds: 170.3 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/progress/docs/progress-queue.md s2.d1
    design: docs/superpowers/specs/relay-progress-design.md
    step: 3. Progress lines: build. `builder` writes `relay/progress.py` and `relay/loop.py`.
    paths: relay/progress.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_progress.py
  s2.d2 | builder | steps: 3 | writes: relay/loop.py | size: builder: tokens: 312692.0 seconds: 170.3 overruns: 0 refusals: 0
    queue /Users/atom/dev/relay-wt/progress/docs/progress-queue.md s2.d2
    design: docs/superpowers/specs/relay-progress-design.md
    step: 3. Progress lines: build. `builder` writes `relay/progress.py` and `relay/loop.py`.
    paths: relay/loop.py
    check: PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -p no:cacheprovider --tb=no -rA tests/test_progress.py tests/test_loop.py
