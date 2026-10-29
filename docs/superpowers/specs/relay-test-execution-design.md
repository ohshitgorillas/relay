Status: approved.

## Why

The dev group holds only pytest (`pyproject.toml:11`) and supplies no timeout or worker policy. Tests already isolate scenario files and state beneath `tmp_path` (`tests/conftest.py:19`, `tests/conftest.py:49`). Real-child tests own recorded PIDs and cleanup (`tests/test_runner.py:46`, `tests/test_runner.py:275`). Loop tests have bounded thread joins (`tests/test_loop.py:114`), but no suite-wide per-test deadline protects a blocked call.

This supplements the test-harness migration with one execution policy. Speed and parallel safety remain measured acceptance conditions, not assumed benefits.

## Modules

`pyproject.toml` owns pytest execution defaults and dev dependencies. Add pytest-timeout and pytest-xdist to the dev group, and resolve them in `uv.lock`.

```toml
[tool.pytest.ini_options]
addopts = "-n 2 --dist=load"
timeout = 30
timeout_method = "signal"
```

The two workers are separate processes. Each executes one test at a time with its own temporary paths, environment mutations and signal handlers. Real-child tests continue exercising real children. No tests are skipped, deleted, grouped out of execution or given weaker assertions.

The timeout covers each test including setup and teardown. On this POSIX host, signal-based failure unwinds normal Python cleanup rather than terminating the worker immediately. Existing test and runner cleanup remains responsible for child groups; the timeout is not a replacement for it. No thread-method fallback or hard worker termination is introduced. A reproducible deadline failure is investigated before changing the deadline or granting any exemption.

Explicit `-n 0` supports a serial comparison. No automatic CPU-derived worker count is configured. The default is enabled only after the complete suite passes under two workers with the baseline test count and no new skips.

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Worker count and test deadline | `pyproject.toml` pytest options | Duplicated wrapper defaults or per-file blanket exemptions |
| Plugin resolution | `uv.lock` | Unpinned ad hoc plugin installation for gates |
| Child cleanup and temporary data | Existing runner/tests and shared test harness | Treating a timeout as proof that children were reaped |

## Order

1. Execution configuration. `builder` updates `pyproject.toml` and `uv.lock` with the dev plugins and pytest defaults above after the harness migration. Done-check: `uv run pytest --durations=25`, timed externally, with the baseline test count and no new skips; report the elapsed time and slowest tests. Parallel failures or cleanup gaps stop this step for a focused harness repair; no production seam is prescribed by this configuration design.
