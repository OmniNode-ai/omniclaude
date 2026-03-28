# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for task_id field on hook event payload models.

OMN-6851: Add task_id field to hook event payloads for cross-session correlation.

Doctrine D2 scope: task_id is added to user-workflow payloads participating in
resume/replay semantics. Excluded from purely infrastructural/tracing payloads
(e.g., ModelCorrelationTraceSpanPayload).

Included models (user-workflow):
    - ModelHookSessionStartedPayload (session lifecycle)
    - ModelHookSessionEndedPayload (session lifecycle)
    - ModelHookPromptSubmittedPayload (prompt execution)
    - ModelHookToolExecutedPayload (tool execution)
    - ModelHookContextInjectedPayload (context injection)
    - ModelHookManifestInjectedPayload (manifest injection)
    - ModelAgentStatusPayload (agent delegation)
    - ModelTaskDelegatedPayload (agent delegation)
    - ModelHookDecisionRecordedPayload (decision recording)

Excluded models (infra/tracing/performance-only):
    - ModelCorrelationTraceSpanPayload (tracing-only per D2)
    - ModelRoutingFeedbackPayload (routing feedback)
    - ModelValidatorCatchPayload (validation infra)
    - ModelContextUtilizationPayload (utilization metrics)
    - ModelAgentMatchPayload (routing matching)
    - ModelLatencyBreakdownPayload (performance metrics)
    - ModelStaticContextEditDetectedPayload (static detection)
    - ModelLlmRoutingDecisionPayload (routing infra)
    - ModelLlmRoutingFallbackPayload (routing fallback)
    - ModelDelegationShadowComparisonPayload (shadow comparison)
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from omniclaude.hooks.schemas import (
    EnumAgentState,
    ModelAgentStatusPayload,
    ModelCorrelationTraceSpanPayload,
    ModelHookContextInjectedPayload,
    ModelHookDecisionRecordedPayload,
    ModelHookManifestInjectedPayload,
    ModelHookPromptSubmittedPayload,
    ModelHookSessionEndedPayload,
    ModelHookSessionStartedPayload,
    ModelHookToolExecutedPayload,
    ModelTaskDelegatedPayload,
)

_SESSION_ID = uuid4()
_NOW = datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)


def _base_tracing() -> dict:
    """Common tracing fields for payload construction."""
    return {
        "entity_id": _SESSION_ID,
        "session_id": str(_SESSION_ID),
        "correlation_id": _SESSION_ID,
        "causation_id": uuid4(),
        "emitted_at": _NOW,
    }


