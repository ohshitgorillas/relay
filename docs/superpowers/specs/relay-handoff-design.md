Status: approved.

# Relay: whole-section leads, full handoffs, fast checks

## Why

Relay already carries a stopped lead's final report into the next lead's prompt (`relay/loop.py:110`, `relay/prompts.py:28`). It also runs every lead in one checkout, the git top level of the queue's directory (`relay/loop.py:23`, `relay/loop.py:50`), so every lead for a section commits on the same branch. A lead started by hand with the Agent tool gets neither of these. This design closes the gaps the owner saw:

- **No handoff without a report.** The handoff is only the lead's own last reply. A lead that is killed or crashes leaves `result_text` empty, and the next lead gets nothing (`relay/loop.py:110`). Relay holds facts that would fill the gap but passes none of them on: the run log (`relay/runner.py:81`), the subagents still live when the lead ended (`relay/agents.py:29`), and the commits the run made.
- **Worker reports are lost.** No contract stops a lead from ending while a worker it started is still running (`relay/prompts.py:40`).
- **git is not in one home.** The only git logic is `_git_top`, which sits in `relay/loop.py:23`.
- **No end-of-section gate.** Relay marks a section done as soon as the lead says DONE (`relay/loop.py:121`). No full-suite check stands between that line and `mark_done`.
- **`tests/test_loop.py` is slow.** It is 2625 lines and holds 97 tests. Every lead in it is a real `python` child: the fake at `tests/fakes/fake_claude.py:15`, and often the shims at `tests/test_loop.py:535` and `tests/test_loop.py:813` as well, which start a second child each. Each test runs `git init` (`tests/test_loop.py:52`), and the file has 18 fixed `time.sleep(SETTLE)` waits of 0.5 s each (`tests/test_loop.py:42`). How much each of these adds to the 85 s is unmeasured. The file also holds its own harness, so no smaller file can reuse it. That harness covers `_Background` (`tests/test_loop.py:91`), `_until` (`tests/test_loop.py:2357`), `_ledger_line` (`tests/test_loop.py:69`) and `_pings` (`tests/test_loop.py:57`). `_until` is also written out inline a second time, inside `_SHIM` (`tests/test_loop.py:561`). The ping recorder `_RECORD` appears twice, at `tests/test_ping.py:16` and `tests/test_loop.py:39`.
- **No pinned linter.** `pyproject.toml` pins no linter and sets no format. The tree has no single line width: 166 lines are longer than 100 characters and 5 are longer than 130. So any `ruff format` run rewraps code.

## Modules

`relay/runner.py` gains short-lived commands, so it stays the one place a child process runs.

```python
@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    output: str                # stdout and stderr together, verbatim

def run_command(argv: list[str], cwd: Path) -> CommandResult: ...
# Runs argv in its own process group, waits for it, and kills and reaps the group on SIGINT, SIGTERM or an exception, as run_agent does.
```

`relay/git.py`: the only Relay code that reads git. It replaces `_git_top` (`relay/loop.py:23`).

```python
def top(directory: Path) -> Path: ...              # the nearest ancestor holding a `.git` (a file in a worktree, a dir in a main checkout), or directory itself
def branch(top: Path) -> str | None: ...           # `git symbolic-ref --short HEAD`; None when HEAD is detached or top is no repository
def head(top: Path) -> str | None: ...             # `git rev-parse --short HEAD`; None when there is no commit
def commits(top: Path, since: str | None) -> list[str]: ...  # `git log --oneline since..HEAD`, newest first; [] when since is None or equals HEAD
```

`relay/handoff.py`: the one place a lead's handoff is put together and worded. `relay/prompts.py` writes the handoff into the prompt verbatim.

```python
@dataclass(frozen=True)
class Handoff:
    report: str | None         # RunResult.stream.result_text; None when the lead left none
    branch: str | None         # git.branch(cwd) at the lead's end
    commits: list[str]         # git.commits(cwd, head at the lead's start)
    live_agents: tuple[agents.Agent, ...]   # Activity.agents whose task_id is in Activity.live at the lead's end
    log: Path                  # RunResult.log
    check_output: str | None   # the tail of a failed section check, else None

def build(result: RunResult, branch: str | None, commits: list[str], check_output: str | None) -> Handoff: ...
def render(handoff: Handoff) -> str: ...
```

