Status: approved.

# Relay Codex-native enforcement without the translation adapter

## Why

This design replaces `docs/superpowers/specs/relay-codex-native-revision-design.md` whole. Every piece lands on branch `codex-native`, off main, and stays unmerged. `docs/codex-native-queue.md` is cut from the replaced design and no longer applies. Its section s1.d1 wrote the Grounding section of `docs/codex-native-report.md`, which this design builds on.

The goal: Relay's Codex runs never invoke `~/.codex/hooks/claude_adapter.py`, and every owner policy that the adapter carries is still enforced in those runs. `relay/backends/claude.py` and every Claude runtime behavior stay as they are.

**The replaced design cannot meet the goal.** It excludes every hook layer and enforces only through sandbox, network and exec-policy prefix rules. Grounding shows that this drops owner policy:
- The two change/edit budgets (`codex-change-budget.py`, `gauntlet-change-budget.py`) count calls since the last genuine user reply. The doc budget (`gauntlet-doc-budget.py`) checks byte and block caps after an edit. Sandbox and prefix rules express neither (`docs/codex-native-report.md:68-74`, `docs/codex-native-report.md:183-187`).
- Foreground-test denial needs the caller's identity and the execution mode. A prefix rule has neither (`docs/codex-native-report.md:26`).
- Excluding every hook also excludes the owner's non-adapter hooks: `agent-wait-policy.py` and `sync-claude.py --rules-hook` (`docs/codex-native-report.md:33-39`).
- Instruction delivery through the adapter's SessionStart `cat` is unverified once that hook is dropped (`docs/codex-native-report.md:22`).

**What the installed CLI offers instead.** `codex-cli 0.165.0` reports `hooks` stable and enabled (`docs/codex-native-report.md:109`). Its schema has inline `[hooks]` event tables and `[hooks.state]` enablement and trust records (`docs/codex-native-report.md:106`). `-c` overrides sit above every ordinary layer (`docs/codex-native-report.md:142-144`). Native Codex hooks receive Codex's own payloads, so a Relay-owned native hook enforces each policy without translation. Relay disables only the hooks that invoke the adapter and leaves every other hook running. The Feasibility conditions below say what Grounding must prove on the installed CLI before any of this launches.

**Copies and gaps in the tree.**
- **Permissions.** Every Codex run passes `--dangerously-bypass-approvals-and-sandbox` (`relay/backends/codex.py:64-67`).
- **Hooks.** Every Codex run inherits the owner's environment (`relay/runner.py:262-264` passes no `env`) and `CODEX_HOME` (`relay/backends/codex.py:26`), so it loads `~/.codex/hooks.json` and the adapter. The captured runs show the file loaded: `tests/fixtures/codex-real/stdout.jsonl:2`, `tests/fixtures/codex-warnings/research-stdout.jsonl:4`. No Relay module reads, selects or enforces a hook today (`grep -rni hook relay/` finds none).
- **Roles.** Codex role names are mapped twice: `relay/backends/codex.py:30-33` and `relay/config.py:59-74`. Claude's own mapping at `relay/backends/claude.py:19-28` stays. Roles are read only from `$CODEX_HOME/agents` (`relay/backends/codex.py:36`). The owner's `researcher.toml` has no model field (`docs/codex-native-report.md:162-163`). A researcher follow-up passes its session id through `research_command` (`relay/loop.py:375`, `relay/backends/codex.py:57-60`).
- **Capability lookup** is copied four times: `relay/loop.py:358`, `relay/loop.py:402`, `relay/loop.py:615`, `relay/ledger.py:167-170`.
- **Dollars.** `CodexBackend.capabilities.dollars` is False (`relay/backends/codex.py:23`), so `Ledger.over` (`relay/ledger.py:159`) ignores Codex dollar budgets.
- **Usage.** Helper threads are found only in the run's own stdout `collab_tool_call` items (`relay/backends/codex.py:98-99`). A helper's own helpers are never seen, and `poll` meters only the run's thread (`relay/backends/codex.py:128-133`). A resumed `ask` reads `total_token_usage` from the pre-resume size (`relay/backends/codex_session.py:38-46`), which may still count earlier turns.
- **Budget.** The watcher can only ask for a retire (`relay/loop.py:405-437`).
- **Failures.** `State.record_failure` only increments and keeps no reason (`relay/state.py:277-282`). `mark_done` does not clear `failures` (`relay/state.py:123-126`). A recut that rewrites a section under the same id keeps the old count (`relay/loop.py:802-806`). `relay/cli.py:28-52` has no `retry`.
- **Claude behavior** is pinned only by the existing `tests/test_backends.py`, `tests/test_loop.py`, `tests/test_ledger.py` and `tests/test_config.py`.
- **Research reuse.** `docs/superpowers/specs/relay-research-reuse-design.md` and `docs/research-reuse-queue.md` are on `codex-native` and are built as cut.

### Dependency inventory

