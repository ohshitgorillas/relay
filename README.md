# Relay

Relay is a simple, quick-and-dirty harness for agentic workflows. It runs the agents from its sibling repo, [Guild](https://github.com/ohshitgorillas/guild), in an unattended loop over a build queue, and stops when the queue is done, a budget runs out, or something goes wrong twice.

Relay takes its name from how it keeps context small. A lead that passes 100k tokens of context is retired at its next safe point and a fresh lead takes over the same section, picking up where the last one left off through [Terminus](https://github.com/jcrenshaw-dev/terminus).

## How it works

Relay reads a queue written by Guild's `divvyer`: a Markdown file of sections, each one a piece of work for a `lead`. On each pass, `relay go`:

1. Stops if the stop file exists or the budget is spent.
2. Re-reads the queue and picks the first section that is open, not parked, and not waiting on a parked section.
3. Starts a `lead` on that section with `claude -p`, piping in a prompt that holds the section's text, the previous session to resume, the previous lead's final report, and any answer from the owner.
4. Watches the lead's stream-json output as it runs. At `context_limit` (100k tokens by default) or when the budget runs out, it asks the lead to retire; at `hard_ceiling` (twice the limit by default) it kills it.
5. Records the run's spend, then acts on the lead's final status line:

| Status | What Relay does |
|---|---|
| `DONE` | Marks the section done and moves on. |
| `RETIRED` | Starts a fresh lead on the same section, resuming from this one. Not a failure. |
| `RECUT: <reason>` | Runs the `divvyer` to re-cut the section, then re-reads the queue. A section that came out of a recut and asks for a second one is parked for the owner instead. |
| `NEEDS-OWNER: <question>` | Parks the section and pings the owner with the question. Sections that depend on it wait; others keep running. |
| anything else | Counts as a failure: a missing status line, a non-zero exit, or a kill. A section's second failure stops the run. |

When only parked sections are left, Relay waits, checking every `poll_seconds` for an answer or the stop file. Every stop sends the owner a ping saying why.

Relay never commits, never cleans the work tree, and never edits the queue. Leads and the divvyer run from the git top level of the queue's directory and keep git and the queue as the record of what is finished.

## Requirements

- Python 3.12 or later. Relay uses only the standard library.
- The `claude` CLI, with Guild's agents installed: at least `lead` and `divvyer`, plus whatever workers your leads dispatch.
- Terminus, so a fresh lead can recall the session it resumes.
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
relay go <queue.md> [--token-budget N] [--dollar-budget D] [--context-limit N]
relay status <queue.md>
relay answer <queue.md> <section-id> "<text>"
relay stop <queue.md>
```

- **`go`** runs the loop until it stops. Progress lines go to stdout, one per event: leads starting and finishing, subagents starting and finishing, retires, kills, recuts and failures. Only one `relay go` can hold a queue at a time. Budgets count only the spend of this run; with no budget set, there is no limit.
- **`status`** prints each section's state (`open`, `done` or `parked`) with a summary of the subagents its leads spawned, then the spend over the last 7 days and in total.
- **`answer`** gives a parked section the owner's answer and reopens it. The next lead on that section gets the answer in its prompt. An answer to a section that is already done is dropped, with a note.
- **`stop`** creates the stop file. A running `relay go` stops at its next check, after the current lead finishes.

Ctrl-C (or SIGTERM) kills the running agent's whole process group before Relay exits.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | The queue is empty: every section is done. |
| 1 | Error. |
| 2 | Bad arguments, bad config, a queue that doesn't parse, or the queue is locked by another `relay go`. |
| 3 | A budget ran out. |
| 4 | Stopped by the stop file. |
| 5 | A section failed twice. |

## The queue

A section starts at a column-0 header line and runs to the next one:

```
section s1.2 | lead | steps: 2 | depends: s1.1
  ...the section's text, passed to the lead verbatim...
```

Header lines inside code fences are ignored. `depends: <id>, <id>` (also `depends on:`, `depends_on:`, `depends-on:`) lists sections this one waits on, and each must exist in the same queue. A `done` field marks the section finished. Every other field is kept as the section's title.

## Config

Relay reads `~/.config/relay/config.toml` if it exists. The `go` flags override the file. Every key is optional:

```toml
token_budget = 5_000_000      # tokens per `relay go`; unset = no limit
dollar_budget = 50.0          # dollars per `relay go`; unset = no limit
context_limit = 100_000       # lead context at which Relay asks it to retire
hard_ceiling = 200_000        # lead context at which Relay kills it; default 2 × context_limit
poll_seconds = 30             # wait between checks while sections are parked
lead_command = ["claude", "-p", "--output-format", "stream-json", "--verbose",
                "--permission-mode", "bypassPermissions"]
recut_command = [...]         # default: lead_command + ["--agent", "divvyer"]
ping_command = ["/path/to/notifier", "{message}"]   # "{message}" is replaced by the ping text
state_root = "~/.local/state/relay"
```

The default `lead_command` runs with `bypassPermissions`, so leads and their workers act without asking. Run Relay only on queues and repositories you're happy to leave in agents' hands.

## State on disk

Relay keeps its own record of each queue under `state_root`, in a directory named after the queue's path plus a short hash of it:

| Path | What it holds |
|---|---|
| `state.json` | Each section's status, failure count, parked question, answer, last session and last report. |
| `ledger.jsonl` | One line per finished lead or recut run: time, section, session, tokens and dollars. |
| `runs/<n>.jsonl` | Each run's stream-json output, verbatim. |
| `runs/<n>.stderr`, `runs/<n>.pid` | Each run's stderr and PID. |
| `runs/retire` | The flag a lead checks at each safe point; Relay creates it to ask for a retire. |
| `STOP` | The stop file. |
| `lock`, `write.lock` | Held by the running `relay go`, and around each state write. |

To start a queue over from scratch, delete its directory under `state_root`.

## Development

```sh
uv run pytest
```

The tests drive the loop with `tests/fakes/fake_claude.py`, a stand-in for `claude` that replays scripted stream-json, so they spend no tokens. The design lives in `docs/superpowers/specs/relay-loop-design.md`, and it names the one module that owns each shared concern: processes in `runner.py`, the stream-json schema in `stream.py`, the queue format in `queue.py`, and so on.
