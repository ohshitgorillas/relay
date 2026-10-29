Status: approved.

## Why

Relay has no gate. Nothing runs a linter, a formatter, a type checker or a coverage floor, and nothing stops a commit:

- No `Makefile` and no tracked hook exist; the only dev tools declared are `pytest`, `pytest-timeout` and `pytest-xdist` (`pyproject.toml:10-11`). `ruff` sits in `.venv/bin` undeclared, so no lockfile pins it.
- The test configuration is the only tool configuration (`pyproject.toml:20-23`).
- Seven suppressions already sit in the tree, none carrying anyone's approval: `relay/cli.py:22`, `tests/test_ladder.py:72`, `tests/test_ladder.py:105`, `tests/test_config.py:169`, `tests/test_config.py:403` (`# type: ignore`), `tests/test_state.py:665`, `tests/test_ledger.py:155` (`# noqa: BLE001`).
- 1702 lines exceed 88 columns, 368 exceed 100 and 30 exceed 120, across `relay/`, `tests/` and `tests/fakes/` (unformatted).
- Test repositories already run with `core.hooksPath=/dev/null` (`tests/conftest.py:142`), so a repository hook never fires inside the suite.

Relay's runtime check runner (`relay/check.py:49`) runs a queue section's `check:` lines; it is Relay's product, not a gate on Relay's own code, and this design leaves it untouched.

## Modules

### `Makefile` — the one gate entry point

`make check` runs every gate with `--keep-going`, so one run reports every failing gate, and exits non-zero if any failed. Each gate is one target; `GATES` lists the gates in force, and a gate joins `GATES` only in the step that leaves the tree passing it.

```make
GATES :=                       # each gate step appends its name: format lint types filepawl hooks-installed

.PHONY: check check-all lock exemptions test format lint types filepawl hooks hooks-installed

check:                         # the one entry point; runs everything, reports every failure
	$(MAKE) --keep-going check-all

check-all: lock exemptions $(GATES) test

lock:                          # uv.lock matches pyproject.toml
	uv lock --check

exemptions:                    # every suppression of a gate in force carries the owner's words and a reason
	uv run python -m gates.exemptions $(GATES)

test:                          # the full suite; from the coverage step on, with the coverage floor
	uv run pytest

format:
	uv run ruff format --check relay gates tests

lint:
	uv run ruff check relay gates tests

types:
	uv run mypy

filepawl:                      # the command filepawl's own docs give; written by the filepawl step
	false

hooks:                         # one-time install; shared by every worktree of the repository
	git config core.hooksPath .githooks

hooks-installed:               # fails unless the commit hook is installed
	test "$$(git config core.hooksPath)" = .githooks
```

Replaces: nothing; no entry point exists.

### `gates/exemptions.py` — the exemption audit

Fails on any suppression of a gate in force that does not carry the owner's words and a reason on the same line. It reads `.py` files under `relay/`, `gates/` and `tests/`, and `pyproject.toml`.

The record form, written on the suppression's own line, after the suppression:

```python
except BaseException as exc:  # noqa: BLE001  owner: "<the owner's words, verbatim>" reason: <why the rule cannot hold here>
```

```toml
"relay/x.py" = ["S310"]  # owner: "<the owner's words, verbatim>" reason: <why>
```

```python
"""Exemption audit: every suppression of a gate in force carries the owner's words and a reason."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# gate name -> regexes matching a suppression of that gate in a .py line
MARKERS: dict[str, tuple[str, ...]] = {
    "format": (r"#\s*fmt:\s*(off|skip)",),
    "lint": (r"#\s*noqa\b", r"#\s*ruff:\s*noqa\b"),
    "types": (r"#\s*type:\s*ignore\b", r"#\s*mypy:"),
    "test": (r"#\s*pragma:\s*no\s*cover\b",),
}

# gate name -> pyproject.toml tables whose every entry is an exemption of that gate
CONFIG_TABLES: dict[str, tuple[str, ...]] = {
    "lint": ("tool.ruff.lint.per-file-ignores",),
    "types": ("tool.mypy.overrides",),
    "test": ("tool.coverage.run.omit", "tool.coverage.report.exclude_lines"),
}

# config entries that define a gate rather than exempt code from it: this design's tests profile
PROFILE: frozenset[str] = frozenset({'tool.ruff.lint.per-file-ignores."tests/**"'})

RECORD: str = r'owner:\s*"[^"]+"\s+reason:\s*\S'


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    gate: str
    text: str


def scan(root: Path, gates: Sequence[str]) -> list[Finding]:
    """Return every suppression of `gates` under `root` that lacks the owner record; a gate with no marker (`hooks-installed`) has none."""
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    """Audit the gates named in argv; print each finding as `path:line: gate: text`; 0 when none, 1 otherwise."""
    raise NotImplementedError
```