| Dependency | Where | Outcome |
|---|---|---|
| Hooks whose command invokes `claude_adapter.py`, in any layer | loaded by every Relay Codex run | Disabled per run by `codex_launch`. Each one's policy is enforced by Relay's native hook. Neither the adapter nor any hook file is edited. |
| Every other hook (`agent-wait-policy.py`, `sync-claude.py --rules-hook`, project `.codex/` hooks) | same | Left enabled. They are already native. |
| `--dangerously-bypass-hook-trust` | `docs/codex-native-report.md:87-89` | Never passed. It would run untrusted hooks. |
| Codex bypass flag | `relay/backends/codex.py:65`, `relay/backends/codex.py:67` | Removed. The role's sandbox and approval settings replace it. |
| Claude `--agent`, `--permission-mode bypassPermissions`, stream-json, `resume <id>` hint, `claude-ping` | `relay/config.py`, `relay/stream.py`, `relay/backends/claude.py:39-40` | Claude only, unchanged. |
| `CODEX_HOME`, credentials, `~/.codex/sessions` | `relay/backends/codex.py:26` | Unchanged. Relay never sets `CODEX_HOME`. |

## Modules

### `relay/codex_launch.py`: the launch that turns the adapter off and Relay's hook on

```python
@dataclass(frozen=True)
class HookSurface:
    """The installed CLI's hook keys, as Grounding proves them on one version."""
    list_args: tuple[str, ...]   # model-free args after "codex" that print every discovered hook
    disable: str                 # -c template disabling one discovered hook; "{key}" is its state key
    inline: str                  # -c template adding one inline hook; "{event}", "{matcher}", "{command}"
    trust: str                   # -c template trusting one inline hook; "{key}"
    deny: str                    # how a PreToolUse hook denies: "exit2" or "json"

PROVEN: dict[str, HookSurface]
"""Each `codex --version` on which Grounding or a shakedown attempt proved every Feasibility condition."""

@dataclass(frozen=True)
class DiscoveredHook:
    key: str                     # the CLI's state key
    layer: str                   # user, project, profile, system, managed or plugin
    event: str
    matcher: str | None
    command: tuple[str, ...]
    disableable: bool

@dataclass(frozen=True)
class Launch:
    argv_prefix: tuple[str, ...]          # "codex", "exec", the disables, Relay's hooks, the role's settings
    env: dict[str, str]                   # added to the inherited environment; never CODEX_HOME
    home: Path                            # inherited CODEX_HOME, else ~/.codex
    disabled: tuple[DiscoveredHook, ...]  # the adapter hooks this run turns off

def version(cfg: Config) -> str:
    """`codex --version` through runner.capture. ConfigError when it cannot run."""
    raise NotImplementedError

def check(cfg: Config) -> str:
    """The installed version. ConfigError when it is not a key of PROVEN."""
    raise NotImplementedError

def discover(cfg: Config, cwd: Path, ver: str) -> tuple[DiscoveredHook, ...]:
    """Every hook the CLI loads for `cwd`, from PROVEN[ver].list_args through runner.capture.
    ConfigError when the listing cannot run or parse."""
    raise NotImplementedError

def adapter_hooks(hooks: tuple[DiscoveredHook, ...]) -> tuple[DiscoveredHook, ...]:
    """The hooks whose command has a word whose basename is claude_adapter.py. ConfigError when
    one is not disableable."""
    raise NotImplementedError

def launch(cfg: Config, inv: Invocation, role: Role, helpers: tuple[Role, ...], ver: str,
           plan: policy.Plan) -> Launch:
    """A disable for each of plan's adapter hooks; one trusted inline hook per event in
    plan.events, running `<sys.executable> -m relay.codex_hooks <event> --plan <inv.plan>`;
    the role's sandbox, approval, network, writable roots, model, effort, instructions and
    features; each helper through the CLI's native agent-role keys; `exec resume <inv.resume>`
    for an ask."""
    raise NotImplementedError
```

Every value in `HookSurface` comes from Grounding. Nothing in this module guesses a key.

### `relay/policy.py`: the owner policies the adapter carries, as native decisions

