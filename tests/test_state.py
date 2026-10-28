"""Red tests for Relay's state (design: Modules, `relay/state.py`; Order 7)."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import Callable

import pytest

import relay.state as state_module
from relay.config import Config
from relay.errors import LockedError
from relay.state import SectionState, State

QUEUE = "workboard-queue.md"


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
