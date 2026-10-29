"""Shared atomic byte publication."""

import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, data: bytes, *, mode: int | None = None) -> None:
    """Publish complete bytes without exposing a partially written destination."""
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            if mode is not None:
                os.fchmod(handle.fileno(), mode)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
