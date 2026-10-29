# Real Codex capture

These three files preserve the real capture documented in
`docs/superpowers/specs/relay-backends-design.md`, Modules:

- `stdout.jsonl`: JSON stdout, including the hook-timeout clamp error item.
- `final.txt`: the final-message output file.
- `token-count.jsonl`: the matching rollout token-count excerpt.

Command:

```text
codex exec --json --dangerously-bypass-approvals-and-sandbox -C /Users/atom/dev/relay-wt/backends -o .codex-capture/final.txt -
```

Stdin was `Reply with exactly RELAY_CODEX_FIXTURE_OK. Do not use tools, inspect files, or change anything.`
Thread identity: `01a1855b-7ba6-79d3-bf98-98c251634b5a`.

The capture has equal last and cumulative usage and no collaboration events.
Collaboration events, role files, session metadata and mutated usage in the
tests are synthetic cases grounded in the design's cited Codex v0.165.0 wire
schema. They are not additional captured output.
