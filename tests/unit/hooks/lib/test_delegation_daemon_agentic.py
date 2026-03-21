# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for agentic job dispatch in delegation_daemon.py (OMN-5725).

Coverage:
- poll_agentic action routing
- Agentic job lifecycle (start, poll running, poll completed, poll failed)
- Job GC (completed TTL, max TTL)
- Agentic dispatch from orchestrator response
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Add the plugins path so we can import hooks.lib modules.
_PLUGINS_ROOT = Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks"
if str(_PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGINS_ROOT))

from lib.delegation_daemon import (
    AgenticJob,
    AgenticJobStatus,
    _agentic_jobs,
    _agentic_jobs_lock,
    _gc_agentic_jobs,
    _handle_request,
    _poll_agentic_jobs,
)


@pytest.fixture(autouse=True)
def _clear_jobs() -> Any:
    """Clear the agentic job store before/after each test."""
    with _agentic_jobs_lock:
        _agentic_jobs.clear()
    yield
    with _agentic_jobs_lock:
        _agentic_jobs.clear()


# ---------------------------------------------------------------------------
# Tests: poll_agentic action
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPollAgenticAction:
    def test_poll_no_jobs(self) -> None:
        result = _poll_agentic_jobs("session-1")
        assert result["agentic_completed"] is False
        assert result["status"] == "no_jobs"

    def test_poll_running_job(self) -> None:
        job = AgenticJob(job_id="j1", session_id="session-1", prompt="test")
        with _agentic_jobs_lock:
            _agentic_jobs["j1"] = job

        result = _poll_agentic_jobs("session-1")
        assert result["agentic_completed"] is False
        assert result["status"] == "running"
        assert result["job_id"] == "j1"

    def test_poll_completed_job(self) -> None:
        # Create a fake completed result
        fake_result = MagicMock()
        fake_result.content = "Research findings here."
        fake_result.iterations = 3
        fake_result.tool_calls_count = 5
        fake_result.tool_names_used = {"read_file", "search_content"}
        fake_result.status = MagicMock(value="success")

        job = AgenticJob(
            job_id="j2",
            session_id="session-1",
            prompt="test",
        )
        job.status = AgenticJobStatus.COMPLETED
        job.result = fake_result
        job.completed_at = time.monotonic()

        with _agentic_jobs_lock:
            _agentic_jobs["j2"] = job

        result = _poll_agentic_jobs("session-1")
        assert result["agentic_completed"] is True
        assert result["content"] == "Research findings here."
        assert result["iterations"] == 3
        assert result["tool_calls_count"] == 5
        assert "read_file" in result["tool_names"]

        # Job should be removed after delivery
        assert "j2" not in _agentic_jobs

    def test_poll_failed_job(self) -> None:
        job = AgenticJob(
            job_id="j3",
            session_id="session-1",
            prompt="test",
        )
        job.status = AgenticJobStatus.FAILED
        job.error = "TIMEOUT"
        job.completed_at = time.monotonic()

        with _agentic_jobs_lock:
            _agentic_jobs["j3"] = job

        result = _poll_agentic_jobs("session-1")
        assert result["agentic_completed"] is False
        assert result["error"] == "TIMEOUT"
        # Job should be removed after delivery
        assert "j3" not in _agentic_jobs

    def test_poll_wrong_session(self) -> None:
        job = AgenticJob(job_id="j4", session_id="session-other", prompt="test")
        with _agentic_jobs_lock:
            _agentic_jobs["j4"] = job

        result = _poll_agentic_jobs("session-1")
        assert result["status"] == "no_jobs"


# ---------------------------------------------------------------------------
# Tests: handle_request with poll_agentic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleRequestPollAction:
    def test_poll_action_routes_correctly(self) -> None:
        req = json.dumps({"action": "poll_agentic", "session_id": "s1"}).encode()
        resp = _handle_request(req)
        data = json.loads(resp)
        assert "agentic_completed" in data

    def test_standard_request_still_works(self) -> None:
        """Standard delegation requests should still work when orchestrator is available."""
        with (
            patch(
                "lib.delegation_daemon.orchestrate_delegation",
                return_value={"delegated": False, "reason": "not_delegatable"},
            ),
            patch(
                "lib.delegation_daemon._classify_with_cache",
                return_value=None,
            ),
        ):
            req = json.dumps(
                {"prompt": "test", "correlation_id": "c1", "session_id": "s1"}
            ).encode()
            resp = _handle_request(req)
            data = json.loads(resp)
            assert data["delegated"] is False


# ---------------------------------------------------------------------------
# Tests: GC
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgenticJobGC:
    def test_gc_removes_old_completed_jobs(self) -> None:
        job = AgenticJob(
            job_id="gc1",
            session_id="s",
            prompt="test",
            started_at=time.monotonic() - 200,
        )
        job.status = AgenticJobStatus.COMPLETED
        job.completed_at = time.monotonic() - 100  # 100s ago, exceeds 60s TTL

        with _agentic_jobs_lock:
            _agentic_jobs["gc1"] = job

        _gc_agentic_jobs()
        assert "gc1" not in _agentic_jobs

    def test_gc_keeps_recent_completed_jobs(self) -> None:
        job = AgenticJob(
            job_id="gc2",
            session_id="s",
            prompt="test",
        )
        job.status = AgenticJobStatus.COMPLETED
        job.completed_at = time.monotonic()

        with _agentic_jobs_lock:
            _agentic_jobs["gc2"] = job

        _gc_agentic_jobs()
        assert "gc2" in _agentic_jobs

    def test_gc_removes_very_old_running_jobs(self) -> None:
        job = AgenticJob(
            job_id="gc3",
            session_id="s",
            prompt="test",
            started_at=time.monotonic() - 400,  # Exceeds 300s max TTL
        )
        with _agentic_jobs_lock:
            _agentic_jobs["gc3"] = job

        _gc_agentic_jobs()
        assert "gc3" not in _agentic_jobs


# ---------------------------------------------------------------------------
# Tests: Agentic dispatch from orchestrator
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgenticDispatch:
    def test_agentic_response_triggers_dispatch(self) -> None:
        """When orchestrator returns agentic=True, daemon starts a job."""
        agentic_result = {
            "delegated": False,
            "agentic": True,
            "agentic_prompt": "Research error handling",
            "agentic_system_prompt": "You are a researcher.",
            "agentic_endpoint_url": "http://localhost:8000",
            "reason": "agentic_eligible",
        }

        with (
            patch(
                "lib.delegation_daemon.orchestrate_delegation",
                return_value=agentic_result,
            ),
            patch(
                "lib.delegation_daemon._classify_with_cache",
                return_value=None,
            ),
            patch(
                "lib.delegation_daemon.run_agentic_task",
                return_value=MagicMock(),
            ) as mock_task,
        ):
            # Make run_agentic_task available (not None)
            req = json.dumps(
                {
                    "prompt": "Research error handling",
                    "correlation_id": "c1",
                    "session_id": "s1",
                }
            ).encode()
            resp = _handle_request(req)
            data = json.loads(resp)
            assert data.get("agentic_dispatched") is True
            assert "job_id" in data
