Status: approved.

# Relay graceful drain

## Why

A running `relay go` has two ways to stop, and neither lets the work in hand finish under the run's control:

- Ctrl-C or SIGTERM: `_group_guard` (`relay/runner.py:348`) kills the live child's group and re-raises the signal (`relay/runner.py:355-358`). Every child Relay starts runs under it (`relay/runner.py:260`, `relay/runner.py:377`, `relay/runner.py:399`), so the interrupted lead's result is never recorded.
- The stop file: `relay stop` touches `STOP` (`relay/cli.py:73-76`), and the loop reads it only at the top of a pass (`relay/loop.py:70-71`). A pass can run research, a lead, checks, a recut and up to two architect runs (`relay/loop.py:127`, `relay/loop.py:185`, `relay/loop.py:539`, `relay/loop.py:656`, `relay/loop.py:666`, `relay/loop.py:747`), so a stop waits on all of them.

Nothing records that a run is live or stopping: the lock (`relay/state.py:80-90`) holds no PID, and `relay status` (`relay/cli.py:132-156`) prints only section states. The `_group_guard` is the only signal handler in the tree; `signal` and `os.kill` appear nowhere else in `relay/`. The parked-section wait sleeps `poll_seconds` in one call (`relay/loop.py:93`).

Relay runs one child at a time. A lead's own workers run inside that child's process group, so "every running agent" is the one live child and the subagents it spawned.

## Modules

`relay/runner.py`: keeps every signal decision. It gains the run's drain switch: the first SIGTERM to an armed `relay go` sets it and kills nothing; a second SIGTERM, or any SIGINT, takes today's path.

```python
class DrainSwitch:
    """Set once by the first SIGTERM while armed; read by the loop at each dispatch boundary."""
    @property
    def requested(self) -> bool: ...
    def pause(self, seconds: float) -> None:
        """Sleep up to `seconds` in slices of at most 0.5 s, returning early once requested."""

@contextmanager
def drain_armed(on_request: Callable[[], None]) -> Iterator[DrainSwitch]:
    """Arm the run's SIGTERM handler for one `relay go`; restore the previous handler on exit.

    First SIGTERM: set the switch, call `on_request` once, return. Second SIGTERM: raise
    KeyboardInterrupt, so the run unwinds exactly as Ctrl-C does. SIGINT is not touched.
    Off the main thread it installs nothing and yields a switch that never sets."""

def signal_drain(pid: int) -> None:
    """Send SIGTERM to `pid`; ProcessLookupError is swallowed. The one `os.kill` `relay stop` uses."""
```

`_group_guard`'s `on_signal` first asks the armed switch whether this signal only starts a drain (SIGTERM, armed, not yet set). If it does, the switch is set and the handler returns without killing or re-raising. Otherwise it kills the group and re-raises as now; the re-raise of a second SIGTERM reaches the `drain_armed` handler, which raises KeyboardInterrupt. A signal arriving inside `_signals_deferred` is handled at the block's end, as today.

`relay/state.py`: gains the live-run record and the per-section pending dispatch.

```python
@dataclass(frozen=True)
class LiveRun:
    pid: int
    draining: bool
    draining_since: float | None

@dataclass(frozen=True)
class Pending:
    """A dispatch a drain held back after the result it follows was recorded."""
    kind: Literal["climb", "design-retry", "design-recut"]
    lead_log: str
    problem: str
    status: Literal["RECUT", "DESIGN"] | None = None   # climb: the lead's status word
    text: str | None = None                            # climb: the status text as the lead gave it
    design: str | None = None                          # design-retry, design-recut
    brief: str | None = None                           # design-retry: the retry brief, built

class State:
    @property
    def run_record(self) -> Path: ...                  # <dir>/run.json
    def publish_run(self, pid: int) -> None: ...       # atomic; draining False; called with the lock held
    def mark_draining(self) -> None: ...               # atomic; draining True, draining_since now
    def clear_run(self) -> None: ...                   # unlink run.json
    def live_run(self) -> LiveRun | None:
        """The record of the `relay go` holding the lock; None when the lock is free (probed with
        a non-blocking flock on a fresh handle, released at once) or the record is missing or
        unreadable."""
    def set_pending(self, sid: str, pending: Pending) -> None: ...
    def take_pending(self, sid: str) -> Pending | None: ...
```

`SectionState` gains `pending: dict | None = None`; records written before it load as `None`.

`relay/loop.py`: owns the dispatch boundaries, the deferral of follow-up dispatches and the drained stop.

```python
def _drained() -> _Stop:
    """(ExitCode.DRAINED, "drained", "a drain was requested; running work finished and was recorded")"""

def _resume_pending(
    queue: Path, cfg: Config, state: State, ledger: Ledger, since: float, cwd: Path,
    retire_flag: Path, section: Section, pending: Pending,
) -> _Stop | None:
    """Run the held-back dispatch: climb -> _climb; design-retry -> the retry run then
    _design_outcome; design-recut -> the rung-2 _recut, parking with ladder.failed_text on failure."""
```

