# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""In-process delegation pipeline runner.

Drives the full delegation pipeline (routing → inference → quality gate) in a
single process using the same handler pure-functions the Kafka-backed pipeline
uses in production. No Kafka, Postgres, or Docker required. Suitable for local
delegation from the UserPromptSubmit hook when the runtime socket is
unavailable.

Distinct from :class:`omniclaude.delegation.runner.DelegationRunner` (Bifrost
gateway adapter) — that runner is the production-canonical path. Use this
runner only when the Kafka/runtime path is not reachable.

Related:
    - OMN-10610: In-process delegation pipeline runner
    - OMN-10604: Delegation pipeline epic
    - OMN-2248: Delegated Task Execution via Local Models (epic)
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime
from enum import StrEnum

import httpx
from omnibase_infra.nodes.node_delegation_orchestrator.models.model_delegation_request import (
    ModelDelegationRequest,
)
from omnibase_infra.nodes.node_delegation_orchestrator.models.model_delegation_result import (
    ModelDelegationResult,
)
from omnibase_infra.nodes.node_delegation_quality_gate_reducer.handlers.handler_quality_gate import (
    delta as quality_gate_delta,
)
from omnibase_infra.nodes.node_delegation_quality_gate_reducer.models.model_quality_gate_input import (
    ModelQualityGateInput,
)
from omnibase_infra.nodes.node_delegation_routing_reducer.handlers.handler_delegation_routing import (
    delta as routing_delta,
)

logger = logging.getLogger(__name__)

# HTTP timeouts: connect fast, allow generous read for slow local models.
_HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)


class EnumDelegationTaskType(StrEnum):
    """Task types accepted by the in-process delegation runner."""

    TEST = "test"
    DOCUMENT = "document"
    RESEARCH = "research"


class DelegationRunnerError(Exception):
    """Raised when the in-process delegation pipeline fails to produce a result."""


def _call_llm(
    *,
    endpoint_url: str,
    model: str,
    system_prompt: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    correlation_id: uuid.UUID,
) -> tuple[str, dict[str, int], int, str]:
    """POST to an OpenAI-compatible /v1/chat/completions endpoint.

    Returns (content, token_usage, latency_ms, model_used).
    Raises DelegationRunnerError on network failure or non-200 response.
    """
    url = f"{endpoint_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    t0 = time.monotonic_ns()
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.post(url, json=payload)
    except httpx.TimeoutException as exc:
        raise DelegationRunnerError(
            f"LLM inference timed out after 120s (correlation_id={correlation_id})"
        ) from exc
    except httpx.NetworkError as exc:
        raise DelegationRunnerError(
            f"LLM endpoint unreachable: {endpoint_url} — {exc}"
        ) from exc

    latency_ms = (time.monotonic_ns() - t0) // 1_000_000

    if response.status_code != 200:
        raise DelegationRunnerError(
            f"LLM endpoint returned HTTP {response.status_code} for {url}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise DelegationRunnerError(
            f"LLM endpoint returned invalid JSON for {url}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise DelegationRunnerError(
            f"LLM endpoint returned unexpected JSON type {type(data).__name__} for {url}"
        )
    try:
        content: str = data["choices"][0]["message"]["content"] or ""
        model_used: str = data.get("model", model)
        usage: dict[str, int] = {
            "prompt_tokens": data.get("usage", {}).get("prompt_tokens", 0),
            "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
            "total_tokens": data.get("usage", {}).get("total_tokens", 0),
        }
    except (KeyError, IndexError, TypeError) as exc:
        raise DelegationRunnerError(
            f"LLM response missing expected fields: {exc} — raw keys: {list(data.keys())}"
        ) from exc

    logger.debug(
        "LLM inference complete",
        extra={
            "endpoint": endpoint_url,
            "model": model_used,
            "latency_ms": latency_ms,
            "correlation_id": str(correlation_id),
        },
    )
    return content, usage, int(latency_ms), model_used


