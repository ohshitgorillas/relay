design docs/superpowers/specs/relay-codex-native-revision-design.md | order docs/superpowers/specs/relay-codex-native-revision-design.md | main db259df
section s1 | lead | steps: 1, 2 | size: lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  s1.d1 | builder | steps: 1 | writes: docs/codex-native-report.md | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s1.d1
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 1
    paths: docs/codex-native-report.md
    - **Translated hooks.** Each one's event, matcher, the Claude hook it invokes, and what it enforces. Each gets its outcome under `relay/codex_launch.py`: sandbox, writable roots, network, native rule, or dropped.
    - **CLI surface.** `codex --version`, `codex exec --help`, and the installed config schema's keys for:
    - sandbox, approval and `sandbox_workspace_write`;
    - native agent-role delivery;
    - features, including the JavaScript exec-cell feature;
    - exec-policy rules;
    - every hook layer the CLI loads (user home, project `.codex/` in cwd and ancestors, any system or managed layer) and the args that exclude each one.
    - **Rates.** Rates and read date from the pricing page for every model in the shakedown roles and the owner's `~/.codex/agents`.
    The step ends with `DESIGN:` in any of these cases:
    - an owner-rule hook has no native form;
    - the CLI has no native agent-role delivery;
    check: grep -n 'Grounding' docs/codex-native-report.md
  s1.d2 | builder | steps: 1 | writes: docs/codex-native-report.md | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s1.d2
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 1
    paths: docs/codex-native-report.md
    - **Exclusion proof.** In a scratch under `$TMPDIR`: a probe hook in a scratch repository's `.codex/` and its parent, and a run with the candidate args that leaves no marker. Then a run in the owner's home with the same args that shows no hook item in stdout or rollout and no adapter process. These runs are model-priced and their spend is unmeasured until run; the step discloses this before running them. This proof gives `PROVEN`'s first entry.
    - **Rollout fields.** The turn-context model field, the usage fields, the `session_meta` parent-thread field, and whether `total_token_usage` resets on `exec resume`.
    The step ends with `DESIGN:` in any of these cases:
    - some hook layer cannot be excluded on the installed CLI;
    - the CLI has no nested-thread parent field.
    check: grep -n 'Exclusion proof' docs/codex-native-report.md
  s1.d3 | test-writer | steps: 2 | writes: tests/test_backends.py, tests/test_config.py, tests/test_runner.py | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s1.d3
    port
    design: docs/superpowers/specs/relay-codex-native-revision-design.md step 2
    files: tests/test_backends.py, tests/test_config.py, tests/test_runner.py
    view: stubgen .pyi of relay/backends/claude.py
    view: stubgen .pyi of relay/backends/__init__.py
    view: stubgen .pyi of relay/config.py
    view: stubgen .pyi of relay/runner.py
  s1.d4 | test-writer | steps: 2 | writes: tests/test_loop.py, tests/test_ledger.py | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s1.d4
    port
    design: docs/superpowers/specs/relay-codex-native-revision-design.md step 2
    files: tests/test_loop.py, tests/test_ledger.py
    view: stubgen .pyi of relay/loop.py
    view: stubgen .pyi of relay/ledger.py
    view: stubgen .pyi of relay/stream.py
    view: stubgen .pyi of relay/backends/claude.py
section s2 | lead | steps: 3 | size: lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  s2.d1 | lead | steps: 3 | writes: the paths docs/research-reuse-queue.md s1 names | size: lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s2.d1
    queue docs/research-reuse-queue.md s1
  s2.d2 | lead | steps: 3 | writes: the paths docs/research-reuse-queue.md s2 names | size: lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s2.d2
    queue docs/research-reuse-queue.md s2
  s2.d3 | lead | steps: 3 | writes: the paths docs/research-reuse-queue.md s3 names | size: lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s2.d3
    queue docs/research-reuse-queue.md s3
