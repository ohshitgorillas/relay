Status: approved.

# Relay: the unattended lead loop

## Why

Relay is a command-line loop that runs a divvyer `.md` queue with no main agent in the middle. It starts a lead on the first open section. When that lead finishes, or its context passes a token limit, it starts a fresh lead that picks up from the last one through Terminus. It acts on each lead's status line, and it stops on an empty queue, a budget, a stop file or the same section failing twice.

The tree holds no copies to count. HEAD tracks no code: `git ls-tree -r HEAD` lists only `docs/queue.md` and this design, so this design sets each shared concern's one home before any piece exists. Seven concerns are shared by two or more pieces: running and killing child processes, reading Claude's stream-json output, the queue format, persistent state and the spend ledger, owner pings, errors and exit codes, and config. A piece that needs one of these and finds its home lacking stops and reports. It never writes a local copy.

Relay is Python 3.11+ with the standard library only (`tomllib`, `subprocess`, `fcntl`, `argparse`, `json`). Tests run under `pytest`. Relay does not import or call Foreman. Relay calls only these external commands, and each is used as it stands: the `claude` CLI (for leads and the divvyer's `recut`) and `claude-ping`. Leads recall earlier sessions with `recall-session` themselves; Relay only passes them a session id.

## Modules

`relay/errors.py`: the one place for every Relay error type and process exit code.

```python
class RelayError(Exception):
    exit_code: int = 1

class ConfigError(RelayError): exit_code = 2      # bad config or bad CLI arguments
class QueueFormatError(RelayError): exit_code = 2 # queue file does not parse
class LockedError(RelayError): exit_code = 2      # another `relay go` holds this queue

class ExitCode:
    QUEUE_EMPTY = 0
    ERROR = 1
    USAGE = 2
    BUDGET = 3
    STOP_FILE = 4
    FAILED_TWICE = 5
    INTERRUPTED = 130
```

`relay/config.py`: loads `~/.config/relay/config.toml` and applies CLI overrides, giving one frozen `Config`.

```python
@dataclass(frozen=True)
class Config:
    token_budget: int | None          # summed tokens across every run of this `relay go`; None = no limit
    dollar_budget: float | None       # summed total_cost_usd across every run of this `relay go`; None = no limit
    context_limit: int                # lead context tokens at which Relay asks it to retire; default 100_000
    hard_ceiling: int                 # lead context tokens at which Relay kills it; default 2 * context_limit
    poll_seconds: float               # wait between checks for answers and the stop file; default 30
    lead_command: list[str]           # argv; prompt goes on stdin. default: ["claude", "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "bypassPermissions"]
    recut_command: list[str]          # argv; divvyer recut brief goes on stdin. default: lead_command + ["--agent", "divvyer"]
    ping_command: list[str]           # argv; "{message}" is replaced by the message. default: ["~/.local/bin/claude-ping", "{message}"]
    state_root: Path                  # default ~/.local/state/relay

def load_config(path: Path | None, overrides: dict[str, object]) -> Config: ...
```

`relay/queue.py`: parses the divvyer's `.md` queue into sections. This is the only code that knows the queue's format. Relay never writes the queue; the divvyer's `recut` writes it.

```python
@dataclass(frozen=True)
class Section:
    id: str                    # the section's id as the divvyer writes it
    title: str
    body: str                  # the section's full text, verbatim
    depends_on: tuple[str, ...]
    open: bool                 # False when the queue itself marks the section done

def parse_queue(path: Path) -> list[Section]: ...   # raises QueueFormatError
def blocked_by(sections: list[Section], parked: set[str]) -> set[str]: ...  # ids that depend, transitively, on a parked id
```

`relay/state.py`: Relay's own record for one queue, kept under `state_root/<slug of the queue's absolute path>/`. It holds per-section status, failure counts, parked questions, owner answers, the last session id per section, the stop file and the lock. Every write goes through a temp file and `os.replace`.

```python
SectionStatus = Literal["open", "done", "parked"]

@dataclass
class SectionState:
    status: SectionStatus
    failures: int
    question: str | None        # set while parked
    answer: str | None          # set by `relay answer`; consumed by the next lead prompt
    last_session: str | None

class State:
    @classmethod
    def open(cls, queue: Path, cfg: Config) -> "State": ...   # creates the dir; no lock
    def lock(self) -> None: ...                               # fcntl.flock on <dir>/lock; raises LockedError
    def section(self, sid: str) -> SectionState: ...
    def mark_done(self, sid: str) -> None: ...
    def park(self, sid: str, question: str) -> None: ...
    def set_answer(self, sid: str, answer: str) -> None: ...  # also sets status back to "open"
    def take_answer(self, sid: str) -> str | None: ...
    def record_failure(self, sid: str) -> int: ...            # returns the new count
    def set_last_session(self, sid: str, session: str) -> None: ...
    @property
    def last_session_any(self) -> str | None: ...
    @property
    def stop_file(self) -> Path: ...                          # <dir>/STOP
    @property
    def run_dir(self) -> Path: ...                            # <dir>/runs/
```

`relay/ledger.py`: the spend ledger. It appends one JSON line per finished run (lead or recut), stamped with its POSIX time, to `<state dir>/ledger.jsonl`. Budgets count only the current `relay go`: the loop passes its own start time as `since`. `relay status` shows the rolling 7-day total (`since` = now minus 7 days) beside the all-time total.

```python
@dataclass(frozen=True)
class Spend:
    tokens: int        # input + output + cache_creation_input_tokens + cache_read_input_tokens
    dollars: float     # total_cost_usd from the run's result event; 0.0 when absent

class Ledger:
    def __init__(self, path: Path): ...
    def append(self, kind: Literal["lead", "recut"], section: str, session: str | None, spend: Spend) -> None: ...
    def total(self, since: float | None) -> Spend: ...   # since = POSIX timestamp of the window start
    def over(self, cfg: Config, live: Spend, since: float | None) -> Literal["tokens", "dollars"] | None: ...
```

`relay/stream.py`: reads the `claude -p --output-format stream-json` event lines. This is the only code that knows that schema.

```python
@dataclass
class StreamState:
    session_id: str | None     # from the init event
    context_tokens: int        # latest assistant message: input + cache_creation + cache_read
    spend: Spend               # running sum of usage; dollars filled from the result event
    result_text: str | None    # the result event's text
    is_error: bool

def feed(state: StreamState, line: str) -> StreamState: ...   # ignores lines that are not JSON events
```

`relay/runner.py`: the one place a child process starts, streams, is killed and is reaped. Each child runs in its own process group (`start_new_session=True`). The runner records the child's PID in `<run_dir>/<n>.pid`. It kills by process group, then checks with `os.waitpid` and `os.kill(pid, 0)` that the child is gone. It also installs SIGINT and SIGTERM handlers that kill the live child group before Relay exits.

```python
@dataclass(frozen=True)
class RunResult:
    exit_code: int | None      # None when killed
    killed: bool
    stream: StreamState
    log: Path                  # <run_dir>/<n>.jsonl, every stream line verbatim

def run_agent(argv: list[str], stdin_text: str, cwd: Path, run_dir: Path,
              on_event: Callable[[StreamState], Literal["go", "retire", "kill"]],
              retire_flag: Path) -> RunResult: ...
# on_event returning "retire" creates retire_flag once; "kill" kills the group.
```

`relay/status.py`: parses the lead's final status line, which is the last non-empty line of the result text.

```python
@dataclass(frozen=True)
class LeadStatus:
    kind: Literal["DONE", "RECUT", "NEEDS-OWNER", "RETIRED"]
    text: str                  # words after "KIND: "; required for NEEDS-OWNER (the question) and RECUT (the reason)

def parse_status(result_text: str | None) -> LeadStatus | None: ...   # None = no valid status line, which counts as a failure
```

`relay/prompts.py`: builds every text Relay sends to an agent.

```python
def lead_prompt(queue: Path, section: Section, resume: str | None,
                answer: str | None, retire_flag: Path) -> str: ...
# Opens "You are a lead". Holds: the queue path, the section id and body verbatim,
# "resume <session id>" when resume is set, the owner's answer verbatim when set,
# the retire contract (on reaching a safe point, after a step's commit, if retire_flag
# exists end with RETIRED), and the status contract: the last line is exactly one of
# "DONE", "RECUT: <reason>", "NEEDS-OWNER: <question>", "RETIRED".

def recut_brief(queue: Path, section: Section, reason: str, lead_log: Path) -> str: ...
# The divvyer's `recut` brief for that section, carrying the lead's reason and its run log path.
```

`relay/ping.py`: the one place an owner ping is worded and sent. Every message begins `relay <queue name>: `.

```python
def ping(cfg: Config, message: str) -> None: ...   # runs cfg.ping_command through runner-free subprocess.run; a failed ping is logged to stderr, never raised
def needs_owner(cfg: Config, queue: Path, sid: str, question: str) -> None: ...
def stopped(cfg: Config, queue: Path, reason: str, detail: str) -> None: ...
```

`relay/loop.py`: the state machine for one `relay go`.

```python
def run(queue: Path, cfg: Config) -> int: ...   # returns an ExitCode
```

Each pass does the following, in order:
1. If the stop file exists, stop with `STOP_FILE`.
2. If the ledger, summed since this `relay go` started, is over budget, stop with `BUDGET`.
3. Re-parse the queue. Pick the first section that is open in the queue, not `done` or `parked` in state, and not blocked by a parked section.
4. If no such section exists and nothing is parked, stop with `QUEUE_EMPTY`.
5. If no section is runnable but some are parked, wait, holding the lock: check every `poll_seconds` for the stop file (stop with `STOP_FILE`) or a `relay answer` on a parked section (start the next pass). The ping for each parked section went out when it parked; waiting sends none.
6. Otherwise, run a lead with `resume` set to the section's `last_session`, or else `last_session_any`. During the run, `on_event` returns:
   - `retire` once `context_tokens ≥ context_limit` or the live spend passes a budget;
   - `kill` at `hard_ceiling`.
7. Append the run's spend to the ledger and record its session.
8. Act on the status:
   - DONE: `mark_done`.
   - RETIRED: run a fresh lead on the same section; this is no failure.
   - RECUT: run `recut_command` with `recut_brief`, append its spend to the ledger, and re-parse. A non-zero exit or an unchanged queue file counts as a failure of the section.
   - NEEDS-OWNER: `park`, then `ping.needs_owner`.
   - A missing status, non-zero exit or kill: `record_failure`. A second failure stops with `FAILED_TWICE`.

After a budget-triggered retire, the pass ends with `BUDGET`. Every stop calls `ping.stopped` before returning.

`relay/cli.py`: the `relay` console script.

```python
def main(argv: list[str] | None = None) -> int: ...
# relay go <queue.md> [--token-budget N] [--dollar-budget D] [--context-limit N]
# relay stop <queue.md>                     creates the stop file
# relay answer <queue.md> <section-id> <text>   sets the answer, reopens the section
# relay status <queue.md>                   prints each section's state and the ledger's rolling 7-day and all-time totals
```

The lead and the recut run with `cwd` set to the git top level of the queue's directory. Relay never commits, never cleans the work tree and never edits the queue. Leads and the divvyer keep git and the queue as the record of what is finished.

Test helpers: `tests/fakes/fake_claude.py` is an executable that reads its prompt on stdin. It emits scripted stream-json lines taken from a scenario file named by `RELAY_FAKE_SCENARIO`. `tests/conftest.py` holds the fixtures `fake_cfg` (a `Config` whose commands point at the fake, with `state_root` under `tmp_path`), `queue_file` (writes a fixture queue) and `scenario` (writes a scenario). `tests/fixtures/` holds queue samples in the divvyer's `.md` format.

Relay replaces nothing: no copy exists in the tree.

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Starting, streaming, killing and reaping child processes; PID records; signal cleanup | `relay/runner.py` | `subprocess`, `os.kill`, `signal` in any other module (`ping.py` may call `subprocess.run` for the ping only) |
| Claude stream-json schema, token and cost counting | `relay/stream.py` | parsing stream-json events or reading `usage` / `total_cost_usd` anywhere else |
| Divvyer queue format | `relay/queue.py` | reading or regex-matching the queue file anywhere else; writing the queue anywhere |
| Relay state, stop file, lock, run dirs | `relay/state.py` | paths under `state_root` built anywhere else; any non-atomic state write |
| Spend summing and budget checks | `relay/ledger.py` | summing tokens or dollars anywhere else |
| Lead status-line contract | `relay/status.py` (parse) and `relay/prompts.py` (wording) | the status words or their regex written in any other module |
| Agent prompt and brief text | `relay/prompts.py` | prompt strings in `loop.py` or `cli.py` |
| Owner pings | `relay/ping.py` | calling `claude-ping` or wording a ping anywhere else |
| Errors and exit codes | `relay/errors.py` | `sys.exit` with a literal, or an exception class, outside `errors.py`; `cli.py` alone maps them to the process exit |
| Config and defaults | `relay/config.py` | a default value or `config.toml` read anywhere else |
| Test fakes and fixtures | `tests/fakes/fake_claude.py`, `tests/conftest.py`, `tests/fixtures/` | a second fake agent or ad hoc stream-json fixture in a test file |

## Order

1. Skeleton and stubs. `builder` (`stub` piece) writes `pyproject.toml` (package `relay`, console script `relay = relay.cli:main`, dev dependency `pytest`), `relay/__init__.py` and every module above, with the signatures raise-only.
2. Test helpers. `test-writer` writes `tests/conftest.py`, `tests/fakes/fake_claude.py` and `tests/fixtures/` (queue samples copied from `/Users/atom/dev/workboard/docs/queue.md` and `/Users/atom/dev/foreman/queues/m2-rest.md`).
3. Errors and config: red tests. `test-writer` writes `tests/test_config.py`.
4. Errors and config: build. `builder` writes `relay/errors.py` and `relay/config.py`.
5. Queue parser: red tests. `test-writer` writes `tests/test_queue.py`.
6. Queue parser: build. `builder` writes `relay/queue.py`.
7. State and ledger: red tests. `test-writer` writes `tests/test_state.py` and `tests/test_ledger.py`.
8. State and ledger: build. `builder` writes `relay/state.py` and `relay/ledger.py`.
9. Stream and runner: red tests. `test-writer` writes `tests/test_stream.py` and `tests/test_runner.py`.
10. Stream and runner: build. `builder` writes `relay/stream.py` and `relay/runner.py`.
11. Status, prompts and ping: red tests. `test-writer` writes `tests/test_status.py`, `tests/test_prompts.py` and `tests/test_ping.py`.
12. Status, prompts and ping: build. `builder` writes `relay/status.py`, `relay/prompts.py` and `relay/ping.py`.
13. Loop and CLI: red tests. `test-writer` writes `tests/test_loop.py` and `tests/test_cli.py`.
14. Loop and CLI: build. `builder` writes `relay/loop.py` and `relay/cli.py`.
