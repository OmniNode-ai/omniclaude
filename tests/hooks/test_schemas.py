# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for OmniClaude hook event schemas.

Validates ONEX-compliant event schemas for Claude Code hooks following
the registration events pattern from omnibase_infra.

ONEX Compliance Tests:
- entity_id: Required partition key (no default)
- correlation_id: Required for distributed tracing (no default)
- causation_id: Required for event chain tracking (no default)
- emitted_at: Required, must be timezone-aware (no default_factory!)
- Immutability (frozen=True)
- Extra fields forbidden (extra="forbid")
- from_attributes=True for ORM compatibility
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from omniclaude.hooks.schemas import (
    PROMPT_PREVIEW_MAX_LENGTH,
    HookEventType,
    ModelHookEventEnvelope,
    ModelHookPromptSubmittedPayload,
    ModelHookSessionEndedPayload,
    ModelHookSessionStartedPayload,
    ModelHookToolExecutedPayload,
)
from omniclaude.hooks.topics import TopicBase, build_topic

# =============================================================================
# Helper Factories
# =============================================================================


def make_timestamp() -> datetime:
    """Create a valid timezone-aware timestamp."""
    return datetime.now(UTC)


def make_entity_id() -> UUID:
    """Create a valid entity ID."""
    return uuid4()


def make_correlation_id() -> UUID:
    """Create a valid correlation ID."""
    return uuid4()


def make_causation_id() -> UUID:
    """Create a valid causation ID."""
    return uuid4()


# =============================================================================
# Session Started Payload Tests
# =============================================================================


class TestModelHookSessionStartedPayload:
    """Tests for session started event payloads."""

    def test_has_required_fields(self) -> None:
        """Payload defines all required ONEX envelope fields."""
        fields = ModelHookSessionStartedPayload.model_fields
        # ONEX envelope fields
        assert "entity_id" in fields
        assert "session_id" in fields
        assert "correlation_id" in fields
        assert "causation_id" in fields
        assert "emitted_at" in fields
        # Domain-specific fields
        assert "working_directory" in fields
        assert "git_branch" in fields
        assert "hook_source" in fields

    def test_entity_id_is_required(self) -> None:
        """entity_id is required, not auto-generated."""
        with pytest.raises(ValidationError) as exc_info:
            ModelHookSessionStartedPayload(
                # Missing entity_id - should fail!
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                working_directory="/tmp",
                hook_source="startup",
            )
        assert "entity_id" in str(exc_info.value)

    def test_correlation_id_is_required(self) -> None:
        """correlation_id is required, not auto-generated."""
        with pytest.raises(ValidationError) as exc_info:
            ModelHookSessionStartedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                # Missing correlation_id - should fail!
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                working_directory="/tmp",
                hook_source="startup",
            )
        assert "correlation_id" in str(exc_info.value)

    def test_causation_id_is_required(self) -> None:
        """causation_id is required for event chain tracking."""
        with pytest.raises(ValidationError) as exc_info:
            ModelHookSessionStartedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                # Missing causation_id - should fail!
                emitted_at=make_timestamp(),
                working_directory="/tmp",
                hook_source="startup",
            )
        assert "causation_id" in str(exc_info.value)

    def test_emitted_at_is_required(self) -> None:
        """emitted_at is required, not auto-generated."""
        with pytest.raises(ValidationError) as exc_info:
            ModelHookSessionStartedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                # Missing emitted_at - should fail!
                working_directory="/tmp",
                hook_source="startup",
            )
        assert "emitted_at" in str(exc_info.value)

    def test_emitted_at_naive_datetime_converted_to_utc(self) -> None:
        """Naive datetimes are converted to UTC with warning (graceful degradation).

        Note: omnibase_infra.utils.ensure_timezone_aware converts naive datetimes
        to UTC rather than rejecting them. This is intentional for graceful
        degradation. A warning is logged when this happens.
        """
        naive_dt = datetime(2025, 1, 19, 12, 0, 0)  # No tzinfo
        # Should NOT raise - graceful degradation converts to UTC
        event = ModelHookSessionStartedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=naive_dt,  # Converted to UTC
            working_directory="/tmp",
            hook_source="startup",
        )
        # Resulting timestamp should be timezone-aware (UTC)
        assert event.emitted_at.tzinfo is not None

    def test_emitted_at_accepts_utc(self) -> None:
        """UTC timezone is accepted."""
        utc_dt = datetime(2025, 1, 19, 12, 0, 0, tzinfo=UTC)
        event = ModelHookSessionStartedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=utc_dt,
            working_directory="/tmp",
            hook_source="startup",
        )
        assert event.emitted_at == utc_dt
        assert event.emitted_at.tzinfo is not None

    def test_create_minimal(self) -> None:
        """Create with minimal required fields."""
        entity_id = make_entity_id()
        correlation_id = make_correlation_id()
        causation_id = make_causation_id()
        emitted_at = make_timestamp()
        event = ModelHookSessionStartedPayload(
            entity_id=entity_id,
            session_id="session-123",
            correlation_id=correlation_id,
            causation_id=causation_id,
            emitted_at=emitted_at,
            working_directory="/workspace/project",
            hook_source="startup",
        )
        assert event.entity_id == entity_id
        assert event.session_id == "session-123"
        assert event.correlation_id == correlation_id
        assert event.causation_id == causation_id
        assert event.emitted_at == emitted_at
        assert event.working_directory == "/workspace/project"
        assert event.hook_source == "startup"
        assert event.git_branch is None

    def test_create_full(self) -> None:
        """Create with all fields."""
        entity_id = uuid4()
        correlation_id = uuid4()
        causation_id = uuid4()
        emitted_at = datetime(2025, 1, 19, 12, 0, 0, tzinfo=UTC)

        event = ModelHookSessionStartedPayload(
            entity_id=entity_id,
            session_id="session-123",
            correlation_id=correlation_id,
            causation_id=causation_id,
            emitted_at=emitted_at,
            working_directory="/workspace/project",
            git_branch="main",
            hook_source="resume",
        )
        assert event.entity_id == entity_id
        assert event.git_branch == "main"
        assert event.hook_source == "resume"
        assert event.correlation_id == correlation_id
        assert event.causation_id == causation_id
        assert event.emitted_at == emitted_at

    def test_hook_source_validation(self) -> None:
        """Hook source must be valid literal."""
        for hook_source in ["startup", "resume", "clear", "compact"]:
            event = ModelHookSessionStartedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                working_directory="/tmp",
                hook_source=hook_source,  # type: ignore[arg-type]
            )
            assert event.hook_source == hook_source

    def test_invalid_hook_source(self) -> None:
        """Invalid hook source raises validation error."""
        with pytest.raises(ValidationError):
            ModelHookSessionStartedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                working_directory="/tmp",
                hook_source="invalid",  # type: ignore[arg-type]
            )

    def test_frozen_immutable(self) -> None:
        """Events are immutable (frozen)."""
        event = ModelHookSessionStartedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            working_directory="/tmp",
            hook_source="startup",
        )
        with pytest.raises(ValidationError):
            event.session_id = "changed"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        """Extra fields are not allowed."""
        with pytest.raises(ValidationError):
            ModelHookSessionStartedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                working_directory="/tmp",
                hook_source="startup",
                extra_field="not allowed",  # type: ignore[call-arg]
            )


