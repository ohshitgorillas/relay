"""The researcher's map: its format, caps, file, staleness and the follow-up answer."""

from __future__ import annotations

import hashlib
import re
import stat
from dataclasses import dataclass, replace
from pathlib import Path

from relay.config import Config
from relay.state import queue_id, write_atomic

MAP_OPEN = "MAP"
LINKS = "LINKS"
MAP_CLOSE = "END MAP"
ANSWER_OPEN = "ANSWER"
ANSWER_CLOSE = "END ANSWER"
UNKNOWN = "-"

_SPAN = r"([^\s:|>]+):\d+(?:-\d+)?"
_ENTRY = re.compile(rf"{_SPAN} \| \S.*")
_LINK = re.compile(rf"{_SPAN} -> {_SPAN} \| \S.*")


@dataclass(frozen=True)
class Map:
    sid: str
    commit: str  # the HEAD Relay read in the research cwd before the researcher ran
    files: tuple[str, ...]  # every path an entry or link names, sorted, no repeats
    body: str  # the lines from MAP to END MAP, both included
    digests: tuple[str, ...] = ()  # one per files entry; () means none recorded
    queue: str | None = None


def owned(m: Map, queue: Path) -> bool:
    """Whether this map carries the queue's identity."""
    return m.queue == queue_id(queue)


def attribute(m: Map, queue: Path) -> Map:
    """Return this map with the queue's identity, retaining its content and digests."""
    return replace(m, queue=queue_id(queue))


def digest(cwd: Path, path: str) -> str:
    """sha256 hex of the file bytes, or UNKNOWN for an unreadable non-regular file."""
    target = cwd / path
    try:
        if not stat.S_ISREG(target.stat().st_mode):
            return UNKNOWN
        with target.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()
    except OSError:
        return UNKNOWN


def stamp(m: Map, cwd: Path, since_ns: int) -> Map:
    """Record each file's digest, or UNKNOWN if its mtime is at least since_ns."""
    values = []
    for path in m.files:
        value = digest(cwd, path)
        try:
            if (cwd / path).stat().st_mtime_ns >= since_ns:
                value = UNKNOWN
        except OSError:
            value = UNKNOWN
        values.append(value)
    return replace(m, digests=tuple(values))


def changed(m: Map, cwd: Path) -> frozenset[str]:
    """Files whose recorded digest is absent, UNKNOWN, or differs from their current digest."""
    return frozenset(
        path
        for i, path in enumerate(m.files)
        if i >= len(m.digests)
        or m.digests[i] == UNKNOWN
        or m.digests[i] != digest(cwd, path)
    )


def split(m: Map, changed: frozenset[str]) -> Map | None:
    """Keep unchanged entries and links with both ends unchanged; None if no entry remains."""
    parts = _parts(m.body.splitlines())
    if parts is None:
        return None
    entries, links = parts
    entries = [line for line in entries if _ENTRY.fullmatch(line)[1] not in changed]
    links = [
        line for line in links if not changed.intersection(_LINK.fullmatch(line).groups())
    ]
    kept = _build(m.sid, m.commit, _lines(entries, links))
    if kept is None:
        return kept
    kept = replace(kept, queue=m.queue)
    if not m.digests:
        return kept
    values = dict(zip(m.files, m.digests))
    return replace(kept, digests=tuple(values.get(path, UNKNOWN) for path in kept.files))


def parse_refresh(
    kept: Map, commit: str, changed: frozenset[str], result_text: str | None, cfg: Config
) -> Map | None:
    """Merge kept with the last refresh MAP block; None if malformed, overlapping or over caps."""
    lines = _last_block(result_text, MAP_OPEN, MAP_CLOSE)
    fresh_parts = None if lines is None else _parts(lines)
    kept_parts = _parts(kept.body.splitlines())
    if fresh_parts is None or kept_parts is None:
        return None
    entries, links = kept_parts
    fresh_entries, fresh_links = fresh_parts
    kept_paths = {_ENTRY.fullmatch(line)[1] for line in entries}
    if any(_ENTRY.fullmatch(line)[1] in kept_paths for line in fresh_entries):
        return None
    body = "\n".join(_lines(entries + fresh_entries, links + fresh_links))
    merged = parse_map(kept.sid, commit, body, cfg)
    return None if merged is None else replace(merged, queue=kept.queue)


def _last_block(text: str | None, opener: str, closer: str) -> list[str] | None:
    """The lines of the last block opened by a line `opener` and closed by a line `closer`."""
    found: list[str] | None = None
    start: int | None = None
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        if line == opener:
            start = i
        elif line == closer and start is not None:
            found = lines[start : i + 1]
            start = None
    return found


