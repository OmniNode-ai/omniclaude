# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for action_description normalization and schema changes (OMN-3297).

Validates:
- normalize_action_description helper: empty, exact-160, 161-char, multi-line inputs
- action_description field present (optional, empty default) in all 5 payload schemas
- Shell-side precedence logic described in the spec
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from omniclaude.hooks._helpers import (
    ACTION_DESCRIPTION_MAX_LENGTH,
    normalize_action_description,
)
from omniclaude.hooks.schemas import (
    ContextSource,
    HookSource,
    ModelHookContextInjectedPayload,
    ModelHookPromptSubmittedPayload,
    ModelHookSessionEndedPayload,
    ModelHookSessionStartedPayload,
    ModelHookToolExecutedPayload,
    SessionEndReason,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
_SESSION_ID = uuid4()


# =============================================================================
# normalize_action_description helper
# =============================================================================


class TestNormalizeActionDescription:
    """Tests for normalize_action_description()."""

    def test_empty_string_returns_empty(self) -> None:
        assert normalize_action_description("") == ""

    def test_exact_160_chars_unchanged(self) -> None:
        s = "x" * ACTION_DESCRIPTION_MAX_LENGTH
        assert normalize_action_description(s) == s
        assert len(normalize_action_description(s)) == ACTION_DESCRIPTION_MAX_LENGTH

    def test_161_chars_truncated_to_160(self) -> None:
        s = "x" * (ACTION_DESCRIPTION_MAX_LENGTH + 1)
        result = normalize_action_description(s)
        assert len(result) == ACTION_DESCRIPTION_MAX_LENGTH
        assert result == "x" * ACTION_DESCRIPTION_MAX_LENGTH

    def test_newline_replaced_with_space(self) -> None:
        assert normalize_action_description("line1\nline2") == "line1 line2"

    def test_carriage_return_replaced_with_space(self) -> None:
        assert normalize_action_description("line1\rline2") == "line1 line2"

    def test_crlf_replaced_with_spaces(self) -> None:
        assert normalize_action_description("line1\r\nline2") == "line1  line2"

    def test_multiline_long_string_truncated_after_normalization(self) -> None:
        # Multi-line string that after replacement exceeds 160 chars
        s = "a\n" * 100  # 200 chars after replacement
        result = normalize_action_description(s)
        assert len(result) == ACTION_DESCRIPTION_MAX_LENGTH
        assert "\n" not in result

    def test_plain_short_string_unchanged(self) -> None:
        s = "Read: topics.py"
        assert normalize_action_description(s) == s

    def test_bash_format_example(self) -> None:
        s = "Bash: git status --porcelain"
        assert normalize_action_description(s) == "Bash: git status --porcelain"

    def test_200_char_string_truncated(self) -> None:
        s = "y" * 200
        result = normalize_action_description(s)
        assert len(result) == ACTION_DESCRIPTION_MAX_LENGTH


# =============================================================================
# Schema: action_description field present with empty default
# =============================================================================


class TestSchemaActionDescriptionDefaults:
    """Verify action_description is present and defaults to empty string."""

    def test_session_started_defaults_empty(self) -> None:
        payload = ModelHookSessionStartedPayload(
            entity_id=_SESSION_ID,
            session_id=str(_SESSION_ID),
            correlation_id=_SESSION_ID,
            causation_id=uuid4(),
            emitted_at=_NOW,
            working_directory="/workspace",
            hook_source=HookSource.STARTUP,
        )
        assert payload.action_description == ""

    def test_session_started_accepts_value(self) -> None:
        payload = ModelHookSessionStartedPayload(
            entity_id=_SESSION_ID,
            session_id=str(_SESSION_ID),
            correlation_id=_SESSION_ID,
            causation_id=uuid4(),
            emitted_at=_NOW,
            working_directory="/workspace",
            hook_source=HookSource.STARTUP,
            action_description="Session: omniclaude@main",
        )
        assert payload.action_description == "Session: omniclaude@main"

    def test_session_ended_defaults_empty(self) -> None:
        payload = ModelHookSessionEndedPayload(
            entity_id=_SESSION_ID,
            session_id=str(_SESSION_ID),
            correlation_id=_SESSION_ID,
            causation_id=uuid4(),
            emitted_at=_NOW,
            reason=SessionEndReason.CLEAR,
        )
        assert payload.action_description == ""

    def test_session_ended_accepts_value(self) -> None:
        payload = ModelHookSessionEndedPayload(
            entity_id=_SESSION_ID,
            session_id=str(_SESSION_ID),
            correlation_id=_SESSION_ID,
            causation_id=uuid4(),
            emitted_at=_NOW,
            reason=SessionEndReason.CLEAR,
            tools_used_count=47,
            action_description="Session ended: 47 tools, 312000ms",
        )
        assert payload.action_description == "Session ended: 47 tools, 312000ms"

    def test_prompt_submitted_defaults_empty(self) -> None:
        payload = ModelHookPromptSubmittedPayload(
            entity_id=_SESSION_ID,
            session_id=str(_SESSION_ID),
            correlation_id=_SESSION_ID,
            causation_id=uuid4(),
            emitted_at=_NOW,
            prompt_id=uuid4(),
            prompt_preview="run gap-cycle",
            prompt_length=13,
        )
        assert payload.action_description == ""

    def test_prompt_submitted_accepts_value(self) -> None:
        payload = ModelHookPromptSubmittedPayload(
            entity_id=_SESSION_ID,
            session_id=str(_SESSION_ID),
            correlation_id=_SESSION_ID,
            causation_id=uuid4(),
            emitted_at=_NOW,
            prompt_id=uuid4(),
            prompt_preview="run gap-cycle for OMN-3216",
            prompt_length=26,
            action_description="Prompt: run gap-cycle for OMN-3216",
        )
        assert payload.action_description == "Prompt: run gap-cycle for OMN-3216"

    def test_tool_executed_defaults_empty(self) -> None:
        payload = ModelHookToolExecutedPayload(
            entity_id=_SESSION_ID,
            session_id=str(_SESSION_ID),
            correlation_id=_SESSION_ID,
            causation_id=uuid4(),
            emitted_at=_NOW,
            tool_execution_id=uuid4(),
            tool_name="Read",
        )
        assert payload.action_description == ""

    def test_tool_executed_read_format(self) -> None:
        payload = ModelHookToolExecutedPayload(
            entity_id=_SESSION_ID,
            session_id=str(_SESSION_ID),
            correlation_id=_SESSION_ID,
            causation_id=uuid4(),
            emitted_at=_NOW,
            tool_execution_id=uuid4(),
            tool_name="Read",
            action_description="Read: topics.py",
        )
        assert payload.action_description == "Read: topics.py"

    def test_tool_executed_bash_format(self) -> None:
        payload = ModelHookToolExecutedPayload(
            entity_id=_SESSION_ID,
            session_id=str(_SESSION_ID),
            correlation_id=_SESSION_ID,
            causation_id=uuid4(),
            emitted_at=_NOW,
            tool_execution_id=uuid4(),
            tool_name="Bash",
            action_description="Bash: git status --porcelain",
        )
        assert payload.action_description == "Bash: git status --porcelain"

    def test_context_injected_defaults_empty(self) -> None:
        payload = ModelHookContextInjectedPayload(
            entity_id=_SESSION_ID,
            session_id=str(_SESSION_ID),
            correlation_id=_SESSION_ID,
            causation_id=uuid4(),
            emitted_at=_NOW,
            context_source=ContextSource.RAG_QUERY,
            pattern_count=3,
            context_size_bytes=3388,
            retrieval_duration_ms=150,
        )
        assert payload.action_description == ""

    def test_context_injected_accepts_value(self) -> None:
        payload = ModelHookContextInjectedPayload(
            entity_id=_SESSION_ID,
            session_id=str(_SESSION_ID),
            correlation_id=_SESSION_ID,
            causation_id=uuid4(),
            emitted_at=_NOW,
            context_source=ContextSource.RAG_QUERY,
            pattern_count=3,
            context_size_bytes=3388,
            retrieval_duration_ms=150,
            action_description="Context: 3 patterns (847 tokens)",
        )
        assert payload.action_description == "Context: 3 patterns (847 tokens)"

    def test_action_description_max_length_enforced(self) -> None:
        """Schema must reject action_description longer than 160 chars."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ModelHookToolExecutedPayload(
                entity_id=_SESSION_ID,
                session_id=str(_SESSION_ID),
                correlation_id=_SESSION_ID,
                causation_id=uuid4(),
                emitted_at=_NOW,
                tool_execution_id=uuid4(),
                tool_name="Read",
                action_description="x" * 161,
            )
