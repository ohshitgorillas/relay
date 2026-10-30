# Codex telemetry evidence

The coordinator supplied these bounded captured observations from
`/Users/atom/.codex/sessions/2026/10/29/rollout-2026-10-29T18-23-19-01a18a67-77a0-7ac1-9444-688f4192a818.jsonl`.
The tests do not open that live session.

- Line 10: envelope `type: turn_context`, with `payload.model: gpt-6.1-sol`
  and `payload.effort: high`. There is no `reasoning_effort` key. Observed
  turn-context keys also include `summary`, `turn_id` and `root_turn_id`.
- Line 22: envelope `type: event_msg`, `payload.type: token_count`.
  `payload.info.total_token_usage` contains `input_tokens: 26683`,
  `cached_input_tokens: 0`, `cache_write_input_tokens: 0`, `output_tokens: 210`,
  `reasoning_output_tokens: 0`, `total_tokens: 26893`. The observed
  `last_token_usage` has the same fields. The record also has
  `last_usage_includes_reasoning: true`.

All generated records in the telemetry tests are synthetic mutations of these
field names and the captured `codex-real/token-count.jsonl` envelope documented
in the approved backend design. They do not establish emitted cache-write
duration buckets or a billing-regime discriminator. Normalized-reader doubles
are synthetic `Usage` observations, not claims about additional wire fields.
