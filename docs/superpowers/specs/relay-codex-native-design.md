Status: approved.

# Relay Codex-native enforcement

## Why

Relay runs Codex through Claude-shaped seams. Codex runs bypass every sandbox, have no dollar figures, and get their roles from files generated out of Claude agents. A section failure count can only grow. Every piece in this design lands on branch `codex-native`, off main, and stays unmerged.

- **Permissions.** Every Codex run passes `--dangerously-bypass-approvals-and-sandbox` (`relay/backends/codex.py:64-68`). No role carries its own sandbox or approval setting.
- **Budget.** `CodexBackend.capabilities.dollars` is False (`relay/backends/codex.py:23`), so `Ledger.over` (`relay/ledger.py:159-178`) and `_over_cap` (`relay/loop.py:612-620`) ignore Codex dollar limits. Token spend comes from `total_token_usage.total_tokens` alone (`relay/backends/codex_session.py:113-124`), and that covers only the run's own thread: helper threads that `collab_tool_call` names (`relay/backends/codex.py:103-126`) are never metered. When a budget is hit, the watcher can only ask for a retire (`relay/loop.py:413-430`), so it has no way to end a run that ignores the request.
- **Roles.** Role names are mapped in three places: `CodexBackend.argv` (`relay/backends/codex.py:30-35`), `ClaudeBackend.argv` (`relay/backends/claude.py:19-28`) and `Config._role_command` (`relay/config.py:75-77`). Codex roles come only from `$CODEX_HOME/agents` (`relay/backends/codex.py:26,36`). The lead's helper roles reach it through no Relay path at all. A researcher follow-up smuggles its session through `research_command` (`relay/loop.py:375`, `relay/loop.py:283`, `relay/backends/codex.py:57-60`).
- **Failures.** `State.record_failure` (`relay/state.py:277-282`) only increments. Nothing clears it, and it records no reason. It is copied at `relay/loop.py:177-180` and `relay/loop.py:526-529`. A restart after exit 5 runs the section again, and the section stops on its next failure.
- **Capability lookup** is copied four times as `backends.get_backend(cfg.backend).capabilities`: `relay/loop.py:358`, `relay/loop.py:402`, `relay/loop.py:615` and `relay/ledger.py:167-170`.
- **Research.** `relay/loop.py:316-320` remaps the whole section whenever any mapped file changes. `docs/superpowers/specs/relay-research-reuse-design.md` (approved) fixes this, and `docs/research-reuse-queue.md` cuts it into sections s1-s3. Neither is built on main (`git log main..fix/research-reuse` holds only the design commit `b97bf12`). Both files are committed on `codex-native` at `80f9440`.

### Dependency inventory

| Dependency | Where | Codex-native outcome |
|---|---|---|
| Claude agent files through `--agent` | `relay/config.py:11`, `relay/config.py:76`, `relay/config.py:196` | Claude only. Codex reads `roles.load`. |
| `--permission-mode bypassPermissions` | `relay/config.py:12` | Claude only and unchanged. |
| `opus[1m]` researcher model | `relay/config.py:70` | Claude only. The Codex model comes from the role file. |
| stream-json parser | `relay/stream.py:28-66` | Claude only. `StreamState` stays shared. |
| Terminus `resume <id>` hint | `relay/backends/claude.py:39-40`, `relay/prompts.py:38-41` | Claude only. Codex uses its native hint (`relay/backends/codex.py:148-151`). |
| `claude-ping` notifier | `relay/config.py:220` | Shared default. Any backend can override it with `ping_command`. |
| Unmarked logs replay as Claude | `relay/backends/__init__.py:62-63`, `relay/runner.py:227,237` | Kept for old logs. Every new run writes `.backend.json`. |
| `last_backend`/`research_backend` default `"claude"` | `relay/state.py:48-49` | Kept for old state. |
| `relay ask` wording keyed on `"claude"` | `relay/prompts.py:29,56` | Kept. |
| Codex role TOMLs generated from Guild's Claude agents | `README.md:62`, `relay/backends/codex.py:36` | Replaced by `roles_dir`. The generator stays outside Relay. |
| Codex bypass flag | `relay/backends/codex.py:65,67` | Removed. Native sandbox and approval settings replace it. |
| User Codex hooks (`~/.codex/hooks.json`) | `tests/fixtures/codex-real/stdout.jsonl:2` | Codex loads them itself. Relay leaves them on and never edits them. |