class InProcessDelegationRunner:
    """In-process delegation pipeline runner.

    Coordinates routing → inference → quality-gate using the same handler
    pure-functions that the Kafka-backed pipeline uses in production.
    No external bus required; all state is local and synchronous.

    Distinct from :class:`omniclaude.delegation.runner.DelegationRunner`
    (Bifrost gateway adapter) — use this runner when the runtime socket /
    Kafka path is unavailable (e.g. UserPromptSubmit hook running on a
    developer laptop without Docker). The Bifrost adapter is the
    production-canonical path.

    Usage::

        runner = InProcessDelegationRunner()
        result = runner.run(
            task_type="test",
            prompt="Write tests for foo.py",
            tool_input={"tool": "Bash", "command": "..."},
        )
        if result.quality_passed:
            print(result.content)
        else:
            print("Quality gate failed:", result.failure_reason)
    """

    def run(
        self,
        *,
        task_type: EnumDelegationTaskType | str,
        prompt: str,
        tool_input: dict[str, object] | None = None,
        source_session_id: str | None = None,
        source_file_path: str | None = None,
        max_tokens: int = 2048,
    ) -> ModelDelegationResult:
        """Run the delegation pipeline synchronously and return the result.

        Steps:
          1. Build a ModelDelegationRequest (contract-declared input model).
          2. Call routing_delta(request) → ModelRoutingDecision (pure, reads env).
          3. POST to the selected endpoint via _call_llm.
          4. Call quality_gate_delta(gate_input) → ModelQualityGateResult (pure).
          5. Return ModelDelegationResult.

        Args:
            task_type: One of "test", "document", "research".
            prompt: The user prompt to send to the local LLM.
            tool_input: Optional tool input dict serialized into the prompt context.
            source_session_id: Claude Code session identifier for traceability.
            source_file_path: File path context for the delegation.
            max_tokens: Maximum tokens for the LLM response.

        Returns:
            ModelDelegationResult with content, quality metrics, and token usage.

        Raises:
            DelegationRunnerError: If routing fails (no configured endpoint) or
                the LLM call fails with a network/HTTP error.
        """
        correlation_id = uuid.uuid4()
        started_ns = time.monotonic_ns()

        # Normalize task_type to enum; raise on unknown values.
        if not isinstance(task_type, EnumDelegationTaskType):
            try:
                task_type = EnumDelegationTaskType(task_type)
            except ValueError:
                valid = [e.value for e in EnumDelegationTaskType]
                raise DelegationRunnerError(
                    f"Unknown task_type={task_type!r}. Valid values: {valid}"
                )

        # Embed tool_input as JSON comment in prompt when present.
        full_prompt = prompt
        if tool_input:
            tool_json = json.dumps(tool_input, indent=2, default=str)
            full_prompt = (
                f"{prompt}\n\n# Tool input context:\n```json\n{tool_json}\n```"
            )

        request = ModelDelegationRequest(
            prompt=full_prompt,
            task_type=task_type,
            source_session_id=source_session_id,
            source_file_path=source_file_path,
            correlation_id=correlation_id,
            max_tokens=max_tokens,
            emitted_at=datetime.now(UTC),
        )

        # Step 1: routing (pure function, reads env vars for endpoints)
        try:
            routing_decision = routing_delta(request)
        except Exception as exc:
            raise DelegationRunnerError(
                f"Routing failed for task_type={task_type!r}: {exc}"
            ) from exc

        logger.info(
            "Delegation routed",
            extra={
                "task_type": task_type,
                "model": routing_decision.selected_model,
                "endpoint": routing_decision.endpoint_url,
                "correlation_id": str(correlation_id),
            },
        )

        # Step 2: LLM inference
        _TASK_TEMPERATURE: dict[EnumDelegationTaskType, float] = {
            EnumDelegationTaskType.TEST: 0.3,
            EnumDelegationTaskType.DOCUMENT: 0.5,
            EnumDelegationTaskType.RESEARCH: 0.7,
        }
        temperature = _TASK_TEMPERATURE[task_type]

        content, usage, _inference_latency_ms, model_used = _call_llm(
            endpoint_url=routing_decision.endpoint_url,
            model=routing_decision.selected_model,
            system_prompt=routing_decision.system_prompt,
            prompt=full_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            correlation_id=correlation_id,
        )

        # Step 3: quality gate (pure function)
        gate_input = ModelQualityGateInput(
            correlation_id=correlation_id,
            task_type=task_type,
            llm_response_content=content,
        )
        try:
            gate_result = quality_gate_delta(gate_input)
        except Exception as exc:
            raise DelegationRunnerError(
                f"Quality gate failed for task_type={task_type!r}, "
                f"correlation_id={correlation_id}: {exc}"
            ) from exc

        elapsed_ms = (time.monotonic_ns() - started_ns) // 1_000_000

        return ModelDelegationResult(
            correlation_id=correlation_id,
            task_type=task_type,
            model_used=model_used,
            endpoint_url=routing_decision.endpoint_url,
            content=content,
            quality_passed=gate_result.passed,
            quality_score=gate_result.quality_score,
            latency_ms=int(elapsed_ms),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            fallback_to_claude=gate_result.fallback_recommended,
            failure_reason="; ".join(gate_result.failure_reasons)
            if not gate_result.passed
            else "",
        )


__all__: list[str] = [
    "DelegationRunnerError",
    "EnumDelegationTaskType",
    "InProcessDelegationRunner",
]
