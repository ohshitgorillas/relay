"""Atomic byte publication contract from relay-backends-design Modules."""

import os
import stat
from pathlib import Path

import pytest

from relay.files import atomic_write


@pytest.mark.parametrize("mode", [None, 0o640])
def test_complete_private_or_mode_preserving_publication(tmp_path, monkeypatch, mode):
    # Breaks when replacement precedes flush/fsync, changes bytes, or loses permissions.
    destination = tmp_path / "published"
    destination.write_bytes(b"preceding")
    payload = b"new\x00\xff\n" * 10000
    synced = []
    candidates = []
    real_sync, real_replace = os.fsync, os.replace

    def sync(fd):
        synced.append(os.fstat(fd).st_ino)
        real_sync(fd)

    def replace(source, target):
        candidate = Path(source)
        assert Path(target) == destination
        assert candidate.parent == destination.parent
        assert candidate != destination
        assert candidate.read_bytes() == payload
        assert candidate.stat().st_ino in synced
        assert destination.read_bytes() == (payload if candidates else b"preceding")
        candidates.append(candidate)
        real_replace(source, target)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", replace)
    atomic_write(destination, payload, mode=mode)
    atomic_write(destination, payload, mode=mode)
    assert len(set(candidates)) == 2
    assert destination.read_bytes() == payload
    assert stat.S_IMODE(destination.stat().st_mode) == (0o600 if mode is None else mode)
    assert set(tmp_path.iterdir()) == {destination}


@pytest.mark.parametrize("stage", ["fsync", "replace"])
def test_interruption_propagates_and_cleans_temporary_file(tmp_path, monkeypatch, stage):
    # Breaks when an interrupted publication succeeds, removes prior bytes, or leaks a temp.
    destination = tmp_path / "published"
    destination.write_bytes(b"preceding")
    failure = OSError("publication interrupted")

    def fail(*args):
        raise failure

    monkeypatch.setattr(os, stage, fail)
    with pytest.raises(OSError) as caught:
        atomic_write(destination, b"replacement")
    assert caught.value is failure
    assert destination.read_bytes() == b"preceding"
    assert set(tmp_path.iterdir()) == {destination}