Relay code reads no Claude hook. The Claude adapter consists of `relay/backends/claude.py`, `stream.feed`, the Claude defaults in `relay/config.py:10-13,70,75-77,195-197` and `tests/fakes/fake_claude.py`. No Codex module and no core module imports any of them.

## Modules

### `relay/roles.py`: one source for every role a run launches or delivers

```python
RELAY_ROLES = {"lead": "lead", "recut": "divvyer", "research": "researcher", "ask": "researcher", "design": "architect"}
SANDBOXES = ("read-only", "workspace-write", "danger-full-access")
DEFAULT_SANDBOX = {"lead": "workspace-write", "recut": "workspace-write", "design": "workspace-write",
                   "research": "read-only", "ask": "read-only"}

@dataclass(frozen=True)
class Role:
    name: str                      # file stem: lead, divvyer, builder, ...
    path: Path
    instructions: str              # developer_instructions, non-empty
    model: str                     # required, non-empty
    effort: str | None             # model_reasoning_effort
    sandbox: str                   # one of SANDBOXES
    approval: str                  # always "never"
    network: bool                  # sandbox_workspace_write.network_access
    writable_roots: tuple[str, ...]
    features: dict[str, bool]

def roles_dir(cfg: Config) -> Path:
    """cfg.roles_dir, else $CODEX_HOME/agents, else ~/.codex/agents."""
    raise NotImplementedError

def load(cfg: Config, kind: str) -> Role:
    """The Relay role for a run kind (RELAY_ROLES). Its sandbox defaults to DEFAULT_SANDBOX[kind].
    ConfigError when the file is missing or unreadable, a key has the wrong type, model is absent,
    sandbox is not in SANDBOXES, or approval_policy is set to anything but "never"."""
    raise NotImplementedError

def helpers(cfg: Config) -> tuple[Role, ...]:
    """Every *.toml in roles_dir whose stem is not a RELAY_ROLES value, sorted by name, each validated
    as load validates it. Its sandbox defaults to workspace-write."""
    raise NotImplementedError
```

The role file keys are `developer_instructions`, `model`, `model_reasoning_effort`, `sandbox_mode`, `approval_policy`, `[sandbox_workspace_write] network_access, writable_roots` and `[features]`. Each key keeps the name and type that the installed CLI schema gives it, as recorded in Order step 1. `Config` gains `roles_dir: Path | None = None`.

`roles` replaces the role tables at `relay/backends/codex.py:30-56`. `ClaudeBackend.argv` keeps its own mapping (`relay/backends/claude.py:19-28`) and its behavior.

### `relay/pricing.py`: Relay-owned API-equivalent rates

```python
SOURCE = "https://developers.openai.com/api/docs/pricing"
AS_OF = "<the date step 1 read the page>"

@dataclass(frozen=True)
class Rate:
    input: float          # USD per 1M uncached input tokens
    cached_input: float   # USD per 1M cached input tokens
    output: float         # USD per 1M output tokens; reasoning tokens are part of output

RATES: dict[str, Rate]    # flat-rate models only, with values copied from SOURCE in step 1

@dataclass(frozen=True)
class Usage:
    thread: str
    model: str
    input: int            # input_tokens, cached included
    cached_input: int
    output: int

class Unpriced(RelayError): ...

def rate(cfg: Config, model: str) -> Rate:
    """cfg.prices[model], else RATES[model]; Unpriced for any other model. Never a default or a guess."""
    raise NotImplementedError

def dollars(cfg: Config, usage: tuple[Usage, ...]) -> float:
    """Sum of (input - cached_input) * rate.input + cached_input * rate.cached_input + output * rate.output,
    over 1e6. Raises Unpriced on the first unpriceable model."""
    raise NotImplementedError
```

