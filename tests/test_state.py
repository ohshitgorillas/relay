"""Red tests for Relay's state (design: Modules, `relay/state.py`; Order 7)."""

from __future__ import annotations

import fcntl
import json
import os
import threading
from pathlib import Path
from typing import Callable

import pytest

import relay.state as state_module
import relay.files as publication
from relay.config import Config
from relay.errors import LockedError
from relay.state import SectionState, State

QUEUE = "workboard-queue.md"


def test_design_cycle_failures_persist_independently_and_old_records_default(
    queue: Path, fake_cfg: Config
) -> None:
    # Breaks when: old records fail to load, or architect cycles share lead/section counts.
    state = State.open(queue, fake_cfg)
    state.record_failure("s1")
    path = _dir(state) / "state.json"
    old = json.loads(path.read_text())
    old["sections"]["s1"].pop("design_failures", None)
    old["sections"]["s1"].pop("design_failure", None)
    path.write_text(json.dumps(old))
    section = State.open(queue, fake_cfg).section("s1")
    assert (section.design_failures, section.design_failure) == (0, None)
    assert state_module.DESIGN_FAILURE_LIMIT == 2
    assert State.open(queue, fake_cfg).record_design_failure("s1", "it filed no report") == 1
    assert State.open(queue, fake_cfg).record_design_failure("s1", "it did not approve the design") == 2
    section = State.open(queue, fake_cfg).section("s1")
    assert (section.design_failures, section.design_failure) == (2, "it did not approve the design")
    assert section.failures == 1
    assert State.open(queue, fake_cfg).section("s2").design_failures == 0


@pytest.mark.parametrize("reset", ["clear", "answer", "done"])
def test_design_failure_resets_are_persisted(queue: Path, fake_cfg: Config, reset: str) -> None:
    # Breaks when: explicit recovery or completion leaves the architect bound or reason saved.
    state = State.open(queue, fake_cfg)
    state.record_design_failure("s1", "it filed no report")
    state.record_design_failure("s2", "it rejected the brief as steering")
    if reset == "clear":
        state.clear_design_failures("s1")
    elif reset == "answer":
        assert state.set_answer("s1", "Retry after fixing the cause.")
    else:
        state.mark_done("s1")
    section = State.open(queue, fake_cfg).section("s1")
    assert (section.design_failures, section.design_failure) == (0, None)
    other = State.open(queue, fake_cfg).section("s2")
    assert (other.design_failures, other.design_failure) == (1, "it rejected the brief as steering")


