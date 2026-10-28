Status: approved.

# Relay: a researcher and its readers map each section's code before its lead starts

## Why

A lead starts with nothing but the queue section (`relay/prompts.py:17-51`), so it and every agent it dispatches read the code from scratch. Relay has no notion of a researcher, a reader or a map anywhere in `relay/` or `tests/`.

Copies and gaps this design closes:

- **Starting an agent run**: two copies of the same sequence, `_watcher`, `run_agent`, `ledger.append`, at `relay/loop.py:101-107` (lead) and `relay/loop.py:198-201` (recut). This design adds two more runs (research, ask), so the sequence moves to one helper first.
- **The retire flag**: one file for every run, `relay/state.py:209-210`, unlinked before each lead (`relay/loop.py:103`) and touched by `relay/runner.py:133`. A follow-up asked while the lead runs would touch the lead's flag and retire it, so a research run gets its own flag.
- **Agent commands**: built only in `relay/config.py`; `recut_command` derives from `lead_command` at `relay/config.py:165`. The research command follows that pattern.
- **Run kinds**: `relay/ledger.py:45` takes only `"lead"` and `"recut"`; `relay/progress.py:94` and `relay/loop.py:142` take the same two.
- **Subagent tokens**: the stream carries each subagent's `total_tokens` (`tests/fixtures/stream-agents.jsonl:5`), folded by `relay/agents.py:60-96`, but a ledger line keeps only the run's own spend (`relay/ledger.py:50-57`). `relay status` rebuilds agents from run logs (`relay/cli.py:80-106`). Nothing records which runs had a map.
- **Git queries**: `relay/git.py:12-39` asks for worktrees and branch heads only; nothing reads HEAD or diffs against a commit.
- **A section's working directory**: the check design's `_verify` runs in `git.section_worktree(cwd, sid)` or else `cwd`; the researcher needs the same choice, so it becomes one helper.
- **Section state**: `relay/state.py:29-38` keeps no per-section run besides the lead's session; `mark_done` (`relay/state.py:112-119`) clears only check fields.

This design builds on the approved check design (`docs/superpowers/specs/relay-check-design.md`): its `_verify`, `_park` and idle `_watcher` in `relay/loop.py` land before this design's loop step.

## Modules

### `relay/research.py` (new): the map's format, caps, file, staleness and the follow-up answer

```python
from dataclasses import dataclass
from pathlib import Path

from relay.config import Config

MAP_OPEN = "MAP"
LINKS = "LINKS"
MAP_CLOSE = "END MAP"
ANSWER_OPEN = "ANSWER"
ANSWER_CLOSE = "END ANSWER"


@dataclass(frozen=True)
class Map:
    sid: str
    commit: str               # the HEAD Relay read in the research cwd before the researcher ran
    files: tuple[str, ...]    # every path an entry or link names, sorted, no repeats
    body: str                 # the lines from MAP to END MAP, both included


def parse_map(sid: str, commit: str, result_text: str | None, cfg: Config) -> Map | None:
    """The last block in result_text that opens on a line `MAP` and closes on a line `END MAP`.
    Inside it: entry lines `<path>:<line>[-<line>] | <what it does>`, then an optional line
    `LINKS` and link lines `<path>:<line> -> <path>:<line> | <how they connect>`. None when
    there is no block, a line fits neither form, there is no entry, or the block is over
    cfg.map_max_lines lines or cfg.map_max_chars characters."""


def save(m: Map, path: Path) -> None:
    """Write `map <sid> at <commit>` then m.body to `path` by temp file and os.replace,
    making the parent directory."""


def load(path: Path, sid: str) -> Map | None:
    """The map saved at `path`; None when the file is missing, unreadable, names another
    section, or its body no longer parses."""


def stale(m: Map, cwd: Path) -> bool:
    """True unless git.changed(cwd, m.commit, m.files) is False."""


def block(m: Map) -> str:
    """The text every brief in the section carries verbatim: one paragraph telling the agent
    to start from the map, open a named file only at the lines it gives, and, needing more,
    say what in its report rather than search, since the lead asks the researcher; then
    `map <sid> at <commit>` and m.body."""


def parse_answer(result_text: str | None, cfg: Config) -> str | None:
    """The last block from a line `ANSWER` to a line `END ANSWER`, both included; None when
    absent or over cfg.map_max_chars characters."""
```

It replaces nothing.

### `relay/git.py` (extended): HEAD and a diff

