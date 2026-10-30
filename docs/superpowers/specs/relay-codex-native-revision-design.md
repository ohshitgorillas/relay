Status: approved.

# Relay Codex-native enforcement, revised

## Why

This design replaces `docs/superpowers/specs/relay-codex-native-design.md` whole. Its queue `docs/codex-native-queue.md` is cut from that file and no longer applies. Every piece lands on branch `codex-native`, off main, and stays unmerged.

The goal: Relay's Codex runs never invoke `~/.codex/hooks/claude_adapter.py`, the script that translates the owner's Claude hooks for Codex. Relay enforces those rules natively instead. `relay/backends/claude.py` and every Claude runtime behavior stay as they are.

**The draft got the adapter wrong.**
- It names Relay's own Claude backend as "the Claude adapter" (`docs/superpowers/specs/relay-codex-native-design.md:33`) and plans a report on deleting it (`docs/superpowers/specs/relay-codex-native-design.md:279`). The adapter that matters is `~/.codex/hooks/claude_adapter.py`, outside this repository.
- It keeps the user hooks running for Relay runs ("Relay leaves them on", `docs/superpowers/specs/relay-codex-native-design.md:31`). Every Codex run inherits the owner's environment (`relay/runner.py:262-265` passes no `env`) and the owner's `CODEX_HOME` (`relay/backends/codex.py:26`). So every Relay Codex run loads `~/.codex/hooks.json`, and with it the adapter. The captured run proves the hooks file is loaded: `tests/fixtures/codex-real/stdout.jsonl:2` and `tests/fixtures/codex-warnings/research-stdout.jsonl:4`.
- Nothing in this repository says which hooks the adapter translates or what they enforce. Order step 1 takes that inventory.

**Copies and gaps.**
- **Permissions.** Every Codex run passes `--dangerously-bypass-approvals-and-sandbox` (`relay/backends/codex.py:64-68`).
- **Roles.** Codex role names are mapped twice: `relay/backends/codex.py:30-33` and `relay/config.py:59-77`. A third copy, for Claude, is at `relay/backends/claude.py:19-28` and is kept. Roles are read only from `$CODEX_HOME/agents` (`relay/backends/codex.py:36`). A researcher follow-up smuggles its session id through `research_command` (`relay/loop.py:375`, `relay/backends/codex.py:57-60`).
- **Capability lookup** is copied four times: `relay/loop.py:358`, `relay/loop.py:402`, `relay/loop.py:615` and `relay/ledger.py:170`.
- **Dollars.** `CodexBackend.capabilities.dollars` is False (`relay/backends/codex.py:23`), so `Ledger.over` (`relay/ledger.py:159-178`) ignores Codex dollar budgets.
- **Usage: nested helpers.** Helper threads are found only in the run's own stdout `collab_tool_call` items (`relay/backends/codex.py:98-99`, `relay/backends/codex.py:103-126`). A helper spawned by a helper shows up only in that helper's rollout, so it is never seen. No helper thread is metered at all: `poll` reads only the run's own thread (`relay/backends/codex.py:128-133`).
- **Usage: resumed sessions.** A resumed `ask` reads from the pre-resume file size (`relay/backends/codex_session.py:38-46`, `relay/backends/codex_session.py:72-84`). But it takes `total_token_usage.total_tokens` (`relay/backends/codex_session.py:113-124`), which may still include the thread's earlier turns. If it does, those turns are counted again on top of the research run's own ledger line. Step 1 records whether the total resets on resume.
- **Budget.** The watcher can only ask for a retire (`relay/loop.py:413-437`). It cannot kill a run that keeps spending past the budget.
- **Failures.**
  - `State.record_failure` (`relay/state.py:277-282`) only ever increments, and records no reason.
  - `mark_done` clears design failures but not `failures` (`relay/state.py:123-136`).
  - Two call sites copy the failure handling: `relay/loop.py:176-180` and `relay/loop.py:525-529`.
  - A successful recut that rewrites the section under the same id keeps the old count (`relay/loop.py:802-806`), so the rewritten section stops on its first failure.
  - Once the owner fixes a blocker, no command reopens the section: `relay/cli.py:33-51` has no `retry`.
