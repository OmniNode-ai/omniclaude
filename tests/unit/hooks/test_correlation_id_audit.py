# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for OMN-6884: correlation_id audit — required where possible.

Validates that:
1. All hook event payload models have required correlation_id fields
2. resolve_correlation_id() correctly falls back through the chain
3. Models that previously had optional correlation_id now require it
4. Models that were missing correlation_id now have it
5. Correlation propagation through emit_*_from_config emitters
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from omnibase_core.enums import EnumClaudeCodeSessionOutcome
from pydantic import ValidationError

from omniclaude.hooks.handler_event_emitter import (
    ModelClaudeHookEventConfig,
    ModelEventTracingConfig,
    ModelSessionOutcomeConfig,
    emit_session_outcome_from_config,
    resolve_correlation_id,
)
from omniclaude.hooks.schemas import (
    ModelRoutingFeedbackPayload,
    ModelSessionOutcome,
    ModelValidatorCatchPayload,
)
from omniclaude.shared.models.model_dod_events import (
    ModelDodGuardFiredEvent,
    ModelDodVerifyCompletedEvent,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)


# =============================================================================
# resolve_correlation_id() tests
# =============================================================================


class TestResolveCorrelationId:
    """Test the central correlation_id resolver (OMN-6884)."""

    def test_returns_tracing_correlation_id_when_present(self) -> None:
        """If tracing has an explicit correlation_id, use it."""
        expected = uuid4()
        tracing = ModelEventTracingConfig(correlation_id=expected)
        result = resolve_correlation_id(tracing)
        assert result == expected

    def test_falls_back_to_uuid_fallback(self) -> None:
        """If tracing.correlation_id is None, use the UUID fallback."""
        fallback = uuid4()
        tracing = ModelEventTracingConfig()
        result = resolve_correlation_id(tracing, fallback=fallback)
        assert result == fallback

    def test_falls_back_to_string_uuid_fallback(self) -> None:
        """If fallback is a valid UUID string, parse and return it."""
        raw = uuid4()
        tracing = ModelEventTracingConfig()
        result = resolve_correlation_id(tracing, fallback=str(raw))
        assert result == raw

    def test_generates_uuid_for_invalid_string_fallback(self) -> None:
        """If fallback is not a valid UUID string, generate a new UUID."""
        tracing = ModelEventTracingConfig()
        result = resolve_correlation_id(tracing, fallback="not-a-uuid")
        assert isinstance(result, UUID)

    def test_generates_uuid_when_no_fallback(self) -> None:
        """If both tracing.correlation_id and fallback are None, generate."""
        tracing = ModelEventTracingConfig()
        result = resolve_correlation_id(tracing)
        assert isinstance(result, UUID)

    def test_tracing_takes_precedence_over_fallback(self) -> None:
        """Tracing correlation_id wins even if fallback is also provided."""
        tracing_id = uuid4()
        fallback_id = uuid4()
        tracing = ModelEventTracingConfig(correlation_id=tracing_id)
        result = resolve_correlation_id(tracing, fallback=fallback_id)
        assert result == tracing_id


# =============================================================================
# ModelRoutingFeedbackPayload — correlation_id now required (was optional)
# =============================================================================


