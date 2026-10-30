# Cache-cost fixtures

`claude-agent-measurements.jsonl` is synthetic protocol evidence for the approved
cache-cost design. Its task-associated `model`, `effort` and `total_cost_usd`
fields exercise normalization; it is not a claim that the installed Claude CLI
emits those fields. The run result remains the authority for aggregate spend.

`snapshot.json` is a synthetic normalized snapshot combining an old agent record
with a measured record and saved, partly unavailable usage. Its unknown model
and saved cost test lossless restoration without current pricing or live data.

`completed-report.json` is a synthetic normalized final snapshot, not captured
CLI evidence. Its cached worker and discoverable descendant each use 1,000
inclusive input tokens, 800 cached reads and 100 output tokens, with known zero
writes in the standard billing regime. The approved Sol and Terra rates give
$0.00148 and $0.00074, rather than full-input prices of $0.003 and $0.0015.
The inventory also includes a receiver with missing rollout and a reported
zero-cost worker. The aggregate $0.00222 already includes both measured workers;
their detail charges must never be added again.
