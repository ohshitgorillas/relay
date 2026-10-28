"""Red tests for Relay's prompt and brief text (design: Modules `relay/prompts.py`; Order 11)."""

from __future__ import annotations

from pathlib import Path

from relay.prompts import lead_prompt, recut_brief
from relay.queue import Section

QUEUE = Path("/work/repo/docs/queue.md")
RETIRE_FLAG = Path("/state/relay/work-repo-docs-queue-md/runs/3.retire")
LEAD_LOG = Path("/state/relay/work-repo-docs-queue-md/runs/3.jsonl")

BODY = (
    "## Ledger recovery\n"
    "\n"
    "Depends on: s3\n"
    "\n"
    "- step 8a: red tests for `relay/ledger.py`\n"
    "- step 8b: build `relay/ledger.py`  (two spaces kept)\n"
    "\tTabbed line: \"quotes\" and {braces} and 100% verbatim\n"
)


def _section(sid: str = "s4", body: str = BODY) -> Section:
    return Section(id=sid, title="Ledger recovery", body=body, depends_on=("s3",), open=True)


def _lead(section: Section | None = None) -> str:
    return lead_prompt(QUEUE, section or _section(), resume=None, answer=None, retire_flag=RETIRE_FLAG)


# Behavior 3: `relay/prompts.py`: builds every text Relay sends to an agent.


def test_lead_prompt_opens_you_are_a_lead() -> None:
    # Breaks when: the lead prompt does not open with "You are a lead".
    assert _lead().startswith("You are a lead")


def test_recut_brief_is_a_text_for_the_divvyer_recut() -> None:
    # Breaks when: recut_brief does not name the divvyer's `recut` step.
    brief = recut_brief(QUEUE, _section(), "three modules, not one step", LEAD_LOG)
    assert isinstance(brief, str)
    assert "recut" in brief


# Behavior 4: Holds: the queue path, the section id and body verbatim,


def test_lead_prompt_holds_the_queue_path() -> None:
    # Breaks when: the lead prompt leaves out the queue's path.
    assert str(QUEUE) in _lead()


def test_lead_prompt_holds_the_section_id() -> None:
    # Breaks when: the lead prompt leaves out the section id.
    assert "s4" in _lead()


def test_lead_prompt_holds_the_section_body_verbatim() -> None:
    # Breaks when: the body is reflowed, stripped, re-indented or escaped instead of kept verbatim.
    assert BODY in _lead()


def test_lead_prompt_holds_the_given_section_not_another() -> None:
    # Breaks when: the prompt is built from a fixed or cached section rather than the one passed.
    other_body = "## Ping\n\nWire `relay/ping.py` to claude-ping.\n"
    prompt = _lead(_section(sid="s9", body=other_body))
    assert "s9" in prompt
    assert other_body in prompt
    assert BODY not in prompt


def test_lead_prompt_holds_resume_with_the_session_id_when_resume_is_set() -> None:
    # Breaks when: lead_prompt ignores `resume` or words it other than "resume <session id>".
    prompt = lead_prompt(QUEUE, _section(), resume="sess-lead-7", answer=None, retire_flag=RETIRE_FLAG)
    assert "resume sess-lead-7" in prompt


def test_lead_prompt_holds_the_owners_answer_verbatim_when_set() -> None:
    # Breaks when: lead_prompt ignores `answer` or alters its text.
    answer = "Yes: ship it as `relay`.\n  Keep the old name as an alias."
    prompt = lead_prompt(QUEUE, _section(), resume=None, answer=answer, retire_flag=RETIRE_FLAG)
    assert answer in prompt


def test_lead_prompt_holds_the_retire_contract_with_the_flag_path() -> None:
    # Breaks when: the prompt leaves out the retire flag's path or the instruction to end with RETIRED.
    prompt = _lead()
    assert str(RETIRE_FLAG) in prompt
    assert "RETIRED" in prompt


def test_lead_prompt_states_the_four_status_forms() -> None:
    # Breaks when: the status contract is left out or a form is worded otherwise (e.g. "FINISHED").
    prompt = _lead()
    assert "DONE" in prompt
    assert "RECUT: " in prompt
    assert "NEEDS-OWNER: " in prompt
    assert "RETIRED" in prompt


# Behavior 5: The divvyer's `recut` brief for that section, carrying the lead's reason and
# its run log path.


def test_recut_brief_names_the_section_id() -> None:
    # Breaks when: the recut brief does not say which section to recut.
    brief = recut_brief(QUEUE, _section(sid="s7"), "three modules, not one step", LEAD_LOG)
    assert "s7" in brief


def test_recut_brief_carries_the_leads_reason() -> None:
    # Breaks when: the lead's RECUT reason is dropped or altered in the brief.
    reason = "three modules, not one step: split stream from runner"
    brief = recut_brief(QUEUE, _section(), reason, LEAD_LOG)
    assert reason in brief


def test_recut_brief_carries_the_lead_run_log_path() -> None:
    # Breaks when: the lead's run log path is left out of the brief.
    brief = recut_brief(QUEUE, _section(), "three modules, not one step", LEAD_LOG)
    assert str(LEAD_LOG) in brief
