Status: approved.

# Relay graceful drain

## Why

Relay's run switch and signal handling have one home (`relay/runner.py:61`, `relay/runner.py:409`), and its live-run record has one home (`relay/state.py:93`). The loop checks the switch before research (`relay/loop.py:183`), but research waits on a blocking lock (`relay/loop.py:393`, `relay/state.py:428`) before launching an agent (`relay/loop.py:412`). A request received during that wait must hold back the launch.

The same boundary concern spans research and the ladder: pending dispatch (`relay/loop.py:42`), climb (`relay/loop.py:597`), architect retry (`relay/loop.py:750`) and design recut (`relay/loop.py:838`). These paths share the run's switch; none owns a second draining flag. The CLI still touches `STOP` (`relay/cli.py:73`) and prints section states (`relay/cli.py:132`); its drain behavior uses the same run record and signal home.

Relay starts guarded child groups (`relay/runner.py:321`, `relay/runner.py:443`, `relay/runner.py:465`). A drain lets the running agent and its descendants finish, records the result, and holds back the next agent.

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
    retire_flag: Path, section: Section, pending: Pending, drain: DrainSwitch,
) -> _Stop | None:
    """Run the held-back dispatch: climb -> _climb; design-retry -> the retry run then
    _design_outcome; design-recut -> the rung-2 _recut, parking with ladder.failed_text on failure."""

def _research(
    cfg: Config, state: State, ledger: Ledger, since: float, cwd: Path,
    queue: Path, section: Section, drain: DrainSwitch,
) -> tuple[research.Map | None, bool]:
    """Recheck after acquiring the research lock and after blocking preparation, before
    dispatch. A held-back researcher returns (None, False); the caller returns _drained()."""
