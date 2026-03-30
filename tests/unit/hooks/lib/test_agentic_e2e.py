# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""End-to-end verification tests for the agentic delegation pipeline (OMN-5730, OMN-6962).

Required failure-path tests (OMN-6962):
1. Malformed tool-call from backend -> loop recovers with error message
2. Tool dispatch failure -> error propagated back into loop as tool result
3. Quality-gate rejection -> result discarded, Claude path continues
4. Completed result injected once only -> second poll returns consumed
5. Second dispatch during active job -> rejected with active_job_exists
6. Loop hits context budget -> returns best partial result with budget_exhausted
7. Backend returns empty response -> loop terminates gracefully
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_LIB_DIR = Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"


def _load_module(name: str) -> Any:
    path = _LIB_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_mod_loop = _load_module("agentic_loop")
_mod_gate = _load_module("agentic_quality_gate")
_mod_tools = _load_module("agentic_tools")
_mod_daemon = _load_module("delegation_daemon")

AgenticStatus = _mod_loop.AgenticStatus
run_agentic_loop = _mod_loop.run_agentic_loop
check_agentic_quality = _mod_gate.check_agentic_quality
ALL_TOOLS = _mod_tools.ALL_TOOLS
dispatch_tool = _mod_tools.dispatch_tool
AgenticJob = _mod_daemon.AgenticJob
AgenticJobStatus = _mod_daemon.AgenticJobStatus
_agentic_jobs = _mod_daemon._agentic_jobs
_agentic_jobs_lock = _mod_daemon._agentic_jobs_lock
_handle_request = _mod_daemon._handle_request
_poll_agentic_jobs = _mod_daemon._poll_agentic_jobs

_JsonDict = dict[str, Any]


@pytest.fixture(autouse=True)
def _clear_jobs() -> Any:
    with _agentic_jobs_lock:
        _agentic_jobs.clear()
    yield
    with _agentic_jobs_lock:
        _agentic_jobs.clear()


@dataclass
class FakeChatResult:
    content: str | None = None
    tool_calls: list[_JsonDict] = field(default_factory=list)
    error: str | None = None


class SimulatedAgenticBackend:
    def __init__(self) -> None:
        self._call_count = 0

    def chat_completion_sync(self, **kwargs: Any) -> FakeChatResult:
        self._call_count += 1
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
        return FakeChatResult(
            content=(
                "Based on my investigation of the codebase, the agentic delegation "
                "system consists of the following components:\n\n"
                "1. **agentic_loop.py** - ReAct-style tool-calling loop\n"
                "2. **agentic_tools.py** - Read-only tool definitions and dispatchers\n"
                "3. **agentic_quality_gate.py** - Work product validation\n"
                "4. **delegation_daemon.py** - Background job dispatch and polling\n"
                "5. **delegation_orchestrator.py** - Task-type routing with agentic path\n\n"
                "The system works by classifying prompts, then running a multi-turn loop "
                "where the LLM reads files and produces an evidence-based analysis."
            )
        )


