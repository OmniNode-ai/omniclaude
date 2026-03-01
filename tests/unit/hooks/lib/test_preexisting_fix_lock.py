# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for preexisting_fix_lock module.

Tests the distributed fix lock used by ticket-pipeline's Phase 0 to prevent
concurrent pipeline workers from fixing the same pre-existing issue simultaneously.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent.parent.parent
        / "plugins"
        / "onex"
        / "hooks"
        / "lib"
    ),
)

from preexisting_fix_lock import PreexistingFixLock


FINGERPRINT = "abc123def456"
RUN_ID = "epic-OMN-3266-test"
TICKET_ID = "OMN-3260"


@pytest.mark.unit
class TestPreexistingFixLockAcquire:
    """Tests for lock acquisition."""

    def test_acquire_succeeds_when_not_locked(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path)
        result = lock.acquire(FINGERPRINT, run_id=RUN_ID, ticket_id=TICKET_ID)
        assert result is True

    def test_acquire_fails_when_already_locked(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path)
        lock.acquire(FINGERPRINT, run_id=RUN_ID, ticket_id=TICKET_ID)
        second = lock.acquire(FINGERPRINT, run_id="other-run", ticket_id=TICKET_ID)
        assert second is False

    def test_acquire_creates_lock_file(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path)
        lock.acquire(FINGERPRINT, run_id=RUN_ID, ticket_id=TICKET_ID)
        assert (tmp_path / f"{FINGERPRINT}.lock").exists()

    def test_acquire_lock_file_contains_metadata(self, tmp_path: Path) -> None:
        import json

        lock = PreexistingFixLock(lock_dir=tmp_path)
        lock.acquire(FINGERPRINT, run_id=RUN_ID, ticket_id=TICKET_ID)
        data = json.loads((tmp_path / f"{FINGERPRINT}.lock").read_text())
        assert data["run_id"] == RUN_ID
        assert data["ticket_id"] == TICKET_ID
        assert data["fingerprint"] == FINGERPRINT
        assert "acquired_at" in data

    def test_different_fingerprints_acquire_independently(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path)
        fp1 = "aaaaaaaaaaaa"
        fp2 = "bbbbbbbbbbbb"
        assert lock.acquire(fp1, run_id=RUN_ID, ticket_id=TICKET_ID) is True
        assert lock.acquire(fp2, run_id=RUN_ID, ticket_id=TICKET_ID) is True

    def test_acquire_breaks_stale_lock(self, tmp_path: Path) -> None:
        # Timeout of 0 means any lock is immediately stale.
        lock = PreexistingFixLock(lock_dir=tmp_path, timeout_seconds=0)
        # Write a "stale" lock file directly.
        lock_file = tmp_path / f"{FINGERPRINT}.lock"
        lock_file.write_text('{"run_id": "old-run"}')
        # Force the mtime to be in the past (just ensure it's not newer than now).
        result = lock.acquire(FINGERPRINT, run_id=RUN_ID, ticket_id=TICKET_ID)
        assert result is True

    def test_acquire_creates_lock_dir_if_missing(self, tmp_path: Path) -> None:
        nested = tmp_path / "nested" / "locks"
        lock = PreexistingFixLock(lock_dir=nested)
        assert lock.acquire(FINGERPRINT, run_id=RUN_ID, ticket_id=TICKET_ID) is True
        assert nested.exists()


@pytest.mark.unit
class TestPreexistingFixLockRelease:
    """Tests for lock release."""

    def test_release_removes_lock_file(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path)
        lock.acquire(FINGERPRINT, run_id=RUN_ID, ticket_id=TICKET_ID)
        lock.release(FINGERPRINT)
        assert not (tmp_path / f"{FINGERPRINT}.lock").exists()

    def test_release_is_idempotent(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path)
        # Release without prior acquire — should not raise.
        lock.release(FINGERPRINT)

    def test_after_release_lock_can_be_reacquired(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path)
        lock.acquire(FINGERPRINT, run_id=RUN_ID, ticket_id=TICKET_ID)
        lock.release(FINGERPRINT)
        assert lock.acquire(FINGERPRINT, run_id="new-run", ticket_id=TICKET_ID) is True


@pytest.mark.unit
class TestPreexistingFixLockIsLocked:
    """Tests for is_locked check."""

    def test_not_locked_initially(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path)
        assert lock.is_locked(FINGERPRINT) is False

    def test_locked_after_acquire(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path)
        lock.acquire(FINGERPRINT, run_id=RUN_ID, ticket_id=TICKET_ID)
        assert lock.is_locked(FINGERPRINT) is True

    def test_not_locked_after_release(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path)
        lock.acquire(FINGERPRINT, run_id=RUN_ID, ticket_id=TICKET_ID)
        lock.release(FINGERPRINT)
        assert lock.is_locked(FINGERPRINT) is False

    def test_stale_lock_treated_as_not_locked(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path, timeout_seconds=0)
        lock_file = tmp_path / f"{FINGERPRINT}.lock"
        lock_file.write_text('{"run_id": "old"}')
        assert lock.is_locked(FINGERPRINT) is False


@pytest.mark.unit
class TestPreexistingFixLockHolder:
    """Tests for holder metadata retrieval."""

    def test_holder_returns_none_when_not_locked(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path)
        assert lock.holder(FINGERPRINT) is None

    def test_holder_returns_metadata_when_locked(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path)
        lock.acquire(FINGERPRINT, run_id=RUN_ID, ticket_id=TICKET_ID)
        info = lock.holder(FINGERPRINT)
        assert info is not None
        assert info["run_id"] == RUN_ID
        assert info["ticket_id"] == TICKET_ID

    def test_holder_returns_none_for_stale_lock(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path, timeout_seconds=0)
        lock_file = tmp_path / f"{FINGERPRINT}.lock"
        lock_file.write_text('{"run_id": "old"}')
        assert lock.holder(FINGERPRINT) is None

    def test_holder_returns_none_for_corrupt_lock_file(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path)
        lock_file = tmp_path / f"{FINGERPRINT}.lock"
        lock_file.write_text("not-valid-json")
        # Corrupt file should not raise; returns None.
        assert lock.holder(FINGERPRINT) is None


@pytest.mark.unit
class TestPreexistingFixLockTimeout:
    """Tests for stale lock expiry behavior."""

    def test_stale_lock_broken_on_acquire(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path, timeout_seconds=1)
        lock.acquire(FINGERPRINT, run_id="old-run", ticket_id=TICKET_ID)
        # Wait for lock to become stale.
        time.sleep(1.1)
        assert lock.acquire(FINGERPRINT, run_id=RUN_ID, ticket_id=TICKET_ID) is True

    def test_fresh_lock_not_broken(self, tmp_path: Path) -> None:
        lock = PreexistingFixLock(lock_dir=tmp_path, timeout_seconds=60)
        lock.acquire(FINGERPRINT, run_id="owner-run", ticket_id=TICKET_ID)
        assert lock.acquire(FINGERPRINT, run_id=RUN_ID, ticket_id=TICKET_ID) is False