```python
Rule = Literal["change_budget", "foreground_tests", "doc_budget", "instructions"]

@dataclass(frozen=True)
class Cover:
    outcome: Literal["enforced", "native", "dropped"]
    rule: Rule | None            # set only when outcome is "enforced"

COVERS: dict[str, Cover]
"""Each adapter target (the basename of the command the adapter runs) mapped to its outcome."""

@dataclass(frozen=True)
class Limits:
    changes: int
    edits_in: int
    edits_out: int
    host_changes: int            # limits for host commands (sudo, docker, podman, systemctl, rm)
    host_edits_in: int
    host_edits_out: int

LIMITS: dict[str, Limits]        # keyed by adapter target
DOCS: dict[str, tuple[int, int]] # governed path relative to the scope root -> (byte cap, block cap)
EXEMPT: frozenset[str]           # agent names exempt from foreground-test denial
SCRATCH: tuple[str, ...]         # temporary roots under which rm is not host-limited

@dataclass(frozen=True)
class Entry:
    """One disabled adapter hook, as Relay enforces it."""
    rule: Rule
    event: str
    matcher: str | None
    scope: Path | None           # None for scope "*"
    target: str
    args: tuple[str, ...]        # the target's own arguments, e.g. the instructions file

@dataclass(frozen=True)
class Plan:
    role: str                    # the Relay role's agent name
    cwd: Path
    entries: tuple[Entry, ...]   # only those whose scope covers cwd
    adapters: tuple[str, ...]    # state keys of every disabled adapter hook
    events: tuple[str, ...]      # native events Relay's hook must receive
    counters: Path
    log: Path

@dataclass(frozen=True)
class Call:
    thread: str
    agent: str                   # the thread's agent name; the run's role for the root thread
    tool: str
    command: str | None
    paths: tuple[Path, ...]
    background: bool

@dataclass(frozen=True)
class Count:
    changes: int = 0
    edits_in: int = 0
    edits_out: int = 0
    host: int = 0

@dataclass(frozen=True)
class Verdict:
    allow: bool
    reason: str | None = None    # shown to the model on a deny or a post-edit finding
    context: str | None = None   # added model context (SessionStart)

def plan(cfg: Config, inv: Invocation, role: str, adapters: tuple[DiscoveredHook, ...]) -> Plan:
    """Parse each adapter hook's scope, target and args. ConfigError for a target not in COVERS.
    A missing --scope resolves as the adapter does: the legacy-scope file, else ~/dev/gauntlet.
    A scope covers cwd when cwd lies under it or shares its git common dir."""
    raise NotImplementedError

def classify(call: Call, cwd: Path) -> Count:
    """What one call adds to the thread's count. Read-only waits, views and a lone ping-me add nothing."""
    raise NotImplementedError

def pre(plan: Plan, count: Count, call: Call) -> Verdict:
    """Deny when any change_budget entry's limits would be passed by this call, or when a
    foreground_tests entry applies, call.agent is not in EXEMPT, call.background is False and the
    command has a test, check or lint command position."""
    raise NotImplementedError

def post(plan: Plan, call: Call) -> Verdict:
    """A finding for each touched DOCS path over its caps, under a doc_budget entry's scope."""
    raise NotImplementedError

def session_start(plan: Plan) -> Verdict:
    """Context holding each instructions entry's file, in entry order."""
    raise NotImplementedError
```

Each Grounding finding has one outcome:

| Adapter target | Outcome | How |
|---|---|---|
| `codex-change-budget.py`, `gauntlet-change-budget.py` | enforced, `change_budget` | `pre` against per-thread counts. Every entry in scope applies, so the stricter limit wins, as under the adapter. A Relay run has no genuine user reply mid-run, so each count runs from the run's start. |
| `no-foreground-tests.py` | enforced, `foreground_tests` | `pre` |
| `gauntlet-doc-budget.py` | enforced, `doc_budget` | `post`. Both configured entries (legacy scope and `*`) become entries. |
| `cat` | enforced, `instructions` | `session_start` delivers the file the adapter entry names, in its scope. |
| `no-foreground-agents.py` | native | Codex helpers are asynchronous. Shakedown phase C proves this. |
| `true`, `cc-status`, `context-watch` | dropped | Bookkeeping, notification and lifecycle reminders. Relay's `ping` and `progress` report the run lifecycle. |

`LIMITS`, `DOCS`, `EXEMPT`, `SCRATCH`, the command positions that count as test, check, lint, change or edit, and the adapter's argument form all come from Grounding's read of the owner's scripts. A target that Grounding finds and `COVERS` lacks stops the launch.

### `relay/codex_hooks.py`: the one native hook Relay installs

```python
def main(argv: list[str]) -> int:
    """python -m relay.codex_hooks <event> --plan <path>. Reads one native payload on stdin and
    answers in the native form PROVEN records. PreToolUse: policy.pre, and the count is updated
    only on allow. PostToolUse: policy.post. SessionStart: policy.session_start. A payload or plan
    that cannot be read denies a PreToolUse and reports a finding otherwise. Every verdict is
    appended to plan.log as one JSON line."""
    raise NotImplementedError

def call(payload: dict, plan: policy.Plan) -> policy.Call:
    """The native payload as a Call: thread, agent, tool, command, touched paths, background."""
    raise NotImplementedError

class Counters:
    """Per-thread counts in plan.counters, read and written under an fcntl lock, because helper
    threads call the hook concurrently."""
    def __init__(self, path: Path): ...
    def get(self, thread: str) -> policy.Count: ...
    def add(self, thread: str, count: policy.Count) -> policy.Count: ...
```

The module imports only the standard library and `relay.policy`. It starts no process.

### Feasibility conditions

Grounding proves each condition on the installed CLI. A failed condition ends Grounding with `DESIGN:`, and nothing launches on that CLI.

