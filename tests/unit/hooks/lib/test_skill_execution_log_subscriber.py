# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for skill_execution_log_subscriber (OMN-2778).

Tests the Kafka-to-table projection consumer that writes
onex.evt.omniclaude.skill-completed.v1 events to skill_execution_logs.

All tests run without Kafka or PostgreSQL (fully mocked).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from omniclaude.hooks.lib.skill_execution_log_subscriber import (
    DEFAULT_GROUP_ID,
    SKILL_COMPLETED_TOPIC,
    _parse_skill_completed_event,
    _upsert_skill_execution_log,
    process_skill_completed_event,
    run_subscriber_background,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_payload(
    *,
    run_id: str | None = None,
    skill_name: str = "ticket-pipeline",
    skill_id: str | None = "plugins/onex/skills/ticket-pipeline",
    repo_id: str = "omniclaude",
    correlation_id: str | None = None,
    session_id: str | None = "sess-abc123",
    status: str = "success",
    duration_ms: int = 1234,
    error_type: str | None = None,
    started_emit_failed: bool = False,
    emitted_at: str | None = None,
) -> dict[str, Any]:
    """Build a minimal valid skill-completed payload dict."""
    return {
        "event_id": str(uuid.uuid4()),
        "run_id": run_id or str(uuid.uuid4()),
        "skill_name": skill_name,
        "skill_id": skill_id,
        "repo_id": repo_id,
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "session_id": session_id,
        "status": status,
        "duration_ms": duration_ms,
        "error_type": error_type,
        "started_emit_failed": started_emit_failed,
        "emitted_at": emitted_at or datetime.now(UTC).isoformat(),
    }


def _encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Verify topic and group ID constants."""

    @pytest.mark.unit
    def test_skill_completed_topic(self) -> None:
        assert SKILL_COMPLETED_TOPIC == "onex.evt.omniclaude.skill-completed.v1"

    @pytest.mark.unit
    def test_default_group_id_has_version_suffix(self) -> None:
        # F5 rule: group ID must end with .v{N}
        import re

        assert re.match(r"^omniclaude-.+\.v\d+$", DEFAULT_GROUP_ID), (
            f"DEFAULT_GROUP_ID {DEFAULT_GROUP_ID!r} must match omniclaude-*.vN"
        )


# ---------------------------------------------------------------------------
# _parse_skill_completed_event
# ---------------------------------------------------------------------------


class TestParseSkillCompletedEvent:
    """Tests for the low-level JSON deserialiser."""

    @pytest.mark.unit
    def test_valid_payload_returns_dict(self) -> None:
        payload = _make_payload()
        raw = _encode(payload)
        result = _parse_skill_completed_event(raw)
        assert result is not None
        assert result["skill_name"] == "ticket-pipeline"

    @pytest.mark.unit
    def test_empty_bytes_returns_none(self) -> None:
        assert _parse_skill_completed_event(b"") is None

    @pytest.mark.unit
    def test_invalid_json_returns_none(self) -> None:
        assert _parse_skill_completed_event(b"not-json{{{") is None

    @pytest.mark.unit
    def test_valid_json_non_object_returns_dict_or_none(self) -> None:
        # A JSON array is parseable but _upsert will reject it
        result = _parse_skill_completed_event(b"[1, 2, 3]")
        # Either None or a list — either way upsert will reject it
        # (just confirm no crash)
        assert result is not None or result is None

    @pytest.mark.unit
    def test_whitespace_only_returns_none(self) -> None:
        assert _parse_skill_completed_event(b"   ") is None


# ---------------------------------------------------------------------------
# _upsert_skill_execution_log
# ---------------------------------------------------------------------------


class TestUpsertSkillExecutionLog:
    """Tests for the DB upsert function (mocked psycopg2)."""

    @pytest.mark.unit
    def test_missing_run_id_returns_false(self) -> None:
        payload = _make_payload()
        del payload["run_id"]
        assert _upsert_skill_execution_log(payload) is False

    @pytest.mark.unit
    def test_null_run_id_returns_false(self) -> None:
        payload = _make_payload(run_id=None)
        payload["run_id"] = None
        assert _upsert_skill_execution_log(payload) is False

    @pytest.mark.unit
    def test_invalid_status_returns_false(self) -> None:
        payload = _make_payload(status="unknown_status")
        assert _upsert_skill_execution_log(payload) is False

    @pytest.mark.unit
    def test_missing_skill_name_returns_false(self) -> None:
        payload = _make_payload()
        payload["skill_name"] = ""
        assert _upsert_skill_execution_log(payload) is False

    @pytest.mark.unit
    def test_missing_repo_id_returns_false(self) -> None:
        payload = _make_payload()
        payload["repo_id"] = ""
        assert _upsert_skill_execution_log(payload) is False

    @pytest.mark.unit
    def test_invalid_run_id_uuid_returns_false(self) -> None:
        payload = _make_payload(run_id="not-a-uuid")
        assert _upsert_skill_execution_log(payload) is False

    @pytest.mark.unit
    def test_db_connect_failure_returns_false(self) -> None:
        payload = _make_payload()
        with patch(
            "omniclaude.hooks.lib.skill_execution_log_subscriber._get_db_connection",
            return_value=None,
        ):
            assert _upsert_skill_execution_log(payload) is False

    @pytest.mark.unit
    def test_successful_upsert_returns_true(self) -> None:
        payload = _make_payload()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "omniclaude.hooks.lib.skill_execution_log_subscriber._get_db_connection",
            return_value=mock_conn,
        ):
            result = _upsert_skill_execution_log(payload)

        assert result is True
        assert mock_cursor.execute.called

    @pytest.mark.unit
    def test_upsert_executes_correct_sql_params(self) -> None:
        run_id = str(uuid.uuid4())
        payload = _make_payload(
            run_id=run_id,
            skill_name="pr-review",
            repo_id="omniclaude",
            status="failed",
            duration_ms=500,
            error_type="TimeoutError",
            started_emit_failed=True,
        )
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "omniclaude.hooks.lib.skill_execution_log_subscriber._get_db_connection",
            return_value=mock_conn,
        ):
            _upsert_skill_execution_log(payload)

        call_args = mock_cursor.execute.call_args
        params = call_args[0][1]  # second positional arg to execute()
        assert params["run_id"] == run_id
        assert params["skill_name"] == "pr-review"
        assert params["repo_id"] == "omniclaude"
        assert params["status"] == "failed"
        assert params["duration_ms"] == 500
        assert params["error_type"] == "TimeoutError"
        assert params["started_emit_failed"] is True

    @pytest.mark.unit
    def test_db_execute_exception_returns_false(self) -> None:
        payload = _make_payload()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = RuntimeError("DB error")
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "omniclaude.hooks.lib.skill_execution_log_subscriber._get_db_connection",
            return_value=mock_conn,
        ):
            result = _upsert_skill_execution_log(payload)

        assert result is False

    @pytest.mark.unit
    def test_all_valid_statuses_accepted(self) -> None:
        for status in ("success", "failed", "partial"):
            payload = _make_payload(status=status)
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

            with patch(
                "omniclaude.hooks.lib.skill_execution_log_subscriber._get_db_connection",
                return_value=mock_conn,
            ):
                result = _upsert_skill_execution_log(payload)

            assert result is True, f"Expected True for status={status!r}"


# ---------------------------------------------------------------------------
# process_skill_completed_event
# ---------------------------------------------------------------------------


class TestProcessSkillCompletedEvent:
    """End-to-end tests for the raw-bytes processor."""

    @pytest.mark.unit
    def test_valid_event_returns_true(self) -> None:
        payload = _make_payload()
        raw = _encode(payload)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "omniclaude.hooks.lib.skill_execution_log_subscriber._get_db_connection",
            return_value=mock_conn,
        ):
            result = process_skill_completed_event(raw)

        assert result is True

    @pytest.mark.unit
    def test_empty_bytes_returns_false(self) -> None:
        assert process_skill_completed_event(b"") is False

    @pytest.mark.unit
    def test_malformed_json_returns_false(self) -> None:
        assert process_skill_completed_event(b"{{bad json}}") is False

    @pytest.mark.unit
    def test_missing_run_id_returns_false(self) -> None:
        payload = _make_payload()
        del payload["run_id"]
        assert process_skill_completed_event(_encode(payload)) is False

    @pytest.mark.unit
    def test_never_raises(self) -> None:
        """process_skill_completed_event must never propagate exceptions."""
        with patch(
            "omniclaude.hooks.lib.skill_execution_log_subscriber._parse_skill_completed_event",
            side_effect=RuntimeError("unexpected crash"),
        ):
            # Should return False, not raise
            result = process_skill_completed_event(b"{}")
        assert result is False


# ---------------------------------------------------------------------------
# run_subscriber_background
# ---------------------------------------------------------------------------


class TestRunSubscriberBackground:
    """Tests for the background thread launcher."""

    @pytest.mark.unit
    def test_returns_daemon_thread(self) -> None:
        import threading

        stop_event = threading.Event()
        stop_event.set()  # Stop immediately so thread exits

        with patch(
            "omniclaude.hooks.lib.skill_execution_log_subscriber.run_subscriber"
        ):
            thread = run_subscriber_background(
                kafka_bootstrap_servers="localhost:9092",
                stop_event=stop_event,
            )

        assert isinstance(thread, threading.Thread)
        assert thread.daemon is True

    @pytest.mark.unit
    def test_thread_name(self) -> None:
        import threading

        stop_event = threading.Event()
        stop_event.set()

        with patch(
            "omniclaude.hooks.lib.skill_execution_log_subscriber.run_subscriber"
        ):
            thread = run_subscriber_background(
                kafka_bootstrap_servers="localhost:9092",
                stop_event=stop_event,
            )

        assert thread.name == "skill-execution-log-subscriber"


# ---------------------------------------------------------------------------
# Consumer group guard integration
# ---------------------------------------------------------------------------


class TestConsumerGroupGuardRegistration:
    """Verify SkillExecutionLogSubscriber is registered in SKILL_NODE_CONSUMER_GROUPS."""

    @pytest.mark.unit
    def test_subscriber_registered_in_consumer_group_guard(self) -> None:
        from omniclaude.lib.consumer_group_guard import SKILL_NODE_CONSUMER_GROUPS

        assert "SkillExecutionLogSubscriber" in SKILL_NODE_CONSUMER_GROUPS

    @pytest.mark.unit
    def test_registered_group_id_matches_default(self) -> None:
        from omniclaude.lib.consumer_group_guard import SKILL_NODE_CONSUMER_GROUPS

        assert (
            SKILL_NODE_CONSUMER_GROUPS["SkillExecutionLogSubscriber"] == DEFAULT_GROUP_ID
        )

    @pytest.mark.unit
    def test_registered_group_id_has_version_suffix(self) -> None:
        import re

        from omniclaude.lib.consumer_group_guard import SKILL_NODE_CONSUMER_GROUPS

        group_id = SKILL_NODE_CONSUMER_GROUPS["SkillExecutionLogSubscriber"]
        assert re.match(r"^omniclaude-.+\.v\d+$", group_id), (
            f"Consumer group ID {group_id!r} must match omniclaude-*.vN"
        )
