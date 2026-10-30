# Cache-cost fixtures

`claude-agent-measurements.jsonl` is synthetic protocol evidence for the approved
cache-cost design. Its task-associated `model`, `effort` and `total_cost_usd`
fields exercise normalization; it is not a claim that the installed Claude CLI
emits those fields. The run result remains the authority for aggregate spend.

`snapshot.json` is a synthetic normalized snapshot combining an old agent record
with a measured record and saved, partly unavailable usage. Its unknown model
and saved cost test lossless restoration without current pricing or live data.
