Status: approved.

# Relay run overhead

## Why

A queue step goes from lead to built and landed only if Relay's own text and measurements send the lead nothing false. Six Relay-side causes keep that from happening, each anchored at HEAD:

1. **False retire.** `relay/stream.py:76-88` sets `context_tokens` from every `assistant` event. That includes subagent events, the ones whose `parent_tool_use_id` is set: in the lead's run log, 88 of 109 assistant events are a subagent's. `relay/loop.py:557,566,576` retire and kill the lead on that figure, so a builder's 105k context retired a lead whose own context peaked at about 66k. The figure is read in three places, each trusting the one value.
2. **Killed lead, then a loaded resume.** `relay/runner.py:323-326` starts every agent child with the parent's environment, unchanged. The Claude CLI stops a print-mode session's background agents 10 minutes after its last turn unless `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` is set. That message is in the earlier lead's stderr. That lead died with no status line and was counted as a failure (`relay/loop.py:260-266`). Then `relay/loop.py:257` saved its last reply ("still running; waiting for its report") as `last_report`, and `relay/prompts.py:51-54` handed it to the next lead as "the previous lead's final report … you need not recall it". The next lead recalled the old session anyway, and was about 55k into its context before its first dispatch.
3. **A map that workers reject.** `relay/research.py:239-246` puts a read-and-search instruction into the map block. `relay/prompts.py:66-74` tells the lead to paste that block verbatim into every brief. The builder rejected the brief as steering, quoting the instruction and three map entries that state conclusions ("states no PROVEN entry exists", "line 288 says no HookSurface or PROVEN entry is justified"). `relay/prompts.py:195-212` (`_map_form`, shared by `research_brief` at `:215` and `refresh_brief` at `:225`) does not limit what an entry may say.
4. **No rule for a worker's refusal.** `relay/prompts.py:75-83` covers retiring and RECUT for a wrong cut. It says nothing about a worker that rejects, refuses as overloaded, or stops heavy. So the lead assayed the rejection, wrote its own cut and resent it, and that cut ran to 107k.
5. **Dispatch after retire.** The retire contract (`relay/prompts.py:75-83`) is only text. Nothing stops an `Agent` call once the retire flag is up (`relay/runner.py:316-318`), and the lead started an assayer 52 seconds after the flag went up.
6. **A misleading research figure.** `relay/progress.py:45-47` prints `spend.tokens`, which `relay/stream.py:86` builds by adding every turn's full context, cache re-reads included. That gives "149247 tokens" for a run whose largest context was 26,840 and whose cost was $0.52. `research_brief` (`relay/prompts.py:215-222`) leaves it to the researcher whether to send readers, so mapping one file took a researcher and a reader.

## Modules

**`relay/stream.py`**: measures the main thread's context only. Subagent usage still counts toward spend. Replaces the unconditional `context_tokens=context` at `relay/stream.py:88`.

```python
@dataclass
class StreamState:
    session_id: str | None
    context_tokens: int          # the main thread's latest context; subagent events never set it
    spend: Spend                 # every assistant message, subagents included
    result_text: str | None
    is_error: bool
    seen_messages: frozenset[str] = frozenset()
    activity: agents.Activity = agents.Activity()
    usage: tuple[Usage, ...] = ()
    peak_context: int = 0        # the largest context_tokens seen in the run

def feed(state: StreamState, line: str) -> StreamState:
    """An assistant event whose parent_tool_use_id is a string adds to spend and seen_messages
    and leaves context_tokens and peak_context unchanged."""
```

**`relay/backends/base.py`**: one launch description per backend child. `run_agent` applies it. Replaces the bare `Popen(argv, cwd=cwd, ...)` at `relay/runner.py:323-326`.

```python
@dataclass(frozen=True)
class Launch:
    extra_argv: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)   # merged over os.environ

class Backend(Protocol):
    def launch(self, role: str, retire_flag: Path, run_dir: Path) -> Launch: ...
```

**`relay/backends/claude.py`**: the Claude child's environment, plus the retire gate for a lead.

```python
CHILD_ENV: Mapping[str, str] = {"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0"}

class ClaudeBackend:
    def launch(self, role: str, retire_flag: Path, run_dir: Path) -> Launch:
        """env=CHILD_ENV for every role. For role "lead", also writes run_dir/retire-gate.settings.json,
        holding a PreToolUse hook (matcher "Agent") that runs
        [sys.executable, "-m", "relay.retire_gate", str(retire_flag)], and returns
        extra_argv=("--settings", <that path>)."""
```

`relay/backends/codex.py` and `relay/backends/generic.py` return `Launch()`.

**`relay/retire_gate.py`**: the hook that refuses a new dispatch once the retire flag is up. It is new and replaces nothing. The contract text in `lead_prompt` stays.

```python
REFUSAL = "Relay's retire flag is up: dispatch nothing new, wait for running agents, end with RETIRED."

def main(argv: list[str]) -> int:
    """argv[0] is the retire flag's path. Reads and discards the hook's stdin. Prints REFUSAL to
    stderr and returns 2 when the flag exists; otherwise returns 0."""
```

**`relay/research.py`**: `block()` is the map's header and body, with no instruction lines. Replaces `rule` at `relay/research.py:241-245`.

```python
def block(m: Map) -> str:
    """f"{_header(m.sid, m.commit)}\n{m.body}\n" and nothing else."""
```

**`relay/prompts.py`**: every text sent to an agent, now including the entry rule, the handoff and the worker-reply contract.

