design docs/superpowers/specs/relay-cache-cost-design.md | order docs/superpowers/specs/relay-cache-cost-design.md | main db259df

section s1 | lead | steps: 1, 2, 3, 4, 5 | size: calibration: one shared-core commit piece; retain steps 1-5 together through green gates, no standalone stub or red commit; five fresh worker contexts, below lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  s1.d1 | builder | steps: 1 | writes: relay/pricing.py, relay/config.py, relay/agents.py, relay/stream.py | size: calibration: four additive interface modules, import check only; below builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/cache-cost-queue.md s1.d1
    stub
    design: docs/superpowers/specs/relay-cache-cost-design.md
    step: 1
    paths: relay/pricing.py, relay/config.py, relay/agents.py, relay/stream.py
    done-check: uv run python -c 'import relay.pricing, relay.config, relay.agents, relay.stream'
  s1.d2 | test-writer | steps: 2 | writes: tests/test_pricing.py, tests/test_config.py | size: calibration: pricing and override behavior, two red runs and scoped formatting; below test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/cache-cost-queue.md s1.d2
    red
    design: docs/superpowers/specs/relay-cache-cost-design.md Order 2
    behavior: Prove cache reads and each billed-write duration use their own rates, writes replace uncached charges, mixed categories do not overlap, reasoning is counted once, custom rates work, and incomplete or invalid billing evidence never becomes a false numeric cost. Preserve the approved five-field usage and three-rate construction where writes are known absent.
    view: stubgen .pyi of relay/pricing.py
    behavior: Reject unknown keys and nonfinite, negative, boolean or nonnumeric rates. Missing optional write rates remain unavailable for nonzero billed writes.
    view: stubgen .pyi of relay/config.py
  s1.d3 | builder | steps: 3 | writes: relay/pricing.py, relay/config.py | size: calibration: one formula and config validation with focused check; below builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/cache-cost-queue.md s1.d3
    design: docs/superpowers/specs/relay-cache-cost-design.md
    step: 3
    paths: relay/pricing.py, relay/config.py
    red: s1.d2 report and tests/test_pricing.py, tests/test_config.py
    done-check: uv run python -m pytest tests/test_pricing.py tests/test_config.py
  s1.d4 | test-writer | steps: 4 | writes: tests/test_agents.py, tests/test_backends.py, tests/test_stream.py, tests/fixtures/cache-cost/ | size: calibration: inventory and replay contract, two red runs and scoped formatting; below test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/cache-cost-queue.md s1.d4
    red
    design: docs/superpowers/specs/relay-cache-cost-design.md Order 4
    behavior: Cover missing measurements, known zero, repeated lifecycle events, multiple settings, resumed identity, Claude reported totals, and old/new snapshot replay without live lookups.
    view: stubgen .pyi of relay/agents.py
    behavior: Snapshot replay restores `Usage` and calls `agents.restore_agent` for both inventory and event records. Old snapshots without additions remain readable with unavailable agent measurements. Replay uses saved observations without consulting current live sessions or repricing old costs.
    view: stubgen .pyi of relay/backends/__init__.py
    behavior: Missing Claude model, effort and final cost are displayed as unavailable. Generic's absent subagent telemetry remains explicitly unsupported.
    view: stubgen .pyi of relay/stream.py
  s1.d5 | builder | steps: 5 | writes: relay/agents.py, relay/stream.py, relay/backends/__init__.py | size: calibration: metadata folding and replay consumers complete the stub piece; below builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/cache-cost-queue.md s1.d5
    design: docs/superpowers/specs/relay-cache-cost-design.md
    step: 5
    paths: relay/agents.py, relay/stream.py, relay/backends/__init__.py
    red: s1.d4 report and tests/test_agents.py, tests/test_backends.py, tests/test_stream.py
    done-check: uv run python -m pytest tests/test_pricing.py tests/test_config.py tests/test_agents.py tests/test_backends.py tests/test_stream.py

