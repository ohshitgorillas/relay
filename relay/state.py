"""Relay's own record for one queue."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO, Callable, Iterator, Literal, TypeVar

from relay.config import Config
from relay.errors import LockedError
from relay.files import atomic_write

FAILURE_LIMIT = 2

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
    last_report: str | None = None


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
        atomic_write(self._dir / _RECORD, json.dumps(record).encode("utf-8"))

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

        self._update(sid, change)

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

    def set_last_report(self, sid: str, report: str | None) -> None:
        def change(s: SectionState, _r: dict) -> None:
            s.last_report = report

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

    @property
    def retire_flag(self) -> Path:
        return self.run_dir / "retire"