`Config` gains `prices: dict[str, Rate]` from the config file's `[prices."<model>"]` tables, with keys `input`, `cached_input` and `output`. Each must be a finite, non-negative number. Codex dollars are an estimate of what the same tokens would cost on the API. They are not what a ChatGPT subscription bills. The ledger and `relay status` label them that way.

### `relay/backends/base.py`: contract changes

```python
@dataclass(frozen=True)
class Capabilities:
    context: bool
    tokens: bool
    dollars: bool
    subagents: bool
    resume: bool = False
    budget_kill: bool = False   # a run past budget plus grace is killed, not only asked to retire
    basis: Literal["reported", "api-estimate", "none"] = "reported"

@dataclass(frozen=True)
class Invocation:
    role: str          # a RELAY_ROLES key
    cwd: Path
    output: Path
    resume: str | None = None   # the session an "ask" resumes

class Backend(Protocol):
    capabilities: Capabilities
    def argv(self, inv: Invocation, cfg: Config) -> list[str]: ...
    def preflight(self, cfg: Config) -> None:
        """Raise ConfigError when this backend cannot launch every Relay role under cfg."""
    def parse(self, state: StreamState, line: str) -> StreamState: ...
    def poll(self, state: StreamState) -> StreamState: ...
    def finish(self, state: StreamState, output: Path) -> StreamState: ...
    def resume_hint(self, session_id: str) -> str: ...
```

`relay/backends/__init__.py` gains `capabilities(name: str) -> Capabilities`, which reads the adapter class. It replaces the four copies listed under **Why**. Claude's capabilities are `basis="reported"` and `budget_kill=False`, with its preflight a no-op. Generic's are `basis="none"` with a no-op preflight. `run_agent` (`relay/runner.py:213-234`) takes `inv: Invocation` in place of `role` and the argv rewrite. `loop.ask` passes `resume=session` and stops rewriting `research_command`.

### `relay/stream.py`

```python
@dataclass
class StreamState:
    ...                                   # existing fields unchanged
    usage: tuple[Usage, ...] = ()         # per-thread, per-model cumulative counts; Codex only
    fault: str | None = None              # a backend demand to end the run now, with its reason
```

`feed` is unchanged. `_snapshot` (`relay/backends/__init__.py:30-53`) restores both new fields.

### `relay/backends/codex.py` and `relay/backends/codex_session.py`

`CodexBackend.capabilities` is `Capabilities(context=True, tokens=True, dollars=True, subagents=True, resume=True, budget_kill=True, basis="api-estimate")`.

- **`argv`** builds `codex exec --json -C <cwd> -o <output>`, or `codex exec resume --json -o <output> <session>` for `ask`. It adds the native sandbox flag, `-c approval_policy="never"`, `sandbox_workspace_write` settings, model, effort, instructions and features from `roles.load`. For `workspace-write`, the writable roots also include the git common dir of `cwd`. Each helper from `roles.helpers` is delivered through the CLI's native agent-role config keys, as step 1 records them, pointing at the helper's file. It never passes `--dangerously-bypass-approvals-and-sandbox`.
- **`preflight`** loads every Relay role and every helper, then calls `pricing.rate` on each model. A `ConfigError` or `Unpriced` here stops `relay go` with exit 2 before any run.
- **`SessionReader`** also reads the model of each turn from the rollout's turn-context records, and the input, cached-input and output counts from `total_token_usage`. Step 1 records the field names. The reader yields one `Usage` per thread and model.
- **`poll`** opens a reader for the run's own thread and one for each receiver thread in `collab_tool_call` (`relay/backends/codex.py:103-126`). It sets `spend.tokens` to the sum of their `total_tokens`, `spend.dollars` to `pricing.dollars(cfg, usage)` and `context_tokens` from the run's own thread only. An `Unpriced` model sets `fault = "unpriced model <m>"`.
- **`finish`** behaves as today (`relay/backends/codex.py:135-146`). It also errors when any metered thread has no telemetry.

