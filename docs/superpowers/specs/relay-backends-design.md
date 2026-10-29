Status: approved.

## Why

Relay binds command defaults to Claude in `relay/config.py:9`, stream parsing in `relay/stream.py:28`, subagent events in `relay/agents.py:60`, and log replay in `relay/cli.py:80`; the handoff interface lives in `relay/prompts.py:13`. Process management has one home, `relay/runner.py:80`; preserve it. Budget decisions occur before dispatch and during streaming (`relay/loop.py:58`, `relay/loop.py:164`) and must both honor backend capabilities. These are separate concerns, not duplicate implementations to merge indiscriminately.

The backend defaults to Claude with existing commands, parser semantics, spend and handoff behavior unchanged. Codex uses fresh threads for rotation, receives the previous report and a backend-specific history hint, and never treats cumulative thread tokens as current context. Generic commands receive prompts on stdin and return plain stdout; they have no budget or context telemetry.

Atomic replacement has two existing implementations, telemetry publication at `relay/runner.py:111` and state persistence at `relay/state.py:75`. Queue recovery adds a third consumer, not another implementation. The queue parser and user documentation state an unconditional no-write rule (`relay/queue.py:1`, `README.md:27`); Relay's sole exception is restoring the exact pre-invocation queue after a failed recut. Queue authorship remains with leads and the divvyer.

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

