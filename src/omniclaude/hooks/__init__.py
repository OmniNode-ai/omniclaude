# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""OmniClaude hooks - ONEX-compliant event schemas and topic definitions for Claude Code hooks.

This module provides:
- ONEX-compatible event payload schemas following omnibase patterns
- Topic base names and helpers for Kafka/Redpanda integration
- YAML contract definitions for hook events

Event Payload Models:
    - ModelHookSessionStartedPayload: Emitted when a Claude Code session starts
    - ModelHookSessionEndedPayload: Emitted when a Claude Code session ends
    - ModelHookPromptSubmittedPayload: Emitted when user submits a prompt
    - ModelHookToolExecutedPayload: Emitted after tool execution completes

All payload models follow ONEX patterns:
    - entity_id: UUID partition key for Kafka ordering
    - correlation_id: UUID for distributed tracing
    - causation_id: UUID for event chain tracking
    - emitted_at: Explicit timezone-aware timestamp (no default_factory!)

Example:
    >>> from datetime import UTC, datetime
    >>> from uuid import uuid4
    >>> from omniclaude.hooks import ModelHookSessionStartedPayload, TopicBase, build_topic
    >>>
    >>> session_id = uuid4()
    >>> event = ModelHookSessionStartedPayload(
    ...     entity_id=session_id,
    ...     session_id=str(session_id),
    ...     correlation_id=session_id,
    ...     causation_id=uuid4(),
    ...     emitted_at=datetime.now(UTC),
    ...     working_directory="/workspace/project",
    ...     hook_source="startup",
    ... )
    >>> topic = build_topic("dev", TopicBase.SESSION_STARTED)
    >>> # Publish event.model_dump_json() to topic
"""

from __future__ import annotations

from omniclaude.hooks.context_config import ContextInjectionConfig
from omniclaude.hooks.contracts import (
    CONTRACT_PROMPT_SUBMITTED,
    CONTRACT_SESSION_ENDED,
    CONTRACT_SESSION_STARTED,
    CONTRACT_TOOL_EXECUTED,
    CONTRACTS_DIR,
)
from omniclaude.hooks.handler_context_injection import (
    HandlerContextInjection,
    ModelInjectionResult,
    ModelPatternRecord,
    PatternConnectionError,
    PatternPersistenceError,
    inject_patterns,
    inject_patterns_sync,
)
from omniclaude.hooks.handler_event_emitter import (
    emit_hook_event,
    emit_prompt_submitted,
    emit_session_ended,
    emit_session_started,
    emit_tool_executed,
)
from omniclaude.hooks.models import ModelEventPublishResult
from omniclaude.hooks.schemas import (
    ContextSource,
    HookEventType,
    ModelHookContextInjectedPayload,
    ModelHookEventEnvelope,
    ModelHookPayload,
    ModelHookPromptSubmittedPayload,
    ModelHookSessionEndedPayload,
    ModelHookSessionStartedPayload,
    ModelHookToolExecutedPayload,
    sanitize_text,
)
from omniclaude.hooks.topics import TopicBase, build_topic

__all__ = [
    # Configuration
    "ContextInjectionConfig",
    # Event type enum
    "HookEventType",
    # Payload models (ONEX-compliant)
    "ModelHookSessionStartedPayload",
    "ModelHookSessionEndedPayload",
    "ModelHookPromptSubmittedPayload",
    "ModelHookToolExecutedPayload",
    "ModelHookContextInjectedPayload",
    # Context source enum
    "ContextSource",
    # Output models
    "ModelEventPublishResult",
    # Envelope and types
    "ModelHookEventEnvelope",
    "ModelHookPayload",
    # Sanitization utilities
    "sanitize_text",
    # Topics
    "TopicBase",
    "build_topic",
    # Event emission functions (OMN-1400)
    "emit_hook_event",
    "emit_session_started",
    "emit_session_ended",
    "emit_prompt_submitted",
    "emit_tool_executed",
    # Contracts
    "CONTRACTS_DIR",
    "CONTRACT_SESSION_STARTED",
    "CONTRACT_SESSION_ENDED",
    "CONTRACT_PROMPT_SUBMITTED",
    "CONTRACT_TOOL_EXECUTED",
    # Context injection handler (OMN-1403)
    "HandlerContextInjection",
    "ModelPatternRecord",  # API transfer model (8 fields) - canonical for context injection
    "ModelInjectionResult",
    "inject_patterns",
    "inject_patterns_sync",
    # Pattern persistence exceptions (OMN-1403)
    "PatternPersistenceError",  # Base error for persistence operations
    "PatternConnectionError",  # Connection error (extends PatternPersistenceError)
]
