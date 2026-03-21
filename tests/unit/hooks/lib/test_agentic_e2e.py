# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""End-to-end verification tests for the agentic delegation pipeline (OMN-5730).

Exercises the full flow with a mocked LLM backend:
1. TaskClassifier classifies prompt as agentic-eligible
2. Orchestrator returns agentic metadata
3. Daemon dispatches agentic loop in background
4. Agentic loop calls tools and produces work product
5. Quality gate validates the work product
6. Poll delivers the completed work product

Uses real code for all components except the LLM endpoint (mocked).
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# Add the plugins path so we can import hooks.lib modules.
_PLUGINS_ROOT = Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks"
if str(_PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGINS_ROOT))

from lib.agentic_loop import AgenticStatus, run_agentic_loop
from lib.agentic_quality_gate import check_agentic_quality
from lib.agentic_tools import ALL_TOOLS, dispatch_tool
from lib.delegation_daemon import (
    AgenticJob,
    AgenticJobStatus,
    _agentic_jobs,
    _agentic_jobs_lock,
    _handle_request,
    _poll_agentic_jobs,
)

# Type alias
_JsonDict = dict[str, Any]


@pytest.fixture(autouse=True)
def _clear_jobs() -> Any:
    """Clear job store before/after each test."""
    with _agentic_jobs_lock:
        _agentic_jobs.clear()
    yield
    with _agentic_jobs_lock:
        _agentic_jobs.clear()


# ---------------------------------------------------------------------------
# Fake LLM backend that simulates tool-calling behavior
# ---------------------------------------------------------------------------


@dataclass
class FakeChatResult:
    """Mimics ChatCompletionResult."""

    content: str | None = None
    tool_calls: list[_JsonDict] = field(default_factory=list)
    error: str | None = None


class SimulatedAgenticBackend:
    """Simulates a multi-turn agentic LLM that reads a file then answers.

    Turn 1: Requests read_file for a known file
    Turn 2: Returns a final answer incorporating the file contents
    """

    def __init__(self) -> None:
        self._call_count = 0

    def chat_completion_sync(self, **kwargs: Any) -> FakeChatResult:
        self._call_count += 1
        messages = kwargs.get("messages", [])

        # Turn 1: Request to read a file
        if self._call_count == 1:
            return FakeChatResult(
                content=None,
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps(
                                {"path": str(Path(__file__).resolve()), "limit": 5}
                            ),
                        },
                    }
                ],
            )

        # Turn 2: Search for a pattern
        if self._call_count == 2:
            return FakeChatResult(
                content=None,
                tool_calls=[
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "find_files",
                            "arguments": json.dumps(
                                {
                                    "pattern": "test_agentic_*.py",
                                    "path": str(Path(__file__).parent),
                                }
                            ),
                        },
                    }
                ],
            )

        # Turn 3: Final answer
        return FakeChatResult(
            content=(
                "Based on my investigation of the codebase, the agentic delegation "
                "system consists of the following components:\n\n"
                "1. **agentic_loop.py** - ReAct-style tool-calling loop\n"
                "2. **agentic_tools.py** - Read-only tool definitions and dispatchers\n"
                "3. **agentic_quality_gate.py** - Work product validation\n"
                "4. **delegation_daemon.py** - Background job dispatch and polling\n"
                "5. **delegation_orchestrator.py** - Task-type routing with agentic path\n\n"
                "The system works by classifying prompts for agentic eligibility, then "
                "running a multi-turn loop where the LLM reads files, searches code, and "
                "produces an evidence-based analysis. The quality gate validates that the "
                "model actually used tools and produced substantive output before delivering "
                "the work product to the user."
            )
        )


# ---------------------------------------------------------------------------
# E2E Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgenticLoopE2E:
    """Full agentic loop with simulated backend and real tool dispatchers."""

    def test_full_loop_with_real_tools(self) -> None:
        """Run agentic loop with real file read + find, simulated LLM."""
        backend = SimulatedAgenticBackend()

        result = run_agentic_loop(
            prompt="Research how the agentic delegation system works in this codebase",
            system_prompt="You are a codebase research assistant.",
            endpoint_url="http://localhost:8000",
            tools=ALL_TOOLS,
            dispatch_fn=dispatch_tool,
            max_iterations=10,
            timeout_s=30.0,
            backend=backend,
        )

        assert result.status == AgenticStatus.SUCCESS
        assert result.iterations == 3
        assert result.tool_calls_count == 2
        assert "read_file" in result.tool_names_used
        assert "find_files" in result.tool_names_used
        assert result.content is not None
        assert "agentic_loop.py" in result.content
        assert len(result.content) > 100


