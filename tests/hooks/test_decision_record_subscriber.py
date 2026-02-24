"""Unit tests for the decision record subscriber (OMN-2720).

Tests the full pipeline from raw Kafka payload → JSONL audit log append:
- Payload deserialization (_parse_decision_record)
- Field validation and filtering (process_decision_record_event)
- Audit log persistence (_append_audit_record)
- Edge cases: missing fields, malformed payloads, empty input

All tests run without network access, Kafka, or external services.
Kafka consumer integration is not tested here — that path requires a live broker.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from omniclaude.hooks.lib.decision_record_subscriber import (
    DECISION_RECORDED_CMD_TOPIC,
    _append_audit_record,
    _parse_decision_record,
    process_decision_record_event,
    run_subscriber_background,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DECISION_ID = "dec-test-001"
_DECISION_TYPE = "model_select"
_SELECTED = "claude-opus-4-6"


def _make_decision_payload(
    *,
    decision_id: str = _DECISION_ID,
    decision_type: str = _DECISION_TYPE,
    selected_candidate: str = _SELECTED,
    agent_rationale: str | None = "Selected for coding expertise.",
    reproducibility_snapshot: dict[str, str] | None = None,
    session_id: str | None = "sess-abc",
    emitted_at: str = "2026-02-24T17:00:00Z",
) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "decision_type": decision_type,
        "timestamp": "2026-02-24T17:00:00Z",
        "candidates_considered": [selected_candidate, "claude-sonnet-4-6"],
        "constraints_applied": {"context_length": "64k"},
        "scoring_breakdown": [
            {"candidate": selected_candidate, "score": 0.92, "breakdown": {}},
        ],
        "tie_breaker": None,
        "selected_candidate": selected_candidate,
        "agent_rationale": agent_rationale,
        "reproducibility_snapshot": reproducibility_snapshot or {},
        "session_id": session_id,
        "emitted_at": emitted_at,
    }


def _to_raw(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# DECISION_RECORDED_CMD_TOPIC constant
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_topic_constant() -> None:
    """DECISION_RECORDED_CMD_TOPIC must match the canonical wire name."""
    assert (
        DECISION_RECORDED_CMD_TOPIC == "onex.cmd.omniintelligence.decision-recorded.v1"
    )


# ---------------------------------------------------------------------------
# _parse_decision_record
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_valid_payload() -> None:
    payload = _make_decision_payload()
    result = _parse_decision_record(_to_raw(payload))
    assert result is not None
    assert result["decision_id"] == _DECISION_ID
    assert result["decision_type"] == _DECISION_TYPE
    assert result["selected_candidate"] == _SELECTED


@pytest.mark.unit
def test_parse_invalid_json_returns_none() -> None:
    result = _parse_decision_record(b"not-json")
    assert result is None


@pytest.mark.unit
def test_parse_non_dict_returns_none() -> None:
    result = _parse_decision_record(b'["list", "not", "dict"]')
    assert result is None


@pytest.mark.unit
def test_parse_empty_bytes_returns_none() -> None:
    result = _parse_decision_record(b"")
    assert result is None


@pytest.mark.unit
def test_parse_invalid_utf8_returns_none() -> None:
    result = _parse_decision_record(b"\xff\xfe")
    assert result is None


# ---------------------------------------------------------------------------
# process_decision_record_event — validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_process_missing_decision_id_returns_false(tmp_path: Path) -> None:
    payload = _make_decision_payload()
    del payload["decision_id"]
    with patch.dict(
        "os.environ", {"OMNICLAUDE_DECISION_AUDIT_LOG": str(tmp_path / "audit.jsonl")}
    ):
        result = process_decision_record_event(_to_raw(payload))
    assert result is False


@pytest.mark.unit
def test_process_missing_decision_type_returns_false(tmp_path: Path) -> None:
    payload = _make_decision_payload()
    del payload["decision_type"]
    with patch.dict(
        "os.environ", {"OMNICLAUDE_DECISION_AUDIT_LOG": str(tmp_path / "audit.jsonl")}
    ):
        result = process_decision_record_event(_to_raw(payload))
    assert result is False


@pytest.mark.unit
def test_process_missing_selected_candidate_returns_false(tmp_path: Path) -> None:
    payload = _make_decision_payload()
    del payload["selected_candidate"]
    with patch.dict(
        "os.environ", {"OMNICLAUDE_DECISION_AUDIT_LOG": str(tmp_path / "audit.jsonl")}
    ):
        result = process_decision_record_event(_to_raw(payload))
    assert result is False


@pytest.mark.unit
def test_process_empty_raw_returns_false(tmp_path: Path) -> None:
    with patch.dict(
        "os.environ", {"OMNICLAUDE_DECISION_AUDIT_LOG": str(tmp_path / "audit.jsonl")}
    ):
        result = process_decision_record_event(b"")
    assert result is False


@pytest.mark.unit
def test_process_malformed_json_returns_false(tmp_path: Path) -> None:
    with patch.dict(
        "os.environ", {"OMNICLAUDE_DECISION_AUDIT_LOG": str(tmp_path / "audit.jsonl")}
    ):
        result = process_decision_record_event(b"{bad json")
    assert result is False


# ---------------------------------------------------------------------------
# process_decision_record_event — persistence
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_process_valid_payload_writes_audit_log(tmp_path: Path) -> None:
    audit_path = tmp_path / "decision_audit.jsonl"
    payload = _make_decision_payload()
    with patch.dict("os.environ", {"OMNICLAUDE_DECISION_AUDIT_LOG": str(audit_path)}):
        result = process_decision_record_event(_to_raw(payload))
    assert result is True
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    written = json.loads(lines[0])
    assert written["decision_id"] == _DECISION_ID
    assert written["selected_candidate"] == _SELECTED
    assert written["agent_rationale"] == "Selected for coding expertise."


@pytest.mark.unit
def test_process_multiple_events_appends_to_log(tmp_path: Path) -> None:
    """Multiple events accumulate as separate JSONL lines."""
    audit_path = tmp_path / "decision_audit.jsonl"
    with patch.dict("os.environ", {"OMNICLAUDE_DECISION_AUDIT_LOG": str(audit_path)}):
        process_decision_record_event(_to_raw(_make_decision_payload(decision_id="d1")))
        process_decision_record_event(_to_raw(_make_decision_payload(decision_id="d2")))
        process_decision_record_event(_to_raw(_make_decision_payload(decision_id="d3")))

    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    ids = [json.loads(ln)["decision_id"] for ln in lines]
    assert ids == ["d1", "d2", "d3"]


@pytest.mark.unit
def test_process_null_agent_rationale_still_persisted(tmp_path: Path) -> None:
    """Records with agent_rationale=null should still be written."""
    audit_path = tmp_path / "decision_audit.jsonl"
    payload = _make_decision_payload(agent_rationale=None)
    with patch.dict("os.environ", {"OMNICLAUDE_DECISION_AUDIT_LOG": str(audit_path)}):
        result = process_decision_record_event(_to_raw(payload))
    assert result is True
    written = json.loads(audit_path.read_text(encoding="utf-8").strip())
    assert written["agent_rationale"] is None


# ---------------------------------------------------------------------------
# _append_audit_record — I/O error handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_append_audit_record_creates_parent_dirs(tmp_path: Path) -> None:
    nested_path = tmp_path / "nested" / "subdir" / "audit.jsonl"
    with patch.dict("os.environ", {"OMNICLAUDE_DECISION_AUDIT_LOG": str(nested_path)}):
        result = _append_audit_record(
            {"decision_id": "x", "decision_type": "model_select"}
        )
    assert result is True
    assert nested_path.exists()


@pytest.mark.unit
def test_append_audit_record_io_error_returns_false() -> None:
    """If audit log path is unwritable, returns False silently."""
    with patch(
        "omniclaude.hooks.lib.decision_record_subscriber._resolve_audit_log_path",
        return_value=Path("/proc/1/mem"),  # unwritable on any OS
    ):
        result = _append_audit_record({"decision_id": "x"})
    assert result is False


# ---------------------------------------------------------------------------
# run_subscriber_background — thread lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_subscriber_background_starts_daemon_thread() -> None:
    """run_subscriber_background returns a started daemon thread."""
    stop_event = threading.Event()
    stop_event.set()  # Stop immediately so run_subscriber exits fast

    mock_consumer_cls = MagicMock()
    mock_consumer_instance = MagicMock()
    mock_consumer_cls.return_value = mock_consumer_instance
    mock_consumer_instance.poll.return_value = {}

    with patch(
        "omniclaude.hooks.lib.decision_record_subscriber._get_kafka_consumer_class",
        return_value=mock_consumer_cls,
    ):
        thread = run_subscriber_background(
            kafka_bootstrap_servers="localhost:9092",
            group_id="omniclaude-decision-record-subscriber.v1",
            stop_event=stop_event,
        )

    assert thread.daemon is True
    thread.join(timeout=2.0)


@pytest.mark.unit
def test_run_subscriber_background_no_kafka_exits_gracefully() -> None:
    """run_subscriber_background exits gracefully when kafka-python is not available."""
    stop_event = threading.Event()

    with patch(
        "omniclaude.hooks.lib.decision_record_subscriber._get_kafka_consumer_class",
        return_value=None,
    ):
        thread = run_subscriber_background(
            kafka_bootstrap_servers="localhost:9092",
            stop_event=stop_event,
        )

    thread.join(timeout=2.0)
    assert not thread.is_alive()