- **Claude behavior** is pinned only by the existing tests: `tests/test_backends.py`, `tests/test_loop.py`, `tests/test_ledger.py` and `tests/test_config.py`. The draft put its Claude pin after research reuse, which is a new feature (`docs/superpowers/specs/relay-codex-native-design.md:262-263`).
- **Research reuse.** `docs/superpowers/specs/relay-research-reuse-design.md` (approved) and its queue `docs/research-reuse-queue.md` are committed on `codex-native` (`80f9440`, recut at `04a3d0c`). This design builds them as cut.

### Dependency inventory

| Dependency | Where | Outcome |
|---|---|---|
| `~/.codex/hooks.json` and `~/.codex/hooks/claude_adapter.py` | loaded by every Relay Codex run (`relay/runner.py:262-265`, `relay/backends/codex.py:26`) | Relay Codex runs never invoke them. The hook exclusion in `relay/codex_launch.py` does this, and native enforcement covers each translated hook. Neither file is edited. The owner's own Codex sessions and every non-Relay user keep them. |
| Project hooks in the run's cwd and its ancestors (`.codex/` in the target repository and its parents) | not handled today | Excluded the same way. Step 1 proves this per layer on the installed CLI. |
| Claude agent files through `--agent` | `relay/config.py:11`, `relay/config.py:76`, `relay/config.py:196` | Claude only and unchanged. |
| `--permission-mode bypassPermissions` | `relay/config.py:12` | Claude only and unchanged. |
| stream-json parser | `relay/stream.py` `feed` | Claude only and unchanged. |
| Terminus `resume <id>` hint | `relay/backends/claude.py:39-40` | Claude only and unchanged. |
| `claude-ping` notifier default | `relay/config.py:220` | Shared default and unchanged. |
| Codex role TOMLs generated from Claude agents | `relay/backends/codex.py:36` | Replaced by `roles_dir`. The generator stays outside Relay. |
| Codex bypass flag | `relay/backends/codex.py:65,67` | Removed. Native sandbox and approval settings replace it. |
| `CODEX_HOME`, credentials, `~/.codex/sessions` | `relay/backends/codex.py:26` | Unchanged. Relay never sets `CODEX_HOME`, so credentials and existing sessions are never copied, moved or rewritten. |

## Modules

### `relay/codex_launch.py`: the launch that keeps the translation adapter out

Builds the configuration every Relay Codex process starts with. It excludes every hook layer, carries the native enforcement settings, and refuses to launch on a CLI version where the exclusion has not been proven.

```python
PROVEN: dict[str, tuple[str, ...]]
"""Each `codex --version` string on which step 1 or a shakedown attempt proved the exclusion,
mapped to the exact `-c` overrides and flags that exclude every hook layer on that version."""

@dataclass(frozen=True)
class Launch:
    argv_prefix: tuple[str, ...]      # "codex", "exec", the hook-exclusion args, the enforcement args
    env: dict[str, str]               # added to the inherited environment; never CODEX_HOME
    home: Path                        # the CODEX_HOME the rollouts are read from: inherited, else ~/.codex

def version(cfg: Config) -> str:
    """`codex --version`, run through runner.capture. ConfigError when it cannot run."""
    raise NotImplementedError

def check(cfg: Config) -> str:
    """The installed version. ConfigError when it is not a key of PROVEN: the hook exclusion is
    unproven on it, and Relay will not launch Codex on it."""
    raise NotImplementedError

def launch(cfg: Config, inv: Invocation, role: Role, helpers: tuple[Role, ...], ver: str) -> Launch:
    """The hook exclusion PROVEN[ver]; the sandbox, approval, network, writable roots, model,
    effort, instructions and features of `role`; each helper delivered through the CLI's native
    agent-role keys; `exec resume <inv.resume>` for an ask."""
    raise NotImplementedError
```

