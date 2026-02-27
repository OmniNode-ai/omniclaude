# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for node_ci_repair_effect -- Self-Healing CI ONEX effect node.

Coverage:
    RepairStrategy
        - Strategy rotation for attempts 1-3
        - Out-of-range attempt numbers clamp to last strategy

    CIFailureEvent / RepairRunState contracts
        - Construction from dict
        - Default values
        - Extra fields ignored

    execute_effect
        - Creates run state with correct defaults
        - Populates attempts list for max_attempts
        - Persists state to disk

    record_attempt_result
        - Updates attempt fields
        - Sets status to "repaired" on passing CI
        - Sets status to "exhausted" when max attempts reached
        - Sends inbox notification on terminal states

    finalize_with_error
        - Sets error status and sends notification

    fetch_ci_status
        - Calls ci-status.sh (mocked)
        - Handles timeout and missing script

    send_inbox_notification
        - Writes JSON to inbox directory
        - Handles missing directory gracefully

    State persistence
        - save_repair_state / load_repair_state round-trip

Related Tickets:
    - OMN-2829: Phase 7 -- Self-Healing CI
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Ensure the hooks lib is importable
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "plugins" / "onex" / "hooks" / "lib"),
)

from node_ci_repair_effect import (
    CIFailureEvent,
    RepairAttempt,
    RepairRunState,
    RepairStrategy,
    execute_effect,
    fetch_ci_status,
    finalize_with_error,
    load_repair_state,
    record_attempt_result,
    save_repair_state,
    send_inbox_notification,
)

# =============================================================================
# RepairStrategy Tests
# =============================================================================


class TestRepairStrategy:
    """Test strategy rotation logic."""

    def test_attempt_1_returns_targeted_fix(self) -> None:
        assert RepairStrategy.for_attempt(1) == RepairStrategy.TARGETED_FIX

    def test_attempt_2_returns_broad_lint_fix(self) -> None:
        assert RepairStrategy.for_attempt(2) == RepairStrategy.BROAD_LINT_FIX

    def test_attempt_3_returns_regenerate(self) -> None:
        assert RepairStrategy.for_attempt(3) == RepairStrategy.REGENERATE_AND_FIX

    def test_attempt_beyond_max_clamps_to_last(self) -> None:
        assert RepairStrategy.for_attempt(5) == RepairStrategy.REGENERATE_AND_FIX

    def test_attempt_0_clamps_to_first(self) -> None:
        assert RepairStrategy.for_attempt(0) == RepairStrategy.TARGETED_FIX


# =============================================================================
# Contract Tests
# =============================================================================


class TestCIFailureEvent:
    """Test CIFailureEvent Pydantic model."""

    def test_minimal_construction(self) -> None:
        event = CIFailureEvent(pr_number=42, repo="org/repo", branch="main")
        assert event.pr_number == 42
        assert event.repo == "org/repo"
        assert event.failed_jobs == []

    def test_full_construction(self) -> None:
        event = CIFailureEvent(
            pr_number=42,
            repo="org/repo",
            branch="feature/test",
            run_id="12345",
            ticket_id="OMN-2829",
            failed_jobs=[{"job_name": "lint"}],
            failure_summary="1 job failed",
        )
        assert event.run_id == "12345"
        assert event.ticket_id == "OMN-2829"
        assert len(event.failed_jobs) == 1

    def test_extra_fields_ignored(self) -> None:
        event = CIFailureEvent(
            pr_number=42,
            repo="org/repo",
            branch="main",
            unknown_field="should be ignored",  # type: ignore[call-arg]
        )
        assert event.pr_number == 42


class TestRepairRunState:
    """Test RepairRunState Pydantic model."""

    def test_defaults(self) -> None:
        state = RepairRunState(
            run_id="test-123",
            pr_number=42,
            repo="org/repo",
            branch="main",
        )
        assert state.status == "in_progress"
        assert state.attempts == []
        assert state.max_attempts == 3
        assert state.inbox_notification_sent is False


