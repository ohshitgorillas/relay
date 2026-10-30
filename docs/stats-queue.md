design docs/superpowers/specs/relay-stats-design.md | order docs/superpowers/specs/relay-stats-design.md | main a05719a
section s1 | lead | steps: 1, 2 | size: calibration
  s1.d1 | builder | steps: 2 | writes: relay/history.py, relay/agents.py, relay/ledger.py, relay/state.py | size: calibration
    queue /Users/atom/dev/relay-wt/unblock/docs/stats-queue.md s1.d1
    stub
    design: docs/superpowers/specs/relay-stats-design.md
    step: Order step 2, Core build: the Modules signatures of relay/history.py, relay/agents.py (Agent.peak), relay/ledger.py (Ledger.entries) and relay/state.py (numbered_logs, State.run_logs, State.all), every body raise NotImplementedError
    paths: relay/history.py, relay/agents.py, relay/ledger.py, relay/state.py
    check: uv run python -c 'import relay.history, relay.agents, relay.ledger, relay.state'
  s1.d2 | test-writer | steps: 1 | writes: tests/test_history.py, tests/test_agents.py, tests/test_ledger.py, tests/test_state.py, tests/harness.py | size: calibration
    queue /Users/atom/dev/relay-wt/unblock/docs/stats-queue.md s1.d2
    red
    design: docs/superpowers/specs/relay-stats-design.md, Order step 1
    behavior: **`relay/history.py`** (new): the one place that turns a state directory into its runs. Each run is one ledger line paired with its replayed run log. Pairing follows `relay/cli.py:99-122`: runs are numbered and ledgered in the order they ran, so a session that the ledger names more than once is paired with its logs in that order. A log that cannot be replayed (`OSError`, `ConfigError` from `relay/backends/__init__.py:59`) is skipped and counted. A ledger line with no session, such as a `check` line (`relay/ledger.py:116`), is no run.
    view: stubgen .pyi of relay/history.py
    behavior: **`relay/agents.py`** (extended): `Agent` gains `peak: int = 0`, which `_with_usage` (`relay/agents.py:102`) sets to the largest `total_tokens` reported. `restore_agent` (`relay/agents.py:63`) reads it when present and otherwise leaves it 0, so `max(peak, context)` stays right for older telemetry snapshots.
    view: stubgen .pyi of relay/agents.py
    behavior: def entries(self) -> Iterator[dict]: ...   # each readable line, in the order written
    view: stubgen .pyi of relay/ledger.py
    behavior: def run_logs(self) -> list[Path]: ...            # numbered runs/*.jsonl, ascending by number
    view: stubgen .pyi of relay/state.py
    behavior: def all(cls, cfg: Config) -> list["State"]: ...  # each directory under cfg.state_root holding a ledger.jsonl
    view: stubgen .pyi of relay/state.py
  s1.d3 | builder | steps: 2 | writes: relay/history.py, relay/agents.py, relay/ledger.py, relay/state.py, relay/runner.py, relay/cli.py | size: calibration
    queue /Users/atom/dev/relay-wt/unblock/docs/stats-queue.md s1.d3
    design: docs/superpowers/specs/relay-stats-design.md
    step: Order step 2, Core build
    paths: relay/history.py, relay/agents.py, relay/ledger.py, relay/state.py, relay/runner.py, relay/cli.py
    check: uv run python -m pytest tests/test_history.py tests/test_agents.py tests/test_ledger.py tests/test_state.py tests/test_runner.py tests/test_status.py tests/test_cli.py
section s2 | lead | steps: 3, 4 | size: calibration
  s2.d1 | builder | steps: 4 | writes: relay/stats.py, relay/cli.py | size: calibration
    queue /Users/atom/dev/relay-wt/unblock/docs/stats-queue.md s2.d1
    stub
    design: docs/superpowers/specs/relay-stats-design.md
    step: Order step 4, Stats build: the Modules signatures of relay/stats.py (Role, Sized, RoleStats, sized, by_role, lines) and the relay/cli.py `stats` subcommand, every body raise NotImplementedError
    paths: relay/stats.py, relay/cli.py
    check: uv run python -c 'import relay.stats, relay.cli'
  s2.d2 | test-writer | steps: 3 | writes: tests/test_stats.py, tests/test_cli.py | size: calibration
    queue /Users/atom/dev/relay-wt/unblock/docs/stats-queue.md s2.d2
    red
    design: docs/superpowers/specs/relay-stats-design.md, Order step 3
    behavior: - **Top-level run.** Its role is `Run.kind` and its peak is `stream.peak_context`. It is an overrun when `parse_status(stream.result_text)` is `RETIRED` (`"retired"`). It is also an overrun when it has no result after reaching `cfg.hard_ceiling` (`"killed"`), or when its peak is at or above `cfg.context_limit` (`"over context limit"`). These limits are the ones the watcher enforces at `relay/loop.py:558` and `relay/loop.py:567`. A lead run with any other status, or with none, is neither finished nor overrun unless it ended `DONE`. A run of any other kind is finished when it has a result and `is_error` is false.
    view: stubgen .pyi of relay/stats.py
    behavior: - **Subagent** (`stream.activity.agents`). Its role is `Agent.name` and its peak is `max(Agent.peak, Agent.context)`. It is finished when `status == "completed"` and its peak is below `cfg.context_limit`. It is an overrun when `status == "stopped"` (`"stopped"`) or when its peak is at or above `cfg.context_limit` (`"over context limit"`). Any other status is neither.
    view: stubgen .pyi of relay/stats.py
    behavior: def by_role(items: Iterable[Sized]) -> list[RoleStats]: ...   # sorted by role name
    view: stubgen .pyi of relay/stats.py
    behavior: <role>: <n> finished, peak context median <m>, p90 <p>, max <x>; <k> overruns
    view: stubgen .pyi of relay/stats.py
    behavior: A role with no finished run prints `0 finished` and no figures. After each role line come its overruns, newest last, at most five, each one line:
    view: stubgen .pyi of relay/stats.py
    behavior:   <role> overrun: <section> <label> peak <n> (<reason>)
    view: stubgen .pyi of relay/stats.py
    behavior: When a role has more than five overruns, the five lines are preceded by `  <role>: <j> earlier overruns not shown`. Numbers are bare integers, as `relay/progress.py:48` prints them. A final line `skipped <n> unreadable run logs` appears only when `n > 0`.
    view: stubgen .pyi of relay/stats.py
    behavior: **`relay/cli.py`** (extended): a `stats` subcommand that takes no arguments. It loads `_config({})`, reads every `State.all(cfg)` with `history.read`, joins the runs, and prints `stats.lines(stats.by_role(stats.sized(history, cfg)))`. It returns `ExitCode.QUEUE_EMPTY` (`relay/errors.py:25`). When no state directory exists, it prints `no runs under <state_root>` and exits the same way. Errors go through `main`'s `RelayError` handler (`relay/cli.py:168-174`).
  s2.d3 | builder | steps: 4 | writes: relay/stats.py, relay/cli.py | size: calibration
    queue /Users/atom/dev/relay-wt/unblock/docs/stats-queue.md s2.d3
    design: docs/superpowers/specs/relay-stats-design.md
    step: Order step 4, Stats build
    paths: relay/stats.py, relay/cli.py
    check: uv run python -m pytest tests/test_stats.py tests/test_cli.py
