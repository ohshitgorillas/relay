"""Parses the divvyer's .md queue into sections. Relay never writes the queue."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    body: str
    depends_on: tuple[str, ...]
    open: bool


def parse_queue(path: Path) -> list[Section]:
    raise NotImplementedError


def blocked_by(sections: list[Section], parked: set[str]) -> set[str]:
    raise NotImplementedError
