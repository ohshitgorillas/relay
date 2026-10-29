Status: approved.

## Why

Relay binds command defaults to Claude in `relay/config.py:9`, stream parsing in `relay/stream.py:28`, subagent events in `relay/agents.py:60`, handoff text in `relay/prompts.py:26`, and log replay in `relay/cli.py:85`. Process management already has one home, `relay/runner.py:72`; preserve it. Budget decisions occur before dispatch and during streaming (`relay/loop.py:59`, `relay/loop.py:158`) and must both honor backend capabilities. These are separate concerns, not duplicate implementations to merge indiscriminately.

The backend defaults to Claude with existing commands, parser semantics, spend and handoff behavior unchanged. Codex uses fresh threads for rotation, receives the previous report and a backend-specific history hint, and never treats cumulative thread tokens as current context. Generic commands receive prompts on stdin and return plain stdout; they have no budget or context telemetry.

## Modules

`relay/backends/base.py` owns the protocol, capabilities and per-run resources. It reuses `StreamState`, `Spend` and `Activity` as the normalized public observations rather than creating parallel models.

```python
@dataclass(frozen=True)
class Capabilities:
    context: bool
    tokens: bool
    dollars: bool
    subagents: bool

class Backend(Protocol):
    capabilities: Capabilities
    def argv(self, role: str, cfg: Config, cwd: Path, output: Path) -> list[str]: ...
    def parse(self, state: StreamState, line: str) -> StreamState: ...
    def poll(self, state: StreamState) -> StreamState: ...
    def finish(self, state: StreamState, output: Path) -> StreamState: ...
    def resume_hint(self, session_id: str) -> str: ...
```

`relay/backends/__init__.py` owns selection, fresh per-run adapters and historical log replay. `get_backend(name: str) -> Backend` rejects unknown names through ConfigError. `replay(log: Path) -> StreamState` recognizes backend metadata beside new logs and treats legacy unmarked logs as Claude. It never tails live session files while replaying history.

`relay/backends/claude.py` delegates to existing `stream.feed` and preserves the existing command defaults and agent override behavior. Poll and finish are no-ops; resume_hint returns the existing `resume <sid>` text. `relay/stream.py` and `relay/agents.py` retain their legacy API and data types.

`relay/backends/generic.py` accumulates stdout, including line breaks, as final text. All capabilities are false. Config requires an explicit command for generic mode; recut defaults to that command without Claude flags.

`relay/backends/codex.py` owns Codex argv, generated role TOML loading, JSON event normalization, final-message file handling and handoff hints. It runs `codex exec --json --dangerously-bypass-approvals-and-sandbox -C <cwd> -o <output>` with stdin prompt. It loads the generated lead/divvyer configuration from CODEX_HOME/agents (default ~/.codex/agents), preserving instructions and declared model/effort through supported CLI config overrides. Missing or invalid role data raises ConfigError before launch. Confirm the installed CLI and upstream source's supported configuration keys before building this mapping; do not silently discard role instructions or weaken hooks.

Codex thread.started sets session_id. Completed agent_message items and the unique output file supply final text, with the file authoritative when present; failed/error events set is_error. turn.completed usage updates cumulative spend without adding repeated snapshots or cached tokens twice. collab_tool_call items normalize receiver IDs and agents_states into Activity; a completed tool call is not itself proof that a receiver agent finished. Receiver status determines completion, and duplicate item updates do not duplicate activity events. Unknown or malformed events leave known state intact. Generated roles are TOML files; preserve developer_instructions, model, model_reasoning_effort and feature settings through CLI config overrides.

`relay/backends/codex_session.py` owns incremental reading of the matching on-disk rollout and token_count observations. It locates the rollout by validated thread identity under CODEX_HOME/sessions, caches its path and byte offset, buffers partial lines and retries delayed file creation. It reads last_token_usage for context and total_token_usage for cumulative spend; it retains model_context_window separately. No cumulative count substitutes for context. Context may fall after compaction. Source schema and a captured session excerpt establish the exact fields. Missing telemetry at finalization is an explicit error, not a silent successful zero-context run. Bounded polling avoids repeatedly scanning the whole session tree.

```python
class SessionReader:
    def __init__(self, home: Path, session_id: str): ...
    def poll(self, state: StreamState) -> StreamState: ...
```