section s2 | lead | steps: 6, 7 | size: calibration: one telemetry commit piece, interface preparation plus red tests plus integration, after landed s1; retain all three dispatches through green gates, no standalone stub or red commit; below lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  s2.d3 | builder | steps: 7 | writes: relay/backends/codex_session.py, relay/backends/codex.py | size: calibration: two telemetry interface modules, import check only, committed with s2.d1 and s2.d2; below builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/cache-cost-queue.md s2.d3
    resume 01a18a90-e46e-7a63-a8e7-3bde7dc73cb2
    stub
    design: docs/superpowers/specs/relay-cache-cost-design.md
    step: 7
    paths: relay/backends/codex_session.py, relay/backends/codex.py
    done-check: uv run python -c 'import relay.backends.codex_session, relay.backends.codex'
  s2.d1 | test-writer | steps: 6 | writes: tests/test_codex_session.py, tests/test_backends.py, tests/fixtures/cache-cost/ | size: calibration: reader and adapter behavior, two red runs and scoped formatting; below test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/cache-cost-queue.md s2.d1
    red
    design: docs/superpowers/specs/relay-cache-cost-design.md Order 6
    behavior: Prove cached-session pricing from realistic normalized telemetry, repeated cumulative observations without double billing, model transitions, resume boundaries, descendants, absent status records, unavailable write dimensions and incomplete final measurements.
    view: stubgen .pyi of relay/backends/codex_session.py
    behavior: Poll every discovered thread through the same reader registry, including descendants, with one reader per ID and cycle prevention. At finalization force the final available read before enriching agents. A still-running, missing, malformed or incomplete thread retains its inventory row and has final cost unavailable with a reason.
    view: stubgen .pyi of relay/backends/codex.py
  s2.d2 | builder | steps: 7 | writes: relay/backends/codex_session.py, relay/backends/codex.py | size: calibration: one registry and normalization integration using established core, focused check; below builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/cache-cost-queue.md s2.d2
    design: docs/superpowers/specs/relay-cache-cost-design.md
    step: 7
    paths: relay/backends/codex_session.py, relay/backends/codex.py
    red: s2.d1 report and tests/test_codex_session.py, tests/test_backends.py
    done-check: uv run python -m pytest tests/test_codex_session.py tests/test_backends.py

section s3 | lead | steps: 8, 9 | size: calibration: one completed-report commit piece, red plus implementation, after s2; below lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  s3.d1 | test-writer | steps: 8 | writes: tests/test_progress.py, tests/test_ledger.py, tests/test_loop.py, tests/fixtures/cache-cost/ | size: calibration: report, persistence and end-to-end behavior, two red runs and scoped formatting; below test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/cache-cost-queue.md s3.d1
    red
    design: docs/superpowers/specs/relay-cache-cost-design.md Order 8
    behavior: Prove the completed lead report and ledger contain every discovered agent exactly once, including failures, missing telemetry and descendants, with model, effort and final cost or explicit unavailability; prove detail never doubles aggregate spend.
    view: stubgen .pyi of relay/progress.py
    behavior: Agent entries are detail, never additional run spend. Existing aggregate ledger parsing remains unchanged.
    view: stubgen .pyi of relay/ledger.py
    behavior: Output is generated from final normalized state, not by prompting the lead to calculate costs.
    view: stubgen .pyi of relay/loop.py
  s3.d2 | builder | steps: 9 | writes: relay/progress.py, relay/ledger.py, README.md | size: calibration: presentation and persistence on normalized state, documentation and focused check; below builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/cache-cost-queue.md s3.d2
    design: docs/superpowers/specs/relay-cache-cost-design.md
    step: 9
    paths: relay/progress.py, relay/ledger.py, README.md
    red: s3.d1 report and tests/test_progress.py, tests/test_ledger.py, tests/test_loop.py
    done-check: uv run python -m pytest tests/test_progress.py tests/test_ledger.py tests/test_loop.py