```python
def head(cwd: Path) -> str | None:
    """`git rev-parse HEAD` in `cwd`; None when git fails."""


def changed(cwd: Path, commit: str, paths: tuple[str, ...]) -> bool | None:
    """`git diff --name-only <commit> -- <paths>` in `cwd`, which compares the working tree:
    False on exit 0 with no output, True on exit 0 with output, None when git fails."""
```

Both run git through `runner.capture`. Neither raises.

### `relay/config.py` (extended): three keys

```python
@dataclass(frozen=True)
class Config:
    ...                          # existing fields, in their order
    research_command: list[str] | None = None   # default [*lead_command, "--agent", "researcher",
                                                # "--model", "opus[1m]"], set in __post_init__
                                                # and load_config as recut_command's default is
    map_max_lines: int = 150     # positive integer
    map_max_chars: int = 12_000  # positive integer
```

All three keys join `_KEYS`. The 1M window is the default model's alone: Relay's `context_limit`, `idle_ceiling` and `hard_ceiling` watch a research run unchanged.

### `relay/state.py` (extended): the researcher's session, the map file, the research flag and lock

```python
@dataclass
class SectionState:
    ...                                   # existing fields
    research_session: str | None = None   # the researcher a follow-up resumes

class State:
    def map_path(self, sid: str) -> Path: ...         # <dir>/maps/<sid>.map
    def research_flag(self, sid: str) -> Path: ...    # run_dir / "research-<sid>": the research runs' retire flag
    def set_research_session(self, sid: str, session: str | None) -> None: ...
    def drop_map(self, sid: str) -> None: ...         # clears research_session, deletes map_path(sid)
    @contextlib.contextmanager
    def research_lock(self, sid: str) -> Iterator[None]: ...   # blocking flock on <dir>/research-<sid>.lock
```

`mark_done` also calls the work of `drop_map`.

### `relay/ledger.py` (extended): research and ask lines, the map and the agents on every run line

```python
Kind = Literal["lead", "recut", "research", "ask"]

def append(
    self,
    kind: Kind,
    section: str,
    session: str | None,
    spend: Spend,
    map_commit: str | None = None,             # the map the run's prompt carried; null when none
    agents: tuple["Agent", ...] = (),          # each subagent: {"name", "task_id", "total_tokens"}
) -> None: ...
```

A lead line's `map` and `agents` give the lead's and its dispatched agents' tokens with and without a map; a research line's `agents` are its readers. `_parse` is unchanged, so `total`, `over`, `unreadable` and `sessions` read the new lines as they read lead lines. `total_tokens` is what the stream reports per subagent (`relay/agents.py:51`); whether a run's own `tokens` already include its subagents' is unmeasured.

### `relay/errors.py` (extended)

```python
class ResearchError(RelayError):
    exit_code = 1
```

### `relay/prompts.py` (extended)

```python
def lead_prompt(queue, section, resume, answer, retire_flag, check_feedback=None,
                map_block: str | None = None) -> str:
    """As now, plus, when map_block is set: "Relay's researcher mapped this section's code.
    Put the block below verbatim in every brief you send for this section, the architect's
    included. When an agent reports it needs more, run `relay ask <queue> <sid> "<question>"`
    and pass on its answer; no agent searches for it." and the block."""

def research_brief(queue: Path, section: Section, flag: Path, cfg: Config) -> str:
    """The queue path, the section id and body, the caps cfg.map_max_lines and
    cfg.map_max_chars, the MAP / LINKS / END MAP form, and: "When the file <flag> exists,
    send no more readers and return the map you have.""""

def ask_brief(question: str, flag: Path, cfg: Config) -> str:
    """The question, the ANSWER / END ANSWER form, the cap cfg.map_max_chars, the flag rule."""
```

### `relay/progress.py` (extended)

```python
def research_started(sid: str, cwd: Path) -> None: ...                    # "research <sid>: mapping in <cwd>"
def research_finished(sid: str, result: RunResult, m: Map | None) -> None: ...  # "research <sid>: map of <n> lines, <f> files at <commit> <spend>" | "no usable map <spend>; the lead starts without one"
def map_reused(sid: str, m: Map) -> None: ...                             # "research <sid>: map at <commit> still current, reused"
def agent_event(who: Literal["lead", "recut", "research", "ask"], sid: str, event: Event) -> None: ...
```

`relay ask` prints only the answer on stdout; its progress goes nowhere.

### `relay/loop.py` (changed)