### `relay/ledger.py`

`append` gains `basis` and `usage`. A line gains `"basis"`, and gains `"usage": [{thread, model, input, cached_input, output}]` only when usage is present. `append_failure(kind, section, session, reason, log)` writes `{"kind": "failure", tokens 0, dollars 0.0, ...}`. `totals_by_basis(since) -> dict[str, Spend]` serves `relay status`. `over` takes its capabilities from `backends.capabilities`. `_parse`, `total` and `section_spend` are unchanged.

### `relay/loop.py`: budget termination and failure rules

```python
@dataclass
class _Watch:
    on_event: Callable[[StreamState], Literal["go", "retire", "kill"]]
    budget_hit: bool = False
    budget_killed: bool = False
    idle_retired: bool = False
```

- **Watcher** (`relay/loop.py:395-436`): a `stream.fault` returns `"kill"`. A budget or cap hit asks for a retire, as today. For a backend with `budget_kill`, spend past the budget, or past the section cap, by more than `cfg.budget_grace` (a fraction of that limit, default 0.1) sets `budget_killed` and returns `"kill"`.
- **Budget kill:** the run is ledgered and the loop returns exit 3. It is never a failure, and the section is not touched.
- **`relay go`:** `backends.get_backend(cfg.backend).preflight(cfg)` runs once before the first pass.

Failure rules hold on every backend:

1. **What counts.** A failure is a run that `run_failed` reports, a lead with no status line (`relay/loop.py:173`), a `fault`, or a failed recut (`relay/loop.py:526`). Each is recorded with `State.record_failure(sid, reason, log)` and `Ledger.append_failure`. A budget kill, a stop file, an interrupt and an idle retire are not failures.
2. **Retry once.** At count 1, the next pass runs a fresh lead on the section. `guidance` carries `Relay's previous run on this section failed: <reason>. Log: <path>.`
3. **Stop at two.** At `FAILURE_LIMIT` (2), the run stops with exit 5. On restart, `_run_section` stops with exit 5 before any research or lead whenever the section's count is at the limit. This mirrors `relay/loop.py:118-119`.
4. **Clear.** A lead that ends with a parsed status, a section marked done, `relay answer` and `relay retry` set the count to 0 and the reason to None.

`_fail` and `_failed_twice` stay the one home for this, and both copies call them.

### `relay/state.py`

`SectionState` gains `failure: str | None = None` and `failure_log: str | None = None`. `record_failure(sid, reason, log) -> int` replaces `record_failure(sid)`. `clear_failures(sid)` and `failed_sections() -> list[tuple[str, SectionState]]` are added. `mark_done` (`relay/state.py:123-136`) and `set_answer` (`relay/state.py:240-255`) also clear `failures`.

### `relay/cli.py`

```text
relay failures <queue.md>                     # each section with failures or design_failures > 0:
                                              # "<sid> | failures <n> | design <n> | <reason> | <log>"; exit 0
relay retry <queue.md> (<section-id>... | --all)   # clear_failures and clear_design_failures, reopen, print each id
relay go ... [--budget-grace F]
```

`_status` (`relay/cli.py:132-148`) prints spend split by basis, for example `all time: N tokens, $X reported, $Y API-equivalent estimate (not subscription billing)`.

### `scripts/codex_shakedown.py`: the repeatable real Codex shakedown

```python
def main(argv: list[str]) -> int:
    """codex_shakedown.py --scratch <new empty dir> [--relay <relay checkout>]
    Refuses a scratch path that exists non-empty or sits inside a git work tree."""
```

The script uses only the standard library. It builds a fresh scratch git repository. That repository holds a queue of four sections, minimal role files (lead, divvyer, researcher, architect and one helper, `builder`) under `<scratch>/roles`, and a config whose `state_root`, `roles_dir` and `ping_command` (a file appender) all point inside the scratch.

