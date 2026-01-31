# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for injection tracking integration.

Tests verify:
- Control cohort records empty injection and returns early
- Treatment cohort with no patterns records no_patterns source
- Treatment cohort with patterns records injected source
- Emit failures don't break the handler
- No tracking when session_id is empty

Part of OMN-1673: INJECT-004 injection tracking.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from omniclaude.hooks.cohort_assignment import EnumCohort
from omniclaude.hooks.context_config import ContextInjectionConfig
from omniclaude.hooks.handler_context_injection import HandlerContextInjection
from omniclaude.hooks.models_injection_tracking import (
    EnumInjectionContext,
    EnumInjectionSource,
)

pytestmark = pytest.mark.unit

# =============================================================================
# Deterministic Session IDs for Cohort Testing
# =============================================================================
# These session IDs have been pre-computed to hash deterministically to their
# respective cohorts using SHA-256(session_id + ":omniclaude-injection-v1") % 100.
# Control cohort: seed 0-19 (20%), Treatment cohort: seed 20-99 (80%)

# Session ID that deterministically hashes to CONTROL cohort (seed=16)
SESSION_ID_CONTROL = "test-session-6"

# Session ID that deterministically hashes to TREATMENT cohort (seed=52)
SESSION_ID_TREATMENT = "test-session-0"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def disabled_db_config() -> ContextInjectionConfig:
    """Config with database disabled for unit tests."""
    return ContextInjectionConfig(
        enabled=True,
        min_confidence=0.0,
        db_enabled=False,
    )


@pytest.fixture
def handler(disabled_db_config: ContextInjectionConfig) -> HandlerContextInjection:
    """Create a handler with disabled database."""
    return HandlerContextInjection(config=disabled_db_config)


# =============================================================================
# Test Injection Tracking in Handler
# =============================================================================


class TestInjectionTracking:
    """Test injection tracking in handler."""

    @pytest.mark.asyncio
    @patch("omniclaude.hooks.handler_context_injection.emit_hook_event")
    @patch("plugins.onex.hooks.lib.emit_client_wrapper.emit_event")
    async def test_emit_failure_does_not_raise(
        self,
        mock_emit_client: MagicMock,
        mock_emit_hook: MagicMock,
        disabled_db_config: ContextInjectionConfig,
    ) -> None:
        """Emit failure is logged but doesn't break handler."""
        mock_emit_client.return_value = False  # Simulate failure
        mock_emit_hook.return_value = None  # Don't emit hook event
        handler = HandlerContextInjection(config=disabled_db_config)

        # Should not raise even when emit fails
        # Use pre-computed session ID that deterministically hashes to treatment cohort
        # SESSION_ID_TREATMENT ("test-session-0") -> seed=52 -> TREATMENT
        result = await handler.handle(
            session_id=SESSION_ID_TREATMENT,
            emit_event=False,
        )
        assert result.success  # Handler still succeeds

    @pytest.mark.asyncio
    async def test_no_tracking_when_no_session_id(
        self,
        disabled_db_config: ContextInjectionConfig,
    ) -> None:
        """No injection recorded when session_id is empty."""
        handler = HandlerContextInjection(config=disabled_db_config)

        with patch.object(handler, "_emit_injection_record") as mock_emit:
            await handler.handle(session_id="", emit_event=False)
            mock_emit.assert_not_called()

    @pytest.mark.asyncio
    @patch("plugins.onex.hooks.lib.emit_client_wrapper.emit_event")
    async def test_injection_context_default(
        self,
        mock_emit: MagicMock,
        disabled_db_config: ContextInjectionConfig,
    ) -> None:
        """Default injection_context is USER_PROMPT_SUBMIT."""
        mock_emit.return_value = True
        handler = HandlerContextInjection(config=disabled_db_config)

        # Use pre-computed session ID that deterministically hashes to treatment cohort
        # SESSION_ID_TREATMENT ("test-session-0") -> seed=52 -> TREATMENT
        # The handler will call _emit_injection_record which calls emit_event
        await handler.handle(
            session_id=SESSION_ID_TREATMENT,
            emit_event=False,
        )

        # Treatment cohort always emits, verify with explicit assertion
        mock_emit.assert_called_once()
        call_args = mock_emit.call_args
        payload = call_args[0][1]  # Second positional arg is payload
        assert (
            payload["injection_context"]
            == EnumInjectionContext.USER_PROMPT_SUBMIT.value
        )

    @pytest.mark.asyncio
    @patch("plugins.onex.hooks.lib.emit_client_wrapper.emit_event")
    async def test_control_cohort_emits_control_source(
        self,
        mock_emit: MagicMock,
        disabled_db_config: ContextInjectionConfig,
    ) -> None:
        """Control cohort sessions emit with control_cohort source."""
        mock_emit.return_value = True
        handler = HandlerContextInjection(config=disabled_db_config)

        # Use pre-computed session ID that deterministically hashes to control cohort
        # SESSION_ID_CONTROL ("test-session-6") -> seed=16 -> CONTROL
        result = await handler.handle(
            session_id=SESSION_ID_CONTROL,
            emit_event=False,
        )

        # Control cohort returns early with empty patterns
        assert result.success
        assert result.pattern_count == 0
        assert result.source == "control_cohort"

        # Control cohort also emits (with control_cohort source), verify explicitly
        mock_emit.assert_called_once()
        call_args = mock_emit.call_args
        payload = call_args[0][1]
        assert payload["source"] == EnumInjectionSource.CONTROL_COHORT.value


