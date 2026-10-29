Status: approved.

# Relay: one backend contract for every agent run, and finishing the backends–main merge

## Why

The worktree holds an open merge: HEAD is the backends branch, MERGE_HEAD is main. Every conflicted file's working text is free of conflict markers but unstaged and unvalidated. The four approved designs this merge joins are `docs/superpowers/specs/relay-backends-design.md`, `relay-research-design.md`, `relay-check-design.md` and `relay-ladder-design.md`; every behavior they approve holds unchanged unless this file names it. Research, ask and architect runs now go through the backend adapters, but the contract the backends design wrote for lead and recut does not cover a continued session, so the drafted routing works around it.

Copies and gaps this design closes:

- **Which command a role runs**: two identical role tables, `relay/backends/claude.py:19-28` and `relay/backends/generic.py:20-29`. Config derives role commands twice: `_role_command` (`relay/config.py:74`) and again for recut in `load_config` (`relay/config.py:195-197`).
- **Two argv sources per run**: `_run` passes an argv to `run_agent` (`relay/loop.py:278`), and `run_agent` throws it away whenever a cfg is given (`relay/runner.py:207-208`). The lead, research, design and recut argv passed at `relay/loop.py:152`, `relay/loop.py:328`, `relay/loop.py:600` and `relay/loop.py:681` are never run.
- **Continuing a researcher**: `ask` appends Claude's `--resume <id>` to `research_command` (`relay/loop.py:360`), `_run` smuggles that argv in as a replaced `research_command` (`relay/loop.py:277`), and the Codex adapter reads the session id back out of the command's last two words (`relay/backends/codex.py:57-63`). The generic adapter would run its command with `--resume <id>` appended (`relay/backends/generic.py:24-25`). No capability says whether a backend can continue a session.
- **Whose session a hint names**: state records a session id with no backend (`relay/state.py:255-259`, `relay/state.py:38`). A lead whose previous session came from another backend gets that id worded by the current backend's `resume_hint` (`relay/loop.py:140`), and `relay ask` resumes a researcher with whatever backend its own config file names (`relay/cli.py:89`), not the backend that ran the researcher.
- **What counts as a failed run**: five copies of `killed or exit_code != 0 or is_error`, at `relay/loop.py:167`, `relay/loop.py:334`, `relay/loop.py:365`, `relay/loop.py:627-632` and `relay/loop.py:684`.
- **Capabilities per run**: three adapters built only to read capabilities, `relay/loop.py:128`, `relay/loop.py:387` and `relay/loop.py:573`, beside the per-run adapter `_run` builds (`relay/loop.py:276`).
- **Bad role configuration mid-loop**: a missing or invalid Codex role file raises `ConfigError` inside `run_agent` (`relay/backends/codex.py:37-40`), after `.backend.json` is already written (`relay/runner.py:204-206`). A missing `researcher.toml` or `architect.toml` stops `relay go` at the first research or design run, not at start.
- **Run metadata write**: `.backend.json` is written in place with `write_text` (`relay/runner.py:204`), beside the shared atomic helper `relay/files.py:8`.
- **A resumed Codex thread's telemetry**: `SessionReader` reads its rollout from byte 0 (`relay/backends/codex_session.py:17`) and is built only once the stream reports a session id (`relay/backends/codex.py:127-131`), after the child is running. A resumed thread's rollout already holds the researcher's `token_count` lines, so `finish` sees `observed` (`relay/backends/codex.py:136`) even when the follow-up produced no telemetry of its own; and any boundary taken at the first poll would drop telemetry the child wrote before it. Whether `codex exec resume` appends to the same rollout file or starts a new one, and how soon it creates either, is unmeasured.
- **`codex exec resume` flags**: the drafted argv passes `--json`, `--dangerously-bypass-approvals-and-sandbox` and `-o` to `codex exec resume`, without `-C` (`relay/backends/codex.py:61-63`). Whether 0.165.0's `exec resume` accepts each is unmeasured.

Already single and kept: atomic byte publication in `relay/files.py:8`, with `state.write_atomic` (`relay/state.py:49-51`) a UTF-8 wrapper over it serving `State._save` and `research.save` (`relay/research.py:89`); process start, polling and group cleanup in `run_agent` (`relay/runner.py:184-316`); capability-gated budgets in `Ledger.over` (`relay/ledger.py:159-178`); recut rollback in `_recut` (`relay/loop.py:656-699`).

## Modules

### `relay/backends/base.py` (extended): one invocation for every role