def test_ordinary_section_activity_does_not_clear_design_failures(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: lead bookkeeping, guidance consumption or ordinary recuts clear the bound.
    state = State.open(queue, fake_cfg)
    state.record_design_failure("s1", "it filed no report")
    state.set_guidance("s1", "Keep going.")
    state.take_guidance("s1")
    state.set_last_session("s1", "retired-lead")
    state.set_last_report("s1", "Retired with work left.")
    state.record_failure("s1")
    state.mark_from_recut("s1")
    section = State.open(queue, fake_cfg).section("s1")
    assert (section.design_failures, section.design_failure) == (1, "it filed no report")
    assert section.failures == 1


def test_answer_clears_architect_failures_in_the_answer_publication(
    queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: accepting an answer publishes its reopened state before resetting the bound,
    # or a rejected answer changes a completed section's persisted state.
    state = State.open(queue, fake_cfg)
    state.park("s1", "Which direction?")
    state.mark_done("s2")
    path = _dir(state) / "state.json"
    saved = json.loads(path.read_text())
    for sid in ("s1", "s2"):
        saved["sections"][sid]["design_failures"] = 2
        saved["sections"][sid]["design_failure"] = "it filed no report"
    path.write_text(json.dumps(saved))
    before = path.read_bytes()
    assert state.set_answer("s2", "Retry.") is False
    assert path.read_bytes() == before
    publications = []
    real_replace = os.replace

    def observe(src: object, dst: object, *args: object, **kwargs: object) -> None:
        if Path(os.fsdecode(dst)) == path:
            publications.append(json.loads(Path(os.fsdecode(src)).read_text()))
        real_replace(src, dst, *args, **kwargs)

    _patch_replace(monkeypatch, observe)
    assert state.set_answer("s1", "Use the documented direction.") is True
    assert publications
    for published in publications:
        section = published["sections"]["s1"]
        assert section["status"] == "open"
        assert section["answer"] == "Use the documented direction."
        assert section["question"] is None
        assert (section["design_failures"], section["design_failure"]) == (0, None)
        assert published["sections"]["s2"] == saved["sections"]["s2"]
    reopened = State.open(queue, fake_cfg).section("s1")
    assert (reopened.design_failures, reopened.design_failure) == (0, None)


def test_done_clears_architect_failures_in_the_completion_publication(
    queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: completion and its architect-bound reset appear in different state writes.
    state = State.open(queue, fake_cfg)
    state.park("s1", "Which direction?")
    state.park("s2", "Another question.")
    path = _dir(state) / "state.json"
    saved = json.loads(path.read_text())
    for sid in ("s1", "s2"):
        saved["sections"][sid]["design_failures"] = 2
        saved["sections"][sid]["design_failure"] = "it filed no report"
    path.write_text(json.dumps(saved))
    publications = []
    real_replace = os.replace

    def observe(src: object, dst: object, *args: object, **kwargs: object) -> None:
        if Path(os.fsdecode(dst)) == path:
            publications.append(json.loads(Path(os.fsdecode(src)).read_text()))
        real_replace(src, dst, *args, **kwargs)

    _patch_replace(monkeypatch, observe)
    state.mark_done("s1")
    assert publications
    for published in publications:
        section = published["sections"]["s1"]
        assert section["status"] == "done"
        assert (section["design_failures"], section["design_failure"]) == (0, None)
        assert published["sections"]["s2"] == saved["sections"]["s2"]
    reopened = State.open(queue, fake_cfg).section("s1")
    assert reopened.status == "done"
    assert (reopened.design_failures, reopened.design_failure) == (0, None)


def test_state_serializes_through_shared_publisher_while_retaining_lock(
    queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when state bypasses the shared publisher, loses its data, or drops its lock.
    state = State.open(queue, fake_cfg)
    state.lock()
    calls = []
    original = publication.atomic_write

    def publish(path, data, *, mode=None):
        calls.append((path, data))
        json.loads(data)
        path.write_bytes(data)

    for name, value in list(vars(state_module).items()):
        if value is original:
            monkeypatch.setattr(state_module, name, publish)
    monkeypatch.setattr(publication, "atomic_write", publish)
    for write in WRITES.values():
        before = len(calls)
        write(state)
        assert len(calls) > before, "state bypassed shared atomic publication"
    state.set_last_report("s1", "exact report λ\nDONE")
    assert State.open(queue, fake_cfg).section("s1").last_report == "exact report λ\nDONE"
    assert calls
    assert all(path.parent == _dir(state) and isinstance(data, bytes) for path, data in calls)
    with pytest.raises(LockedError):
        State.open(queue, fake_cfg).lock()


def _patch_replace(monkeypatch: pytest.MonkeyPatch, fake: Callable[..., None]) -> None:
    """Swap `os.replace` for `fake`, however `relay.state` imported it (`os.replace` or `from os import replace`)."""
    real = os.replace
    for name, value in list(vars(state_module).items()):
        if value is real:
            monkeypatch.setattr(state_module, name, fake)
    monkeypatch.setattr(os, "replace", fake)


def _dir(state: State) -> Path:
    """The queue's state directory: the stop file is `<dir>/STOP`."""
    return state.stop_file.parent


@pytest.fixture
def queue(queue_file: Callable[[str], Path]) -> Path:
    return queue_file(QUEUE)


@pytest.fixture
def other_queue(tmp_path: Path) -> Path:
    """A second queue with the same file name in another directory."""
    path = tmp_path / "elsewhere" / QUEUE
    path.parent.mkdir()
    path.write_bytes((Path(__file__).parent / "fixtures" / QUEUE).read_bytes())
    return path


# Behavior 1: Relay's own record for one queue, kept under
# `state_root/<slug of the queue's absolute path>/`.


def test_open_creates_one_directory_directly_under_state_root(queue: Path, fake_cfg: Config) -> None:
    state = State.open(queue, fake_cfg)
    assert _dir(state).is_dir()
    assert _dir(state).parent == fake_cfg.state_root


def test_open_keys_the_directory_by_absolute_path_so_a_relative_path_finds_the_same_one(
    queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    by_absolute = State.open(queue.resolve(), fake_cfg)
    monkeypatch.chdir(queue.parent)
    by_relative = State.open(Path(queue.name), fake_cfg)
    assert _dir(by_relative) == _dir(by_absolute)


def test_two_queues_with_the_same_name_in_different_directories_get_different_directories(
    queue: Path, other_queue: Path, fake_cfg: Config
) -> None:
    first = State.open(queue, fake_cfg)
    second = State.open(other_queue, fake_cfg)
    assert _dir(first) != _dir(second)
    assert _dir(first).parent == _dir(second).parent == fake_cfg.state_root


def test_run_dir_is_runs_inside_the_queues_directory(queue: Path, fake_cfg: Config) -> None:
    state = State.open(queue, fake_cfg)
    assert state.run_dir == _dir(state) / "runs"


def test_records_of_one_queue_are_not_seen_by_another(
    queue: Path, other_queue: Path, fake_cfg: Config
) -> None:
    State.open(queue, fake_cfg).mark_done("s1")
    assert State.open(other_queue, fake_cfg).section("s1").status == "open"


# Behavior 2: It holds per-section status, failure counts, parked questions, owner
# answers, the last session id per section, the stop file and the lock.


def test_a_section_with_no_record_is_open_with_nothing_set(queue: Path, fake_cfg: Config) -> None:
    section = State.open(queue, fake_cfg).section("s1")
    assert section == SectionState(status="open", failures=0, question=None, answer=None, last_session=None)


def test_mark_done_sets_status_done_and_survives_reopening(queue: Path, fake_cfg: Config) -> None:
    State.open(queue, fake_cfg).mark_done("s2")
    reopened = State.open(queue, fake_cfg)
    assert reopened.section("s2").status == "done"
    assert reopened.section("s1").status == "open"


def test_park_sets_status_parked_and_keeps_the_question_across_reopening(
    queue: Path, fake_cfg: Config
) -> None:
    State.open(queue, fake_cfg).park("s3", "Which port should the server use?")
    section = State.open(queue, fake_cfg).section("s3")
    assert section.status == "parked"
    assert section.question == "Which port should the server use?"


def test_record_failure_returns_the_new_count_and_keeps_it_across_reopening(
    queue: Path, fake_cfg: Config
) -> None:
    state = State.open(queue, fake_cfg)
    assert state.record_failure("s4") == 1
    assert State.open(queue, fake_cfg).record_failure("s4") == 2
    reopened = State.open(queue, fake_cfg)
    assert reopened.section("s4").failures == 2
    assert reopened.section("s5").failures == 0


def test_set_answer_is_kept_across_reopening_and_take_answer_consumes_it(
    queue: Path, fake_cfg: Config
) -> None:
    State.open(queue, fake_cfg).set_answer("s5", "Use port 8080.")
    reopened = State.open(queue, fake_cfg)
    assert reopened.section("s5").answer == "Use port 8080."
    assert reopened.take_answer("s5") == "Use port 8080."
    assert reopened.take_answer("s5") is None
    assert State.open(queue, fake_cfg).section("s5").answer is None


def test_every_answer_is_kept_in_order_after_take_answer(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: an owner answer is dropped once a lead takes it, so a later architect brief for
    # the section cannot carry it (Gauntlet s2), or a later answer replaces an earlier one.
    state = State.open(queue, fake_cfg)
    state.set_answer("s5", "Use port 8080.")
    state.take_answer("s5")
    state.set_answer("s5", "Compress the spec.\nKeep the cap.")
    assert State.open(queue, fake_cfg).section("s5").answers == ["Use port 8080.", "Compress the spec.\nKeep the cap."]


def test_guidance_is_kept_across_reopening_and_taken_once(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: a reportless architect's message, handed to the section's next lead, is lost on
    # reopening, leaves the section anything but open, or reaches every later lead again.
    State.open(queue, fake_cfg).set_guidance("s5", "Order 3 already covers it.")
    state = State.open(queue, fake_cfg)
    assert state.section("s5").status == "open"
    assert state.take_guidance("s5") == "Order 3 already covers it."
    assert state.take_guidance("s5") is None


def test_take_answer_with_no_answer_returns_none(queue: Path, fake_cfg: Config) -> None:
    assert State.open(queue, fake_cfg).take_answer("s6") is None


def test_last_session_is_kept_per_section_across_reopening(queue: Path, fake_cfg: Config) -> None:
    state = State.open(queue, fake_cfg)
    state.set_last_session("s1", "session-a")
    state.set_last_session("s2", "session-b")
    reopened = State.open(queue, fake_cfg)
    assert reopened.section("s1").last_session == "session-a"
    assert reopened.section("s2").last_session == "session-b"
    assert reopened.section("s3").last_session is None


def test_last_session_any_is_none_before_any_session_is_recorded(queue: Path, fake_cfg: Config) -> None:
    assert State.open(queue, fake_cfg).last_session_any is None


def test_last_session_any_is_the_most_recently_recorded_session_of_any_section(
    queue: Path, fake_cfg: Config
) -> None:
    state = State.open(queue, fake_cfg)
    state.set_last_session("s2", "session-b")
    state.set_last_session("s1", "session-a")
    assert State.open(queue, fake_cfg).last_session_any == "session-a"
    state.set_last_session("s2", "session-c")
    assert State.open(queue, fake_cfg).last_session_any == "session-c"


def test_stop_file_is_STOP_in_the_queues_directory_and_open_does_not_create_it(
    queue: Path, fake_cfg: Config
) -> None:
    state = State.open(queue, fake_cfg)
    assert state.stop_file.name == "STOP"
    assert state.stop_file.parent.parent == fake_cfg.state_root
    assert not state.stop_file.exists()


def test_a_created_stop_file_is_seen_by_a_reopened_state(queue: Path, fake_cfg: Config) -> None:
    State.open(queue, fake_cfg).stop_file.touch()
    assert State.open(queue, fake_cfg).stop_file.exists()


# Behavior 3: Every write goes through a temp file and `os.replace`.

WRITES: dict[str, Callable[[State], object]] = {
    "mark_done": lambda s: s.mark_done("s1"),
    "park": lambda s: s.park("s1", "Which port?"),
    "set_answer": lambda s: s.set_answer("s1", "Port 8080."),
    "take_answer": lambda s: s.take_answer("s1"),
    "record_failure": lambda s: s.record_failure("s1"),
    "set_last_session": lambda s: s.set_last_session("s1", "session-a"),
}


@pytest.mark.parametrize("write", sorted(WRITES))
def test_every_write_replaces_a_file_in_the_queues_directory_from_a_temp_file(
    write: str, queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = State.open(queue, fake_cfg)
    state.set_answer("s1", "An earlier answer.")
    calls: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def recording_replace(src: object, dst: object, *args: object, **kwargs: object) -> None:
        calls.append((Path(os.fsdecode(src)), Path(os.fsdecode(dst))))
        real_replace(src, dst, *args, **kwargs)

    _patch_replace(monkeypatch, recording_replace)
    WRITES[write](state)
    assert calls
    for src, dst in calls:
        assert src != dst
        assert dst.is_relative_to(_dir(state))
        assert not src.exists()


def test_a_write_whose_replace_fails_leaves_the_earlier_record_intact(
    queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = State.open(queue, fake_cfg)
    state.mark_done("s1")

    def failing_replace(src: object, dst: object, *args: object, **kwargs: object) -> None:
        raise OSError("replace failed")

    _patch_replace(monkeypatch, failing_replace)
    with pytest.raises(OSError):
        state.park("s1", "Which port?")
    monkeypatch.undo()
    section = State.open(queue, fake_cfg).section("s1")
    assert section.status == "done"
    assert section.question is None


# Behavior 4: fcntl.flock on <dir>/lock; raises LockedError


def test_open_takes_no_lock(queue: Path, fake_cfg: Config) -> None:
    holder = State.open(queue, fake_cfg)
    holder.lock()
    other = State.open(queue, fake_cfg)
    assert _dir(other) == _dir(holder)


def test_lock_creates_the_lock_file_in_the_queues_directory(queue: Path, fake_cfg: Config) -> None:
    state = State.open(queue, fake_cfg)
    state.lock()
    assert (_dir(state) / "lock").is_file()


def test_a_second_lock_on_the_same_queue_raises_locked_error(queue: Path, fake_cfg: Config) -> None:
    holder = State.open(queue, fake_cfg)
    holder.lock()
    with pytest.raises(LockedError):
        State.open(queue, fake_cfg).lock()


def test_lock_raises_locked_error_while_another_holder_has_flock_on_the_lock_file(
    queue: Path, fake_cfg: Config
) -> None:
    state = State.open(queue, fake_cfg)
    with open(_dir(state) / "lock", "a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(LockedError):
            state.lock()


def test_lock_holds_flock_on_the_lock_file_against_other_holders(queue: Path, fake_cfg: Config) -> None:
    state = State.open(queue, fake_cfg)
    state.lock()
    with open(_dir(state) / "lock", "a") as other:
        with pytest.raises(BlockingIOError):
            fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_a_lock_on_one_queue_does_not_block_another_queue(
    queue: Path, other_queue: Path, fake_cfg: Config
) -> None:
    holder = State.open(queue, fake_cfg)
    holder.lock()
    other = State.open(other_queue, fake_cfg)
    other.lock()
    assert (_dir(other) / "lock").is_file()


# Behavior 5: also sets status back to "open"


def test_set_answer_on_a_parked_section_sets_status_back_to_open(queue: Path, fake_cfg: Config) -> None:
    state = State.open(queue, fake_cfg)
    state.park("s7", "Which port?")
    state.set_answer("s7", "Port 8080.")
    section = State.open(queue, fake_cfg).section("s7")
    assert section.status == "open"
    assert section.answer == "Port 8080."


# Order 15, behavior 1: `ledger_path` is `<dir>/ledger.jsonl` (design: Modules, `relay/state.py`).
# Order 15, behavior 2: `retire_flag` is `<dir>/runs/retire`.
# `getattr` with a default keeps a missing accessor an assertion failure, not an AttributeError.


def test_ledger_path_is_ledger_jsonl_in_the_queues_directory(queue: Path, fake_cfg: Config) -> None:
    state = State.open(queue, fake_cfg)
    assert getattr(state, "ledger_path", None) == _dir(state) / "ledger.jsonl"


def test_ledger_path_is_the_same_file_for_a_reopened_state_and_differs_per_queue(
    queue: Path, other_queue: Path, fake_cfg: Config
) -> None:
    first = getattr(State.open(queue, fake_cfg), "ledger_path", None)
    again = getattr(State.open(queue, fake_cfg), "ledger_path", None)
    other = getattr(State.open(other_queue, fake_cfg), "ledger_path", None)
    assert first is not None
    assert first == again
    assert first != other


def test_retire_flag_is_retire_inside_the_run_dir(queue: Path, fake_cfg: Config) -> None:
    state = State.open(queue, fake_cfg)
    assert getattr(state, "retire_flag", None) == _dir(state) / "runs" / "retire"
    assert getattr(state, "retire_flag", None) == state.run_dir / "retire"


def test_retire_flag_is_the_same_file_for_a_reopened_state_and_differs_per_queue(
    queue: Path, other_queue: Path, fake_cfg: Config
) -> None:
    first = getattr(State.open(queue, fake_cfg), "retire_flag", None)
    again = getattr(State.open(queue, fake_cfg), "retire_flag", None)
    other = getattr(State.open(other_queue, fake_cfg), "retire_flag", None)
    assert first is not None
    assert first == again
    assert first != other


def test_mark_from_recut_is_kept_for_that_section_only(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: the flag is not saved, or is set on another section too.
    State.open(queue, fake_cfg).mark_from_recut("s1.1")
    state = State.open(queue, fake_cfg)
    assert state.section("s1.1").from_recut
    assert not state.section("s1").from_recut


def test_a_record_saved_before_from_recut_existed_loads_with_it_false(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: a state.json from an older relay, without the key, no longer loads.
    state = State.open(queue, fake_cfg)
    old = '{"sections": {"s1": {"status": "parked", "failures": 1, "question": "q", "answer": null, "last_session": null}}, "last_any": null}'
    (_dir(state) / "state.json").write_text(old)
    section = state.section("s1")
    assert section.status == "parked"
    assert not section.from_recut


# Relay's check (design: docs/superpowers/specs/relay-check-design.md, Modules `relay/state.py`; Order 3).
# Behavior 1: failed checks (verdict "fail"); never counts toward FAILURE_LIMIT


def test_failed_checks_leave_the_failure_count_alone(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: `record_check_failure` also bumps `failures`, the count FAILURE_LIMIT reads.
    state = State.open(queue, fake_cfg)
    for _ in range(state_module.FAILURE_LIMIT + 1):
        state.record_check_failure("s1", "exit 1")
    section = State.open(queue, fake_cfg).section("s1")
    assert section.failures == 0
    assert section.check_failures == state_module.FAILURE_LIMIT + 1


def test_a_failure_after_failed_checks_counts_from_zero(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: `record_failure` adds the failed checks into the count it returns.
    state = State.open(queue, fake_cfg)
    state.record_check_failure("s1", "exit 1")
    state.record_check_failure("s1", "exit 1")
    assert state.record_failure("s1") == 1
    section = State.open(queue, fake_cfg).section("s1")
    assert section.failures == 1
    assert section.check_failures == 2


# Behavior 2: +1, sets check_feedback, returns the count


def test_record_check_failure_returns_the_count_after_adding_one(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: the count is not raised by one per call, or the old count is returned.
    state = State.open(queue, fake_cfg)
    assert state.record_check_failure("s2", "first") == 1
    assert state.record_check_failure("s2", "second") == 2
    assert State.open(queue, fake_cfg).record_check_failure("s2", "third") == 3


def test_record_check_failure_is_kept_per_section_across_reopening(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: the count is not saved, or is shared between sections.
    state = State.open(queue, fake_cfg)
    state.record_check_failure("s2", "exit 1")
    state.record_check_failure("s2", "exit 1")
    state.record_check_failure("s3", "exit 2")
    reopened = State.open(queue, fake_cfg)
    assert reopened.section("s2").check_failures == 2
    assert reopened.section("s3").check_failures == 1
    assert reopened.section("s4").check_failures == 0


def test_record_check_failure_sets_check_feedback_to_the_latest_text(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: the feedback is not saved, or an older failure's text is kept.
    state = State.open(queue, fake_cfg)
    state.record_check_failure("s2", "make test: exit 1\nFAILED test_a")
    assert State.open(queue, fake_cfg).section("s2").check_feedback == "make test: exit 1\nFAILED test_a"
    state.record_check_failure("s2", "make test: exit 2\nFAILED test_b")
    reopened = State.open(queue, fake_cfg)
    assert reopened.section("s2").check_feedback == "make test: exit 2\nFAILED test_b"
    assert reopened.section("s3").check_feedback is None


# Behavior 3: `mark_done` also clears `check_feedback` and `check_pending`.
# `set_answer` leaves `check_pending` as it is.


def test_mark_done_clears_check_feedback_and_check_pending(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: `mark_done` leaves either the feedback or the pending flag set.
    state = State.open(queue, fake_cfg)
    state.record_check_failure("s5", "exit 1")
    state.set_check_pending("s5", True)
    state.mark_done("s5")
    section = State.open(queue, fake_cfg).section("s5")
    assert section.status == "done"
    assert section.check_feedback is None
    assert section.check_pending is False


def test_set_answer_leaves_a_pending_check_pending(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: `set_answer` clears `check_pending` on the parked section it reopens.
    state = State.open(queue, fake_cfg)
    state.set_check_pending("s6", True)
    state.park("s6", "make test: exit 127")
    state.set_answer("s6", "Installed the tool.")
    section = State.open(queue, fake_cfg).section("s6")
    assert section.status == "open"
    assert section.check_pending is True


# Relay's research (design: docs/superpowers/specs/relay-research-design.md, Modules `relay/state.py`; Order 3).
# Behavior 1: Researcher session, map path, research flag, research lock; dropping the map when
# the section is done.

MAP_FIXTURE = Path(__file__).parent / "fixtures" / "research-map.txt"


def _save_map(state: State, sid: str) -> Path:
    """Put the fixture map at the section's map path, as `research.save` leaves one."""
    path = state.map_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(MAP_FIXTURE.read_bytes())
    return path


def test_map_path_is_the_sections_map_file_under_maps_in_the_queues_directory(
    queue: Path, fake_cfg: Config
) -> None:
    # Breaks when: the map is kept anywhere but `<dir>/maps/<sid>.map`.
    state = State.open(queue, fake_cfg)
    assert state.map_path("s1") == _dir(state) / "maps" / "s1.map"
    assert state.map_path("s2.d1") == _dir(state) / "maps" / "s2.d1.map"


def test_map_path_is_the_same_for_a_reopened_state_and_differs_per_queue(
    queue: Path, other_queue: Path, fake_cfg: Config
) -> None:
    # Breaks when: the path is not derived from the queue's own directory.
    first = State.open(queue, fake_cfg).map_path("s1")
    assert State.open(queue, fake_cfg).map_path("s1") == first
    assert State.open(other_queue, fake_cfg).map_path("s1") != first


def test_research_flag_is_research_sid_inside_the_run_dir(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: the research flag is the lead's retire flag or lies outside `run_dir`.
    state = State.open(queue, fake_cfg)
    assert state.research_flag("s1") == state.run_dir / "research-s1"
    assert state.research_flag("s2.d1") == state.run_dir / "research-s2.d1"
    assert state.research_flag("s1") != state.retire_flag


def test_set_research_session_is_kept_per_section_across_reopening(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: the session is not saved, or is shared between sections.
    state = State.open(queue, fake_cfg)
    state.set_research_session("s1", "research-a")
    state.set_research_session("s2", "research-b")
    reopened = State.open(queue, fake_cfg)
    assert reopened.section("s1").research_session == "research-a"
    assert reopened.section("s2").research_session == "research-b"
    assert reopened.section("s3").research_session is None


def test_set_research_session_none_clears_it(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: a None session is ignored and the old one kept.
    state = State.open(queue, fake_cfg)
    state.set_research_session("s1", "research-a")
    state.set_research_session("s1", None)
    assert State.open(queue, fake_cfg).section("s1").research_session is None


def test_set_research_session_leaves_the_leads_session_alone(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: the researcher's session is written into `last_session` or `last_session_any`.
    state = State.open(queue, fake_cfg)
    state.set_last_session("s1", "lead-a")
    state.set_research_session("s1", "research-a")
    reopened = State.open(queue, fake_cfg)
    assert reopened.section("s1").last_session == "lead-a"
    assert reopened.section("s1").research_session == "research-a"
    assert reopened.last_session_any == "lead-a"


def test_drop_map_clears_the_research_session_and_deletes_the_map(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: `drop_map` leaves either the session or the map file behind.
    state = State.open(queue, fake_cfg)
    state.set_research_session("s1", "research-a")
    path = _save_map(state, "s1")
    state.drop_map("s1")
    assert not path.exists()
    assert State.open(queue, fake_cfg).section("s1").research_session is None


def test_drop_map_leaves_other_sections_maps_and_sessions(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: `drop_map` clears or deletes another section's research.
    state = State.open(queue, fake_cfg)
    state.set_research_session("s1", "research-a")
    state.set_research_session("s2", "research-b")
    _save_map(state, "s1")
    other = _save_map(state, "s2")
    state.drop_map("s1")
    assert other.read_bytes() == MAP_FIXTURE.read_bytes()
    assert State.open(queue, fake_cfg).section("s2").research_session == "research-b"


def test_drop_map_with_no_map_saved_clears_the_session(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: `drop_map` raises on a section whose map file is absent (as `_research` meets
    # before a section's first research run), or keeps the session.
    state = State.open(queue, fake_cfg)
    state.set_research_session("s1", "research-a")
    state.drop_map("s1")
    assert not state.map_path("s1").exists()
    assert State.open(queue, fake_cfg).section("s1").research_session is None


RESEARCH_WRITES: dict[str, Callable[[State], object]] = {
    "set_research_session": lambda s: s.set_research_session("s1", "research-a"),
    "drop_map": lambda s: s.drop_map("s1"),
}


@pytest.mark.parametrize("write", sorted(RESEARCH_WRITES))
def test_each_research_write_replaces_a_file_in_the_queues_directory_from_a_temp_file(
    write: str, queue: Path, fake_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Breaks when: the research session is written other than by temp file and `os.replace`.
    state = State.open(queue, fake_cfg)
    state.set_answer("s1", "An earlier answer.")
    # An earlier, different session, so each write below changes the section's research state.
    state.set_research_session("s1", "research-earlier")
    calls: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def recording_replace(src: object, dst: object, *args: object, **kwargs: object) -> None:
        calls.append((Path(os.fsdecode(src)), Path(os.fsdecode(dst))))
        real_replace(src, dst, *args, **kwargs)

    _patch_replace(monkeypatch, recording_replace)
    RESEARCH_WRITES[write](state)
    assert calls
    for src, dst in calls:
        assert src != dst
        assert dst.is_relative_to(_dir(state))
        assert not src.exists()


def _research_lock_file(state: State, sid: str) -> Path:
    return _dir(state) / f"research-{sid}.lock"


def test_research_lock_holds_flock_on_the_sections_lock_file(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: the lock is taken on another file, or not held while the block runs.
    state = State.open(queue, fake_cfg)
    with state.research_lock("s1"):
        assert _research_lock_file(state, "s1").is_file()
        with open(_research_lock_file(state, "s1"), "a") as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_research_lock_is_released_when_the_block_ends(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: the flock outlives the `with` block.
    state = State.open(queue, fake_cfg)
    with state.research_lock("s1"):
        assert _research_lock_file(state, "s1").is_file()
    with open(_research_lock_file(state, "s1"), "a") as other:
        fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_research_lock_is_released_when_the_block_raises(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: an error inside the block leaves the flock held, or the error is swallowed.
    state = State.open(queue, fake_cfg)
    with pytest.raises(LookupError):
        with state.research_lock("s1"):
            raise LookupError("inside")
    with open(_research_lock_file(state, "s1"), "a") as other:
        fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_research_lock_blocks_until_the_holder_lets_go(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: the lock is non-blocking, raising or entering while another holds it.
    state = State.open(queue, fake_cfg)
    entered = threading.Event()
    errors: list[BaseException] = []

    def take() -> None:
        try:
            with State.open(queue, fake_cfg).research_lock("s1"):
                entered.set()
        except BaseException as exc:  # noqa: BLE001 - handed to the test thread
            errors.append(exc)
            entered.set()

    with state.research_lock("s1"):
        waiter = threading.Thread(target=take)
        waiter.start()
        assert not entered.wait(0.3)
    waiter.join(5)
    assert errors == []
    assert entered.is_set()


def test_research_lock_of_one_section_does_not_block_another_or_the_go_lock(
    queue: Path, fake_cfg: Config
) -> None:
    # Breaks when: research locks share one file, or take `<dir>/lock`, the `relay go` lock.
    state = State.open(queue, fake_cfg)
    with state.research_lock("s1"):
        with State.open(queue, fake_cfg).research_lock("s2"):
            assert _research_lock_file(state, "s2").is_file()
        State.open(queue, fake_cfg).lock()


# Behavior 2: `mark_done` also calls the work of `drop_map`.


def test_mark_done_clears_the_research_session_and_deletes_the_map(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: `mark_done` leaves the researcher's session or the map file behind.
    state = State.open(queue, fake_cfg)
    state.set_research_session("s1", "research-a")
    path = _save_map(state, "s1")
    state.mark_done("s1")
    assert not path.exists()
    section = State.open(queue, fake_cfg).section("s1")
    assert section.status == "done"
    assert section.research_session is None


def test_mark_done_leaves_other_sections_maps_and_sessions(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: `mark_done` drops every section's research, not only its own.
    state = State.open(queue, fake_cfg)
    state.set_research_session("s1", "research-a")
    state.set_research_session("s2", "research-b")
    _save_map(state, "s1")
    other = _save_map(state, "s2")
    state.mark_done("s1")
    assert other.read_bytes() == MAP_FIXTURE.read_bytes()
    assert State.open(queue, fake_cfg).section("s2").research_session == "research-b"


def test_mark_done_with_a_session_and_no_map_file_clears_the_session(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: `mark_done` raises on an absent map, or keeps the session when there is no map.
    state = State.open(queue, fake_cfg)
    state.set_research_session("s1", "research-a")
    state.mark_done("s1")
    section = State.open(queue, fake_cfg).section("s1")
    assert section.status == "done"
    assert section.research_session is None


# Relay's ladder (design: docs/superpowers/specs/relay-ladder-design.md, Modules `relay/state.py`; Order 4).
# Behavior 2: design_changed: this section had a design change, or a design-change recut made it.


def test_mark_design_changed_is_kept_for_that_section_only(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: the flag is not saved across reopening, or is set on another section too.
    State.open(queue, fake_cfg).mark_design_changed("s1.1")
    state = State.open(queue, fake_cfg)
    assert state.section("s1.1").design_changed is True
    assert state.section("s1").design_changed is False


def test_mark_design_changed_leaves_from_recut_alone(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: the design-change flag is stored in, or also sets, the recut lineage flag.
    state = State.open(queue, fake_cfg)
    state.mark_design_changed("s1")
    state.mark_from_recut("s2")
    reopened = State.open(queue, fake_cfg)
    assert reopened.section("s1").from_recut is False
    assert reopened.section("s1").design_changed is True
    assert reopened.section("s2").from_recut is True
    assert reopened.section("s2").design_changed is False


def test_a_record_saved_before_the_ladder_loads_with_its_fields_at_their_defaults(
    queue: Path, fake_cfg: Config
) -> None:
    # Breaks when: a state.json from an older relay, without the ladder's keys, no longer loads.
    state = State.open(queue, fake_cfg)
    old = '{"sections": {"s1": {"status": "parked", "failures": 1, "question": "q", "answer": null, "last_session": null}}, "last_any": null}'
    (_dir(state) / "state.json").write_text(old)
    state.mark_design_changed("s2")
    section = State.open(queue, fake_cfg).section("s1")
    assert section.status == "parked"
    assert section.design_changed is False
    assert section.design_open is None
    assert section.waits_on is None


# Behavior 3: design_open: the design path whose product decision awaits the owner's answer.

DESIGN = "docs/superpowers/specs/relay-check-design.md"


def test_set_design_open_keeps_the_path_for_that_section_across_reopening(
    queue: Path, fake_cfg: Config
) -> None:
    # Breaks when: the design path is not saved, is altered, or is set on another section too.
    State.open(queue, fake_cfg).set_design_open("s3", DESIGN)
    state = State.open(queue, fake_cfg)
    assert state.section("s3").design_open == DESIGN
    assert state.section("s1").design_open is None


def test_set_design_open_none_clears_it(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: a None design is ignored and the old path kept.
    state = State.open(queue, fake_cfg)
    state.set_design_open("s3", DESIGN)
    state.set_design_open("s3", None)
    assert State.open(queue, fake_cfg).section("s3").design_open is None


# Behavior 4: wait: status "waiting", waits_on blocker; no question.


def test_wait_sets_status_waiting_and_the_blocker_across_reopening(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: wait does not set "waiting", does not save the blocker, or touches another section.
    State.open(queue, fake_cfg).wait("s3", "s2")
    state = State.open(queue, fake_cfg)
    assert state.section("s3").status == "waiting"
    assert state.section("s3").waits_on == "s2"
    assert state.section("s2").status == "open"
    assert state.section("s2").waits_on is None


def test_wait_sets_no_question(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: wait parks a question for the owner, as park does.
    State.open(queue, fake_cfg).wait("s3", "s2")
    assert State.open(queue, fake_cfg).section("s3").question is None


# Behavior 5: wake: status "open", waits_on None.


def test_wake_reopens_a_waiting_section_and_clears_its_blocker(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: wake leaves the section waiting or keeps waits_on.
    state = State.open(queue, fake_cfg)
    state.wait("s3", "s2")
    state.wake("s3")
    section = State.open(queue, fake_cfg).section("s3")
    assert section.status == "open"
    assert section.waits_on is None


def test_wake_leaves_other_waiting_sections_waiting(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: wake reopens every waiting section, not only the one named.
    state = State.open(queue, fake_cfg)
    state.wait("s3", "s2")
    state.wait("s4", "s2")
    state.wake("s3")
    section = State.open(queue, fake_cfg).section("s4")
    assert section.status == "waiting"
    assert section.waits_on == "s2"


# Behavior 6: `set_answer` also reopens a waiting section and clears `waits_on`.
# `mark_done` clears `design_open` and `waits_on`.


def test_set_answer_on_a_waiting_section_reopens_it_and_clears_waits_on(
    queue: Path, fake_cfg: Config
) -> None:
    # Breaks when: set_answer leaves a waiting section waiting, or keeps its blocker.
    state = State.open(queue, fake_cfg)
    state.wait("s3", "s2")
    state.set_answer("s3", "Go on without s2.")
    section = State.open(queue, fake_cfg).section("s3")
    assert section.status == "open"
    assert section.waits_on is None
    assert section.answer == "Go on without s2."


def test_mark_done_clears_design_open(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: mark_done leaves the open design path set.
    state = State.open(queue, fake_cfg)
    state.set_design_open("s3", DESIGN)
    state.mark_done("s3")
    section = State.open(queue, fake_cfg).section("s3")
    assert section.status == "done"
    assert section.design_open is None


def test_mark_done_clears_waits_on(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: mark_done leaves the section's blocker set.
    state = State.open(queue, fake_cfg)
    state.wait("s3", "s2")
    state.mark_done("s3")
    section = State.open(queue, fake_cfg).section("s3")
    assert section.status == "done"
    assert section.waits_on is None
# Order 17, behavior 1: It holds ... the last session id and the last lead's final report per
# section (design: Modules, `relay/state.py`).
# Order 17, behavior 2: last_report: str | None = None  # RunResult.stream.result_text of the
# section's most recent lead run; a record without it loads as None
# Order 17, behavior 3: def set_last_report(self, sid: str, report: str | None) -> None: ...  # None clears it
# `getattr` with a default keeps a missing field or method an assertion failure, not an AttributeError.

REPORT_A = "Step 2 committed at 1a2b3c.\n  Next: step 3, the build.\nRETIRED"
REPORT_B = "Red tests written for s2.\nDONE"


def _set_last_report(state: State, sid: str, report: str | None) -> None:
    setter = getattr(state, "set_last_report", None)
    assert setter is not None, "State.set_last_report"
    setter(sid, report)


def test_a_section_with_no_record_has_no_last_report(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: SectionState has no last_report, or a fresh section's is not None.
    section = State.open(queue, fake_cfg).section("s1")
    assert getattr(section, "last_report", "missing") is None


def test_last_report_is_kept_per_section_verbatim_across_reopening(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: the report is not saved, is altered, or is kept for the queue rather than per section.
    state = State.open(queue, fake_cfg)
    _set_last_report(state, "s1", REPORT_A)
    _set_last_report(state, "s2", REPORT_B)
    reopened = State.open(queue, fake_cfg)
    assert getattr(reopened.section("s1"), "last_report", None) == REPORT_A
    assert getattr(reopened.section("s2"), "last_report", None) == REPORT_B
    assert getattr(reopened.section("s3"), "last_report", "missing") is None


def test_a_later_report_replaces_the_earlier_one(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: set_last_report keeps the first report, or appends the second to it.
    state = State.open(queue, fake_cfg)
    _set_last_report(state, "s1", REPORT_A)
    _set_last_report(state, "s1", REPORT_B)
    assert getattr(State.open(queue, fake_cfg).section("s1"), "last_report", None) == REPORT_B


def test_set_last_report_none_clears_it_for_that_section_only(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: None is ignored, stored as a string, or clears another section's report too.
    state = State.open(queue, fake_cfg)
    _set_last_report(state, "s1", REPORT_A)
    _set_last_report(state, "s2", REPORT_B)
    _set_last_report(state, "s1", None)
    reopened = State.open(queue, fake_cfg)
    assert getattr(reopened.section("s1"), "last_report", "missing") is None
    assert getattr(reopened.section("s2"), "last_report", None) == REPORT_B


def test_the_last_report_and_the_last_session_are_kept_side_by_side(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: setting one of the two overwrites or clears the other.
    state = State.open(queue, fake_cfg)
    state.set_last_session("s1", "session-a")
    _set_last_report(state, "s1", REPORT_A)
    state.set_last_session("s1", "session-b")
    section = State.open(queue, fake_cfg).section("s1")
    assert section.last_session == "session-b"
    assert getattr(section, "last_report", None) == REPORT_A


def test_a_record_saved_before_last_report_existed_loads_with_it_none(queue: Path, fake_cfg: Config) -> None:
    # Breaks when: a state.json from an older relay, without the key, no longer loads or loads a report.
    state = State.open(queue, fake_cfg)
    old = '{"sections": {"s1": {"status": "open", "failures": 1, "question": null, "answer": null, "last_session": "session-a"}}, "last_any": "session-a"}'
    (_dir(state) / "state.json").write_text(old)
    section = state.section("s1")
    assert section.last_session == "session-a"
    assert section.failures == 1
    assert getattr(section, "last_report", "missing") is None