section s3 | lead | steps: 4, 5, 6, 7, 8 | size: lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  s3.d1 | builder | steps: 4 | writes: relay/pricing.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s3.d1
    stub
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 4
    paths: relay/pricing.py
    check: uv run python -c 'import relay.pricing'
  s3.d2 | test-writer | steps: 5 | writes: tests/test_pricing.py, tests/test_config.py | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s3.d2
    red
    design: docs/superpowers/specs/relay-codex-native-revision-design.md step 5
    behavior: cfg.prices[model], else RATES[model]; Unpriced otherwise. Never a default.
    view: stubgen .pyi of relay/pricing.py
    behavior: Sum of (input - cached_input) * input + cached_input * cached_input + output * output, over 1e6.
    view: stubgen .pyi of relay/pricing.py
    behavior: `Config` gains `prices: dict[str, Rate]` from the config file's `[prices."<model>"]` tables. Each value must be finite and non-negative.
    view: stubgen .pyi of relay/config.py
  s3.d3 | builder | steps: 6 | writes: relay/pricing.py, relay/config.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s3.d3
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 6
    paths: relay/pricing.py, relay/config.py
    check: uv run pytest tests/test_pricing.py tests/test_config.py
  s3.d4 | builder | steps: 4 | writes: relay/codex_launch.py, relay/roles.py, relay/backends/base.py, relay/stream.py, relay/backends/__init__.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s3.d4
    stub
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 4
    paths: relay/codex_launch.py, relay/roles.py, relay/backends/base.py, relay/stream.py, relay/backends/__init__.py
    check: uv run python -c 'import relay.codex_launch, relay.roles, relay.backends.base, relay.stream, relay.backends'
  s3.d5 | builder | steps: 8 | writes: relay/backends/claude.py, relay/backends/codex.py, relay/backends/generic.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s3.d5
    stub
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 8
    paths: relay/backends/claude.py, relay/backends/codex.py, relay/backends/generic.py
    def env(self, inv: Invocation, cfg: Config) -> dict[str, str]: ...   # added to the inherited environment
    def preflight(self, cfg: Config) -> None: ...
    check: uv run python -c 'import relay.backends.claude, relay.backends.codex, relay.backends.generic'
  s3.d6 | test-writer | steps: 7 | writes: tests/test_codex_launch.py, tests/test_roles.py, tests/fixtures/codex-native/ | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s3.d6
    red
    design: docs/superpowers/specs/relay-codex-native-revision-design.md step 7
    behavior: Builds the configuration every Relay Codex process starts with. It excludes every hook layer, carries the native enforcement settings, and refuses to launch on a CLI version where the exclusion has not been proven.
    view: stubgen .pyi of relay/codex_launch.py
    behavior: added to the inherited environment; never CODEX_HOME
    view: stubgen .pyi of relay/codex_launch.py
    behavior: - **Write and path guards** become `Role.sandbox` and `Role.writable_roots`. Writable roots are the run's cwd and the git common dir of the cwd. `~/.claude`, `~/.codex` and every other path stay read-only.
    view: stubgen .pyi of relay/codex_launch.py
    behavior: - **Remote and push guards** become `network = false`. This is the default for every role. `read-only` roles have no network.
    view: stubgen .pyi of relay/roles.py
    behavior: cfg.roles_dir, else $CODEX_HOME/agents, else ~/.codex/agents.
    view: stubgen .pyi of relay/roles.py
    behavior: The Relay role for a run kind. ConfigError when the file is missing or unreadable, a key has
    view: stubgen .pyi of relay/roles.py
    behavior: the wrong type, model is absent, sandbox is not in SANDBOXES, approval_policy is set to anything
    view: stubgen .pyi of relay/roles.py
    behavior: but "never", or a writable root lies under ~/.claude or ~/.codex.
    view: stubgen .pyi of relay/roles.py
    behavior: Every *.toml in roles_dir whose stem is not a RELAY_ROLES value, sorted by name, validated as load
    view: stubgen .pyi of relay/roles.py
    behavior: `danger-full-access` is refused.
    view: stubgen .pyi of relay/roles.py
  s3.d7 | test-writer | steps: 7 | writes: tests/test_backends.py, tests/test_runner.py | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s3.d7
    red
    design: docs/superpowers/specs/relay-codex-native-revision-design.md step 7
    behavior: It never passes `--dangerously-bypass-approvals-and-sandbox`.
    view: stubgen .pyi of relay/backends/codex.py
    behavior: - **`env`** returns `Launch.env`.
    view: stubgen .pyi of relay/backends/codex.py
    behavior: - **`preflight`** runs `codex_launch.check`, loads every Relay role and helper, and prices every model with `pricing.rate`.
    view: stubgen .pyi of relay/backends/codex.py
    behavior: For Claude, `argv` returns what it returns today for the same role
    view: stubgen .pyi of relay/backends/claude.py
    behavior: `relay/backends/__init__.py` gains `capabilities(name) -> Capabilities`, replacing the four copies.
    view: stubgen .pyi of relay/backends/__init__.py
    behavior: With an empty `env` the child's environment is exactly today's.
    view: stubgen .pyi of relay/runner.py
  s3.d8 | builder | steps: 8 | writes: relay/roles.py, relay/config.py, relay/codex_launch.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s3.d8
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 8
    paths: relay/roles.py, relay/config.py, relay/codex_launch.py
    check: uv run pytest tests/test_roles.py tests/test_codex_launch.py tests/test_config.py
  s3.d9 | builder | steps: 8 | writes: relay/backends/__init__.py, relay/loop.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s3.d9
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 8
    paths: relay/backends/__init__.py, relay/loop.py
    `relay/backends/__init__.py` gains `capabilities(name) -> Capabilities`, replacing the four copies.
    check: uv run pytest tests/test_loop.py
  s3.d10 | builder | steps: 8 | writes: relay/backends/base.py, relay/backends/claude.py, relay/backends/generic.py, relay/backends/codex.py, relay/runner.py, relay/loop.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s3.d10
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 8
    paths: relay/backends/base.py, relay/backends/claude.py, relay/backends/generic.py, relay/backends/codex.py, relay/runner.py, relay/loop.py
    - **`argv`** returns `codex_launch.launch(...).argv_prefix` plus `--json -C <cwd> -o <output> -`, or the resume form for an ask. It never passes `--dangerously-bypass-approvals-and-sandbox`.
    - **`env`** returns `Launch.env`.
    `relay/backends/__init__.py` gains `capabilities(name) -> Capabilities`, replacing the four copies. For Claude, `argv` returns what it returns today for the same role, `env` is `{}` and `preflight` is a no-op. Generic works the same way. `run_agent` (`relay/runner.py:213-234`) takes `inv: Invocation` and passes `{**os.environ, **backend.env(inv, cfg)}` to `Popen`. With an empty `env` the child's environment is exactly today's. `loop.ask` passes `resume=session` and stops rewriting `research_command`.
    check: uv run pytest tests/test_backends.py tests/test_runner.py tests/test_loop.py
  s3.d11 | builder | steps: 8 | writes: relay/cli.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s3.d11
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 8
    paths: relay/cli.py
    - **`preflight`** runs `codex_launch.check`, loads every Relay role and helper, and prices every model with `pricing.rate`. A `ConfigError` or `Unpriced` stops `relay go` and `relay ask` with exit 2 before any run.
    check: uv run pytest tests/test_backends.py tests/test_runner.py tests/test_codex_launch.py tests/test_roles.py