@pytest.mark.unit
class TestAgenticLoopE2E:
    def test_full_loop_with_real_tools(self) -> None:
        backend = SimulatedAgenticBackend()
        result = run_agentic_loop(
            prompt="Research how the agentic delegation system works",
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
        assert result.content is not None
        assert "agentic_loop.py" in result.content


@pytest.mark.unit
class TestQualityGateE2E:
    def test_passing_work_product(self) -> None:
        backend = SimulatedAgenticBackend()
        result = run_agentic_loop(
            prompt="Research",
            system_prompt="Assistant.",
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
        gate = check_agentic_quality(
            content="Here is my answer.", tool_calls_count=0, iterations=1
        )
        assert gate.passed is False


@pytest.mark.unit
class TestDaemonPollE2E:
    def test_dispatch_poll_delivery_cycle(self) -> None:
        backend = SimulatedAgenticBackend()
        loop_result = run_agentic_loop(
            prompt="Research",
            system_prompt="Assistant.",
            endpoint_url="http://localhost:8000",
            tools=ALL_TOOLS,
            dispatch_fn=dispatch_tool,
            backend=backend,
        )
        job = AgenticJob(job_id="e2e-1", session_id="e2e-session", prompt="Research")
        job.status = AgenticJobStatus.COMPLETED
        job.result = loop_result
        job.completed_at = time.monotonic()
        with _agentic_jobs_lock:
            _agentic_jobs["e2e-1"] = job
        poll_result = _poll_agentic_jobs("e2e-session")
        assert poll_result["agentic_completed"] is True
        assert poll_result["job_id"] == "e2e-1"
        assert "e2e-1" not in _agentic_jobs


@pytest.mark.unit
class TestClassifierAgenticEligibility:
    def test_research_with_codebase_signal(self) -> None:
        from omniclaude.lib.task_classifier import TaskClassifier

        classifier = TaskClassifier()
        score = classifier.is_delegatable(
            "Explain where the delegation orchestrator is and how does it route tasks. "
            "Find the relevant source files and explain the flow."
        )
        assert score.agentic_eligible is True

    def test_plain_research_not_agentic(self) -> None:
        from omniclaude.lib.task_classifier import TaskClassifier

        classifier = TaskClassifier()
        score = classifier.is_delegatable("document the pytest fixtures")
        assert score.agentic_eligible is False

    def test_implement_intent_not_agentic(self) -> None:
        from omniclaude.lib.task_classifier import TaskClassifier

        classifier = TaskClassifier()
        score = classifier.is_delegatable(
            "Implement a new API endpoint for search in this codebase"
        )
        assert score.agentic_eligible is False


@pytest.mark.unit
class TestHandleRequestE2E:
    def test_poll_then_dispatch_then_poll(self) -> None:
        poll_req = json.dumps({"action": "poll_agentic", "session_id": "e2e"}).encode()
        poll_resp = json.loads(_handle_request(poll_req))
        assert poll_resp["status"] == "no_jobs"

        with (
            patch.object(
                _mod_daemon,
                "orchestrate_delegation",
                return_value={
                    "delegated": False,
                    "agentic": True,
                    "agentic_prompt": "Research error handling",
                    "agentic_system_prompt": "You are a researcher.",
                    "agentic_endpoint_url": "http://localhost:8000",
                    "reason": "agentic_eligible",
                },
            ),
            patch.object(_mod_daemon, "_classify_with_cache", return_value=None),
            patch.object(_mod_daemon, "run_agentic_task") as mock_task,
        ):
            dispatch_req = json.dumps(
                {
                    "prompt": "Research error handling",
                    "correlation_id": "e2e-corr",
                    "session_id": "e2e",
                }
            ).encode()
            dispatch_resp = json.loads(_handle_request(dispatch_req))
            assert dispatch_resp.get("agentic_dispatched") is True


# =========== Required Failure-Path Tests (OMN-6962) ===========


@pytest.mark.unit
class TestFailurePath1MalformedToolCall:
    def test_malformed_tool_call_recovery(self) -> None:
        responses = [
            FakeChatResult(
                content=None,
                tool_calls=[
                    {
                        "id": "call_bad",
                        "type": "function",
                        "function": {"arguments": "{}"},
                    },
                    {
                        "id": "call_good",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps(
                                {"path": str(Path(__file__).resolve()), "limit": 3}
                            ),
                        },
                    },
                ],
            ),
            FakeChatResult(
                content="Found the file src/handler.py with def process_request at line 10."
            ),
        ]
        idx = 0

        class B:
            def chat_completion_sync(self, **kw: Any) -> FakeChatResult:
                nonlocal idx
                r = responses[min(idx, len(responses) - 1)]
                idx += 1
                return r

        result = run_agentic_loop(
            prompt="Test",
            system_prompt="System",
            endpoint_url="http://localhost:8000",
            tools=ALL_TOOLS,
            dispatch_fn=dispatch_tool,
            backend=B(),
        )
        assert result.status == AgenticStatus.SUCCESS
        assert result.tool_calls_count >= 1


@pytest.mark.unit
class TestFailurePath2ToolDispatchFailure:
    def test_file_not_found_propagated(self) -> None:
        responses = [
            FakeChatResult(
                content=None,
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps({"path": "/nonexistent/file.py"}),
                        },
                    }
                ],
            ),
            FakeChatResult(content="The file was not found at /nonexistent/file.py."),
        ]
        idx = 0

        class B:
            def chat_completion_sync(self, **kw: Any) -> FakeChatResult:
                nonlocal idx
                r = responses[min(idx, len(responses) - 1)]
                idx += 1
                return r

        result = run_agentic_loop(
            prompt="Read",
            system_prompt="System",
            endpoint_url="http://localhost:8000",
            tools=ALL_TOOLS,
            dispatch_fn=dispatch_tool,
            backend=B(),
        )
        assert result.status == AgenticStatus.SUCCESS
        assert result.iterations == 2