Native enforcement is the role's settings plus the hook exclusion. No Relay code reads, runs or imitates a hook. Step 1's inventory gives each translated hook exactly one outcome:
- **Write and path guards** become `Role.sandbox` and `Role.writable_roots`. Writable roots are the run's cwd and the git common dir of the cwd. `~/.claude`, `~/.codex` and every other path stay read-only.
- **Remote and push guards** become `network = false`. This is the default for every role. `read-only` roles have no network.
- **Command guards a sandbox cannot express** become a native rule on the installed CLI: an exec-policy rule or a config key, as step 1 records it, passed in `argv_prefix`.
- **Session, notification and judge hooks** are dropped for Relay runs. Relay's own `ping` and `progress` already report run lifecycle.

If the inventory holds a hook that enforces an owner rule and has no native form on the installed CLI, step 1 ends with `DESIGN:`.

### `relay/roles.py`: one source for every Codex role a run launches or delivers

```python
RELAY_ROLES = {"lead": "lead", "recut": "divvyer", "research": "researcher", "ask": "researcher", "design": "architect"}
SANDBOXES = ("read-only", "workspace-write")
DEFAULT_SANDBOX = {"lead": "workspace-write", "recut": "workspace-write", "design": "workspace-write",
                   "research": "read-only", "ask": "read-only"}

@dataclass(frozen=True)
class Role:
    name: str
    path: Path
    instructions: str              # developer_instructions, non-empty
    model: str                     # required
    effort: str | None
    sandbox: str                   # one of SANDBOXES
    approval: str                  # always "never"
    network: bool                  # default False
    writable_roots: tuple[str, ...]
    features: dict[str, bool]

def roles_dir(cfg: Config) -> Path:
    """cfg.roles_dir, else $CODEX_HOME/agents, else ~/.codex/agents."""
    raise NotImplementedError

def load(cfg: Config, kind: str) -> Role:
    """The Relay role for a run kind. ConfigError when the file is missing or unreadable, a key has
    the wrong type, model is absent, sandbox is not in SANDBOXES, approval_policy is set to anything
    but "never", or a writable root lies under ~/.claude or ~/.codex."""
    raise NotImplementedError

def helpers(cfg: Config) -> tuple[Role, ...]:
    """Every *.toml in roles_dir whose stem is not a RELAY_ROLES value, sorted by name, validated as load
    validates. Sandbox defaults to workspace-write."""
    raise NotImplementedError
```

The role-file keys are `developer_instructions`, `model`, `model_reasoning_effort`, `sandbox_mode`, `approval_policy`, `[sandbox_workspace_write] network_access, writable_roots` and `[features]`. Each keeps the name and type that step 1 records from the installed CLI. `danger-full-access` is refused. `Config` gains `roles_dir: Path | None = None`. `roles` replaces `relay/backends/codex.py:30-56`. `ClaudeBackend.argv` keeps its own mapping.

### `relay/pricing.py`: Relay-owned API-equivalent rates

```python
SOURCE = "https://developers.openai.com/api/docs/pricing"
AS_OF = "<the date step 1 read the page>"

@dataclass(frozen=True)
class Rate:
    input: float          # USD per 1M uncached input tokens
    cached_input: float
    output: float         # reasoning tokens are part of output

RATES: dict[str, Rate]

@dataclass(frozen=True)
class Usage:
    thread: str
    model: str
    input: int            # cached included
    cached_input: int
    output: int

class Unpriced(RelayError): ...

def rate(cfg: Config, model: str) -> Rate:
    """cfg.prices[model], else RATES[model]; Unpriced otherwise. Never a default."""
    raise NotImplementedError

def dollars(cfg: Config, usage: tuple[Usage, ...]) -> float:
    """Sum of (input - cached_input) * input + cached_input * cached_input + output * output, over 1e6."""
    raise NotImplementedError
```

`Config` gains `prices: dict[str, Rate]` from the config file's `[prices."<model>"]` tables. Each value must be finite and non-negative. Codex dollars are an API-equivalent estimate, not subscription billing. The ledger and `relay status` say so.

### `relay/backends/base.py`: contract changes

