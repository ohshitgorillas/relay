"""Synthetic rollout edges using the design's documented Codex wire schema."""

import json
from pathlib import Path

import pytest

from relay.backends.codex_session import SessionReader, rollout_boundary
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


def _billing_rollout(tmp_path: Path, sid: str) -> tuple[Path, dict]:
    """Synthetic identity and counts, derived from the documented captured envelope."""
    folder = tmp_path / "sessions" / "2026" / "10" / "29"
    folder.mkdir(parents=True)
    path = folder / f"rollout-2026-10-29T01-52-00-{sid}.jsonl"
    path.write_text(json.dumps({"type": "session_meta", "payload": {"id": sid}}) + "\n")
    event = json.loads(
        (Path(__file__).parent / "fixtures/codex-real/token-count.jsonl").read_text()
    )
    return path, event


@pytest.mark.parametrize("writes", [0, 400])
def test_billing_retains_known_counts_without_guessing_settings_or_write_duration(
    tmp_path: Path, writes: int,
) -> None:
    # Breaks when absent settings erase counts or undifferentiated writes get a guessed duration.
    sid = "01a1855b-7ba6-79d3-bf98-98c251634b5a"
    path, event = _billing_rollout(tmp_path, sid)
    event["payload"]["info"]["total_token_usage"]["cache_write_input_tokens"] = writes
    with path.open("a") as stream:
        stream.write(json.dumps(event) + "\n")
    reader = SessionReader(tmp_path, sid, boundary={})
    state = reader.poll(StreamState(sid, 0, Spend(0, 0.0), None, False))
    assert hasattr(reader, "models"), "reader must expose normalized model observations"
    assert reader.models == ("unavailable",)
    assert reader.efforts == ("unavailable",)
    assert len(reader.usage) == 1
    usage = reader.usage[0]
    assert (usage.thread, usage.cached_input, usage.output) == (
        sid, 7168, 11,
    )
    assert reader.unavailable or usage.unavailable
    if writes:
        assert usage.cache_write_30m is None
        assert usage.cache_write_12h is None
    else:
        assert usage.input == 27196
    assert reader.poll(state) == state
    assert reader.usage == (usage,)


def test_billing_resume_prices_only_new_cumulative_delta(tmp_path: Path) -> None:
    # Breaks when resumed cumulative snapshots bill previously ledgered input again.
    sid = "01a1855b-7ba6-79d3-bf98-98c251634b5a"
    path, event = _billing_rollout(tmp_path, sid)
    with path.open("a") as stream:
        stream.write(json.dumps(event) + "\n")
    boundary = rollout_boundary(tmp_path, sid)
    reader = SessionReader(tmp_path, sid, boundary=boundary)
    total = event["payload"]["info"]["total_token_usage"]
    total.update(input_tokens=28196, cached_input_tokens=7668, output_tokens=31, total_tokens=28227)
    with path.open("a") as stream:
        stream.write(json.dumps(event) + "\n")
    state = reader.poll(StreamState(sid, 0, Spend(0, 0.0), None, False))
    assert hasattr(reader, "usage"), "reader must expose invocation usage"
    assert len(reader.usage) == 1
    usage = reader.usage[0]
    assert (usage.input, usage.cached_input, usage.output) == (1000, 500, 20)
    assert state.spend.tokens == 1020
    reader.poll(state)
    assert reader.usage == (usage,)


@pytest.mark.parametrize("problem", ["missing_cached", "counter_reset"])
def test_billing_incomplete_dimensions_or_reset_remain_unavailable(
    tmp_path: Path, problem: str,
) -> None:
    # Breaks when missing cached reads or unexplained resets become a complete numeric bill.
    sid = "01a1855b-7ba6-79d3-bf98-98c251634b5a"
    path, event = _billing_rollout(tmp_path, sid)
    with path.open("a") as stream:
        stream.write(json.dumps(event) + "\n")
    reader = SessionReader(tmp_path, sid, boundary={})
    state = reader.poll(StreamState(sid, 0, Spend(0, 0.0), None, False))
    total = event["payload"]["info"]["total_token_usage"]
    if problem == "missing_cached":
        total.pop("cached_input_tokens")
    else:
        total.update(input_tokens=10, cached_input_tokens=5, output_tokens=1, total_tokens=11)
    with path.open("a") as stream:
        stream.write(json.dumps(event) + "\n")
    reader.poll(state)
    assert hasattr(reader, "usage"), "reader must retain known usage when pricing is incomplete"
    assert reader.usage
    assert reader.unavailable
    assert all(row.input >= 0 and row.output >= 0 for row in reader.usage)
    reason = " ".join([reader.unavailable, *(row.unavailable or "" for row in reader.usage)]).lower()
    assert "cache" in reason if problem == "missing_cached" else any(
        word in reason for word in ("reset", "counter", "baseline")
    )


