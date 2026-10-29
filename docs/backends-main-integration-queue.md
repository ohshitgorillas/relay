design docs/superpowers/specs/relay-backends-integration-design.md | order docs/superpowers/specs/relay-backends-integration-design.md | main b7f0051
section s1 | lead | steps: 1, 2, 3, 4 | size: lead: tokens: 1378927.4 seconds: 742.3 overruns: 0 refusals: 0
  s1.d1 | spiker | steps: 1 | writes: the scratchpad | size: spiker: tokens: 140504.6 seconds: 41.3 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s1.d1
    design: docs/superpowers/specs/relay-backends-integration-design.md | Order 1
  s1.d2 | builder | steps: 2 | writes: relay/backends/base.py, relay/backends/__init__.py, relay/backends/codex_session.py, relay/config.py, relay/runner.py, relay/state.py | size: builder: tokens: 273924.8 seconds: 144.9 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s1.d2
    stub
    design: docs/superpowers/specs/relay-backends-integration-design.md | Order 2
    step: 2. Stubs. `builder` (`stub` piece) adds every new signature above, raise-only, to `relay/backends/base.py`, `relay/backends/__init__.py`, `relay/backends/codex_session.py`, `relay/config.py`, `relay/runner.py` and `relay/state.py`. New fields go in with their defaults.
    paths: relay/backends/base.py, relay/backends/__init__.py, relay/backends/codex_session.py, relay/config.py, relay/runner.py, relay/state.py
    check: uv run python -c 'import relay.backends, relay.backends.base, relay.backends.codex_session, relay.config, relay.runner, relay.state'
  s1.d3 | test-writer | steps: 3 | writes: tests/test_backends.py, tests/test_codex_session.py, tests/conftest.py | size: test-writer: tokens: 624794.7 seconds: 198.2 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s1.d3
    red
    design: docs/superpowers/specs/relay-backends-integration-design.md | Order 3
    behavior: each adapter's argv for every role
    view: stubgen .pyi of relay/backends/base.py
    behavior: a resume on each backend
    view: stubgen .pyi of relay/backends/base.py
    behavior: `check` with missing and invalid role files
    view: stubgen .pyi of relay/backends/base.py
    behavior: a resumed rollout's prior lines not counting
    view: stubgen .pyi of relay/backends/codex_session.py
  s1.d4 | test-writer | steps: 3 | writes: tests/test_runner.py, tests/test_config.py, tests/test_state.py | size: test-writer: tokens: 624794.7 seconds: 198.2 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s1.d4
    red
    design: docs/superpowers/specs/relay-backends-integration-design.md | Order 3
    behavior: no log or metadata after a launch-time `ConfigError`
    view: stubgen .pyi of relay/runner.py
    behavior: atomic `.backend.json`
    view: stubgen .pyi of relay/runner.py
    behavior: `RunResult.failed`
    view: stubgen .pyi of relay/runner.py
    behavior: Role to command, for command-driven backends
    view: stubgen .pyi of relay/config.py
    behavior: a session carries its backend
    view: stubgen .pyi of relay/state.py
    behavior: legacy state records
    view: stubgen .pyi of relay/state.py
  s1.d5 | builder | steps: 4 | writes: relay/backends/base.py, relay/backends/__init__.py, relay/backends/claude.py, relay/backends/generic.py, relay/config.py | size: builder: tokens: 273924.8 seconds: 144.9 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s1.d5
    design: docs/superpowers/specs/relay-backends-integration-design.md | Order 4
    step: `relay/backends/__init__.py` gains `capabilities(name: str) -> Capabilities`, read from the adapter class without building per-run resources; it replaces the reads at `relay/loop.py:128`, `relay/loop.py:387` and `relay/loop.py:573`. `get_backend` and `replay` are unchanged.
    step: `argv` returns `cfg.command_for(inv.role)`; Claude appends `["--resume", inv.resume]` for `ask`. Generic sets `resume=False` and raises `ConfigError` on any `inv.resume`. `check` raises nothing for either. This replaces both role tables (`relay/backends/claude.py:19-28`, `relay/backends/generic.py:20-29`).
    step: `load_config` passes an unset `recut_command` as `[]` and `__post_init__` derives it through `_role_command`, as research and design already do, replacing `relay/config.py:195-197`. Positional `Config` construction and every default are unchanged.
    paths: relay/backends/base.py, relay/backends/__init__.py, relay/backends/claude.py, relay/backends/generic.py, relay/config.py
    check: uv run pytest tests/test_config.py
  s1.d6 | builder | steps: 4 | writes: relay/backends/codex.py, relay/backends/codex_session.py | size: builder: tokens: 273924.8 seconds: 144.9 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s1.d6
    design: docs/superpowers/specs/relay-backends-integration-design.md | Order 4
    step: `argv` keeps its role-file mapping (`ask` and `research` both load `researcher.toml`) and overrides, and for `ask` builds `codex exec resume` with `inv.resume` in place of reading it from `research_command`, which replaces `relay/backends/codex.py:57-63`. The resume argv carries exactly the flags the step 1 evidence shows 0.165.0's `exec resume` accepts; a flag it lacks is not passed, and the cwd comes from the runner's `cwd` when `-C` is absent. `check` loads and validates the role file of each role given, through the same loader `argv` uses, so start-up and launch read one validation. `resume=True`.
    step: For a run whose invocation has `resume` set, `poll` builds its `SessionReader` with `skip_existing=True`, so only `token_count` lines written after launch count, and `finish` errors when this run observed none.
    step: The size is taken at the first successful locate; a rollout first created after launch is read from byte 0.
    evidence: <the CLAIM and ANSWER lines of s1.d1's report, verbatim>
    paths: relay/backends/codex.py, relay/backends/codex_session.py
    check: uv run pytest tests/test_backends.py tests/test_codex_session.py tests/test_config.py
  s1.d7 | builder | steps: 4 | writes: relay/runner.py, relay/state.py | size: builder: tokens: 273924.8 seconds: 144.9 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s1.d7
    design: docs/superpowers/specs/relay-backends-integration-design.md | Order 4
    step: The legacy `argv` positional and the `cfg is None` path go; tests call `run_agent` with a backend and cfg (`tests/test_runner.py:54` already does). Process, signal and cleanup behavior (`relay/runner.py:229-316`) is unchanged.
    step: A state record without these keys reads them as `"claude"`.
    paths: relay/runner.py, relay/state.py
    check: uv run pytest tests/test_runner.py tests/test_state.py
