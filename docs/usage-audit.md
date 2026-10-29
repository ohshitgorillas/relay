# Claude Code usage audit, 28 Oct 2026

Written from the helper's numbers (its scratch data and scripts are in /tmp/audit). Prices are list prices, priced from the transcripts. The pricing matched the Opal ledger to the cent.

## Where the week's usage went (Sun 25 Oct 04:00 to now)
- Total: about $1,467.
- Relay: $171, about 12%. That's Opal hqptuner2 $93, Mac workboard $40 and Mac gauntlet $38.
- Headless runs outside Relay (foreman, ~/ and gauntlet): about $400.
- The rest: interactive sessions (Void, relay, gauntlet, workboard).

## Plan headroom
- The weekly limit was 68% used at 03:17 on 28 Oct, which works out to about $21.6 per 1%.
- The remaining 32% is about $690, or about $7 an hour until Sun 04:00.
- The Opal Relay run alone burns about $17 an hour.

## The Opal run: $92.3
Productive, about $50-55 (55-60%):
- s1's merges: 4 commits.
- s3's lib/dom.js work: 8 commits, $33.
- The s4 chain: one commit, 12c58803.
- s4.2: 2 commits.

Waste, about $37-42:
- Recuts, about $19: $5.2 on recut runs plus $14 on leads that ended in RECUT. The s4 chain cost $24.4 for one commit. The s2 chain cost $10 with no commits of its own.
- Review and repair loops, about $14: 28 test-writer repairs cost $12.8, and the same repair was sent 3 times in one run. About half of it is loop, not real fixes.
- Leads started on blocked sections, about $7.9.
- Fresh-lead startup and re-reading, about $6-7: every lead starts at about 50k tokens of context.
- Done sections re-woken, $0.87. The fix (c50c456) is on the Mac's main but not on Opal.
- Idle, about $0.10. The final message was already written, but a ScheduleWakeup or a background agent kept `claude -p` alive.

Other findings:
- The architect cost $6 in total, and no logs show a rejected design.
- Effort settings are worth at most $4-6. Cache writes are 51% of spend, output 23%, thinking about $8.5.

## Verdict
Relay is about 55-60% productive, but it's only 12% of the plan. The drain is the headless runs outside Relay.

## What to do
1. Today: pause or cut the non-Relay headless runs (foreman and others). Stop Relay between leads with `touch <statedir>/STOP` when it isn't needed.
2. Update Opal's Relay to the Mac's main (two commits behind, including the re-woken-section fix).
3. baley-ideas (no commits yet): flat recuts with a park after 3 failed checks, and Relay running the check itself, hit the two biggest buckets. Auto-wake and not starting leads on blocked sections (part 6) hits the $7.9 bucket. The researcher (part 5) targets the startup re-reading.