def test_billing_resume_without_baseline_is_explicitly_unavailable(tmp_path: Path) -> None:
    # Breaks when a resumed rollout with no historical token baseline prices the whole cumulative total.
    sid = "01a1855b-7ba6-79d3-bf98-98c251634b5a"
    path, event = _billing_rollout(tmp_path, sid)
    reader = SessionReader(tmp_path, sid, boundary=rollout_boundary(tmp_path, sid))
    with path.open("a") as stream:
        stream.write(json.dumps(event) + "\n")
    reader.poll(StreamState(sid, 0, Spend(0, 0.0), None, False))
    assert hasattr(reader, "unavailable"), "reader must expose missing resume baselines"
    assert reader.unavailable
    reason = " ".join([reader.unavailable, *(row.unavailable or "" for row in reader.usage)]).lower()
    assert "baseline" in reason


def test_billing_model_transitions_attribute_only_cumulative_deltas(tmp_path: Path) -> None:
    # Breaks when a new model takes ownership of earlier totals or repeated snapshots add a second bill.
    # Field evidence: fixtures/cache-cost/telemetry-evidence.md; every generated record is synthetic.
    sid = "01a1855b-7ba6-79d3-bf98-98c251634b5a"
    path, event = _billing_rollout(tmp_path, sid)
    total = event["payload"]["info"]["total_token_usage"]
    total.update(input_tokens=1000, cached_input_tokens=800, output_tokens=100, total_tokens=1100)
    first_context = {"type": "turn_context", "payload": {"model": "gpt-6.1-sol", "effort": "high"}}
    with path.open("a") as stream:
        stream.write(json.dumps(first_context) + "\n" + json.dumps(event) + "\n")
    reader = SessionReader(tmp_path, sid, boundary={})
    state = reader.poll(StreamState(sid, 0, Spend(0, 0.0), None, False))
    total.update(input_tokens=1500, cached_input_tokens=900, output_tokens=150, total_tokens=1650)
    second_context = {"type": "turn_context", "payload": {"model": "gpt-6-astra", "effort": "medium"}}
    with path.open("a") as stream:
        stream.write(json.dumps(second_context) + "\n" + json.dumps(event) + "\n" + json.dumps(event) + "\n")
    state = reader.poll(state)
    assert hasattr(reader, "usage"), "reader must expose per-model usage"
    assert [(row.model, row.input, row.cached_input, row.output) for row in reader.usage] == [
        ("gpt-6.1-sol", 1000, 800, 100), ("gpt-6-astra", 500, 100, 50),
    ]
    assert reader.models == ("gpt-6.1-sol", "gpt-6-astra")
    assert reader.efforts == ("high", "medium")
    before = reader.usage
    reader.poll(state)
    assert reader.usage == before


def test_billing_missing_turn_setting_keeps_explicit_unavailable_marker(tmp_path: Path) -> None:
    # Breaks when a later turn with absent settings silently inherits the prior model or effort.
    # Field evidence: fixtures/cache-cost/telemetry-evidence.md; both turn records are synthetic.
    sid = "01a1855b-7ba6-79d3-bf98-98c251634b5a"
    path, event = _billing_rollout(tmp_path, sid)
    with path.open("a") as stream:
        stream.write(json.dumps({"type": "turn_context", "payload": {"model": "gpt-6.1-sol", "effort": "high"}}) + "\n")
        stream.write(json.dumps(event) + "\n")
    reader = SessionReader(tmp_path, sid, boundary={})
    state = reader.poll(StreamState(sid, 0, Spend(0, 0.0), None, False))
    total = event["payload"]["info"]["total_token_usage"]
    total.update(input_tokens=28196, cached_input_tokens=7668, output_tokens=31, total_tokens=28227)
    with path.open("a") as stream:
        stream.write(json.dumps({"type": "turn_context", "payload": {}}) + "\n")
        stream.write(json.dumps(event) + "\n")
    reader.poll(state)
    assert hasattr(reader, "models"), "reader must retain unknown turn settings"
    assert reader.models == ("gpt-6.1-sol", "unavailable")
    assert reader.efforts == ("high", "unavailable")
    assert reader.unavailable or any(row.unavailable for row in reader.usage)


@pytest.mark.parametrize("missing,dimension", [
    ("cached_input_tokens", "cache"),
    ("output_tokens", "output"),
])
def test_incomplete_billing_keeps_running_total_token_observations(
    tmp_path: Path, missing: str, dimension: str,
) -> None:
    # Breaks when an unavailable billing dimension freezes otherwise valid live total-token accounting.
    sid = "01a1855b-7ba6-79d3-bf98-98c251634b5a"
    path, event = _billing_rollout(tmp_path, sid)
    with path.open("a") as stream:
        stream.write(json.dumps(event) + "\n")
    reader = SessionReader(tmp_path, sid, boundary={})
    state = reader.poll(StreamState(sid, 0, Spend(0, 0.0), None, False))
    assert state.spend.tokens == 27207

    total = event["payload"]["info"]["total_token_usage"]
    total.update(input_tokens=28196, cached_input_tokens=7668, output_tokens=31, total_tokens=28227)
    total.pop(missing)
    with path.open("a") as stream:
        stream.write(json.dumps(event) + "\n")
    state = reader.poll(state)
    assert state.spend.tokens == 28227, "incomplete billing must retain the valid cumulative token total"
    assert reader.unavailable
    reasons = " ".join([reader.unavailable, *(row.unavailable or "" for row in reader.usage)]).lower()
    assert dimension in reasons
    assert reader.poll(state).spend.tokens == 28227
