"""Relay's own record for one queue."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import IO, Callable, Iterator, Literal, TypeVar

from relay.config import Config
from relay.errors import LockedError
from relay.files import atomic_write

FAILURE_LIMIT = 2
CHECK_LIMIT = 3
DESIGN_FAILURE_LIMIT = 2

SectionStatus = Literal["open", "done", "parked", "waiting"]

_RECORD = "state.json"
_T = TypeVar("_T")


@dataclass(frozen=True)
class LiveRun:
    pid: int
    draining: bool
    draining_since: float | None


@dataclass(frozen=True)
class Pending:
    """A dispatch a drain held back after the result it follows was recorded."""

    kind: Literal["climb", "design-retry", "design-recut"]
    lead_log: str
    problem: str
    status: Literal["RECUT", "DESIGN"] | None = None
    text: str | None = None
    design: str | None = None
    brief: str | None = None


@dataclass
class SectionState:
    status: SectionStatus
    failures: int
    question: str | None
    answer: str | None
    last_session: str | None
    from_recut: bool = False
    check_failures: int = 0
    check_feedback: str | None = None
    check_pending: bool = False
    research_session: str | None = None  # the researcher a follow-up resumes
    last_log: str | None = None  # the run log of the section's last lead run
    design_changed: bool = False  # this section had a design change, or a design-change recut made it
    design_open: str | None = None  # the design path whose product decision awaits the owner's answer
    # The open decision numbers of the park now awaiting that answer; None when the section's
    # current park (or run) is for another reason, so an answer to it is not a design answer.
    design_numbers: list[int] | None = None
    waits_on: str | None = None  # the section id a waiting section waits for
    last_report: str | None = None
    last_backend: str = "claude"
    research_backend: str = "claude"
    answers: list[str] = field(default_factory=list)  # every owner answer to this section, in order
    guidance: str | None = None  # a reportless architect's final message, for the next lead
    design_failures: int = 0
    design_failure: str | None = None
    worktree_branch: str | None = None
    worktree_path: str | None = None
    pending: dict | None = None


def numbered_logs(run_dir: Path) -> list[Path]:
    """The numbered `<n>.jsonl` run logs in `run_dir`, ascending by number."""
    return sorted((p for p in run_dir.glob("*.jsonl") if p.stem.isdigit()), key=lambda p: int(p.stem))


def queue_id(queue: Path) -> str:
    """SHA-256 hex digest of the resolved queue path."""
    return hashlib.sha256(str(queue.resolve()).encode()).hexdigest()


def queue_key(queue: Path) -> str:
    """The existing readable resolved-path suffix and 16-character hash suffix."""
    readable = re.sub(r"[^A-Za-z0-9._-]+", "-", str(queue.resolve())).strip("-")
    return f"{readable[-80:]}-{queue_id(queue)[:16]}"


def write_atomic(path: Path, text: str) -> None:
    """Publish UTF-8 text through the shared atomic byte writer."""
    atomic_write(path, text.encode("utf-8"))


def _fresh() -> SectionState:
    return SectionState(status="open", failures=0, question=None, answer=None, last_session=None)


class State:
    def __init__(self, directory: Path):
        self._dir = directory
        self._lock_handle: IO[str] | None = None

    def run_logs(self) -> list[Path]:
        return numbered_logs(self.run_dir)

    @classmethod
    def all(cls, cfg: Config) -> list["State"]:
        """Each directory under `cfg.state_root` holding a ledger.jsonl."""
        try:
            children = sorted(cfg.state_root.iterdir())
        except OSError:
            return []
        return [cls(d) for d in children if (d / "ledger.jsonl").is_file()]

    @property
    def run_record(self) -> Path:
        return self._dir / "run.json"

    def publish_run(self, pid: int) -> None:
        write_atomic(self.run_record, json.dumps(asdict(LiveRun(pid, False, None))))

    def mark_draining(self) -> None:
        try:
            record = json.loads(self.run_record.read_text())
        except (OSError, ValueError):
            return
        if record["draining"]:
            return
        record["draining"] = True
        record["draining_since"] = time.time()
        write_atomic(self.run_record, json.dumps(record))

    def clear_run(self) -> None:
        self.run_record.unlink(missing_ok=True)

    def live_run(self) -> LiveRun | None:
        with open(self._dir / "lock", "a") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                return None
        try:
            return LiveRun(**json.loads(self.run_record.read_text()))
        except (OSError, ValueError, TypeError):
            return None

    def set_pending(self, sid: str, pending: Pending) -> None:
        def change(s: SectionState, _r: dict) -> None:
            s.pending = asdict(pending)

        self._update(sid, change)

    def take_pending(self, sid: str) -> Pending | None:
        def change(s: SectionState, _r: dict) -> Pending | None:
            taken = Pending(**s.pending) if s.pending is not None else None
            s.pending = None
            return taken

        return self._update(sid, change)

    @classmethod
    def open(cls, queue: Path, cfg: Config) -> "State":
        directory = cfg.state_root / queue_key(queue)
        directory.mkdir(parents=True, exist_ok=True)
        return cls(directory)

    def lock(self) -> None:
        handle = open(self._dir / "lock", "a")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise LockedError(f"another relay go holds {self._dir}") from exc
        except OSError:
            handle.close()
            raise
        self._lock_handle = handle

    def _load(self) -> dict:
        try:
            return json.loads((self._dir / _RECORD).read_text())
        except FileNotFoundError:
            return {"sections": {}, "last_any": None}

    def _save(self, record: dict) -> None:
        write_atomic(self._dir / _RECORD, json.dumps(record))

    @contextlib.contextmanager
    def _write_guard(self) -> Iterator[None]:
        """Serialize read-modify-write across processes (separate from the `relay go` lock)."""
        with open(self._dir / "write.lock", "a") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield

    def _update(
        self, sid: str, change: Callable[[SectionState, dict], _T]
    ) -> _T:
        with self._write_guard():
            record = self._load()
            section = SectionState(**record["sections"].get(sid, asdict(_fresh())))
            result = change(section, record)
            record["sections"][sid] = asdict(section)
            self._save(record)
            return result

    def section(self, sid: str) -> SectionState:
        data = self._load()["sections"].get(sid)
        return SectionState(**data) if data else _fresh()

    def bind_worktree(self, sid: str, branch: str, path: Path) -> None:
        """Atomically persist the validated branch and absolute worktree path together."""
        absolute = str(path.resolve())

        def change(s: SectionState, _r: dict) -> None:
            s.worktree_branch = branch
            s.worktree_path = absolute

        self._update(sid, change)

    def mark_done(self, sid: str) -> None:
        def change(s: SectionState, _r: dict) -> None:
            s.status = "done"
            s.question = None
            s.check_feedback = None
            s.check_pending = False
            s.design_open = None
            s.design_numbers = None
            s.waits_on = None
            s.design_failures = 0
            s.design_failure = None

        self._update(sid, change)
        self.drop_map(sid)

    def record_check_failure(self, sid: str, feedback: str) -> int:
        def change(s: SectionState, _r: dict) -> int:
            s.check_failures += 1
            s.check_feedback = feedback
            return s.check_failures

        return self._update(sid, change)

    def take_check_feedback(self, sid: str) -> str | None:
        def change(s: SectionState, _r: dict) -> str | None:
            taken, s.check_feedback = s.check_feedback, None
            return taken

        return self._update(sid, change)

    def set_check_pending(self, sid: str, pending: bool) -> None:
        def change(s: SectionState, _r: dict) -> None:
            s.check_pending = pending

        self._update(sid, change)

    def check_log(self, run_log: Path) -> Path:
        return run_log.with_suffix(".check")

    def rejected_cut(self, run_log: Path) -> Path:
        """Where a recut's rejected cut is kept: beside the recut's run log."""
        return run_log.with_suffix(".rejected")

    def set_last_log(self, sid: str, log: Path) -> None:
        def change(s: SectionState, _r: dict) -> None:
            s.last_log = str(log)

        self._update(sid, change)

    def pending_check_log(self, sid: str) -> Path:
        """The check log of a pending check on `sid`: beside its last lead run's log, or with no
        lead run recorded, the section's own runs/check-<sid>.check."""
        recorded = self.section(sid).last_log
        if recorded:
            return self.check_log(Path(recorded))
        return self.run_dir / f"check-{sid}.check"

    def park(
        self, sid: str, question: str, design: tuple[str, tuple[int, ...]] | None = None
    ) -> None:
        """Park `sid` on `question`. `design` is the design path and the open decision numbers when
        the question is the open design decisions': both are written with the park, one record. Any
        other park clears both, so no design decision is recorded as waiting and its answer is no
        design answer."""

        def change(s: SectionState, _r: dict) -> None:
            s.status = "parked"
            s.question = question
            if design is None:
                s.design_open = None
                s.design_numbers = None
            else:
                s.design_open = design[0]
                s.design_numbers = list(design[1])

        self._update(sid, change)

    def mark_design_changed(self, sid: str) -> None:
        def change(s: SectionState, _r: dict) -> None:
            s.design_changed = True

        self._update(sid, change)

    def set_design_open(self, sid: str, design: str | None) -> None:
        def change(s: SectionState, _r: dict) -> None:
            s.design_open = design
            if design is None:
                s.question = None
                s.design_numbers = None

        self._update(sid, change)

    def wait(self, sid: str, blocker: str) -> None:
        """Status "waiting", waits_on blocker; no question."""

        def change(s: SectionState, _r: dict) -> None:
            s.status = "waiting"
            s.waits_on = blocker
            s.question = None

        self._update(sid, change)

    def wake(self, sid: str) -> None:
        """Status "open", waits_on None."""

        def change(s: SectionState, _r: dict) -> None:
            s.status = "open"
            s.waits_on = None

        self._update(sid, change)

    def mark_from_recut(self, sid: str) -> None:
        def change(s: SectionState, _r: dict) -> None:
            s.from_recut = True

        self._update(sid, change)

    def set_answer(self, sid: str, answer: str) -> bool:
        """Record `answer` and reopen `sid`; False, recording nothing, when `sid` is done."""

        def change(s: SectionState, _r: dict) -> bool:
            if s.status == "done":
                return False
            s.answer = answer
            s.answers.append(answer)
            s.status = "open"
            s.question = None
            s.waits_on = None
            s.design_failures = 0
            s.design_failure = None
            return True

        return self._update(sid, change)

    def take_answer(self, sid: str) -> str | None:
        def change(s: SectionState, _r: dict) -> str | None:
            taken, s.answer = s.answer, None
            return taken

        return self._update(sid, change)

    def set_guidance(self, sid: str, guidance: str) -> None:
        def change(s: SectionState, _r: dict) -> None:
            s.guidance = guidance

        self._update(sid, change)

    def take_guidance(self, sid: str) -> str | None:
        def change(s: SectionState, _r: dict) -> str | None:
            taken, s.guidance = s.guidance, None
            return taken

        return self._update(sid, change)

    def record_failure(self, sid: str) -> int:
        def change(s: SectionState, _r: dict) -> int:
            s.failures += 1
            return s.failures

        return self._update(sid, change)

    def record_design_failure(self, sid: str, reason: str) -> int:
        """Atomically increment design_failures and store reason; return the new count."""
        def change(s: SectionState, _r: dict) -> int:
            s.design_failures += 1
            s.design_failure = reason
            return s.design_failures

        return self._update(sid, change)

    def clear_design_failures(self, sid: str) -> None:
        """Atomically clear the count and reason for this section."""
        def change(s: SectionState, _r: dict) -> None:
            s.design_failures = 0
            s.design_failure = None

        self._update(sid, change)

    def set_last_session(self, sid: str, session: str, backend: str = "claude") -> None:
        def change(s: SectionState, r: dict) -> None:
            s.last_session = session
            s.last_backend = backend
            r["last_any"] = session
            r["last_any_backend"] = backend

        self._update(sid, change)

    def set_last_report(self, sid: str, report: str | None) -> None:
        def change(s: SectionState, _r: dict) -> None:
            s.last_report = report

        self._update(sid, change)

    @property
    def last_session_any(self) -> str | None:
        return self._load()["last_any"]

    @property
    def last_backend_any(self) -> str:
        return self._load().get("last_any_backend", "claude")

    @property
    def stop_file(self) -> Path:
        return self._dir / "STOP"

    @property
    def run_dir(self) -> Path:
        return self._dir / "runs"

    @property
    def ledger_path(self) -> Path:
        return self._dir / "ledger.jsonl"

    def map_path(self, sid: str) -> Path:
        """<dir>/maps/<sid>.map"""
        return self._dir / "maps" / f"{sid}.map"

    def research_flag(self, sid: str) -> Path:
        """run_dir / "research-<sid>": the research runs' retire flag."""
        return self.run_dir / f"research-{sid}"

    def set_research_session(self, sid: str, session: str | None, backend: str = "claude") -> None:
        def change(s: SectionState, _r: dict) -> None:
            s.research_session = session
            s.research_backend = backend

        self._update(sid, change)

    def drop_map(self, sid: str) -> None:
        """Clear research_session and delete map_path(sid)."""
        self.set_research_session(sid, None)
        self.map_path(sid).unlink(missing_ok=True)

    @contextlib.contextmanager
    def research_lock(self, sid: str) -> Iterator[None]:
        """Blocking flock on <dir>/research-<sid>.lock."""
        with open(self._dir / f"research-{sid}.lock", "a") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield

    @property
    def retire_flag(self) -> Path:
        return self.run_dir / "retire"
