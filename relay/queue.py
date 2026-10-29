"""Parse the divvyer's .md queue; queue authorship belongs to leads and the divvyer.

Relay's sole write exception is restoring exact pre-invocation queue bytes and
permissions after a failed recut, through the transaction in relay.loop.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from relay.errors import QueueFormatError


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    body: str
    depends_on: tuple[str, ...]
    open: bool


_HEADER = re.compile(r"^section[ \t]+([A-Za-z0-9][A-Za-z0-9._-]*)[ \t]*\|(.*)$")
_DEPENDS = re.compile(r"^depends(?:[ _-]on)?:\s*(.*)$", re.IGNORECASE)
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def parse_queue(path: Path) -> list[Section]:
    """Sections start at a column-0 `section <id> | ...` line and run to the next."""
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise QueueFormatError(f"cannot read queue {path}: {exc}") from exc
    chunks: list[tuple[str, str, list[str]]] = []
    fenced = False
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
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
        for field in (f.strip() for f in title.split("|")):
            d = _DEPENDS.match(field)
            if d:
                deps += [x.strip() for x in d.group(1).split(",") if x.strip()]
            elif field.lower() in ("done", "status: done"):
                is_open = False
            else:
                kept.append(field)
        title = " | ".join(kept)
        for dep in deps:
            if not _ID.match(dep):
                raise QueueFormatError(f"section {sid}: bad dependency {dep!r}")
        sections.append(
            Section(sid, title, "\n".join(body_lines), tuple(deps), is_open)
        )
    ids = {x.id for x in sections}
    for x in sections:
        for dep in x.depends_on:
            if dep not in ids:
                raise QueueFormatError(f"section {x.id} depends on unknown {dep}")
    if not sections:
        raise QueueFormatError(f"no sections in {path}")
    return sections


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
