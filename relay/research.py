"""The researcher's map: its format, caps, file, staleness and the follow-up answer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from relay.config import Config

MAP_OPEN = "MAP"
LINKS = "LINKS"
MAP_CLOSE = "END MAP"
ANSWER_OPEN = "ANSWER"
ANSWER_CLOSE = "END ANSWER"


@dataclass(frozen=True)
class Map:
    sid: str
    commit: str  # the HEAD Relay read in the research cwd before the researcher ran
    files: tuple[str, ...]  # every path an entry or link names, sorted, no repeats
    body: str  # the lines from MAP to END MAP, both included


def parse_map(sid: str, commit: str, result_text: str | None, cfg: Config) -> Map | None:
    """The last MAP ... END MAP block of result_text, or None when absent, malformed or over the caps."""
    raise NotImplementedError


def save(m: Map, path: Path) -> None:
    """Write `map <sid> at <commit>` then m.body to `path` by temp file and os.replace."""
    raise NotImplementedError


def load(path: Path, sid: str) -> Map | None:
    """The map saved at `path`; None when missing, unreadable, another section's or unparsable."""
    raise NotImplementedError


def stale(m: Map, cwd: Path) -> bool:
    """True unless git.changed(cwd, m.commit, m.files) is False."""
    raise NotImplementedError


def block(m: Map) -> str:
    """The text every brief in the section carries verbatim."""
    raise NotImplementedError


def parse_answer(result_text: str | None, cfg: Config) -> str | None:
    """The last ANSWER ... END ANSWER block; None when absent or over cfg.map_max_chars."""
    raise NotImplementedError
