"""Exemption audit contract from relay-gates-design Modules."""

from pathlib import Path

import pytest

from gates.exemptions import Finding, main, scan


COMMENT = chr(35)
RECORD = 'owner: "Approved for this fixture" reason: exercise the audit contract'


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.mark.parametrize(
    ("gate", "marker"),
    [
        ("format", "fmt: off"),
        ("format", "fmt: skip"),
        ("lint", "noqa: S310"),
        ("lint", "ruff: noqa"),
        ("types", "type: ignore[arg-type]"),
        ("types", "mypy: ignore-errors"),
        ("test", "pragma: no cover"),
    ],
)
def test_each_active_gate_reports_its_unrecorded_suppression(
    tmp_path: Path, gate: str, marker: str
) -> None:
    # Breaks when a documented suppression marker is omitted or misclassified.
    text = f"pass  {COMMENT} {marker}"
    path = _write(tmp_path, "relay/sample.py", f"pass\n{text}\n")
    assert scan(tmp_path, [gate]) == [Finding(path, 2, gate, text)]


def test_only_gates_in_force_are_audited(tmp_path: Path) -> None:
    # Breaks when inactive gates or a gate without markers produce findings.
    _write(tmp_path, "relay/sample.py", f"pass  {COMMENT} type: ignore\n")
    assert scan(tmp_path, ["lint", "hooks-installed"]) == []
    assert scan(tmp_path, []) == []


def test_every_simultaneously_active_gate_is_audited(tmp_path: Path) -> None:
    # Breaks when the audit stops after one active gate or omits another gate.
    markers = [
        ("format", "fmt: off"),
        ("lint", "noqa: S310"),
        ("types", "type: ignore[arg-type]"),
        ("test", "pragma: no cover"),
    ]
    lines = [f"pass  {COMMENT} {marker}" for _, marker in markers]
    path = _write(tmp_path, "relay/sample.py", "\n".join(lines) + "\n")
    findings = scan(tmp_path, [gate for gate, _ in markers])
    assert sorted(findings, key=lambda finding: finding.line) == [
        Finding(path, line, gate, text)
        for line, ((gate, _), text) in enumerate(zip(markers, lines), start=1)
    ]


@pytest.mark.parametrize(
    "record",
    [
        RECORD,
        'owner:   "Keep it"   reason: justified',
    ],
)
def test_owner_words_and_reason_after_suppression_are_accepted(tmp_path: Path, record: str) -> None:
    # Breaks when a valid same-line approval record is rejected.
    _write(tmp_path, "gates/sample.py", f"pass  {COMMENT} noqa: S310  {record}\n")
    assert scan(tmp_path, ["lint"]) == []


@pytest.mark.parametrize(
    "record",
    [
        "reason: justified",
        'owner: "Keep it"',
        'owner: "" reason: justified',
        "owner: Keep-it reason: justified",
        'owner: "Keep it" reason:   ',
    ],
)
def test_incomplete_record_does_not_authorize_a_suppression(tmp_path: Path, record: str) -> None:
    # Breaks when missing owner words, quotes, or a reason authorize a suppression.
    text = f"pass  {COMMENT} noqa: S310  {record}"
    path = _write(tmp_path, "tests/sample.py", text + "\n")
    assert scan(tmp_path, ["lint"]) == [Finding(path, 1, "lint", text)]


def test_record_must_follow_the_suppression_on_its_own_line(tmp_path: Path) -> None:
    # Breaks when an earlier line, later line, or preceding record authorizes it.
    plain = f"pass  {COMMENT} noqa: S310"
    preceding = f"pass  {COMMENT} {RECORD}  {COMMENT} noqa: S310"
    path = _write(
        tmp_path,
        "relay/sample.py",
        f"{COMMENT} {RECORD}\n{plain}\n{COMMENT} {RECORD}\n{preceding}\n",
    )
    assert sorted(scan(tmp_path, ["lint"]), key=lambda finding: finding.line) == [
        Finding(path, 2, "lint", plain),
        Finding(path, 4, "lint", preceding),
    ]


def test_scan_reads_nested_python_files_in_each_documented_tree(tmp_path: Path) -> None:
    # Breaks when any source tree, nested file, or suppression after the first is lost.
    text = f"pass  {COMMENT} noqa: S310"
    paths = [
        _write(tmp_path, f"{tree}/nested/sample.py", f"{text}\n{text}\n")
        for tree in ("relay", "gates", "tests")
    ]
    findings = scan(tmp_path, ["lint"])
    assert {(item.path, item.line, item.gate, item.text) for item in findings} == {
        (path, line, "lint", text) for path in paths for line in (1, 2)
    }
    assert len(findings) == 6


def test_scan_ignores_files_outside_its_documented_scope(tmp_path: Path) -> None:
    # Breaks when non-Python files or unrelated directories are audited.
    text = f"pass  {COMMENT} noqa: S310\n"
    for relative in ("relay/readme.txt", "gates/data.toml", "other/sample.py", "top.py"):
        _write(tmp_path, relative, text)
    assert scan(tmp_path, ["lint"]) == []