```

`run` wraps the whole run in `drain_armed(on_request)`, entered before `state.lock()`. After the lock it calls `state.publish_run(os.getpid())`, and in a `finally` it calls `state.clear_run()`. `on_request` calls `state.mark_draining()` and `progress.draining()`. `publish_run` follows `state.lock()` directly, so a stale `run.json`, left only by a run that was SIGKILLed, is overwritten before anything is dispatched; a new run always starts not draining, and a drain leaves nothing behind that a restart obeys except the `Pending` records it set. The same `DrainSwitch` is passed explicitly through `_loop`, `_run_section`, `_research`, `_resume_pending`, `_climb`, `_design_change`, `_design_answer`, `_architect` and `_design_outcome`. Helpers performing blocking dispatch preparation also receive it explicitly when they need a final check. No loop or ladder global holds draining state. The switch is read at these boundaries:

| Boundary | Where | When the switch is set |
|---|---|---|
| Top of each pass, before the stop file | `relay/loop.py:129` | return `_drained()` |
| Parked or waiting wait | `relay/loop.py:154` | `drain.pause(cfg.poll_seconds)`; the next pass top returns `_drained()` |
| After the cap and architect-failure checks, before a pending dispatch, the design-answer `take_answer` or research | `relay/loop.py:183` | return `_drained()` |
| After acquiring the researcher lock and after blocking preparation, before research dispatch | `relay/loop.py:393`, `relay/loop.py:412` | hold back both initial and refresh research; preserve the saved map and session; return to the caller's drained boundary |
| After research, before `take_answer`, `take_check_feedback`, `take_guidance` and the lead | `relay/loop.py:197` | return `_drained()`; nothing has been taken |
| Lead `RECUT`/`DESIGN`, before `_climb` | `relay/loop.py:254` | `set_pending(climb)`, return `_drained()` |
| Architect failed or reportless, before the retry | `relay/loop.py:750` | `set_pending(design-retry)` with the built retry brief, return `_drained()` |
| Architect approved, before the rung-2 recut | `relay/loop.py:838` | `set_pending(design-recut)` after `set_design_open(None)` and `mark_design_changed`, return `_drained()` |
| After blocking preparation in any dispatch path above, including resumed pending work | research `relay/loop.py:393`, architect `relay/loop.py:777`, recut `relay/loop.py:866` | recheck before launching; preserve the input or pending dispatch for the next run, without counting a failure |

Everything the finished child's result causes without starting an agent runs as it does now: the ledger line, last session, report and log, failure counts, `DONE`'s checks, `WAITING`, `NEEDS-OWNER` and rung-3 parks, pings. A section stop the finishing work returns (`FAILED_TWICE`, `BUDGET`) is returned as is; otherwise the next boundary returns `_drained()`. A drain never retires or kills the running child; its watcher keeps its usual limits.

`_run_section` takes a section's `Pending` at `relay/loop.py:185`, after that boundary and before the design-answer branch, and runs `_resume_pending` in place of research and a lead. The over-cap and failure checks in `_design_change` and `_architect` still apply inside it.

A signal that lands after the final boundary check and before the child starts lets that child start; it is then the running agent and finishes and is recorded as above. Blocking preparation, including waiting for the researcher lock, is outside this window and requires a fresh check afterward. Place blocking preparation before consumption of dispatch inputs where possible; if a later check holds back already-consumed work, retain its input or restore its pending record before returning drained. No answer, guidance, feedback or pending dispatch is lost. Every same-cause dispatch path follows this rule.

`relay/errors.py`: `ExitCode.DRAINED = 6`.

`relay/cli.py`: `_stop` calls `state.live_run()`; with a live run whose pid is not its own it calls `runner.signal_drain(pid)` and touches no stop file; with none it touches `STOP` as now. A second `relay stop` on a draining run sends the second SIGTERM and stops it at once. `_status` prints `run: draining since HH:MM (pid N)` as its first line when `live_run()` says draining, and nothing new otherwise.

`relay/progress.py`: `draining()` prints `drain requested: finishing the running agent, starting nothing new`.

`README.md`: How it works step 1, the `stop` and `status` usage lines, the Ctrl-C line, the exit-code table (6: drained) and the state table (`run.json`) say what the code above does.

Replaces: unconditional SIGTERM termination in the guarded signal path (`relay/runner.py:416`), the STOP-only `relay stop` (`relay/cli.py:73`) and a research launch authorized only by the pre-lock check (`relay/loop.py:183`, `relay/loop.py:393`).

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Signal handlers, the drain switch, signalling a run | `relay/runner.py` | `signal` or `os.kill` in any other module, `cli.py` included; a second flag or global for "draining" |
| Live-run record, pending dispatch record, lock probing | `relay/state.py` | opening `run.json` or `lock`, or a `pending` key, anywhere else |
| Dispatch boundaries and deferral | `relay/loop.py` | a drain check inside `runner.run_agent`, `research.py` or `ladder.py`; treating blocking preparation as the signal-after-boundary window; implicit or global switch access in loop helpers |
| The drained exit code | `relay/errors.py` | the literal 6 anywhere else |
| Progress and ping wording | `relay/progress.py`, `relay/ping.py` | drain wording in `loop.py` or `cli.py`; the stop ping goes through `ping.stopped` as every stop does |
| Test fakes and helpers | `tests/fakes/fake_claude.py`, `tests/conftest.py`, `tests/harness.py` | a fake agent or a signal-sending helper written inside a test file |

## Order

1. Drain switch. `test-writer` writes `tests/test_runner.py`; `builder` writes `relay/runner.py` and `relay/errors.py`.
2. Live-run and pending records. `test-writer` writes `tests/test_state.py`; `builder` writes `relay/state.py`.
3. Loop drain: arming, boundaries, deferral, resume and the drained stop; explicit switch threading through research and every ladder helper that needs it; rechecking after blocking preparation across every same-cause dispatch path. Coverage includes a request during the researcher-lock wait holding back initial or refresh research after acquisition, preservation of dispatch inputs, and deferred climb, architect retry and design recut using the same run switch. A request mid-section lets the running agent finish, records its result, starts nothing new and exits 6. `test-writer` writes `tests/test_loop.py`, `tests/harness.py` and `tests/fakes/fake_claude.py`; `builder` writes `relay/loop.py` and `relay/progress.py`.
4. `relay stop` signals and `relay status` shows draining. `test-writer` writes `tests/test_cli.py`; `builder` writes `relay/cli.py`.
5. Documentation. `builder` writes `README.md`.
