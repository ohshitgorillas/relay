# Relay

Relay is a simple, quick-and-dirty harness for agentic workflows. It runs the agents from its sibling repo, [Guild](https://github.com/ohshitgorillas/guild), in an unattended loop over a build queue, and stops when the queue is done, a budget runs out, or something goes wrong twice.

Relay takes its name from how it keeps context small. A lead that passes 100k tokens of context is retired at its next safe point and a fresh lead takes over the same section, receiving the previous lead's final report and a backend-specific history hint.

## How it works

Relay reads a queue written by Guild's `divvyer`: a Markdown file of sections, each one a piece of work for a `lead`. On each pass, `relay go`:

1. Stops if the stop file exists or the budget is spent.
2. Re-reads the queue, wakes any waiting section whose blocker has landed, and picks the first section that is open and not held up by a parked or waiting section.
3. Parks the section for the owner if its spend is over its dollar cap.
4. Gets the section a map of its code. A `researcher` reads the section's files and returns `path:line` pointers, which Relay keeps under `maps/` and reuses until a mapped file changes in git. If there is no map, the lead runs without one.
5. Starts a `lead` on that section using the selected backend (Claude by default). Its prompt holds the section's text, the map, the previous session's history hint, the previous lead's final report, any answer from the owner, and the output of any check that failed. The lead puts the map in every brief it writes, and when a worker needs more it asks the researcher with `relay ask` rather than searching.
6. Watches the lead's output and available telemetry as it runs. At `context_limit` (100k tokens by default), when the budget runs out, or when the section goes over its cap, it asks the lead to retire. At `hard_ceiling` (twice the limit by default) it kills it. A lead past `idle_ceiling` that has committed nothing since it was asked to retire is also killed, and that counts as a retire. Context comparisons apply only to backends that report context, and dollar caps apply only to backends that report dollars.
7. Records the run's spend, then acts on the lead's final status line:

| Status | What Relay does |
|---|---|
| `DONE` | Runs the section's checks (see [Checks](#checks)). If they pass, or there are none, it marks the section done and moves on. |
| `RETIRED` | Starts a fresh lead on the same section, resuming from this one. Not a failure. |
| `RECUT: <problem>` | Climbs the [ladder](#the-ladder): the first time, the `divvyer` re-cuts the section. |
| `DESIGN: <problem>` | Climbs the ladder straight to a design change: the section's design is missing something a recut can't fix. |
| `WAITING: <id>` | Holds the section until section `<id>` lands, with no ping. If that can never happen (the id is unknown, already landed, the section itself, or part of a cycle), it parks the section instead. |
| `NEEDS-OWNER: <question>` | Parks the section and pings the owner with the question. Sections that depend on it wait; others keep running. |
| anything else | Counts as a failure: a missing status line, a non-zero exit, or a kill. A section's second failure stops the run. |

A `RECUT:` or `DESIGN:` problem may end in ` | guess: <cause>`. Relay passes on only the problem.

A blocker has landed when it is done and its worktree (the one on branch `lead/<id>`, if there is one) has nothing uncommitted. If the blocker was recut out of the queue, it has landed once every section cut from it has.

When only parked and waiting sections are left, Relay waits, checking every `poll_seconds` for an answer, a blocker landing, or the stop file. Every stop sends the owner a ping saying why.

### Checks

A section's body can carry check lines, `check: <command>` (or `done-check: <command>`). After a lead says `DONE`, Relay runs them in order in the section's worktree (or the repository top if it has none) and stops at the first that fails, with a time limit of `check_timeout` on each:

- Every check passes: the section is done.
- A check fails: the section stays open, and the next lead gets the failing command and the end of its output. After the third failed check, the section is parked.
- The failure looks like it comes from outside the work (exit 126 or 127, or output matching a `check_outside` pattern such as a missing command or a network error): the section is parked, and the check runs again once the owner answers.

### The ladder

`RECUT` and `DESIGN` move a section up three rungs:

1. **Recut.** The first `RECUT` runs the `divvyer`, which rewrites the section in place or splits it into new sections. A recut that changes nothing, or fails, counts as a failure.
2. **Design change.** A second `RECUT` on a section that came out of a recut, or any `DESIGN`, runs the `architect` on the design named on the queue's `design` line, then has the divvyer re-cut the section from the amended design. If the architect needs a product choice, the section is parked with its decisions. The owner's `relay answer` goes back to the architect, and the climb carries on from there.
3. **Owner.** A section that has already had its design change, or a queue with no `design` line, parks the section for the owner.

Relay never commits or cleans the work tree. Leads and the divvyer own queue authorship; Relay's sole queue-write exception is restoring the exact pre-invocation bytes and permission mode after a failed recut. Leads and the divvyer run from the git top level of the queue's directory and keep git and the queue as the record of what is finished.

A recut must finish without a kill, non-zero exit or backend error and produce a parseable, changed queue. Failed invocations, malformed, empty or missing output, and unchanged sections restore the original queue and count as failures; a second failure stops the run. Invocation exceptions restore the original before propagating. If restoration itself fails, Relay stops rather than continuing with failed queue edits. Backend finalization errors, including missing required Codex telemetry, also fail lead and recut invocations even when the child exits successfully.

## Requirements

- Python 3.12 or later. Relay uses only the standard library.
- The CLI for your backend: `claude`, `codex`, or an explicit generic command, with the roles and workers your queue needs.
- For Claude, Guild's agents (at least `lead`, `divvyer`, `researcher` (with its `reader`) and `architect`) and [Terminus](https://github.com/jcrenshaw-dev/terminus) for recalling prior sessions.
- For Codex, generated `lead.toml`, `divvyer.toml`, `researcher.toml` and `architect.toml` role files under `$CODEX_HOME/agents` (default `~/.codex/agents`) and readable rollout files under that same Codex home's `sessions` directory. Missing or invalid role files fail before launch.
- Something to receive pings. By default Relay runs `~/.local/bin/claude-ping relay "<message>"`; point `ping_command` at your own notifier if you don't have that script.

## Install

```sh
uv tool install .
```

Or, to work on Relay itself:

```sh
uv sync
uv run relay --help
```

## Usage

```sh
relay go <queue.md> [--backend claude|codex|generic] [--token-budget N] [--dollar-budget D] [--context-limit N]
                    [--idle-ceiling N] [--section-dollar-cap D]
relay status <queue.md>
relay answer <queue.md> <section-id> "<text>"
relay ask [--backend claude|codex|generic] <queue.md> <section-id> "<question>"
relay stop <queue.md>
```

- **`go`** runs the loop until it stops. Progress lines go to stdout, one per event: research, leads and subagents starting and finishing, checks, retires, kills, recuts, design changes, waits and failures. Only one `relay go` can hold a queue at a time. Supported budgets count only the spend of this run; with no budget set, there is no limit.
- **`status`** prints each section's state (`open`, `done`, `parked`, or `waiting on <id>`) with a summary of the subagents its leads spawned, then the spend over the last 7 days and in total.
- **`answer`** gives a parked section the owner's answer and reopens it. The next lead on that section gets the answer in its prompt, or, if the section was parked on a design decision, the architect does. An answer to a section that is already done is dropped, with a note.
- **`ask`** puts a question to the section's researcher by resuming its session, and prints only the answer. Leads run it when a worker reports that it needs more than the map gives. It fails if the section has no researcher yet.
- **`stop`** creates the stop file. A running `relay go` stops at its next check, after the current lead finishes.

Ctrl-C (or SIGTERM) kills the running agent's whole process group before Relay exits.

### Backends and telemetry

Choose a backend with `--backend` or the `backend` config key. Unknown names are errors; omitting the choice keeps the existing Claude behavior. Research, researcher follow-ups and architect runs use the same selected backend; Codex follow-ups use native resume on the saved researcher thread.

Use the researcher's backend when running `relay ask`; a backend mismatch is an error. Generic researchers cannot be resumed for follow-up questions.

| Backend | Commands and observations |
|---|---|
| `claude` | Uses `claude -p` with stream-json output. Reports context, tokens, dollars and subagent activity. Supports token and dollar budgets. |
| `codex` | Uses `codex exec --json` with generated role instructions, model, reasoning effort and feature settings. Reports tokens and context, and collaboration receiver activity when emitted. Supports token budgets; ignores dollar budgets, including historical dollar spend. |
| `generic` | Requires an explicit `lead_command`; sends the prompt on stdin and treats plain stdout as the final report. Reports no context, tokens, dollars or subagents, so both budgets and context limits are ignored. Unless set explicitly, research, design and recut commands use the same command. |

Codex context comes from the matching rollout's latest `last_token_usage.total_tokens`; cumulative `total_token_usage.total_tokens` supplies spend. Cumulative tokens are never used as current context, which may fall after compaction. Relay polls the rollout even while stdout is quiet. Missing telemetry at finalization is an explicit error. Codex supplies no dollar costs or per-agent context and duration telemetry here; collaboration activity does not imply those measurements are available. A completed collaboration tool call alone does not mean its receiver agents have finished.

Codex rotation starts a fresh thread with the previous report as its handoff. The history hint identifies the old thread and the native continuation command, `codex exec resume <id>`, for accessing its history. Relay does not use that command to rotate into the full context it just retired, and it does not send Codex thread IDs to Terminus. For further recall the hint points the Codex lead at deja (`~/.codex/skills/deja/scripts/recall-session <id>`).

The following trial command targets the Gauntlet queue using this Relay worktree. It is documented only and has **not been executed** as part of validation:

```sh
uv run --project /Users/atom/dev/relay-wt/backends relay go ~/dev/gauntlet/docs/queue.md --backend codex
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | The queue is empty: every section is done. |
| 1 | Error. |
| 2 | Bad arguments, bad config, a queue that doesn't parse, or the queue is locked by another `relay go`. |
| 3 | A budget ran out. |
| 4 | Stopped by the stop file. |
| 5 | A section failed twice. |
| 130 | Interrupted by Ctrl-C or SIGTERM. |

## The queue

A section starts at a column-0 header line and runs to the next one:

```
design docs/superpowers/specs/widget-design.md

section s2 | lead | steps: 2 | depends: s1 | cap: $15
  ...the section's text, passed to the lead verbatim...
  check: uv run pytest tests/test_widget.py
```

Header lines inside code fences are ignored. The header's fields:

- `depends: <id>, <id>` (also `depends on:`, `depends_on:`, `depends-on:`) lists sections this one waits on, and each must exist in the same queue.
- `cap: <dollars>` caps what the section may spend, overriding `section_dollar_cap`.
- `from: <id>` names the section a recut made this one from.
- `done` (or `status: done`) marks the section finished.

Every other field is kept as the section's title. In the body, each `check: <command>` line outside a code fence is a [check](#checks).

An optional first line, `design <path>`, names the design the queue was cut from, relative to the repository top. The ladder's design change needs it.

## Config

Relay reads `~/.config/relay/config.toml` if it exists. The `go` flags override the file. Every key is optional except `lead_command` when using the generic backend:

```toml
backend = "claude"            # claude (default), codex or generic; --backend overrides it
token_budget = 5_000_000      # tokens per `relay go`; unset = no limit
dollar_budget = 50.0          # dollars per `relay go`; unset = no limit
context_limit = 100_000       # lead context at which Relay asks it to retire
hard_ceiling = 200_000        # lead context at which Relay kills it; default 2 × context_limit
poll_seconds = 30             # wait between checks while sections are parked
lead_command = ["claude", "-p", "--output-format", "stream-json", "--verbose",
                "--permission-mode", "bypassPermissions"]
idle_ceiling = 130_000        # past this, a retiring lead that has committed nothing is killed;
                              # default 13/10 of context_limit, kept below hard_ceiling
section_dollar_cap = 20.0     # dollars any one section may spend; unset = no cap
check_timeout = 1800          # seconds each check may run
check_outside = ["command not found", "(?i)credit balance", ...]
                              # regexes marking a failed check's output as outside the work
map_max_lines = 150           # caps on a researcher's map
map_max_chars = 12_000
recut_command = [...]         # default: lead_command + ["--agent", "divvyer"]
research_command = [...]      # default: lead_command + ["--agent", "researcher", "--model", "opus[1m]"]
design_command = [...]        # default: lead_command + ["--agent", "architect"]
design_approval = "..."       # the owner's standing approval, which the architect quotes on its approve: line
ping_command = ["/path/to/notifier", "{message}"]   # "{message}" is replaced by the ping text
state_root = "~/.local/state/relay"
```

The recut, research and design command defaults above are Claude's; other backends inherit the lead command without Claude flags. The command defaults depend on the backend: the example above is Claude's default; Codex defaults to `["codex"]`, to which its adapter adds the exec flags and role configuration. Generic has no default lead command. Set command overrides for the backend you select: changing `backend` does not discard explicit commands from your config.

For example, a generic command configuration is:

```toml
backend = "generic"
lead_command = ["/path/to/agent"]
```

The default Claude command runs with `bypassPermissions`; Codex uses `--dangerously-bypass-approvals-and-sandbox`. Leads and their workers act without asking. Run Relay only on queues and repositories you're happy to leave in agents' hands.

## State on disk

Relay keeps its own record of each queue under `state_root`, in a directory named after the queue's path plus a short hash of it:

| Path | What it holds |
|---|---|
| `state.json` | Each section's status, failure and check-failure counts, parked question, answer, last session and last report, what it waits on, its researcher session, and where it stands on the ladder. |
| `ledger.jsonl` | One line per finished run (lead, research, ask, recut or design) and per check: time, section, session, tokens and dollars. |
| `maps/<id>.map` | Each section's research map. |
| `runs/<n>.jsonl` | Each run's stdout, verbatim: Claude stream-json, Codex JSON events or generic plain text. |
| `runs/<n>.backend.json` | The backend used for the run. Older logs without this metadata are treated as Claude. |
| `runs/<n>.telemetry.json` | Saved normalized observations for historical replay without live Codex rollout files. |
| `runs/<n>.final.txt` | The final-message output file used by Codex; authoritative when present. |
| `runs/<n>.stderr`, `runs/<n>.pid` | Each run's stderr and PID. |
| `runs/<n>.check` | The output of the checks run after that lead's `DONE`. |
| `runs/retire`, `runs/research-<id>` | The flags a lead and a researcher check at each safe point; Relay creates them to ask for a retire. |
| `STOP` | The stop file. |
| `lock`, `write.lock`, `research-<id>.lock` | Held by the running `relay go`, around each state write, and while a section's map is drawn or asked. |

To start a queue over from scratch, delete its directory under `state_root`.

## Development

```sh
uv run pytest
```

The tests use fake commands and saved fixtures, so the test run spends no model tokens and does not run the Gauntlet queue. Claude loop tests use `tests/fakes/fake_claude.py` to replay scripted stream-json. Codex fixture provenance and the distinction between captured and synthetic events are documented in `docs/superpowers/specs/relay-backends-design.md`. The original loop design lives in `docs/superpowers/specs/relay-loop-design.md`; the check, research and ladder designs add those features, and the backend design extends it with adapter selection, telemetry and replay while keeping processes in `runner.py`.