`relay/runner.py` remains the sole process and lifecycle owner. Add optional backend/config/role inputs with legacy defaults or a thin backend invocation wrapper, preserving existing callers. It allocates unique final output and backend metadata beside each numbered log before launch. Timed stdout multiplexing invokes backend.poll and the existing callback even during quiet stdout, so retirement and hard kills work while Codex is using tools. Persist normalized telemetry updates in a companion file for deterministic replay without requiring retained Codex session files. Finish performs a last telemetry read and reads final output before returning. Every exception, signal and callback kill uses existing process-group cleanup; no adapter spawns processes or background monitors.

`relay/config.py` adds validated backend selection and backend-sensitive default commands while preserving positional Config construction via a trailing default field. Config retains ownership of validation. `relay/ledger.py` gates both budget kinds by capabilities, so existing historical dollars cannot stop Codex, and generic ignores both budgets. The backend registry must not create a config/ledger/stream import cycle; type-only imports and lazy selection keep dependencies acyclic.

`relay/prompts.py` accepts an optional pre-rendered handoff hint, preserving its default. Codex hints identify the prior thread, describe `codex exec resume <id>` as the native history continuation command, and state that the supplied report is the handoff; they never direct Terminus to recall a Codex ID. Relay rotation itself starts a fresh thread, never native resume into the full context being retired.

`relay/loop.py` selects the adapter and supplies it at lead/recut invocation and prompt construction. Existing state-machine branches remain unchanged. Backend capabilities guard context comparisons. `relay/cli.py` adds --backend on go and delegates historical parsing to replay; ledger session ownership remains unchanged. README documents configuration, telemetry limitations and a command using this worktree against ~/dev/gauntlet/docs/queue.md without running that queue.

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Backend selection and replay | relay/backends/__init__.py | Backend detection in loop or CLI |
| Normalized observations | relay/stream.py, relay/agents.py, relay/ledger.py existing data types | Parallel state models per adapter |
| Claude protocol | relay/stream.py and relay/agents.py through Claude adapter | Reimplementation in runner |
| Codex protocol and roles | relay/backends/codex.py | Codex conditionals in loop or CLI |
| Codex rollout telemetry | relay/backends/codex_session.py | Cumulative usage as context; independent poller processes |
| Spawn, polling and cleanup | relay/runner.py | Adapter-owned subprocesses |
| Budget policy | relay/ledger.py | Adapter-specific budget decisions at individual call sites |
| Prompt wording | relay/prompts.py with backend handoff hook | Unconditional Claude history instructions |
| Config validation | relay/config.py | Silent fallback for unknown backend or invalid roles |
| Fixture provenance | tests/fixtures plus capture documentation | Invented output described as captured |

## Order

| Step | Agent | Paths | Behavior and completion |
|---|---|---|---|
| Shared adapter contract and Claude/generic support | builder | relay/backends/base.py, relay/backends/__init__.py, relay/backends/claude.py, relay/backends/generic.py, relay/config.py | Existing Claude behavior and generic command/stdout behavior remain independently testable. |
| Codex adapter and rollout reader | builder | relay/backends/codex.py, relay/backends/codex_session.py | Source-confirmed role loading, events, spend, context and final output implement the protocol. |
| Runtime integration | builder | relay/runner.py, relay/loop.py, relay/prompts.py, relay/ledger.py, relay/cli.py | Quiet-stream context polling, capabilities, fresh-thread handoff and mixed historical replay work through minimal loop/CLI edits. |
| Behavioral tests and real fixture capture | test-writer | tests/test_backends.py, tests/test_codex_session.py, tests/test_runner.py, tests/test_loop.py, tests/test_config.py, tests/test_cli.py, tests/test_prompts.py, tests/test_ledger.py, tests/fixtures/ | Capture a tiny real Codex JSON run and matching token_count excerpt, preserving provenance and distinguishing synthetic edge cases; cover rotation, budgets, role errors, malformed/partial/delayed telemetry, duplicate events and generic output. Run uv run pytest. |
| User documentation | builder | README.md | Document backend choice, unsupported Codex dollar/agent telemetry, native-resume versus rotation distinction and the exact unexecuted Gauntlet trial command. |

Tests are authored before their implementation step using the interface stubs above; the divvyer cuts the dispatch queue and places the red-test dispatches accordingly. Codex source/help verification and tiny fixture capture are required evidence before adapter implementation; no real Gauntlet run is part of validation.