`render` gives these parts, in this order:
1. The report verbatim, under a heading that names it the previous lead's final report. When there is no report, a line saying the previous lead left none.
2. The branch, and each commit the run made.
3. Each live agent's task id, type and description, with a line saying its report never reached the lead. Whether `recall-session` accepts a task id is unverified.
4. The run log path.
5. The failed check's tail, when there is one.

`render` never returns an empty string.

`relay/queue.py`: `Section` gains `check: str | None`. It is read from a header field `check: <command>`, and that field is taken out of `title`. The divvyer writes the field on each lead section, set to the repository's full-suite command.

`relay/loop.py` changes as follows:
- `cwd` comes from `git.top(queue.parent)`.
- Step 6 records `git.head(cwd)` before the lead starts.
- Step 7 stores `handoff.render(handoff.build(...))` through `set_last_report` whenever the run has a session, so every next lead gets a handoff. A run with no session still leaves the old one in place.
- Step 8 DONE: when `section.check` is set, the loop first runs `runner.run_command(["/bin/sh", "-c", section.check], cwd)`. Exit 0 calls `mark_done`. Any other exit counts as a failure: `record_failure`, with the check's output tail (its last 40 lines) stored in the handoff, so the next lead starts from the failing lines. A section without `check` is marked done as today.

`relay/progress.py` gains `check_started(sid: str, command: str) -> None` and `check_finished(sid: str, exit_code: int) -> None`. These are the terminal lines for the section check.

`relay/prompts.py`: `lead_prompt(queue, section, resume, handoff: str | None, answer, retire_flag, branch: str | None)`. The `report` parameter becomes `handoff`, the rendered text, set under the same heading rule. The prompt names the branch and adds four contracts:
- Commit only on that branch, in the working directory Relay started the lead in. Never switch branches, never make a worktree.
- Never end, with any status, while a worker the lead started is still running. Wait for its report first.
- A step's done-check runs only that step's tests.
- Relay runs the section's full suite after DONE. The lead does not run it.

`relay/state.py`: unchanged. `SectionState.last_report` holds the rendered handoff.

Test harness:

```python
# tests/harness.py: the loop-test helpers every loop test file shares, moved from tests/test_loop.py
RECORD: str                                    # the ping recorder, from tests/test_loop.py:39 and tests/test_ping.py:16
class Background: ...                          # tests/test_loop.py:91
def until(condition: Callable[[], bool], timeout: float = 15.0) -> None: ...   # tests/test_loop.py:2357; replaces every time.sleep(SETTLE)
def ledger_line(state: State, stamp: float, tokens: int, dollars: float) -> None: ...
def pings(tmp_path: Path) -> list[list[str]]: ...

# tests/fakes/fake_runner.py: an in-process stand-in for relay.runner.run_agent
class FakeRunner:
    def __init__(self, scenarios: list[Path]): ...      # one scenario per call, in order; the last repeats
    calls: list[dict]                                   # argv, prompt, cwd and retire-flag-seen of each call
    def __call__(self, argv, stdin_text, cwd, run_dir, on_event, retire_flag) -> RunResult: ...
    # feeds each line through stream.feed and on_event, writes <run_dir>/<n>.jsonl, honours "retire" (touches the flag)
    # and "kill" (killed=True, exit_code None); the scenario line `{"fake": "await-flag"}` stands where a shim watched for the flag
```

`tests/conftest.py` gains:
- `loop_cfg`, the `cfg` fixture from `tests/test_loop.py:50`, with the `git init` it runs.
- `fake_run`, which installs a `FakeRunner` on `relay.loop.run_agent` and on `runner.run_command` where a test scripts git or check output.

Most loop tests run on `fake_run` with no child process. The subprocess fake stays for `tests/test_runner.py`, `tests/test_cli.py`, and an end-to-end file of the loop tests that need a real child, such as signals, process groups and stderr.

`tests/test_loop.py` is split by the design's pass steps:
- `tests/test_loop_pass.py`: steps 1 to 5. Stop, budget, pick and wait.
- `tests/test_loop_lead.py`: steps 6 and 7. Resume, retire, kill, ledger, session, handoff and cwd.
- `tests/test_loop_status.py`: step 8 and the recut.
- `tests/test_loop_progress.py`: the progress lines.
- `tests/test_loop_e2e.py`: real-child runs only.