| # | Condition | Proof |
|---|---|---|
| F1 | A model-free command lists every hook the CLI loads for a cwd, in every layer, with its state key, layer, event, matcher, command and whether it can be disabled. | `app-server --print-startup-config` or another listed command, run in a scratch with probe hooks in a repo's `.codex/` and its parent. |
| F2 | A `-c` override disables one listed hook by key in every layer where an adapter hook can live, and the listing shows the hook disabled. | Model-free listing, then one priced run that leaves the disabled probe's marker absent. |
| F3 | An inline `-c` hook loads and runs once a `-c` trust record is added, without `--dangerously-bypass-hook-trust`. | Priced run with a probe inline hook. |
| F4 | PreToolUse fires before every shell or `exec_command` call, every `apply_patch`, every nested tool call in a code-mode exec cell, and every spawn or message call, in the root thread and in helper threads. A deny blocks the call. | Priced run with a denying probe. |
| F5 | PostToolUse fires after `apply_patch` with the touched paths, and its finding reaches the model. | Priced run. |
| F6 | SessionStart output becomes model context in the root thread and in helper threads. | Priced run. |
| F7 | The payload carries the thread id, and either the payload or the thread's rollout `session_meta` gives a helper's agent name. | Priced run with one helper. |
| F8 | A hook process runs outside the run's sandbox: it can write the run directory, which the agent cannot. | Priced run in `workspace-write`. |
| F9 | The native form of a background `exec_command`, or a record that none exists. | Help text and payload from F4's run. |

Hooks that are not adapter hooks keep running. Their effect on a run is part of the shakedown evidence.

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
    """ConfigError naming the file when it is missing or unreadable, a key has the wrong type, model is
    absent, sandbox is not in SANDBOXES, approval_policy is anything but "never", or a writable root
    lies under ~/.claude, ~/.codex or cfg.state_root."""
    raise NotImplementedError

def helpers(cfg: Config) -> tuple[Role, ...]:
    """Every *.toml in roles_dir whose stem is not a RELAY_ROLES value, sorted by name, validated as
    load validates. Sandbox defaults to workspace-write."""
    raise NotImplementedError
```

Role-file keys are `developer_instructions`, `model`, `model_reasoning_effort`, `sandbox_mode`, `approval_policy`, `[sandbox_workspace_write] network_access, writable_roots` and `[features]`, with the names and types Grounding recorded (`docs/codex-native-report.md:101-104`). `danger-full-access` is refused. Writable roots are the run's cwd and the cwd's git common dir. `Config` gains `roles_dir: Path | None = None`. `roles` replaces `relay/backends/codex.py:30-56`. A `researcher.toml` without a model stops `relay go` at preflight with that file named.

### `relay/pricing.py`: Relay-owned API-equivalent rates

```python
SOURCE = "https://developers.openai.com/api/docs/pricing"
AS_OF: str                                   # the read date Grounding records

@dataclass(frozen=True)
class Rate:
    input: float          # USD per 1M uncached input tokens
    cached_input: float
    output: float         # reasoning tokens are part of output

RATES: dict[str, Rate]    # gpt-6-astra and gpt-6.1-sol from docs/codex-native-report.md:173-174, plus each shakedown model

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

`Config` gains `prices: dict[str, Rate]` from `[prices."<model>"]` tables, each value finite and non-negative. Codex dollars are an API-equivalent estimate, not subscription billing. The ledger and `relay status` say so.

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
    plan: Path                  # <log>.policy.json, beside the run's log
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

`relay/backends/__init__.py` gains `capabilities(name) -> Capabilities`, replacing the four copies. For Claude, `argv` returns what it returns today for the same role, `env` is `{}`, and `preflight` is a no-op. Generic works the same way. `run_agent` (`relay/runner.py:213-234`) builds the `Invocation` and passes `{**os.environ, **backend.env(inv, cfg)}` to `Popen`. An empty `env` leaves the child's environment exactly as today. `loop.ask` passes `resume=session` and stops rewriting `research_command`.

### `relay/stream.py`

```python
@dataclass
class StreamState:
    ...                                   # existing fields unchanged
    usage: tuple[Usage, ...] = ()         # Codex only: one entry per thread and model, net of any resume baseline
    fault: str | None = None              # a backend demand to end the run now
```

`feed` is unchanged. `_snapshot` (`relay/backends/__init__.py:30`) restores both fields.

### `relay/backends/codex_session.py`: complete usage

```python
@dataclass(frozen=True)
class ThreadUsage:
    thread: str
    parent: str | None
    agent: str | None             # the helper's agent name from session_meta
    usage: tuple[Usage, ...]      # per model, net of baseline

class ThreadTree:
    """Every thread a run owns: its own thread, each collab receiver, and transitively each thread whose
    session_meta names an owned thread as its parent. Each thread is counted once."""
    def __init__(self, home: Path, root: str, *, boundary: dict[Path, int] | None = None): ...
    def add_receivers(self, threads: Iterable[str]) -> None: ...
    def poll(self, *, force_scan: bool = False) -> tuple[ThreadUsage, ...]: ...
    def unobserved(self) -> tuple[str, ...]: ...    # owned threads with no telemetry yet

def agent_of(home: Path, thread: str) -> str | None:
    """A thread's agent name from its rollout session_meta; used by codex_hooks when F7 places it there."""
```