# =============================================================================
# Session Ended Payload Tests
# =============================================================================


class TestModelHookSessionEndedPayload:
    """Tests for session ended event payloads."""

    def test_create_minimal(self) -> None:
        """Create with minimal required fields."""
        entity_id = make_entity_id()
        emitted_at = make_timestamp()
        event = ModelHookSessionEndedPayload(
            entity_id=entity_id,
            session_id="session-123",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=emitted_at,
            reason="clear",
        )
        assert event.entity_id == entity_id
        assert event.session_id == "session-123"
        assert event.emitted_at == emitted_at
        assert event.reason == "clear"
        assert event.duration_seconds is None
        assert event.tools_used_count == 0

    def test_create_full(self) -> None:
        """Create with all fields."""
        event = ModelHookSessionEndedPayload(
            entity_id=make_entity_id(),
            session_id="session-123",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            reason="logout",
            duration_seconds=3600.5,
            tools_used_count=42,
        )
        assert event.reason == "logout"
        assert event.duration_seconds == 3600.5
        assert event.tools_used_count == 42

    def test_reason_validation(self) -> None:
        """Reason must be valid literal."""
        for reason in ["clear", "logout", "prompt_input_exit", "other"]:
            event = ModelHookSessionEndedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                reason=reason,  # type: ignore[arg-type]
            )
            assert event.reason == reason

    def test_required_fields(self) -> None:
        """All ONEX envelope fields are required."""
        with pytest.raises(ValidationError) as exc_info:
            ModelHookSessionEndedPayload(
                # Missing all required fields
                reason="clear",  # type: ignore[call-arg]
            )
        error_str = str(exc_info.value)
        assert "entity_id" in error_str
        assert "session_id" in error_str
        assert "correlation_id" in error_str
        assert "causation_id" in error_str
        assert "emitted_at" in error_str


# =============================================================================
# Prompt Submitted Payload Tests
# =============================================================================


