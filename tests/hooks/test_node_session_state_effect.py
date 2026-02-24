# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
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
    monkeypatch.setenv("CLAUDE_STATE_DIR", state_dir)
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
    update_session_index,
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

    def test_read_path_traversal_returns_none(self) -> None:
        """Reading with a path-traversal run_id returns None instead of raising."""
        assert read_run_context("../etc/passwd") is None

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

    def test_fsyncs_parent_directory_after_rename(self, tmp_path, monkeypatch) -> None:
        """Atomic write fsyncs the parent directory after rename for crash safety."""
        target = tmp_path / "durable.json"

        # Track os.open, os.fsync, and os.close calls to detect dir fsync
        real_open = os.open
        real_fsync = os.fsync
        real_close = os.close

        dir_fd_opened: list[int] = []
        dir_fd_fsynced: list[int] = []

        def patched_open(path, flags, *args, **kwargs):
            fd = real_open(path, flags, *args, **kwargs)
            # Detect O_RDONLY opens on the parent directory (the dir fsync pattern)
            if flags == os.O_RDONLY and path == str(target.parent):
                dir_fd_opened.append(fd)
            return fd

        def patched_fsync(fd):
            if fd in dir_fd_opened:
                dir_fd_fsynced.append(fd)
            return real_fsync(fd)

        monkeypatch.setattr(os, "open", patched_open)
        monkeypatch.setattr(os, "fsync", patched_fsync)

        _atomic_write(target, '{"durable": true}')

        assert target.exists()
        assert len(dir_fd_opened) == 1, "Expected os.open on parent dir with O_RDONLY"
        assert len(dir_fd_fsynced) == 1, "Expected os.fsync called on parent dir fd"


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
            monkeypatch.setenv("CLAUDE_STATE_LOCK_TIMEOUT_MS", "20")
            index = ContractSessionIndex(active_run_id="blocked")
            result = write_session_index(index)
            assert result == LockResult.TIMEOUT
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_update_session_index_returns_timeout_on_held_lock(
        self, tmp_path, monkeypatch
    ) -> None:
        """update_session_index returns TIMEOUT if the lock is held."""
        from node_session_state_effect import _session_index_path

        path = _session_index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")

        # Hold the lock externally on the dedicated lock file
        lock_path = path.parent / "session.json.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        try:
            # Set a very short timeout
            monkeypatch.setenv("CLAUDE_STATE_LOCK_TIMEOUT_MS", "20")
            result = update_session_index(
                lambda idx: ContractSessionIndex(
                    active_run_id="blocked",
                    updated_at="2026-01-01T00:00:00+00:00",
                )
            )
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
        monkeypatch.setenv("CLAUDE_STATE_GC_TTL_SECONDS", "0")

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
        """GC does not remove active runs within orphan TTL (7x normal TTL)."""
        # Use 1 hour TTL — orphan cutoff is 7 hours. A 5-hour-old active run survives.
        monkeypatch.setenv("CLAUDE_STATE_GC_TTL_SECONDS", "3600")

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

        # Create a recent stamp (mtime = now)
        stamp.touch()

        # GC should return 0 immediately (time-gated)
        removed = gc_stale_runs()
        assert removed == 0

    def test_gc_runs_when_stamp_is_old(self, monkeypatch) -> None:
        """GC runs when stamp file is older than the interval."""
        monkeypatch.setenv("CLAUDE_STATE_GC_TTL_SECONDS", "0")
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
        # Set stamp mtime to old time
        old_epoch = time.time() - 700
        stamp.touch()
        os.utime(str(stamp), (old_epoch, old_epoch))

        removed = gc_stale_runs()
        assert removed == 1

    def test_gc_cleans_session_index_recent_run_ids(self, monkeypatch) -> None:
        """GC removes deleted run_ids from session.json recent_run_ids."""
        from node_session_state_effect import _gc_stamp_path, update_session_index

        # Use 1-hour TTL so ended runs 5h old are GC'd, but active runs
        # within orphan cutoff (7h) survive.
        monkeypatch.setenv("CLAUDE_STATE_GC_TTL_SECONDS", "3600")
        monkeypatch.setattr("node_session_state_effect._GC_INTERVAL_SECONDS", 0)

        old_time = (datetime.now(UTC) - timedelta(hours=5)).isoformat()

        # Create two stale ended runs (5h old, past the 1h TTL)
        for rid in ("stale-run-1", "stale-run-2"):
            write_run_context(
                ContractRunContext(
                    run_id=rid,
                    session_id="sess-gc",
                    state="run_ended",
                    created_at=old_time,
                    updated_at=old_time,
                )
            )

        # Create one active run that should survive (5h old but within 7h orphan cutoff)
        write_run_context(
            ContractRunContext(
                run_id="alive-run",
                session_id="sess-gc",
                state="run_active",
                created_at=old_time,
                updated_at=old_time,
            )
        )

        # Set up session index referencing all three runs
        now = datetime.now(UTC).isoformat()

        def _setup(index):
            index.active_run_id = "stale-run-1"
            index.recent_run_ids = ["stale-run-1", "stale-run-2", "alive-run"]
            index.updated_at = now
            return index

        update_session_index(_setup)

        # Remove stamp to allow GC to run
        stamp = _gc_stamp_path()
        if stamp.exists():
            stamp.unlink()

        removed = gc_stale_runs()
        assert removed == 2

        # Verify session index was cleaned
        loaded = read_session_index()
        assert "stale-run-1" not in loaded.recent_run_ids
        assert "stale-run-2" not in loaded.recent_run_ids
        assert "alive-run" in loaded.recent_run_ids

    def test_gc_clears_active_run_id_if_gcd(self, monkeypatch) -> None:
        """GC clears active_run_id when it references a deleted run."""
        from node_session_state_effect import _gc_stamp_path, update_session_index

        monkeypatch.setenv("CLAUDE_STATE_GC_TTL_SECONDS", "0")
        monkeypatch.setattr("node_session_state_effect._GC_INTERVAL_SECONDS", 0)

        old_time = (datetime.now(UTC) - timedelta(hours=5)).isoformat()

        # Create a stale run that is also the active run
        write_run_context(
            ContractRunContext(
                run_id="active-but-stale",
                session_id="sess-gc2",
                state="run_ended",
                created_at=old_time,
                updated_at=old_time,
            )
        )

        now = datetime.now(UTC).isoformat()

        def _setup(index):
            index.active_run_id = "active-but-stale"
            index.recent_run_ids = ["active-but-stale"]
            index.updated_at = now
            return index

        update_session_index(_setup)

        stamp = _gc_stamp_path()
        if stamp.exists():
            stamp.unlink()

        removed = gc_stale_runs()
        assert removed == 1

        # active_run_id should be cleared to None (consistent with contract default)
        loaded = read_session_index()
        assert loaded.active_run_id is None
        assert loaded.recent_run_ids == []


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
            "update_session_index",
            "read_run_context",
            "write_run_context",
            "delete_run_context",
            "gc_stale_runs",
        }
        assert set(HANDLERS.keys()) == expected

    def test_all_handlers_are_callable(self) -> None:
        """All registered handlers are callable."""
        from node_session_state_effect import HANDLERS

        for name, handler in HANDLERS.items():
            assert callable(handler), f"Handler {name} is not callable"