```python
@dataclass(frozen=True)
class Capabilities:
    context: bool
    tokens: bool
    dollars: bool
    subagents: bool
    resume: bool = False
    budget_kill: bool = False
    basis: Literal["reported", "api-estimate", "none"] = "reported"

@dataclass(frozen=True)
class Invocation:
    role: str                   # a RELAY_ROLES key
    cwd: Path
    output: Path
    resume: str | None = None

class Backend(Protocol):
    capabilities: Capabilities
    def argv(self, inv: Invocation, cfg: Config) -> list[str]: ...
    def env(self, inv: Invocation, cfg: Config) -> dict[str, str]: ...   # added to the inherited environment
    def preflight(self, cfg: Config) -> None: ...
    def parse(self, state: StreamState, line: str) -> StreamState: ...
    def poll(self, state: StreamState) -> StreamState: ...
    def finish(self, state: StreamState, output: Path) -> StreamState: ...
    def resume_hint(self, session_id: str) -> str: ...
```

`relay/backends/__init__.py` gains `capabilities(name) -> Capabilities`, replacing the four copies. For Claude, `argv` returns what it returns today for the same role, `env` is `{}` and `preflight` is a no-op. Generic works the same way. `run_agent` (`relay/runner.py:213-234`) takes `inv: Invocation` and passes `{**os.environ, **backend.env(inv, cfg)}` to `Popen`. With an empty `env` the child's environment is exactly today's. `loop.ask` passes `resume=session` and stops rewriting `research_command`.

### `relay/stream.py`

```python
@dataclass
class StreamState:
    ...                                   # existing fields unchanged
    usage: tuple[Usage, ...] = ()         # Codex only: one entry per thread and model, net of any resume baseline
    fault: str | None = None              # a backend demand to end the run now
```

`feed` is unchanged. `_snapshot` (`relay/backends/__init__.py:30-53`) restores both fields.

### `relay/backends/codex_session.py`: complete usage

```python
@dataclass(frozen=True)
class ThreadUsage:
    thread: str
    parent: str | None
    usage: tuple[Usage, ...]      # per model, net of baseline

class ThreadTree:
    """Every thread a run owns: its own thread, each collab receiver, and transitively each thread whose
    session_meta names an owned thread as its parent (the field step 1 records). Each thread is counted once."""
    def __init__(self, home: Path, root: str, *, boundary: dict[Path, int] | None = None): ...
    def add_receivers(self, threads: Iterable[str]) -> None: ...
    def poll(self, *, force_scan: bool = False) -> tuple[ThreadUsage, ...]: ...
    def unobserved(self) -> tuple[str, ...]: ...    # owned threads with no telemetry yet
```

- **Baseline.** For a thread that existed before the run (a resume), the baseline is the last `total_token_usage` before the boundary. The run's usage is the current total minus that baseline, per field. A thread first seen during the run has a zero baseline.
- **No double counting.** A thread is keyed by id. A thread reached both as a receiver and through `session_meta` is counted once. A thread's total is its latest cumulative value, never a sum of increments.
- **Models.** Turn-context records give each thread's model per turn. Usage is split per model where the rollout records the change.
- `SessionReader` stays the per-file reader and is the only code that parses rollout files.

### `relay/backends/codex.py`

`capabilities = Capabilities(context=True, tokens=True, dollars=True, subagents=True, resume=True, budget_kill=True, basis="api-estimate")`.

- **`argv`** returns `codex_launch.launch(...).argv_prefix` plus `--json -C <cwd> -o <output> -`, or the resume form for an ask. It never passes `--dangerously-bypass-approvals-and-sandbox`.
- **`env`** returns `Launch.env`.
- **`preflight`** runs `codex_launch.check`, loads every Relay role and helper, and prices every model with `pricing.rate`. A `ConfigError` or `Unpriced` stops `relay go` and `relay ask` with exit 2 before any run.
- **`poll`** feeds receivers from `collab_tool_call` items into a `ThreadTree` rooted at the run's thread.
  - `spend.tokens` is the sum over the tree. `spend.dollars` is `pricing.dollars` over the tree's usage.
  - `usage` holds the tree's entries. `context_tokens` comes from the run's own thread only.
  - An unpriced model sets `fault`.
- **`finish`** behaves as today (`relay/backends/codex.py:135-146`). It also marks the run an error when `unobserved()` is non-empty.

### `relay/ledger.py`

`append` gains `basis` and `usage`. Each line carries `"basis"`, plus `"usage": [{thread, parent, model, input, cached_input, output}]` when usage is present. `append_failure(kind, section, session, reason, log)` writes a zero-spend `failure` line. `totals_by_basis(since)` serves `relay status`. `over` takes capabilities from `backends.capabilities`.

