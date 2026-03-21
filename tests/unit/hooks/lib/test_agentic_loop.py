# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for agentic_loop.py (OMN-5724).

Coverage:
- Single-shot completion (no tool calls)
- Multi-turn tool-calling loop
- Max iterations termination
- Timeout termination
- LLM error handling
- Backend unavailable
- Malformed tool calls (graceful recovery)
- dispatch_fn exceptions
- Empty tool_calls list treated as final answer
"""

from __future__ import annotations

import importlib.util
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

# The hooks/lib modules are not installed packages — they're loaded at runtime.
# Use importlib to load by file path so we don't pollute sys.path with a 'lib'
# entry that would shadow tests/unit/lib/ during pytest collection.
_MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
    / "agentic_loop.py"
)
import sys

_spec = importlib.util.spec_from_file_location("agentic_loop", _MODULE_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["agentic_loop"] = _mod
_spec.loader.exec_module(_mod)

AgenticStatus = _mod.AgenticStatus
run_agentic_loop = _mod.run_agentic_loop

# Type alias matching the module's convention.
_JsonDict = dict[str, Any]


# ---------------------------------------------------------------------------
# Fake backend for testing
# ---------------------------------------------------------------------------


@dataclass
class FakeChatResult:
    """Mimics ChatCompletionResult from backend_vllm."""

    content: str | None = None
    tool_calls: list[_JsonDict] = field(default_factory=list)
    error: str | None = None


class FakeBackend:
    """Test double for VllmInferenceBackend.

    Accepts a sequence of FakeChatResult to return on successive calls
    to chat_completion_sync().
    """

    def __init__(self, responses: list[FakeChatResult]) -> None:
        self._responses = list(responses)
        self._call_count = 0
        self.calls: list[_JsonDict] = []

    def chat_completion_sync(self, **kwargs: Any) -> FakeChatResult:
        self.calls.append(kwargs)
        if self._call_count >= len(self._responses):
            return FakeChatResult(content="(exhausted responses)", error=None)
        result = self._responses[self._call_count]
        self._call_count += 1
        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_TOOLS: list[_JsonDict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }
]


def _make_tool_call(
    name: str = "read_file",
    args: str = '{"path": "/tmp/test.py"}',
    call_id: str = "call_0",
) -> _JsonDict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": args},
    }


def _noop_dispatch(tool_name: str, args_json: str) -> str:
    return f"result for {tool_name}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSingleShotCompletion:
    """LLM returns text with no tool calls -> loop exits immediately."""

    def test_returns_content_on_no_tool_calls(self) -> None:
        backend = FakeBackend([FakeChatResult(content="Here is my analysis.")])
        result = run_agentic_loop(
            prompt="Analyze the code",
            system_prompt="You are a researcher.",
            endpoint_url="http://localhost:8000",
            tools=_SAMPLE_TOOLS,
            dispatch_fn=_noop_dispatch,
            backend=backend,
        )
        assert result.status == AgenticStatus.SUCCESS
        assert result.content == "Here is my analysis."
        assert result.iterations == 1
        assert result.tool_calls_count == 0
        assert len(result.tool_names_used) == 0

    def test_empty_tool_calls_treated_as_final(self) -> None:
        backend = FakeBackend([FakeChatResult(content="Done.", tool_calls=[])])
        result = run_agentic_loop(
            prompt="Task",
            system_prompt="System",
            endpoint_url="http://localhost:8000",
            tools=_SAMPLE_TOOLS,
            dispatch_fn=_noop_dispatch,
            backend=backend,
        )
        assert result.status == AgenticStatus.SUCCESS
        assert result.content == "Done."


@pytest.mark.unit
class TestMultiTurnToolCalling:
    """LLM makes tool calls, receives results, then produces final answer."""

    def test_two_iteration_loop(self) -> None:
        responses = [
            # Iteration 1: LLM requests read_file
            FakeChatResult(
                content=None,
                tool_calls=[_make_tool_call("read_file", '{"path": "/a.py"}', "c1")],
            ),
            # Iteration 2: LLM produces final answer
            FakeChatResult(content="The file contains a class definition."),
        ]
        backend = FakeBackend(responses)

        result = run_agentic_loop(
            prompt="What's in /a.py?",
            system_prompt="Research assistant.",
            endpoint_url="http://localhost:8000",
            tools=_SAMPLE_TOOLS,
            dispatch_fn=_noop_dispatch,
            backend=backend,
        )

        assert result.status == AgenticStatus.SUCCESS
        assert result.iterations == 2
        assert result.tool_calls_count == 1
        assert "read_file" in result.tool_names_used
        assert result.content == "The file contains a class definition."

    def test_multiple_tool_calls_in_single_response(self) -> None:
        responses = [
            FakeChatResult(
                content=None,
                tool_calls=[
                    _make_tool_call("read_file", '{"path": "/a.py"}', "c1"),
                    _make_tool_call("read_file", '{"path": "/b.py"}', "c2"),
                ],
            ),
            FakeChatResult(content="Both files analyzed."),
        ]
        backend = FakeBackend(responses)

        result = run_agentic_loop(
            prompt="Compare files",
            system_prompt="System",
            endpoint_url="http://localhost:8000",
            tools=_SAMPLE_TOOLS,
            dispatch_fn=_noop_dispatch,
            backend=backend,
        )

        assert result.status == AgenticStatus.SUCCESS
        assert result.tool_calls_count == 2
        assert result.iterations == 2

    def test_tool_names_tracked(self) -> None:
        responses = [
            FakeChatResult(
                content=None,
                tool_calls=[
                    _make_tool_call("read_file", '{"path": "/a.py"}', "c1"),
                    _make_tool_call("search_content", '{"pattern": "class"}', "c2"),
                ],
            ),
            FakeChatResult(content="Found it."),
        ]
        backend = FakeBackend(responses)

        result = run_agentic_loop(
            prompt="Find class",
            system_prompt="System",
            endpoint_url="http://localhost:8000",
            tools=_SAMPLE_TOOLS,
            dispatch_fn=_noop_dispatch,
            backend=backend,
        )

        assert result.tool_names_used == {"read_file", "search_content"}


@pytest.mark.unit
class TestMaxIterations:
    """Loop terminates when max_iterations is reached."""

    def test_max_iterations_reached(self) -> None:
        # Every response has tool calls -> never produces final answer
        responses = [
            FakeChatResult(
                content=None,
                tool_calls=[_make_tool_call("read_file", '{"path": "/x.py"}', f"c{i}")],
            )
            for i in range(5)
        ]
        backend = FakeBackend(responses)

        result = run_agentic_loop(
            prompt="Task",
            system_prompt="System",
            endpoint_url="http://localhost:8000",
            tools=_SAMPLE_TOOLS,
            dispatch_fn=_noop_dispatch,
            max_iterations=3,
            backend=backend,
        )

        assert result.status == AgenticStatus.MAX_ITERATIONS
        assert result.iterations == 3
        assert result.tool_calls_count == 3


@pytest.mark.unit
class TestTimeout:
    """Loop terminates when wall-clock timeout is exceeded."""

    def test_timeout_triggers(self) -> None:
        call_count = 0

        class SlowBackend:
            def chat_completion_sync(self, **kwargs: Any) -> FakeChatResult:
                nonlocal call_count
                call_count += 1
                # Simulate slow response by advancing time
                time.sleep(0.05)
                return FakeChatResult(
                    content=None,
                    tool_calls=[_make_tool_call("read_file", "{}", f"c{call_count}")],
                )

        result = run_agentic_loop(
            prompt="Task",
            system_prompt="System",
            endpoint_url="http://localhost:8000",
            tools=_SAMPLE_TOOLS,
            dispatch_fn=_noop_dispatch,
            timeout_s=0.1,
            max_iterations=100,
            backend=SlowBackend(),
        )

        assert result.status == AgenticStatus.TIMEOUT
        assert result.iterations > 0


@pytest.mark.unit
class TestLlmErrors:
    """Loop terminates on LLM errors."""

    def test_first_call_error(self) -> None:
        backend = FakeBackend([FakeChatResult(error="TIMEOUT")])
        result = run_agentic_loop(
            prompt="Task",
            system_prompt="System",
            endpoint_url="http://localhost:8000",
            tools=_SAMPLE_TOOLS,
            dispatch_fn=_noop_dispatch,
            backend=backend,
        )
        assert result.status == AgenticStatus.LLM_ERROR
        assert result.error == "TIMEOUT"
        assert result.iterations == 1

    def test_error_after_tool_call(self) -> None:
        responses = [
            FakeChatResult(
                content=None,
                tool_calls=[_make_tool_call()],
            ),
            FakeChatResult(error="BACKEND_UNAVAILABLE"),
        ]
        backend = FakeBackend(responses)

        result = run_agentic_loop(
            prompt="Task",
            system_prompt="System",
            endpoint_url="http://localhost:8000",
            tools=_SAMPLE_TOOLS,
            dispatch_fn=_noop_dispatch,
            backend=backend,
        )

        assert result.status == AgenticStatus.LLM_ERROR
        assert result.iterations == 2
        assert result.tool_calls_count == 1


@pytest.mark.unit
class TestNoBackend:
    """Loop returns NO_BACKEND when backend is unavailable."""

    def test_no_backend_returns_error(self) -> None:
        """When _get_backend() returns None, the loop should return NO_BACKEND."""
        from unittest.mock import patch

        with patch.object(_mod, "_get_backend", return_value=None):
            result = run_agentic_loop(
                prompt="Task",
                system_prompt="System",
                endpoint_url="http://localhost:8000",
                tools=_SAMPLE_TOOLS,
                dispatch_fn=_noop_dispatch,
                backend=None,
            )
        assert result.status == AgenticStatus.NO_BACKEND
        assert "not available" in (result.error or "")


@pytest.mark.unit
class TestDispatchErrors:
    """Dispatch function errors are caught and sent back to the LLM."""

    def test_dispatch_exception_returned_as_error_message(self) -> None:
        def failing_dispatch(name: str, args: str) -> str:
            raise RuntimeError("Permission denied")

        responses = [
            FakeChatResult(
                content=None,
                tool_calls=[_make_tool_call()],
            ),
            # After getting the error message, LLM produces final answer
            FakeChatResult(content="I encountered an error reading the file."),
        ]
        backend = FakeBackend(responses)

        result = run_agentic_loop(
            prompt="Task",
            system_prompt="System",
            endpoint_url="http://localhost:8000",
            tools=_SAMPLE_TOOLS,
            dispatch_fn=failing_dispatch,
            backend=backend,
        )

        assert result.status == AgenticStatus.SUCCESS
        assert result.iterations == 2
        assert result.tool_calls_count == 1
        # Verify the error was sent back to the LLM as a tool message
        last_tool_msg = [
            m for m in backend.calls[1]["messages"] if m.get("role") == "tool"
        ]
        assert len(last_tool_msg) == 1
        assert "Permission denied" in last_tool_msg[0]["content"]


@pytest.mark.unit
class TestMessageBuilding:
    """Verify the messages list is correctly constructed."""

    def test_initial_messages_include_system_and_user(self) -> None:
        backend = FakeBackend([FakeChatResult(content="Done.")])
        run_agentic_loop(
            prompt="My prompt",
            system_prompt="System prompt",
            endpoint_url="http://localhost:8000",
            tools=_SAMPLE_TOOLS,
            dispatch_fn=_noop_dispatch,
            backend=backend,
        )
        messages = backend.calls[0]["messages"]
        assert messages[0] == {"role": "system", "content": "System prompt"}
        assert messages[1] == {"role": "user", "content": "My prompt"}

    def test_tool_results_appended_with_correct_ids(self) -> None:
        responses = [
            FakeChatResult(
                content=None,
                tool_calls=[_make_tool_call("read_file", '{"path": "/x"}', "call_abc")],
            ),
            FakeChatResult(content="Final."),
        ]
        backend = FakeBackend(responses)

        run_agentic_loop(
            prompt="Task",
            system_prompt="System",
            endpoint_url="http://localhost:8000",
            tools=_SAMPLE_TOOLS,
            dispatch_fn=_noop_dispatch,
            backend=backend,
        )

        # Second call should have the tool result in messages
        second_call_msgs = backend.calls[1]["messages"]
        tool_msgs = [m for m in second_call_msgs if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "call_abc"
        assert "result for read_file" in tool_msgs[0]["content"]

    def test_assistant_message_with_tool_calls_preserved(self) -> None:
        responses = [
            FakeChatResult(
                content="Let me check that.",
                tool_calls=[_make_tool_call()],
            ),
            FakeChatResult(content="Here's what I found."),
        ]
        backend = FakeBackend(responses)

        run_agentic_loop(
            prompt="Task",
            system_prompt="System",
            endpoint_url="http://localhost:8000",
            tools=_SAMPLE_TOOLS,
            dispatch_fn=_noop_dispatch,
            backend=backend,
        )

        second_call_msgs = backend.calls[1]["messages"]
        assistant_msgs = [m for m in second_call_msgs if m.get("role") == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0]["content"] == "Let me check that."
        assert "tool_calls" in assistant_msgs[0]


@pytest.mark.unit
class TestBackendCallParameters:
    """Verify correct parameters are passed to the backend."""

    def test_tools_and_tool_choice_passed(self) -> None:
        backend = FakeBackend([FakeChatResult(content="Done.")])
        run_agentic_loop(
            prompt="Task",
            system_prompt="System",
            endpoint_url="http://test:8000",
            tools=_SAMPLE_TOOLS,
            dispatch_fn=_noop_dispatch,
            backend=backend,
        )
        call = backend.calls[0]
        assert call["endpoint_url"] == "http://test:8000"
        assert call["tools"] == _SAMPLE_TOOLS
        assert call["tool_choice"] == "auto"
        assert call["temperature"] == 0.1

    def test_empty_tools_sends_none(self) -> None:
        backend = FakeBackend([FakeChatResult(content="Done.")])
        run_agentic_loop(
            prompt="Task",
            system_prompt="System",
            endpoint_url="http://test:8000",
            tools=[],
            dispatch_fn=_noop_dispatch,
            backend=backend,
        )
        call = backend.calls[0]
        assert call["tools"] is None
        assert call["tool_choice"] is None