class TestModelHookPromptSubmittedPayload:
    """Tests for prompt submitted event payloads."""

    def test_create_minimal(self) -> None:
        """Create with minimal required fields."""
        entity_id = make_entity_id()
        prompt_id = uuid4()
        emitted_at = make_timestamp()
        event = ModelHookPromptSubmittedPayload(
            entity_id=entity_id,
            session_id="session-123",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=emitted_at,
            prompt_id=prompt_id,
            prompt_preview="Help me with...",
            prompt_length=100,
        )
        assert event.entity_id == entity_id
        assert event.prompt_id == prompt_id
        assert event.emitted_at == emitted_at
        assert event.prompt_preview == "Help me with..."
        assert event.prompt_length == 100
        assert event.detected_intent is None

    def test_create_full(self) -> None:
        """Create with all fields."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="session-123",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="Implement feature X",
            prompt_length=500,
            detected_intent="workflow",
        )
        assert event.detected_intent == "workflow"

    def test_prompt_preview_max_length(self) -> None:
        """Prompt preview is limited to PROMPT_PREVIEW_MAX_LENGTH (100) characters."""
        # Valid at exactly max length
        max_len = PROMPT_PREVIEW_MAX_LENGTH
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="x" * max_len,
            prompt_length=max_len,
        )
        assert len(event.prompt_preview) == max_len

    def test_prompt_preview_auto_truncation(self) -> None:
        """Prompt preview longer than max is auto-truncated with ellipsis."""
        max_len = PROMPT_PREVIEW_MAX_LENGTH
        long_preview = "x" * 200  # Much longer than max
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview=long_preview,
            prompt_length=200,
        )
        # Should be truncated to max_len with "..." suffix
        assert len(event.prompt_preview) == max_len
        assert event.prompt_preview.endswith("...")

    def test_prompt_length_non_negative(self) -> None:
        """Prompt length must be non-negative."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="test",
            prompt_length=0,
        )
        assert event.prompt_length == 0

        with pytest.raises(ValidationError):
            ModelHookPromptSubmittedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                prompt_id=uuid4(),
                prompt_preview="test",
                prompt_length=-1,
            )

    def test_prompt_id_is_required(self) -> None:
        """prompt_id is required."""
        with pytest.raises(ValidationError) as exc_info:
            ModelHookPromptSubmittedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                # Missing prompt_id
                prompt_preview="test",
                prompt_length=4,
            )
        assert "prompt_id" in str(exc_info.value)


# =============================================================================
# Prompt Preview Sanitization Tests
# =============================================================================


class TestPromptPreviewSanitization:
    """Tests for prompt preview privacy sanitization."""

    def test_openai_api_key_redacted(self) -> None:
        """OpenAI API keys (sk-...) are redacted."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="Use OPENAI_API_KEY=sk-1234567890abcdefghij",
            prompt_length=50,
        )
        # The actual secret value must be removed
        assert "sk-1234567890abcdefghij" not in event.prompt_preview
        # Some form of redaction marker should be present
        assert "REDACTED" in event.prompt_preview

    def test_aws_access_key_redacted(self) -> None:
        """AWS access keys (AKIA...) are redacted."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="AWS key: AKIAIOSFODNN7EXAMPLE",
            prompt_length=35,
        )
        assert "AKIAIOSFODNN7EXAMPLE" not in event.prompt_preview
        assert "AKIA***REDACTED***" in event.prompt_preview

    def test_github_token_redacted(self) -> None:
        """GitHub personal access tokens (ghp_...) are redacted."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="Token: ghp_1234567890abcdefghijklmnopqrstuvwxyz",
            prompt_length=50,
        )
        # The actual secret value must be removed
        assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz" not in event.prompt_preview
        # Some form of redaction marker should be present
        assert "REDACTED" in event.prompt_preview

    def test_bearer_token_redacted(self) -> None:
        """Bearer tokens in Authorization headers are redacted."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="Header: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            prompt_length=60,
        )
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in event.prompt_preview
        assert "Bearer ***REDACTED***" in event.prompt_preview

    def test_password_in_url_redacted(self) -> None:
        """Passwords in connection URLs are redacted."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="Connect to postgres://user:secretpass@localhost:5432",
            prompt_length=55,
        )
        assert "secretpass" not in event.prompt_preview
        assert "***REDACTED***@" in event.prompt_preview

    def test_generic_password_field_redacted(self) -> None:
        """Generic password=value patterns are redacted."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="Set password=supersecretvalue123",
            prompt_length=35,
        )
        assert "supersecretvalue123" not in event.prompt_preview
        assert "password=***REDACTED***" in event.prompt_preview

    def test_safe_content_unchanged(self) -> None:
        """Content without secrets passes through unchanged (except truncation)."""
        safe_preview = "Fix the bug in the authentication module"
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview=safe_preview,
            prompt_length=len(safe_preview),
        )
        assert event.prompt_preview == safe_preview

    def test_combined_sanitization_and_truncation(self) -> None:
        """Sanitization and truncation work together correctly."""
        # Long text with a secret near the end
        long_preview = "a" * 80 + " secret=verysecretvalue"
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview=long_preview,
            prompt_length=len(long_preview),
        )
        # Should be sanitized (secret redacted) and truncated
        assert len(event.prompt_preview) == PROMPT_PREVIEW_MAX_LENGTH
        assert "verysecretvalue" not in event.prompt_preview

    def test_slack_token_redacted(self) -> None:
        """Slack tokens (xoxb-...) are redacted."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="Slack: xoxb-1234567890-abcdefghij",
            prompt_length=40,
        )
        assert "xoxb-1234567890-abcdefghij" not in event.prompt_preview
        assert "xox*-***REDACTED***" in event.prompt_preview

    def test_stripe_secret_key_live_redacted(self) -> None:
        """Stripe live secret keys (sk_live_...) are redacted."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="Key: sk_live_51AbCdEfGhIjKlMnOpQrStUv",
            prompt_length=45,
        )
        assert "sk_live_51AbCdEfGhIjKlMnOpQrStUv" not in event.prompt_preview
        assert "stripe_***REDACTED***" in event.prompt_preview

    def test_stripe_publishable_key_test_redacted(self) -> None:
        """Stripe test publishable keys (pk_test_...) are redacted."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="Key: pk_test_51AbCdEfGhIjKlMnOpQrStUv",
            prompt_length=45,
        )
        assert "pk_test_51AbCdEfGhIjKlMnOpQrStUv" not in event.prompt_preview
        assert "stripe_***REDACTED***" in event.prompt_preview

    def test_stripe_restricted_key_live_redacted(self) -> None:
        """Stripe live restricted keys (rk_live_...) are redacted."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="Key: rk_live_51AbCdEfGhIjKlMnOpQrStUv",
            prompt_length=45,
        )
        assert "rk_live_51AbCdEfGhIjKlMnOpQrStUv" not in event.prompt_preview
        assert "stripe_***REDACTED***" in event.prompt_preview

    def test_gcp_api_key_redacted(self) -> None:
        """Google Cloud Platform API keys (AIza...) are redacted."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="GCP: AIzaSyA0123456789abcdefghijklmnopqrstuvwxy",
            prompt_length=55,
        )
        assert "AIzaSyA0123456789abcdefghijklmnopqrstuvwxy" not in event.prompt_preview
        assert "AIza***REDACTED***" in event.prompt_preview

    def test_pem_private_key_redacted(self) -> None:
        """Generic PEM private key headers are redacted."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="Key: -----BEGIN PRIVATE KEY-----",
            prompt_length=40,
        )
        assert "-----BEGIN PRIVATE KEY-----" not in event.prompt_preview
        assert "-----BEGIN ***REDACTED*** PRIVATE KEY-----" in event.prompt_preview

    def test_pem_rsa_private_key_redacted(self) -> None:
        """RSA PEM private key headers are redacted."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="Key: -----BEGIN RSA PRIVATE KEY-----",
            prompt_length=45,
        )
        assert "-----BEGIN RSA PRIVATE KEY-----" not in event.prompt_preview
        assert "-----BEGIN ***REDACTED*** PRIVATE KEY-----" in event.prompt_preview

    def test_pem_ec_private_key_redacted(self) -> None:
        """EC PEM private key headers are redacted."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="Key: -----BEGIN EC PRIVATE KEY-----",
            prompt_length=45,
        )
        assert "-----BEGIN EC PRIVATE KEY-----" not in event.prompt_preview
        assert "-----BEGIN ***REDACTED*** PRIVATE KEY-----" in event.prompt_preview

    def test_pem_encrypted_private_key_redacted(self) -> None:
        """Encrypted PEM private key headers are redacted."""
        event = ModelHookPromptSubmittedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="-----BEGIN ENCRYPTED PRIVATE KEY-----",
            prompt_length=40,
        )
        assert "-----BEGIN ENCRYPTED PRIVATE KEY-----" not in event.prompt_preview
        assert "-----BEGIN ***REDACTED*** PRIVATE KEY-----" in event.prompt_preview


