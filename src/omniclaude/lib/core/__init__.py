"""Core functionality for Claude artifacts.

This package contains core components for the OmniClaude agent system:
- Manifest injection: Dynamic context injection via event bus
- Agent routing: Smart agent selection with confidence scoring
- Action logging: Structured logging for agent actions
- Intelligence gathering: RAG integration for pattern discovery
- Correlation tracking: Request tracing across services
- Error handling: ONEX-compliant error classes

Core Modules:
    manifest_injector: Dynamic system manifest generation
    routing_event_client: Kafka-based agent routing
    action_logger: Action event logging with Slack notifications
    action_event_publisher: Kafka event publishing
    intelligence_cache: Valkey-backed caching
    intelligence_gatherer: RAG integration
    intelligence_event_client: Kafka-based intelligence discovery
    agent_router: Agent selection with fuzzy matching
    trigger_matcher: Trigger-based agent matching
    confidence_scorer: Confidence score calculation
    agent_transformer: Polymorphic agent transformation
    capability_index: Agent capability indexing
    result_cache: In-memory result caching
"""

# Import errors from agents.lib.errors (canonical location)
# Re-export for unified access via claude.lib.core
try:
    from agents.lib.errors import (
        CoreErrorCode,
        EnumCoreErrorCode,
        ModelOnexError,
        OnexError,
    )

    _errors_available = True
except ImportError:
    # Fallback: Define minimal error classes if agents.lib.errors not available
    from enum import Enum
    from typing import Any

    class _FallbackEnumCoreErrorCode(str, Enum):
        """Core error codes for ONEX operations."""

        VALIDATION_ERROR = "VALIDATION_ERROR"
        CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
        OPERATION_FAILED = "OPERATION_FAILED"
        EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
        FILE_NOT_FOUND = "FILE_NOT_FOUND"
        IO_ERROR = "IO_ERROR"

    EnumCoreErrorCode = _FallbackEnumCoreErrorCode
    CoreErrorCode = _FallbackEnumCoreErrorCode

    class _FallbackOnexError(Exception):
        """Base exception class for ONEX operations."""

        def __init__(
            self,
            code: _FallbackEnumCoreErrorCode,
            message: str,
            details: dict[str, Any] | None = None,
        ) -> None:
            self.code = code
            self.error_code = code
            self.message = message
            self.details = details or {}
            super().__init__(message)

    OnexError = _FallbackOnexError
    ModelOnexError = _FallbackOnexError
    _errors_available = False

# Event Publishing (Kafka integration for agent actions)
from .action_event_publisher import (
    close_producer,
    publish_action_event,
    publish_decision,
    publish_error,
    publish_success,
    publish_tool_call,
)

# Action Logging
from .action_logger import ActionLogger, ToolCallContext, log_action
from .agent_router import AgentRecommendation, AgentRouter, RoutingTiming
from .agent_transformer import AgentIdentity, AgentTransformer
from .capability_index import CapabilityIndex
from .confidence_scorer import ConfidenceScore, ConfidenceScorer

# Intelligence
from .intelligence_cache import IntelligenceCache
from .intelligence_event_client import (
    IntelligenceEventClient,
    IntelligenceEventClientContext,
)
from .intelligence_gatherer import IntelligenceGatherer
from .manifest_injector import ManifestInjector, inject_manifest
from .result_cache import ResultCache

# Routing
from .routing_event_client import (
    RoutingEventClient,
    RoutingEventClientContext,
    route_via_events,
)

# Agent Components
from .trigger_matcher import TriggerMatcher

__all__ = [
    # Error Handling
    "CoreErrorCode",
    "EnumCoreErrorCode",
    "ModelOnexError",
    "OnexError",
    "_errors_available",
    # Manifest Injection
    "ManifestInjector",
    "inject_manifest",
    # Routing
    "RoutingEventClient",
    "RoutingEventClientContext",
    "route_via_events",
    "AgentRouter",
    "AgentRecommendation",
    "RoutingTiming",
    # Action Logging
    "ActionLogger",
    "ToolCallContext",
    "log_action",
    "publish_action_event",
    "publish_tool_call",
    "publish_decision",
    "publish_error",
    "publish_success",
    "close_producer",
    # Intelligence
    "IntelligenceCache",
    "IntelligenceGatherer",
    "IntelligenceEventClient",
    "IntelligenceEventClientContext",
    # Agent Components
    "TriggerMatcher",
    "ConfidenceScorer",
    "ConfidenceScore",
    "AgentTransformer",
    "AgentIdentity",
    "CapabilityIndex",
    "ResultCache",
]