```python
def _section_cwd(cwd: Path, sid: str) -> Path:
    """git.section_worktree(cwd, sid) or else cwd: where a section's check and research run."""

def _run(cfg, state, ledger, since: float | None, kind: Kind, sid: str, argv: list[str],
         text: str, cwd: Path, flag: Path, map_commit: str | None = None
         ) -> tuple[RunResult, list[bool]]:
    """_watcher, run_agent, then ledger.append(kind, sid, session, spend, map_commit,
    result.stream.activity.agents): the one agent run. Returns the result and the budget slot."""

def _watcher(cfg, ledger, since: float | None, who: Kind, sid, repo) -> _Watch:
    """As the check design has it; since None skips the budget test."""

def _research(cfg, state, ledger, since, cwd, queue, section) -> Map | None:
    """In _section_cwd(cwd, sid): a saved map that is not stale gets map_reused and is
    returned, the researcher kept. Otherwise drop_map, read git.head (None: no map, no run),
    unlink research_flag(sid), run research_command with research_brief through _run (kind
    "research"), set_research_session, parse_map, save it, progress.research_finished. A run
    that fails, is killed or returns no usable map records no failure and returns None."""

def ask(queue: Path, cfg: Config, sid: str, question: str) -> str:
    """Under state.research_lock(sid), without the `relay go` lock: resume the section's
    research_session with [*research_command, "--resume", session] and ask_brief, through
    _run (kind "ask", since None) in _section_cwd, its flag research_flag(sid). Returns
    parse_answer's text. ResearchError when the section has no research_session, the run
    fails or is killed, or there is no answer."""
```

`_run_section` changes in two places:

- Before a lead runs (never on the `check_pending` path), `_research` runs; its map's `block` goes to `lead_prompt` as `map_block`, and its commit to the lead's ledger line.
- The lead run goes through `_run`, replacing `relay/loop.py:101-107`.

`_recut` runs through `_run`, replacing `relay/loop.py:198-201`, and calls `state.drop_map(section.id)` when the recut queue no longer holds `section.id`. A recut that keeps the id keeps the map, and the next pass's `_research` reuses or refreshes it.

### `relay/cli.py` (extended)

```python
# relay ask <queue> <section> <question>: print loop.ask's answer on stdout, exit 0;
# a ResearchError goes through main's RelayError handling.
_COMMANDS = {"go": _go, "stop": _stop, "answer": _answer, "status": _status, "ask": _ask}
```

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| The map's form, caps check, file, staleness, the answer's form, the block every brief carries | `relay/research.py` | parsing or writing a map or an answer, or wording the map's usage rule, anywhere else |
| Starting an agent run, ledgering it | `relay/loop.py` `_run` | `run_agent` or `ledger.append` called anywhere else; replaces `relay/loop.py:101-107`, `relay/loop.py:198-201` |
| Where a section's check and research run | `relay/loop.py` `_section_cwd` | `git.section_worktree` called anywhere else in `loop.py` |
| When research runs, is reused or refreshed | `relay/loop.py` `_research` | a research run started anywhere else |
| Follow-up questions | `relay/loop.py` `ask`, reached by `relay ask` | resuming a researcher anywhere else |
| Git HEAD and diff | `relay/git.py` | a `git` argv anywhere else |
| Research command, map caps and their defaults | `relay/config.py` | a `"researcher"`, `"opus[1m]"` or cap literal anywhere else |
| Researcher session, map path, research flag, research lock; dropping the map when the section is done | `relay/state.py` | a path joined onto the state directory or `run_dir` elsewhere |
| Run lines with map commit and agents' tokens | `relay/ledger.py` `append` | writing `ledger.jsonl` anywhere else |
| Lead-facing map wording, research and ask briefs | `relay/prompts.py` | brief text in `loop.py` or `research.py`, `block` excepted |
| Progress lines for research | `relay/progress.py` | printing them anywhere else |
| How the researcher scopes, groups, fans out and stitches; how a reader reads and hands back | `/Users/atom/.claude/agents/researcher.md`, `/Users/atom/.claude/agents/reader.md` | a second statement of either in another role file or in Relay |
| Putting the map in every brief, routing follow-ups through `relay ask` | `/Users/atom/.claude/agents/lead.md` | the same rule in another role file |
| Test fakes and fixtures | `tests/conftest.py`, `tests/fakes/fake_claude.py`, `tests/fixtures/` | an ad hoc map, research stream or git repo built inside a test file |

## Order