# =============================================================================
# Test _emit_injection_record Helper Method
# =============================================================================


class TestEmitInjectionRecord:
    """Test _emit_injection_record helper method."""

    def test_emit_injection_record_returns_bool(
        self,
        disabled_db_config: ContextInjectionConfig,
    ) -> None:
        """Test _emit_injection_record returns boolean."""
        handler = HandlerContextInjection(config=disabled_db_config)

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event"
        ) as mock_emit:
            mock_emit.return_value = True
            result = handler._emit_injection_record(
                injection_id=uuid4(),
                session_id_raw="test-session",
                pattern_ids=[],
                injection_context=EnumInjectionContext.USER_PROMPT_SUBMIT,
                source=EnumInjectionSource.CONTROL_COHORT,
                cohort=EnumCohort.CONTROL,
                assignment_seed=15,
                injected_content="",
                injected_token_count=0,
                correlation_id="",
            )
            assert result is True

    def test_emit_injection_record_handles_exception(
        self,
        disabled_db_config: ContextInjectionConfig,
    ) -> None:
        """Test _emit_injection_record handles exceptions gracefully."""
        handler = HandlerContextInjection(config=disabled_db_config)

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event"
        ) as mock_emit:
            mock_emit.side_effect = Exception("Connection failed")
            result = handler._emit_injection_record(
                injection_id=uuid4(),
                session_id_raw="test-session",
                pattern_ids=[],
                injection_context=EnumInjectionContext.USER_PROMPT_SUBMIT,
                source=EnumInjectionSource.ERROR,
                cohort=EnumCohort.TREATMENT,
                assignment_seed=75,
                injected_content="",
                injected_token_count=0,
                correlation_id="",
            )
            assert result is False

    def test_emit_injection_record_returns_false_on_emit_failure(
        self,
        disabled_db_config: ContextInjectionConfig,
    ) -> None:
        """Test _emit_injection_record returns False when emit returns False."""
        handler = HandlerContextInjection(config=disabled_db_config)

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event"
        ) as mock_emit:
            mock_emit.return_value = False  # Daemon unavailable
            result = handler._emit_injection_record(
                injection_id=uuid4(),
                session_id_raw="test-session",
                pattern_ids=["pattern-1", "pattern-2"],
                injection_context=EnumInjectionContext.SESSION_START,
                source=EnumInjectionSource.INJECTED,
                cohort=EnumCohort.TREATMENT,
                assignment_seed=50,
                injected_content="## Some markdown",
                injected_token_count=10,
                correlation_id="corr-123",
            )
            assert result is False

    def test_emit_injection_record_payload_structure(
        self,
        disabled_db_config: ContextInjectionConfig,
    ) -> None:
        """Test _emit_injection_record creates correct payload structure."""
        handler = HandlerContextInjection(config=disabled_db_config)
        injection_id = uuid4()

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event"
        ) as mock_emit:
            mock_emit.return_value = True
            handler._emit_injection_record(
                injection_id=injection_id,
                session_id_raw="test-session-123",
                pattern_ids=["pat-001", "pat-002"],
                injection_context=EnumInjectionContext.PRE_TOOL_USE,
                source=EnumInjectionSource.INJECTED,
                cohort=EnumCohort.TREATMENT,
                assignment_seed=42,
                injected_content="## Patterns\n\nContent here",
                injected_token_count=25,
                correlation_id="correlation-abc",
            )

            mock_emit.assert_called_once()
            call_args = mock_emit.call_args
            event_type = call_args[0][0]
            payload = call_args[0][1]

            assert event_type == "injection.recorded"
            assert payload["injection_id"] == str(injection_id)
            assert payload["session_id"] == "test-session-123"
            assert payload["pattern_ids"] == ["pat-001", "pat-002"]
            assert payload["injection_context"] == "PreToolUse"
            assert payload["source"] == "injected"
            assert payload["cohort"] == "treatment"
            assert payload["assignment_seed"] == 42
            assert payload["injected_content"] == "## Patterns\n\nContent here"
            assert payload["injected_token_count"] == 25
            assert payload["correlation_id"] == "correlation-abc"


