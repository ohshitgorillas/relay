Status: approved.

## Why

Relay needs cache-aware API-equivalent pricing and a completed lead report that lists every observed subagent with its model, effort and final cost, including explicit unavailable measurements.

There are zero token-pricing implementations in the surveyed tree: Claude accepts `total_cost_usd` at `relay/stream.py:58`, while Codex declares dollars unsupported at `relay/backends/codex.py:23`. There are two Codex cumulative-token observations, stdout at `relay/backends/codex.py:85` and rollout polling at `relay/backends/codex_session.py:113`; neither is an independent billable increment. Claude's three input categories already contribute to context at `relay/stream.py:49` and must retain that meaning.

There is one subagent inventory, `Activity.agents` at `relay/agents.py:28`, shared by Claude task events (`relay/agents.py:60`) and Codex receiver events (`relay/backends/codex.py:103`). `Agent` has no model, effort or cost (`relay/agents.py:10`). Two presentation paths omit those measurements: final lead output (`relay/progress.py:63`) and ledger agent rows (`relay/ledger.py:74`). The final output has no subagent rows. Snapshot restoration reconstructs agents separately for inventory and events (`relay/backends/__init__.py:36`), so both must preserve the new fields.

The compatible pricing and per-thread contract is the approved `relay-codex-native-design.md`, Modules `relay/pricing.py`, `relay/stream.py` and Codex telemetry, supplied from the named concurrent worktree. Its first five `Usage` fields, first three `Rate` fields, `rate`, `dollars`, `Config.prices` and `StreamState.usage` remain compatible. This work supplies additive cache accounting and reporting. It does not change role delivery, permissions, failure policy, process lifecycle or budget termination. Concurrent changes to those concerns remain independent.

## Modules

### `relay/pricing.py` — one rate table and one cache-aware pricing function

```python
@dataclass(frozen=True)
class Rate:
    input: float
    cached_input: float
    output: float
    cache_write_30m: float | None = None
    cache_write_12h: float | None = None

@dataclass(frozen=True)
class Usage:
    thread: str
    model: str
    input: int                     # includes cached reads and billed cache writes
    cached_input: int
    output: int                    # includes reasoning output
    cache_write_30m: int | None = 0
    cache_write_12h: int | None = 0
    unavailable: str | None = None

class Unpriced(RelayError): ...

RATES: dict[str, Rate]
SOURCE = "https://developers.openai.com/api/docs/pricing"

def rate(cfg: Config, model: str) -> Rate:
    raise NotImplementedError

def dollars(cfg: Config, usage: tuple[Usage, ...]) -> float:
    raise NotImplementedError
```

Rates are USD per million tokens. Preserve the approved exact-model lookup and config override precedence; unknown models never inherit another model's rate. The standard short-context entries, in input/read/output/30m-write/12h-write order, are `gpt-6-astra: 10/1/50/12.5/25`, `gpt-6.1-sol: 2/.1/10/2.5/5`, `gpt-6.1-terra: 1/.05/5/1.25/2.5`, and `gpt-6-luna: .1/.01/.5/.125/.25`. These entries apply only when the billing context matches that rate regime. The pricing source and https://developers.openai.com/api/docs/guides/prompt-caching define cache-write pricing as a replacement for uncached-input pricing.

For each usage row let `uncached = input - cached_input - cache_write_30m - cache_write_12h`. The charge is `(uncached * input_rate + cached_input * read_rate + write_30m * write_30m_rate + write_12h * write_12h_rate + output * output_rate) / 1_000_000`. Writes are neither charged twice nor classified as reads. A zero write count needs no write rate. Validate nonnegative integer counts excluding booleans, non-overlapping input categories, and finite nonnegative rates. Missing required rates, unknown write buckets, an unavailable billing dimension or an unsupported rate regime raise `Unpriced` with a useful reason. No clamping, default full-input pricing or guessed cache duration is permitted.

