# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Delegation dispatch handler.

Classifies incoming prompts, selects the appropriate LLM backend, and
routes to the selected effect node. correlation_id-keyed, replay-safe.

Backend selection fallback chain:
    1. Local vLLM (if endpoint healthy, <3s response)
    2. Gemini CLI (if installed, <60s)
    3. Codex CLI (if installed, <120s)
    4. GLM/Z.AI (if API key set, cloud fallback)
    5. Fail — emit delegation-failed event

Related:
    - OMN-7109: Implement delegation orchestrator dispatch handler
    - OMN-7103: Node-Based LLM Delegation Workflow
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from typing import Any

from omniclaude.lib.task_classifier import TaskClassifier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DelegationRoute:
    """Selected backend route for a delegation request."""

    backend: str  # "local_vllm" | "gemini_cli" | "codex_cli" | "glm"
    base_url: str
    model: str
    api_key: str | None = None
    timeout: int = 30


# Backend selection priorities
_LOCAL_VLLM_ENDPOINTS = [
    ("LLM_CODER_FAST_URL", "LLM_CODER_FAST_MODEL_NAME", "Qwen/Qwen3-14B-AWQ"),
    ("LLM_CODER_URL", "LLM_CODER_MODEL_NAME", "Qwen3-Coder-30B-A3B-Instruct"),
    ("LLM_DEEPSEEK_R1_URL", "LLM_DEEPSEEK_R1_MODEL_NAME", "DeepSeek-R1-Distill"),
]


def select_backend() -> DelegationRoute | None:
    """Select the best available LLM backend via fallback chain.

    Returns:
        DelegationRoute if a backend is available, None otherwise.
    """
    # 1. Local vLLM endpoints (fastest)
    for url_var, model_var, default_model in _LOCAL_VLLM_ENDPOINTS:
        url = os.environ.get(url_var)
        if url:
            model = os.environ.get(model_var, default_model)
            return DelegationRoute(
                backend="local_vllm",
                base_url=url,
                model=model,
                timeout=15,
            )

    # 2. Gemini CLI
    if shutil.which("gemini"):
        return DelegationRoute(
            backend="gemini_cli",
            base_url="cli://gemini",
            model="gemini-cli",
            timeout=60,
        )

    # 3. Codex CLI
    if shutil.which("codex"):
        return DelegationRoute(
            backend="codex_cli",
            base_url="cli://codex",
            model="codex-cli",
            timeout=120,
        )

    # 4. GLM/Z.AI (cloud fallback)
    glm_url = os.environ.get("LLM_GLM_URL")
    glm_key = os.environ.get("LLM_GLM_API_KEY")
    if glm_url and glm_key:
        glm_model = os.environ.get("LLM_GLM_MODEL_NAME", "glm-4.5")
        return DelegationRoute(
            backend="glm",
            base_url=glm_url,
            model=glm_model,
            api_key=glm_key,
            timeout=30,
        )

    return None


def handle_delegation_dispatch(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Classify prompt, select backend, return routing decision.

    Args:
        payload: Command event payload with 'prompt', 'correlation_id', 'session_id'.

    Returns:
        Dict with routing decision: backend, model, intent, confidence,
        or failure reason.
    """
    prompt = payload.get("prompt", "")
    correlation_id = payload.get("correlation_id", "")

    if not prompt:
        return {
            "routed": False,
            "reason": "empty_prompt",
            "correlation_id": correlation_id,
        }

    # Classify
    classifier = TaskClassifier()
    score = classifier.is_delegatable(prompt)

    if not score.delegatable:
        return {
            "routed": False,
            "reason": f"not_delegatable: {score.reasons[0] if score.reasons else 'unknown'}",
            "intent": score.primary_intent.value
            if hasattr(score, "primary_intent")
            else "unknown",
            "confidence": score.confidence,
            "correlation_id": correlation_id,
        }

    # Select backend
    route = select_backend()
    if route is None:
        return {
            "routed": False,
            "reason": "no_backend_available",
            "intent": score.delegate_to_model,
            "confidence": score.confidence,
            "correlation_id": correlation_id,
        }

    logger.info(
        "Delegation dispatch: intent=%s confidence=%.2f backend=%s model=%s (correlation_id=%s)",
        score.delegate_to_model,
        score.confidence,
        route.backend,
        route.model,
        correlation_id,
    )

    return {
        "routed": True,
        "backend": route.backend,
        "base_url": route.base_url,
        "model": route.model,
        "api_key": route.api_key,
        "timeout": route.timeout,
        "intent": score.delegate_to_model,
        "confidence": score.confidence,
        "estimated_savings_usd": score.estimated_savings_usd,
        "prompt": prompt,
        "correlation_id": correlation_id,
        "session_id": payload.get("session_id", ""),
    }


__all__ = [
    "DelegationRoute",
    "handle_delegation_dispatch",
    "select_backend",
]
