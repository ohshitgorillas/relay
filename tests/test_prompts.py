"""Red tests for Relay's prompt and brief text (design: Modules `relay/prompts.py`; Order 11)."""

from __future__ import annotations

import dataclasses
import inspect
import re
from pathlib import Path

import pytest

from relay import git
from relay.check import CheckResult
from relay.config import Config
from relay.ladder import handback_text
from relay.prompts import (
    ask_brief,
    check_feedback,
    design_answer_brief,
    design_brief,
    design_retry_brief,
    lead_prompt,
    recut_brief,
    refresh_brief,
    research_brief,
)
from relay.queue import Section
from relay.research import Map, block
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
    return lead_prompt(QUEUE, section or _section(), resume=None, report=None, answer=None, retire_flag=RETIRE_FLAG)


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
    prompt = lead_prompt(QUEUE, _section(), resume="sess-lead-7", report=None, answer=None, retire_flag=RETIRE_FLAG)
    assert "resume sess-lead-7" in prompt


def test_lead_prompt_holds_the_owners_answer_verbatim_when_set() -> None:
    # Breaks when: lead_prompt ignores `answer` or alters its text.
    answer = "Yes: ship it as `relay`.\n  Keep the old name as an alias."
    prompt = lead_prompt(QUEUE, _section(), resume=None, report=None, answer=answer, retire_flag=RETIRE_FLAG)
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
        report=None,
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
# Codex architect design, Modules `relay/prompts.py` `lead_prompt`: the map paragraph says put
# the block verbatim in every brief for this section except an architect's, whose brief
# carries only its ruling lines.
MAP_RULE = "verbatim in every brief you send for this section except an architect's"
MAP_RULING_ONLY = "an architect brief carries only its ruling lines"
MAP_ROUTE = (
    f'When an agent reports it needs more, run `relay ask {QUEUE} s4 "<question>"` '
    "with a 600000 ms timeout or in the background, and pass on its answer; "
    "on a non-zero exit the agent reads for itself."
)


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
        report=None,
        answer=None,
        retire_flag=RETIRE_FLAG,
        map_block=map_block,
    )


def test_lead_prompt_with_a_map_routes_needs_through_relay_ask_and_keeps_the_map_out_of_architect_briefs() -> None:
    # Breaks when: the lead is not told to run `relay ask` with a 600000 ms timeout or in the
    # background, or the non-zero-exit fallback is left out, or the lead is still told to put
    # the map in the architect's brief, or is not told to put it in every other brief for the
    # section, or the routing sentence leaves its place between the map rule and the block.
    prompt = _with_map()
    assert MAP_ROUTE in prompt
    assert "the architect's included" not in prompt
    rule = prompt.find(MAP_RULE)
    route = prompt.find(MAP_ROUTE)
    assert rule != -1
    assert prompt.find(MAP_RULING_ONLY, rule + len(MAP_RULE)) != -1
    assert rule + len(MAP_RULE) <= route
    assert prompt.find(MAP_BLOCK, route + len(MAP_ROUTE)) != -1


def test_lead_prompt_carries_the_map_block_verbatim() -> None:
    # Breaks when: the map block is dropped, stripped, re-indented or escaped.
    assert MAP_BLOCK in _with_map()


def test_lead_prompt_puts_the_map_block_after_its_architect_excepting_wording() -> None:
    # Breaks when: the block comes before the map rule that introduces it, or that rule still
    # takes in the architect's brief.
    prompt = _with_map()
    start = prompt.find(MAP_RULE)
    assert start != -1
    ruling_only = prompt.find(MAP_RULING_ONLY, start)
    assert ruling_only != -1
    assert prompt.find(MAP_BLOCK, ruling_only + len(MAP_RULING_ONLY)) != -1


def test_lead_prompt_without_a_map_leaves_the_architect_excepting_map_wording_out() -> None:
    # Breaks when: the map wording is written though map_block is None or left at its
    # default, or is never written at all.
    assert MAP_RULE in _with_map()
    assert MAP_RULING_ONLY in _with_map()
    for prompt in (_with_map(None), _lead()):
        assert MAP_RULE not in prompt
        assert MAP_RULING_ONLY not in prompt
        assert "except an architect's" not in prompt
        assert "relay ask" not in prompt


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
    # The flag path here holds no section id, so the id can only come from the section.
    flag = Path("/state/relay/work-repo-docs-queue-md/runs/research-flag")
    assert "s4" not in str(flag)
    brief = research_brief(QUEUE, _section(), flag, _capped(fake_cfg))
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


# Research reuse design, Modules `relay/prompts.py`; Order 4.
def _kept_map() -> Map:
    body = MAP_BLOCK.split("\n", 1)[1]
    return Map(
        sid="s4",
        commit="0123456789abcdef0123456789abcdef01234567",
        files=("relay/git.py", "relay/loop.py", "relay/research.py"),
        body=body,
        digests=("a" * 64, "b" * 64, "c" * 64),
    )


def test_refresh_brief_carries_the_section_and_kept_block_without_digests(fake_cfg: Config) -> None:
    # Breaks when: refresh drops or alters the section or retained block, or leaks file digests.
    kept = _kept_map()
    brief = refresh_brief(QUEUE, _section(), kept, ("relay/prompts.py",), RESEARCH_FLAG, fake_cfg)
    assert BODY in brief
    assert block(kept) in brief
    for digest in kept.digests:
        assert digest not in brief