`gates/__init__.py` is empty. `make check` runs `exemptions` with `test` in its argument list once `test` carries the coverage floor; until then `test` has no exemptions to audit.

Replaces: nothing; the seven suppressions listed under **Why** are resolved by the lint and types steps.

### `pyproject.toml` — every tool's configuration

Adds to the `dev` group (`pyproject.toml:11`): `ruff`, `mypy`, `pytest-cov`, and filepawl as its own docs say to install it. Adds:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"
src = ["relay", "gates", "tests"]

[tool.ruff.lint]
select = ["ALL"]
ignore = [
    # counts: the owner's rule, no limit on how many of anything
    "C90", "PLR0904", "PLR0911", "PLR0912", "PLR0913", "PLR0914",
    "PLR0915", "PLR0916", "PLR0917", "PLR1702",
    # the formatter owns these
    "COM812", "ISC001",
    # Relay is a CLI that prints its output and runs configured commands by design
    "T20", "S603", "S607",
]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "PLR2004", "D", "SLF001", "INP001", "ARG001", "FBT001"]

[tool.mypy]
strict = true
python_version = "3.12"
files = ["relay", "gates", "tests"]

[tool.coverage.run]
source = ["relay", "gates"]
parallel = true

[tool.coverage.report]
fail_under = 0   # the coverage step sets the measured whole-percent floor
show_missing = true
```

The coverage step adds `--cov --cov-report=term-missing` to `addopts` (`pyproject.toml:21`).

### `.githooks/pre-commit` — the commit path

```sh
#!/bin/sh
exec make check
```

Executable, tracked. `make hooks` points the repository at it once, for the main checkout and every worktree; `make check` runs `hooks-installed`, so a checkout without the hook fails the gate. A commit made with `--no-verify` skips the hook; every queue section's `check:` line runs `make check`, so such a commit still fails at the section's DONE.

## Homes

| Concern | Home | Forbidden elsewhere |
|---|---|---|
| Gate entry point | `Makefile` `check` | Any other script, alias or CI file that runs gates; a gate run outside `make check`'s target |
| Gates in force | `Makefile` `GATES` | A gate target in `check-all` that is not listed in `GATES`; a gate added to `GATES` before the tree passes it |
| Tool configuration | `pyproject.toml` `[tool.*]` | `ruff.toml`, `mypy.ini`, `.coveragerc`, `setup.cfg`, `pytest.ini`, tool flags in the `Makefile` beyond the paths to check |
| Dev tools and versions | `pyproject.toml` `dev` group and `uv.lock` | A tool run that is not declared there (`ruff` in `.venv/bin` today) |
| Exemptions | The suppression's own line, with `owner: "<words>" reason: <why>` | A suppression without the record; a separate exemption list; an owner record written from anything but the owner's own words given to that agent |
| Exemption audit | `gates/exemptions.py` | A second scan for suppressions; a gate's suppression marker not in `MARKERS` or `CONFIG_TABLES` |
| Coverage floor | `pyproject.toml` `[tool.coverage.report] fail_under` | A `--cov-fail-under` flag; a floor set below the measured whole percent |
| Commit path | `.githooks/pre-commit` | Any other hook; a hook that runs less than `make check` |

## Order

Each step leaves `uv run pytest` green and `make check` green for the gates then in `GATES`. A cleanup changes no behavior: no test changes its assertions, inputs or expected values, and none is deleted. A cleanup that finds a site no behavior-neutral rewrite fixes stops and asks the owner for an exemption; it never writes an owner record from its own words.

1. **Gate frame, stubs.** `builder` (stub): `gates/__init__.py`, `gates/exemptions.py` raise-only per **Modules**.
2. **Exemption audit, red tests.** `test-writer`: `tests/test_exemptions.py`.
3. **Gate frame.** `builder`: `gates/exemptions.py`, `Makefile` (every target per **Modules**, `GATES` empty), `pyproject.toml` (dev group, the `[tool.ruff]`, `[tool.mypy]` and `[tool.coverage]` tables), `uv.lock`.
4. **Format, code.** `builder`: `ruff format` over `relay/` and `gates/`.
5. **Format, tests.** `test-writer`: `ruff format` over `tests/`; adds nothing else.
6. **Format gate on.** `builder`: `Makefile` (`format` joins `GATES`).
7. **Lint, code.** `builder`: `relay/`, `gates/` pass `ruff check`; `relay/cli.py:22`'s suppression goes if a typed rewrite removes it.
8. **Lint, tests.** `test-writer`: `tests/` pass `ruff check`; `tests/test_state.py:665` and `tests/test_ledger.py:155` lose their `noqa` where a rewrite keeps the test's behavior.
9. **Lint gate on.** `builder`: `Makefile` (`lint` joins `GATES`).
10. **Types, code.** `builder`: `relay/`, `gates/` pass `mypy`.
11. **Types, tests.** `test-writer`: `tests/` pass `mypy`; `tests/test_ladder.py:72`, `tests/test_ladder.py:105`, `tests/test_config.py:169`, `tests/test_config.py:403` lose their `type: ignore` where a rewrite keeps the test's behavior.
12. **Types gate on.** `builder`: `Makefile` (`types` joins `GATES`).
13. **Coverage floor.** `builder`: `pyproject.toml` (`addopts`, `fail_under` set to the measured total rounded down to a whole percent), `Makefile` (the `exemptions` target audits `$(GATES) test`).
14. **filepawl, code.** `builder`: reads filepawl's own docs and code under `~/dev/filepawl` for what it enforces, how it runs and how it marks an exemption; adds filepawl to `dev` in `pyproject.toml` and `uv.lock` as those docs say; fixes what it reports in `relay/` and `gates/` without behavior change.
15. **filepawl, tests.** `test-writer`: fixes what filepawl reports in `tests/` without behavior change.
16. **filepawl exemption marker, red test.** `test-writer`: `tests/test_exemptions.py`.
17. **filepawl gate on.** `builder`: `gates/exemptions.py` (`MARKERS["filepawl"]`, and `CONFIG_TABLES["filepawl"]` if filepawl reads `pyproject.toml`), `pyproject.toml` (filepawl's config, if any), `Makefile` (`filepawl` target, joins `GATES`).
18. **Commit hook.** `builder`: `.githooks/pre-commit`, `Makefile` (`hooks-installed` joins `GATES`), `README.md` (a Development section: `make check`, `make hooks`, the exemption record), and `make hooks` run once in the main checkout. This step lands last: no step after it runs under the hook.

Gate worth: the format and lint gates keep agent-written code uniform and catch dead and unsafe code; the types gate catches the wrong-shape data Relay passes between loop, state and backends; the coverage floor stops untested code landing; the lock gate stops an undeclared or drifted tool; the exemption audit makes every suppression carry the owner's approval; the hook makes `make check` run before every commit. A separate file or function size cap is left out: the owner's lint rule lifts every count limit, and filepawl may already cover file shape. Each commit runs the full suite through the hook; its time is unmeasured.

## Decisions for the owner

1. **The 31 branches not merged into main.** Format and lint rewrite most lines of `relay/` and `tests/`, so every unmerged branch (`feat/agent-activity`, `fix/codex-gauntlet`, `lead/s1`–`lead/s8` and others) conflicts on merge.
   - Recommend: run this queue now; each branch, when it next merges, rebases onto main, runs `ruff format`, and passes `make check`. Cost: one conflict-resolution pass per surviving branch, unmeasured.
   - Alternative: merge or drop those branches first, then run this queue. Cost: the gates wait on that work.