@pytest.mark.unit
class TestFailurePath3QualityGateRejection:
    def test_gate_rejection_cleans_up(self) -> None:
        job = AgenticJob(job_id="gate-fail", session_id="gate-session", prompt="Test")
        job.status = AgenticJobStatus.COMPLETED

        @dataclass
        class FakeResult:
            content: str | None = "This is a general discussion about software " * 10
            iterations: int = 3
            tool_calls_count: int = 2
            status: Any = AgenticStatus.SUCCESS
            tool_names_used: set[str] = field(default_factory=lambda: {"read_file"})
            error: str | None = None
            total_message_bytes: int = 0

        job.result = FakeResult()
        job.completed_at = time.monotonic()
        with _agentic_jobs_lock:
            _agentic_jobs["gate-fail"] = job
        poll_result = _poll_agentic_jobs("gate-session")
        assert poll_result.get("agentic_completed") is not True or poll_result.get(
            "quality_gate_failed"
        )
        assert "gate-fail" not in _agentic_jobs


@pytest.mark.unit
class TestFailurePath4SingleConsumeDelivery:
    def test_second_poll_returns_no_jobs(self) -> None:
        backend = SimulatedAgenticBackend()
        loop_result = run_agentic_loop(
            prompt="Research",
            system_prompt="Assistant.",
            endpoint_url="http://localhost:8000",
            tools=ALL_TOOLS,
            dispatch_fn=dispatch_tool,
            backend=backend,
        )
        job = AgenticJob(
            job_id="consume-1", session_id="consume-session", prompt="Research"
        )
        job.status = AgenticJobStatus.COMPLETED
        job.result = loop_result
        job.completed_at = time.monotonic()
        with _agentic_jobs_lock:
            _agentic_jobs["consume-1"] = job
        first_poll = _poll_agentic_jobs("consume-session")
        assert first_poll["agentic_completed"] is True
        second_poll = _poll_agentic_jobs("consume-session")
        assert second_poll.get("status") == "no_jobs"


@pytest.mark.unit
class TestFailurePath5RejectDuringActiveJob:
    def test_active_job_blocks_new_dispatch(self) -> None:
        job = AgenticJob(
            job_id="active-1", session_id="active-session", prompt="Long running"
        )
        job.status = AgenticJobStatus.RUNNING
        with _agentic_jobs_lock:
            _agentic_jobs["active-1"] = job
        with (
            patch.object(
                _mod_daemon,
                "orchestrate_delegation",
                return_value={
                    "delegated": False,
                    "agentic": True,
                    "agentic_prompt": "New task",
                    "agentic_system_prompt": "System.",
                    "agentic_endpoint_url": "http://localhost:8000",
                    "reason": "agentic_eligible",
                },
            ),
            patch.object(_mod_daemon, "_classify_with_cache", return_value=None),
        ):
            req = json.dumps(
                {
                    "prompt": "New task",
                    "correlation_id": "corr-2",
                    "session_id": "active-session",
                }
            ).encode()
            resp = json.loads(_handle_request(req))
        assert resp.get("error") == "active_job_exists"


@pytest.mark.unit
class TestFailurePath6ContextBudgetExhausted:
    def test_budget_exhausted_returns_partial(self) -> None:
        call_count = 0

        class LargeBackend:
            def chat_completion_sync(self, **kw: Any) -> FakeChatResult:
                nonlocal call_count
                call_count += 1
                return FakeChatResult(
                    content=None,
                    tool_calls=[
                        {
                            "id": f"call_{call_count}",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": json.dumps(
                                    {"path": str(Path(__file__).resolve())}
                                ),
                            },
                        }
                    ],
                )

        result = run_agentic_loop(
            prompt="Read everything",
            system_prompt="System",
            endpoint_url="http://localhost:8000",
            tools=ALL_TOOLS,
            dispatch_fn=dispatch_tool,
            max_iterations=100,
            timeout_s=30.0,
            backend=LargeBackend(),
            context_budget_bytes=2048,
        )
        assert result.status == AgenticStatus.BUDGET_EXHAUSTED
        assert result.total_message_bytes >= 2048
        assert "budget" in (result.error or "").lower()


@pytest.mark.unit
class TestFailurePath7EmptyBackendResponse:
    def test_empty_response_terminates(self) -> None:
        class EmptyBackend:
            def chat_completion_sync(self, **kw: Any) -> FakeChatResult:
                return FakeChatResult(content=None, tool_calls=[], error=None)

        result = run_agentic_loop(
            prompt="Test",
            system_prompt="System",
            endpoint_url="http://localhost:8000",
            tools=ALL_TOOLS,
            dispatch_fn=dispatch_tool,
            backend=EmptyBackend(),
        )
        assert result.status == AgenticStatus.SUCCESS
        assert result.content == ""
        assert result.iterations == 1
        assert result.tool_calls_count == 0