| Section | What it holds |
|---|---|
| s1 | Writes one file. Its check confirms it. |
| s2 | Has the lead create `out/1.txt` to `out/3.txt` with a shell loop. Its check is `for i in 1 2 3; do test -f out/$i.txt \|\| exit 1; done`. |
| s3 | A deliberate failure: the lead ends with a final line that is not a status line unless `REPAIRED` exists in the scratch root. |
| s4 | A multi-turn task. |

The script runs these phases in order:

- **A.** `relay go --backend codex --dollar-budget <tiny>` must exit 3. The ledger must hold a lead line with `basis: api-estimate` and dollars > 0, and the progress output must show a budget kill or retire.
- **B.** `relay go` with no budget must exit 5 on s3. `relay failures` must list s3 with its reason and log, and the ledger must hold its `failure` lines.
- **Repair.** The script creates `REPAIRED`, then runs `relay retry --all`.
- **C.** `relay go` reruns until it exits 0 or until three attempts are used. `relay status` must show every section done and `git status --short` must be clean.

The script records each `relay go` PID at launch and its process group. After each phase it checks them with `ps -p`, and kills only by recorded PGID. It prints one evidence block: phases, exit codes, ledger excerpts, est. dollars, failure lines and PID results. It touches no path outside the scratch except Codex's own `~/.codex/sessions` writes, and no other state root, queue or process.

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Codex role files, sandbox, approval, helpers | `relay/roles.py` | Reading `*.toml` role files or mapping role names for Codex anywhere else |
| Token prices and dollar estimates | `relay/pricing.py`, `Config.prices` | A rate literal, or a dollar computation from tokens, anywhere else. Any default rate for an unknown model |
| Codex usage telemetry (threads, models, counts) | `relay/backends/codex_session.py` | Parsing rollout files elsewhere |
| Backend capabilities | `backends.capabilities(name)` | `get_backend(...).capabilities` outside `relay/backends/` |
| Launch validation | `Backend.preflight`, called once in `relay go` | Role or price checks inside `argv` or the loop |
| Budget and cap decisions, including kill | `loop._watcher` with `Ledger.over` | A second budget check in a backend or the runner |
| Section failure count, reason and rules | `loop._fail`/`_failed_twice`, `State.record_failure`/`clear_failures` | `s.failures` written anywhere else |
| Failure log lines | `Ledger.append_failure`, `progress.failed` | `print` of failures in `loop.py` |
| Resume of a researcher session | `Invocation.resume` | Session ids inside `research_command` |
| Process start, kill and reap | `relay/runner.py` | `subprocess`/`os.killpg` in backends or the shakedown's relay runs, except the shakedown's own recorded-PGID cleanup |
| Map reuse and refresh | `docs/superpowers/specs/relay-research-reuse-design.md` Homes | Any map change in this design |
| Claude test fakes | `tests/fakes/fake_claude.py` | A second Claude replayer |
| Codex fixtures | `tests/fixtures/codex-real/` (captured), `tests/fixtures/codex-native/` (synthetic, labelled) | Codex event text inline in more than one test module |
| Shakedown | `scripts/codex_shakedown.py` | Real model runs from pytest |

## Order

Every step lands on `codex-native`. No step merges, pushes, touches another worktree, stops a running Relay, Codex or HQPTuner job, or connects to Opal.