Trailing zero defaults preserve construction of the approved five-field `Usage` for protocols known to have no billed writes. An adapter must explicitly pass `None` or `unavailable` when the source does not establish that fact; an absent field is not evidence of zero. The same restriction applies to absent cached-read counts. Config overrides describe the same standard regime, not an implicit override of unknown billing conditions. Costs remain API-equivalent estimates, not subscription charges.

This creates the pricing home anticipated by the concurrent design; it replaces no existing dollar formula. Imports of `Config` in pricing are type-only to avoid a cycle with config.

### `relay/config.py` — validates the shared price overrides

```python
@dataclass(frozen=True)
class Config:
    ...
    prices: dict[str, Rate] = field(default_factory=dict)

def _prices(value: object) -> dict[str, Rate]:
    raise NotImplementedError
```

Use `[prices."<model>"]` with required `input`, `cached_input`, `output` and optional `cache_write_30m`, `cache_write_12h`. Reject unknown keys and nonfinite, negative, boolean or nonnumeric rates. Missing optional write rates remain unavailable for nonzero billed writes. This extends the config loader at `relay/config.py:170`, using the approved native config spelling; no second price configuration is introduced.

### `relay/agents.py` — retains final per-agent measurements in the existing inventory

```python
@dataclass(frozen=True)
class Agent:
    ...                            # existing fields and positional order unchanged
    models: tuple[str, ...] = ()
    efforts: tuple[str, ...] = ()
    cost_dollars: float | None = None
    cost_basis: str = "none"        # reported, api-estimate, none
    cost_unavailable: str | None = "not reported"

def measured(activity: Activity, task_id: str, *, models: tuple[str, ...],
             efforts: tuple[str, ...], cost_dollars: float | None,
             cost_basis: str, cost_unavailable: str | None) -> Activity:
    raise NotImplementedError

def restore_agent(value: dict) -> Agent:
    raise NotImplementedError
```

Keep every discovered agent once, keyed by stable task/thread ID, in first-observed order. Repeated notifications and resumed activity update that entry without adding cumulative costs together. Preserve previously observed metadata when later records omit it; retain all distinct observed models and efforts in observation order, including an explicit `unavailable` marker for turns whose setting is unknown. Never infer actual model or effort from a role name or the parent's settings. A never-measured agent uses empty tuples and renders unavailable. A known zero charge is distinct from an unavailable charge. Partial usage is not a final cost.

`measured` enriches an existing agent without inventing lifecycle events or changing live membership. Backend discovery inserts a valid receiver before enrichment, even when its status or rollout is missing. Discovery follows child relationships exposed by child telemetry as well as the lead's direct receivers, deduplicates IDs and does not follow unrelated sessions. Only discoverable agents can be reported; absent child discovery is a documented backend limitation.

`restore_agent` owns defaults for old snapshots and tuple restoration for new snapshots, used for both inventory and event agents. `merge` retains its later-run semantics (`relay/agents.py:101`) while preserving nonmissing measurements. No report or ledger reconstructs an inventory from events or role names.

### `relay/backends/codex_session.py` and `relay/backends/codex.py` — normalize observed usage and settings

```python
class SessionReader:
    ...
    usage: tuple[Usage, ...]
    models: tuple[str, ...]
    efforts: tuple[str, ...]
    children: tuple[str, ...]
    unavailable: str | None
    def poll(self, state: StreamState, *, force_scan: bool = False) -> StreamState: ...

class CodexBackend:
    def poll(self, state: StreamState) -> StreamState: ...
    def finish(self, state: StreamState, output: Path) -> StreamState: ...
```

Extend the concurrent native reader's per-thread, per-model usage collection. Turn-context settings establish actual model and effort; capture missing settings explicitly. Normalize provider input semantics once in the reader into inclusive `Usage.input`. Ground any cache-write duration or billing-regime fields in actual captured protocol evidence before interpreting them. Where the installed telemetry cannot distinguish billed writes or pricing regimes, retain all known counts and report the precise unavailable dimension. The reader is the only rollout parser.