- **Baseline.** For a thread that existed before the run (a resume), the baseline is the last `total_token_usage` before the boundary. The run's usage is the current total minus that baseline, per field. A thread first seen during the run has a zero baseline.
- **No double counting.** A thread is keyed by id and its total is its latest cumulative value.
- **Models.** Turn-context records split each thread's usage per model.
- `SessionReader` stays the per-file reader and is the only code that parses rollout files.

### `relay/backends/codex.py`

`capabilities = Capabilities(context=True, tokens=True, dollars=True, subagents=True, resume=True, budget_kill=True, basis="api-estimate")`.

- **`argv`** runs `codex_launch.discover` and `adapter_hooks` for the run's cwd, builds `policy.plan`, writes it to `inv.plan`, and returns `codex_launch.launch(...).argv_prefix` plus `--json -C <cwd> -o <output> -`, or the resume form for an ask. It never passes either bypass flag.
- **`env`** returns `Launch.env`.
- **`preflight`** runs `codex_launch.check`, discovers the hooks for the queue's cwd and builds a plan (so an uncovered adapter target stops here), loads every Relay role and helper, and prices every model. A `ConfigError` or `Unpriced` stops `relay go` and `relay ask` with exit 2 before any run.
- **`poll`** feeds receivers into a `ThreadTree` rooted at the run's thread. `spend.tokens` sums the tree, and `spend.dollars` is `pricing.dollars` over it. `context_tokens` comes from the run's own thread. An unpriced model sets `fault`.
- **`finish`** behaves as today (`relay/backends/codex.py:135-146`) and also marks the run an error when `unobserved()` is non-empty.

### `relay/ledger.py`

`append` gains `basis` and `usage`. Each line carries `"basis"`, plus `"usage": [{thread, parent, model, input, cached_input, output}]` when usage is present. `append_failure(kind, section, session, reason, log)` writes a zero-spend `failure` line. `totals_by_basis(since)` serves `relay status`. `over` takes capabilities from `backends.capabilities`.

### `relay/loop.py`: bounded budget termination and failure rules

```python
@dataclass
class _Watch:
    on_event: Callable[[StreamState], Literal["go", "retire", "kill"]]
    budget_hit: bool = False
    budget_killed: bool = False
    idle_retired: bool = False
```

**Budget termination**, on a backend with `budget_kill`:
1. A budget or section-cap hit asks for a retire, as today.
2. Spend past the limit by more than `cfg.budget_grace` (a fraction of that limit, default 0.1, `--budget-grace F`) returns `"kill"` and sets `budget_killed`. The runner's `_kill_and_reap` (`relay/runner.py:161`) carries out the kill: SIGTERM to the group, `_GRACE_SECONDS` (`relay/runner.py:28`), SIGKILL, then a check that the group is gone.
3. The killed run is ledgered with its spend, and `relay go` exits 3. A budget kill is never a failure.

A backend without `budget_kill`, Claude included, only retires, as today. `relay go` and `relay ask` call `preflight` once before any run. A `stream.fault` returns `"kill"` and counts as a failure.

**Failure rules**, on every backend:
1. **What counts.** A failure is a run that `run_failed` reports, a lead with no status line, a `fault`, or a failed recut. Each is recorded with `State.record_failure(sid, reason, log)` and `Ledger.append_failure`. A budget kill, a stop file, an interrupt and an idle retire are not failures. A policy denial is not a failure. It counts only when the run then ends in one of these failures.
2. **Retry once.** At count 1, the next pass runs a fresh lead whose guidance reads `Relay's previous run on this section failed: <reason>. Log: <path>.`
3. **Stop at two.** At `FAILURE_LIMIT`, `relay go` exits 5. On restart, `_run_section` exits 5 before research or lead while the count is at the limit.
4. **Clear.** The count, reason and log are cleared by a lead that ends with a parsed status, by `mark_done`, by `relay answer`, by `relay retry`, and by a successful recut whose section keeps its id and whose own entry changed (`relay/loop.py:802-806`). A recut that leaves the entry unchanged keeps the count.
5. **Retry after a fix.** `relay retry` is the only way to reopen a section stopped at the limit. It sets status to open and clears `failures`, `failure`, `failure_log`, `design_failures` and `design_failure`. The next lead's guidance reads `The owner fixed the blocker and retried this section. The last failure was: <reason>. Log: <path>.` Spend, sessions, maps and answers are untouched.

`_fail` and `_failed_twice` are the one home. Both call sites and the recut clear go through them.

### `relay/state.py`

`SectionState` gains `failure: str | None = None` and `failure_log: str | None = None`. `record_failure(sid, reason, log) -> int` replaces `record_failure(sid)`. It adds `clear_failures(sid)`, `retry(sid, guidance)` and `failed_sections()`. `mark_done` and `set_answer` also clear `failures`.

### `relay/cli.py`

```text
relay failures <queue.md>                          # "<sid> | failures <n> | design <n> | <reason> | <log>"; exit 0
relay retry <queue.md> (<section-id>... | --all)   # State.retry on each; prints each id; exit 2 while relay go holds the state lock
relay go ... [--budget-grace F]
```