`relay/backends/codex.py` owns Codex argv, generated role TOML loading, JSON event normalization, final-message file handling and handoff hints. It runs `codex exec --json --dangerously-bypass-approvals-and-sandbox -C <cwd> -o <output>` with stdin prompt. It loads the generated lead/divvyer configuration from CODEX_HOME/agents (default ~/.codex/agents), preserving instructions and declared model/effort through supported CLI config overrides. Missing or invalid role data raises ConfigError before launch. Role mapping uses repeatable `-c key=value` arguments with TOML-encoded values, supported by installed CLI 0.165.0 `exec --help` and [utils/cli/src/config_override.rs:15–36,47–81](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/utils/cli/src/config_override.rs#L15-L81). Supported keys are `model`, `developer_instructions`, `model_reasoning_effort` and dotted `features.<name>` keys; preserve feature settings individually without replacing unrelated features. Their definitions are [config/src/config_toml.rs:170,254–256,402,512–515](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/config/src/config_toml.rs#L170-L515). Do not silently discard role instructions or weaken hooks.

Codex thread.started sets session_id. Completed agent_message items and the unique output file supply final text, with the file authoritative when present; failed/error events set is_error. turn.completed usage updates cumulative spend without adding repeated snapshots or cached tokens twice. collab_tool_call items normalize receiver IDs and agents_states into Activity; a completed tool call is not itself proof that a receiver agent finished. Receiver status determines completion, and duplicate item updates do not duplicate activity events. Unknown or malformed events leave known state intact. Generated roles are TOML files; preserve developer_instructions, model, model_reasoning_effort and feature settings through CLI config overrides.

`relay/backends/codex_session.py` owns incremental reading of the matching on-disk rollout and token_count observations. It locates the rollout by validated thread identity under CODEX_HOME/sessions, caches its path and byte offset, buffers partial lines and retries delayed file creation. It reads last_token_usage for context and total_token_usage for cumulative spend; it retains model_context_window separately. No cumulative count substitutes for context. Context may fall after compaction. Source schema and a captured session excerpt establish the exact fields. Missing telemetry at finalization is an explicit error, not a silent successful zero-context run. Bounded polling avoids repeatedly scanning the whole session tree.

An I/O failure opening or reading a matching rollout candidate during discovery, or reading the selected rollout later, raises the existing `RelayError` (`relay/errors.py:4`), with the original error chained. It never returns stale telemetry as a successful poll. Malformed identity records remain skippable; delayed creation with no candidate yet present remains retryable. The exception propagates to runner process-group cleanup.

The Codex wire contract uses the official upstream `rust-v0.165.0` source. [exec/src/exec_events.rs:205–242](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/exec/src/exec_events.rs#L205-L242) defines `collab_tool_call` fields `tool`, `sender_thread_id`, `receiver_thread_ids`, `prompt`, `agents_states` and `status`. `agents_states` maps receiver IDs to objects containing `status` and `message`; receiver statuses are `pending_init`, `running`, `interrupted`, `completed`, `errored`, `shutdown` and `not_found`. The outer tool-call status and each receiver's status are distinct observations. A tool-call completion alone cannot complete all receivers. Synthetic collaboration fixtures use this schema and are labeled synthetic; the captured minimal run contains no collaboration event (`tests/fixtures/codex-real/stdout.jsonl:1`).

[protocol/src/protocol.rs:2427–2496](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/protocol/src/protocol.rs#L2427-L2496) defines `token_count.info` with `total_token_usage`, `last_token_usage` and `model_context_window`. The captured rollout line has envelope `type: "event_msg"`, then `payload.type: "token_count"` and `payload.info` (`tests/fixtures/codex-real/token-count.jsonl:1`). Each captured usage object contains `input_tokens`, `cached_input_tokens`, `cache_write_input_tokens`, `output_tokens`, `reasoning_output_tokens` and `total_tokens`. Read context from `last_token_usage.total_tokens` and cumulative spend from `total_token_usage.total_tokens`; cached and reasoning components are not additional totals. Preserve the separately reported context window. This capture has equal last and total usage; it does not establish behavior across turns or compaction.

Fixture provenance: `tests/fixtures/codex-real/stdout.jsonl:1`, `tests/fixtures/codex-real/token-count.jsonl:1` and `tests/fixtures/codex-real/final.txt:1` come from the real command below, with stdin `Reply with exactly RELAY_CODEX_FIXTURE_OK. Do not use tools, inspect files, or change anything.` The captured stdout thread ID is `01a1855b-7ba6-79d3-bf98-98c251634b5a`. Its final text and final-message file contain `RELAY_CODEX_FIXTURE_OK`; stdout also contains an error item reporting a hook-timeout clamp (`tests/fixtures/codex-real/stdout.jsonl:2`), which must remain in the fixture.

```text
codex exec --json --dangerously-bypass-approvals-and-sandbox -C /Users/atom/dev/relay-wt/backends -o .codex-capture/final.txt -
```

The rollout identity envelope is `{timestamp, optional ordinal, type: "session_meta", payload: {id: <thread UUID>, session_id: <root UUID>, ...}}`. Match `payload.id` to `thread.started.thread_id`; `payload.session_id` identifies the root session and is not the matching key. [protocol/src/protocol.rs:3278–3287](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/protocol/src/protocol.rs#L3278-L3287) defines both identities; [SessionMetaLine:3395–3399](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/protocol/src/protocol.rs#L3395-L3399) flattens its metadata, and [protocol.rs:3418–3423](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/protocol/src/protocol.rs#L3418-L3423) backfills an absent root `session_id` from `id`. The tagged `session_meta` payload is defined in [history/src/rollout_payload.rs:30–36](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/history/src/rollout_payload.rs#L30-L36); [rollout/src/recorder.rs:2127–2134](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/rollout/src/recorder.rs#L2127-L2134) flattens the item alongside timestamp and optional ordinal. Filename matching only locates candidates; metadata validates their thread identity. Identity fixtures derived from these definitions are synthetic because the captured excerpts contain no session metadata (`tests/fixtures/codex-real/token-count.jsonl:1`).

The matching telemetry envelope is `event_msg.payload.type = "token_count"`; [history/src/rollout_payload.rs:66–67](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/history/src/rollout_payload.rs#L66-L67) defines the EventMsg payload. [protocol/src/protocol.rs:2392–2405](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/protocol/src/protocol.rs#L2392-L2405) defines usage fields, and [protocol.rs:2427–2432](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/protocol/src/protocol.rs#L2427-L2432) defines the usage information. Read context at `payload.info.last_token_usage.total_tokens`, cumulative spend at `payload.info.total_token_usage.total_tokens`, and the separate context window at `payload.info.model_context_window`.

```python
class SessionReader:
    def __init__(self, home: Path, session_id: str): ...
    def poll(self, state: StreamState) -> StreamState: ...
```

`relay/runner.py` remains the sole process and lifecycle owner. Add optional backend/config/role inputs with legacy defaults or a thin backend invocation wrapper, preserving existing callers. It allocates unique final output and backend metadata beside each numbered log before launch. Timed stdout multiplexing invokes backend.poll and the existing callback even during quiet stdout and when normalized state is unchanged; repeated callback snapshots are valid, so retirement and hard kills work while Codex is using tools. Parsed stdout observations reach the callback in stream order after polling and snapshot publication; quiet-poll callbacks may occur between them (`relay/runner.py:123`, `relay/runner.py:194`). Finalization follows stream processing and process cleanup, publishes the finalized state and returns it without an additional callback (`relay/runner.py:209`). Persist normalized telemetry updates in a companion file for deterministic replay without requiring retained Codex session files. Finish performs a last telemetry read and reads final output before returning. Every exception, signal and callback kill uses existing process-group cleanup; no adapter spawns processes or background monitors.

Observe direct-child exit independently of stdout EOF. That exit triggers descendant process-group cleanup even when a descendant retains inherited stdout; drain already buffered output through the normal decoder and parser before finalization. Descendant-held descriptors cannot indefinitely postpone cleanup or return. Preserve the direct child's exit result on this path.

Publish every telemetry snapshot through the shared atomic publication helper. Readers see the preceding complete snapshot or the new complete snapshot; interruption before replacement preserves the preceding snapshot. Runner owns snapshot serialization and publication timing for every backend. Replay reads the published snapshot and never depends on a temporary file.

`relay/files.py` owns atomic byte publication and temporary-file cleanup, replacing the mechanisms at `relay/runner.py:111` and `relay/state.py:75`. It creates a unique temporary file beside the destination, writes all bytes, flushes and fsyncs, closes, then replaces the destination atomically. Cleanup removes its temporary file on success or exception. Errors propagate; failed publication cannot return success. An optional permission mode lets queue recovery preserve the pre-invocation queue's mode; absent that argument, retain the existing private-file creation semantics. Serialization, state locking and recovery policy stay with the callers.

```python
def atomic_write(path: Path, data: bytes, *, mode: int | None = None) -> None: ...
```

`relay/loop.py` owns the recut transaction at `_recut` (`relay/loop.py:190`). Before invoking the divvyer, retain the queue's exact bytes and permission mode and parse the original sections. A killed invocation, nonzero exit or backend error restores those bytes through `atomic_write` before any attempt to parse the failed output, including malformed, empty or missing output. Report the failed recut with no accepted change and use the existing failure counter and second-failure return. A nominally successful invocation must yield a parseable, changed queue; malformed, empty or missing output and unchanged sections restore the original and take that same failure branch. Accept and mark recut sections only after validation. An invocation exception restores the original before re-raising; a restoration error propagates and stops the loop, never allowing a next pass over failed output. Existing budget, parking, recut-origin and failure-count branches remain intact. Relay never authors, rewrites or marks queue sections itself; this byte-for-byte rollback is its narrow restoration exception. Reflect that exception in the parser's ownership documentation and README.

Backend finalization errors are invocation failures. Runner preserves the finalized stream's `is_error` flag in its result, including missing required telemetry, even when the child exit code is zero and final text contains a syntactically successful report. Exceptions still propagate through cleanup. Both lead and recut result handling treat `stream.is_error` as failure before accepting report status or queue changes; a missing-telemetry run cannot mark a section done or accept a recut as successful. The existing lead and recut outcome branches are `relay/loop.py:119` and `relay/loop.py:212`; neither may infer success solely from child exit and report text or queue changes.

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
| Codex rollout telemetry | relay/backends/codex_session.py | Cumulative usage as context; independent poller processes; swallowing candidate or selected-rollout I/O failures |
| Error types | relay/errors.py existing RelayError | Adapter-specific replacement error hierarchy |
| Backend finalization outcome | runner's finalized StreamState.is_error, consumed by relay/loop.py | Lead or recut success that ignores backend errors |
| Spawn, polling and cleanup | relay/runner.py | Adapter-owned subprocesses; waiting for descendant-held stdout before cleanup |
| Telemetry publication | relay/runner.py | In-place writes to published snapshots; per-adapter publication paths |
| Atomic byte publication and temporary cleanup | relay/files.py | Independent temporary-write/replace implementations in runner, state or loop |
| Failed recut recovery | relay/loop.py _recut, using relay/files.py | Parsing known-failed output before rollback; accepting failed edits; Relay-authored queue content beyond exact restoration |
| Budget policy | relay/ledger.py | Adapter-specific budget decisions at individual call sites |
| Prompt wording | relay/prompts.py with backend handoff hook | Unconditional Claude history instructions |
| Config validation | relay/config.py | Silent fallback for unknown backend or invalid roles |
| Fixture provenance | tests/fixtures plus capture documentation | Invented output described as captured |

## Order

| Step | Agent | Paths | Behavior and completion |
|---|---|---|---|
| Shared adapter contract and Claude/generic support | builder | relay/backends/base.py, relay/backends/__init__.py, relay/backends/claude.py, relay/backends/generic.py, relay/config.py | Existing Claude behavior and generic command/stdout behavior remain independently testable. |
| Codex adapter and rollout reader | builder | relay/backends/codex.py, relay/backends/codex_session.py | Source-confirmed role loading, events, spend, context and final output implement the protocol; candidate-discovery and selected-rollout I/O failures raise chained RelayError, while malformed identity records and delayed creation remain retryable. |
| Shared atomic publication | builder | relay/files.py, relay/runner.py, relay/state.py | One byte-publication helper replaces both existing mechanisms, preserving serialization, locking, fsync and cleanup behavior. |
| Failed recut recovery | builder | relay/loop.py, relay/queue.py | Capture and atomically restore pre-invocation bytes and mode before parsing known-failed output; reject invalid successful output, preserve failure counting and control branches, and document the restoration ownership exception. |
| Runtime integration | builder | relay/runner.py, relay/loop.py, relay/prompts.py, relay/ledger.py, relay/cli.py | Quiet-stream context polling, capabilities, fresh-thread handoff and mixed historical replay work through minimal loop/CLI edits; direct-child exit cleans descendants while draining buffered output, telemetry snapshots publish atomically, and backend finalization errors fail both lead and recut invocations. |
| Behavioral tests and real fixture capture | test-writer | tests/test_backends.py, tests/test_codex_session.py, tests/test_runner.py, tests/test_loop.py, tests/test_config.py, tests/test_cli.py, tests/test_prompts.py, tests/test_ledger.py, tests/fixtures/ | Capture a tiny real Codex JSON run and matching token_count excerpt, preserving provenance and distinguishing synthetic edge cases; cover rotation, budgets, role errors, malformed/partial/delayed telemetry, discovery and later rollout I/O failure and cleanup, finalization failure overriding successful child reports for lead and recut, descendant-held stdout after direct-child exit, atomic snapshots under concurrent reading and interrupted writing, duplicate events and generic output. Run uv run pytest. |
| Atomic publication and recovery tests | test-writer | tests/test_files.py, tests/test_state.py, tests/test_runner.py, tests/test_loop.py | Cover complete publication, interruption and cleanup, preserved state locking and serialization, failed recuts with valid, malformed, empty or missing output, invocation exceptions, restoration failure, and unchanged failure counting; failed output never becomes successful completion on the next pass. |
| User documentation | builder | README.md | Document backend choice, unsupported Codex dollar/agent telemetry, native-resume versus rotation distinction, the narrow failed-recut queue restoration exception and the exact unexecuted Gauntlet trial command. |

Tests are authored before their implementation step using the interface stubs above; the divvyer cuts the dispatch queue and places the red-test dispatches accordingly. Codex source/help verification and tiny fixture capture are required evidence before adapter implementation; no real Gauntlet run is part of validation.
