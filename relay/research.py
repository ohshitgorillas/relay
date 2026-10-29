"""The researcher's map: its format, caps, file, staleness and the follow-up answer."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from relay import git
from relay.config import Config
from relay.state import write_atomic

MAP_OPEN = "MAP"
LINKS = "LINKS"
MAP_CLOSE = "END MAP"
ANSWER_OPEN = "ANSWER"
ANSWER_CLOSE = "END ANSWER"

_SPAN = r"([^\s:|>]+):\d+(?:-\d+)?"
_ENTRY = re.compile(rf"{_SPAN} \| \S.*")
_LINK = re.compile(rf"{_SPAN} -> {_SPAN} \| \S.*")


@dataclass(frozen=True)
class Map:
    sid: str
    commit: str  # the HEAD Relay read in the research cwd before the researcher ran
    files: tuple[str, ...]  # every path an entry or link names, sorted, no repeats
    body: str  # the lines from MAP to END MAP, both included


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


def _files(lines: list[str]) -> tuple[str, ...] | None:
    """The sorted paths of a block's inner lines; None when a line fits neither form or no entry."""
    paths: set[str] = set()
    entries = 0
    in_links = False
    for line in lines[1:-1]:
        if line == LINKS and not in_links:
            in_links = True
            continue
        m = _LINK.fullmatch(line) if in_links else _ENTRY.fullmatch(line)
        if m is None:
            return None
        if not in_links:
            entries += 1
        paths.update(m.groups())
    return tuple(sorted(paths)) if entries else None


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
    """Write `map <sid> at <commit>` then m.body to `path` by temp file and os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, f"{_header(m.sid, m.commit)}\n{m.body}\n")


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
    lines = _last_block(rest, MAP_OPEN, MAP_CLOSE)
    return None if lines is None else _build(sid, commit, lines)


def stale(m: Map, cwd: Path) -> bool:
    """True unless git.changed(cwd, m.commit, m.files) is False."""
    return git.changed(cwd, m.commit, m.files) is not False


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