`_status` (`relay/cli.py:132`) prints spend by basis, for example `all time: N tokens, $X reported, $Y API-equivalent estimate (not subscription billing)`.

### `scripts/codex_shakedown.py`: the real Codex shakedown

```python
def main(argv: list[str]) -> int:
    """codex_shakedown.py --scratch <new empty dir> --attempt <n> [--relay <checkout>]
    Refuses a scratch that exists non-empty or lies inside a git work tree. Runs every phase even after
    a defect, and exits 0 only when the attempt has no defect."""

@dataclass(frozen=True)
class Finding:
    phase: str
    kind: Literal["expected", "defect"]
    what: str
    evidence: str            # path:line in the scratch, ledger line, hook-log line, or ps -p result
```

The script uses only the standard library. It builds a fresh scratch git repository with:
- a queue;
- roles under `<scratch>/roles`: lead, divvyer, researcher, architect, a helper `builder` that spawns a helper `scout`, and `scout`;
- in the scratch repository's `.codex/hooks.json` and in its parent's, a fake `claude_adapter.py` hook for each enforced target, scoped to the scratch, that writes marker `A` if it ever runs, and a plain probe hook that writes marker `P`;
- a governed doc from `DOCS` under the scratch;
- a config whose `state_root`, `roles_dir` and `ping_command` all point inside the scratch.

| Section | What it holds |
|---|---|
| s1 | One JavaScript exec cell calling `tools.exec_command` in a `for` loop, inside an `if`, and in an awaited `Promise.all`, creating `out/1.txt` to `out/3.txt` and `out/even.txt`. |
| s2 | The lead delegates to `builder`, which delegates a read to `scout`. |
| s3 | A deliberate failure: the lead's last line is not a status line unless `REPAIRED` exists. |
| s4 | A long task that keeps working past a tiny budget. |
| s5 | The lead makes more separate changes than the scratch-scoped `change_budget` allows, one inside a JS exec cell. |
| s6 | The architect role grows the governed doc past its caps, then runs a foreground test command. |

Phases run in order. Each declares its expected outcomes. A matching result is an `expected` Finding; anything else is a `defect`.

- **A. Hooks.** Marker `A` never exists. Marker `P` exists. No run's process group ever shows a `claude_adapter.py` process. Each run's plan file lists every fake adapter hook as disabled. In the owner's home, the plan lists the owner's adapter hooks and `ps` shows no adapter process.
- **B. Exec cells.** s1 is done, and its hook log has one PreToolUse verdict per nested `exec_command`.
- **C. Helpers.** s2 is done. The lead's ledger line carries usage for the lead, `builder` and `scout` threads, with `scout`'s parent `builder`, each priced with dollars > 0 and `basis: api-estimate`, and no thread twice. The hook log shows verdicts from all three threads, each with its agent name. The lead keeps acting while `builder` runs.
- **D. Budget.** On s4, `relay go --dollar-budget <tiny> --budget-grace 0` exits 3. Progress shows a kill, and the ledger holds the killed run's spend.
- **E. Failure and recovery.** `relay go` exits 5 on s3, and `relay failures` lists s3 with reason and log. The script creates `REPAIRED` and runs `relay retry <queue> s3`. `relay go` then reruns until it exits 0 or three attempts are used. `relay status` shows every section done, and `git status --short` is clean.
- **F. Ask.** `relay ask` on a researched section. Its ledger line's usage is net of the research run's.
- **G. Policy.** On s5, the hook log shows a deny at the first call past the limit, the JS-cell call included, and no change past it lands. On s6, the hook log shows a doc finding after the oversized edit and a deny of the foreground test. The rollout shows that both reached the model. An uncovered fake adapter target in a second scratch config makes `relay go` exit 2 before any run.