### `relay/loop.py`: bounded graceful budget termination and failure rules

```python
@dataclass
class _Watch:
    on_event: Callable[[StreamState], Literal["go", "retire", "kill"]]
    budget_hit: bool = False
    budget_killed: bool = False
    idle_retired: bool = False
```

**Budget termination** on a backend with `budget_kill`:
1. A budget or section-cap hit asks for a retire, as today.
2. Spend past the limit by more than `cfg.budget_grace` (a fraction of that limit, default 0.1, `--budget-grace F`) returns `"kill"` and sets `budget_killed`. The runner's `_kill_and_reap` (`relay/runner.py:161-198`) carries out the kill: SIGTERM to the process group, `_GRACE_SECONDS` (`relay/runner.py:28`), SIGKILL, then a check that the group is gone. So the overrun is bounded by the grace and the termination is graceful.
3. The killed run is ledgered with its spend, and `relay go` exits 3. A budget kill is never a failure.

A backend without `budget_kill`, Claude included, behaves exactly as today: retire only. `relay go` and `relay ask` call `preflight` once before any run. A `stream.fault` returns `"kill"` and counts as a failure.

**Failure rules**, on every backend:
1. **What counts.** A failure is any of:
   - a run that `run_failed` reports;
   - a lead with no status line;
   - a `fault`;
   - a failed recut.

   Each is recorded with `State.record_failure(sid, reason, log)` and `Ledger.append_failure`. A budget kill, a stop file, an interrupt and an idle retire are not failures.
2. **Retry once.** At count 1, the next pass runs a fresh lead. Its guidance reads `Relay's previous run on this section failed: <reason>. Log: <path>.`
3. **Stop at two.** At `FAILURE_LIMIT`, `relay go` exits 5. On restart, `_run_section` exits 5 before research or lead while the count is at the limit, as it does for design failures (`relay/loop.py:118-119`).
4. **Clear.** These set the count to 0 and clear reason and log:
   - a lead that ends with a parsed status;
   - `mark_done`;
   - `relay answer`;
   - `relay retry`;
   - a successful recut whose section keeps its id and whose own entry changed (the `mark_from_recut(section.id)` branch, `relay/loop.py:802-806`).

   A recut that keeps the id but leaves the section's entry unchanged keeps the count.
5. **Explicit retry after a blocker is fixed.** `relay retry` is the only way to reopen a section stopped at the limit.
   - It sets status to open and clears `failures`, `failure`, `failure_log`, `design_failures` and `design_failure`.
   - The next lead's guidance reads `The owner fixed the blocker and retried this section. The last failure was: <reason>. Log: <path>.`
   - Spend, sessions, maps and answers are untouched.

`_fail` and `_failed_twice` are the one home. Both call sites, and the recut clear, go through them.

### `relay/state.py`

`SectionState` gains `failure: str | None = None` and `failure_log: str | None = None`.
- `record_failure(sid, reason, log) -> int` replaces `record_failure(sid)`.
- Added: `clear_failures(sid)`, `retry(sid, guidance)` and `failed_sections()`.
- `mark_done` and `set_answer` also clear `failures`.

### `relay/cli.py`

```text
relay failures <queue.md>                          # "<sid> | failures <n> | design <n> | <reason> | <log>"; exit 0
relay retry <queue.md> (<section-id>... | --all)   # State.retry on each; prints each id; exit 2 while relay go holds the state lock
relay go ... [--budget-grace F]
```

`_status` (`relay/cli.py:132-148`) prints spend by basis, for example `all time: N tokens, $X reported, $Y API-equivalent estimate (not subscription billing)`.

### `scripts/codex_shakedown.py`: the real Codex shakedown

```python
def main(argv: list[str]) -> int:
    """codex_shakedown.py --scratch <new empty dir> --attempt <n> [--relay <checkout>]
    Refuses a scratch that exists non-empty or lies inside a git work tree. Runs every phase even after a
    defect, and exits 0 only when the attempt has no defect."""

@dataclass(frozen=True)
class Finding:
    phase: str
    kind: Literal["expected", "defect"]
    what: str
    evidence: str            # path:line in the scratch, ledger line, or ps -p result
```