1. Stubs. `builder` (`stub` piece) writes `relay/research.py`, and adds to `relay/git.py`, `relay/config.py`, `relay/state.py`, `relay/ledger.py`, `relay/errors.py`, `relay/prompts.py` and `relay/progress.py` every new signature above, raise-only. New fields go in with their defaults.
2. Test helpers. `test-writer` writes `tests/conftest.py`, `tests/fakes/fake_claude.py`, `tests/fixtures/stream-research.jsonl`, `tests/fixtures/stream-ask.jsonl` and `tests/fixtures/research-map.txt`. `fake_cfg` gains the three config fields. `fake_claude.py` emits the scenario named by `RELAY_FAKE_SCENARIO_RESEARCHER` when its argv carries `--agent researcher` and that variable is set, and `RELAY_FAKE_SCENARIO` otherwise. The research stream holds reader `task_*` events and a final map; the ask stream holds an answer.
3. Core: red tests. `test-writer` writes `tests/test_research.py`, `tests/test_git.py`, `tests/test_config.py`, `tests/test_state.py` and `tests/test_ledger.py`.
4. Core: build. `builder` writes `relay/research.py`, `relay/git.py`, `relay/config.py`, `relay/state.py`, `relay/ledger.py` and `relay/errors.py`.
5. Prompts, progress: red tests. `test-writer` writes `tests/test_prompts.py` and `tests/test_progress.py`.
6. Prompts, progress: build. `builder` writes `relay/prompts.py` and `relay/progress.py`.
7. Loop, CLI: red tests. `test-writer` writes `tests/test_loop.py` and `tests/test_cli.py`. The tests cover:
   - research before a lead, its map in the lead prompt, the lead's ledger line carrying the map commit and agents;
   - no research on a `check_pending` pass;
   - reuse after a retire with the mapped files unchanged, refresh after one changed, both in the section worktree;
   - a failed, killed or over-cap research: the lead starts without a map, no failure counted;
   - the research run's own flag, the lead's flag untouched;
   - the map dropped on `DONE` and on a recut that removes the section;
   - `relay ask`: the answer printed, the session resumed, an `ask` ledger line, and exit 1 with no session.
8. Loop, CLI: build. `builder` writes `relay/loop.py` and `relay/cli.py`, after the check design's loop step has landed, with `_run` replacing `relay/loop.py:101-107` and `relay/loop.py:198-201`. The step ends with the full suite green.
9. Researcher and reader. `general-purpose` writes `/Users/atom/.claude/agents/researcher.md` and `/Users/atom/.claude/agents/reader.md`.
   - Both: read-only, never edit, never build or run tests; `effort: medium`. The reader's frontmatter sets `model: opus`; the researcher's model comes from Relay's `research_command`. Tools: researcher `Read`, `Grep`, `Glob`, `Agent` (readers only), and `Bash` for `wc`, `ls` and read-only `git`; reader `Read`, `Grep`, `Glob`.
   - Researcher scope: the section's step in its design, the step's paths and files, and the in-repository files those import.
   - Researcher fan-out: split the files into groups each well inside a reader's context, send one reader per group, all in one message so they run in parallel; read little itself beyond the readers' pieces and the lines a link needs.
   - Reader: reads only its group, returns a piece of at most 40 lines: entry lines `<path>:<line>[-<line>] | <what it does>`, and `OUT <path>:<line> -> <name or path> | <how>` for each reference leaving the group. Nearing its context, it returns `SPLIT` alone and no notes; the researcher splits that group smaller and sends fresh readers. No reader's notes reach another reader.
   - Researcher stitches pieces into Relay's map form and caps, turns `OUT` lines into `LINKS`, sends a reader at each gap, and ends its final message with the map: `file:line` pointers, one line each, no prose, no advice on the step. The 1M window is never planned on; when the brief's flag file exists it sends no more readers and returns the map it has.
   - On a follow-up it answers in the `ANSWER` form, sending readers as it needs, in the same pointer style.
10. Lead and architect. `general-purpose` writes `/Users/atom/.claude/agents/lead.md` and `/Users/atom/.claude/agents/architect.md`, and every other roster role file whose brief rules would reject Relay's map block.
    - `lead.md`: a lead prompt carrying a map block puts it verbatim in every brief for the section, the architect's included. When an agent reports it needs more, the lead runs `relay ask <queue> <sid> "<question>"` with a 600000 ms timeout or in the background, and passes the answer on; on a non-zero exit the agent reads for itself.
    - `architect.md` and the others: Relay's map block in a brief is legal and never steering; the agent starts from it and, needing more, says so in its report.
11. Opal copy list. `general-purpose` adds `researcher.md` and `reader.md` to the list of agent files copied to Opal. Nothing is copied to Opal.