The script records each `relay go` PID and PGID at launch, checks them with `ps -p` after each phase, and kills only by recorded PGID. It prints one evidence block: attempt number, phases, exit codes, ledger and hook-log excerpts, estimated dollars, PID results, then every Finding, with defects last. It touches nothing outside the scratch except Codex's own new files under `~/.codex/sessions`.

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Which discovered hooks a run disables, and Relay's hook installation | `relay/codex_launch.py` | Editing any hook file, `~/.codex`, `~/.claude`, project `.codex/`, credentials or `CODEX_HOME`; `--dangerously-bypass-hook-trust`; disabling a hook that does not invoke the adapter |
| Proven CLI versions and hook keys | `codex_launch.PROVEN` | A version check or a hook key literal anywhere else |
| Owner-policy decisions, limits, governed docs, exemptions, scopes, adapter coverage | `relay/policy.py` | A budget, doc-cap or command-position rule anywhere else; running, importing or translating a payload for any owner hook script |
| Native hook payloads, answers, per-thread counters, the hook log | `relay/codex_hooks.py` | Reading a hook payload or writing `<log>.policy.json`'s counters anywhere else |
| Codex role files, sandbox, approval, helpers | `relay/roles.py` | Reading role TOMLs or mapping Codex role names elsewhere |
| Token prices and dollar estimates | `relay/pricing.py`, `Config.prices` | A rate literal or token-to-dollar sum elsewhere; any default rate |
| Rollout parsing, thread tree, baselines, a thread's agent name | `relay/backends/codex_session.py` | Parsing rollouts elsewhere, `codex_hooks` included |
| Backend capabilities | `backends.capabilities(name)` | `get_backend(...).capabilities` outside `relay/backends/` |
| Launch validation | `Backend.preflight`, called once by `relay go` and `relay ask` | Role, price, version or coverage checks in the loop |
| Child environment | `Backend.env`, applied only in `run_agent` | `os.environ` writes or `env=` anywhere else |
| Spend-budget and cap decisions, kill included | `loop._watcher` with `Ledger.over` | A spend-budget check in a backend, the runner or a hook |
| Process start, kill and reap | `relay/runner.py` | `subprocess` or `os.killpg` in backends or modules; the shakedown's recorded-PGID cleanup is the one exception |
| Section failure count, reason, clear and retry | `loop._fail`/`_failed_twice`, `State.record_failure`/`clear_failures`/`retry` | `s.failures` written anywhere else |
| Failure log lines | `Ledger.append_failure`, `progress.failed` | `print` of failures in `loop.py` |
| Researcher resume | `Invocation.resume` | Session ids in `research_command` |
| Map reuse and refresh | `docs/superpowers/specs/relay-research-reuse-design.md` Homes | Any map change in this design |
| Claude runtime | `relay/backends/claude.py`, `stream.feed`, the Claude defaults in `relay/config.py` | Any change to their behavior; step 2's tests pin it |
| Claude test fakes | `tests/fakes/fake_claude.py` | A second Claude replayer |
| Codex fixtures | `tests/fixtures/codex-real/` (captured), `tests/fixtures/codex-native/` (synthetic, labelled), including native hook payloads | Codex event or hook-payload text inline in more than one test module |
| Real model runs | `scripts/codex_shakedown.py` and Grounding's disclosed probe runs | Real model runs from pytest |
| Grounding, feasibility proof, shakedown evidence, adapter judgment | `docs/codex-native-report.md` | Any claim about removing Relay's Claude backend, anywhere |

## Order

Every step lands on `codex-native`. No step merges or pushes. No step touches another worktree, edits `~/.codex` or `~/.claude`, stops a running Relay, Codex or HQPTuner job, or connects to Opal.

1. **Grounding: hook surface and feasibility** (`builder`): writes `docs/codex-native-report.md`, adding to its Grounding section. It reads the owner's hook files and scripts read-only and records:
   - the adapter's command-line form (scope flag, target, target args) and the legacy-scope file's contents;
   - for `policy.py`: each change/edit budget's limits and command classes, the scratch roots for `rm`, the foreground-test command positions, the exempt agent names, the background form, and the governed docs with their caps;
   - `sync-claude.py --rules-hook` and `cc-status` behavior;
   - F1 to F9, each proved or failed, with the `HookSurface` values for `PROVEN`'s first entry;
   - the rollout fields: turn-context model, usage fields, `session_meta` parent and agent name, and whether `total_token_usage` resets on `exec resume`.

   F2 to F8 need model runs in a scratch under `$TMPDIR`. They are model-priced, and their spend is unmeasured until run; the step discloses this before running them. It ends with `DESIGN:` when any condition fails or the CLI has no native agent-role delivery.