def _parts(lines: list[str]) -> tuple[list[str], list[str]] | None:
    """Validate a MAP block and separate entries and links, allowing no entries."""
    entries: list[str] = []
    links: list[str] = []
    in_links = False
    for line in lines[1:-1]:
        if line == LINKS and not in_links:
            in_links = True
            continue
        m = _LINK.fullmatch(line) if in_links else _ENTRY.fullmatch(line)
        if m is None:
            return None
        (links if in_links else entries).append(line)
    return entries, links


def _lines(entries: list[str], links: list[str]) -> list[str]:
    return [MAP_OPEN, *entries, *([LINKS, *links] if links else []), MAP_CLOSE]


def _files(lines: list[str]) -> tuple[str, ...] | None:
    """The sorted paths of a valid block with at least one entry."""
    parts = _parts(lines)
    if parts is None or not parts[0]:
        return None
    entries, links = parts
    paths = {_ENTRY.fullmatch(line)[1] for line in entries}
    for line in links:
        paths.update(_LINK.fullmatch(line).groups())
    return tuple(sorted(paths))


def _build(sid: str, commit: str, lines: list[str]) -> Map | None:
    files = _files(lines)
    if files is None:
        return None
    return Map(sid, commit, files, "\n".join(lines))


def _header(sid: str, commit: str) -> str:
    return f"map {sid} at {commit}"


def parse_map(sid: str, commit: str, result_text: str | None, cfg: Config) -> Map | None:
    """The last MAP ... END MAP block of result_text, or None when absent, malformed or over the caps."""
    lines = _last_block(result_text, MAP_OPEN, MAP_CLOSE)
    if lines is None or len(lines) > cfg.map_max_lines:
        return None
    m = _build(sid, commit, lines)
    if m is None or len(m.body) > cfg.map_max_chars:
        return None
    return m


def save(m: Map, path: Path) -> None:
    """Atomically write the map header, optional per-file digests, and body."""
    path.parent.mkdir(parents=True, exist_ok=True)
    records = "".join(
        f"file {value} {name}\n"
        for name, value in zip(m.files, m.digests, strict=bool(m.digests))
    )
    provenance = f"queue {m.queue}\n" if m.queue is not None else ""
    write_atomic(path, f"{_header(m.sid, m.commit)}\n{provenance}{records}{m.body}\n")


def load(path: Path, sid: str) -> Map | None:
    """The map saved at `path`; None when missing, unreadable, another section's or unparsable."""
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    head, _, rest = text.partition("\n")
    prefix = _header(sid, "")
    commit = head[len(prefix) :]
    if not head.startswith(prefix) or not commit or commit.split() != [commit]:
        return None
    records: dict[str, str] = {}
    body_lines = rest.splitlines()
    queue = None
    while body_lines and body_lines[0].startswith(("file", "queue")):
        record = body_lines.pop(0)
        if record.startswith("queue"):
            match = re.fullmatch(r"queue ([0-9a-f]{64})", record)
            if match is None or queue is not None or records:
                return None
            queue = match[1]
            continue
        match = re.fullmatch(r"file (-|[0-9a-f]{64}) ([^\s:|>]+)", record)
        if match is None or match[2] in records:
            return None
        records[match[2]] = match[1]
    lines = _last_block("\n".join(body_lines), MAP_OPEN, MAP_CLOSE)
    m = None if lines is None else _build(sid, commit, lines)
    if m is None:
        return m
    m = replace(m, queue=queue)
    if not records:
        return m
    if records.keys() != set(m.files):
        return None
    return replace(m, digests=tuple(records[name] for name in m.files))


def block(m: Map) -> str:
    """The text every brief in the section carries verbatim."""
    rule = (
        "Start from this map of the code, which Relay's researcher drew. Open a file it names "
        "only at the lines it gives. Needing more, say what in your report and do not search "
        "for it: the lead asks the researcher."
    )
    return f"{rule}\n\n{_header(m.sid, m.commit)}\n{m.body}\n"


def parse_answer(result_text: str | None, cfg: Config) -> str | None:
    """The last ANSWER ... END ANSWER block; None when absent or over cfg.map_max_chars."""
    lines = _last_block(result_text, ANSWER_OPEN, ANSWER_CLOSE)
    if lines is None:
        return None
    answer = "\n".join(lines)
    return answer if len(answer) <= cfg.map_max_chars else None