# =============================================================================
# Tool Executed Payload Tests
# =============================================================================


class TestModelHookToolExecutedPayload:
    """Tests for tool executed event payloads."""

    def test_create_minimal(self) -> None:
        """Create with minimal required fields."""
        entity_id = make_entity_id()
        tool_execution_id = uuid4()
        emitted_at = make_timestamp()
        event = ModelHookToolExecutedPayload(
            entity_id=entity_id,
            session_id="session-123",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=emitted_at,
            tool_execution_id=tool_execution_id,
            tool_name="Read",
        )
        assert event.entity_id == entity_id
        assert event.tool_execution_id == tool_execution_id
        assert event.emitted_at == emitted_at
        assert event.tool_name == "Read"
        assert event.success is True
        assert event.duration_ms is None
        assert event.summary is None

    def test_create_full(self) -> None:
        """Create with all fields."""
        event = ModelHookToolExecutedPayload(
            entity_id=make_entity_id(),
            session_id="session-123",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            tool_execution_id=uuid4(),
            tool_name="Bash",
            success=False,
            duration_ms=150,
            summary="Command failed with exit code 1",
        )
        assert event.success is False
        assert event.duration_ms == 150
        assert event.summary == "Command failed with exit code 1"

    def test_summary_max_length(self) -> None:
        """Summary is limited to 500 characters."""
        # Valid at exactly 500
        event = ModelHookToolExecutedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            tool_execution_id=uuid4(),
            tool_name="Test",
            summary="x" * 500,
        )
        assert len(event.summary) == 500  # type: ignore[arg-type]

        # Invalid at 501
        with pytest.raises(ValidationError):
            ModelHookToolExecutedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                tool_execution_id=uuid4(),
                tool_name="Test",
                summary="x" * 501,
            )

    def test_tool_execution_id_is_required(self) -> None:
        """tool_execution_id is required."""
        with pytest.raises(ValidationError) as exc_info:
            ModelHookToolExecutedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                # Missing tool_execution_id
                tool_name="Read",
            )
        assert "tool_execution_id" in str(exc_info.value)


# =============================================================================
# Causation Chain Tests
# =============================================================================