section s2 | lead | steps: 5, 6 | size: lead: tokens: 1378927.4 seconds: 742.3 overruns: 0 refusals: 0
  s2.d1 | builder | steps: 6 | writes: relay/prompts.py | size: builder: tokens: 273924.8 seconds: 144.9 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s2.d1
    stub
    design: docs/superpowers/specs/relay-backends-integration-design.md | Order 6
    step: `lead_prompt` gains `backend: str = "claude"`. When it is not `"claude"`, the `relay ask` command in the map paragraph reads `relay ask --backend <backend> <queue> <sid> "<question>"`; the Claude wording is unchanged.
    paths: relay/prompts.py
    check: uv run python -c 'import relay.prompts'
  s2.d2 | test-writer | steps: 5 | writes: tests/test_loop.py, tests/conftest.py | size: test-writer: tokens: 624794.7 seconds: 198.2 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s2.d2
    red
    design: docs/superpowers/specs/relay-backends-integration-design.md | Order 5
    behavior: research, ask and design runs on Claude, Codex (fake adapter) and generic
    view: stubgen .pyi of relay/loop.py
    behavior: `relay go` stopping at start on a bad role file
    view: stubgen .pyi of relay/loop.py
    behavior: the lead's hint worded by the recorded backend across a backend change
    view: stubgen .pyi of relay/loop.py
    behavior: every failure branch through `result.failed`
    view: stubgen .pyi of relay/loop.py
  s2.d3 | test-writer | steps: 5 | writes: tests/test_prompts.py, tests/test_cli.py | size: test-writer: tokens: 624794.7 seconds: 198.2 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s2.d3
    red
    design: docs/superpowers/specs/relay-backends-integration-design.md | Order 5
    behavior: `relay ask` refused on generic and on a backend mismatch
    view: stubgen .pyi of relay/cli.py
    behavior: `relay ask` gains `--backend`, passed as the `backend` override to `load_config`.
    view: stubgen .pyi of relay/cli.py
    behavior: `lead_prompt` gains `backend: str = "claude"`.
    view: stubgen .pyi of relay/prompts.py
    behavior: the Claude wording is unchanged
    view: stubgen .pyi of relay/prompts.py
  s2.d4 | builder | steps: 6 | writes: relay/prompts.py | size: builder: tokens: 273924.8 seconds: 144.9 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s2.d4
    design: docs/superpowers/specs/relay-backends-integration-design.md | Order 6
    step: `lead_prompt` gains `backend: str = "claude"`. When it is not `"claude"`, the `relay ask` command in the map paragraph reads `relay ask --backend <backend> <queue> <sid> "<question>"`; the Claude wording is unchanged.
    paths: relay/prompts.py
    check: uv run pytest tests/test_prompts.py
  s2.d5 | builder | steps: 6 | writes: relay/loop.py | size: builder: tokens: 273924.8 seconds: 144.9 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s2.d5
    design: docs/superpowers/specs/relay-backends-integration-design.md | Order 6
    step: `run` calls `backends.get_backend(cfg.backend).check(cfg, ("lead", "recut", "research", "design"))` before the first pass; `ask` calls it with `("ask",)` before its run.
    step: The lead's handoff hint is `get_backend(<recorded backend of the resumed session>).resume_hint(resume)`, from `last_backend` or `last_backend_any`; the lead's session is recorded with `cfg.backend`.
    step: `_research` records the researcher's session with `cfg.backend`.
    step: `ask` raises `ResearchError` when `capabilities(cfg.backend).resume` is False, when the section has no `research_session`, or when `research_backend` differs from `cfg.backend`, naming both; otherwise `_run(kind="ask", resume=research_session)`.
    step: Every failure test reads `result.failed`; `_design_outcome` keeps its reason wording branches (`relay/loop.py:627-632`) and reaches them only when `result.failed`. Idle retire keeps `watch.idle_retired and not result.stream.is_error`.
    paths: relay/loop.py
    check: uv run pytest tests/test_loop.py
  s2.d6 | builder | steps: 6 | writes: relay/cli.py, README.md | size: builder: tokens: 273924.8 seconds: 144.9 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s2.d6
    design: docs/superpowers/specs/relay-backends-integration-design.md | Order 6
    step: `relay ask` gains `--backend`, passed as the `backend` override to `load_config`.
    step: The backend section states that `relay ask` uses the backend the researcher ran under, that generic researchers cannot be asked follow-ups, and that every Codex role file is checked when `relay go` starts.
    paths: relay/cli.py, README.md
    check: uv run pytest tests/test_cli.py
