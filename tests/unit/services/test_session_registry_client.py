# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for SessionRegistryClient -- D4 typed results and format_resume_context."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from omniclaude.services.session_registry_client import (
    ModelRegistryUnavailable,
    ModelSessionFound,
    ModelSessionNotFound,
    ModelSessionRegistryRow,
    SessionRegistryClient,
)


def _sample_row() -> ModelSessionRegistryRow:
    """Return a realistic session registry row model."""
    return ModelSessionRegistryRow(
        task_id="OMN-1234",
        status="active",
        current_phase="implementing",
        worktree_path="/tmp/worktrees/OMN-1234/omnibase_core",  # local-path-ok
        files_touched=["src/models/foo.py", "tests/test_foo.py"],
        depends_on=["OMN-1230"],
        session_ids=["session-abc", "session-def"],
        correlation_ids=["corr-111", "corr-222"],
        decisions=[
            "Chose approach B: extend existing ModelFoo rather than creating ModelBar"
        ],
        last_activity=datetime(2026, 3, 27, 14, 0, 0, tzinfo=UTC),
        created_at=datetime(2026, 3, 27, 10, 0, 0, tzinfo=UTC),
    )


def _sample_db_tuple() -> tuple[object, ...]:
    """Return a DB row tuple matching _COLUMNS order."""
    return (
        "OMN-1234",
        "active",
        "implementing",
        None,
        ["src/foo.py"],
        [],
        ["s1"],
        [],
        [],
        datetime(2026, 3, 27, 14, 0, 0, tzinfo=UTC),
        datetime(2026, 3, 27, 10, 0, 0, tzinfo=UTC),
    )


@pytest.mark.unit
class TestFormatResumeContext:
    """Test format_resume_context produces correct human-readable output."""

    def test_format_includes_task_id(self) -> None:
        client = SessionRegistryClient(db_url=None)
        context = client.format_resume_context(_sample_row())
        assert "OMN-1234" in context

    def test_format_includes_phase(self) -> None:
        client = SessionRegistryClient(db_url=None)
        context = client.format_resume_context(_sample_row())
        assert "implementing" in context

    def test_format_includes_files(self) -> None:
        client = SessionRegistryClient(db_url=None)
        context = client.format_resume_context(_sample_row())
        assert "src/models/foo.py" in context
        assert "tests/test_foo.py" in context

    def test_format_includes_dependencies(self) -> None:
        client = SessionRegistryClient(db_url=None)
        context = client.format_resume_context(_sample_row())
        assert "OMN-1230" in context

    def test_format_includes_decisions(self) -> None:
        client = SessionRegistryClient(db_url=None)
        context = client.format_resume_context(_sample_row())
        assert "approach B" in context

    def test_format_includes_session_count(self) -> None:
        client = SessionRegistryClient(db_url=None)
        context = client.format_resume_context(_sample_row())
        assert "2 session(s)" in context

    def test_format_includes_last_activity(self) -> None:
        client = SessionRegistryClient(db_url=None)
        context = client.format_resume_context(_sample_row())
        assert "2026-03-27" in context

    def test_format_handles_empty_lists(self) -> None:
        row = ModelSessionRegistryRow(
            task_id="OMN-5555",
            status="active",
            current_phase="planning",
        )
        client = SessionRegistryClient(db_url=None)
        context = client.format_resume_context(row)
        assert "OMN-5555" in context
        assert "Files Touched" not in context
        assert "Dependencies" not in context
        assert "Decisions" not in context

    def test_format_handles_none_phase(self) -> None:
        """current_phase=None renders as 'unknown'."""
        row = ModelSessionRegistryRow(task_id="OMN-7777", status="active")
        client = SessionRegistryClient(db_url=None)
        context = client.format_resume_context(row)
        assert "unknown" in context


@pytest.mark.unit
class TestGetSessionD4:
    """Test get_session returns typed results per Doctrine D4."""

    def test_returns_found_when_entry_exists(self) -> None:
        """get_session returns ModelSessionFound when task exists."""
        client = SessionRegistryClient(
            db_url="postgresql://test:test@localhost:5436/test"
        )

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = _sample_db_tuple()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(client, "_connect", return_value=mock_conn):
            result = client.get_session("OMN-1234")

        assert isinstance(result, ModelSessionFound)
        assert isinstance(result.entry, ModelSessionRegistryRow)
        assert result.entry.task_id == "OMN-1234"
        assert result.entry.status == "active"

    def test_returns_not_found_when_no_entry(self) -> None:
        """get_session returns ModelSessionNotFound when task doesn't exist."""
        client = SessionRegistryClient(
            db_url="postgresql://test:test@localhost:5436/test"
        )

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(client, "_connect", return_value=mock_conn):
            result = client.get_session("OMN-9999")

        assert isinstance(result, ModelSessionNotFound)
        assert result.task_id == "OMN-9999"

    def test_returns_unavailable_on_connection_error(self) -> None:
        """get_session returns ModelRegistryUnavailable on connection failure."""
        client = SessionRegistryClient(db_url="postgresql://bad:bad@nowhere:5432/nodb")

        with patch.object(
            client, "_connect", side_effect=ConnectionError("connection refused")
        ):
            result = client.get_session("OMN-1234")

        assert isinstance(result, ModelRegistryUnavailable)
        assert "connection refused" in result.reason

    def test_returns_unavailable_on_query_error(self) -> None:
        """get_session returns ModelRegistryUnavailable on SQL error."""
        client = SessionRegistryClient(
            db_url="postgresql://test:test@localhost:5436/test"
        )

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = psycopg2.ProgrammingError(
            "relation does not exist"
        )
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(client, "_connect", return_value=mock_conn):
            result = client.get_session("OMN-1234")

        assert isinstance(result, ModelRegistryUnavailable)
        assert "relation does not exist" in result.reason

    def test_returns_unavailable_when_no_db_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_session returns Unavailable when no DB URL configured."""
        monkeypatch.delenv("OMNIBASE_INFRA_DB_URL", raising=False)
        client = SessionRegistryClient(db_url=None)
        result = client.get_session("OMN-1234")

        assert isinstance(result, ModelRegistryUnavailable)
        assert "OMNIBASE_INFRA_DB_URL" in result.reason


@pytest.mark.unit
class TestListActiveSessions:
    """Test list_active_sessions returns typed results."""

    def test_returns_list_on_success(self) -> None:
        client = SessionRegistryClient(
            db_url="postgresql://test:test@localhost:5436/test"
        )

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [_sample_db_tuple()]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(client, "_connect", return_value=mock_conn):
            result = client.list_active_sessions()

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ModelSessionRegistryRow)
        assert result[0].task_id == "OMN-1234"

    def test_returns_unavailable_on_error(self) -> None:
        client = SessionRegistryClient(db_url="postgresql://bad:bad@nowhere:5432/nodb")

        with patch.object(
            client, "_connect", side_effect=ConnectionError("connection refused")
        ):
            result = client.list_active_sessions()

        assert isinstance(result, ModelRegistryUnavailable)
        assert "connection refused" in result.reason