section s4 | lead | steps: 9, 10 | size: lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  s4.d1 | builder | steps: 10 | writes: relay/backends/codex_session.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s4.d1
    stub
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 10
    paths: relay/backends/codex_session.py
    check: uv run python -c 'import relay.backends.codex_session'
  s4.d2 | test-writer | steps: 9 | writes: tests/test_codex_session.py, tests/test_backends.py, tests/fixtures/codex-native/ | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s4.d2
    red
    design: docs/superpowers/specs/relay-codex-native-revision-design.md step 9
    behavior: Covers nested helpers, receivers also found by parent field, resume baselines and model splits.
    view: stubgen .pyi of relay/backends/codex_session.py
    behavior: For a thread that existed before the run (a resume), the baseline is the last `total_token_usage` before the boundary.
    view: stubgen .pyi of relay/backends/codex_session.py
    behavior: - **No double counting.** A thread is keyed by id. A thread reached both as a receiver and through `session_meta` is counted once. A thread's total is its latest cumulative value, never a sum of increments.
    view: stubgen .pyi of relay/backends/codex_session.py
    behavior: - **Models.** Turn-context records give each thread's model per turn. Usage is split per model where the rollout records the change.
    view: stubgen .pyi of relay/backends/codex_session.py
    behavior: - **`poll`** feeds receivers from `collab_tool_call` items into a `ThreadTree` rooted at the run's thread.
    view: stubgen .pyi of relay/backends/codex.py
    behavior: - `spend.tokens` is the sum over the tree. `spend.dollars` is `pricing.dollars` over the tree's usage.
    view: stubgen .pyi of relay/backends/codex.py
    behavior: - `usage` holds the tree's entries. `context_tokens` comes from the run's own thread only.
    view: stubgen .pyi of relay/backends/codex.py
    behavior: - An unpriced model sets `fault`.
    view: stubgen .pyi of relay/backends/codex.py
    behavior: It also marks the run an error when `unobserved()` is non-empty.
    view: stubgen .pyi of relay/backends/codex.py
  s4.d3 | builder | steps: 10 | writes: relay/backends/codex_session.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s4.d3
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 10
    paths: relay/backends/codex_session.py
    check: uv run pytest tests/test_codex_session.py
  s4.d4 | builder | steps: 10 | writes: relay/backends/codex.py, relay/stream.py, relay/backends/__init__.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s4.d4
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 10
    paths: relay/backends/codex.py, relay/stream.py, relay/backends/__init__.py
    check: uv run pytest tests/test_backends.py tests/test_codex_session.py
