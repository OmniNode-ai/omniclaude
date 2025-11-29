"""
Agent Routing Library - Phase 1
================================

Provides fuzzy matching, confidence scoring, and intelligent agent routing
for the agent-workflow-coordinator system.

Components:
- trigger_matcher: Fuzzy trigger matching with scoring
- confidence_scorer: Multi-component confidence calculation
- capability_index: In-memory agent capability indexing
- result_cache: Result caching with TTL
- agent_router: Main routing orchestration
- errors: ONEX-compliant error handling

DEPRECATION NOTICE
==================
This module re-exports from claude.lib.core for backwards compatibility.
Please update imports to use claude.lib.core directly:

    # OLD (deprecated)
    from agents.lib import ManifestInjector
    from agents.lib import AgentRouter

    # NEW (preferred)
    from claude.lib.core import ManifestInjector
    from claude.lib.core import AgentRouter
"""

__version__ = "1.0.0"
__author__ = "Archon Agent Coordination System"

# Re-export errors from local module (canonical location)
from .errors import CoreErrorCode, EnumCoreErrorCode, ModelOnexError, OnexError


# Re-export from claude.lib.core for backwards compatibility
# These provide the canonical implementations
_claude_lib_available = False
try:
    from claude.lib.core import (
        # Action Logging
        ActionLogger,
        AgentIdentity,
        AgentRecommendation,
        AgentRouter,
        AgentTransformer,
        CapabilityIndex,
        ConfidenceScore,
        ConfidenceScorer,
        # Intelligence
        IntelligenceCache,
        IntelligenceEventClient,
        IntelligenceEventClientContext,
        IntelligenceGatherer,
        # Manifest Injection
        ManifestInjector,
        ResultCache,
        # Routing
        RoutingEventClient,
        RoutingEventClientContext,
        RoutingTiming,
        ToolCallContext,
        # Agent Components
        TriggerMatcher,
        close_producer,
        inject_manifest,
        log_action,
        publish_action_event,
        publish_decision,
        publish_error,
        publish_success,
        publish_tool_call,
        route_via_events,
    )

    _claude_lib_available = True
except ImportError:
    # claude.lib.core not yet installed or available
    # Fall back to local implementations
    from .agent_router import AgentRecommendation, AgentRouter
    from .capability_index import CapabilityIndex
    from .confidence_scorer import ConfidenceScore, ConfidenceScorer
    from .result_cache import ResultCache
    from .trigger_matcher import TriggerMatcher

    # These are only available from claude.lib.core
    # Set to None to indicate unavailability
    ManifestInjector = None
    inject_manifest = None
    RoutingEventClient = None
    RoutingEventClientContext = None
    route_via_events = None
    RoutingTiming = None
    ActionLogger = None
    ToolCallContext = None
    log_action = None
    publish_action_event = None
    publish_tool_call = None
    publish_decision = None
    publish_error = None
    publish_success = None
    close_producer = None
    IntelligenceCache = None
    IntelligenceGatherer = None
    IntelligenceEventClient = None
    IntelligenceEventClientContext = None
    AgentTransformer = None
    AgentIdentity = None


__all__ = [
    # Error Handling (always available from .errors)
    "CoreErrorCode",
    "EnumCoreErrorCode",
    "ModelOnexError",
    "OnexError",
    # Core routing (always available)
    "AgentRecommendation",
    "AgentRouter",
    "CapabilityIndex",
    "ConfidenceScore",
    "ConfidenceScorer",
    "ResultCache",
    "TriggerMatcher",
    # Manifest Injection (from claude.lib.core)
    "ManifestInjector",
    "inject_manifest",
    # Routing Event Client (from claude.lib.core)
    "RoutingEventClient",
    "RoutingEventClientContext",
    "route_via_events",
    "RoutingTiming",
    # Action Logging (from claude.lib.core)
    "ActionLogger",
    "ToolCallContext",
    "log_action",
    "publish_action_event",
    "publish_tool_call",
    "publish_decision",
    "publish_error",
    "publish_success",
    "close_producer",
    # Intelligence (from claude.lib.core)
    "IntelligenceCache",
    "IntelligenceGatherer",
    "IntelligenceEventClient",
    "IntelligenceEventClientContext",
    # Agent Components (from claude.lib.core)
    "AgentTransformer",
    "AgentIdentity",
    # Availability flag
    "_claude_lib_available",
]
