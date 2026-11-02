# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for endpoint configuration and resilience in NodeTransitionSelectorEffect.

Tests added as part of the Crenshaw architecture review fixes:
- Task 1: Fail-fast when LLM_CODER_FAST_URL is unset
- Task 10: Health probing
- Task 11: Actionable error messages
- Task 12: Prompt building purity
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from omniclaude.nodes.node_transition_selector_effect.models.model_contract_state import (
    ModelContractState,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_goal_condition import (
    ModelGoalCondition,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_navigation_context import (
    ModelNavigationContext,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_transition_selector_request import (
    ModelTransitionSelectorRequest,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_transition_selector_result import (
    SelectionErrorKind,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_typed_action import (
    ActionCategory,
    ModelTypedAction,
)
from omniclaude.nodes.node_transition_selector_effect.node import (
    NodeTransitionSelectorEffect,
    _resolve_endpoint,
    _resolve_model_id,
)

pytestmark = pytest.mark.unit

_CONTRACT_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "omniclaude"
    / "nodes"
    / "node_transition_selector_effect"
    / "contract.yaml"
)


# =============================================================================
# Fixtures (matching existing test_node_logic.py patterns)
# =============================================================================


def _make_request() -> ModelTransitionSelectorRequest:
    """Create a minimal valid request for testing."""
    return ModelTransitionSelectorRequest(
        current_state=ModelContractState(
            state_id="state-alpha",
            node_type="Effect",
            fields={"status": "pending"},
        ),
        goal=ModelGoalCondition(
            goal_id="goal-test",
            summary="Complete task",
            target_state_id="state-beta",
        ),
        action_set=(
            ModelTypedAction(
                action_id="action-001",
                action_type="transition_to_effect",
                category=ActionCategory.STATE_TRANSITION,
                description="Build the code",
                target_state_id="state-002",
            ),
            ModelTypedAction(
                action_id="action-002",
                action_type="transition_to_effect",
                category=ActionCategory.STATE_TRANSITION,
                description="Run tests",
                target_state_id="state-003",
            ),
        ),
        context=ModelNavigationContext(
            session_id=uuid4(),
            step_number=1,
            goal_summary="Reach compute state",
        ),
        correlation_id=uuid4(),
    )


def _make_node() -> NodeTransitionSelectorEffect:
    """Create a NodeTransitionSelectorEffect without full container init."""
    container = MagicMock()
    node = NodeTransitionSelectorEffect.__new__(NodeTransitionSelectorEffect)
    node._container = container  # type: ignore[attr-defined]
    return node


# =============================================================================
# Task 1: Fail-fast endpoint configuration
# =============================================================================


class TestResolveEndpoint:
    """Tests for _resolve_endpoint() fail-fast behavior."""

    def test_endpoint_not_configured_raises_configuration_error(self) -> None:
        """Node must fail fast when LLM_CODER_FAST_URL is not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("LLM_CODER_FAST_URL", None)
            with pytest.raises(
                RuntimeError,
                match="LLM_CODER_FAST_URL",
            ):
                _resolve_endpoint()


class TestContractRoutingBoundary:
    """Contract declares required config keys, not served model defaults."""

    def test_contract_has_no_served_model_default(self) -> None:
        text = _CONTRACT_PATH.read_text(encoding="utf-8")

        assert "qwen3-14b" not in text
        assert "model: " not in text
        assert "OMNICLAUDE_TRANSITION_SELECTOR_MODEL_NAME" in text
        assert "no_contract_served_model_defaults: true" in text


class TestResolveModelId:
    """Tests for served model configuration fail-fast behavior."""

    def test_model_id_not_configured_raises_configuration_error(self) -> None:
        """Node must fail fast when served model config is not set."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(
                RuntimeError,
                match="OMNICLAUDE_TRANSITION_SELECTOR_MODEL_NAME",
            ):
                _resolve_model_id()

    def test_model_id_configured_returns_value(self) -> None:
        """_resolve_model_id returns the configured served model ID."""
        with patch.dict(
            os.environ,
            {"OMNICLAUDE_TRANSITION_SELECTOR_MODEL_NAME": "configured-selector"},
        ):
            assert _resolve_model_id() == "configured-selector"

    def test_model_id_empty_string_raises(self) -> None:
        """Empty string is treated as unset."""
        with patch.dict(os.environ, {"OMNICLAUDE_TRANSITION_SELECTOR_MODEL_NAME": ""}):
            with pytest.raises(
                RuntimeError,
                match="OMNICLAUDE_TRANSITION_SELECTOR_MODEL_NAME",
            ):
                _resolve_model_id()

    def test_endpoint_configured_returns_url(self) -> None:
        """_resolve_endpoint returns the configured URL."""
        with patch.dict(os.environ, {"LLM_CODER_FAST_URL": "http://localhost:8001"}):
            assert _resolve_endpoint() == "http://localhost:8001"

    def test_endpoint_empty_string_raises(self) -> None:
        """Empty string is treated as unset."""
        with patch.dict(os.environ, {"LLM_CODER_FAST_URL": ""}):
            with pytest.raises(RuntimeError, match="LLM_CODER_FAST_URL"):
                _resolve_endpoint()


class TestSelectEndpointError:
    """Tests for select() structured error on misconfiguration."""

    @pytest.mark.asyncio
    async def test_select_returns_structured_error_when_endpoint_unconfigured(
        self,
    ) -> None:
        """select() must surface config failure as typed result, not raw exception."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("LLM_CODER_FAST_URL", None)
            node = _make_node()
            request = _make_request()
            result = await node.select(request)
            assert not result.success
            assert result.error_kind == SelectionErrorKind.MODEL_UNAVAILABLE
            assert "LLM_CODER_FAST_URL" in (result.error_detail or "")


# =============================================================================
# Task 10: Health probing
# =============================================================================


class TestProbeEndpoint:
    """Tests for _probe_endpoint() health checking."""

    @pytest.mark.asyncio
    async def test_probe_endpoint_returns_false_when_unreachable(self) -> None:
        """Health probe returns False when endpoint is unreachable."""
        with patch.dict("os.environ", {"LLM_CODER_FAST_URL": "http://localhost:1"}):
            node = _make_node()
            result = await node._probe_endpoint(timeout=0.5)
            assert result is False

    @pytest.mark.asyncio
    async def test_probe_endpoint_returns_true_when_healthy(self) -> None:
        """Health probe returns True when endpoint responds."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.dict("os.environ", {"LLM_CODER_FAST_URL": "http://localhost:8001"}):
            with patch("httpx.AsyncClient.get", return_value=mock_response):
                node = _make_node()
                result = await node._probe_endpoint()
                assert result is True


# =============================================================================
# Task 11: Actionable error messages
# =============================================================================


class TestActionableErrors:
    """Tests for actionable error detail in MODEL_UNAVAILABLE."""

    @pytest.mark.asyncio
    async def test_select_returns_actionable_error_when_endpoint_unreachable(
        self,
    ) -> None:
        """MODEL_UNAVAILABLE error must include endpoint URL and remediation hint."""
        with patch.dict("os.environ", {"LLM_CODER_FAST_URL": "http://test-host:8001"}):
            node = _make_node()
            # Mock _call_model to raise a network error
            node._call_model = AsyncMock(  # type: ignore[method-assign]
                side_effect=httpx.NetworkError("Connection refused")
            )
            request = _make_request()
            result = await node.select(request)
            assert result.error_kind == SelectionErrorKind.MODEL_UNAVAILABLE
            assert "LLM_CODER_FAST_URL" in (result.error_detail or "")
            assert "test-host:8001" in (result.error_detail or "")
            assert "curl" in (result.error_detail or "").lower()


# =============================================================================
# Task 12: Prompt building purity
# =============================================================================


class TestBuildPromptPurity:
    """Tests verifying _build_prompt is a pure function with no network deps."""

    @pytest.mark.unit
    def test_build_prompt_is_pure_no_network(self) -> None:
        """Prompt building must work without any network access or env vars."""
        request = _make_request()
        # Should succeed even with no endpoint configured
        with patch.dict("os.environ", {}, clear=True):
            node = _make_node()
            prompt = node._build_prompt(request)
            assert "Build the code" in prompt
            assert "Run tests" in prompt


class TestContractRuntimePolicy:
    """Contract changes and injected policy reach the actual I/O boundaries."""

    def test_policy_reads_contract_and_refuses_missing_values(
        self, tmp_path: Path
    ) -> None:
        import yaml

        from omniclaude.nodes.node_transition_selector_effect.models.model_selector_policy import (
            ModelSelectorPolicy,
        )

        contract = yaml.safe_load(_CONTRACT_PATH.read_text())
        policy = ModelSelectorPolicy.from_contract(_CONTRACT_PATH)
        assert policy.selection_timeout_seconds == 10
        assert policy.http_timeout_seconds == 12
        assert policy.probe_timeout_seconds == 2
        assert policy.max_retries == 1
        assert policy.retry_delay_seconds == 0.5
        contract["error_handling"]["selection_timeout_seconds"] = 0.025
        changed = tmp_path / "contract.yaml"
        changed.write_text(yaml.safe_dump(contract))
        assert (
            ModelSelectorPolicy.from_contract(changed).selection_timeout_seconds
            == 0.025
        )
        del contract["error_handling"]["selection_timeout_seconds"]
        changed.write_text(yaml.safe_dump(contract))
        with pytest.raises((ValueError, KeyError)):
            ModelSelectorPolicy.from_contract(changed)

    @pytest.mark.asyncio
    async def test_injected_policy_controls_http_probe_and_retry(self) -> None:
        from omniclaude.nodes.node_transition_selector_effect.models.model_selector_policy import (
            ModelSelectorPolicy,
        )

        node = _make_node()
        node.policy = ModelSelectorPolicy(
            selection_timeout_seconds=0.025,
            http_timeout_margin_seconds=0.01,
            probe_timeout_seconds=0.015,
            max_retries=2,
            initial_delay_ms=3,
        )
        response = MagicMock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": "answer"}}]}
        client = AsyncMock()
        client.get.return_value = response
        client.post.return_value = response
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=client)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.dict(
                os.environ,
                {
                    "LLM_CODER_FAST_URL": "http://test-endpoint:8001",
                    "OMNICLAUDE_TRANSITION_SELECTOR_MODEL_NAME": "test-model",
                },
            ),
            patch(
                "omniclaude.nodes.node_transition_selector_effect.node.httpx.AsyncClient",
                factory,
            ),
        ):
            assert await node._call_model_once("prompt") == "answer"
            factory.assert_called_with(timeout=0.035)
            assert await node._probe_endpoint()
            assert client.get.call_args.kwargs["timeout"] == 0.015
            assert await node._probe_endpoint(timeout=0.02)
            assert client.get.call_args.kwargs["timeout"] == 0.02
        with (
            patch.object(
                node,
                "_call_model_once",
                AsyncMock(side_effect=[OSError("first"), OSError("second"), "answer"]),
            ) as call,
            patch(
                "omniclaude.nodes.node_transition_selector_effect.node.asyncio.sleep",
                AsyncMock(),
            ) as sleep,
        ):
            assert await node._call_model("prompt") == "answer"
            assert call.await_count == 3
            assert sleep.await_count == 2
            sleep.assert_awaited_with(0.003)

    @pytest.mark.asyncio
    async def test_injected_deadline_returns_structured_timeout(self) -> None:
        import asyncio

        from omniclaude.nodes.node_transition_selector_effect.models.model_selector_policy import (
            ModelSelectorPolicy,
        )

        node = _make_node()
        node.policy = ModelSelectorPolicy.from_contract(_CONTRACT_PATH).model_copy(
            update={"selection_timeout_seconds": 0.005}
        )

        async def slow_call(prompt: str) -> str:
            await asyncio.sleep(10)
            return "unreachable"

        with (
            patch.dict(os.environ, {"LLM_CODER_FAST_URL": "http://test-endpoint:8001"}),
            patch.object(node, "_call_model", slow_call),
        ):
            result = await node.select(_make_request())
        assert result.error_kind == SelectionErrorKind.SELECTION_TIMEOUT
        assert "0.005s" in result.error_detail

    def test_constructor_keeps_injected_policy(self) -> None:
        from omnibase_core.models.container.model_onex_container import (
            ModelONEXContainer,
        )

        from omniclaude.nodes.node_transition_selector_effect.models.model_selector_policy import (
            ModelSelectorPolicy,
        )

        policy = ModelSelectorPolicy.from_contract(_CONTRACT_PATH)
        node = NodeTransitionSelectorEffect(ModelONEXContainer(), policy=policy)
        assert node.policy is policy

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("selection_timeout_seconds", 0),
            ("selection_timeout_seconds", float("inf")),
            ("http_timeout_margin_seconds", -1),
            ("probe_timeout_seconds", 0),
            ("initial_delay_ms", -1),
            ("max_retries", -1),
            ("max_retries", 1.5),
        ],
    )
    def test_policy_refuses_invalid_values(self, field: str, value: float) -> None:
        from pydantic import ValidationError

        from omniclaude.nodes.node_transition_selector_effect.models.model_selector_policy import (
            ModelSelectorPolicy,
        )

        values = ModelSelectorPolicy.from_contract(_CONTRACT_PATH).model_dump()
        values[field] = value
        with pytest.raises(ValidationError):
            ModelSelectorPolicy.model_validate(values)

    @pytest.mark.asyncio
    async def test_node_selects_over_live_http_with_injected_policy(self) -> None:
        import asyncio
        import json

        from omniclaude.nodes.node_transition_selector_effect.models.model_selector_policy import (
            ModelSelectorPolicy,
        )

        received = []

        async def respond(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            headers = await reader.readuntil(b"\r\n\r\n")
            length = next(
                int(line.split(b":", 1)[1])
                for line in headers.split(b"\r\n")
                if line.lower().startswith(b"content-length:")
            )
            received.append(json.loads(await reader.readexactly(length)))
            body = json.dumps(
                {"choices": [{"message": {"content": '{"selected": 1}'}}]}
            ).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + body
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(respond, "127.0.0.1", 0)
        async with server:
            port = server.sockets[0].getsockname()[1]
            from omnibase_core.models.container.model_onex_container import (
                ModelONEXContainer,
            )

            node = NodeTransitionSelectorEffect(
                ModelONEXContainer(),
                policy=ModelSelectorPolicy.from_contract(_CONTRACT_PATH),
            )
            with patch.dict(
                os.environ,
                {
                    "LLM_CODER_FAST_URL": f"http://127.0.0.1:{port}",
                    "OMNICLAUDE_TRANSITION_SELECTOR_MODEL_NAME": "test-model",
                },
            ):
                result = await node.select(_make_request())
        assert result.success
        assert result.selected_action.action_id == "action-001"
        assert received[0]["model"] == "test-model"
