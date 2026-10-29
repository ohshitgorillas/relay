"""Synthetic rollout edges using the design's documented Codex wire schema."""

import json
from pathlib import Path

import pytest

from relay.backends.codex_session import SessionReader
from relay.errors import RelayError
from relay.ledger import Spend
from relay.stream import StreamState


def test_context_uses_last_usage_and_can_fall_after_compaction(tmp_path: Path) -> None:
    # Breaks when cumulative spend substitutes for context or context cannot fall.
    sid = "01a1855b-7ba6-79d3-bf98-98c251634b5a"
    folder = tmp_path / "sessions" / "2026" / "10" / "29"
    folder.mkdir(parents=True)
    path = folder / f"rollout-2026-10-29T01-52-00-{sid}.jsonl"
    identity = {"type": "session_meta", "payload": {
        "id": sid, "session_id": "01a1855b-7ba6-79d3-bf98-98c251634b5b",
    }}
    event = json.loads((Path(__file__).parent / "fixtures/codex-real/token-count.jsonl").read_text())
    # Mutated usage is synthetic; the source capture has equal last/total usage.
    info = event["payload"]["info"]
    info["last_token_usage"]["total_tokens"] = 12000
    info["total_token_usage"]["total_tokens"] = 40000
    path.write_text(json.dumps(identity) + "\n" + json.dumps(event) + "\n")
    reader = SessionReader(tmp_path, sid)
    state = reader.poll(StreamState(sid, 0, Spend(0, 0.0), None, False))
    assert state.context_tokens == 12000
    assert state.spend.tokens == 40000
    info["last_token_usage"]["total_tokens"] = 3000
    info["total_token_usage"]["total_tokens"] = 45000
    with path.open("a") as stream:
        stream.write(json.dumps(event) + "\n")
    state = reader.poll(state)
    assert state.context_tokens == 3000
    assert state.spend.tokens == 45000
    assert reader.poll(state) == state


def test_discovered_rollout_io_failure_raises_chained_relay_error(tmp_path: Path) -> None:
    # Breaks when a discovered rollout's I/O failure returns stale telemetry.
    sid = "01a1855b-7ba6-79d3-bf98-98c251634b5a"
    folder = tmp_path / "sessions" / "2026" / "10" / "29"
    folder.mkdir(parents=True)
    path = folder / f"rollout-2026-10-29T01-52-00-{sid}.jsonl"
    identity = {"type": "session_meta", "payload": {"id": sid}}
    event = (Path(__file__).parent / "fixtures/codex-real/token-count.jsonl").read_text()
    path.write_text(json.dumps(identity) + "\n" + event + "\n")
    reader = SessionReader(tmp_path, sid)
    state = reader.poll(StreamState(sid, 0, Spend(0, 0.0), None, False))
    path.unlink()

    with pytest.raises(RelayError) as failure:
        reader.poll(state)

    assert isinstance(failure.value.__cause__, FileNotFoundError)


@pytest.mark.parametrize("io_error", [PermissionError("denied"), OSError("device failure")])
def test_discovery_open_failure_raises_chained_relay_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, io_error: OSError
) -> None:
    # Breaks when opening a discovery candidate silently swallows an I/O failure.
    sid = "01a1855b-7ba6-79d3-bf98-98c251634b5a"
    folder = tmp_path / "sessions" / "2026" / "10" / "29"
    folder.mkdir(parents=True)
    path = folder / f"rollout-2026-10-29T01-52-00-{sid}.jsonl"
    identity = {"type": "session_meta", "payload": {"id": sid}}
    path.write_text(json.dumps(identity) + "\n")
    original_open = Path.open

    def fail_candidate_open(candidate: Path, *args, **kwargs):
        if candidate == path:
            raise io_error
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_candidate_open)
    reader = SessionReader(tmp_path, sid)
    state = StreamState(sid, 0, Spend(0, 0.0), None, False)

    with pytest.raises(RelayError) as failure:
        reader.poll(state)

    assert failure.value.__cause__ is io_error
