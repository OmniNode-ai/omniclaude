# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for node_session_state_effect.py

Verifies:
- Session index read/write round-trips
- Run context read/write round-trips
- Atomic write safety (no partial files)
- flock timeout behavior
- GC of stale run documents
- GC time-gate (stamp file prevents re-runs)
- Schema validation with extra="ignore"

All tests use tmp_path fixture and CLAUDE_STATE_DIR env var override.

Related Tickets:
    - OMN-2119: Session State Orchestrator Shim + Adapter
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# Add hooks lib to path for imports
_HOOKS_LIB = Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _state_dir(tmp_path, monkeypatch):
    """Configure CLAUDE_STATE_DIR to use tmp_path for all tests."""
    state_dir = str(tmp_path / "state")
    monkeypatch.setattr("node_session_state_effect.CLAUDE_STATE_DIR", state_dir)
    return state_dir


# =============================================================================
# Import after fixtures are defined (module-level config is overridden per test)
# =============================================================================

from node_session_state_effect import (
    ContractRunContext,
    ContractSessionIndex,
    LockResult,
    _acquire_lock,
    _atomic_write,
    _release_lock,
    gc_stale_runs,
    read_run_context,
    read_session_index,
    write_run_context,
    write_session_index,
)

# =============================================================================
# Session Index Tests
# =============================================================================


class TestSessionIndex:
    """Tests for session index read/write."""

    def test_read_empty_returns_default(self) -> None:
        """Reading non-existent session index returns default ContractSessionIndex."""
        index = read_session_index()
        assert index.active_run_id is None
        assert index.recent_run_ids == []
        assert index.updated_at == ""

    def test_write_read_roundtrip(self) -> None:
        """Write then read session index preserves all fields."""
        index = ContractSessionIndex(
            active_run_id="run-abc",
            recent_run_ids=["run-abc", "run-def"],
            updated_at=datetime.now(UTC).isoformat(),
        )
        result = write_session_index(index)
        assert result == LockResult.ACQUIRED

        loaded = read_session_index()
        assert loaded.active_run_id == "run-abc"
        assert loaded.recent_run_ids == ["run-abc", "run-def"]
        assert loaded.updated_at == index.updated_at

    def test_write_creates_directory(self, tmp_path) -> None:
        """write_session_index creates parent directories if needed."""
        index = ContractSessionIndex(active_run_id="test")
        result = write_session_index(index)
        assert result == LockResult.ACQUIRED

        loaded = read_session_index()
        assert loaded.active_run_id == "test"


# =============================================================================
# Run Context Tests
# =============================================================================


class TestRunContext:
    """Tests for run context read/write."""

    def test_read_nonexistent_returns_none(self) -> None:
        """Reading non-existent run context returns None."""
        assert read_run_context("nonexistent-run") is None

    def test_write_read_roundtrip(self) -> None:
        """Write then read run context preserves all fields."""
        now = datetime.now(UTC).isoformat()
        ctx = ContractRunContext(
            run_id="run-123",
            session_id="session-456",
            state="run_active",
            created_at=now,
            updated_at=now,
        )
        write_run_context(ctx)

        loaded = read_run_context("run-123")
        assert loaded is not None
        assert loaded.run_id == "run-123"
        assert loaded.session_id == "session-456"
        assert loaded.state == "run_active"
        assert loaded.created_at == now
        assert loaded.updated_at == now


# =============================================================================
# Atomic Write Tests
# =============================================================================


class TestAtomicWrite:
    """Tests for atomic write safety."""

    def test_no_partial_file_on_success(self, tmp_path) -> None:
        """Successful atomic write produces the target file with correct content."""
        target = tmp_path / "test.json"
        data = json.dumps({"key": "value"})
        _atomic_write(target, data)

        assert target.exists()
        assert json.loads(target.read_text()) == {"key": "value"}

    def test_tmp_file_cleaned_up(self, tmp_path) -> None:
        """After atomic write, no .tmp.* files remain."""
        target = tmp_path / "test.json"
        _atomic_write(target, '{"clean": true}')

        tmp_files = list(tmp_path.glob(".tmp.*"))
        assert len(tmp_files) == 0

    def test_creates_parent_directories(self, tmp_path) -> None:
        """Atomic write creates parent directories if they do not exist."""
        target = tmp_path / "sub" / "dir" / "file.json"
        _atomic_write(target, '{"nested": true}')
        assert target.exists()