The script uses only the standard library. It builds a fresh scratch git repository with four pieces:
- a queue;
- roles under `<scratch>/roles`: lead, divvyer, researcher, architect, a helper `builder` that spawns a helper `scout`, and `scout`;
- a `.codex/hooks.json` probe hook in the scratch repository and one in its parent directory, each writing a marker file if it ever runs;
- a config whose `state_root`, `roles_dir` and `ping_command` all point inside the scratch.

| Section | What it holds |
|---|---|
| s1 | One JavaScript exec cell that calls `tools.exec_command` in a `for` loop, inside an `if`, and in an awaited `Promise.all`, creating `out/1.txt` to `out/3.txt` and `out/even.txt`. Its check tests every file. |
| s2 | The lead delegates to `builder` through native helper delivery. `builder` delegates a read to `scout`. Its check tests the file `builder` wrote. |
| s3 | A deliberate failure: the lead's last line is not a status line unless `REPAIRED` exists in the scratch root. |
| s4 | A long task that keeps working past a tiny budget. |

Phases run in order. Each declares its expected outcomes. A result matching a declaration is a `Finding` of kind `expected`. Anything else is a `defect`.

- **A. Hooks.** After every phase, neither probe marker exists. The run's JSON stdout and rollouts show no hook item. A process sample of each run's group shows no `claude_adapter.py` process.
- **B. Exec cells.** s1 is done. Its rollout shows the JS cell and each nested `exec_command` call.
- **C. Helpers.** s2 is done. The ledger's lead line carries `usage` entries for the lead, `builder` and `scout` threads, with `scout`'s parent being `builder`. Every entry is priced with dollars > 0 and `basis: api-estimate`. No thread appears twice.
- **D. Budget.** On s4, `relay go --dollar-budget <tiny> --budget-grace 0` exits 3. Progress shows a kill, not only a retire. The ledger holds the killed run's spend. `ps -p` on every recorded PID and `kill -0` on every recorded PGID find nothing.
- **E. Failure and recovery.**
  1. `relay go` exits 5 on s3. `relay failures` lists s3 with reason and log, and the ledger holds two `failure` lines; these are expected.
  2. The script creates `REPAIRED` and runs `relay retry <queue> s3`.
  3. `relay go` reruns until it exits 0 or three attempts are used.
  4. `relay status` shows every section done, and `git status --short` is clean.
- **F. Ask.** `relay ask` on a researched section. Its ledger line's usage is net of the research run's (no double count).

The script records each `relay go` PID and PGID at launch. After each phase it checks them with `ps -p` and kills only by recorded PGID. It prints one evidence block: attempt number, phases, exit codes, ledger excerpts, est. dollars, PID results, then every `Finding`, with defects listed last. It touches nothing outside the scratch except Codex's own new files under `~/.codex/sessions`. It never touches an existing session, the owner's hooks, role files, credentials, any other state root, or any running process.

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Hook exclusion and native enforcement settings | `relay/codex_launch.py` | Any Relay code that reads, writes, runs or imitates a hook, or edits `~/.codex/hooks.json`, `~/.codex/hooks/`, project `.codex/` files, credentials or `CODEX_HOME` |
| Proven CLI versions | `codex_launch.PROVEN` | A version check anywhere else |
| Codex role files, sandbox, approval, helpers | `relay/roles.py` | Reading role TOMLs or mapping Codex role names elsewhere |
| Token prices and dollar estimates | `relay/pricing.py`, `Config.prices` | A rate literal or token-to-dollar sum elsewhere; any default rate |
| Rollout parsing, thread tree, baselines | `relay/backends/codex_session.py` | Parsing rollouts or summing thread usage elsewhere |
| Backend capabilities | `backends.capabilities(name)` | `get_backend(...).capabilities` outside `relay/backends/` |
| Launch validation | `Backend.preflight`, called once by `relay go` and `relay ask` | Role, price or version checks in `argv` or the loop |
| Child environment | `Backend.env`, applied only in `run_agent` | `os.environ` writes or `env=` anywhere else |
| Budget and cap decisions, kill included | `loop._watcher` with `Ledger.over` | A budget check in a backend or the runner |
| Process start, kill and reap | `relay/runner.py` | `subprocess` or `os.killpg` in backends or modules. The shakedown's own recorded-PGID cleanup is the one exception |
| Section failure count, reason, clear and retry | `loop._fail`/`_failed_twice`, `State.record_failure`/`clear_failures`/`retry` | `s.failures` written anywhere else |
| Failure log lines | `Ledger.append_failure`, `progress.failed` | `print` of failures in `loop.py` |
| Researcher resume | `Invocation.resume` | Session ids in `research_command` |
| Map reuse and refresh | `docs/superpowers/specs/relay-research-reuse-design.md` Homes | Any map change in this design |
| Claude runtime | `relay/backends/claude.py`, `stream.feed`, the Claude defaults in `relay/config.py` | Any change to their behavior; the step 2 tests pin it |
| Claude test fakes | `tests/fakes/fake_claude.py` | A second Claude replayer |
| Codex fixtures | `tests/fixtures/codex-real/` (captured), `tests/fixtures/codex-native/` (synthetic, labelled) | Codex event text inline in more than one test module |
| Real model runs | `scripts/codex_shakedown.py` | Real model runs from pytest |
| Adapter judgment and shakedown evidence | `docs/codex-native-report.md` | Any claim about removing Relay's Claude backend, anywhere |