```python
Role = Literal["lead", "recut", "research", "ask", "design"]


@dataclass(frozen=True)
class Capabilities:
    context: bool
    tokens: bool
    dollars: bool
    subagents: bool
    resume: bool          # can continue a saved session natively; Claude True, Codex True, generic False


@dataclass(frozen=True)
class Invocation:
    role: Role
    resume: str | None = None   # the session to continue; only role "ask" sets it


class Backend(Protocol):
    name: str                    # "claude" | "codex" | "generic", as written to .backend.json
    capabilities: Capabilities
    def check(self, cfg: Config, roles: tuple[Role, ...]) -> None:
        """ConfigError for any role in `roles` this backend cannot launch with `cfg`; no I/O beyond
        reading role configuration, no process."""
    def argv(self, inv: Invocation, cfg: Config, cwd: Path, output: Path) -> list[str]:
        """The full argv. ConfigError when inv.resume is set and capabilities.resume is False, or
        inv.resume is None for role "ask"."""
    def prepare(self, inv: Invocation, cfg: Config) -> None:
        """Called by run_agent once per run, after argv and before .backend.json and the spawn.
        Takes whatever this run must measure before its child exists; RelayError on a read
        failure. Claude and generic: no-op."""
    def parse(self, state: StreamState, line: str) -> StreamState: ...
    def poll(self, state: StreamState) -> StreamState: ...
    def finish(self, state: StreamState, output: Path) -> StreamState: ...
    def resume_hint(self, session_id: str) -> str: ...
```

`relay/backends/__init__.py` gains `capabilities(name: str) -> Capabilities`, read from the adapter class without building per-run resources; it replaces the reads at `relay/loop.py:128`, `relay/loop.py:387` and `relay/loop.py:573`. `get_backend` and `replay` are unchanged.

### `relay/backends/claude.py`, `relay/backends/generic.py` (changed)

`argv` returns `cfg.command_for(inv.role)`; Claude appends `["--resume", inv.resume]` for `ask`. Generic sets `resume=False` and raises `ConfigError` on any `inv.resume`. `check` raises nothing for either, and `prepare` does nothing. This replaces both role tables (`relay/backends/claude.py:19-28`, `relay/backends/generic.py:20-29`).

### `relay/backends/codex.py` (changed)

`argv` keeps its role-file mapping (`ask` and `research` both load `researcher.toml`) and overrides, and for `ask` builds `codex exec resume` with `inv.resume` in place of reading it from `research_command`, which replaces `relay/backends/codex.py:57-63`. The resume argv carries exactly the flags the step 1 evidence shows 0.165.0's `exec resume` accepts; a flag it lacks is not passed, and the cwd comes from the runner's `cwd` when `-C` is absent. `check` loads and validates the role file of each role given, through the same loader `argv` uses, so start-up and launch read one validation. `resume=True`.

`prepare`, for an invocation with `resume` set, sets `self.reader = SessionReader(self.home, inv.resume, boundary=rollout_boundary(self.home, inv.resume))`; for any other invocation it leaves `self.reader` unset, and `poll` builds the reader from the stream's session id as now. `poll` reads through the prepared reader from the first poll, before the stream reports any session id. When the stream reports a session id other than the reader's, `poll` replaces the reader with one for that id carrying the same boundary. `finish` polls once more with a forced scan and errors when this run observed none, a resumed run whose rollout never appears included.

### `relay/backends/codex_session.py` (extended): the one preparation/reader contract

```python
@dataclass(frozen=True)
class RolloutBoundary:
    sizes: Mapping[Path, int]   # every rollout whose session_meta id is the resumed id, at its
                                # byte size before the spawn; empty when none exists yet


def rollout_boundary(home: Path, session_id: str) -> RolloutBoundary:
    """Scan home/sessions with the same match SessionReader uses and record each matching
    rollout's size. Called only from an adapter's prepare, so before the child starts.
    RelayError on a read failure."""


class SessionReader:
    def __init__(self, home: Path, session_id: str, *,
                 boundary: RolloutBoundary | None = None): ...
        """No boundary: as now, the first located rollout from byte 0.
        With a boundary: every rollout of session_id is tracked, each with its own offset; one
        in boundary.sizes starts at its recorded size, any other starts at byte 0. Scans for
        new rollouts continue on every poll (rate-limited as now) instead of stopping at the
        first. `observed` turns true only on a token_count read past a rollout's start offset."""
    def poll(self, state: StreamState, *, force_scan: bool = False) -> StreamState: ...
```

So a resumed run counts every `token_count` its child writes, before its first poll included, whether `codex exec resume` appends to the old rollout or creates a new one, early or late; no line that existed before the spawn ever counts.

### `relay/config.py` (extended): one role table

