"""Parse the divvyer's .md queue; queue authorship belongs to leads and the divvyer.

Relay's sole write exception is restoring exact pre-invocation queue bytes and
permissions after a failed recut, through the transaction in relay.loop.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path

from relay.errors import QueueFormatError


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    body: str
    depends_on: tuple[str, ...]
    open: bool
    checks: tuple[str, ...] = ()
    came_from: str | None = None
    steps: tuple[str, ...] = ()
    dollar_cap: float | None = None


_HEADER = re.compile(r"^section[ \t]+([A-Za-z0-9][A-Za-z0-9._-]*)[ \t]*\|(.*)$")
_DEPENDS = re.compile(r"^depends(?:[ _-]on)?:\s*(.*)$", re.IGNORECASE)
_CHECK = re.compile(r"^\s*(?:done-)?check:\s*(\S.*?)\s*$", re.IGNORECASE)
_FROM = re.compile(r"^from:\s*(.*)$", re.IGNORECASE)
_STEPS = re.compile(r"^steps:\s*(.*)$", re.IGNORECASE)
_CAP = re.compile(r"^cap:\s*(.*)$", re.IGNORECASE)
_CAP_VALUE = re.compile(r"^\$?(\d+(?:\.\d*)?|\.\d+)$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _fence_states(lines: list[str]) -> Iterator[tuple[str, bool]]:
    """Yield each line with whether it sits on or inside a ``` / ~~~ fence."""
    fenced = False
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        yield line, fenced


def _read_lines(path: Path) -> list[str]:
    """The one reader of the queue file: every caller reads and fails the same way."""
    try:
        return path.read_text().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise QueueFormatError(f"cannot read queue {path}: {exc}") from exc


def parse_queue(path: Path) -> list[Section]:
    """Sections start at a column-0 `section <id> | ...` line and run to the next."""
    lines = _read_lines(path)
    chunks: list[tuple[str, str, list[str]]] = []
    for line, fenced in _fence_states(lines):
        m = None if fenced else _HEADER.match(line)
        if m:
            title = m.group(2).strip()
            chunks.append((m.group(1), title, [line]))
        elif chunks:
            chunks[-1][2].append(line)
    sections: list[Section] = []
    seen: set[str] = set()
    for sid, title, body_lines in chunks:
        if sid in seen:
            raise QueueFormatError(f"duplicate section id {sid} in {path}")
        seen.add(sid)
        # Only the header line's `|` fields carry markers: `depends: a, b`, `done`.
        deps: list[str] = []
        is_open = True
        kept: list[str] = []
        came_from: str | None = None
        steps: tuple[str, ...] = ()
        dollar_cap: float | None = None
        for field in (f.strip() for f in title.split("|")):
            d = _DEPENDS.match(field)
            if d:
                deps += [x.strip() for x in d.group(1).split(",") if x.strip()]
            elif (f := _FROM.match(field)) is not None:
                came_from = f.group(1).strip()
                if not _ID.match(came_from):
                    raise QueueFormatError(f"section {sid}: bad from id {came_from!r}")
            elif (c := _CAP.match(field)) is not None:
                m = _CAP_VALUE.match(c.group(1).strip())
                dollar_cap = float(m.group(1)) if m else 0.0
                if dollar_cap <= 0:
                    raise QueueFormatError(
                        f"section {sid}: bad cap {c.group(1).strip()!r}, want a positive number"
                    )
            elif field.lower() in ("done", "status: done"):
                is_open = False
            else:
                if (st := _STEPS.match(field)) is not None:
                    steps = tuple(x.strip() for x in st.group(1).split(",") if x.strip())
                kept.append(field)
        title = " | ".join(kept)
        for dep in deps:
            if not _ID.match(dep):
                raise QueueFormatError(f"section {sid}: bad dependency {dep!r}")
        checks: list[str] = []
        for line, fenced in _fence_states(body_lines):
            if not fenced and (c := _CHECK.match(line)):
                checks.append(c.group(1))
        sections.append(
            Section(
                sid,
                title,
                "\n".join(body_lines),
                tuple(deps),
                is_open,
                tuple(checks),
                came_from,
                steps,
                dollar_cap,
            )
        )
    ids = {x.id for x in sections}
    for x in sections:
        for dep in x.depends_on:
            if dep not in ids:
                raise QueueFormatError(f"section {x.id} depends on unknown {dep}")
    if not sections:
        raise QueueFormatError(f"no sections in {path}")
    return sections


def same_entry(a: Section, b: Section) -> bool:
    """True when two parses of a section differ at most in the blank lines that trail its body."""
    return replace(a, body=a.body.rstrip()) == replace(b, body=b.body.rstrip())


def blocked_by(sections: list[Section], parked: set[str]) -> set[str]:
    """Ids that depend, transitively, on a parked id."""
    blocked: set[str] = set()
    changed = True
    while changed:
        changed = False
        for s in sections:
            if s.id not in blocked and any(
                d in parked or d in blocked for d in s.depends_on
            ):
                blocked.add(s.id)
                changed = True
    return blocked


def queue_design(path: Path) -> str | None:
    """The path after `design ` on the queue's first non-blank line, when that line starts
    `design ` and comes before the first section, up to the first ` | ` or the end of the line; None otherwise."""
    lines = _read_lines(path)
    for line in lines:
        if not line.strip():
            continue
        if not line.startswith("design "):
            return None
        return line[len("design ") :].split(" | ", 1)[0].strip() or None
    return None
