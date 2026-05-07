# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for the in-process delegation runner (OMN-10610)."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from omniclaude.delegation.inprocess_runner import (
    DelegationRunnerError,
    InProcessDelegationRunner,
    _call_llm,
)


@pytest.mark.unit
class TestInProcessDelegationRunnerInstantiation:
    """InProcessDelegationRunner can be instantiated without external dependencies."""

    def test_runner_instantiates(self) -> None:
        runner = InProcessDelegationRunner()
        assert isinstance(runner, InProcessDelegationRunner)


@pytest.mark.unit
class TestInProcessDelegationRunnerRoutingAndGate:
    """Tests for the routing + quality-gate flow with a mocked LLM call."""

    def _make_routing_decision(
        self,
        correlation_id: uuid.UUID,
        endpoint_url: str = "http://localhost:8000",
        model: str = "test-model",
    ) -> MagicMock:
        decision = MagicMock()
        decision.correlation_id = correlation_id
        decision.endpoint_url = endpoint_url
        decision.selected_model = model
        decision.system_prompt = "You are a test assistant."
        return decision

    def _make_llm_response(self, content: str) -> dict[str, Any]:
        return {
            "model": "test-model",
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 50,
                "total_tokens": 60,
            },
        }

    @patch(
        "omniclaude.delegation.inprocess_runner.routing_delta",
    )
    @patch(
        "omniclaude.delegation.inprocess_runner._call_llm",
    )
    def test_run_returns_result_on_quality_pass(
        self,
        mock_call_llm: MagicMock,
        mock_routing_delta: MagicMock,
    ) -> None:
        """Successful pipeline returns a quality-passing ModelDelegationResult."""
        corr_id = uuid.uuid4()
        mock_routing_delta.return_value = self._make_routing_decision(corr_id)

        # Response long enough to pass quality gate for "research" (≥60 chars)
        long_content = "This is a detailed research response. " * 5
        mock_call_llm.return_value = (
            long_content,
            {"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60},
            120,
            "test-model",
        )

        runner = InProcessDelegationRunner()
        result = runner.run(
            task_type="research", prompt="Explain the code architecture."
        )

        assert result.quality_passed is True
        assert result.content == long_content
        assert result.task_type == "research"
        assert result.model_used == "test-model"
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 50
        assert result.total_tokens == 60
        assert result.failure_reason == ""

    @patch(
        "omniclaude.delegation.inprocess_runner.routing_delta",
    )
    @patch(
        "omniclaude.delegation.inprocess_runner._call_llm",
    )
    def test_run_returns_result_on_quality_fail(
        self,
        mock_call_llm: MagicMock,
        mock_routing_delta: MagicMock,
    ) -> None:
        """Pipeline returns quality_passed=False when output contains a refusal phrase."""
        corr_id = uuid.uuid4()
        mock_routing_delta.return_value = self._make_routing_decision(corr_id)

        # Refusal phrase in first 200 chars forces no_refusal=0.0, so score < 0.6
        refusal_content = "I cannot assist with that request. " + "x" * 100
        mock_call_llm.return_value = (
            refusal_content,
            {"prompt_tokens": 5, "completion_tokens": 20, "total_tokens": 25},
            50,
            "test-model",
        )

        runner = InProcessDelegationRunner()
        result = runner.run(task_type="research", prompt="Quick question.")

        assert result.quality_passed is False
        assert result.failure_reason != ""

    @patch(
        "omniclaude.delegation.inprocess_runner.routing_delta",
    )
    def test_run_raises_on_routing_failure(
        self,
        mock_routing_delta: MagicMock,
    ) -> None:
        """DelegationRunnerError is raised when no endpoint is configured."""
        mock_routing_delta.side_effect = Exception(
            "No tier has a configured endpoint for task_type='test'"
        )

        runner = InProcessDelegationRunner()
        with pytest.raises(DelegationRunnerError, match="Routing failed"):
            runner.run(task_type="test", prompt="Write a test.")

    @patch(
        "omniclaude.delegation.inprocess_runner.routing_delta",
    )
    @patch(
        "omniclaude.delegation.inprocess_runner._call_llm",
    )
    def test_tool_input_embedded_in_prompt(
        self,
        mock_call_llm: MagicMock,
        mock_routing_delta: MagicMock,
    ) -> None:
        """tool_input dict is serialized and appended to the prompt."""
        corr_id = uuid.uuid4()
        mock_routing_delta.return_value = self._make_routing_decision(corr_id)

        long_content = "Research result: " + "x" * 80
        mock_call_llm.return_value = (
            long_content,
            {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50},
            80,
            "test-model",
        )

        runner = InProcessDelegationRunner()
        runner.run(
            task_type="research",
            prompt="Analyze this.",
            tool_input={"tool": "Read", "file_path": "/src/foo.py"},
        )

        # The request that routing_delta received should have tool JSON in prompt
        routing_call_args = mock_routing_delta.call_args[0][0]
        assert "Tool input context" in routing_call_args.prompt
        assert '"tool": "Read"' in routing_call_args.prompt

    @patch(
        "omniclaude.delegation.inprocess_runner.routing_delta",
    )
    @patch(
        "omniclaude.delegation.inprocess_runner._call_llm",
    )
    def test_source_metadata_propagated(
        self,
        mock_call_llm: MagicMock,
        mock_routing_delta: MagicMock,
    ) -> None:
        """source_session_id and source_file_path are forwarded to the request."""
        corr_id = uuid.uuid4()
        mock_routing_delta.return_value = self._make_routing_decision(corr_id)

        long_content = "Document: " + "y" * 100
        mock_call_llm.return_value = (
            long_content,
            {"prompt_tokens": 15, "completion_tokens": 25, "total_tokens": 40},
            90,
            "test-model",
        )

        runner = InProcessDelegationRunner()
        runner.run(
            task_type="document",
            prompt="Document this function.",
            source_session_id="sess-abc123",
            source_file_path="/src/module.py",
        )

        routing_call_args = mock_routing_delta.call_args[0][0]
        assert routing_call_args.source_session_id == "sess-abc123"
        assert routing_call_args.source_file_path == "/src/module.py"

    @patch(
        "omniclaude.delegation.inprocess_runner.routing_delta",
    )
    @patch(
        "omniclaude.delegation.inprocess_runner._call_llm",
    )
    @patch(
        "omniclaude.delegation.inprocess_runner.quality_gate_delta",
    )
    def test_run_wraps_quality_gate_failure(
        self,
        mock_quality_gate_delta: MagicMock,
        mock_call_llm: MagicMock,
        mock_routing_delta: MagicMock,
    ) -> None:
        """Quality gate reducer exceptions stay inside DelegationRunnerError."""
        corr_id = uuid.uuid4()
        mock_routing_delta.return_value = self._make_routing_decision(corr_id)
        mock_call_llm.return_value = (
            "Research result: " + "x" * 100,
            {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            40,
            "test-model",
        )
        mock_quality_gate_delta.side_effect = RuntimeError("gate unavailable")

        runner = InProcessDelegationRunner()
        with pytest.raises(DelegationRunnerError, match="Quality gate failed"):
            runner.run(task_type="research", prompt="Analyze this.")


@pytest.mark.unit
class TestCallLlmErrorHandling:
    """Tests for LLM response parsing error normalization."""

    def _mock_response(
        self, json_result: Any = None, json_error: Exception | None = None
    ) -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        if json_error is not None:
            response.json.side_effect = json_error
        else:
            response.json.return_value = json_result
        return response

    @patch("omniclaude.delegation.inprocess_runner.httpx.Client")
    def test_call_llm_wraps_invalid_json(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """Malformed JSON responses raise DelegationRunnerError."""
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = self._mock_response(
            json_error=ValueError("bad json")
        )

        with pytest.raises(DelegationRunnerError, match="invalid JSON"):
            _call_llm(
                endpoint_url="http://localhost:8000",
                model="test-model",
                system_prompt="system",
                prompt="prompt",
                max_tokens=100,
                temperature=0.3,
                correlation_id=uuid.uuid4(),
            )

    @patch("omniclaude.delegation.inprocess_runner.httpx.Client")
    def test_call_llm_rejects_non_dict_json(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """Non-object JSON responses raise DelegationRunnerError."""
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = self._mock_response(
            json_result=["not", "a", "dict"]
        )

        with pytest.raises(DelegationRunnerError, match="unexpected JSON type list"):
            _call_llm(
                endpoint_url="http://localhost:8000",
                model="test-model",
                system_prompt="system",
                prompt="prompt",
                max_tokens=100,
                temperature=0.3,
                correlation_id=uuid.uuid4(),
            )