def test_refresh_brief_lists_changed_paths_sorted(fake_cfg: Config) -> None:
    # Breaks when: changed paths are omitted or retain caller order rather than sorted order.
    changed = ("relay/zebra.py", "relay/alpha.py", "relay/middle.py")
    brief = refresh_brief(QUEUE, _section(), _kept_map(), changed, RESEARCH_FLAG, fake_cfg)
    positions = [brief.index(path) for path in sorted(changed)]
    assert positions == sorted(positions)


def test_refresh_brief_limits_mapping_to_changed_section_code_and_allows_new_paths(fake_cfg: Config) -> None:
    # Design: relay-research-reuse-design.md:85-90 makes these exact scope sentences contractual.
    # Breaks when: refresh alters or omits any of the three scope instruction sentences.
    brief = refresh_brief(
        QUEUE, _section(), _kept_map(), ("relay/prompts.py",), RESEARCH_FLAG, fake_cfg
    )
    assert "Map only code in the changed paths that this section touches." in brief
    assert "You may name new paths." in brief
    assert "No entry may name a file that a kept entry names." in brief


def test_refresh_brief_gives_the_room_left_after_kept(fake_cfg: Config) -> None:
    # Breaks when: refresh quotes the full caps instead of subtracting the retained body.
    kept = _kept_map()
    cfg = _capped(fake_cfg)
    brief = refresh_brief(QUEUE, _section(), kept, ("relay/prompts.py",), RESEARCH_FLAG, cfg)
    assert re.search(rf"\b{cfg.map_max_lines - len(kept.body.splitlines())}\s+lines\b", brief)
    assert re.search(rf"\b{cfg.map_max_chars - len(kept.body)}\s+(?:characters|chars)\b", brief)


def test_refresh_brief_keeps_the_map_form_and_flag_rule(fake_cfg: Config) -> None:
    # Breaks when: refresh omits its response form or changes the existing flag instruction.
    kept = _kept_map()
    brief = refresh_brief(QUEUE, _section(), kept, ("relay/prompts.py",), RESEARCH_FLAG, fake_cfg)
    response = brief.replace(block(kept), "")
    for marker in ("MAP", "LINKS", "END MAP"):
        assert marker in response.splitlines()
    sentence = f"When the file {RESEARCH_FLAG} exists, send no more readers and return the map you have."
    assert sentence in response


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


# Ladder design (docs/superpowers/specs/relay-ladder-design.md, Modules `relay/prompts.py`,
# "The architect's brief" and Homes; Order 6).

DESIGN = Path("/work/repo/docs/superpowers/specs/relay-check-design.md")
APPROVAL = "I am sick of this paperwork bullshit. Make it stop."
EVIDENCE = [
    Path("/state/relay/work-repo-docs-queue-md/runs/3.jsonl"),
    Path("/work/repo/tests/test_loop.py"),
]
PROBLEM = "`_verify` parks after one failed check, not three; tests/test_loop.py fails on it"
GUESS_FIX = "move CHECK_LIMIT into relay/config.py"


def _stepped(steps: tuple[str, ...] = ("6", "7"), body: str = BODY, title: str = "Ledger recovery") -> Section:
    return Section(
        id="s4",
        title=title,
        body=body,
        depends_on=("s3",),
        open=True,
        steps=steps,
    )


# Behavior 2 to 5: As now, plus a status rule: the problem after RECUT: or DESIGN:, the guess
# after ` | guess: `, DESIGN and WAITING: <id>.


def test_lead_prompt_states_the_guess_separator() -> None:
    # Breaks when: the lead is not told that a fix it has in mind follows only after " | guess: ".
    assert " | guess: " in _lead()


def test_lead_prompt_says_when_design_and_waiting_apply() -> None:
    # Breaks when: the lead is not told DESIGN is for a lack no recut can supply, or that
    # WAITING: <id> is for a section that cannot go on until queue section <id> lands.
    prompt = _lead()
    assert "DESIGN: " in prompt
    assert "no recut can supply" in prompt
    assert "WAITING: <id>" in prompt
    assert "until queue section <id> lands" in prompt


def test_lead_prompt_says_the_problem_names_its_evidence_and_design_step() -> None:
    # Breaks when: the rule that the problem names what fails, its evidence and its design step
    # is left out.
    prompt = _lead().lower()
    assert "what fails" in prompt
    assert "evidence" in prompt
    assert "design step" in prompt


def test_lead_prompt_with_the_status_rule_keeps_everything_else() -> None:
    # Breaks when: the status rule replaces the old forms instead of adding to them.
    prompt = _lead()
    assert " | guess: " in prompt
    assert prompt.startswith("You are a lead")
    assert BODY in prompt
    for form in ("DONE", "RECUT: ", "NEEDS-OWNER: ", "RETIRED"):
        assert form in prompt


# Behavior 1 and 6: design_brief is the rulings, lead new and approve lines, then the section's
# text; it carries the problem, the steps and the evidence paths, and the lead's guess stays out.


def test_design_brief_carries_every_owner_answer_verbatim_as_new_lines() -> None:
    # Breaks when: an owner answer recorded for the section never reaches the architect (Gauntlet
    # s2, runs 24-28: the answer went only to the lead), only the last is kept, one is reworded,
    # or they land after the approve line.
    answers = ["Compress the spec throughout, {keep} 100% of its contracts.", "Yes: the cap stays."]
    lines = design_brief(DESIGN, QUEUE, _stepped(), PROBLEM, EVIDENCE, APPROVAL, answers).splitlines()
    assert lines[2:5] == [f"new: {answers[0]}", f"new: {answers[1]}", f"approve: {APPROVAL}"]