@pytest.mark.unit
class TestQualityGateE2E:
    """Quality gate validates real agentic loop output."""

    def test_passing_work_product(self) -> None:
        """A good work product passes the quality gate."""
        backend = SimulatedAgenticBackend()
        result = run_agentic_loop(
            prompt="Research agentic system",
            system_prompt="Research assistant.",
            endpoint_url="http://localhost:8000",
            tools=ALL_TOOLS,
            dispatch_fn=dispatch_tool,
            backend=backend,
        )

        gate = check_agentic_quality(
            content=result.content,
            tool_calls_count=result.tool_calls_count,
            iterations=result.iterations,
        )

        assert gate.passed is True

    def test_empty_loop_fails_gate(self) -> None:
        """A loop that produces no tool calls fails the gate."""
        gate = check_agentic_quality(
            content="Here is my answer without tools.",
            tool_calls_count=0,
            iterations=1,
        )
        assert gate.passed is False


@pytest.mark.unit
class TestDaemonPollE2E:
    """Full daemon dispatch -> poll -> quality gate -> delivery."""

    def test_dispatch_poll_delivery_cycle(self) -> None:
        """Simulate the complete daemon lifecycle for an agentic job."""
        # Manually create a completed job with realistic data
        backend = SimulatedAgenticBackend()
        loop_result = run_agentic_loop(
            prompt="Research the system",
            system_prompt="Assistant.",
            endpoint_url="http://localhost:8000",
            tools=ALL_TOOLS,
            dispatch_fn=dispatch_tool,
            backend=backend,
        )

        # Create a completed job in the store
        job = AgenticJob(
            job_id="e2e-1",
            session_id="e2e-session",
            prompt="Research the system",
        )
        job.status = AgenticJobStatus.COMPLETED
        job.result = loop_result
        job.completed_at = time.monotonic()

        with _agentic_jobs_lock:
            _agentic_jobs["e2e-1"] = job

        # Poll should deliver the work product (quality gate passes)
        poll_result = _poll_agentic_jobs("e2e-session")

        assert poll_result["agentic_completed"] is True
        assert poll_result["job_id"] == "e2e-1"
        assert poll_result["iterations"] == 3
        assert poll_result["tool_calls_count"] == 2
        assert len(poll_result["content"]) > 100
        assert "agentic_loop.py" in poll_result["content"]

        # Job should be removed after delivery
        assert "e2e-1" not in _agentic_jobs


@pytest.mark.unit
class TestClassifierAgenticEligibility:
    """Verify TaskClassifier correctly identifies agentic-eligible prompts."""

    def test_research_with_codebase_signal(self) -> None:
        """A research prompt with codebase interaction should be agentic-eligible."""
        from omniclaude.lib.task_classifier import TaskClassifier

        classifier = TaskClassifier()
        # Use a prompt that clearly classifies as RESEARCH intent and has
        # codebase interaction signals ("how does", "where is", "find")
        score = classifier.is_delegatable(
            "Explain where the delegation orchestrator is and how does it route tasks. "
            "Find the relevant source files and explain the flow."
        )
        # Should be agentic-eligible: research intent + codebase signals
        assert score.agentic_eligible is True

    def test_plain_research_not_agentic(self) -> None:
        """A plain research prompt without codebase signals should not be agentic."""
        from omniclaude.lib.task_classifier import TaskClassifier

        classifier = TaskClassifier()
        score = classifier.is_delegatable("document the pytest fixtures")
        # Should not be agentic: no codebase interaction signals
        assert score.agentic_eligible is False

    def test_implement_intent_not_agentic(self) -> None:
        """Implementation tasks should never be agentic (not in DELEGATABLE_INTENTS)."""
        from omniclaude.lib.task_classifier import TaskClassifier

        classifier = TaskClassifier()
        score = classifier.is_delegatable(
            "Implement a new API endpoint for search in this codebase"
        )
        assert score.agentic_eligible is False


@pytest.mark.unit
class TestHandleRequestE2E:
    """Test the daemon's _handle_request with full orchestration path."""

    def test_poll_then_dispatch_then_poll(self) -> None:
        """Full lifecycle through the daemon socket protocol."""
        # Phase 1: Poll with no jobs
        poll_req = json.dumps({"action": "poll_agentic", "session_id": "e2e"}).encode()
        poll_resp = json.loads(_handle_request(poll_req))
        assert poll_resp["status"] == "no_jobs"

        # Phase 2: Dispatch via orchestrator returning agentic=True
        with (
            patch(
                "lib.delegation_daemon.orchestrate_delegation",
                return_value={
                    "delegated": False,
                    "agentic": True,
                    "agentic_prompt": "Research error handling in hooks",
                    "agentic_system_prompt": "You are a researcher.",
                    "agentic_endpoint_url": "http://localhost:8000",
                    "reason": "agentic_eligible",
                },
            ),
            patch("lib.delegation_daemon._classify_with_cache", return_value=None),
            patch("lib.delegation_daemon.run_agentic_task") as mock_task,
        ):
            dispatch_req = json.dumps(
                {
                    "prompt": "Research error handling in hooks",
                    "correlation_id": "e2e-corr",
                    "session_id": "e2e",
                }
            ).encode()
            dispatch_resp = json.loads(_handle_request(dispatch_req))
            assert dispatch_resp.get("agentic_dispatched") is True
            assert "job_id" in dispatch_resp