class TestCausationChain:
    """Tests for causation chain tracking (ONEX pattern)."""

    def test_causation_chain_linkage(self) -> None:
        """Events can form a causation chain using entity_id -> causation_id."""
        session_entity_id = make_entity_id()
        correlation_id = uuid4()
        synthetic_trigger_id = uuid4()  # External trigger

        # Parent event (session start)
        parent = ModelHookSessionStartedPayload(
            entity_id=session_entity_id,
            session_id="test",
            correlation_id=correlation_id,
            causation_id=synthetic_trigger_id,  # Caused by external trigger
            emitted_at=make_timestamp(),
            working_directory="/tmp",
            hook_source="startup",
        )

        # Child event (prompt submitted) - links to parent via causation_id
        prompt_entity_id = uuid4()
        child = ModelHookPromptSubmittedPayload(
            entity_id=prompt_entity_id,
            session_id="test",
            correlation_id=correlation_id,  # Same correlation
            causation_id=parent.entity_id,  # Caused by session start
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="Hello",
            prompt_length=5,
        )

        assert child.causation_id == parent.entity_id
        assert child.correlation_id == parent.correlation_id

    def test_causation_chain_multiple_events(self) -> None:
        """Multiple events can chain together via causation_id."""
        correlation_id = uuid4()
        synthetic_trigger = uuid4()

        # Event 1: Session started
        event1_entity_id = uuid4()
        event1 = ModelHookSessionStartedPayload(
            entity_id=event1_entity_id,
            session_id="test",
            correlation_id=correlation_id,
            causation_id=synthetic_trigger,
            emitted_at=make_timestamp(),
            working_directory="/tmp",
            hook_source="startup",
        )

        # Event 2: Prompt submitted (caused by session)
        event2_entity_id = uuid4()
        event2 = ModelHookPromptSubmittedPayload(
            entity_id=event2_entity_id,
            session_id="test",
            correlation_id=correlation_id,
            causation_id=event1.entity_id,
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="Hello",
            prompt_length=5,
        )

        # Event 3: Tool executed (caused by prompt)
        event3 = ModelHookToolExecutedPayload(
            entity_id=uuid4(),
            session_id="test",
            correlation_id=correlation_id,
            causation_id=event2.entity_id,
            emitted_at=make_timestamp(),
            tool_execution_id=uuid4(),
            tool_name="Read",
        )

        # Verify chain
        assert event2.causation_id == event1.entity_id
        assert event3.causation_id == event2.entity_id
        # All share same correlation
        assert event1.correlation_id == event2.correlation_id == event3.correlation_id


# =============================================================================
# Event Envelope Tests
# =============================================================================


class TestModelHookEventEnvelope:
    """Tests for the event envelope wrapper."""

    def test_create_envelope(self) -> None:
        """Create envelope with payload."""
        payload = ModelHookSessionStartedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            working_directory="/tmp",
            hook_source="startup",
        )
        envelope = ModelHookEventEnvelope(
            event_type="hook.session.started",
            payload=payload,
        )
        assert envelope.event_type == "hook.session.started"
        assert envelope.schema_version == "1.0.0"
        assert envelope.source == "omniclaude"
        assert envelope.payload == payload

    def test_envelope_event_types(self) -> None:
        """Envelope accepts all valid event types."""
        payloads_and_types = [
            (
                ModelHookSessionStartedPayload(
                    entity_id=make_entity_id(),
                    session_id="test",
                    correlation_id=make_correlation_id(),
                    causation_id=make_causation_id(),
                    emitted_at=make_timestamp(),
                    working_directory="/tmp",
                    hook_source="startup",
                ),
                "hook.session.started",
            ),
            (
                ModelHookSessionEndedPayload(
                    entity_id=make_entity_id(),
                    session_id="test",
                    correlation_id=make_correlation_id(),
                    causation_id=make_causation_id(),
                    emitted_at=make_timestamp(),
                    reason="clear",
                ),
                "hook.session.ended",
            ),
            (
                ModelHookPromptSubmittedPayload(
                    entity_id=make_entity_id(),
                    session_id="test",
                    correlation_id=make_correlation_id(),
                    causation_id=make_causation_id(),
                    emitted_at=make_timestamp(),
                    prompt_id=uuid4(),
                    prompt_preview="test",
                    prompt_length=4,
                ),
                "hook.prompt.submitted",
            ),
            (
                ModelHookToolExecutedPayload(
                    entity_id=make_entity_id(),
                    session_id="test",
                    correlation_id=make_correlation_id(),
                    causation_id=make_causation_id(),
                    emitted_at=make_timestamp(),
                    tool_execution_id=uuid4(),
                    tool_name="Read",
                ),
                "hook.tool.executed",
            ),
        ]
        for payload, event_type in payloads_and_types:
            envelope = ModelHookEventEnvelope(
                event_type=event_type,  # type: ignore[arg-type]
                payload=payload,
            )
            assert envelope.event_type == event_type

    def test_envelope_frozen(self) -> None:
        """Envelope is immutable."""
        envelope = ModelHookEventEnvelope(
            event_type="hook.session.started",
            payload=ModelHookSessionStartedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                working_directory="/tmp",
                hook_source="startup",
            ),
        )
        with pytest.raises(ValidationError):
            envelope.event_type = "hook.session.ended"  # type: ignore[misc]


# =============================================================================
# Topic Tests
# =============================================================================


