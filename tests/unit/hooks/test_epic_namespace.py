# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for epic namespace isolation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from omniclaude.hooks.lib.epic_namespace import (
    ModelEpicNamespaceLock,
    acquire_namespace,
    build_isolation_context,
    get_active_namespace,
    is_epic_active,
    release_namespace,
)


@pytest.mark.unit
class TestModelEpicNamespaceLock:
    """Tests for the namespace lock model."""

    def test_create_lock(self) -> None:
        lock = ModelEpicNamespaceLock(
            epic_id="OMN-1234",
            run_id="run-abc123",
            started_at=datetime(2026, 3, 26, 12, 0, 0, tzinfo=UTC),
            session_id="session-xyz",
        )
        assert lock.epic_id == "OMN-1234"
        assert lock.run_id == "run-abc123"
        assert lock.session_id == "session-xyz"

    def test_frozen(self) -> None:
        lock = ModelEpicNamespaceLock(
            epic_id="OMN-1234",
            run_id="run-abc123",
            started_at=datetime(2026, 3, 26, 12, 0, 0, tzinfo=UTC),
            session_id="session-xyz",
        )
        with pytest.raises(Exception):  # noqa: B017 — frozen model
            lock.epic_id = "OMN-5678"  # type: ignore[misc]

    def test_extra_forbid(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 — extra="forbid"
            ModelEpicNamespaceLock(
                epic_id="OMN-1234",
                run_id="run-abc123",
                started_at=datetime(2026, 3, 26, 12, 0, 0, tzinfo=UTC),
                session_id="session-xyz",
                extra_field="bad",  # type: ignore[call-arg]
            )


@pytest.mark.unit
class TestAcquireRelease:
    """Tests for namespace acquire/release lifecycle."""

    def test_acquire_creates_lock(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import tempfile

        state_dir = tempfile.mkdtemp()
        monkeypatch.setenv("ONEX_STATE_DIR", state_dir)

        result = acquire_namespace(
            epic_id="OMN-1234",
            run_id="run-001",
            session_id="sess-001",
            started_at=datetime(2026, 3, 26, 12, 0, 0, tzinfo=UTC),
        )
        assert result is True
        assert is_epic_active() is True

    def test_release_removes_lock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import tempfile

        state_dir = tempfile.mkdtemp()
        monkeypatch.setenv("ONEX_STATE_DIR", state_dir)

        acquire_namespace(
            epic_id="OMN-1234",
            run_id="run-001",
            session_id="sess-001",
        )
        assert is_epic_active() is True

        result = release_namespace("OMN-1234")
        assert result is True
        assert is_epic_active() is False

    def test_release_wrong_owner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import tempfile

        state_dir = tempfile.mkdtemp()
        monkeypatch.setenv("ONEX_STATE_DIR", state_dir)

        acquire_namespace(
            epic_id="OMN-1234",
            run_id="run-001",
            session_id="sess-001",
        )
        # Try to release with wrong epic_id
        result = release_namespace("OMN-5678")
        assert result is False
        assert is_epic_active() is True

    def test_no_lock_means_inactive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import tempfile

        state_dir = tempfile.mkdtemp()
        monkeypatch.setenv("ONEX_STATE_DIR", state_dir)

        assert is_epic_active() is False
        assert get_active_namespace() is None


@pytest.mark.unit
class TestBuildIsolationContext:
    """Tests for dispatch isolation context generation."""

    def test_no_epic_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import tempfile

        state_dir = tempfile.mkdtemp()
        monkeypatch.setenv("ONEX_STATE_DIR", state_dir)

        ctx = build_isolation_context()
        assert ctx == {}

    def test_active_epic_returns_markers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import tempfile

        state_dir = tempfile.mkdtemp()
        monkeypatch.setenv("ONEX_STATE_DIR", state_dir)

        acquire_namespace(
            epic_id="OMN-1234",
            run_id="run-001",
            session_id="sess-001",
        )

        ctx = build_isolation_context()
        assert ctx["epic_namespace_exclude"] is True
        assert ctx["active_epic_id"] == "OMN-1234"
        assert ctx["active_epic_run_id"] == "run-001"
        assert "isolation_reason" in ctx