```python
class Config:
    def command_for(self, role: Role) -> list[str]:
        """lead_command, recut_command, research_command (research and ask) or design_command,
        copied; ConfigError on any other role."""
```

`load_config` passes an unset `recut_command` as `[]` and `__post_init__` derives it through `_role_command`, as research and design already do, replacing `relay/config.py:195-197`. Positional `Config` construction and every default are unchanged.

### `relay/runner.py` (changed)

```python
@dataclass(frozen=True)
class RunResult:
    exit_code: int | None
    killed: bool
    stream: StreamState
    log: Path

    @property
    def failed(self) -> bool:
        """killed, a non-zero or missing exit code, or stream.is_error: the one test of a failed run."""


def run_agent(
    inv: Invocation, stdin_text: str, cwd: Path, run_dir: Path,
    on_event: Callable[[StreamState], Literal["go", "retire", "kill"]], retire_flag: Path,
    *, backend: Backend, cfg: Config,
) -> RunResult:
    """backend.argv(inv, cfg, cwd, output) first, then backend.prepare(inv, cfg): a ConfigError
    or RelayError from either leaves no log, metadata or process. Then .backend.json, written with files.atomic_write as {"backend": backend.name},
    then the spawn, polling, publication, finalization and cleanup as now."""
```

The legacy `argv` positional and the `cfg is None` path go; tests call `run_agent` with a backend and cfg (`tests/test_runner.py:54` already does). Process, signal and cleanup behavior (`relay/runner.py:229-316`) is unchanged.

### `relay/state.py` (extended): a session carries its backend

```python
@dataclass
class SectionState:
    ...                                  # existing fields
    last_backend: str = "claude"         # the backend that ran last_session
    research_backend: str = "claude"     # the backend that ran research_session

class State:
    def set_last_session(self, sid: str, session: str, backend: str = "claude") -> None: ...  # also records last_any_backend
    def set_research_session(self, sid: str, session: str | None, backend: str = "claude") -> None: ...
    @property
    def last_backend_any(self) -> str: ...    # "claude" when the record predates it
```

A state record without these keys reads them as `"claude"`.

### `relay/loop.py` (changed)

```python
def _run(cfg, state, ledger, since, kind: Kind, sid, text: str, cwd: Path, flag: Path,
         map_commit=None, rung=None, cap=None, resume: str | None = None
         ) -> tuple[RunResult, _Watch]:
    """One adapter, get_backend(cfg.backend), for the run; its capabilities go to _watcher;
    run_agent(Invocation(kind, resume), ...); ledger.append as now. No argv parameter."""
```

- `run` calls `backends.get_backend(cfg.backend).check(cfg, ("lead", "recut", "research", "design"))` before the first pass; `ask` calls it with `("ask",)` before its run.
- The lead's handoff hint is `get_backend(<recorded backend of the resumed session>).resume_hint(resume)`, from `last_backend` or `last_backend_any`; the lead's session is recorded with `cfg.backend`.
- `_research` records the researcher's session with `cfg.backend`.
- `ask` raises `ResearchError` when `capabilities(cfg.backend).resume` is False, when the section has no `research_session`, or when `research_backend` differs from `cfg.backend`, naming both; otherwise `_run(kind="ask", resume=research_session)`.
- Every failure test reads `result.failed`; `_design_outcome` keeps its reason wording branches (`relay/loop.py:627-632`) and reaches them only when `result.failed`. Idle retire keeps `watch.idle_retired and not result.stream.is_error`.

### `relay/prompts.py` (extended)

`lead_prompt` gains `backend: str = "claude"`. When it is not `"claude"`, the `relay ask` command in the map paragraph reads `relay ask --backend <backend> <queue> <sid> "<question>"`; the Claude wording is unchanged.

### `relay/cli.py` (extended)

`relay ask` gains `--backend`, passed as the `backend` override to `load_config`.

### `README.md` (changed)

