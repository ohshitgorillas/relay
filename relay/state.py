"""Relay's own record for one queue."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO, Callable, Iterator, Literal, TypeVar

from relay.config import Config
from relay.errors import LockedError

FAILURE_LIMIT = 2
CHECK_LIMIT = 3

SectionStatus = Literal["open", "done", "parked"]

_RECORD = "state.json"
_T = TypeVar("_T")


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


def _fresh() -> SectionState:
    return SectionState(status="open", failures=0, question=None, answer=None, last_session=None)


class State:
    def __init__(self, directory: Path):
        self._dir = directory
        self._lock_handle: IO[str] | None = None

    @classmethod
    def open(cls, queue: Path, cfg: Config) -> "State":
        absolute = queue.resolve()
        readable = re.sub(r"[^A-Za-z0-9._-]+", "-", str(absolute)).strip("-")
        digest = hashlib.sha256(str(absolute).encode()).hexdigest()[:16]
        slug = f"{readable[-80:]}-{digest}"
        directory = cfg.state_root / slug
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
        fd, tmp = tempfile.mkstemp(dir=self._dir, prefix=_RECORD + ".")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(record, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._dir / _RECORD)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

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

    def mark_done(self, sid: str) -> None:
        def change(s: SectionState, _r: dict) -> None:
            s.status = "done"
            s.question = None
            s.check_feedback = None
            s.check_pending = False
            s.research_session = None

        self._update(sid, change)
        self.map_path(sid).unlink(missing_ok=True)

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

    def park(self, sid: str, question: str) -> None:
        def change(s: SectionState, _r: dict) -> None:
            s.status = "parked"
            s.question = question

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
            s.status = "open"
            s.question = None
            return True

        return self._update(sid, change)

    def take_answer(self, sid: str) -> str | None:
        def change(s: SectionState, _r: dict) -> str | None:
            taken, s.answer = s.answer, None
            return taken

        return self._update(sid, change)

    def record_failure(self, sid: str) -> int:
        def change(s: SectionState, _r: dict) -> int:
            s.failures += 1
            return s.failures

        return self._update(sid, change)

    def set_last_session(self, sid: str, session: str) -> None:
        def change(s: SectionState, r: dict) -> None:
            s.last_session = session
            r["last_any"] = session

        self._update(sid, change)

    @property
    def last_session_any(self) -> str | None:
        return self._load()["last_any"]

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

    def set_research_session(self, sid: str, session: str | None) -> None:
        def change(s: SectionState, _r: dict) -> None:
            s.research_session = session

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