# =============================================================================
# Flock Tests
# =============================================================================


class TestFlock:
    """Tests for flock acquisition and timeout."""

    def test_acquire_lock_succeeds(self, tmp_path) -> None:
        """Acquiring a lock on an unlocked file succeeds."""
        lock_path = tmp_path / "test.lock"
        result, fd = _acquire_lock(lock_path, timeout_ms=100)
        assert result == LockResult.ACQUIRED
        assert fd >= 0
        _release_lock(fd)

    def test_acquire_lock_timeout(self, tmp_path) -> None:
        """Acquiring a lock on an already-locked file times out."""
        lock_path = tmp_path / "test.lock"

        # Acquire the lock first
        result1, fd1 = _acquire_lock(lock_path, timeout_ms=100)
        assert result1 == LockResult.ACQUIRED

        try:
            # Try to acquire again - should timeout
            result2, fd2 = _acquire_lock(lock_path, timeout_ms=50)
            assert result2 == LockResult.TIMEOUT
            assert fd2 == -1
        finally:
            _release_lock(fd1)

    def test_lock_released_allows_reacquisition(self, tmp_path) -> None:
        """After releasing a lock, another caller can acquire it."""
        lock_path = tmp_path / "test.lock"

        result1, fd1 = _acquire_lock(lock_path, timeout_ms=100)
        assert result1 == LockResult.ACQUIRED
        _release_lock(fd1)

        result2, fd2 = _acquire_lock(lock_path, timeout_ms=100)
        assert result2 == LockResult.ACQUIRED
        _release_lock(fd2)

    def test_write_session_index_returns_timeout_on_held_lock(
        self, tmp_path, monkeypatch
    ) -> None:
        """write_session_index returns TIMEOUT if the lock is held."""
        # The _state_dir fixture already sets CLAUDE_STATE_DIR
        from node_session_state_effect import _session_index_path

        path = _session_index_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        # Hold the lock externally on the dedicated lock file
        lock_path = path.parent / "session.json.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        try:
            # Set a very short timeout
            monkeypatch.setattr(
                "node_session_state_effect.CLAUDE_STATE_LOCK_TIMEOUT_MS", 20
            )
            index = ContractSessionIndex(active_run_id="blocked")
            result = write_session_index(index)
            assert result == LockResult.TIMEOUT
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


# =============================================================================
# GC Tests
# =============================================================================