def test_design_brief_points_at_the_lead_code_by_branch_and_commit_not_by_worktree_path() -> None:
    # Breaks when: the architect, run in the main checkout, is not told the branch and commit
    # holding the lead's code (Gauntlet s2: gauntlet/seams/images.py only on lead/m2-images), or
    # is pointed at the lead's worktree path, which architect.md forbids it to read as outside
    # the repository, instead of `git show <sha>:<path>` / `git diff main...<sha>`.
    code = ("lead/m2-images", "54f611a5")
    lead_new = design_brief(DESIGN, QUEUE, _stepped(), PROBLEM, EVIDENCE, APPROVAL, code=code).splitlines()[1]
    assert lead_new.startswith("lead new: ")
    assert "branch lead/m2-images at 54f611a5 in this repository" in lead_new
    assert "`git show 54f611a5:<path>`" in lead_new
    assert "`git diff main...54f611a5`" in lead_new
    assert "worktree" not in lead_new
    assert "repo-wt" not in lead_new
    no_commit = design_brief(DESIGN, QUEUE, _stepped(), PROBLEM, EVIDENCE, APPROVAL, code=("lead/m2-images", None))
    assert "`git show lead/m2-images:<path>`" in no_commit
    assert "`git diff main...lead/m2-images`" in no_commit


def test_lead_prompt_carries_the_architect_guidance_only_when_given() -> None:
    # Breaks when: a section handed back after two reportless architect runs reaches its lead
    # without the architect's final message, or a lead with no guidance is told of an architect.
    # docs/superpowers/specs/relay-codex-architect-design.md:50-53: the guidance paragraph prints
    # `guidance` as ladder.handback_text wrote it, so the wording is handback_text's, not
    # lead_prompt's: breaks too when lead_prompt rewords it or adds a wrapper of its own.
    said = "The design already covers step 21; the lead misread Order 3."
    guidance = handback_text("it filed no report", said)
    given = lead_prompt(
        QUEUE, _section(), resume=None, report=None, answer=None, retire_flag=RETIRE_FLAG, guidance=guidance
    )
    assert said in given
    assert "filed no design change" in given
    assert guidance in given
    assert given.count("filed no design change") == 1
    # The guidance paragraph is `guidance` alone: no words of lead_prompt's before or after it
    # inside that paragraph (design §Homes: no guidance worded in `prompts.py`).
    paragraphs = [part.strip("\n") for part in re.split(r"\n[ \t]*\n", given)]
    assert guidance.strip("\n") in paragraphs
    plain = lead_prompt(QUEUE, _section(), resume=None, report=None, answer=None, retire_flag=RETIRE_FLAG)
    assert "filed no design change" not in plain


def test_design_brief_with_no_steps_says_steps_unnamed_on_a_lead_new_line_with_the_section_text() -> None:
    # Breaks when: an empty `steps:` gives an empty Order or is worded other than "steps unnamed",
    # or the section's text is left off that `lead new:` line (appended as free lines instead),
    # or is not its last part, written `Section text: <body>` with each whitespace run one space.
    brief = design_brief(DESIGN, QUEUE, _stepped(steps=()), PROBLEM, EVIDENCE[:1], APPROVAL)
    lines = brief.splitlines()
    assert lines[1].startswith(
        f"lead new: Section s4 of the queue at {QUEUE}, under this design's Order steps unnamed, "
        f"cannot go on: {PROBLEM} Evidence: {EVIDENCE[0]}."
    )
    assert lines[1].endswith(f"Section text: {' '.join(BODY.split())}")
    assert lines[2:] == [f"approve: {APPROVAL}"]


def test_design_brief_carries_the_given_design_queue_and_approval() -> None:
    # Breaks when: the design, queue or approval words are fixed rather than taken from the call.
    design = Path("/other/docs/superpowers/specs/relay-ping-design.md")
    queue = Path("/other/docs/baley-queue.md")
    brief = design_brief(design, queue, _stepped(steps=("2",)), PROBLEM, EVIDENCE[:1], "approved by the owner")
    lines = brief.splitlines()
    assert lines[0] == f"rulings {design}"
    assert f"at {queue}, under this design's Order 2, " in lines[1]
    assert lines[2] == "approve: approved by the owner"


def test_design_brief_holds_no_guess_from_the_title() -> None:
    # Breaks when: the section's title, which may carry a lead's guess, reaches the architect's
    # brief, or the problem, steps or evidence paths are dropped.
    section = _stepped(title=f"Check limit, guess: {GUESS_FIX}")
    brief = design_brief(DESIGN, QUEUE, section, PROBLEM, EVIDENCE, APPROVAL)
    assert PROBLEM in brief
    assert "Order 6, 7," in brief
    assert str(EVIDENCE[0]) in brief
    assert str(EVIDENCE[1]) in brief
    assert GUESS_FIX not in brief
    assert "guess" not in brief


# Behavior 7 and 8: design_answer_brief: `rulings <design>`, the answer lines for the numbers as
# written, or `<n>: <answer>` / `new: <answer>` when there is none, then `approve: <approval>`.


def test_design_answer_brief_keeps_the_answer_lines_for_the_numbers_as_written() -> None:
    # Breaks when: a numbered line is reworded, a line for another number or an unnumbered line is
    # kept, "10:" is taken as "1:", or the rulings or approve line is left out.
    answer = "Thanks.\n1: take the recommendation, {braces} 100%\n10: not asked\n2: the alternative\n3: unasked"
    brief = design_answer_brief(DESIGN, (1, 2), answer, APPROVAL)
    assert brief.splitlines() == [
        f"rulings {DESIGN}",
        "1: take the recommendation, {braces} 100%",
        "2: the alternative",
        f"approve: {APPROVAL}",
    ]