section s5 | lead | steps: 11, 12 | size: lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  s5.d1 | builder | steps: 12 | writes: relay/ledger.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s5.d1
    stub
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 12
    paths: relay/ledger.py
    `totals_by_basis(since)` serves `relay status`.
    check: uv run python -c 'import relay.ledger'
  s5.d2 | test-writer | steps: 11 | writes: tests/test_ledger.py, tests/test_loop.py, tests/test_cli.py | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s5.d2
    red
    design: docs/superpowers/specs/relay-codex-native-revision-design.md step 11
    behavior: `append` gains `basis` and `usage`.
    view: stubgen .pyi of relay/ledger.py
    behavior: `totals_by_basis(since)` serves `relay status`.
    view: stubgen .pyi of relay/ledger.py
    behavior: `over` takes capabilities from `backends.capabilities`.
    view: stubgen .pyi of relay/ledger.py
    behavior: 1. A budget or section-cap hit asks for a retire, as today.
    view: stubgen .pyi of relay/loop.py
    behavior: Spend past the limit by more than `cfg.budget_grace`
    view: stubgen .pyi of relay/loop.py
    behavior: The killed run is ledgered with its spend
    view: stubgen .pyi of relay/loop.py
    behavior: A budget kill is never a failure.
    view: stubgen .pyi of relay/loop.py
    behavior: A backend without `budget_kill`, Claude included, behaves exactly as today: retire only.
    view: stubgen .pyi of relay/loop.py
    behavior: prints spend by basis
    view: stubgen .pyi of relay/cli.py
  s5.d3 | builder | steps: 12 | writes: relay/ledger.py, relay/cli.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s5.d3
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 12
    paths: relay/ledger.py, relay/cli.py
    `append` gains `basis` and `usage`. Each line carries `"basis"`, plus `"usage": [{thread, parent, model, input, cached_input, output}]` when usage is present. `append_failure(kind, section, session, reason, log)` writes a zero-spend `failure` line. `totals_by_basis(since)` serves `relay status`. `over` takes capabilities from `backends.capabilities`.
    `_status` (`relay/cli.py:132-148`) prints spend by basis, for example `all time: N tokens, $X reported, $Y API-equivalent estimate (not subscription billing)`.
    check: uv run pytest tests/test_ledger.py
  s5.d4 | builder | steps: 12 | writes: relay/loop.py, relay/config.py, relay/cli.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s5.d4
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 12
    paths: relay/loop.py, relay/config.py, relay/cli.py
    **Budget termination** on a backend with `budget_kill`:
    relay go ... [--budget-grace F]
    check: uv run pytest tests/test_ledger.py tests/test_loop.py tests/test_cli.py