Cumulative snapshots replace earlier totals; stdout and rollout observations of the same work are not added. Attribute cumulative deltas to the turn's observed model, retaining preceding models' amounts. Preserve the existing resume boundary at `relay/backends/codex_session.py:38`; report and price only the invocation's work, not previously ledgered history. Missing baselines or unexplained counter resets make affected cost unavailable rather than producing a negative or guessed increment. Context remains the latest parent context, not the sum of worker usage.

Poll every discovered thread through the same reader registry, including descendants, with one reader per ID and cycle prevention. At finalization force the final available read before enriching agents. A still-running, missing, malformed or incomplete thread retains its inventory row and has final cost unavailable with a reason. Sum each thread's model rows through `pricing.dollars`; catch `Unpriced` only to record report availability, without suppressing the native design's run fault or final telemetry errors. If usage is complete, agent cost has basis `api-estimate`. Report estimates may be populated while main's dollar capability remains disabled; enabling budget enforcement belongs to the native design. When native aggregate pricing is present it calls this same function over the same usage, never adds reported agent costs on top.

Adapter changes are confined to telemetry collection and enrichment. Retain native argv, preflight and role changes on integration; do not replace that adapter with a branch-local copy. The shared `StreamState.usage` below is the integration boundary.

### `relay/stream.py` and `relay/backends/__init__.py` — carry observations through existing snapshots

```python
@dataclass
class StreamState:
    ...
    usage: tuple[Usage, ...] = ()

def _snapshot(path: Path) -> StreamState:
    raise NotImplementedError
```

Use the concurrent native usage field unchanged and preserve its `fault` field if present. Snapshot replay restores `Usage` and calls `agents.restore_agent` for both inventory and event records. Old snapshots without additions remain readable with unavailable agent measurements. Replay uses saved observations without consulting current live sessions or repricing old costs.

Claude `feed` continues to trust the run-level `total_cost_usd` (`relay/stream.py:58`), including cached input already billed by Claude. Enrich agent metadata only from explicitly associated task telemetry; if Claude emits an agent-specific final cost, retain it as `reported` after finite nonnegative validation. Do not allocate the lead's total across workers, price context counts, or use the OpenAI table for Claude. Missing Claude model, effort and final cost are displayed as unavailable. Generic's absent subagent telemetry remains explicitly unsupported.

### `relay/progress.py` and `relay/ledger.py` — render and persist the same complete inventory

```python
def agent_finished_text(agent: Agent) -> str:
    raise NotImplementedError

def lead_finished(sid: str, result: RunResult, status: LeadStatus | None) -> None: ...

class Ledger:
    def append(self, kind: Kind, section: str, session: str | None, spend: Spend,
               map_commit: str | None = None, agents: tuple[Agent, ...] = (),
               rung: int | None = None, *, basis: str = "reported",
               usage: tuple[Usage, ...] = ()) -> None: ...
```

The ledger signature retains the concurrent design's explicit `basis` and `usage` parameters. Preserve their schema. Extend each existing `agents` entry with `models`, `efforts`, `cost_dollars`, `cost_basis` and `cost_unavailable`; retain `name`, `task_id` and `total_tokens` compatibility. Agent entries are detail, never additional run spend. Existing aggregate ledger parsing remains unchanged.

After the existing lead-finished line, print one row per inventory entry, on every terminal outcome, including failed or killed leads. Each row identifies the stable ID, role/name when known, status, model(s), effort(s) and final cost with basis. For example: `agent <id> <name>: completed; model <model>; effort high; final cost $0.123456 API-equivalent estimate (not subscription billing)`. Unavailable values say `unavailable`; costs include the reason. Use sufficient precision that a small positive charge is not displayed as zero. Never truncate the inventory or substitute only its biggest member. Reuse `agent_finished_text` for any final-agent presentation requiring the same fields. Empty inventories report `no subagents observed`, not a claim that unsupported telemetry proves none ran. Output is generated from final normalized state, not by prompting the lead to calculate costs.

## Homes

