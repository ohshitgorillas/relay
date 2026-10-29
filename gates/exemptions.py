"""Exemption audit: every suppression of a gate in force carries the owner's words and a reason."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import io
import re
import sys
import tokenize
import tomllib

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
    findings: list[Finding] = []
    active = tuple(dict.fromkeys(gates))
    for directory in ("relay", "gates", "tests"):
        for path in sorted((root / directory).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            lines = source.splitlines()
            for token in tokenize.generate_tokens(io.StringIO(source).readline):
                if token.type != tokenize.COMMENT:
                    continue
                for gate in active:
                    matches = [
                        match
                        for pattern in MARKERS.get(gate, ())
                        for match in re.finditer(pattern, token.string)
                    ]
                    if any(not re.search(RECORD, token.string[match.end() :]) for match in matches):
                        number = token.start[0]
                        findings.append(Finding(path, number, gate, lines[number - 1]))
    config = root / "pyproject.toml"
    if config.is_file():
        findings.extend(_scan_config(config, active))
    return findings


def _key_parts(key: str) -> tuple[str, ...]:
    """Decode a dotted TOML key, including quoted and escaped components."""
    value = tomllib.loads(f"{key} = 0")
    parts: list[str] = []
    while isinstance(value, dict):
        name, value = next(iter(value.items()))
        parts.append(name)
    return tuple(parts)


def _config_line(line: str) -> tuple[str, str]:
    """Separate code from its comment without treating quoted hashes as comments."""
    strings = re.compile(r""""(?:[^"\\]|\\.)*"|'[^']*'|\#.*""")
    for match in strings.finditer(line):
        if match.group().startswith("#"):
            return line[: match.start()].strip(), match.group()
    return line.strip(), ""


def _config_entries(value: object, prefix: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Expand inline tables to the same paths as ordinary TOML assignments."""
    if isinstance(value, dict):
        return [
            entry
            for key, child in value.items()
            for entry in _config_entries(child, prefix + (key,))
        ]
    if isinstance(value, list) and any(isinstance(child, dict) for child in value):
        return [entry for child in value for entry in _config_entries(child, prefix)]
    return [prefix]


def _scan_config(path: Path, gates: Sequence[str]) -> list[Finding]:
    """Audit exempting entries while retaining their original source lines."""
    findings: list[Finding] = []
    tables = {
        gate: tuple(_key_parts(table) for table in CONFIG_TABLES.get(gate, ())) for gate in gates
    }
    profiles = {_key_parts(profile) for profile in PROFILE}
    section: tuple[str, ...] = ()
    pending = ""
    entry: tuple[str, ...] = ()
    for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        code, comment = _config_line(text)
        if not code:
            continue
        if not pending and code.startswith("["):
            section = _key_parts(code.strip("[] "))
            continue
        if not pending:
            assignment = re.match(r"""((?:"(?:[^"\\]|\\.)*"|'[^']*'|[^=])+)=(.*)""", code)
            if assignment is None:
                continue
            key, value = assignment.groups()
            entry = section + _key_parts(key.strip())
            pending = f"{key} = {value}"
        else:
            pending += "\n" + code
        try:
            parsed = tomllib.loads(pending)
        except tomllib.TOMLDecodeError:
            entries = [entry]
        else:
            entries = _config_entries(parsed, section)
            pending = ""
        for gate, prefixes in tables.items():
            if any(
                candidate not in profiles and candidate[: len(prefix)] == prefix
                for candidate in entries
                for prefix in prefixes
            ):
                if code.rstrip(",").strip() not in {"[", "]", "{", "}"}:
                    if not re.search(RECORD, comment):
                        findings.append(Finding(path, number, gate, text))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    """Audit the gates named in argv; print each finding as `path:line: gate: text`; 0 when none, 1 otherwise."""
    findings = scan(Path.cwd(), sys.argv[1:] if argv is None else argv)
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.gate}: {finding.text}")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