def test_design_answer_brief_with_one_number_and_no_numbered_line_numbers_the_answer() -> None:
    # Breaks when: an unnumbered answer to a single decision is not given that decision's number.
    brief = design_answer_brief(DESIGN, (3,), "go with the recommendation", APPROVAL)
    assert brief.splitlines() == [
        f"rulings {DESIGN}",
        "3: go with the recommendation",
        f"approve: {APPROVAL}",
    ]


def test_design_answer_brief_with_several_numbers_and_no_numbered_line_says_new() -> None:
    # Breaks when: an unnumbered answer to several decisions is not passed as `new: <answer>`.
    brief = design_answer_brief(DESIGN, (1, 2), "do both the cheap way", APPROVAL)
    assert brief.splitlines() == [
        f"rulings {DESIGN}",
        "new: do both the cheap way",
        f"approve: {APPROVAL}",
    ]


def test_design_answer_brief_with_no_numbers_says_new() -> None:
    # Breaks when: an answer with no decisions to number is not passed as `new: <answer>`.
    brief = design_answer_brief(DESIGN, (), "add a cap line", "approved by the owner")
    assert brief.splitlines() == [
        f"rulings {DESIGN}",
        "new: add a cap line",
        "approve: approved by the owner",
    ]


# Behavior 9: recut_brief: as now, plus when design is set, the amended-design sentence.

AMENDED = (
    f"The design {DESIGN} was amended for this problem. "
    "Cut this section's work again from it, its new Order steps included."
)


def test_recut_brief_with_a_design_says_it_was_amended() -> None:
    # Breaks when: the design is ignored, worded otherwise, or names another path.
    brief = recut_brief(QUEUE, _section(), "three modules, not one step", LEAD_LOG, design=DESIGN)
    assert AMENDED in brief


def test_recut_brief_without_a_design_leaves_the_sentence_out() -> None:
    # Breaks when: the amended sentence is written though design is None or left at its default,
    # or is never written at all.
    assert AMENDED in recut_brief(QUEUE, _section(), "three modules", LEAD_LOG, design=DESIGN)
    assert "was amended for this problem" not in recut_brief(QUEUE, _section(), "three modules", LEAD_LOG)
    assert "was amended for this problem" not in recut_brief(
        QUEUE, _section(), "three modules", LEAD_LOG, design=None
    )


def test_recut_brief_with_a_design_keeps_everything_else() -> None:
    # Breaks when: setting design replaces the recut brief instead of adding to it, or drops or
    # rewords any of the brief as it is without a design (the queue path, the section, the reason,
    # the log path): with design set the brief is the no-design brief plus the amended sentence.
    reason = "three modules, not one step: split stream from runner"
    brief = recut_brief(QUEUE, _section(sid="s7"), reason, LEAD_LOG, design=DESIGN)
    plain = recut_brief(QUEUE, _section(sid="s7"), reason, LEAD_LOG)
    assert AMENDED in brief
    assert "recut" in brief
    assert "s7" in brief
    assert reason in brief
    assert str(LEAD_LOG) in brief
    assert str(QUEUE) in brief
    assert brief.count(AMENDED) == 1
    assert brief.replace(AMENDED, " ").split() == plain.split()
# Order 17, behavior 4: "resume <session id>" when resume is set; when report is set, next to
# that line, the report verbatim. relay-run-overhead-design.md:110 moves the heading out: report
# is handoff()'s text and is printed as given, with no heading added.
# The signature check keeps a missing `report` parameter an assertion failure, not a TypeError.

REPORT = (
    "Step 2 committed at 1a2b3c: `relay/state.py` built.\n"
    "  Next: step 3, red tests for {prompts}.\n"
    "\tLeft: 100% of step 4\n"
    "RETIRED"
)
ANSWER = "Use port 8080."
HEADING = "previous lead's final report"


def _with_report(report: str | None, resume: str | None = "sess-lead-7", answer: str | None = ANSWER) -> str:
    assert "report" in inspect.signature(lead_prompt).parameters, "lead_prompt has no `report`"
    return lead_prompt(QUEUE, _section(), resume=resume, report=report, answer=answer, retire_flag=RETIRE_FLAG)


def test_lead_prompt_holds_the_report_verbatim_when_set() -> None:
    # Breaks when: lead_prompt ignores `report`, or reflows, strips or escapes its text.
    prompt = _with_report(REPORT)
    assert REPORT in prompt
    assert "resume sess-lead-7" in prompt


def test_lead_prompt_puts_the_report_next_to_the_resume_line() -> None:
    # Breaks when: the report lands apart from the resume line, with the body, the answer or the
    # retire contract between them.
    prompt = _with_report(REPORT)
    resume = prompt.index("resume sess-lead-7")
    report = prompt.index(REPORT)
    between = prompt[min(resume, report) : max(resume, report)]
    assert BODY not in between
    assert ANSWER not in between
    assert str(RETIRE_FLAG) not in between


def test_lead_prompt_without_a_report_holds_no_report_heading() -> None:
    # Breaks when: the heading is written even when no report is given.
    prompt = _with_report(None)
    assert "resume sess-lead-7" in prompt
    assert HEADING not in prompt.lower()