class TestTopics:
    """Tests for topic names and helpers."""

    def test_topic_base_names(self) -> None:
        """Topic base names are defined correctly."""
        assert TopicBase.SESSION_STARTED == "omniclaude.session.started.v1"
        assert TopicBase.SESSION_ENDED == "omniclaude.session.ended.v1"
        assert TopicBase.PROMPT_SUBMITTED == "omniclaude.prompt.submitted.v1"
        assert TopicBase.TOOL_EXECUTED == "omniclaude.tool.executed.v1"
        assert TopicBase.LEARNING_PATTERN == "omniclaude.learning.pattern.v1"

    def test_build_topic(self) -> None:
        """Build full topic name from prefix and base."""
        topic = build_topic("dev", TopicBase.SESSION_STARTED)
        assert topic == "dev.omniclaude.session.started.v1"

        topic = build_topic("prod", TopicBase.TOOL_EXECUTED)
        assert topic == "prod.omniclaude.tool.executed.v1"

    def test_build_topic_empty_prefix_raises(self) -> None:
        """Empty prefix raises ValueError."""
        with pytest.raises(ValueError, match="prefix must be a non-empty string"):
            build_topic("", TopicBase.SESSION_STARTED)

    def test_build_topic_whitespace_prefix_raises(self) -> None:
        """Whitespace-only prefix raises ValueError."""
        with pytest.raises(ValueError, match="prefix must be a non-empty string"):
            build_topic("   ", TopicBase.SESSION_STARTED)

    def test_build_topic_none_prefix_raises(self) -> None:
        """None prefix raises ValueError with clear message."""
        with pytest.raises(ValueError, match="prefix must not be None"):
            build_topic(None, TopicBase.SESSION_STARTED)  # type: ignore[arg-type]

    def test_build_topic_empty_base_raises(self) -> None:
        """Empty base raises ValueError."""
        with pytest.raises(ValueError, match="base must be a non-empty string"):
            build_topic("dev", "")

    def test_build_topic_none_base_raises(self) -> None:
        """None base raises ValueError with clear message."""
        with pytest.raises(ValueError, match="base must not be None"):
            build_topic("dev", None)  # type: ignore[arg-type]

    def test_build_topic_whitespace_base_raises(self) -> None:
        """Whitespace-only base raises ValueError."""
        with pytest.raises(ValueError, match="base must be a non-empty string"):
            build_topic("dev", "   ")

    def test_build_topic_strips_whitespace(self) -> None:
        """Prefix and base whitespace is stripped."""
        topic = build_topic("  dev  ", "  omniclaude.test.v1  ")
        assert topic == "dev.omniclaude.test.v1"

    def test_build_topic_rejects_leading_dot_in_base(self) -> None:
        """Base with leading dot produces malformed topic (rejected)."""
        with pytest.raises(ValueError, match="consecutive dots"):
            build_topic("dev", ".omniclaude.test.v1")

    def test_build_topic_rejects_trailing_dot_in_base(self) -> None:
        """Base with trailing dot produces malformed topic (rejected)."""
        with pytest.raises(ValueError, match="must not end with a dot"):
            build_topic("dev", "omniclaude.test.v1.")

    def test_build_topic_rejects_consecutive_dots(self) -> None:
        """Topic with consecutive dots is rejected."""
        with pytest.raises(ValueError, match="consecutive dots"):
            build_topic("dev", "omniclaude..test.v1")

    def test_build_topic_valid_characters(self) -> None:
        """Valid topic names with allowed characters."""
        # Alphanumeric, underscores, hyphens are allowed
        topic = build_topic("dev-test_1", "omniclaude.session_started.v1")
        assert topic == "dev-test_1.omniclaude.session_started.v1"

    def test_build_topic_rejects_special_characters(self) -> None:
        """Topic segments with special characters are rejected."""
        with pytest.raises(ValueError, match="invalid characters"):
            build_topic("dev@test", TopicBase.SESSION_STARTED)

        with pytest.raises(ValueError, match="invalid characters"):
            build_topic("dev", "omniclaude.test#v1")


# =============================================================================
# Serialization Tests
# =============================================================================