```python
ENTRY_RULE: str
# Appended by _map_form. Each entry names what lies at its lines (a symbol, table, section or
# call) in nouns. An entry never says what the code proves, lacks, allows or justifies, and never
# tells a reader what to open, skip or search.

READ_RULE: str
# In research_brief and refresh_brief: read the section's files yourself, and send a reader only
# for a file too large to read whole within the map caps.

WORKER_RULE: str
# In lead_prompt, after the retire contract:
# - A worker that replies OVERLOADED, or stops heavy with work left: end this session with
#   RECUT: <that worker's report>. Never cut or resend the step yourself.
# - A worker that replies REJECTED: STEERING: resend the same brief once, with the quoted lines
#   struck and nothing added. No assayer runs on a rejection. A second rejection of the same step
#   ends the session with RECUT: <both rejections>.

def handoff(result: RunResult, status: LeadStatus | None) -> str | None:
    """With a status: "The previous lead's final report (that session's last reply, so you need
    not recall it):\n<result_text>", or None when result_text is empty. With no status:
    "The previous lead stopped without a final report (<error_line(result)>). Its last reply:
    <result_text or 'none'>\nIts agents, as Relay saw them: <one line per agents.Agent:
    name, description, status or 'running when it stopped'>.\""""

def lead_prompt(..., report: str | None, ...) -> str:
    """report is handoff()'s text and is printed as given, with no heading added. The map paragraph
    keeps its paste-verbatim and relay-ask lines and holds only block()'s text."""
```

**`relay/loop.py`**: stores `handoff(result, status)` instead of the raw reply. Replaces `state.set_last_report(sid, result.stream.result_text or None)` at `relay/loop.py:257`. `parse_status` moves above that line.

**`relay/progress.py`**: the spend figure tells re-read context apart from real size. Replaces `_spend` at `relay/progress.py:45-47`.

```python
def _spend(result: RunResult) -> str:
    """f"(peak context {peak_context}, {spend.tokens} tokens summed over turns, ${dollars:.2f})"."""
```

The token budget (`relay/ledger.py`) still meters `spend.tokens`. Its meaning does not change.

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Lead context measurement | `relay/stream.py` `feed`, main-thread events only | Reading context from a subagent's usage. `loop._watcher` (`relay/loop.py:557-582`) reads only `context_tokens`. `relay/backends/codex_session.py:231,236,261` keeps its own Codex measure. |
| Child process environment and extra arguments | `Backend.launch`, applied once in `runner.run_agent` | Setting env vars or adding CLI flags for an agent child anywhere else, config defaults included (`relay/config.py:11-14,76-79`). `run_command` and `capture` (`relay/runner.py:440-470`) run gates, not agents, and take none. |
| Enforcing retire | `relay/retire_gate.py`, installed by `ClaudeBackend.launch` | A second check of the flag in Relay code. The prompt text states the contract and the hook enforces it. |
| Map text sent to agents | `research.block` | Any instruction line around the map, in `research.py` or `prompts.py`. |
| What a map entry may say | `prompts.ENTRY_RULE`, through `_map_form` | Entry rules written separately in `research_brief` or `refresh_brief`. |
| Text handed to the next lead | `prompts.handoff` | `loop.py` storing a raw `result_text` as `last_report`. |
| A worker's refusal | `prompts.WORKER_RULE` in `lead_prompt` | Any other lead-facing text about rejections or resends. |
| Spend shown in progress lines | `progress._spend` | Any other place that formats run tokens or dollars for a progress line. |
| Stream test events | `tests/fixtures/stream-*.jsonl`, read by `tests/test_stream.py:31` `_lines` | Inline JSON event literals in new tests. |
| Fake Claude child | `tests/fakes/fake_claude.py` | A second fake CLI. A runner test that needs to see env or argv reads it through this fake. |

## Order

1. **Main-thread context.** `test-writer`: `tests/test_stream.py`, `tests/fixtures/stream-subagent-context.jsonl`, `tests/test_loop.py`. Then `builder`: `relay/stream.py`.
2. **Launch and child env.** `builder` (stub): `relay/backends/base.py`, `relay/backends/claude.py`, `relay/backends/codex.py`, `relay/backends/generic.py`. Then `test-writer`: `tests/test_backends.py`, `tests/test_runner.py`, `tests/fakes/fake_claude.py`, plus the fake backends in `tests/test_runner.py:508` and `tests/test_loop.py:1157,1210,1255,1314`, which gain `launch`. Then `builder`: the four backend files and `relay/runner.py`.
3. **Retire gate.** `builder` (stub): `relay/retire_gate.py`. Then `test-writer`: `tests/test_retire_gate.py`, `tests/test_backends.py`. Then `builder`: `relay/retire_gate.py`, `relay/backends/claude.py`.
4. **Instruction-free map.** `test-writer`: `tests/test_research.py`, `tests/test_prompts.py`, `tests/fixtures/research-*.txt` where a fixture carries the old rule. Then `builder`: `relay/research.py`, `relay/prompts.py` (`block`, `ENTRY_RULE`, `READ_RULE`, the map paragraph).
5. **Handoff after a stopped lead.** `builder` (stub): `relay/prompts.py` `handoff`. Then `test-writer`: `tests/test_prompts.py`, `tests/test_loop.py`. Then `builder`: `relay/prompts.py`, `relay/loop.py`.
6. **Worker-reply contract.** `test-writer`: `tests/test_prompts.py`. Then `builder`: `relay/prompts.py` (`WORKER_RULE`).
7. **Spend line.** `test-writer`: `tests/test_progress.py`. Then `builder`: `relay/progress.py`.

Step 7 needs step 1's `peak_context`. Step 3 needs step 2's `Launch`. All seven steps run on branch `fix/run-overhead` at `/Users/atom/dev/relay-wt/run-overhead`, and nothing is pushed or merged.