The runtime after the split is unmeasured.

`pyproject.toml`: the dev group adds `ruff`. `[tool.ruff.format] exclude = ["*"]` makes `ruff format` change no file. `ruff check` runs ruff's default rules, which leave line length alone. Whether the tree passes those rules today is unmeasured.

Outside the repository, unsurveyed by this design:
- `~/dev/guild/agents/lead.md` drops `isolation: worktree`. It takes the four prompt contracts above as the lead's own.
- `~/dev/guild/agents/divvyer.md` writes `check: <full suite>` on each lead section header. Each dispatch's `check:` line runs only that step's test files. Each lead section is sized to finish within one lead's `context_limit`.
- `~/.claude/CLAUDE.md` says a queue section's lead is started only by `relay go`, never by the Agent tool. It also says a section already under a `relay go` is not built by a second session.

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Child processes, short-lived ones included | `relay/runner.py` (`run_agent`, `run_command`) | `subprocess` anywhere else; `ping.py` keeps its one `subprocess.run` |
| Reading git | `relay/git.py` | a `git` argv, a `.git` path test, or `_git_top` anywhere else |
| Lead handoff contents and wording | `relay/handoff.py` | putting report, branch, commits or live agents into a prompt anywhere else; `prompts.py` inserts `render`'s text verbatim |
| Section check command | `relay/queue.py` (`Section.check`) and `relay/loop.py` (runs it at DONE) | a full-suite command in config, prompts or a lead's own DONE path |
| Lead contracts: branch, waiting on workers, step checks | `relay/prompts.py`, mirrored in `lead.md` | contract wording in `loop.py` or `cli.py` |
| Loop-test harness | `tests/harness.py`, `tests/conftest.py`, `tests/fakes/` | `_RECORD`, `Background`, `until`, a shim or a fixed `SETTLE` sleep in a test file |
| In-process lead fake | `tests/fakes/fake_runner.py` | a second stand-in for `run_agent` in a test file |
| Lint and format config | `pyproject.toml` | running a formatter that rewrites files; `uvx ruff` |

## Order

1. Stubs. `builder` (`stub` piece) writes `relay/runner.py` (`CommandResult`, `run_command`), `relay/git.py`, `relay/handoff.py` and `relay/queue.py` (`Section.check`), raise-only.
2. Lint pin. `builder` writes `pyproject.toml` and `uv.lock`.
3. Test harness and split. `test-writer` writes these, keeping every existing test's behavior:
   - `tests/harness.py`
   - `tests/fakes/fake_runner.py`
   - `tests/conftest.py`
   - `tests/test_ping.py`
   - `tests/test_loop.py`, removed
   - `tests/test_loop_pass.py`, `tests/test_loop_lead.py`, `tests/test_loop_status.py`, `tests/test_loop_progress.py` and `tests/test_loop_e2e.py`
4. Commands and git: red tests. `test-writer` writes `tests/test_runner.py` and `tests/test_git.py`.
5. Commands and git: build. `builder` writes `relay/runner.py`, `relay/git.py` and `relay/loop.py` (`cwd` from `git.top`; `_git_top` removed).
6. Section check field and handoff: red tests. `test-writer` writes `tests/test_queue.py`, `tests/test_handoff.py` and `tests/fixtures/` (a queue sample with `check:` headers).
7. Section check field and handoff: build. `builder` writes `relay/queue.py` and `relay/handoff.py`.
8. Loop handoff, section check and lead contracts: red tests. `test-writer` writes `tests/test_loop_lead.py`, `tests/test_loop_status.py`, `tests/test_loop_progress.py` and `tests/test_prompts.py`.
9. Loop handoff, section check and lead contracts: build. `builder` writes `relay/loop.py`, `relay/prompts.py` and `relay/progress.py`.
10. Agent files. `general-purpose` writes `~/dev/guild/agents/lead.md` and `~/dev/guild/agents/divvyer.md`.
11. Dispatch rule. `general-purpose` writes `~/.claude/CLAUDE.md`.