def test_lint_config_entries_require_individual_same_line_records(tmp_path: Path) -> None:
    # Breaks when a table-level or adjacent approval authorizes another config entry.
    unapproved = '"relay/bad.py" = ["S310"]'
    path = _write(
        tmp_path,
        "pyproject.toml",
        "[tool.ruff.lint.per-file-ignores]\n"
        f'"relay/good.py" = ["S310"]  {COMMENT} {RECORD}\n'
        f"{unapproved}\n",
    )
    assert scan(tmp_path, ["lint"]) == [Finding(path, 3, "lint", unapproved)]


@pytest.mark.parametrize(
    ("table", "entry"),
    [
        ("tool", 'ruff = { lint = { per-file-ignores = { "relay/sample.py" = ["S310"] } } }'),
        ("tool.ruff", 'lint = { per-file-ignores = { "relay/sample.py" = ["S310"] } }'),
    ],
)
def test_nested_inline_lint_exemptions_require_same_line_records(
    tmp_path: Path, table: str, entry: str
) -> None:
    # Breaks when nesting an exemption inside inline tables bypasses the audit.
    path = _write(tmp_path, "pyproject.toml", f"[{table}]\n{entry}\n")
    assert scan(tmp_path, ["lint"]) == [Finding(path, 2, "lint", entry)]


def test_only_the_designated_tests_profile_is_exempt(tmp_path: Path) -> None:
    # Breaks when the tests profile is flagged or its exception spreads to other keys.
    unapproved = '"relay/**" = ["S101"]'
    path = _write(
        tmp_path,
        "pyproject.toml",
        f'[tool.ruff.lint.per-file-ignores]\n"tests/**" = ["S101"]\n{unapproved}\n',
    )
    assert scan(tmp_path, ["lint"]) == [Finding(path, 3, "lint", unapproved)]


def test_mypy_override_entries_are_type_exemptions(tmp_path: Path) -> None:
    # Breaks when array-table overrides are skipped or assigned to the wrong gate.
    unapproved = "ignore_errors = true"
    path = _write(
        tmp_path,
        "pyproject.toml",
        f'[[tool.mypy.overrides]]\nmodule = "relay.sample"  {COMMENT} {RECORD}\n{unapproved}\n',
    )
    assert scan(tmp_path, ["types"]) == [Finding(path, 3, "types", unapproved)]


@pytest.mark.parametrize(
    ("table", "entry"),
    [
        ("tool.coverage.run", 'omit = ["relay/sample.py"]'),
        ("tool.coverage.report", 'exclude_lines = ["unreachable"]'),
    ],
)
def test_coverage_exclusions_require_records(tmp_path: Path, table: str, entry: str) -> None:
    # Breaks when coverage omit or exclude_lines entries escape the test gate audit.
    path = _write(tmp_path, "pyproject.toml", f"[{table}]\n{entry}\n")
    assert scan(tmp_path, ["test"]) == [Finding(path, 2, "test", entry)]


def test_config_approval_and_gate_filtering_apply_to_coverage(tmp_path: Path) -> None:
    # Breaks when valid config records are rejected or inactive config gates audited.
    _write(
        tmp_path,
        "pyproject.toml",
        f'[tool.coverage.run]\nomit = ["relay/a.py"]  {COMMENT} {RECORD}\n'
        '[tool.coverage.report]\nexclude_lines = ["unreachable"]\n',
    )
    assert scan(tmp_path, ["lint"]) == []
    findings = scan(tmp_path, ["test"])
    assert [(item.line, item.gate) for item in findings] == [(4, "test")]


def test_gate_configuration_itself_is_not_an_exemption(tmp_path: Path) -> None:
    # Breaks when ordinary tool settings or the lint profile are treated as suppressions.
    _write(
        tmp_path,
        "pyproject.toml",
        '[tool.ruff]\nline-length = 100\n[tool.ruff.lint]\nselect = ["ALL"]\n'
        'ignore = ["C90"]\n[tool.mypy]\nstrict = true\n'
        "[tool.coverage.report]\nfail_under = 0\n",
    )
    assert scan(tmp_path, ["format", "lint", "types", "test"]) == []


def test_main_prints_every_finding_and_returns_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when the CLI omits findings, uses another root, or reports success.
    monkeypatch.chdir(tmp_path)
    first = f"pass  {COMMENT} noqa: S310"
    second = f"pass  {COMMENT} noqa: BLE001"
    _write(tmp_path, "relay/sample.py", f"{first}\n{second}\n")
    assert main(["lint"]) == 1
    captured = capsys.readouterr()
    assert sorted(line.removeprefix(f"{tmp_path}/") for line in captured.out.splitlines()) == [
        f"relay/sample.py:1: lint: {first}",
        f"relay/sample.py:2: lint: {second}",
    ]
    assert captured.err == ""


def test_main_with_no_findings_returns_zero_and_prints_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when an inactive suppression fails the CLI or a clean audit emits findings.
    monkeypatch.chdir(tmp_path)
    _write(tmp_path, "relay/sample.py", f"pass  {COMMENT} noqa: S310\n")
    assert main(["types"]) == 0
    assert capsys.readouterr() == ("", "")


def test_main_defaults_to_process_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Breaks when main(None) ignores the gates named in process arguments.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["exemptions", "lint"])
    text = f"pass  {COMMENT} noqa: S310"
    _write(tmp_path, "tests/sample.py", text + "\n")
    assert main() == 1
    assert capsys.readouterr().out.removeprefix(f"{tmp_path}/") == (
        f"tests/sample.py:1: lint: {text}\n"
    )