# relay-run-overhead-design.md, Modules `relay/prompts.py` (`lead_prompt`) and Order 5: report is
# handoff()'s text and is printed as given, with no heading added. The two texts below take
# handoff()'s documented forms, with a status and with none.
HANDOFF_WITH_STATUS = (
    "The previous lead's final report (that session's last reply, so you need not recall it):\n" + REPORT
)
HANDOFF_STOPPED = (
    "The previous lead stopped without a final report (killed). Its last reply: none. "
    "Its agents, as Relay saw them:\n"
    "builder, Build s2.d1 stub, running when it stopped"
)


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize("report", [HANDOFF_WITH_STATUS, HANDOFF_STOPPED], ids=["status", "stopped"])
def test_lead_prompt_prints_the_report_as_given_and_adds_nothing_around_it(report: str) -> None:
    # Breaks when: lead_prompt adds a heading or any text with the report, or alters the report.
    prompt = _with_report(report)
    assert report in prompt
    assert _flat(prompt.replace(report, "", 1)) == _flat(_with_report(None))


def test_lead_prompt_with_a_stopped_leads_handoff_holds_no_final_report_heading() -> None:
    # Breaks when: lead_prompt heads a no-status handoff as "the previous lead's final report".
    prompt = _with_report(HANDOFF_STOPPED)
    assert HEADING not in prompt.lower()


def test_lead_prompt_with_a_status_handoff_holds_its_heading_once() -> None:
    # Breaks when: lead_prompt adds its own heading above handoff's, so the heading appears twice.
    prompt = _with_report(HANDOFF_WITH_STATUS)
    assert prompt.lower().count(HEADING) == 1


def test_prerendered_handoff_replaces_default_resume_text_and_keeps_report() -> None:
    # Breaks when: a backend hint is ignored, altered, or accompanied by Claude's default resume line.
    hint = "Prior thread: thread-42.\n  The supplied report is the handoff."
    prompt = lead_prompt(
        QUEUE, _section(), resume="thread-42", report=REPORT, answer=ANSWER,
        retire_flag=RETIRE_FLAG, handoff_hint=hint,
    )
    assert hint in prompt
    assert "resume thread-42" not in prompt
    assert REPORT in prompt
    assert BODY in prompt
    assert ANSWER in prompt


def test_prerendered_handoff_is_optional_and_does_not_replace_default_on_later_calls() -> None:
    # Breaks when: selecting a backend hint changes the default handoff for subsequent prompts.
    hint = "Prior thread: thread-73; use the supplied handoff."
    custom = lead_prompt(
        QUEUE, _section(), resume="thread-73", report=None, answer=None,
        retire_flag=RETIRE_FLAG, handoff_hint=hint,
    )
    default = lead_prompt(
        QUEUE, _section(), resume="sess-lead-7", report=None, answer=None,
        retire_flag=RETIRE_FLAG,
    )
    explicit_default = lead_prompt(
        QUEUE, _section(), resume="sess-lead-7", report=None, answer=None,
        retire_flag=RETIRE_FLAG, handoff_hint=None,
    )
    assert hint in custom
    assert "resume thread-73" not in custom
    assert "resume sess-lead-7" in default
    assert hint not in default
    assert explicit_default == default


# Codex architect design (docs/superpowers/specs/relay-codex-architect-design.md, Modules
# `relay/prompts.py` and Homes; Order 3): every architect brief line is in a legal form.

LEGAL_LINE = re.compile(r"(rulings |\d+: |new: |lead new: |approve: )")
PROBLEM_ML = "`_verify` parks after one failed check;\n  tests/test_loop.py fails on it\n\n\tsee the run log"
ANSWERS_ML = ["Compress the spec.\n  Keep {braces} 100% of its contracts.", "Yes:\n\n\tthe cap stays."]
SAID_ML = "Blocked: the cited log\n  is outside the repository.\n\nNothing filed."
CODE = ("lead/m2-images", "54f611a5")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _illegal(brief: str) -> list[str]:
    return [line for line in brief.splitlines() if not LEGAL_LINE.match(line)]


def _ml_design_brief() -> str:
    return design_brief(DESIGN, QUEUE, _stepped(), PROBLEM_ML, EVIDENCE, APPROVAL, ANSWERS_ML, code=CODE)


# Behavior 1: every line of each architect brief is `rulings `, `<n>: `, `new: `, `lead new: `
# or `approve: `.


def test_design_brief_with_multiline_problem_answers_and_section_is_only_ruling_lines() -> None:
    # Breaks when: the section text is appended as free lines after approve:, a multi-line
    # problem or owner answer spills into bare lines, or a blank or heading line is written.
    brief = _ml_design_brief()
    assert _illegal(brief) == []
    lines = brief.splitlines()
    assert lines[0] == f"rulings {DESIGN}"
    assert lines[1].startswith("lead new: ")
    assert lines[2:] == [f"new: {_flat(ANSWERS_ML[0])}", f"new: {_flat(ANSWERS_ML[1])}", f"approve: {APPROVAL}"]


def test_design_brief_puts_the_section_text_and_problem_on_its_lead_new_line() -> None:
    # Breaks when: the section's body is dropped or kept multi-line rather than written as
    # `Section text: <body>` with each whitespace run made one space on the lead new line.
    lead_new = _ml_design_brief().splitlines()[1]
    assert f"Section text: {_flat(BODY)}" in lead_new
    assert _flat(PROBLEM_ML) in lead_new


def test_design_retry_brief_with_multiline_message_is_only_ruling_lines() -> None:
    # Breaks when: the rerun's reason or the architect's multi-line final message is written as
    # free prose or bare lines, with or without an error.
    brief = _ml_design_brief()
    assert _illegal(design_retry_brief(brief, SAID_ML, None)) == []
    assert _illegal(design_retry_brief(brief, SAID_ML, "exit 1: codex crashed")) == []