@pytest.mark.unit
class TestTaskIdFieldPresent:
    """task_id field exists and is optional (None by default) on user-workflow payloads."""

    def test_session_started_task_id_default_none(self) -> None:
        payload = ModelHookSessionStartedPayload(
            **_base_tracing(),
            working_directory="/workspace",
            hook_source="startup",
        )
        assert payload.task_id is None

    def test_session_started_task_id_accepted(self) -> None:
        payload = ModelHookSessionStartedPayload(
            **_base_tracing(),
            working_directory="/workspace",
            hook_source="startup",
            task_id="OMN-1234",
        )
        assert payload.task_id == "OMN-1234"

    def test_session_ended_task_id(self) -> None:
        payload = ModelHookSessionEndedPayload(
            **_base_tracing(),
            reason="clear",
        )
        assert payload.task_id is None

    def test_session_ended_task_id_accepted(self) -> None:
        payload = ModelHookSessionEndedPayload(
            **_base_tracing(),
            reason="clear",
            task_id="OMN-5678",
        )
        assert payload.task_id == "OMN-5678"

    def test_prompt_submitted_task_id(self) -> None:
        payload = ModelHookPromptSubmittedPayload(
            **_base_tracing(),
            prompt_id=uuid4(),
            prompt_preview="test prompt",
            prompt_length=11,
            detected_intent="fix",
        )
        assert payload.task_id is None

    def test_prompt_submitted_task_id_accepted(self) -> None:
        payload = ModelHookPromptSubmittedPayload(
            **_base_tracing(),
            prompt_id=uuid4(),
            prompt_preview="test prompt",
            prompt_length=11,
            detected_intent="fix",
            task_id="OMN-9999",
        )
        assert payload.task_id == "OMN-9999"

    def test_tool_executed_task_id(self) -> None:
        payload = ModelHookToolExecutedPayload(
            **_base_tracing(),
            tool_name="Read",
            tool_execution_id=uuid4(),
            success=True,
            duration_ms=50,
        )
        assert payload.task_id is None

    def test_tool_executed_task_id_accepted(self) -> None:
        payload = ModelHookToolExecutedPayload(
            **_base_tracing(),
            tool_name="Read",
            tool_execution_id=uuid4(),
            success=True,
            duration_ms=50,
            task_id="OMN-2222",
        )
        assert payload.task_id == "OMN-2222"

    def test_context_injected_task_id(self) -> None:
        payload = ModelHookContextInjectedPayload(
            **_base_tracing(),
            context_source="database",
            pattern_count=5,
            context_size_bytes=1024,
            retrieval_duration_ms=50,
        )
        assert payload.task_id is None

    def test_manifest_injected_task_id(self) -> None:
        payload = ModelHookManifestInjectedPayload(
            **_base_tracing(),
            agent_name="polymorphic-agent",
            agent_domain="general",
            injection_success=True,
            injection_duration_ms=25,
        )
        assert payload.task_id is None

    def test_agent_status_task_id(self) -> None:
        payload = ModelAgentStatusPayload(
            session_id=str(_SESSION_ID),
            correlation_id=_SESSION_ID,
            emitted_at=_NOW,
            agent_name="test-agent",
            state=EnumAgentState.WORKING,
            message="Processing task",
        )
        assert payload.task_id is None

    def test_task_delegated_task_id(self) -> None:
        payload = ModelTaskDelegatedPayload(
            session_id=str(_SESSION_ID),
            correlation_id=_SESSION_ID,
            emitted_at=_NOW,
            task_type="document",
            handler_used="doc_gen",
            model_used="Qwen2.5-72B",
            quality_gate_passed=True,
            delegation_success=True,
            estimated_savings_usd=0.01,
            latency_ms=100,
        )
        assert payload.task_id is None

    def test_decision_recorded_task_id(self) -> None:
        payload = ModelHookDecisionRecordedPayload(
            decision_id="dec-abc",
            decision_type="agent_routing",
            selected_candidate="polymorphic-agent",
            candidates_count=5,
            has_rationale=True,
            emitted_at=_NOW,
            session_id=str(_SESSION_ID),
        )
        assert payload.task_id is None


@pytest.mark.unit
class TestTaskIdMaxLength:
    """task_id enforces max_length=64."""

    def test_task_id_max_length_accepted(self) -> None:
        payload = ModelHookSessionStartedPayload(
            **_base_tracing(),
            working_directory="/workspace",
            hook_source="startup",
            task_id="A" * 64,
        )
        assert len(payload.task_id) == 64  # type: ignore[arg-type]

    def test_task_id_over_max_length_rejected(self) -> None:
        with pytest.raises(Exception):
            ModelHookSessionStartedPayload(
                **_base_tracing(),
                working_directory="/workspace",
                hook_source="startup",
                task_id="A" * 65,
            )


@pytest.mark.unit
class TestTaskIdExcludedFromInfraPayloads:
    """Infra-only payloads must NOT have task_id (Doctrine D2)."""

    def test_trace_span_has_no_task_id(self) -> None:
        """ModelCorrelationTraceSpanPayload is tracing-only and must not carry task_id."""
        assert not hasattr(ModelCorrelationTraceSpanPayload.model_fields, "task_id")
        # Also verify it's not accepted as a field
        fields = ModelCorrelationTraceSpanPayload.model_fields
        assert "task_id" not in fields