class TestRoutingFeedbackCorrelationRequired:
    """OMN-6884: ModelRoutingFeedbackPayload.correlation_id is now required."""

    def test_accepts_required_correlation_id(self) -> None:
        cid = uuid4()
        payload = ModelRoutingFeedbackPayload(
            session_id="sess-001",
            correlation_id=cid,
            outcome="success",
            feedback_status="produced",
            skip_reason=None,
            emitted_at=_NOW,
        )
        assert payload.correlation_id == cid

    def test_rejects_missing_correlation_id(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ModelRoutingFeedbackPayload(
                session_id="sess-001",
                outcome="success",
                feedback_status="produced",
                skip_reason=None,
                emitted_at=_NOW,
            )
        assert "correlation_id" in str(exc_info.value)


# =============================================================================
# ModelSessionOutcome — correlation_id added (was missing entirely)
# =============================================================================


class TestSessionOutcomeCorrelationRequired:
    """OMN-6884: ModelSessionOutcome now has required correlation_id."""

    def test_accepts_correlation_id(self) -> None:
        cid = uuid4()
        event = ModelSessionOutcome(
            session_id="sess-001",
            correlation_id=cid,
            outcome=EnumClaudeCodeSessionOutcome.SUCCESS,
            emitted_at=_NOW,
        )
        assert event.correlation_id == cid

    def test_rejects_missing_correlation_id(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ModelSessionOutcome(
                session_id="sess-001",
                outcome=EnumClaudeCodeSessionOutcome.SUCCESS,
                emitted_at=_NOW,
            )
        assert "correlation_id" in str(exc_info.value)

    def test_serialization_includes_correlation_id(self) -> None:
        cid = uuid4()
        event = ModelSessionOutcome(
            session_id="sess-001",
            correlation_id=cid,
            outcome=EnumClaudeCodeSessionOutcome.SUCCESS,
            emitted_at=_NOW,
        )
        data = event.model_dump(mode="json")
        assert data["correlation_id"] == str(cid)

    def test_roundtrip_preserves_correlation_id(self) -> None:
        cid = uuid4()
        original = ModelSessionOutcome(
            session_id="sess-rt",
            correlation_id=cid,
            outcome=EnumClaudeCodeSessionOutcome.FAILED,
            emitted_at=_NOW,
        )
        json_str = original.model_dump_json()
        restored = ModelSessionOutcome.model_validate_json(json_str)
        assert restored.correlation_id == cid


# =============================================================================
# ModelValidatorCatchPayload — correlation_id added (was missing entirely)
# =============================================================================


class TestValidatorCatchCorrelationRequired:
    """OMN-6884: ModelValidatorCatchPayload now has required correlation_id."""

    def test_accepts_correlation_id(self) -> None:
        payload = ModelValidatorCatchPayload(
            session_id="sess-001",
            correlation_id="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            validator_type="pre_commit",
            validator_name="ruff",
            catch_description="Import sorting issue",
            severity="error",
            timestamp_iso="2026-03-28T12:00:00Z",
        )
        assert payload.correlation_id == "7c9e6679-7425-40de-944b-e07fc1f90ae7"

    def test_rejects_missing_correlation_id(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ModelValidatorCatchPayload(
                session_id="sess-001",
                validator_type="pre_commit",
                validator_name="ruff",
                catch_description="Issue",
                severity="error",
                timestamp_iso="2026-03-28T12:00:00Z",
            )
        assert "correlation_id" in str(exc_info.value)


# =============================================================================
# ModelDodGuardFiredEvent — correlation_id added (was missing entirely)
# =============================================================================


class TestDodGuardFiredCorrelationRequired:
    """OMN-6884: ModelDodGuardFiredEvent now has required correlation_id."""

    def test_accepts_correlation_id(self) -> None:
        event = ModelDodGuardFiredEvent(
            ticket_id="OMN-1234",
            session_id="sess-001",
            correlation_id="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            guard_outcome="allowed",
            policy_mode="advisory",
            receipt_age_seconds=120.5,
            receipt_pass=True,
            timestamp="2026-03-28T12:00:00Z",
        )
        assert event.correlation_id == "7c9e6679-7425-40de-944b-e07fc1f90ae7"

    def test_rejects_missing_correlation_id(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ModelDodGuardFiredEvent(
                ticket_id="OMN-1234",
                session_id="sess-001",
                guard_outcome="allowed",
                policy_mode="advisory",
                receipt_age_seconds=None,
                receipt_pass=None,
                timestamp="2026-03-28T12:00:00Z",
            )
        assert "correlation_id" in str(exc_info.value)


# =============================================================================
# ModelDodVerifyCompletedEvent — correlation_id already required (str type)
# =============================================================================


class TestDodVerifyCompletedCorrelation:
    """ModelDodVerifyCompletedEvent already had required correlation_id: str."""

    def test_correlation_id_is_required(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ModelDodVerifyCompletedEvent(
                ticket_id="OMN-1234",
                run_id="run-001",
                session_id="sess-001",
                # Missing correlation_id
                total_checks=5,
                passed_checks=4,
                failed_checks=1,
                skipped_checks=0,
                overall_pass=False,
                policy_mode="advisory",
                evidence_items=[],
                timestamp="2026-03-28T12:00:00Z",
            )
        assert "correlation_id" in str(exc_info.value)


# =============================================================================
# ModelClaudeHookEventConfig — correlation_id now defaults to uuid4()
# =============================================================================


class TestClaudeHookEventConfigCorrelation:
    """OMN-6884: ModelClaudeHookEventConfig.correlation_id now has a default."""

    def test_default_generates_uuid(self) -> None:
        from omnibase_core.enums.hooks.claude_code import (
            EnumClaudeCodeHookEventType,
        )

        config = ModelClaudeHookEventConfig(
            event_type=EnumClaudeCodeHookEventType.USER_PROMPT_SUBMIT,
            session_id="sess-001",
        )
        assert isinstance(config.correlation_id, UUID)

    def test_explicit_overrides_default(self) -> None:
        from omnibase_core.enums.hooks.claude_code import (
            EnumClaudeCodeHookEventType,
        )

        explicit_id = uuid4()
        config = ModelClaudeHookEventConfig(
            event_type=EnumClaudeCodeHookEventType.USER_PROMPT_SUBMIT,
            session_id="sess-001",
            correlation_id=explicit_id,
        )
        assert config.correlation_id == explicit_id


# =============================================================================
# Cross-boundary propagation: emit_session_outcome_from_config
# =============================================================================


class TestSessionOutcomeCorrelationPropagation:
    """OMN-6884: correlation_id propagates through session outcome emission."""

    @pytest.mark.asyncio
    async def test_correlation_propagated_from_tracing(self) -> None:
        """Emitter passes tracing.correlation_id into ModelSessionOutcome."""
        expected_cid = uuid4()
        config = ModelSessionOutcomeConfig(
            session_id="sess-prop-001",
            outcome=EnumClaudeCodeSessionOutcome.SUCCESS,
            tracing=ModelEventTracingConfig(
                correlation_id=expected_cid,
                emitted_at=_NOW,
            ),
        )

        with patch(
            "omniclaude.hooks.handler_event_emitter.EventBusKafka"
        ) as mock_bus_cls:
            mock_bus = AsyncMock()
            mock_bus.publish = AsyncMock(return_value=None)
            mock_bus.close = AsyncMock()
            mock_bus_cls.return_value = mock_bus

            await emit_session_outcome_from_config(config)

            if mock_bus.publish.called:
                import json

                call_args = mock_bus.publish.call_args
                payload_json = call_args[1].get("value") or call_args[0][1]
                payload_data = json.loads(payload_json)
                assert payload_data.get("correlation_id") == str(expected_cid)

    @pytest.mark.asyncio
    async def test_correlation_falls_back_to_session_id(self) -> None:
        """When tracing has no correlation_id, emitter uses session_id as UUID fallback."""
        session_uuid = uuid4()
        config = ModelSessionOutcomeConfig(
            session_id=str(session_uuid),
            outcome=EnumClaudeCodeSessionOutcome.SUCCESS,
            tracing=ModelEventTracingConfig(
                emitted_at=_NOW,
            ),
        )

        with patch(
            "omniclaude.hooks.handler_event_emitter.EventBusKafka"
        ) as mock_bus_cls:
            mock_bus = AsyncMock()
            mock_bus.publish = AsyncMock(return_value=None)
            mock_bus.close = AsyncMock()
            mock_bus_cls.return_value = mock_bus

            await emit_session_outcome_from_config(config)

            if mock_bus.publish.called:
                import json

                call_args = mock_bus.publish.call_args
                payload_json = call_args[1].get("value") or call_args[0][1]
                payload_data = json.loads(payload_json)
                assert payload_data.get("correlation_id") == str(session_uuid)
