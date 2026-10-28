"""Red tests for Relay's prompt and brief text (design: Modules `relay/prompts.py`; Order 11)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from relay.check import CheckResult
from relay.config import Config
from relay.prompts import ask_brief, check_feedback, lead_prompt, recut_brief, research_brief
from relay.queue import Section
from tests.conftest import FIXTURES

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


# Check design (docs/superpowers/specs/relay-check-design.md, Modules `relay/prompts.py`;
# Order 5). Behavior 7: As now, plus, when check_feedback is set:

CHECK_SENTENCE = (
    "Relay ran this section's check after your DONE and it failed. "
    "Fix the section and end with DONE again:"
)
FEEDBACK = (
    "make check\nexit 2\n/state/relay/work-repo-docs-queue-md/runs/3.check\n"
    "FAILED tests/test_x.py::test_y - AssertionError\n  indented {braces} 100%\n"
)
CHECK_LOG = Path("/state/relay/work-repo-docs-queue-md/runs/3.check")
CHECK_TAIL = "FAILED tests/test_x.py::test_y - AssertionError\n== 1 failed ==\n"


def _with_feedback(feedback: str | None = FEEDBACK) -> str:
    return lead_prompt(
        QUEUE,
        _section(),
        resume="sess-lead-7",
        answer=None,
        retire_flag=RETIRE_FLAG,
        check_feedback=feedback,
    )


def test_lead_prompt_with_check_feedback_says_the_check_failed() -> None:
    # Breaks when: the check-failed instruction is left out or worded otherwise.
    assert CHECK_SENTENCE in _with_feedback()


def test_lead_prompt_without_check_feedback_leaves_the_check_sentence_out() -> None:
    # Breaks when: the check-failed instruction is written though check_feedback is None,
    # passed or left at its default.
    assert CHECK_SENTENCE not in _with_feedback(None)
    assert "check after your DONE" not in _with_feedback(None)
    assert CHECK_SENTENCE not in _lead()
    assert "check after your DONE" not in _lead()


def test_lead_prompt_carries_the_check_feedback_verbatim() -> None:
    # Breaks when: the feedback is dropped, stripped, re-indented or escaped.
    assert FEEDBACK in _with_feedback()


def test_lead_prompt_puts_the_feedback_after_the_instruction() -> None:
    # Breaks when: the feedback comes before the sentence that introduces it.
    prompt = _with_feedback()
    start = prompt.find(CHECK_SENTENCE)
    assert start != -1
    assert prompt.find(FEEDBACK, start + len(CHECK_SENTENCE)) != -1


def test_lead_prompt_with_check_feedback_keeps_everything_else() -> None:
    # Breaks when: setting check_feedback replaces the prompt instead of adding to it.
    prompt = _with_feedback()
    assert FEEDBACK in prompt
    assert prompt.startswith("You are a lead")
    assert str(QUEUE) in prompt
    assert BODY in prompt
    assert "resume sess-lead-7" in prompt
    assert str(RETIRE_FLAG) in prompt
    for form in ("DONE", "RECUT: ", "NEEDS-OWNER: ", "RETIRED"):
        assert form in prompt


# Behavior 8: the log path and the tail, for the lead.


def _check_result(**changes: object) -> CheckResult:
    if changes.get("timed_out") and "timeout" not in changes:
        changes["timeout"] = 1800.0
    result = CheckResult(
        command="uv run pytest tests/test_x.py",
        exit_code=1,
        timed_out=False,
        tail=CHECK_TAIL,
        log=CHECK_LOG,
        verdict="fail",
    )
    return dataclasses.replace(result, **changes)


def test_check_feedback_holds_the_command() -> None:
    # Breaks when: the failing command is left out of the lead's feedback.
    assert "uv run pytest tests/test_x.py" in check_feedback(_check_result())


def test_check_feedback_holds_the_exit_code() -> None:
    # Breaks when: the exit is left out or not worded "exit <n>".
    assert "exit 1" in check_feedback(_check_result())


def test_check_feedback_holds_the_log_path() -> None:
    # Breaks when: the check log's path is left out.
    assert str(CHECK_LOG) in check_feedback(_check_result())


def test_check_feedback_holds_the_tail() -> None:
    # Breaks when: the end of the failing command's output is left out or altered.
    assert CHECK_TAIL.rstrip("\n") in check_feedback(_check_result())


def test_check_feedback_for_a_timeout_says_timed_out() -> None:
    # Breaks when: a timed-out check is worded "exit None" instead of "timed out", or
    # not as outcome_text's "timed out after <s>s" with the result's timeout written %g.
    text = check_feedback(_check_result(exit_code=None, timed_out=True))
    assert "timed out" in text
    assert "exit None" not in text
    assert "timed out after 1800s" in text
    short = check_feedback(_check_result(exit_code=None, timed_out=True, timeout=0.5))
    assert "timed out after 0.5s" in short


# Research design (docs/superpowers/specs/relay-research-design.md, Modules `relay/prompts.py`
# and Homes; Order 5).

RESEARCH_FLAG = Path("/state/relay/work-repo-docs-queue-md/runs/research-s4")
QUESTION = 'Where does `_research` read HEAD, and what "stale" means?\n  {braces} 100%'

# The researcher's map from `tests/fixtures/research-map.txt`, as the block a lead carries.
_MAP_TEXT = (FIXTURES / "research-map.txt").read_text()
MAP_BLOCK = (
    "map s4 at 0123456789abcdef0123456789abcdef01234567\n"
    + _MAP_TEXT[_MAP_TEXT.index("MAP\n") : _MAP_TEXT.index("END MAP") + len("END MAP")]
)
MAP_SENTENCE = (
    "Relay's researcher mapped this section's code. "
    "Put the block below verbatim in every brief you send for this section, the architect's included."
)
MAP_ROUTE = "and pass on its answer; no agent searches for it."


def _capped(cfg: Config) -> Config:
    return dataclasses.replace(cfg, map_max_lines=137, map_max_chars=9876)


# Behavior 1: Lead-facing map wording, research and ask briefs


def test_research_brief_is_a_text(fake_cfg: Config) -> None:
    # Breaks when: research_brief builds no brief text for the researcher.
    brief = research_brief(QUEUE, _section(), RESEARCH_FLAG, fake_cfg)
    assert isinstance(brief, str)
    assert brief.strip() != ""


def test_ask_brief_is_a_text(fake_cfg: Config) -> None:
    # Breaks when: ask_brief builds no brief text for the follow-up.
    brief = ask_brief(QUESTION, RESEARCH_FLAG, fake_cfg)
    assert isinstance(brief, str)
    assert brief.strip() != ""


# Behavior 2: As now, plus, when map_block is set


def _with_map(map_block: str | None = MAP_BLOCK) -> str:
    return lead_prompt(
        QUEUE,
        _section(),
        resume="sess-lead-7",
        answer=None,
        retire_flag=RETIRE_FLAG,
        map_block=map_block,
    )


def test_lead_prompt_with_a_map_says_put_it_in_every_brief() -> None:
    # Breaks when: the map's usage rule for the lead is left out or worded otherwise.
    assert MAP_SENTENCE in _with_map()


def test_lead_prompt_with_a_map_routes_needs_through_relay_ask() -> None:
    # Breaks when: the lead is not told to run `relay ask` and pass the answer on.
    prompt = _with_map()
    assert "When an agent reports it needs more, run `relay ask " in prompt
    assert MAP_ROUTE in prompt


def test_lead_prompt_carries_the_map_block_verbatim() -> None:
    # Breaks when: the map block is dropped, stripped, re-indented or escaped.
    assert MAP_BLOCK in _with_map()


def test_lead_prompt_puts_the_map_block_after_its_wording() -> None:
    # Breaks when: the block comes before the sentence that introduces it.
    prompt = _with_map()
    start = prompt.find(MAP_SENTENCE)
    assert start != -1
    assert prompt.find(MAP_BLOCK, start + len(MAP_SENTENCE)) != -1


def test_lead_prompt_without_a_map_leaves_the_map_wording_out() -> None:
    # Breaks when: the map wording is written though map_block is None or left at its
    # default, or is never written at all.
    assert MAP_SENTENCE in _with_map()
    assert MAP_SENTENCE not in _with_map(None)
    assert "relay ask" not in _with_map(None)
    assert MAP_SENTENCE not in _lead()
    assert "relay ask" not in _lead()


def test_lead_prompt_with_a_map_keeps_everything_else() -> None:
    # Breaks when: setting map_block replaces the prompt instead of adding to it.
    prompt = _with_map()
    assert MAP_BLOCK in prompt
    assert prompt.startswith("You are a lead")
    assert str(QUEUE) in prompt
    assert BODY in prompt
    assert "resume sess-lead-7" in prompt
    assert str(RETIRE_FLAG) in prompt
    for form in ("DONE", "RECUT: ", "NEEDS-OWNER: ", "RETIRED"):
        assert form in prompt


# Behavior 3: The queue path, the section id and body, the caps cfg.map_max_lines and
# cfg.map_max_chars, the MAP / LINKS / END MAP form, and the flag sentence.


def _research(cfg: Config, section: Section | None = None) -> str:
    return research_brief(QUEUE, section or _section(), RESEARCH_FLAG, _capped(cfg))


def test_research_brief_holds_the_queue_path(fake_cfg: Config) -> None:
    # Breaks when: the research brief leaves out the queue's path.
    assert str(QUEUE) in _research(fake_cfg)


def test_research_brief_holds_the_section_id_and_body_verbatim(fake_cfg: Config) -> None:
    # Breaks when: the section id is left out, or the body is reflowed, stripped or escaped.
    brief = _research(fake_cfg)
    assert "s4" in brief
    assert BODY in brief


def test_research_brief_holds_the_given_section_not_another(fake_cfg: Config) -> None:
    # Breaks when: the brief is built from a fixed or cached section rather than the one passed.
    other_body = "## Ping\n\nWire `relay/ping.py` to claude-ping.\n"
    brief = _research(fake_cfg, _section(sid="s9", body=other_body))
    assert "s9" in brief
    assert other_body in brief
    assert BODY not in brief


def test_research_brief_holds_the_line_cap_from_config(fake_cfg: Config) -> None:
    # Breaks when: the line cap is left out or fixed rather than read from cfg.map_max_lines.
    assert "137" in _research(fake_cfg)


def test_research_brief_holds_the_char_cap_from_config(fake_cfg: Config) -> None:
    # Breaks when: the character cap is left out or fixed rather than read from cfg.map_max_chars.
    assert "9876" in _research(fake_cfg)


def test_research_brief_states_the_map_form(fake_cfg: Config) -> None:
    # Breaks when: the MAP, LINKS or END MAP line of the map's form is left out.
    lines = _research(fake_cfg).splitlines()
    assert "MAP" in lines
    assert "LINKS" in lines
    assert "END MAP" in lines


def test_research_brief_holds_the_flag_rule(fake_cfg: Config) -> None:
    # Breaks when: the flag sentence is left out, worded otherwise or names another path.
    sentence = f"When the file {RESEARCH_FLAG} exists, send no more readers and return the map you have."
    assert sentence in _research(fake_cfg)


# Behavior 4: The question, the ANSWER / END ANSWER form, the cap cfg.map_max_chars, the flag rule.


def _ask(cfg: Config, question: str = QUESTION) -> str:
    return ask_brief(question, RESEARCH_FLAG, _capped(cfg))


def test_ask_brief_holds_the_question_verbatim(fake_cfg: Config) -> None:
    # Breaks when: the question is dropped, stripped, re-indented or escaped.
    assert QUESTION in _ask(fake_cfg)


def test_ask_brief_holds_the_given_question_not_another(fake_cfg: Config) -> None:
    # Breaks when: the brief is built from a fixed or cached question rather than the one passed.
    brief = _ask(fake_cfg, "Which test covers `relay ask`?")
    assert "Which test covers `relay ask`?" in brief
    assert QUESTION not in brief


def test_ask_brief_states_the_answer_form(fake_cfg: Config) -> None:
    # Breaks when: the ANSWER or END ANSWER line of the answer's form is left out.
    lines = _ask(fake_cfg).splitlines()
    assert "ANSWER" in lines
    assert "END ANSWER" in lines


def test_ask_brief_holds_the_char_cap_from_config(fake_cfg: Config) -> None:
    # Breaks when: the character cap is left out or fixed rather than read from cfg.map_max_chars.
    assert "9876" in _ask(fake_cfg)


def test_ask_brief_holds_the_flag_rule(fake_cfg: Config) -> None:
    # Breaks when: the flag rule is left out or names another path than the research flag.
    brief = _ask(fake_cfg)
    assert f"When the file {RESEARCH_FLAG} exists" in brief
    assert "send no more readers" in brief