section s3 | lead | steps: 7, 8, 9 | size: lead: tokens: 1378927.4 seconds: 742.3 overruns: 0 refusals: 0
  s3.d1 | diff-reviewer | steps: 7 | writes: nothing | size: diff-reviewer: tokens: 170551.1 seconds: 49.8 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s3.d1
  s3.d2 | diff-reviewer | steps: 7 | writes: nothing | size: diff-reviewer: tokens: 170551.1 seconds: 49.8 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s3.d2
    MERGE_HEAD
  s3.d3 | test-reviewer | steps: 7 | writes: nothing | size: test-reviewer: tokens: 198814.0 seconds: 67.7 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s3.d3
    working tree
    spec: docs/superpowers/specs/relay-backends-integration-design.md
    spec: docs/superpowers/specs/relay-backends-design.md
    spec: docs/superpowers/specs/relay-research-design.md
    spec: docs/superpowers/specs/relay-check-design.md
    spec: docs/superpowers/specs/relay-ladder-design.md
  s3.d4 | test-reviewer | steps: 7 | writes: nothing | size: test-reviewer: tokens: 198814.0 seconds: 67.7 overruns: 0 refusals: 0
    queue docs/backends-main-integration-queue.md s3.d4
    MERGE_HEAD
    spec: docs/superpowers/specs/relay-backends-integration-design.md
    spec: docs/superpowers/specs/relay-backends-design.md
    spec: docs/superpowers/specs/relay-research-design.md
    spec: docs/superpowers/specs/relay-check-design.md
    spec: docs/superpowers/specs/relay-ladder-design.md
