"""
Agent Router - Phase 1
======================

Main orchestration component that ties all Phase 1 features together.

Flow:
1. Check for explicit agent request (@agent-name)
2. Check cache for previous results
3. Fuzzy trigger matching with scoring
4. Comprehensive confidence scoring
5. Sort and rank recommendations
6. Cache results
7. Return top N recommendations

Async Event-Driven Routing:
- route_async() method provides async event-driven routing via Kafka
- Integrates with routing_event_client for distributed routing
- Falls back to local synchronous routing on failure

Performance Targets:
- Total routing time: <100ms
- Cache hit: <5ms
- Cache miss: <100ms
- Async event routing: <500ms (includes network overhead)
"""

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

# ONEX-compliant error handling with fallback
try:
    from agents.lib.errors import EnumCoreErrorCode, OnexError
except ImportError:
    from enum import Enum

    class EnumCoreErrorCode(str, Enum):
        """Fallback error codes for ONEX compliance."""

        VALIDATION_ERROR = "VALIDATION_ERROR"
        CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
        INITIALIZATION_ERROR = "INITIALIZATION_ERROR"
        OPERATION_FAILED = "OPERATION_FAILED"

    class OnexError(Exception):
        """Fallback OnexError for ONEX compliance."""

        def __init__(
            self, code: EnumCoreErrorCode, message: str, details: dict | None = None
        ):
            self.code = code
            self.error_code = code
            self.message = message
            self.details = details or {}
            super().__init__(message)


logger = logging.getLogger(__name__)


def _get_default_registry_path() -> str:
    """
    Get default agent registry path with environment variable support.

    Priority:
    1. AGENT_REGISTRY_PATH environment variable
    2. REGISTRY_PATH environment variable (Docker compatibility)
    3. Default: ~/.claude/agents/onex/agent-registry.yaml

    Returns:
        Path to agent registry file
    """
    # Check explicit override
    if path := os.getenv("AGENT_REGISTRY_PATH"):
        return path

    # Check Docker-compatible env var
    if path := os.getenv("REGISTRY_PATH"):
        return path

    # Default to home directory
    home_dir = Path.home()
    return str(home_dir / ".claude" / "agents" / "onex" / "agent-registry.yaml")


# Use relative imports for package-based usage
from .capability_index import CapabilityIndex
from .confidence_scorer import ConfidenceScore, ConfidenceScorer
from .result_cache import ResultCache
from .trigger_matcher import TriggerMatcher


@dataclass
class AgentRecommendation:
    """
    Agent recommendation with confidence.

    Attributes:
        agent_name: Internal agent identifier
        agent_title: Human-readable agent title
        confidence: Detailed confidence breakdown
        reason: Primary match reason
        definition_path: Path to agent definition file
    """

    agent_name: str
    agent_title: str
    confidence: ConfidenceScore
    reason: str
    definition_path: str


@dataclass
class RoutingTiming:
    """
    Performance timing data for routing operations.

    All timings in microseconds for high precision.

    Attributes:
        total_routing_time_us: Total time for complete routing operation
        cache_lookup_us: Time spent checking cache
        trigger_matching_us: Time spent matching triggers
        confidence_scoring_us: Time spent calculating confidence scores
        cache_hit: Whether result was found in cache
    """

    total_routing_time_us: int
    cache_lookup_us: int
    trigger_matching_us: int
    confidence_scoring_us: int
    cache_hit: bool