class TestSerialization:
    """Tests for JSON serialization."""

    def test_serialize_to_json(self) -> None:
        """Event can be serialized to JSON."""
        entity_id = make_entity_id()
        event = ModelHookSessionStartedPayload(
            entity_id=entity_id,
            session_id="test-123",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            working_directory="/workspace",
            hook_source="startup",
        )
        json_str = event.model_dump_json()
        assert '"session_id":"test-123"' in json_str
        assert f'"entity_id":"{entity_id}"' in json_str
        assert '"emitted_at"' in json_str

    def test_deserialize_from_json(self) -> None:
        """Event can be deserialized from JSON."""
        entity_id = str(uuid4())
        correlation_id = str(uuid4())
        causation_id = str(uuid4())
        emitted_at = datetime.now(UTC).isoformat()
        json_str = (
            f'{{"entity_id":"{entity_id}",'
            f'"session_id":"test",'
            f'"correlation_id":"{correlation_id}",'
            f'"causation_id":"{causation_id}",'
            f'"emitted_at":"{emitted_at}",'
            f'"working_directory":"/tmp",'
            f'"hook_source":"startup"}}'
        )
        event = ModelHookSessionStartedPayload.model_validate_json(json_str)
        assert event.session_id == "test"
        assert event.working_directory == "/tmp"
        assert str(event.entity_id) == entity_id

    def test_roundtrip_serialization(self) -> None:
        """Event survives JSON roundtrip."""
        entity_id = make_entity_id()
        correlation_id = make_correlation_id()
        causation_id = make_causation_id()
        emitted_at = make_timestamp()
        prompt_id = uuid4()

        original = ModelHookPromptSubmittedPayload(
            entity_id=entity_id,
            session_id="test",
            correlation_id=correlation_id,
            causation_id=causation_id,
            emitted_at=emitted_at,
            prompt_id=prompt_id,
            prompt_preview="Hello world",
            prompt_length=11,
            detected_intent="greeting",
        )
        json_str = original.model_dump_json()
        restored = ModelHookPromptSubmittedPayload.model_validate_json(json_str)

        assert restored.entity_id == original.entity_id
        assert restored.session_id == original.session_id
        assert restored.correlation_id == original.correlation_id
        assert restored.causation_id == original.causation_id
        assert restored.emitted_at == original.emitted_at
        assert restored.prompt_id == original.prompt_id
        assert restored.prompt_preview == original.prompt_preview
        assert restored.prompt_length == original.prompt_length
        assert restored.detected_intent == original.detected_intent

    def test_serialization_preserves_timezone(self) -> None:
        """Serialization preserves timezone information."""
        emitted_at = datetime(2025, 1, 19, 12, 0, 0, tzinfo=UTC)
        event = ModelHookSessionStartedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=emitted_at,
            working_directory="/tmp",
            hook_source="startup",
        )
        json_str = event.model_dump_json()
        restored = ModelHookSessionStartedPayload.model_validate_json(json_str)

        # Restored timestamp should still be timezone-aware
        assert restored.emitted_at.tzinfo is not None
        # And equal to original
        assert restored.emitted_at == emitted_at


# =============================================================================
# Entity ID Partition Key Tests
# =============================================================================


class TestEntityIdAsPartitionKey:
    """Tests for entity_id usage as Kafka partition key."""

    def test_entity_id_is_uuid(self) -> None:
        """entity_id is a UUID type."""
        entity_id = make_entity_id()
        event = ModelHookSessionStartedPayload(
            entity_id=entity_id,
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            working_directory="/tmp",
            hook_source="startup",
        )
        assert isinstance(event.entity_id, UUID)

    def test_entity_id_from_string(self) -> None:
        """entity_id can be created from string UUID."""
        entity_id_str = "12345678-1234-5678-1234-567812345678"
        event = ModelHookSessionStartedPayload(
            entity_id=entity_id_str,  # type: ignore[arg-type]
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            working_directory="/tmp",
            hook_source="startup",
        )
        assert str(event.entity_id) == entity_id_str

    def test_entity_id_invalid_format(self) -> None:
        """Invalid entity_id format raises validation error."""
        with pytest.raises(ValidationError):
            ModelHookSessionStartedPayload(
                entity_id="not-a-valid-uuid",  # type: ignore[arg-type]
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                working_directory="/tmp",
                hook_source="startup",
            )

    def test_different_events_have_unique_entity_ids(self) -> None:
        """Different events have unique entity_ids (partition keys)."""
        session_id = "shared-session"
        correlation_id = uuid4()
        synthetic_trigger = uuid4()

        event1_entity_id = uuid4()
        event1 = ModelHookSessionStartedPayload(
            entity_id=event1_entity_id,
            session_id=session_id,
            correlation_id=correlation_id,
            causation_id=synthetic_trigger,
            emitted_at=make_timestamp(),
            working_directory="/tmp",
            hook_source="startup",
        )

        event2_entity_id = uuid4()
        event2 = ModelHookPromptSubmittedPayload(
            entity_id=event2_entity_id,
            session_id=session_id,
            correlation_id=correlation_id,
            causation_id=event1.entity_id,
            emitted_at=make_timestamp(),
            prompt_id=uuid4(),
            prompt_preview="test",
            prompt_length=4,
        )

        # Same session and correlation, but different entity_ids
        assert event1.session_id == event2.session_id
        assert event1.correlation_id == event2.correlation_id
        assert event1.entity_id != event2.entity_id


# =============================================================================
# HookEventType Enum Tests
# =============================================================================


class TestHookEventType:
    """Tests for HookEventType StrEnum."""

    def test_hook_event_type_values(self) -> None:
        """HookEventType has correct string values."""
        assert HookEventType.SESSION_STARTED == "hook.session.started"
        assert HookEventType.SESSION_ENDED == "hook.session.ended"
        assert HookEventType.PROMPT_SUBMITTED == "hook.prompt.submitted"
        assert HookEventType.TOOL_EXECUTED == "hook.tool.executed"

    def test_hook_event_type_is_str(self) -> None:
        """HookEventType values are strings (StrEnum)."""
        assert isinstance(HookEventType.SESSION_STARTED, str)
        assert isinstance(HookEventType.SESSION_ENDED, str)
        assert isinstance(HookEventType.PROMPT_SUBMITTED, str)
        assert isinstance(HookEventType.TOOL_EXECUTED, str)

    def test_hook_event_type_string_comparison(self) -> None:
        """HookEventType can be compared to strings."""
        assert HookEventType.SESSION_STARTED == "hook.session.started"
        assert HookEventType.SESSION_ENDED == "hook.session.ended"

    def test_hook_event_type_in_envelope(self) -> None:
        """HookEventType can be used in envelope event_type field."""
        payload = ModelHookSessionStartedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            working_directory="/tmp",
            hook_source="startup",
        )
        envelope = ModelHookEventEnvelope(
            event_type=HookEventType.SESSION_STARTED,
            payload=payload,
        )
        assert envelope.event_type == HookEventType.SESSION_STARTED
        assert envelope.event_type == "hook.session.started"