## Order

Every step lands on `codex-native`. No step merges or pushes. No step touches another worktree, edits `~/.codex` or `~/.claude`, stops a running Relay, Codex or HQPTuner job, or connects to Opal.

1. **Grounding** (`builder`): writes `docs/codex-native-report.md`, section Grounding. It reads `~/.codex/hooks.json` and `~/.codex/hooks/claude_adapter.py` read-only, and records:
   - **Translated hooks.** Each one's event, matcher, the Claude hook it invokes, and what it enforces. Each gets its outcome under `relay/codex_launch.py`: sandbox, writable roots, network, native rule, or dropped.
   - **CLI surface.** `codex --version`, `codex exec --help`, and the installed config schema's keys for:
     - sandbox, approval and `sandbox_workspace_write`;
     - native agent-role delivery;
     - features, including the JavaScript exec-cell feature;
     - exec-policy rules;
     - every hook layer the CLI loads (user home, project `.codex/` in cwd and ancestors, any system or managed layer) and the args that exclude each one.
   - **Exclusion proof.** In a scratch under `$TMPDIR`: a probe hook in a scratch repository's `.codex/` and its parent, and a run with the candidate args that leaves no marker. Then a run in the owner's home with the same args that shows no hook item in stdout or rollout and no adapter process. These runs are model-priced and their spend is unmeasured until run; the step discloses this before running them. This proof gives `PROVEN`'s first entry.
   - **Rollout fields.** The turn-context model field, the usage fields, the `session_meta` parent-thread field, and whether `total_token_usage` resets on `exec resume`.
   - **Rates.** Rates and read date from the pricing page for every model in the shakedown roles and the owner's `~/.codex/agents`.

   The step ends with `DESIGN:` in any of these cases:
   - some hook layer cannot be excluded on the installed CLI;
   - an owner-rule hook has no native form;
   - the CLI has no native agent-role delivery;
   - the CLI has no nested-thread parent field.
2. **Claude pin** (`test-writer`): writes `tests/test_backends.py`, `tests/test_loop.py`, `tests/test_config.py`, `tests/test_ledger.py` and `tests/test_runner.py`. The tests pin today's Claude behavior, and all of them pass on arrival at HEAD:
   - argv for every role, and the default commands;
   - stream-json tokens and dollars;
   - retire-only budget and section cap with no kill;
   - the `resume <id>` hint;
   - an inherited child environment;
   - no import of `relay.backends.claude` outside `relay/backends/`.
