"""Builds every text Relay sends to an agent."""

from pathlib import Path

from relay.queue import Section


def lead_prompt(
    queue: Path,
    section: Section,
    resume: str | None,
    answer: str | None,
    retire_flag: Path,
) -> str:
    raise NotImplementedError


def recut_brief(queue: Path, section: Section, reason: str, lead_log: Path) -> str:
    raise NotImplementedError
