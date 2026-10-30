Status: approved.

# `relay stats`: run sizes per role for the divvyer

## Why

`relay stats` reads every state directory under `cfg.state_root` (`relay/config.py:228`, default `~/.local/state/relay`), pairs each ledger line with its run log, and prints one short line per role giving the sizes of finished steps and the overruns. Size is peak context per run. The ledger's `tokens` are summed over turns (`relay/stream.py:87`, written at `relay/loop.py:411`), so `stats` never reads them as size.

The work it needs exists today as copies or private code:

1. Pairing ledger lines with run logs by session: private to `relay status`, at `relay/cli.py:99-122` (`_section_activity`).
2. Listing a state directory's numbered run logs: two copies, `relay/cli.py:108-110` and `relay/runner.py:136` (`_next_number`).
3. Reading ledger entries: `Ledger._entries` (`relay/ledger.py:142`) is private. The only public reader returns `(section, session)` alone (`relay/ledger.py:173`), so it cannot give a line's `kind`.
4. A subagent's context size: `Agent.context` holds the last `total_tokens` reported (`relay/agents.py:14`, set at `relay/agents.py:102-108`), not the peak. A lead's peak is already kept as `StreamState.peak_context` (`relay/stream.py:24`, `relay/stream.py:93`; Codex at `relay/backends/codex_session.py:231`, `:236`, `:261`).
5. Turning a lead's final text into a status: `relay/status.py:24` (`parse_status`), the one home, reused as is.

## Modules

**`relay/history.py`** (new): the one place that turns a state directory into its runs. Each run is one ledger line paired with its replayed run log. Pairing follows `relay/cli.py:99-122`: runs are numbered and ledgered in the order they ran, so a session that the ledger names more than once is paired with its logs in that order. A log that cannot be replayed (`OSError`, `ConfigError` from `relay/backends/__init__.py:59`) is skipped and counted. A ledger line with no session, such as a `check` line (`relay/ledger.py:116`), is no run.

```python
@dataclass(frozen=True)
class Run:
    kind: str            # the ledger line's "kind": lead, recut, research, ask, design
    section: str
    session: str
    log: Path
    stream: StreamState  # replayed from `log`

@dataclass(frozen=True)
class History:
    runs: tuple[Run, ...]   # in the order they ran
    skipped_logs: int       # logs that could not be replayed

def read(state: State, ledger: Ledger) -> History: ...
def activity_by_section(history: History) -> dict[str, agents.Activity]: ...
```

It replaces `relay/cli.py:99-122`. `relay status` calls `activity_by_section(read(...))`, and its output is unchanged.

**`relay/stats.py`** (new): the one place for sizing figures and their text. It reads `History` only, never the ledger's `tokens` or `dollars`.

```python
Role = str  # a top-level run's ledger kind, or a subagent's type (`Agent.name`)

@dataclass(frozen=True)
class Sized:
    role: Role
    section: str
    label: str         # the run's session, or the subagent's description
    peak: int          # peak context of this one run
    overrun: str | None  # None when finished; else "retired", "killed", "stopped" or "over context limit"

@dataclass(frozen=True)
class RoleStats:
    role: Role
    finished: tuple[int, ...]    # peaks of finished runs
    overruns: tuple[Sized, ...]  # in the order they ran

def sized(history: History, cfg: Config) -> list[Sized]: ...
def by_role(items: Iterable[Sized]) -> list[RoleStats]: ...   # sorted by role name
def lines(stats: list[RoleStats]) -> list[str]: ...
```

Classification:

- **Top-level run.** Its role is `Run.kind` and its peak is `stream.peak_context`. It is an overrun when `parse_status(stream.result_text)` is `RETIRED` (`"retired"`). It is also an overrun when it has no result after reaching `cfg.hard_ceiling` (`"killed"`), or when its peak is at or above `cfg.context_limit` (`"over context limit"`). These limits are the ones the watcher enforces at `relay/loop.py:558` and `relay/loop.py:567`. A lead run with any other status, or with none, is neither finished nor overrun unless it ended `DONE`. A run of any other kind is finished when it has a result and `is_error` is false.
- **Subagent** (`stream.activity.agents`). Its role is `Agent.name` and its peak is `max(Agent.peak, Agent.context)`. It is finished when `status == "completed"` and its peak is below `cfg.context_limit`. It is an overrun when `status == "stopped"` (`"stopped"`) or when its peak is at or above `cfg.context_limit` (`"over context limit"`). Any other status is neither.

`lines` prints one line per role:

```
<role>: <n> finished, peak context median <m>, p90 <p>, max <x>; <k> overruns
```