def test_design_answer_brief_fallback_with_a_multiline_answer_is_one_numbered_line() -> None:
    # Breaks when: an unnumbered multi-line answer to one decision becomes `<n>:` plus bare lines.
    brief = design_answer_brief(DESIGN, (3,), "go with the\nrecommendation\n\n  but keep the cap", APPROVAL)
    assert _illegal(brief) == []
    assert brief.splitlines() == [
        f"rulings {DESIGN}",
        "3: go with the recommendation but keep the cap",
        f"approve: {APPROVAL}",
    ]


def test_design_answer_brief_fallback_with_a_multiline_answer_is_one_new_line() -> None:
    # Breaks when: an unnumbered multi-line answer to several decisions becomes `new:` plus bare lines.
    brief = design_answer_brief(DESIGN, (1, 2), "do both\n\tthe cheap way", APPROVAL)
    assert _illegal(brief) == []
    assert brief.splitlines() == [f"rulings {DESIGN}", "new: do both the cheap way", f"approve: {APPROVAL}"]


# Behavior 2: the retry reason sits in a `lead new:` line before `approve:`.


def _reason_line(brief: str, retry: str) -> str:
    before, after = brief.splitlines(), retry.splitlines()
    assert after[:-2] == before[:-1]
    assert after[-1] == before[-1]
    assert after[-1].startswith("approve: ")
    return after[-2]


def test_design_retry_brief_puts_the_no_report_reason_in_a_lead_new_line_before_approve() -> None:
    # Breaks when: the reason follows approve:, replaces a line of the brief, or does not say the
    # final message had no BRIEF … END DESIGN block and carry that message, or does not say the
    # architect filed no design change and tell it to make the design change or file a report
    # saying why none is needed (spec relay-codex-architect-design.md:42-45).
    brief = _ml_design_brief()
    line = _reason_line(brief, design_retry_brief(brief, SAID_ML, None))
    assert line.startswith("lead new: ")
    assert "its final message had no BRIEF … END DESIGN block" in line
    assert _flat(SAID_ML) in line
    assert "filed no design change" in line
    assert re.search(r"[Mm]ake the design change, or file a report saying why none is needed", line)


def test_design_retry_brief_puts_the_failure_reason_in_a_lead_new_line_before_approve() -> None:
    # Breaks when: a failed run's error is left out of the reason line, worded other than
    # "it failed: <error>", the run is called reportless instead, or the line does not say the
    # architect filed no design change and tell it to make the design change or file a report
    # saying why none is needed (spec relay-codex-architect-design.md:42-45).
    brief = _ml_design_brief()
    line = _reason_line(brief, design_retry_brief(brief, SAID_ML, "exit 1: codex crashed"))
    assert line.startswith("lead new: ")
    assert "it failed: exit 1: codex crashed" in line
    assert "had no BRIEF" not in line
    assert _flat(SAID_ML) in line
    assert "filed no design change" in line
    assert re.search(r"[Mm]ake the design change, or file a report saying why none is needed", line)


def test_design_retry_brief_on_an_answer_brief_puts_the_reason_before_approve() -> None:
    # Breaks when: the reason line is placed by the design brief's layout rather than before the
    # given brief's own approve: line.
    brief = design_answer_brief(DESIGN, (1, 2), "1: take it\n2: leave it", APPROVAL)
    line = _reason_line(brief, design_retry_brief(brief, "No change needed.", None))
    assert line.startswith("lead new: ")
    assert "No change needed." in line


# Behavior 3: the lead prompt's map rule excludes architect briefs.


def test_lead_prompt_map_rule_excludes_architect_briefs() -> None:
    # Breaks when: the lead is still told to put the map block in the architect's brief too, or
    # the exception for an architect's brief is left out.
    prompt = _with_map()
    assert MAP_BLOCK in prompt
    assert "the architect's included" not in prompt
    assert "except an architect's" in prompt
    assert "except an architect's" not in _with_map(None)


# Queue-worktree design, Modules `relay/prompts.py`: Relay renders an assignment
# chosen by the ownership resolver, including an existing legacy assignment.


@pytest.mark.parametrize(
    ("branch", "path", "resume"),
    [
        ("lead/" + "7" * 64 + "/s4", Path("/work/repo-wt/assigned/s4"), None),
        ("custom/retained-work", Path("/work/old location/section-four"), "prior-lead"),
    ],
    ids=["new-qualified", "resumed-legacy"],
)
def test_lead_prompt_assigns_the_supplied_branch_and_exact_absolute_path(
    branch: str, path: Path, resume: str | None,
) -> None:
    # Breaks when: rendering ignores the selected binding or rewrites a legacy name/location.
    prompt = lead_prompt(
        QUEUE, _section(), resume=resume, report=None, answer=None,
        retire_flag=RETIRE_FLAG, worktree=git.SectionWorktree(branch, path),
    )
    assert branch in prompt
    assert str(path) in prompt
    assert re.search(r"\buse\b[^\n]*" + re.escape(branch), prompt, re.IGNORECASE)
    assert re.search(r"\buse\b[^\n]*" + re.escape(str(path)), prompt, re.IGNORECASE)


def test_lead_prompt_instructs_creation_when_absent_and_final_branch_report() -> None:
    # Breaks when: a fresh lead is not told to create the assigned worktree or report its binding.
    binding = git.SectionWorktree("custom/selected", Path("/work/exact-assignment"))
    prompt = lead_prompt(
        QUEUE, _section(), resume=None, report=None, answer=None,
        retire_flag=RETIRE_FLAG, worktree=binding,
    )
    creation = r"\bcreat\w*\b"
    absence = r"\b(?:absent|missing|not exist|doesn't exist)\b"
    assert re.search(
        rf"(?:{creation}[^.\n]*{absence}|{absence}[^.\n]*{creation})",
        prompt, re.IGNORECASE,
    )
    assert f"BRANCH {binding.branch} {binding.path}" in prompt
    assert re.search(r"\bfinal\s+report\b", prompt, re.IGNORECASE)