3. **Research reuse** (`lead`): carries `docs/research-reuse-queue.md` sections s1-s3 as cut. The `fix/research-reuse` worktree is not touched.
4. **Stub** (`builder`): writes `relay/codex_launch.py`, `relay/roles.py`, `relay/pricing.py`, `relay/backends/base.py`, `relay/stream.py` and `relay/backends/__init__.py`, with the Modules signatures raise-only and the new fields.
5. **Red: pricing** (`test-writer`): writes `tests/test_pricing.py` and `tests/test_config.py`.
6. **Pricing** (`builder`): writes `relay/pricing.py` and `relay/config.py`.
7. **Red: launch, roles, argv, env and preflight** (`test-writer`): writes `tests/test_codex_launch.py`, `tests/test_roles.py`, `tests/test_backends.py`, `tests/test_runner.py` and `tests/fixtures/codex-native/`.
8. **Launch, roles, argv, env and preflight** (`builder`): writes `relay/codex_launch.py`, `relay/roles.py`, `relay/backends/base.py`, `relay/backends/codex.py`, `relay/backends/claude.py`, `relay/backends/generic.py`, `relay/backends/__init__.py`, `relay/runner.py`, `relay/loop.py`, `relay/cli.py` and `relay/config.py`.
9. **Red: complete usage** (`test-writer`): writes `tests/test_codex_session.py`, `tests/test_backends.py` and `tests/fixtures/codex-native/`. Covers nested helpers, receivers also found by parent field, resume baselines and model splits.
10. **Complete usage** (`builder`): writes `relay/backends/codex_session.py`, `relay/backends/codex.py`, `relay/stream.py` and `relay/backends/__init__.py`.
11. **Red: budget termination and ledger basis** (`test-writer`): writes `tests/test_ledger.py`, `tests/test_loop.py` and `tests/test_cli.py`.
12. **Budget termination and ledger basis** (`builder`): writes `relay/ledger.py`, `relay/loop.py`, `relay/cli.py` and `relay/config.py`.
13. **Red: recoverable failures** (`test-writer`): writes `tests/test_state.py`, `tests/test_loop.py`, `tests/test_cli.py` and `tests/test_progress.py`. Covers the recut clear on same id and the explicit retry.
14. **Recoverable failures** (`builder`): writes `relay/state.py`, `relay/loop.py`, `relay/ledger.py`, `relay/progress.py` and `relay/cli.py`.
15. **Red: shakedown setup and verdicts** (`test-writer`): writes `tests/test_shakedown.py`. Covers the scratch refusals, the generated repository, roles, probes and config, and the classification of recorded evidence into expected findings and defects. No model runs.
16. **Shakedown script** (`builder`): writes `scripts/codex_shakedown.py`.
17. **User docs** (`builder`): writes `README.md`. Covers:
    - the hook exclusion and `PROVEN`;
    - native sandbox and approval, `roles_dir`, helpers;
    - `prices`, `budget_grace`, and estimates versus subscription billing;
    - failure rules, `relay failures` and `relay retry`.
18. **Full suite** (`lead`, writes nothing): `uv run pytest` passes.
19. **Shakedown attempt** (`builder`): runs `scripts/codex_shakedown.py --attempt <n>` in a new scratch under `$TMPDIR`, after disclosing the spend, which is model-priced, nonzero and unmeasured until the run. It writes `docs/codex-native-report.md` section Attempt `<n>`: the evidence block and every defect. It fixes nothing.
20. **Repair batch** (`test-writer` for the red tests, then `builder`): takes every defect from the last attempt as one batch. Writes the tests and the modules that each defect's evidence points to, under the Homes above. A defect that needs a new home ends with `DESIGN:`. Steps 18 to 20 repeat until an attempt reports no defect.
21. **Report** (`builder`): completes `docs/codex-native-report.md` with these sections:
    - **Dependency inventory**: the table above, re-anchored at HEAD.
    - **Translation adapter judgment**: the evidence that Relay Codex runs never invoke `~/.codex/hooks/claude_adapter.py` (phase A of the clean attempt, and the `PROVEN` args). Also whether anything outside Relay still needs it. That means the owner's interactive Codex sessions and any other tool whose Codex runs load `~/.codex/hooks.json`, each named with its evidence or recorded as unknown. The verdict is "Relay no longer needs it", plus "keep" or "unused" for everyone else. The file is never edited or deleted.
    - **Limitations.**
    - **PID cleanup**: each recorded PID with its `ps -p` result.
