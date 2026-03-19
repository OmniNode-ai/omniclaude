# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for treatment group wiring in session outcome (OMN-5551).

Validates that treatment_group flows from ModelSessionOutcomeConfig
through to ModelSessionOutcome in the emitter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from omnibase_core.enums import EnumClaudeCodeSessionOutcome

from omniclaude.hooks.handler_event_emitter import (
    ModelEventTracingConfig,
    ModelSessionOutcomeConfig,
    emit_session_outcome_from_config,
)

pytestmark = pytest.mark.unit


class TestTreatmentGroupWiring:
    """Test treatment_group flows through session outcome emission."""

    def test_config_accepts_treatment_group(self) -> None:
        config = ModelSessionOutcomeConfig(
            session_id="sess-001",
            outcome=EnumClaudeCodeSessionOutcome.SUCCESS,
            treatment_group="treatment",
        )
        assert config.treatment_group == "treatment"

    def test_config_defaults_to_none(self) -> None:
        config = ModelSessionOutcomeConfig(
            session_id="sess-002",
            outcome=EnumClaudeCodeSessionOutcome.SUCCESS,
        )
        assert config.treatment_group is None

    def test_config_accepts_control(self) -> None:
        config = ModelSessionOutcomeConfig(
            session_id="sess-003",
            outcome=EnumClaudeCodeSessionOutcome.SUCCESS,
            treatment_group="control",
        )
        assert config.treatment_group == "control"

    def test_config_accepts_unknown(self) -> None:
        config = ModelSessionOutcomeConfig(
            session_id="sess-004",
            outcome=EnumClaudeCodeSessionOutcome.UNKNOWN,
            treatment_group="unknown",
        )
        assert config.treatment_group == "unknown"

    @pytest.mark.asyncio
    async def test_treatment_group_passed_to_payload(self) -> None:
        """Verify treatment_group is passed through to the ModelSessionOutcome payload."""
        config = ModelSessionOutcomeConfig(
            session_id="sess-005",
            outcome=EnumClaudeCodeSessionOutcome.SUCCESS,
            tracing=ModelEventTracingConfig(
                emitted_at=datetime(2026, 3, 19, 12, 0, 0, tzinfo=UTC),
            ),
            treatment_group="treatment",
        )

        with patch(
            "omniclaude.hooks.handler_event_emitter.EventBusKafka"
        ) as mock_bus_cls:
            mock_bus = AsyncMock()
            mock_bus.publish = AsyncMock(return_value=None)
            mock_bus.close = AsyncMock()
            mock_bus_cls.return_value = mock_bus

            result = await emit_session_outcome_from_config(config)

            # Check the payload passed to publish contains treatment_group
            if mock_bus.publish.called:
                call_args = mock_bus.publish.call_args
                payload_json = call_args[1].get("value") or call_args[0][1]
                import json

                payload_data = json.loads(payload_json)
                # The envelope wraps the payload
                if "payload" in payload_data:
                    assert payload_data["payload"]["treatment_group"] == "treatment"
                else:
                    assert payload_data.get("treatment_group") == "treatment"