| Shared concern | One home | Forbidden elsewhere |
|---|---|---|
| Rates, cache category arithmetic, price errors | `relay/pricing.py` | Inline rates, full-input fallback, per-agent formulas or cache duration guesses |
| Price overrides | `relay/config.py` | Environment-only or adapter-local rate tables |
| Codex usage/settings and descendant discovery | `relay/backends/codex_session.py`, coordinated by the existing Codex adapter | Rollout parsing in reports, ledgers or a second reader; duplicate stdout billing |
| Agent identity, final measurements and defaults | `relay/agents.py` | Independent report inventories or role-based measurement guesses |
| Claude event normalization | `relay/stream.py` | Repricing the reported total or treating context as billed usage |
| Snapshot serialization/restoration | Existing runner snapshot and `backends._snapshot` | New sidecar stores or live lookup during replay |
| Human-readable agent rows | `relay/progress.py` | Agent-cost formatting in the loop or adapters |
| Durable agent detail and run totals | `relay/ledger.py` | Adding agent detail charges to already aggregated run spend |
| Synthetic billing and reporting event fixtures | `tests/fixtures/cache-cost/` | Duplicated protocol fixtures across tests or unlabelled synthetic evidence |

## Order

Steps write only the active `cache-cost-report` checkout. The concurrent native worktree is surveyed, not edited. Shared signatures above are additive to its approved contract; integration uses those definitions once. A missing shared capability is reported as a design gap, not implemented as a second core.

1. **Shared stubs** — `builder`; paths `relay/pricing.py`, `relay/config.py`, `relay/agents.py`, `relay/stream.py`. Add the documented interfaces and fields; new function bodies are raise-only.
2. **Pricing behavior** — `test-writer`; paths `tests/test_pricing.py`, `tests/test_config.py`. Prove cache reads and each billed-write duration use their own rates, writes replace uncached charges, mixed categories do not overlap, reasoning is counted once, custom rates work, and incomplete or invalid billing evidence never becomes a false numeric cost. Preserve the approved five-field usage and three-rate construction where writes are known absent.
3. **Pricing implementation** — `builder`; paths `relay/pricing.py`, `relay/config.py`. Implement the one formula, rate coverage and validated shared configuration.
4. **Inventory and replay behavior** — `test-writer`; paths `tests/test_agents.py`, `tests/test_backends.py`, `tests/test_stream.py`, `tests/fixtures/cache-cost/`. Cover missing measurements, known zero, repeated lifecycle events, multiple settings, resumed identity, Claude reported totals, and old/new snapshot replay without live lookups.
5. **Inventory and replay implementation** — `builder`; paths `relay/agents.py`, `relay/stream.py`, `relay/backends/__init__.py`. Implement metadata folding and lossless snapshot restoration.
6. **Codex telemetry behavior** — `test-writer`; paths `tests/test_codex_session.py`, `tests/test_backends.py`, `tests/fixtures/cache-cost/`. Prove cached-session pricing from realistic normalized telemetry, repeated cumulative observations without double billing, model transitions, resume boundaries, descendants, absent status records, unavailable write dimensions and incomplete final measurements. Mark synthetic fixtures; do not claim an unsupported field is emitted by the installed CLI.
7. **Codex telemetry integration** — `builder`; paths `relay/backends/codex_session.py`, `relay/backends/codex.py`. Connect normalized measurements to the existing inventory and shared pricing while preserving concurrent adapter changes.
8. **Completed-report behavior** — `test-writer`; paths `tests/test_progress.py`, `tests/test_ledger.py`, `tests/test_loop.py`, `tests/fixtures/cache-cost/`. Prove the completed lead report and ledger contain every discovered agent exactly once, including failures, missing telemetry and descendants, with model, effort and final cost or explicit unavailability; prove detail never doubles aggregate spend. Include an end-to-end fixture-driven cached lead with multiple agents whose prices differ from full-input pricing and whose emitted rows survive replay.
9. **Completed-report implementation and documentation** — `builder`; paths `relay/progress.py`, `relay/ledger.py`, `README.md`. Render final rows and persist measured detail; document API estimates, unsupported dimensions and discovery limitations. No real model run is required to prove these behaviors.