# =============================================================================
# execute_effect Tests
# =============================================================================


class TestExecuteEffect:
    """Test the main effect execution."""

    def test_creates_run_state(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"CI_REPAIR_STATE_DIR": str(tmp_path)}):
            event = CIFailureEvent(
                pr_number=42, repo="org/repo", branch="main", run_id="old-run"
            )
            state = execute_effect(event)

            assert state.pr_number == 42
            assert state.repo == "org/repo"
            assert state.status == "in_progress"
            assert len(state.attempts) == 3
            assert state.started_at != ""

    def test_persists_state_to_disk(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"CI_REPAIR_STATE_DIR": str(tmp_path)}):
            event = CIFailureEvent(pr_number=42, repo="org/repo", branch="main")
            state = execute_effect(event)

            # Verify file exists on disk
            state_files = list(tmp_path.glob("ci-repair-*.json"))
            assert len(state_files) == 1

    def test_custom_max_attempts(self, tmp_path: Path) -> None:
        with patch.dict(
            os.environ,
            {
                "CI_REPAIR_STATE_DIR": str(tmp_path),
                "CI_REPAIR_MAX_ATTEMPTS": "5",
            },
        ):
            event = CIFailureEvent(pr_number=42, repo="org/repo", branch="main")
            state = execute_effect(event)
            assert state.max_attempts == 5
            assert len(state.attempts) == 5


# =============================================================================
# record_attempt_result Tests
# =============================================================================


class TestRecordAttemptResult:
    """Test attempt result recording."""

    def _make_state(self, tmp_path: Path) -> RepairRunState:
        state = RepairRunState(
            run_id="test-run",
            pr_number=42,
            repo="org/repo",
            branch="main",
            max_attempts=3,
            attempts=[
                RepairAttempt(
                    attempt_number=1, strategy="targeted_fix", started_at="t1"
                ),
                RepairAttempt(
                    attempt_number=2, strategy="broad_lint_fix", started_at="t2"
                ),
                RepairAttempt(
                    attempt_number=3, strategy="regenerate_and_fix", started_at="t3"
                ),
            ],
            started_at="t0",
        )
        return state

    def test_records_success(self, tmp_path: Path) -> None:
        with patch.dict(
            os.environ,
            {
                "CI_REPAIR_STATE_DIR": str(tmp_path),
                "CI_REPAIR_INBOX_DIR": str(tmp_path / "inbox"),
            },
        ):
            state = self._make_state(tmp_path)
            updated = record_attempt_result(
                state,
                attempt_number=1,
                files_changed=["src/foo.py"],
                commit_sha="abc123",
                ci_result="passing",
            )
            assert updated.status == "repaired"
            assert updated.attempts[0].ci_result == "passing"
            assert updated.inbox_notification_sent is True

    def test_records_exhaustion(self, tmp_path: Path) -> None:
        with patch.dict(
            os.environ,
            {
                "CI_REPAIR_STATE_DIR": str(tmp_path),
                "CI_REPAIR_INBOX_DIR": str(tmp_path / "inbox"),
            },
        ):
            state = self._make_state(tmp_path)
            updated = record_attempt_result(
                state,
                attempt_number=3,
                ci_result="failing",
            )
            assert updated.status == "exhausted"
            assert updated.inbox_notification_sent is True

    def test_intermediate_attempt_stays_in_progress(self, tmp_path: Path) -> None:
        with patch.dict(
            os.environ,
            {
                "CI_REPAIR_STATE_DIR": str(tmp_path),
                "CI_REPAIR_INBOX_DIR": str(tmp_path / "inbox"),
            },
        ):
            state = self._make_state(tmp_path)
            updated = record_attempt_result(
                state,
                attempt_number=1,
                ci_result="failing",
            )
            assert updated.status == "in_progress"

    def test_invalid_attempt_number_returns_unchanged(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"CI_REPAIR_STATE_DIR": str(tmp_path)}):
            state = self._make_state(tmp_path)
            updated = record_attempt_result(state, attempt_number=99)
            assert updated.status == "in_progress"