def test_lead_prompt_assignment_takes_precedence_over_section_and_recalled_session() -> None:
    # Breaks when: an explicit assignment lacks priority over older generic or recalled naming.
    body = "Use generic branch lead/s4 at /work/generic-worktree.\n"
    report = "BRANCH lead/old-name /work/recalled-worktree\nRETIRED"
    binding = git.SectionWorktree("custom/current-assignment", Path("/work/current-assignment"))
    prompt = lead_prompt(
        QUEUE, _section(body=body), resume="old-session", report=report, answer=None,
        retire_flag=RETIRE_FLAG, worktree=binding,
    )
    assert body in prompt
    assert report in prompt
    assert f"BRANCH {binding.branch} {binding.path}" in prompt
    priority = re.search(
        r"\b(?:this\s+)?(?:worktree\s+)?assignment\s+"
        r"(?:takes\s+(?:precedence|priority)\s+over|has\s+priority\s+over|overrides?)\s+"
        r"([^\n.]+)",
        prompt, re.IGNORECASE,
    )
    assert priority is not None
    assert re.search(r"\bsection\b", priority.group(1), re.IGNORECASE)
    assert re.search(r"\b(recalled|prior|previous)\s+session\b", priority.group(1), re.IGNORECASE)


def test_lead_prompt_renders_the_assignment_without_selecting_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Breaks when: the renderer selects branch/path names rather than rendering Relay's assignment.
    calls: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        calls.append("selection")
        raise AssertionError("prompt rendering must not select a worktree")

    monkeypatch.setattr(git, "section_branch", forbidden)
    monkeypatch.setattr(git, "section_path", forbidden)
    binding = git.SectionWorktree("custom/render-only", Path("/work/render-only"))
    prompt = lead_prompt(
        QUEUE, _section(), resume=None, report=None, answer=None,
        retire_flag=RETIRE_FLAG, worktree=binding,
    )
    assert calls == []
    assert f"BRANCH {binding.branch} {binding.path}" in prompt


# Run overhead design (docs/superpowers/specs/relay-run-overhead-design.md, Modules
# `relay/prompts.py` ENTRY_RULE, READ_RULE and lead_prompt; Order 4).


def _flat_lower(text: str) -> str:
    return " ".join(text.split()).lower()


def _run_overhead_brief(cfg: Config, which: str) -> str:
    if which == "research":
        return research_brief(QUEUE, _section(), RESEARCH_FLAG, cfg)
    return refresh_brief(
        QUEUE, _section(), _kept_map(), ("relay/prompts.py",), RESEARCH_FLAG, cfg
    )


# ENTRY_RULE, appended by _map_form: each entry names what lies at its lines (a symbol, table,
# section or call) in nouns. An entry never says what the code proves, lacks, allows or
# justifies, and never tells a reader what to open, skip or search.


@pytest.mark.parametrize("which", ["research", "refresh"])
def test_map_form_says_an_entry_never_says_what_the_code_proves_lacks_allows_or_justifies(
    fake_cfg: Config, which: str
) -> None:
    # Breaks when the brief's map form leaves out any clause of the entry rule: that an entry
    # names what lies at its lines in nouns, any of the four verbs it never says the code does,
    # or that it never tells a reader what to open, skip or search.
    brief = _flat_lower(_run_overhead_brief(fake_cfg, which))
    assert re.search(
        r"an entry never says what the code proves, lacks, allows,? or justifies", brief
    )
    assert re.search(
        r"each entry names what lies at its lines \(a symbol, table, section,? or call\) "
        r"in nouns",
        brief,
    )
    assert re.search(
        r"an entry never says what the code proves, lacks, allows,? or justifies,? and never "
        r"tells a reader what to open, skip,? or search",
        brief,
    )


# READ_RULE, in research_brief and refresh_brief: read the section's files yourself, and send a
# reader only for a file too large to read whole within the map caps.


@pytest.mark.parametrize("which", ["research", "refresh"])
def test_brief_says_read_the_sections_files_yourself_and_send_a_reader_only_for_a_large_file(
    fake_cfg: Config, which: str
) -> None:
    # Breaks when the brief leaves the choice to send readers to the researcher, or drops the
    # limit that a reader goes only for a file too large to read whole within the map caps.
    brief = _flat_lower(_run_overhead_brief(fake_cfg, which))
    assert "read the section's files yourself" in brief
    assert "send a reader only for a file too large to read whole within the map caps" in brief


# lead_prompt: the map paragraph keeps its paste-verbatim and relay-ask lines and holds only
# block()'s text.