`run` wraps the whole run in `drain_armed(on_request)`, entered before `state.lock()`. After the lock it calls `state.publish_run(os.getpid())`, and in a `finally` it calls `state.clear_run()`. `on_request` calls `state.mark_draining()` and `progress.draining()`. `publish_run` follows `state.lock()` directly, so a stale `run.json`, left only by a run that was SIGKILLed, is overwritten before anything is dispatched; a new run always starts not draining, and a drain leaves nothing behind that a restart obeys except the `Pending` records it set. The switch is threaded to `_loop` and `_run_section` and read at these boundaries, and only there:

| Boundary | Where | When the switch is set |
|---|---|---|
| Top of each pass, before the stop file | `relay/loop.py:70` | return `_drained()` |
| Parked or waiting wait | `relay/loop.py:93` | `drain.pause(cfg.poll_seconds)` replaces `time.sleep`; the next pass top returns `_drained()` |
| After the cap and architect-failure checks, before a pending dispatch, the design-answer `take_answer` or research | `relay/loop.py:121` | return `_drained()` |
| After research, before `take_answer`, `take_check_feedback`, `take_guidance` and the lead | `relay/loop.py:130-150` | return `_drained()`; nothing has been taken |
| Lead `RECUT`/`DESIGN`, before `_climb` | `relay/loop.py:185` | `set_pending(climb)`, return `_drained()` |
| Architect failed or reportless, before the retry | `relay/loop.py:666` | `set_pending(design-retry)` with the built retry brief, return `_drained()` |
| Architect approved, before the rung-2 recut | `relay/loop.py:747` | `set_pending(design-recut)` after `set_design_open(None)` and `mark_design_changed`, return `_drained()` |

Everything the finished child's result causes without starting an agent runs as it does now: the ledger line, last session, report and log, failure counts, `DONE`'s checks, `WAITING`, `NEEDS-OWNER` and rung-3 parks, pings. A section stop the finishing work returns (`FAILED_TWICE`, `BUDGET`) is returned as is; otherwise the next boundary returns `_drained()`. A drain never retires or kills the running child; its watcher keeps its usual limits.

`_run_section` takes a section's `Pending` at `relay/loop.py:121`, after that boundary and before the design-answer branch, and runs `_resume_pending` in place of research and a lead. The over-cap and failure checks in `_design_change` and `_architect` still apply inside it.

A signal that lands after a boundary's check and before the child starts lets that child start; it is then the running agent and finishes and is recorded as above. No state is taken without its dispatch following, so the window loses nothing.

`relay/errors.py`: `ExitCode.DRAINED = 6`.

`relay/cli.py`: `_stop` calls `state.live_run()`; with a live run whose pid is not its own it calls `runner.signal_drain(pid)` and touches no stop file; with none it touches `STOP` as now. A second `relay stop` on a draining run sends the second SIGTERM and stops it at once. `_status` prints `run: draining since HH:MM (pid N)` as its first line when `live_run()` says draining, and nothing new otherwise.

`relay/progress.py`: `draining()` prints `drain requested: finishing the running agent, starting nothing new`.

`README.md`: How it works step 1, the `stop` and `status` usage lines, the Ctrl-C line, the exit-code table (6: drained) and the state table (`run.json`) say what the code above does.

Replaces: the single-path SIGTERM in `_group_guard` (`relay/runner.py:355-358`), the STOP-only `relay stop` (`relay/cli.py:73-76`) and the uninterruptible wait (`relay/loop.py:93`).

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Signal handlers, the drain switch, signalling a run | `relay/runner.py` | `signal` or `os.kill` in any other module, `cli.py` included; a second flag or global for "draining" |
| Live-run record, pending dispatch record, lock probing | `relay/state.py` | opening `run.json` or `lock`, or a `pending` key, anywhere else |
| Dispatch boundaries and deferral | `relay/loop.py` | a drain check inside `runner.run_agent`, `research.py` or `ladder.py`; a boundary not in the table above |
| The drained exit code | `relay/errors.py` | the literal 6 anywhere else |
| Progress and ping wording | `relay/progress.py`, `relay/ping.py` | drain wording in `loop.py` or `cli.py`; the stop ping goes through `ping.stopped` as every stop does |
| Test fakes and helpers | `tests/fakes/fake_claude.py`, `tests/conftest.py`, `tests/harness.py` | a fake agent or a signal-sending helper written inside a test file |

## Order

1. Drain switch. `test-writer` writes `tests/test_runner.py`; `builder` writes `relay/runner.py` and `relay/errors.py`.
2. Live-run and pending records. `test-writer` writes `tests/test_state.py`; `builder` writes `relay/state.py`.
3. Loop drain: arming, boundaries, deferral, resume and the drained stop, with the test that signals a run mid-section and sees the running agent finish, its result recorded, nothing new started and exit 6. `test-writer` writes `tests/test_loop.py`, `tests/harness.py` and `tests/fakes/fake_claude.py`; `builder` writes `relay/loop.py` and `relay/progress.py`.
4. `relay stop` signals and `relay status` shows draining. `test-writer` writes `tests/test_cli.py`; `builder` writes `relay/cli.py`.
5. Documentation. `builder` writes `README.md`.
