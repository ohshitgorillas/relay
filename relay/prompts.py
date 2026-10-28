"""Builds every text Relay sends to an agent."""

from pathlib import Path
from typing import TYPE_CHECKING

from relay.check import outcome_text
from relay.queue import Section
from relay.status import KINDS, Kind, TEXT_NAMES

if TYPE_CHECKING:
    from relay.check import CheckResult


def _status_form(kind: Kind) -> str:
    return f"{kind}: <{TEXT_NAMES[kind]}>" if kind in TEXT_NAMES else kind


def lead_prompt(
    queue: Path,
    section: Section,
    resume: str | None,
    answer: str | None,
    retire_flag: Path,
    check_feedback: str | None = None,
) -> str:
    parts = [
        "You are a lead. Carry the queue section below through development until it is done.",
        f"Queue: {queue}\nSection: {section.id}",
        f"Section body:\n{section.body}",
    ]
    if resume is not None:
        parts.append(f"resume {resume}")
    if answer is not None:
        parts.append(f"The owner's answer to your earlier question:\n{answer}")
    if check_feedback is not None:
        parts.append(
            "Relay ran this section's check after your DONE and it failed. "
            "Fix the section and end with DONE again:\n" + check_feedback
        )
    parts.append(
        "Retire contract: on reaching a safe point, after a step's commit, check whether "
        f"the file {retire_flag} exists. If it exists, stop and end with RETIRED. "
        "A session grown heavy, past about 100k tokens of context, also stops at its "
        "next safe point and ends with RETIRED, never RECUT: Relay starts a fresh lead "
        "on the same section, which resumes from this session. RECUT is only for a "
        "section whose cut is wrong or too big."
    )
    parts.append(
        "Status contract: the last line of your final message is exactly one of these, "
        "and nothing follows it:\n" + "\n".join(_status_form(kind) for kind in KINDS)
    )
    return "\n\n".join(parts) + "\n"


def recut_brief(queue: Path, section: Section, reason: str, lead_log: Path) -> str:
    return (
        f"recut section {section.id} of the queue at {queue}.\n\n"
        f"A lead asked for this recut. Its reason: {reason}\n"
        f"The lead's run log: {lead_log}\n\n"
        f"Section body:\n{section.body}\n"
    )


def check_feedback(result: "CheckResult") -> str:
    return f"{result.command}\n{outcome_text(result)}\n{result.log}\n{result.tail.rstrip(chr(10))}\n"