2. **Claude pin** (`test-writer`): writes `tests/test_backends.py`, `tests/test_loop.py`, `tests/test_config.py`, `tests/test_ledger.py` and `tests/test_runner.py`. The tests pin today's Claude behavior and pass at HEAD on arrival: argv for every role and the default commands; stream-json tokens and dollars; a retire-only budget and section cap; the `resume <id>` hint; an inherited child environment; no import of `relay.backends.claude` outside `relay/backends/`.
3. **Research reuse** (`lead`): carries `docs/research-reuse-queue.md` sections s1 to s3 as cut. The `fix/research-reuse` worktree is not touched.
4. **Stub** (`builder`): writes `relay/codex_launch.py`, `relay/policy.py`, `relay/codex_hooks.py`, `relay/roles.py`, `relay/pricing.py`, `relay/backends/base.py`, `relay/stream.py` and `relay/backends/__init__.py`, with the Modules signatures raise-only and the new fields.
5. **Red: pricing** (`test-writer`): writes `tests/test_pricing.py` and `tests/test_config.py`.
6. **Pricing** (`builder`): writes `relay/pricing.py` and `relay/config.py`.
7. **Red: policy decisions** (`test-writer`): writes `tests/test_policy.py`. Covers coverage and uncovered targets, scope resolution (legacy, `*`, sibling worktrees), every rule's allow and deny, and the stricter limit winning.
8. **Policy decisions** (`builder`): writes `relay/policy.py`.
9. **Red: native hook entry** (`test-writer`): writes `tests/test_codex_hooks.py` and `tests/fixtures/codex-native/`. Covers payload parsing per event, answers in the proven form, fail-closed PreToolUse, per-thread counting under concurrent calls, and the hook log.
10. **Native hook entry** (`builder`): writes `relay/codex_hooks.py` and `relay/backends/codex_session.py` (`agent_of` only).
11. **Red: launch, roles, argv, env and preflight** (`test-writer`): writes `tests/test_codex_launch.py`, `tests/test_roles.py`, `tests/test_backends.py`, `tests/test_runner.py` and `tests/fixtures/codex-native/`. Covers discovery parsing, adapter selection, a non-disableable adapter hook, the plan file, and that non-adapter hooks are never disabled.
12. **Launch, roles, argv, env and preflight** (`builder`): writes `relay/codex_launch.py`, `relay/roles.py`, `relay/backends/base.py`, `relay/backends/codex.py`, `relay/backends/claude.py`, `relay/backends/generic.py`, `relay/backends/__init__.py`, `relay/runner.py`, `relay/loop.py`, `relay/cli.py` and `relay/config.py`.
13. **Red: complete usage** (`test-writer`): writes `tests/test_codex_session.py`, `tests/test_backends.py` and `tests/fixtures/codex-native/`. Covers nested helpers, receivers also found by parent field, resume baselines and model splits.
14. **Complete usage** (`builder`): writes `relay/backends/codex_session.py`, `relay/backends/codex.py`, `relay/stream.py` and `relay/backends/__init__.py`.
15. **Red: budget termination and ledger basis** (`test-writer`): writes `tests/test_ledger.py`, `tests/test_loop.py` and `tests/test_cli.py`.
16. **Budget termination and ledger basis** (`builder`): writes `relay/ledger.py`, `relay/loop.py`, `relay/cli.py` and `relay/config.py`.
17. **Red: recoverable failures** (`test-writer`): writes `tests/test_state.py`, `tests/test_loop.py`, `tests/test_cli.py` and `tests/test_progress.py`. Covers the recut clear on the same id and the explicit retry.
18. **Recoverable failures** (`builder`): writes `relay/state.py`, `relay/loop.py`, `relay/ledger.py`, `relay/progress.py` and `relay/cli.py`.
19. **Red: shakedown setup and verdicts** (`test-writer`): writes `tests/test_shakedown.py`. Covers the scratch refusals; the generated repository, roles, fake adapter and probe hooks, governed doc and config; and the classification of recorded evidence into findings. No model runs.
20. **Shakedown script** (`builder`): writes `scripts/codex_shakedown.py`.
21. **User docs** (`builder`): writes `README.md`. Covers adapter-hook disabling and `PROVEN`; the policies Relay enforces natively and where their verdicts are logged; native sandbox and approval, `roles_dir` and helpers; `prices`, `budget_grace`, and estimates versus subscription billing; failure rules, `relay failures` and `relay retry`.
22. **Full suite** (`lead`, writes nothing): `uv run pytest` passes.
23. **Shakedown attempt** (`builder`): runs `scripts/codex_shakedown.py --attempt <n>` in a new scratch under `$TMPDIR`, after disclosing the spend, which is model-priced, nonzero and unmeasured until run. It writes `docs/codex-native-report.md` section Attempt `<n>`: the evidence block and every defect. It fixes nothing.
24. **Repair batch** (`test-writer` for the red tests, then `builder`): takes every defect from the last attempt as one batch, and writes the tests and modules each defect's evidence points to, under the Homes above. A defect that needs a new home ends with `DESIGN:`. Steps 22 to 24 repeat until an attempt reports no defect.
25. **Report** (`builder`): completes `docs/codex-native-report.md` with these sections:
    - **Dependency inventory**: the table above, re-anchored at HEAD.
    - **Policy coverage**: each adapter target with its outcome and the phase A, B, C or G evidence for it.
    - **Translation adapter judgment**: the evidence that Relay Codex runs never invoke `~/.codex/hooks/claude_adapter.py`, and whether anything outside Relay still needs it, each user named with evidence or recorded as unknown. The verdict is "Relay no longer needs it", plus "keep" or "unused" for everyone else. The file is never edited or deleted.
    - **Limitations.**
    - **PID cleanup**: each recorded PID with its `ps -p` result.

## Decisions for the owner

1. **Where the native form of the owner's hook policies lives.**
   - **Recommendation:** Relay keeps its own native copy in `relay/policy.py`, scoped to Relay's Codex runs. The owner's hook scripts and every Claude or interactive Codex session stay untouched. Cost: two copies of each policy's limits and command classes, Relay's and the owner's scripts'. A change to an owner script does not reach Relay until `policy.py` is changed to match. The coverage check catches only a new adapter target, not a changed limit.
   - **Alternative:** each owner policy script gains a native Codex input mode, and Relay's hook calls those scripts directly, so each policy has one home for Claude, interactive Codex and Relay. Cost: the work edits files under `~/.claude/hooks` and `~/.codex/hooks` that every Claude session depends on. It adds a step outside this repository (`general-purpose`) and a native-payload test surface to those scripts, and it moves the owner's interactive Codex sessions off the adapter as well.