class TestGarbageCollection:
    """Tests for stale run document garbage collection."""

    def test_gc_removes_old_ended_runs(self, monkeypatch) -> None:
        """GC removes run docs where state=run_ended and older than TTL."""
        # Set TTL to 0 so everything is "old"
        monkeypatch.setattr("node_session_state_effect.CLAUDE_STATE_GC_TTL_SECONDS", 0)

        old_time = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
        ctx = ContractRunContext(
            run_id="old-ended",
            session_id="sess-1",
            state="run_ended",
            created_at=old_time,
            updated_at=old_time,
        )
        write_run_context(ctx)

        # Ensure stamp file does not gate us
        from node_session_state_effect import _gc_stamp_path

        stamp = _gc_stamp_path()
        if stamp.exists():
            stamp.unlink()

        removed = gc_stale_runs()
        assert removed == 1
        assert read_run_context("old-ended") is None

    def test_gc_preserves_active_runs(self, monkeypatch) -> None:
        """GC does not remove runs that are still active."""
        monkeypatch.setattr("node_session_state_effect.CLAUDE_STATE_GC_TTL_SECONDS", 0)

        old_time = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
        ctx = ContractRunContext(
            run_id="still-active",
            session_id="sess-2",
            state="run_active",
            created_at=old_time,
            updated_at=old_time,
        )
        write_run_context(ctx)

        from node_session_state_effect import _gc_stamp_path

        stamp = _gc_stamp_path()
        if stamp.exists():
            stamp.unlink()

        removed = gc_stale_runs()
        assert removed == 0
        assert read_run_context("still-active") is not None

    def test_gc_time_gate_prevents_frequent_runs(self) -> None:
        """GC stamp file prevents running more than once per interval."""
        from node_session_state_effect import _gc_stamp_path

        stamp = _gc_stamp_path()
        stamp.parent.mkdir(parents=True, exist_ok=True)

        # Write a recent stamp
        stamp.write_text(str(time.time()))

        # GC should return 0 immediately (time-gated)
        removed = gc_stale_runs()
        assert removed == 0

    def test_gc_runs_when_stamp_is_old(self, monkeypatch) -> None:
        """GC runs when stamp file is older than the interval."""
        monkeypatch.setattr("node_session_state_effect.CLAUDE_STATE_GC_TTL_SECONDS", 0)
        monkeypatch.setattr("node_session_state_effect._GC_INTERVAL_SECONDS", 0)

        old_time = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
        ctx = ContractRunContext(
            run_id="gc-target",
            session_id="sess-3",
            state="run_ended",
            created_at=old_time,
            updated_at=old_time,
        )
        write_run_context(ctx)

        from node_session_state_effect import _gc_stamp_path

        stamp = _gc_stamp_path()
        stamp.parent.mkdir(parents=True, exist_ok=True)
        # Set stamp to old time
        old_epoch = time.time() - 700
        stamp.write_text(str(old_epoch))
        os.utime(str(stamp), (old_epoch, old_epoch))

        removed = gc_stale_runs()
        assert removed == 1


# =============================================================================
# Schema Validation Tests
# =============================================================================


class TestSchemaValidation:
    """Tests for Pydantic model behavior with extra fields."""

    def test_session_index_ignores_extra_fields(self) -> None:
        """ContractSessionIndex ignores unknown fields (extra='ignore')."""
        index = ContractSessionIndex(
            active_run_id="test",
            unknown_field="should be ignored",  # type: ignore[call-arg]
        )
        assert index.active_run_id == "test"
        assert not hasattr(index, "unknown_field")

    def test_run_context_ignores_extra_fields(self) -> None:
        """ContractRunContext ignores unknown fields (extra='ignore')."""
        ctx = ContractRunContext(
            run_id="test",
            session_id="sess",
            extra_data=42,  # type: ignore[call-arg]
        )
        assert ctx.run_id == "test"
        assert not hasattr(ctx, "extra_data")

    def test_run_context_defaults(self) -> None:
        """ContractRunContext has sensible defaults."""
        ctx = ContractRunContext(run_id="r1", session_id="s1")
        assert ctx.state == "idle"
        assert ctx.created_at == ""
        assert ctx.updated_at == ""

    def test_session_index_defaults(self) -> None:
        """ContractSessionIndex has sensible defaults."""
        index = ContractSessionIndex()
        assert index.active_run_id is None
        assert index.recent_run_ids == []
        assert index.updated_at == ""


# =============================================================================
# Handler Registry Tests
# =============================================================================


class TestHandlerRegistry:
    """Tests for the HANDLERS registry."""

    def test_all_handlers_registered(self) -> None:
        """All expected handlers are in the registry."""
        from node_session_state_effect import HANDLERS

        expected = {
            "read_session_index",
            "write_session_index",
            "read_run_context",
            "write_run_context",
            "gc_stale_runs",
        }
        assert set(HANDLERS.keys()) == expected

    def test_all_handlers_are_callable(self) -> None:
        """All registered handlers are callable."""
        from node_session_state_effect import HANDLERS

        for name, handler in HANDLERS.items():
            assert callable(handler), f"Handler {name} is not callable"