section s6 | lead | steps: 13, 14 | size: lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  s6.d1 | builder | steps: 14 | writes: relay/state.py, relay/ledger.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s6.d1
    stub
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 14
    paths: relay/state.py, relay/ledger.py
    - Added: `clear_failures(sid)`, `retry(sid, guidance)` and `failed_sections()`.
    `append_failure(kind, section, session, reason, log)` writes a zero-spend `failure` line.
    check: uv run python -c 'import relay.state, relay.ledger'
  s6.d2 | test-writer | steps: 13 | writes: tests/test_state.py, tests/test_loop.py, tests/test_cli.py, tests/test_progress.py | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s6.d2
    red
    design: docs/superpowers/specs/relay-codex-native-revision-design.md step 13
    behavior: A budget kill, a stop file, an interrupt and an idle retire are not failures.
    view: stubgen .pyi of relay/loop.py
    behavior: 2. **Retry once.** At count 1, the next pass runs a fresh lead.
    view: stubgen .pyi of relay/loop.py
    behavior: 3. **Stop at two.**
    view: stubgen .pyi of relay/loop.py
    behavior: a successful recut whose section keeps its id and whose own entry changed
    view: stubgen .pyi of relay/loop.py
    behavior: A recut that keeps the id but leaves the section's entry unchanged keeps the count.
    view: stubgen .pyi of relay/loop.py
    behavior: - `mark_done` and `set_answer` also clear `failures`.
    view: stubgen .pyi of relay/state.py
    behavior: - Spend, sessions, maps and answers are untouched.
    view: stubgen .pyi of relay/state.py
    behavior: 5. **Explicit retry after a blocker is fixed.** `relay retry` is the only way to reopen a section stopped at the limit.
    view: stubgen .pyi of relay/cli.py
    behavior: relay failures <queue.md>
    view: stubgen .pyi of relay/cli.py
    behavior: `Ledger.append_failure`, `progress.failed`
    view: stubgen .pyi of relay/progress.py
  s6.d3 | builder | steps: 14 | writes: relay/state.py, relay/ledger.py, relay/progress.py, relay/loop.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s6.d3
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 14
    paths: relay/state.py, relay/ledger.py, relay/progress.py, relay/loop.py
    `_fail` and `_failed_twice` are the one home. Both call sites, and the recut clear, go through them.
    check: uv run pytest tests/test_state.py tests/test_loop.py tests/test_progress.py
  s6.d4 | builder | steps: 14 | writes: relay/state.py, relay/cli.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s6.d4
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 14
    paths: relay/state.py, relay/cli.py
    5. **Explicit retry after a blocker is fixed.** `relay retry` is the only way to reopen a section stopped at the limit.
    relay failures <queue.md>
    check: uv run pytest tests/test_state.py tests/test_cli.py
section s7 | lead | steps: 15, 16, 17 | size: lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  s7.d1 | builder | steps: 16 | writes: scripts/codex_shakedown.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s7.d1
    stub
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 16
    paths: scripts/codex_shakedown.py
    check: uv run python -c 'import runpy; runpy.run_path("scripts/codex_shakedown.py")'
  s7.d2 | test-writer | steps: 15 | writes: tests/test_shakedown.py | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s7.d2
    red
    design: docs/superpowers/specs/relay-codex-native-revision-design.md step 15
    behavior: Refuses a scratch that exists non-empty or lies inside a git work tree.
    view: stubgen .pyi of scripts/codex_shakedown.py
    behavior: The script uses only the standard library. It builds a fresh scratch git repository with four pieces:
    view: stubgen .pyi of scripts/codex_shakedown.py
    behavior: - roles under `<scratch>/roles`: lead, divvyer, researcher, architect, a helper `builder` that spawns a helper `scout`, and `scout`;
    view: stubgen .pyi of scripts/codex_shakedown.py
    behavior: - a `.codex/hooks.json` probe hook in the scratch repository and one in its parent directory, each writing a marker file if it ever runs;
    view: stubgen .pyi of scripts/codex_shakedown.py
    behavior: - a config whose `state_root`, `roles_dir` and `ping_command` all point inside the scratch.
    view: stubgen .pyi of scripts/codex_shakedown.py
    behavior: Phases run in order. Each declares its expected outcomes. A result matching a declaration is a `Finding` of kind `expected`. Anything else is a `defect`.
    view: stubgen .pyi of scripts/codex_shakedown.py
  s7.d3 | builder | steps: 16 | writes: scripts/codex_shakedown.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s7.d3
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 16
    paths: scripts/codex_shakedown.py
    The script uses only the standard library. It builds a fresh scratch git repository with four pieces:
    Phases run in order. Each declares its expected outcomes. A result matching a declaration is a `Finding` of kind `expected`. Anything else is a `defect`.
    check: uv run pytest tests/test_shakedown.py
  s7.d4 | builder | steps: 16 | writes: scripts/codex_shakedown.py | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s7.d4
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 16
    paths: scripts/codex_shakedown.py
    - **A. Hooks.** After every phase, neither probe marker exists. The run's JSON stdout and rollouts show no hook item. A process sample of each run's group shows no `claude_adapter.py` process.
    - **B. Exec cells.** s1 is done. Its rollout shows the JS cell and each nested `exec_command` call.
    - **C. Helpers.** s2 is done. The ledger's lead line carries `usage` entries for the lead, `builder` and `scout` threads, with `scout`'s parent being `builder`. Every entry is priced with dollars > 0 and `basis: api-estimate`. No thread appears twice.
    - **D. Budget.** On s4, `relay go --dollar-budget <tiny> --budget-grace 0` exits 3. Progress shows a kill, not only a retire. The ledger holds the killed run's spend. `ps -p` on every recorded PID and `kill -0` on every recorded PGID find nothing.
    - **E. Failure and recovery.**
    - **F. Ask.** `relay ask` on a researched section. Its ledger line's usage is net of the research run's (no double count).
    The script records each `relay go` PID and PGID at launch. After each phase it checks them with `ps -p` and kills only by recorded PGID. It prints one evidence block: attempt number, phases, exit codes, ledger excerpts, est. dollars, PID results, then every `Finding`, with defects listed last. It touches nothing outside the scratch except Codex's own new files under `~/.codex/sessions`. It never touches an existing session, the owner's hooks, role files, credentials, any other state root, or any running process.
    check: uv run pytest tests/test_shakedown.py
  s7.d5 | builder | steps: 17 | writes: README.md | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s7.d5
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 17
    paths: README.md
    check: grep -n 'relay retry' README.md
