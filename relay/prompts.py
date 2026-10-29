"""Builds every text Relay sends to an agent."""

from pathlib import Path

from relay.queue import Section
from relay.status import Kind, TEXT_NAMES


def _status_form(kind: Kind) -> str:
    return f"{kind}: <{TEXT_NAMES[kind]}>" if kind in TEXT_NAMES else kind


def lead_prompt(
    queue: Path,
    section: Section,
    resume: str | None,
    report: str | None,
    answer: str | None,
    retire_flag: Path,
    *,
    handoff_hint: str | None = None,
) -> str:
    raise NotImplementedError


def recut_brief(queue: Path, section: Section, reason: str, lead_log: Path) -> str:
    return (
        f"recut section {section.id} of the queue at {queue}.\n\n"
        f"A lead asked for this recut. Its reason: {reason}\n"
        f"The lead's run log: {lead_log}\n\n"
        f"Section body:\n{section.body}\n"
    )