# =============================================================================
# Test Injection Source Enums
# =============================================================================


class TestInjectionSourceEnums:
    """Test injection source enum values."""

    def test_control_cohort_value(self) -> None:
        """Test control_cohort source value."""
        assert EnumInjectionSource.CONTROL_COHORT.value == "control_cohort"

    def test_no_patterns_value(self) -> None:
        """Test no_patterns source value."""
        assert EnumInjectionSource.NO_PATTERNS.value == "no_patterns"

    def test_injected_value(self) -> None:
        """Test injected source value."""
        assert EnumInjectionSource.INJECTED.value == "injected"

    def test_error_value(self) -> None:
        """Test error source value."""
        assert EnumInjectionSource.ERROR.value == "error"

    def test_all_values_are_strings(self) -> None:
        """Test all enum values are strings."""
        for member in EnumInjectionSource:
            assert isinstance(member.value, str)

    def test_enum_members_count(self) -> None:
        """Test correct number of enum members."""
        assert len(EnumInjectionSource) == 4


# =============================================================================
# Test Injection Context Enums
# =============================================================================


class TestInjectionContextEnums:
    """Test injection context enum values match DB CHECK constraints."""

    def test_session_start_value(self) -> None:
        """Test SessionStart context value."""
        assert EnumInjectionContext.SESSION_START.value == "SessionStart"

    def test_user_prompt_submit_value(self) -> None:
        """Test UserPromptSubmit context value."""
        assert EnumInjectionContext.USER_PROMPT_SUBMIT.value == "UserPromptSubmit"

    def test_pre_tool_use_value(self) -> None:
        """Test PreToolUse context value."""
        assert EnumInjectionContext.PRE_TOOL_USE.value == "PreToolUse"

    def test_subagent_start_value(self) -> None:
        """Test SubagentStart context value."""
        assert EnumInjectionContext.SUBAGENT_START.value == "SubagentStart"

    def test_all_values_are_strings(self) -> None:
        """Test all enum values are strings."""
        for member in EnumInjectionContext:
            assert isinstance(member.value, str)

    def test_enum_members_count(self) -> None:
        """Test correct number of enum members."""
        assert len(EnumInjectionContext) == 4

    def test_values_match_hook_event_names(self) -> None:
        """Test enum values match Claude Code hook event names."""
        # These must match the hook event names in Claude Code
        expected_hook_names = {
            "SessionStart",
            "UserPromptSubmit",
            "PreToolUse",
            "SubagentStart",
        }
        actual_values = {member.value for member in EnumInjectionContext}
        assert actual_values == expected_hook_names