class AgentRouter:
    """
    Agent routing with confidence scoring and caching.

    Combines fuzzy matching, capability indexing, confidence scoring,
    and result caching to provide intelligent agent recommendations.
    """

    def __init__(
        self,
        registry_path: str | None = None,
        cache_ttl: int = 3600,
    ):
        """
        Initialize enhanced router.

        Args:
            registry_path: Path to agent registry YAML file (uses default if None)
            cache_ttl: Cache time-to-live in seconds (default: 1 hour)

        Raises:
            FileNotFoundError: If the registry file does not exist.
            yaml.YAMLError: If the registry file contains invalid YAML.
            OnexError: If initialization fails due to configuration issues.

        Example:
            >>> router = AgentRouter()
            >>> router = AgentRouter(registry_path="/custom/path/registry.yaml")
            >>> router = AgentRouter(cache_ttl=7200)  # 2-hour cache
        """
        # Use default registry path if not provided
        if registry_path is None:
            registry_path = _get_default_registry_path()

        try:
            # Load registry
            with open(registry_path) as f:
                self.registry = yaml.safe_load(f)

            # Convert relative definition_path to absolute paths
            registry_dir = Path(registry_path).parent
            for agent_name, agent_data in self.registry.get("agents", {}).items():
                if "definition_path" in agent_data:
                    def_path = agent_data["definition_path"]
                    # Convert relative path to absolute
                    if not Path(def_path).is_absolute():
                        # Strip agents/onex/ prefix if present (already in registry_dir)
                        if def_path.startswith("agents/onex/"):
                            def_path = def_path.replace("agents/onex/", "", 1)
                        agent_data["definition_path"] = str(registry_dir / def_path)

            logger.info(
                f"Loaded agent registry from {registry_path}",
                extra={"agent_count": len(self.registry.get("agents", {}))},
            )

            # Initialize components
            self.trigger_matcher = TriggerMatcher(self.registry)
            self.confidence_scorer = ConfidenceScorer()
            self.capability_index = CapabilityIndex(registry_path)
            self.cache = ResultCache(default_ttl_seconds=cache_ttl)

            # Track routing stats
            self.routing_stats = {
                "total_routes": 0,
                "cache_hits": 0,
                "cache_misses": 0,
                "explicit_requests": 0,
                "fuzzy_matches": 0,
            }

            # Track performance timing for most recent route
            self.last_routing_timing: RoutingTiming | None = None

            logger.info("AgentRouter initialized successfully")

        except FileNotFoundError:
            logger.error(f"Registry not found: {registry_path}")
            raise
        except yaml.YAMLError as e:
            logger.error(
                f"Invalid YAML in registry: {registry_path}",
                exc_info=True,
                extra={"yaml_error": str(e)},
            )
            raise
        except Exception as e:
            logger.error(
                "Router initialization failed",
                exc_info=True,
                extra={
                    "registry_path": registry_path,
                    "error_type": type(e).__name__,
                },
            )
            raise OnexError(
                code=EnumCoreErrorCode.INITIALIZATION_ERROR,
                message=f"Router initialization failed: {e}",
                details={
                    "component": "AgentRouter",
                    "operation": "initialization",
                    "registry_path": registry_path,
                    "original_error_type": type(e).__name__,
                    "original_error": str(e),
                },
            ) from e

    def route(
        self,
        user_request: str,
        context: dict[str, Any] | None = None,
        max_recommendations: int = 5,
    ) -> list[AgentRecommendation]:
        """
        Route user request to best agent(s).

        Performance timing is captured and stored in self.last_routing_timing.

        Args:
            user_request: User's input text
            context: Optional execution context (domain, previous agent, etc.)
            max_recommendations: Maximum number of recommendations to return

        Returns:
            List of agent recommendations sorted by confidence (highest first).
            Returns empty list on routing failure (graceful degradation).

        Raises:
            None: Exceptions are caught and logged; returns empty list on error.

        Example:
            >>> router = AgentRouter()
            >>> recommendations = router.route(
            ...     user_request="debug this performance issue",
            ...     context={"domain": "performance"},
            ...     max_recommendations=3,
            ... )
            >>> if recommendations:
            ...     best = recommendations[0]
            ...     print(f"Agent: {best.agent_name}, Confidence: {best.confidence.total:.2%}")
        """
        try:
            # Start overall timing
            routing_start_us = time.perf_counter_ns() // 1000

            self.routing_stats["total_routes"] += 1
            context = context or {}

            logger.debug(
                f"Routing request: {user_request[:100]}...",
                extra={"context": context, "max_recommendations": max_recommendations},
            )

            # Track timing for each stage
            cache_lookup_start_us = time.perf_counter_ns() // 1000

            # 1. Check cache
            cached = self.cache.get(user_request, context)
            cache_lookup_end_us = time.perf_counter_ns() // 1000
            cache_lookup_time_us = cache_lookup_end_us - cache_lookup_start_us

            if cached is not None:
                self.routing_stats["cache_hits"] += 1
                logger.debug(
                    "Cache hit - returning cached recommendations",
                    extra={"cached_count": len(cached)},
                )

                # Record timing for cache hit
                routing_end_us = time.perf_counter_ns() // 1000
                self.last_routing_timing = RoutingTiming(
                    total_routing_time_us=routing_end_us - routing_start_us,
                    cache_lookup_us=cache_lookup_time_us,
                    trigger_matching_us=0,
                    confidence_scoring_us=0,
                    cache_hit=True,
                )

                return cast(list[AgentRecommendation], cached)

            self.routing_stats["cache_misses"] += 1

            # 2. Check for explicit agent request
            explicit_agent = self._extract_explicit_agent(user_request)
            if explicit_agent:
                self.routing_stats["explicit_requests"] += 1
                recommendation = self._create_explicit_recommendation(explicit_agent)
                if recommendation:
                    result = [recommendation]
                    self.cache.set(user_request, result, context)
                    logger.info(
                        f"Explicit agent request: {explicit_agent}",
                        extra={"agent_name": explicit_agent},
                    )

                    # Record timing for explicit request
                    routing_end_us = time.perf_counter_ns() // 1000
                    self.last_routing_timing = RoutingTiming(
                        total_routing_time_us=routing_end_us - routing_start_us,
                        cache_lookup_us=cache_lookup_time_us,
                        trigger_matching_us=0,
                        confidence_scoring_us=0,
                        cache_hit=False,
                    )

                    return result

            # 3. Trigger-based matching with scoring
            self.routing_stats["fuzzy_matches"] += 1

            trigger_matching_start_us = time.perf_counter_ns() // 1000
            trigger_matches = self.trigger_matcher.match(user_request)
            trigger_matching_end_us = time.perf_counter_ns() // 1000
            trigger_matching_time_us = (
                trigger_matching_end_us - trigger_matching_start_us
            )

            logger.debug(
                f"Found {len(trigger_matches)} trigger matches",
                extra={"match_count": len(trigger_matches)},
            )

            # 4. Score each match
            confidence_scoring_start_us = time.perf_counter_ns() // 1000
            recommendations = []
            for agent_name, trigger_score, match_reason in trigger_matches:
                try:
                    agent_data = self.registry["agents"][agent_name]

                    # Calculate comprehensive confidence
                    confidence = self.confidence_scorer.score(
                        agent_name=agent_name,
                        agent_data=agent_data,
                        user_request=user_request,
                        context=context,
                        trigger_score=trigger_score,
                    )

                    recommendation = AgentRecommendation(
                        agent_name=agent_name,
                        agent_title=agent_data["title"],
                        confidence=confidence,
                        reason=match_reason,
                        definition_path=agent_data["definition_path"],
                    )

                    recommendations.append(recommendation)

                except KeyError as e:
                    logger.warning(
                        f"Agent {agent_name} missing required field: {e}",
                        extra={"agent_name": agent_name, "missing_field": str(e)},
                    )
                    continue
                except Exception as e:
                    logger.warning(
                        f"Failed to score agent {agent_name}: {type(e).__name__}",
                        exc_info=True,
                        extra={"agent_name": agent_name},
                    )
                    continue

            # 5. Sort by confidence
            recommendations.sort(key=lambda x: x.confidence.total, reverse=True)

            # 6. Limit to max recommendations
            recommendations = recommendations[:max_recommendations]

            confidence_scoring_end_us = time.perf_counter_ns() // 1000
            confidence_scoring_time_us = (
                confidence_scoring_end_us - confidence_scoring_start_us
            )

            # 7. Cache results (even empty results to avoid recomputation)
            self.cache.set(user_request, recommendations, context)

            # Calculate total routing time
            routing_end_us = time.perf_counter_ns() // 1000

            # Record detailed timing
            self.last_routing_timing = RoutingTiming(
                total_routing_time_us=routing_end_us - routing_start_us,
                cache_lookup_us=cache_lookup_time_us,
                trigger_matching_us=trigger_matching_time_us,
                confidence_scoring_us=confidence_scoring_time_us,
                cache_hit=False,
            )

            # 8. Log routing decision
            logger.info(
                f"Routed request to {len(recommendations)} agents",
                extra={
                    "user_request": user_request[:100],
                    "top_agent": (
                        recommendations[0].agent_name if recommendations else "none"
                    ),
                    "confidence": (
                        recommendations[0].confidence.total if recommendations else 0.0
                    ),
                    "total_candidates": len(trigger_matches),
                    "routing_time_us": self.last_routing_timing.total_routing_time_us,
                },
            )

            return recommendations

        except Exception as e:
            logger.error(
                f"Routing failed for request: {user_request[:100]}...",
                exc_info=True,
                extra={
                    "user_request": user_request,
                    "context": context,
                    "error_type": type(e).__name__,
                },
            )
            # Return empty list on failure (graceful degradation)
            return []

    async def route_async(
        self,
        user_request: str,
        context: dict[str, Any] | None = None,
        max_recommendations: int = 5,
        min_confidence: float = 0.6,
        timeout_ms: int = 5000,
        fallback_to_local: bool = True,
    ) -> list[AgentRecommendation]:
        """
        Route user request to best agent(s) using async event-driven routing.

        This method uses the Kafka event bus for distributed routing, enabling
        integration with the routing_adapter service. Falls back to local
        synchronous routing on timeout or failure if fallback_to_local=True.

        Args:
            user_request: User's input text
            context: Optional execution context (domain, previous agent, etc.)
            max_recommendations: Maximum number of recommendations to return
            min_confidence: Minimum confidence threshold (0.0-1.0)
            timeout_ms: Response timeout in milliseconds (default: 5000)
            fallback_to_local: If True, use local routing on failure (default: True)

        Returns:
            List of agent recommendations sorted by confidence (highest first)

        Raises:
            OnexError: If routing fails and fallback_to_local is False.
                The error will include details about the failure type
                (timeout, connection error, etc.) and correlation ID.

        Example:
            router = AgentRouter()
            recommendations = await router.route_async(
                user_request="optimize my database queries",
                context={"domain": "database_optimization"},
                max_recommendations=3,
            )
        """
        try:
            # Import here to avoid circular imports
            from .routing_event_client import route_via_events

            logger.debug(
                f"Async routing request: {user_request[:100]}...",
                extra={"context": context, "max_recommendations": max_recommendations},
            )

            # Use event-driven routing
            recommendations_dicts = await route_via_events(
                user_request=user_request,
                context=context,
                max_recommendations=max_recommendations,
                min_confidence=min_confidence,
                timeout_ms=timeout_ms,
                fallback_to_local=False,  # Handle fallback ourselves for better typing
            )

            # Convert dict format to AgentRecommendation objects
            recommendations = []
            for rec_dict in recommendations_dicts:
                confidence_data = rec_dict.get("confidence", {})
                recommendation = AgentRecommendation(
                    agent_name=rec_dict["agent_name"],
                    agent_title=rec_dict["agent_title"],
                    confidence=ConfidenceScore(
                        total=confidence_data.get("total", 0.0),
                        trigger_score=confidence_data.get("trigger_score", 0.0),
                        context_score=confidence_data.get("context_score", 0.0),
                        capability_score=confidence_data.get("capability_score", 0.0),
                        historical_score=confidence_data.get("historical_score", 0.0),
                        explanation=confidence_data.get("explanation", ""),
                    ),
                    reason=rec_dict.get("reason", ""),
                    definition_path=rec_dict.get("definition_path", ""),
                )
                recommendations.append(recommendation)

            logger.info(
                f"Async routed request to {len(recommendations)} agents",
                extra={
                    "user_request": user_request[:100],
                    "top_agent": (
                        recommendations[0].agent_name if recommendations else "none"
                    ),
                    "confidence": (
                        recommendations[0].confidence.total if recommendations else 0.0
                    ),
                    "routing_method": "event_driven",
                },
            )

            return recommendations

        except Exception as e:
            logger.warning(
                f"Async event-driven routing failed: {e}",
                extra={
                    "user_request": user_request[:100],
                    "error_type": type(e).__name__,
                },
            )

            if fallback_to_local:
                # Fallback to synchronous local routing
                logger.info("Falling back to local synchronous routing")
                # Run sync route in executor to avoid blocking event loop
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    None,
                    lambda: self.route(
                        user_request=user_request,
                        context=context,
                        max_recommendations=max_recommendations,
                    ),
                )
            else:
                # Re-raise if no fallback
                raise

    def _extract_explicit_agent(self, text: str) -> str | None:
        """
        Extract explicit agent name from request.

        Supports patterns:
        - "use agent-X" - Specific agent request
        - "@agent-X" - Specific agent request
        - "agent-X" at start of text - Specific agent request
        - "use an agent", "spawn an agent", etc. - Generic request -> polymorphic-agent

        Args:
            text: User's input text

        Returns:
            Agent name if found and valid, None otherwise.

        Raises:
            None: Exceptions are caught and logged; returns None on error.

        Example:
            >>> router = AgentRouter()
            >>> router._extract_explicit_agent("use agent-researcher to find docs")
            'agent-researcher'
            >>> router._extract_explicit_agent("@agent-debug analyze error")
            'agent-debug'
            >>> router._extract_explicit_agent("use an agent to help")
            'polymorphic-agent'
            >>> router._extract_explicit_agent("just a normal query")
            None
        """
        try:
            text_lower = text.lower()

            # Patterns for specific agent requests (with agent name)
            specific_patterns = [
                r"use\s+(agent-[\w-]+)",  # "use agent-researcher"
                r"@(agent-[\w-]+)",  # "@agent-researcher"
                r"^(agent-[\w-]+)",  # "agent-researcher" at start
            ]

            # Check specific patterns first
            for pattern in specific_patterns:
                match = re.search(pattern, text_lower)
                if match:
                    agent_name = match.group(1)
                    # Verify agent exists in registry
                    if agent_name in self.registry["agents"]:
                        logger.debug(
                            f"Extracted explicit agent: {agent_name}",
                            extra={"pattern": pattern, "text_sample": text[:50]},
                        )
                        return agent_name

            # Patterns for generic agent requests (no specific agent name)
            # These should default to polymorphic-agent
            # Word boundaries (\b) prevent false positives like "misuse an agent"
            generic_patterns = [
                r"\buse\s+an?\s+agent\b",  # "use an agent" or "use a agent"
                r"\bspawn\s+an?\s+agent\b",  # "spawn an agent" or "spawn a agent"
                r"\bspawn\s+an?\s+poly\b",  # "spawn a poly" or "spawn an poly"
                r"\bdispatch\s+to\s+an?\s+agent\b",  # "dispatch to an agent"
                r"\bcall\s+an?\s+agent\b",  # "call an agent" or "call a agent"
                r"\binvoke\s+an?\s+agent\b",  # "invoke an agent" or "invoke a agent"
            ]

            # Check generic patterns
            for pattern in generic_patterns:
                match = re.search(pattern, text_lower)
                if match:
                    # Default to polymorphic-agent
                    default_agent = "polymorphic-agent"
                    # Verify polymorphic-agent exists in registry
                    if default_agent in self.registry["agents"]:
                        logger.debug(
                            f"Generic agent request matched, "
                            f"using default: {default_agent}",
                            extra={"pattern": pattern, "text_sample": text[:50]},
                        )
                        return default_agent
                    else:
                        logger.warning(
                            f"Generic agent request matched but "
                            f"{default_agent} not found in registry",
                            extra={"pattern": pattern},
                        )

            return None

        except Exception as e:
            logger.warning(
                f"Failed to extract explicit agent from: {text[:50]}...",
                exc_info=True,
                extra={"error_type": type(e).__name__},
            )
            return None

    def _create_explicit_recommendation(
        self, agent_name: str
    ) -> AgentRecommendation | None:
        """
        Create recommendation for explicitly requested agent.

        Args:
            agent_name: Name of explicitly requested agent

        Returns:
            AgentRecommendation with 100% confidence, or None if agent not found
        """
        agent_data = self.registry["agents"].get(agent_name)
        if not agent_data:
            return None

        return AgentRecommendation(
            agent_name=agent_name,
            agent_title=agent_data["title"],
            confidence=ConfidenceScore(
                total=1.0,
                trigger_score=1.0,
                context_score=1.0,
                capability_score=1.0,
                historical_score=1.0,
                explanation="Explicit agent request",
            ),
            reason="Explicitly requested by user",
            definition_path=agent_data["definition_path"],
        )

    def get_cache_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache performance metrics
        """
        cache_stats: dict[str, Any] = self.cache.stats()
        cache_stats["cache_hit_rate"] = (
            self.routing_stats["cache_hits"] / self.routing_stats["total_routes"]
            if self.routing_stats["total_routes"] > 0
            else 0.0
        )
        return cache_stats

    def get_routing_stats(self) -> dict[str, Any]:
        """
        Get routing statistics.

        Returns:
            Dictionary with routing performance metrics
        """
        stats: dict[str, Any] = dict(self.routing_stats)

        # Calculate rates
        total = stats["total_routes"]
        if total > 0:
            stats["cache_hit_rate"] = stats["cache_hits"] / total
            stats["explicit_request_rate"] = stats["explicit_requests"] / total
            stats["fuzzy_match_rate"] = stats["fuzzy_matches"] / total

        return stats

    def invalidate_cache(self):
        """Invalidate entire routing cache."""
        self.cache.clear()

    def reload_registry(self, registry_path: str | None = None):
        """
        Reload agent registry.

        Useful when agent definitions change. Rebuilds trigger matcher,
        capability index, and clears the result cache.

        Args:
            registry_path: Path to registry file (uses default if None)

        Returns:
            None

        Raises:
            FileNotFoundError: If the registry file does not exist.
            yaml.YAMLError: If the registry file contains invalid YAML.
            OnexError: If reload fails due to configuration issues.

        Example:
            >>> router = AgentRouter()
            >>> # After modifying agent definitions...
            >>> router.reload_registry()  # Reload from default path
            >>> router.reload_registry("/custom/path/registry.yaml")  # Custom path
        """
        path = registry_path or _get_default_registry_path()

        try:
            logger.info(f"Reloading registry from {path}")

            with open(path) as f:
                self.registry = yaml.safe_load(f)

            # Convert relative definition_path to absolute paths
            registry_dir = Path(path).parent
            for agent_name, agent_data in self.registry.get("agents", {}).items():
                if "definition_path" in agent_data:
                    def_path = agent_data["definition_path"]
                    # Convert relative path to absolute
                    if not Path(def_path).is_absolute():
                        # Strip agents/onex/ prefix if present (already in registry_dir)
                        if def_path.startswith("agents/onex/"):
                            def_path = def_path.replace("agents/onex/", "", 1)
                        agent_data["definition_path"] = str(registry_dir / def_path)

            # Rebuild components
            self.trigger_matcher = TriggerMatcher(self.registry)
            self.capability_index = CapabilityIndex(path)

            # Clear cache since definitions changed
            self.cache.clear()

            logger.info(
                "Registry reloaded successfully",
                extra={"agent_count": len(self.registry.get("agents", {}))},
            )

        except FileNotFoundError:
            logger.error(f"Registry not found during reload: {path}")
            raise
        except yaml.YAMLError as e:
            logger.error(
                f"Invalid YAML during reload: {path}",
                exc_info=True,
                extra={"yaml_error": str(e)},
            )
            raise
        except Exception as e:
            logger.error(
                "Registry reload failed",
                exc_info=True,
                extra={
                    "registry_path": path,
                    "error_type": type(e).__name__,
                },
            )
            raise OnexError(
                code=EnumCoreErrorCode.CONFIGURATION_ERROR,
                message=f"Registry reload failed: {e}",
                details={
                    "component": "AgentRouter",
                    "operation": "reload_registry",
                    "registry_path": path,
                    "original_error_type": type(e).__name__,
                    "original_error": str(e),
                },
            ) from e


# Example usage and testing
if __name__ == "__main__":  # pragma: no cover
    from pathlib import Path

    registry_path = Path.home() / ".claude" / "agents" / "onex" / "agent-registry.yaml"

    if not registry_path.exists():
        print(f"Registry not found at: {registry_path}")
        exit(1)

    router = AgentRouter(str(registry_path))

    test_queries = [
        "debug this performance issue",
        "use agent-api-architect to design API",
        "@agent-debug-intelligence analyze error",
        "optimize my database queries",
        "review security of authentication",
        "create CI/CD pipeline for deployment",
    ]

    for query in test_queries:
        print(f"\n{'='*70}")
        print(f"Query: {query}")
        print("=" * 70)

        recommendations = router.route(query, max_recommendations=3)

        if not recommendations:
            print("  No recommendations found")
            continue

        for i, rec in enumerate(recommendations, 1):
            print(f"\n{i}. {rec.agent_title}")
            print(f"   Agent: {rec.agent_name}")
            print(f"   Confidence: {rec.confidence.total:.2%}")
            print("   Breakdown:")
            print(f"     - Trigger:     {rec.confidence.trigger_score:.2%}")
            print(f"     - Context:     {rec.confidence.context_score:.2%}")
            print(f"     - Capability:  {rec.confidence.capability_score:.2%}")
            print(f"     - Historical:  {rec.confidence.historical_score:.2%}")
            print(f"   Reason: {rec.reason}")
            print(f"   Explanation: {rec.confidence.explanation}")

    # Show statistics
    print(f"\n{'='*70}")
    print("ROUTING STATISTICS")
    print("=" * 70)

    routing_stats = router.get_routing_stats()
    for key, value in routing_stats.items():
        if isinstance(value, float):
            print(f"{key}: {value:.2%}")
        else:
            print(f"{key}: {value}")

    print(f"\n{'='*70}")
    print("CACHE STATISTICS")
    print("=" * 70)

    cache_stats = router.get_cache_stats()
    for key, value in cache_stats.items():
        if isinstance(value, float) and "rate" in key:
            print(f"{key}: {value:.2%}")
        elif isinstance(value, float):
            print(f"{key}: {value:.1f}")
        else:
            print(f"{key}: {value}")
