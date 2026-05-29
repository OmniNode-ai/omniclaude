# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Delegation dispatch handler (DEPRECATED).

.. deprecated::
    This module is superseded by ``omnimarket.nodes.node_delegate_skill_orchestrator``
    which uses bifrost config-driven routing (``bifrost_delegation.yaml`` +
    ``~/.omninode/delegation/bifrost_overrides.yaml``).

    The ``/onex:delegate`` skill dispatches to the omnimarket node, NOT this handler.
    This module remains wired in the omniclaude ``contract.yaml`` for backwards
    compatibility with the cross-CLI dispatch path (``handle_cross_cli_dispatch``).

Legacy backend selection fallback chain (hardcoded, not config-driven):
    1. OpenRouter GLM-4.7-Flash (if API key configured)
    2. Local vLLM Qwen coder (fallback)
    3. Gemini CLI (if installed, <60s)
    4. Codex CLI (if installed, <120s)
    5. GLM/Z.AI (if API key set, cloud fallback)
    6. Fail -- emit delegation-failed event

Related:
    - OMN-7109: Implement delegation orchestrator dispatch handler
    - OMN-7103: Node-Based LLM Delegation Workflow
    - Replacement: omnimarket/nodes/node_delegate_skill_orchestrator
"""

from __future__ import annotations

import logging
import shutil
import warnings
from dataclasses import dataclass

from omniclaude.config.model_local_llm_config import (
    LlmEndpointConfig,
    LlmEndpointPurpose,
    LocalLlmEndpointRegistry,
)
from omniclaude.lib.task_classifier import TaskClassifier
from omniclaude.nodes.node_delegation_orchestrator.models.model_cross_cli_invocation_result import (
    ModelCrossCLIInvocationResult,
)
from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_command import (
    ModelDelegationCommand,
)
from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_result import (
    ModelDelegationDispatchResult,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DelegationRoute:
    """Selected backend route for a delegation request."""

    backend: str  # "openrouter" | "local_vllm" | "gemini_cli" | "codex_cli" | "glm"
    base_url: str
    model: str
    api_key: str | None = None
    timeout: int = 30


def _route_from_endpoint(
    *,
    backend: str,
    endpoint: LlmEndpointConfig,
) -> DelegationRoute:
    """Convert a typed endpoint config into a delegation route."""
    timeout_seconds = max(1, (endpoint.max_latency_ms + 999) // 1000)
    return DelegationRoute(
        backend=backend,
        base_url=str(endpoint.url).rstrip("/"),
        model=endpoint.model_name,
        api_key=endpoint.api_key,
        timeout=timeout_seconds,
    )


def select_backend(
    registry: LocalLlmEndpointRegistry | None = None,
) -> DelegationRoute | None:
    """Select the best available LLM backend via fallback chain.

    .. deprecated::
        Use ``omnimarket.nodes.node_delegate_skill_orchestrator`` with bifrost
        config-driven routing instead. This function uses a hardcoded fallback
        chain that does not respect ``bifrost_delegation.yaml`` or the user
        overlay at ``~/.omninode/delegation/bifrost_overrides.yaml``.

    Args:
        registry: Optional typed endpoint registry, injected by tests.

    Returns:
        DelegationRoute if a backend is available, None otherwise.
    """
    warnings.warn(
        "select_backend() is deprecated. Use omnimarket "
        "node_delegate_skill_orchestrator with bifrost config routing.",
        DeprecationWarning,
        stacklevel=2,
    )
    endpoint_registry = registry or LocalLlmEndpointRegistry()

    # 1. Hosted OpenRouter code generation. It is only registered when
    # OPENROUTER_API_KEY is configured; missing credentials fall through to local.
    openrouter = endpoint_registry.get_endpoint(LlmEndpointPurpose.OPENROUTER)
    if openrouter is not None and openrouter.api_key:
        return _route_from_endpoint(backend="openrouter", endpoint=openrouter)

    # 2. Local vLLM fallback. Prefer the dedicated coder model, then the
    # mid-tier routing model, then the best configured reasoning endpoint.
    for purpose in (
        LlmEndpointPurpose.CODE_ANALYSIS,
        LlmEndpointPurpose.ROUTING,
        LlmEndpointPurpose.REASONING,
    ):
        endpoint = endpoint_registry.get_endpoint(purpose)
        if endpoint is not None:
            return _route_from_endpoint(backend="local_vllm", endpoint=endpoint)

    # 3. Gemini CLI
    if shutil.which("gemini"):
        return DelegationRoute(
            backend="gemini_cli",
            base_url="cli://gemini",
            model="gemini-cli",
            timeout=60,
        )

    # 4. Codex CLI
    if shutil.which("codex"):
        return DelegationRoute(
            backend="codex_cli",
            base_url="cli://codex",
            model="codex-cli",
            timeout=120,
        )

    # 5. GLM/Z.AI direct cloud fallback.
    glm = endpoint_registry.get_endpoint(LlmEndpointPurpose.GLM)
    if glm is not None and glm.api_key:
        return _route_from_endpoint(backend="glm", endpoint=glm)

    return None


def handle_delegation_dispatch(
    command: ModelDelegationCommand,
) -> ModelDelegationDispatchResult:
    """Classify prompt, select backend, return routing decision.

    .. deprecated::
        Use ``omnimarket.nodes.node_delegate_skill_orchestrator`` instead.
        This handler uses the hardcoded ``select_backend()`` fallback chain
        rather than bifrost config-driven routing.

    Args:
        command: Typed delegation command from the hook or Kafka consumer.

    Returns:
        Typed dispatch result with routing decision or failure reason.
    """
    warnings.warn(
        "handle_delegation_dispatch() is deprecated. Use omnimarket "
        "node_delegate_skill_orchestrator with bifrost config routing.",
        DeprecationWarning,
        stacklevel=2,
    )
    if not command.prompt:
        return ModelDelegationDispatchResult(
            routed=False,
            reason="empty_prompt",
            correlation_id=command.correlation_id,
        )

    # Classify
    classifier = TaskClassifier()
    score = classifier.is_delegatable(command.prompt)

    if not score.delegatable:
        reason = score.reasons[0] if score.reasons else "unknown"
        return ModelDelegationDispatchResult(
            routed=False,
            reason=f"not_delegatable: {reason}",
            intent=score.delegate_to_model,
            confidence=score.confidence,
            correlation_id=command.correlation_id,
        )

    # Select backend
    route = select_backend()
    if route is None:
        return ModelDelegationDispatchResult(
            routed=False,
            reason="no_backend_available",
            intent=score.delegate_to_model,
            confidence=score.confidence,
            correlation_id=command.correlation_id,
        )

    logger.info(
        "Delegation dispatch: intent=%s confidence=%.2f backend=%s model=%s (correlation_id=%s)",
        score.delegate_to_model,
        score.confidence,
        route.backend,
        route.model,
        command.correlation_id,
    )

    return ModelDelegationDispatchResult(
        routed=True,
        backend=route.backend,
        base_url=route.base_url,
        model=route.model,
        api_key=route.api_key,
        timeout=route.timeout,
        intent=score.delegate_to_model,
        confidence=score.confidence,
        estimated_savings_usd=score.estimated_savings_usd,
        prompt=command.prompt,
        correlation_id=command.correlation_id,
        session_id=command.session_id,
    )


def handle_cross_cli_dispatch(
    command: ModelDelegationCommand,
) -> ModelCrossCLIInvocationResult:
    """Dispatch to claude/opencode/codex CLI via HandlerCrossCLIInvoker.

    Only valid when command.recipient is claude, opencode, or codex.
    For recipient='auto', use handle_delegation_dispatch() instead.
    """
    if command.recipient == "auto":
        raise ValueError(
            "handle_cross_cli_dispatch requires explicit recipient; got recipient='auto'. "
            "Use handle_delegation_dispatch() for auto-routing."
        )
    from omniclaude.nodes.node_delegation_orchestrator.handlers.handler_cross_cli_invoker import (
        HandlerCrossCLIInvoker,
    )

    invoker = HandlerCrossCLIInvoker()
    return invoker.invoke(command)


__all__ = [
    "DelegationRoute",
    "handle_cross_cli_dispatch",
    "handle_delegation_dispatch",
    "select_backend",
]