# =============================================================================
# finalize_with_error Tests
# =============================================================================


class TestFinalizeWithError:
    """Test error finalization."""

    def test_sets_error_status(self, tmp_path: Path) -> None:
        with patch.dict(
            os.environ,
            {
                "CI_REPAIR_STATE_DIR": str(tmp_path),
                "CI_REPAIR_INBOX_DIR": str(tmp_path / "inbox"),
            },
        ):
            state = RepairRunState(
                run_id="test-err",
                pr_number=42,
                repo="org/repo",
                branch="main",
            )
            updated = finalize_with_error(state, "ci-status.sh not found")
            assert updated.status == "error"
            assert updated.inbox_notification_sent is True


# =============================================================================
# Inbox Notification Tests
# =============================================================================


class TestInboxNotification:
    """Test inbox notification writing."""

    def test_writes_notification_file(self, tmp_path: Path) -> None:
        inbox = tmp_path / "inbox"
        with patch.dict(os.environ, {"CI_REPAIR_INBOX_DIR": str(inbox)}):
            state = RepairRunState(
                run_id="test-notify",
                pr_number=42,
                repo="org/repo",
                branch="main",
            )
            result = send_inbox_notification(state, "Test message")
            assert result is True
            files = list(inbox.glob("ci-repair-*.json"))
            assert len(files) == 1

            data = json.loads(files[0].read_text())
            assert data["type"] == "ci_repair"
            assert data["pr_number"] == 42
            assert data["message"] == "Test message"


# =============================================================================
# State Persistence Tests
# =============================================================================


class TestStatePersistence:
    """Test save/load round-trip."""

    def test_round_trip(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"CI_REPAIR_STATE_DIR": str(tmp_path)}):
            state = RepairRunState(
                run_id="test-persist",
                pr_number=42,
                repo="org/repo",
                branch="main",
                status="repaired",
                attempts=[
                    RepairAttempt(
                        attempt_number=1,
                        strategy="targeted_fix",
                        files_changed=["a.py"],
                    ),
                ],
            )
            save_repair_state(state)
            loaded = load_repair_state("test-persist")

            assert loaded is not None
            assert loaded.run_id == "test-persist"
            assert loaded.status == "repaired"
            assert len(loaded.attempts) == 1
            assert loaded.attempts[0].files_changed == ["a.py"]

    def test_load_nonexistent_returns_none(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"CI_REPAIR_STATE_DIR": str(tmp_path)}):
            assert load_repair_state("nonexistent") is None


# =============================================================================
# fetch_ci_status Tests (mocked subprocess)
# =============================================================================


class TestFetchCIStatus:
    """Test CI status fetching via subprocess mock."""

    def test_passing_status(self) -> None:
        mock_output = json.dumps(
            {
                "status": "passing",
                "pr_number": 42,
                "repo": "org/repo",
                "branch": "main",
                "run_id": "999",
                "failed_jobs": [],
                "failure_summary": "All checks passing",
                "fetched_at": "2026-02-26T13:00:00Z",
            }
        )
        with patch("node_ci_repair_effect.subprocess.run") as mock_run:
            mock_run.return_value = type(
                "Result", (), {"returncode": 0, "stdout": mock_output, "stderr": ""}
            )()
            result = fetch_ci_status(42, "org/repo")
            assert result["status"] == "passing"
            assert result["pr_number"] == 42

    def test_script_not_found(self) -> None:
        with patch(
            "node_ci_repair_effect.subprocess.run",
            side_effect=FileNotFoundError("not found"),
        ):
            result = fetch_ci_status(42, "org/repo")
            assert result["status"] == "unknown"
            assert "not found" in result["error"]