def test_lead_prompt_map_paragraph_holds_only_the_rule_route_and_block_text() -> None:
    # Breaks when the map paragraph carries an instruction line beyond the paste-verbatim and
    # relay-ask lines and block()'s header and body, or drops either of those two lines.
    kept = _kept_map()
    expected_block = f"map {kept.sid} at {kept.commit}\n{kept.body}\n"
    with_map = _with_map(block(kept))
    without = set(_with_map(None).splitlines())
    assert MAP_RULE in with_map
    assert MAP_RULING_ONLY in with_map
    assert MAP_ROUTE in with_map
    assert expected_block in with_map
    block_lines = set(expected_block.splitlines())
    added = [line for line in with_map.splitlines() if line not in without]
    for line in added:
        assert (
            not line.strip()
            or line in block_lines
            or MAP_RULE in line
            or MAP_RULING_ONLY in line
            or MAP_ROUTE in line
        ), line
    # The paragraph runs from the start of the rule's line through block()'s text, and the
    # prompt with it taken out is the no-map prompt, so nothing else rides along with the map.
    start = with_map.rfind("\n", 0, with_map.find(MAP_RULE)) + 1
    block_at = with_map.find(expected_block, start)
    assert block_at != -1
    paragraph = with_map[start : block_at + len(expected_block)]
    rest = with_map.replace(paragraph, "", 1)
    assert [line for line in rest.splitlines() if line.strip()] == [
        line for line in _with_map(None).splitlines() if line.strip()
    ]
    # Before the block, the paragraph holds the route sentence once and otherwise only the
    # paste-verbatim rule's lines; no sentence follows the rule's last one, and nothing in them
    # tells an agent what to open, skip, search or read.
    lead_in = paragraph[: len(paragraph) - len(expected_block)]
    assert lead_in.count(MAP_ROUTE) == 1
    rule_text = lead_in.replace(MAP_ROUTE, "\n")
    for line in rule_text.splitlines():
        if line.strip():
            assert MAP_RULE in line or MAP_RULING_ONLY in line, line
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", rule_text.strip()) if s.strip()]
    last_rule = max(
        i for i, s in enumerate(sentences) if MAP_RULE in s or MAP_RULING_ONLY in s
    )
    assert sentences[last_rule + 1 :] == []
    outside = rule_text.replace(MAP_RULE, " ").replace(MAP_RULING_ONLY, " ")
    assert not re.search(r"\b(?:open|skip|search|read|grep)(?:s|es|ing)?\b", outside, re.I)
# Run-overhead design (docs/superpowers/specs/relay-run-overhead-design.md, Modules
# `relay/prompts.py` `WORKER_RULE`; Order 6): the worker-reply contract stands in
# lead_prompt after the retire contract.


def _worker_rule_text() -> str:
    prompt = _lead()
    return prompt[prompt.index(str(RETIRE_FLAG)) + len(str(RETIRE_FLAG)) :]


def _sentence(text: str, *parts: str) -> bool:
    # True when one sentence of text (no full stop between) holds every part, in order.
    pattern = r"[^.]*".join(parts)
    return re.search(pattern, text, re.IGNORECASE) is not None


# Behavior 1: A worker that replies OVERLOADED, or stops heavy with work left: end this
# session with RECUT: <that worker's report>.


def test_lead_prompt_ends_with_recut_and_the_report_on_an_overloaded_worker() -> None:
    # Breaks when: the lead is not told to end with RECUT: and the worker's report when a
    # worker replies OVERLOADED, or the rule stands before the retire contract.
    text = _worker_rule_text()
    assert _sentence(text, r"\bOVERLOADED\b", r"\bend\b", r"\bsession\b", r"RECUT: ", r"\breport\b")


def test_lead_prompt_ends_with_recut_and_the_report_on_a_worker_stopped_heavy_with_work_left() -> None:
    # Breaks when: a worker that stops heavy with work left is not routed to RECUT: with its report.
    text = _worker_rule_text()
    assert _sentence(text, r"\bheavy\b", r"\bwork left\b", r"\bend\b", r"RECUT: ", r"\breport\b")


# Behavior 2: Never cut or resend the step yourself.


def test_lead_prompt_forbids_the_lead_cutting_or_resending_the_step_itself() -> None:
    # Breaks when: the lead is not told never to cut or resend the step itself.
    text = _worker_rule_text()
    assert _sentence(text, r"\bnever\b", r"\bcut\b", r"\bresend\b", r"\bstep\b", r"\byourself\b")


# Behavior 3: A worker that replies REJECTED: STEERING: resend the same brief once, with
# the quoted lines struck and nothing added.


def test_lead_prompt_resends_the_same_brief_once_on_a_steering_rejection() -> None:
    # Breaks when: a REJECTED: STEERING reply is not met by resending the same brief once.
    text = _worker_rule_text()
    assert _sentence(text, r"REJECTED: STEERING", r"\bresend\b", r"\bsame brief\b", r"\bonce\b")


def test_lead_prompt_resends_with_the_quoted_lines_struck_and_nothing_added() -> None:
    # Breaks when: the resend keeps the quoted lines or lets the lead add to the brief.
    text = _worker_rule_text()
    assert _sentence(text, r"REJECTED: STEERING", r"\bquoted lines\b", r"\bstruck\b", r"\bnothing added\b")


# Behavior 4: No assayer runs on a rejection.


def test_lead_prompt_runs_no_assayer_on_a_rejection() -> None:
    # Breaks when: the lead is not told that no assayer runs on a rejection.
    text = _worker_rule_text()
    assert _sentence(text, r"\bno assayer\b", r"\brejection\b")


# Behavior 5: A second rejection of the same step ends the session with RECUT: <both rejections>.


def test_lead_prompt_ends_with_recut_and_both_rejections_on_a_second_rejection_of_the_same_step() -> None:
    # Breaks when: a second rejection of the same step is not routed to RECUT: carrying both
    # rejections (left out, met by another resend, or carrying only the latest rejection).
    text = _worker_rule_text()
    assert _sentence(
        text,
        r"\bsecond rejection\b",
        r"\bsame step\b",
        r"\bends?\b",
        r"\bsession\b",
        r"RECUT: ",
        r"\bboth rejections\b",
    )