section s8 | lead | steps: 18, 19, 20 | size: lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  s8.d1 | builder | steps: 19 | writes: docs/codex-native-report.md | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s8.d1
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 19
    paths: docs/codex-native-report.md
    attempt: <n>, from the Attempt sections of docs/codex-native-report.md
    check: grep -n 'Attempt' docs/codex-native-report.md
  s8.d2 | test-writer | steps: 20 | writes: the test files each defect's evidence in docs/codex-native-report.md points to | size: test-writer: tokens: 621972.3 seconds: 196.4 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s8.d2
    red
    design: docs/superpowers/specs/relay-codex-native-revision-design.md step 20
    behavior: <each defect line, from section Attempt <n> of docs/codex-native-report.md>
    view: stubgen .pyi of <the module that defect's evidence points to, from docs/codex-native-report.md>
  s8.d3 | builder | steps: 20 | writes: the modules each defect's evidence in docs/codex-native-report.md points to | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s8.d3
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 20
    paths: <the modules each defect's evidence points to, from section Attempt <n> of docs/codex-native-report.md>
    check: uv run pytest <the test files s8.d2 wrote>
section s9 | lead | steps: 21 | size: lead: tokens: 1395004.9 seconds: 743.7 overruns: 0 refusals: 0
  s9.d1 | builder | steps: 21 | writes: docs/codex-native-report.md | size: builder: tokens: 274446.6 seconds: 144.5 overruns: 0 refusals: 0
    queue docs/codex-native-queue.md s9.d1
    design: docs/superpowers/specs/relay-codex-native-revision-design.md
    step: 21
    paths: docs/codex-native-report.md
    - **Dependency inventory**: the table above, re-anchored at HEAD.
    - **Translation adapter judgment**: the evidence that Relay Codex runs never invoke `~/.codex/hooks/claude_adapter.py` (phase A of the clean attempt, and the `PROVEN` args). Also whether anything outside Relay still needs it. That means the owner's interactive Codex sessions and any other tool whose Codex runs load `~/.codex/hooks.json`, each named with its evidence or recorded as unknown. The verdict is "Relay no longer needs it", plus "keep" or "unused" for everyone else. The file is never edited or deleted.
    - **Limitations.**
    - **PID cleanup**: each recorded PID with its `ps -p` result.
    check: grep -n 'Translation adapter judgment' docs/codex-native-report.md