1. **Grounding** (`builder`): writes `docs/codex-native-report.md`, section Grounding. It records `codex --version`, `codex exec --help`, the installed config schema's names and values for sandbox mode, approval policy, `sandbox_workspace_write`, agent-role delivery and features, and the rollout's turn-context model field and usage fields. Each is checked against https://developers.openai.com/codex/cli/reference and https://developers.openai.com/codex/security. It also records the rates and read date from https://developers.openai.com/api/docs/pricing for every model that the shakedown roles and the owner's `~/.codex/agents` role files name. It records any model that has no flat rate as unpriced. If the installed CLI has no native agent-role delivery, this step ends with `DESIGN:`.
2. **Research reuse** (`lead`): carries `docs/research-reuse-queue.md` sections s1-s3 as cut, building that design's Order steps 1-7 here. The `fix/research-reuse` worktree is not touched.
3. **Claude pin** (`test-writer`): writes `tests/test_backends.py`, `tests/test_loop.py`, `tests/test_config.py` and `tests/test_ledger.py`. These pin today's Claude behavior: argv for every role, stream-json spend and dollars, `basis` reported, retire-only budget with no kill, and dollar caps. A further test checks that no module under `relay/` other than `relay/backends/claude.py` and `relay/backends/__init__.py` imports `relay.backends.claude`. All of these pass on arrival.
4. **Stub** (`builder`): writes `relay/roles.py`, `relay/pricing.py`, `relay/backends/base.py`, `relay/stream.py` and `relay/backends/__init__.py`. They get the Modules signatures, raise-only, plus the new fields.
5. **Red: pricing** (`test-writer`): writes `tests/test_pricing.py` and `tests/test_config.py`.
6. **Pricing** (`builder`): writes `relay/pricing.py` and `relay/config.py`.
7. **Red: roles, argv and preflight** (`test-writer`): writes `tests/test_roles.py`, `tests/test_backends.py` and fixtures under `tests/fixtures/codex-native/`.
8. **Roles, argv and preflight** (`builder`): writes `relay/roles.py`, `relay/backends/base.py`, `relay/backends/codex.py`, `relay/backends/claude.py`, `relay/backends/generic.py`, `relay/backends/__init__.py`, `relay/runner.py`, `relay/loop.py` and `relay/config.py`.
9. **Red: Codex usage telemetry** (`test-writer`): writes `tests/test_codex_session.py`, `tests/test_backends.py` and `tests/fixtures/codex-native/`.
10. **Codex usage telemetry** (`builder`): writes `relay/backends/codex_session.py`, `relay/backends/codex.py`, `relay/stream.py` and `relay/backends/__init__.py`.
11. **Red: budget termination and ledger basis** (`test-writer`): writes `tests/test_ledger.py`, `tests/test_loop.py` and `tests/test_cli.py`.
12. **Budget termination and ledger basis** (`builder`): writes `relay/ledger.py`, `relay/loop.py`, `relay/cli.py` and `relay/config.py`.
13. **Red: recoverable failures** (`test-writer`): writes `tests/test_state.py`, `tests/test_loop.py`, `tests/test_cli.py` and `tests/test_progress.py`.
14. **Recoverable failures** (`builder`): writes `relay/state.py`, `relay/loop.py`, `relay/ledger.py`, `relay/progress.py` and `relay/cli.py`.
15. **Red: shakedown setup and verdicts** (`test-writer`): writes `tests/test_shakedown.py`. It covers the scratch refusal rules, the generated repo, queue, roles and config, and the phase checks against recorded evidence. It runs no model.
16. **Shakedown script** (`builder`): writes `scripts/codex_shakedown.py`.
17. **User docs** (`builder`): writes `README.md`. It covers native sandbox and approval, `roles_dir`, helpers, `prices`, `budget_grace`, API-equivalent estimates versus subscription billing, failure rules, `relay failures` and `relay retry`.
18. **Full suite** (`lead`, writes nothing): runs `uv run pytest` over the whole suite. It must pass.
19. **Shakedown and report** (`builder`): runs `scripts/codex_shakedown.py` in a new scratch directory under `$TMPDIR`. Before it runs, the step discloses the spend, which is model-priced and nonzero but small, and is unmeasured until the run. The step then completes `docs/codex-native-report.md` with sections Evidence (the script's block), Dependency inventory (the table above, re-anchored at HEAD), Adapter removability (what deleting the Claude adapter removes, and the import test from step 3), Limitations and PID cleanup (each recorded PID with its `ps -p` result).
