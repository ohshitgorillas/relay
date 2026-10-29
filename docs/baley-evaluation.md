# Baley evaluation against Relay and Gauntlet

Clone: /tmp/baley-eval/baley (commit f7dbdb7f, 2026-10-26). Nothing was built, installed or run from it.

## What Baley is
A single Rust program that runs alongside Claude Code in three ways: an MCP server, a hook that runs before each tool call (the "guard"), and an owner command line. It writes every agent's brief, runs the tests itself, keeps a hash-chained SQLite log, and blocks the next step until proof of the last one is recorded. It has 6 roles at 5 effort levels each, so 30 agent files. Findings from outside model reviews (OpenAI, DeepSeek) go to the owner for a ruling.

## Maturity
- The README says "Not ready to use". It is on build 4 of 9, and most designed rules are marked "Not built".
- The macOS support has never been run. CI is Linux only.
- About 253k lines of Rust, about 3,900 tests, 238 crates. Builds are unsigned. Almost all the work is by one author.
- Its rules clash with Relay: no parallel agents or worktrees, no worker timeout, and every stop waits for the owner.

## Recommendation: borrow ideas, don't install
It isn't usable yet, it's untested on macOS, and it would replace Relay's loop rather than plug into it. It adds process, which is your main complaint. Look again after its first signed release.

## Ideas to borrow, ranked
1. **Relay runs the section's `check:` itself and trusts only the exit code** before marking it DONE (Baley ADR 0014, EXE-R6/R7). This goes in the DONE branch of relay/loop.py: log the result, and mark done only on exit 0. Gauntlet can do the same with `make check`. About half a day.
2. **No deeper recut ids.** Recut children become flat siblings (s4a, s4b), and after 3 failed checks the section parks with a ping (EXE-R10/R13/R14/R19). Changes go in ~/.claude/agents/divvyer.md and in loop.py/state.py. This builds on 8d5e513 and on the unmerged recut-keeps-id branch (6566796). About 2 hours.
3. **Low effort by default, one step up on a retry** (ADR 0046). (Correction: the agent files already set `effort: medium`, on both machines. Only lead.md has none.) Owner ruling, 28 Oct: set levels by role, but test-writer stays on Opus at medium at least, never low, and steps up to high on a retry after a failure. Make the levels differ by role: low or medium for builder, test-writer and mutant-hunter, high for architect, divvyer and the reviewers. Check the ledger to see whether cost per section drops. 1-2 hours.
4. **Check the working copy before a fresh lead** (EXE-R17). Put the output of `git status` and the log since the last recorded commit into the lead's prompt, or park the section if the tree is dirty with no explanation. About 2 hours.
5. **A visible progress view.** `relay status --watch` would show the section, elapsed time, context against the retire threshold, live agents, cost so far and the last check. `relay go` would open it in its own tab or pane. About half a day.
6. **Repeat permission prompts:** the real fix is `permissions.allow` entries in ~/.claude/settings.json for commands already approved. (This is the helper's suggestion. It hasn't been done.) About 30 minutes.

## Don't borrow
The extra owner steps (stories and truths, rulings on every finding, landing gates), the tamper-evident log, and the no-timeout and no-parallel rules.

## Side notes
- ~/dev/relay is on the recut-keeps-id branch, one commit ahead of main.
- Gauntlet has an uncommitted change to CLAUDE.md, and its docs/queue.md and .claude/settings.json aren't tracked.
- Where the idle time comes from: Relay sets the retire flag at 100k context but only kills the lead at 200k, and leads look for the flag only after a commit. All agents and tests are forced into the background and waited on. When only parked sections are left, Relay polls every 30 seconds.
- Suggested fix: kill the lead at about 130k if it hasn't committed since the flag went up.
