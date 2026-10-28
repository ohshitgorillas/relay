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
    parts = [
        "You are a lead. Carry the queue section below through development until it is done.",
        f"Queue: {queue}\nSection: {section.id}",
        f"Section body:\n{section.body}",
    ]
    if resume:
        parts.append(f"resume {resume}")
    if answer:
        parts.append(f"The owner's answer to your earlier question:\n{answer}")
    parts.append(
        "Retire contract: on reaching a safe point, after a step's commit, check whether "
        f"the file {retire_flag} exists. If it exists, stop and end with RETIRED."
    )
    parts.append(
        "Status contract: the last line of your final message is exactly one of these, "
        "and nothing follows it:\n"
        "DONE\n"
        "RECUT: <reason>\n"
        "NEEDS-OWNER: <question>\n"
        "RETIRED"
    )
    return "\n\n".join(parts) + "\n"


def recut_brief(queue: Path, section: Section, reason: str, lead_log: Path) -> str:
    return (
        f"recut section {section.id} of the queue at {queue}.\n\n"
        f"A lead asked for this recut. Its reason: {reason}\n"
        f"The lead's run log: {lead_log}\n\n"
        f"Section body:\n{section.body}\n"
    )