# =============================================================================
# Event Type Payload Validation Tests
# =============================================================================


class TestEventTypePayloadValidation:
    """Tests for model_validator that ensures event_type matches payload type."""

    def test_mismatched_event_type_and_payload_raises(self) -> None:
        """Mismatched event_type and payload raises ValidationError."""
        # Create a session ended payload
        ended_payload = ModelHookSessionEndedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            reason="clear",
        )
        # Try to create envelope with wrong event_type
        with pytest.raises(ValidationError) as exc_info:
            ModelHookEventEnvelope(
                event_type=HookEventType.SESSION_STARTED,  # Wrong type!
                payload=ended_payload,
            )
        assert "requires payload type ModelHookSessionStartedPayload" in str(
            exc_info.value
        )

    def test_all_valid_combinations(self) -> None:
        """All valid event_type + payload combinations work."""
        valid_combinations = [
            (
                HookEventType.SESSION_STARTED,
                ModelHookSessionStartedPayload(
                    entity_id=make_entity_id(),
                    session_id="test",
                    correlation_id=make_correlation_id(),
                    causation_id=make_causation_id(),
                    emitted_at=make_timestamp(),
                    working_directory="/tmp",
                    hook_source="startup",
                ),
            ),
            (
                HookEventType.SESSION_ENDED,
                ModelHookSessionEndedPayload(
                    entity_id=make_entity_id(),
                    session_id="test",
                    correlation_id=make_correlation_id(),
                    causation_id=make_causation_id(),
                    emitted_at=make_timestamp(),
                    reason="clear",
                ),
            ),
            (
                HookEventType.PROMPT_SUBMITTED,
                ModelHookPromptSubmittedPayload(
                    entity_id=make_entity_id(),
                    session_id="test",
                    correlation_id=make_correlation_id(),
                    causation_id=make_causation_id(),
                    emitted_at=make_timestamp(),
                    prompt_id=uuid4(),
                    prompt_preview="test",
                    prompt_length=4,
                ),
            ),
            (
                HookEventType.TOOL_EXECUTED,
                ModelHookToolExecutedPayload(
                    entity_id=make_entity_id(),
                    session_id="test",
                    correlation_id=make_correlation_id(),
                    causation_id=make_causation_id(),
                    emitted_at=make_timestamp(),
                    tool_execution_id=uuid4(),
                    tool_name="Read",
                ),
            ),
        ]
        for event_type, payload in valid_combinations:
            envelope = ModelHookEventEnvelope(
                event_type=event_type,
                payload=payload,
            )
            assert envelope.event_type == event_type


# =============================================================================
# Duration Bounds Tests
# =============================================================================


class TestDurationBounds:
    """Tests for duration field upper bounds."""

    def test_duration_seconds_max_30_days(self) -> None:
        """duration_seconds has upper bound of 30 days (2,592,000 seconds)."""
        # Valid: exactly 30 days
        max_duration = 86400 * 30  # 2,592,000 seconds
        event = ModelHookSessionEndedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            reason="clear",
            duration_seconds=max_duration,
        )
        assert event.duration_seconds == max_duration

        # Invalid: over 30 days
        with pytest.raises(ValidationError) as exc_info:
            ModelHookSessionEndedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                reason="clear",
                duration_seconds=max_duration + 1,
            )
        assert "duration_seconds" in str(exc_info.value)

    def test_duration_ms_max_1_hour(self) -> None:
        """duration_ms has upper bound of 1 hour (3,600,000 milliseconds)."""
        # Valid: exactly 1 hour
        max_duration = 3600000  # 1 hour in milliseconds
        event = ModelHookToolExecutedPayload(
            entity_id=make_entity_id(),
            session_id="test",
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=make_timestamp(),
            tool_execution_id=uuid4(),
            tool_name="Bash",
            duration_ms=max_duration,
        )
        assert event.duration_ms == max_duration

        # Invalid: over 1 hour
        with pytest.raises(ValidationError) as exc_info:
            ModelHookToolExecutedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                tool_execution_id=uuid4(),
                tool_name="Bash",
                duration_ms=max_duration + 1,
            )
        assert "duration_ms" in str(exc_info.value)

    def test_duration_seconds_non_negative(self) -> None:
        """duration_seconds must be non-negative."""
        with pytest.raises(ValidationError):
            ModelHookSessionEndedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                reason="clear",
                duration_seconds=-1.0,
            )

    def test_duration_ms_non_negative(self) -> None:
        """duration_ms must be non-negative."""
        with pytest.raises(ValidationError):
            ModelHookToolExecutedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                tool_execution_id=uuid4(),
                tool_name="Bash",
                duration_ms=-1,
            )