The backend section states that `relay ask` uses the backend the researcher ran under, that generic researchers cannot be asked follow-ups, and that every Codex role file is checked when `relay go` starts.

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Role to command, for command-driven backends | `relay/config.py` `Config.command_for`, `_role_command` | a role table in an adapter; a second derivation in `load_config`; replaces `relay/backends/claude.py:19-28`, `relay/backends/generic.py:20-29`, `relay/config.py:195-197` |
| Building a run's argv, a continued session's argv included | the adapter's `argv(Invocation, ...)` | an argv built or passed in `relay/loop.py`; a resume flag appended outside an adapter; a session id read back out of a command; replaces `relay/loop.py:277`, `relay/loop.py:360`, `relay/backends/codex.py:57-63` |
| Whether a backend can continue a session | `Capabilities.resume` | testing a backend name for it |
| Capabilities by backend name | `relay/backends/__init__.py` `capabilities` | building an adapter only to read capabilities; replaces `relay/loop.py:128`, `relay/loop.py:387`, `relay/loop.py:573` |
| Role configuration validity | the adapter's `check`, called by `loop.run` and `loop.ask` before any run | a role-file read at launch that validates differently from `check` |
| Which backend ran a saved session | `relay/state.py` `last_backend`, `research_backend`, `last_backend_any` | wording a hint, or resuming, with a backend other than the recorded one |
| A failed run | `relay/runner.py` `RunResult.failed` | `killed`, `exit_code` and `is_error` tested together anywhere else; replaces `relay/loop.py:167`, `relay/loop.py:334`, `relay/loop.py:365`, `relay/loop.py:684` |
| Run metadata and telemetry publication | `relay/runner.py` through `relay/files.py` `atomic_write` | `write_text` of `.backend.json` or `.telemetry.json`; replaces `relay/runner.py:204` |
| A resumed Codex run's own telemetry | `relay/backends/codex_session.py` `skip_existing` | counting a prior run's `token_count` as this run's |
| Spawn, polling, finalization, group cleanup | `relay/runner.py` `run_agent` | an adapter or loop helper that starts a process |
| Handoff wording | each adapter's `resume_hint`, chosen by the recorded backend | handoff text in `relay/loop.py`; a Terminus recall of a Codex id |
| Test fakes and fixtures | `tests/conftest.py`, `tests/fakes/fake_claude.py`, `tests/fixtures/` | an ad hoc Codex role file or rollout built inside a test file |

## Order

No step commits: the merge is open, and the merge commit in step 9 is the one commit. No step runs Relay, Codex or Claude against a real queue, and no step touches another worktree. Every step writes into this worktree's open merge.

1. Codex resume evidence. `spiker` writes the scratchpad. It records `codex exec resume --help` from the installed CLI and the `exec resume` argument definitions in upstream `rust-v0.165.0` source, with file and line links, for `--json`, `--dangerously-bypass-approvals-and-sandbox`, `-o`, `-C`, `-c` and the stdin `-` prompt. It runs no model call.
2. Stubs. `builder` (`stub` piece) adds every new signature above, raise-only, to `relay/backends/base.py`, `relay/backends/__init__.py`, `relay/backends/codex_session.py`, `relay/config.py`, `relay/runner.py` and `relay/state.py`. New fields go in with their defaults.
3. Contract: red tests. `test-writer` writes `tests/test_backends.py`, `tests/test_codex_session.py`, `tests/test_runner.py`, `tests/test_config.py` and `tests/test_state.py`, and `tests/conftest.py` where a shared Codex role-file or rollout helper is needed. They cover each adapter's argv for every role, a resume on each backend, `check` with missing and invalid role files, no log or metadata after a launch-time `ConfigError`, atomic `.backend.json`, `RunResult.failed`, a resumed rollout's prior lines not counting, and legacy state records reading `"claude"`.
4. Contract: build. `builder` writes `relay/backends/base.py`, `relay/backends/__init__.py`, `relay/backends/claude.py`, `relay/backends/generic.py`, `relay/backends/codex.py`, `relay/backends/codex_session.py`, `relay/config.py`, `relay/runner.py` and `relay/state.py`, the Codex resume argv from step 1's evidence.
5. Loop, prompts, CLI: red tests. `test-writer` writes `tests/test_loop.py`, `tests/test_prompts.py` and `tests/test_cli.py`. They cover research, ask and design runs on Claude, Codex (fake adapter) and generic; `relay go` stopping at start on a bad role file; `relay ask` refused on generic and on a backend mismatch, and carried by `--backend`; the lead's hint worded by the recorded backend across a backend change; every failure branch through `result.failed`; and the approved research, check and ladder loop behavior unchanged (the existing tests stay green unedited except where a call shape above changes).
6. Loop, prompts, CLI: build. `builder` writes `relay/loop.py`, `relay/prompts.py`, `relay/cli.py` and `README.md`.
7. Blind review. `diff-reviewer` reads `git diff HEAD` and `git diff MERGE_HEAD` against this file and the four approved designs; `test-reviewer` reads the test diff the same way. Findings go back to steps 4 and 6's agents.
8. Stage. `lead` stages every path of the merge, the conflicted ones included, and checks `git diff --check` and that no conflict marker remains.
9. Verify and commit. `lead` runs `uv run pytest` itself; on green it makes the merge commit, its parents HEAD and MERGE_HEAD as they stand.
