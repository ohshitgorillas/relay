"""Red tests for Relay's state (design: Modules, `relay/state.py`; Order 7)."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Callable

import pytest

import relay.state as state_module
import relay.files as publication
from relay.config import Config
from relay.errors import LockedError
from relay.state import SectionState, State

QUEUE = "workboard-queue.md"


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