A role with no finished run prints `0 finished` and no figures. After each role line come its overruns, newest last, at most five, each one line:

```
  <role> overrun: <section> <label> peak <n> (<reason>)
```

When a role has more than five overruns, the five lines are preceded by `  <role>: <j> earlier overruns not shown`. Numbers are bare integers, as `relay/progress.py:48` prints them. A final line `skipped <n> unreadable run logs` appears only when `n > 0`.

**`relay/agents.py`** (extended): `Agent` gains `peak: int = 0`, which `_with_usage` (`relay/agents.py:102`) sets to the largest `total_tokens` reported. `restore_agent` (`relay/agents.py:63`) reads it when present and otherwise leaves it 0, so `max(peak, context)` stays right for older telemetry snapshots.

```python
@dataclass(frozen=True)
class Agent:
    ...
    peak: int = 0  # the largest `total_tokens` reported
```

**`relay/ledger.py`** (extended): one public reader over `_entries`.

```python
def entries(self) -> Iterator[dict]: ...   # each readable line, in the order written
```

`sessions()` (`relay/ledger.py:173`) is rebuilt on it.

**`relay/state.py`** (extended): listing run logs and state directories.

```python
def run_logs(self) -> list[Path]: ...            # numbered runs/*.jsonl, ascending by number
@classmethod
def all(cls, cfg: Config) -> list["State"]: ...  # each directory under cfg.state_root holding a ledger.jsonl
```

`runner._next_number` (`relay/runner.py:135`) and `history.read` use `run_logs`. Their only shared input is `run_dir`, which runner already receives (`relay/runner.py:291`), so `run_logs` is written as a module function, `numbered_logs(run_dir: Path) -> list[Path]`, and `State.run_logs` returns `numbered_logs(self.run_dir)`.

**`relay/cli.py`** (extended): a `stats` subcommand that takes no arguments. It loads `_config({})`, reads every `State.all(cfg)` with `history.read`, joins the runs, and prints `stats.lines(stats.by_role(stats.sized(history, cfg)))`. It returns `ExitCode.QUEUE_EMPTY` (`relay/errors.py:25`). When no state directory exists, it prints `no runs under <state_root>` and exits the same way. Errors go through `main`'s `RelayError` handler (`relay/cli.py:168-174`).

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Pairing ledger lines with run logs | `relay/history.py` `read` | any other session-to-log pairing; `cli.py` keeps no `_section_activity` |
| Listing numbered run logs | `relay/state.py` `numbered_logs` / `State.run_logs` | any `glob("*.jsonl")` with `isdigit` outside it |
| Reading ledger lines | `relay/ledger.py` `_entries` / `entries` | parsing `ledger.jsonl` anywhere else |
| Peak context of a lead run | `StreamState.peak_context` (`relay/stream.py:24`) | recomputing it from usage events |
| Peak context of a subagent | `Agent.peak` (`relay/agents.py`) | taking `context` or the ledger's `total_tokens` as a peak |
| Finished vs. overrun, and sizing figures | `relay/stats.py` `sized` / `by_role` | any other place deciding either |
| Stats text | `relay/stats.py` `lines` | `cli.py` formatting any stats figure |
| Lead status parsing | `relay/status.py` `parse_status` | — |
| Exit codes and errors | `relay/errors.py` | — |
| Enumerating state directories | `State.all` | listing `state_root` anywhere else |
| Test ledger lines | `tests/harness.py:148` `ledger_line`, extended to take `kind` and `session` | hand-written ledger JSON in tests |

## Order

1. **Core red tests.** `test-writer`. Writes `tests/test_history.py`, `tests/test_agents.py`, `tests/test_ledger.py`, `tests/test_state.py` and `tests/harness.py`. Covers: pairing of runs, including a session the ledger names twice and an unreadable log; `Agent.peak`; `Ledger.entries`; `State.run_logs` and `State.all`.
2. **Core build.** `builder`. Writes `relay/history.py`, `relay/agents.py`, `relay/ledger.py`, `relay/state.py`, `relay/runner.py` and `relay/cli.py`, where `status` moves onto `history` with unchanged output.
3. **Stats red tests.** `test-writer`. Writes `tests/test_stats.py` and `tests/test_cli.py`. Covers the classification and line format above, and `relay stats` over a `state_root` of two queues.
4. **Stats build.** `builder`. Writes `relay/stats.py` and `relay/cli.py`.
5. **Point the divvyer at it.** `general-purpose`. Writes `~/dev/guild/agents/divvyer.md`: lines 3 and 66 call `uv run --project ~/dev/relay relay stats` in place of `foreman stats`. The path is outside this repository, and this change takes no red test.
