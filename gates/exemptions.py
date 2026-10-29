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
