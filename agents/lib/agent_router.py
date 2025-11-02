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

Performance Targets:
- Total routing time: <100ms
- Cache hit: <5ms
- Cache miss: <100ms
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Use absolute imports to avoid relative import issues
try:
    from capability_index import CapabilityIndex
    from confidence_scorer import ConfidenceScore, ConfidenceScorer
    from result_cache import ResultCache
    from trigger_matcher import TriggerMatcher
except ImportError:
    # Fallback to relative imports if used as a package
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


class AgentRouter:
    """
    Agent routing with confidence scoring and caching.

    Combines fuzzy matching, capability indexing, confidence scoring,
    and result caching to provide intelligent agent recommendations.
    """

    def __init__(
        self,
        registry_path: str = (
            "/Users/jonah/.claude/agent-definitions/agent-registry.yaml"
        ),
        cache_ttl: int = 3600,
    ):
        """
        Initialize enhanced router.

        Args:
            registry_path: Path to agent registry YAML file
            cache_ttl: Cache time-to-live in seconds (default: 1 hour)
        """
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
                        # Strip "agent-definitions/" prefix if present
                        # (already in registry_dir)
                        if def_path.startswith("agent-definitions/"):
                            def_path = def_path.replace("agent-definitions/", "", 1)
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
            raise

    def route(
        self,
        user_request: str,
        context: Optional[Dict[str, Any]] = None,
        max_recommendations: int = 5,
    ) -> List[AgentRecommendation]:
        """
        Route user request to best agent(s).

        Args:
            user_request: User's input text
            context: Optional execution context (domain, previous agent, etc.)
            max_recommendations: Maximum number of recommendations to return

        Returns:
            List of agent recommendations sorted by confidence (highest first)
        """
        try:
            self.routing_stats["total_routes"] += 1
            context = context or {}

            logger.debug(
                f"Routing request: {user_request[:100]}...",
                extra={"context": context, "max_recommendations": max_recommendations},
            )

            # 1. Check cache
            cached = self.cache.get(user_request, context)
            if cached is not None:
                self.routing_stats["cache_hits"] += 1
                logger.debug(
                    "Cache hit - returning cached recommendations",
                    extra={"cached_count": len(cached)},
                )
                return cached

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
                    return result

            # 3. Trigger-based matching with scoring
            self.routing_stats["fuzzy_matches"] += 1
            trigger_matches = self.trigger_matcher.match(user_request)

            logger.debug(
                f"Found {len(trigger_matches)} trigger matches",
                extra={"match_count": len(trigger_matches)},
            )

            # 4. Score each match
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

            # 7. Cache results (even empty results to avoid recomputation)
            self.cache.set(user_request, recommendations, context)

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

    def _extract_explicit_agent(self, text: str) -> Optional[str]:
        """
        Extract explicit agent name from request.

        Supports patterns:
        - "use agent-X" - Specific agent request
        - "@agent-X" - Specific agent request
        - "agent-X" at start of text - Specific agent request
        - "use an agent", "spawn an agent", etc. - Generic request → polymorphic-agent

        Args:
            text: User's input text

        Returns:
            Agent name if found and valid, None otherwise
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
            generic_patterns = [
                r"use\s+an?\s+agent",  # "use an agent" or "use a agent"
                r"spawn\s+an?\s+agent",  # "spawn an agent" or "spawn a agent"
                r"spawn\s+an?\s+poly",  # "spawn a poly" or "spawn an poly"
                r"dispatch\s+an?\s+agent",  # "dispatch an agent" or "dispatch a agent"
                r"call\s+an?\s+agent",  # "call an agent" or "call a agent"
                r"invoke\s+an?\s+agent",  # "invoke an agent" or "invoke a agent"
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
    ) -> Optional[AgentRecommendation]:
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

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache performance metrics
        """
        cache_stats = self.cache.stats()
        cache_stats["cache_hit_rate"] = (
            self.routing_stats["cache_hits"] / self.routing_stats["total_routes"]
            if self.routing_stats["total_routes"] > 0
            else 0.0
        )
        return cache_stats

    def get_routing_stats(self) -> Dict[str, Any]:
        """
        Get routing statistics.

        Returns:
            Dictionary with routing performance metrics
        """
        stats = self.routing_stats.copy()

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

    def reload_registry(self, registry_path: Optional[str] = None):
        """
        Reload agent registry.

        Useful when agent definitions change.

        Args:
            registry_path: Path to registry file (uses default if None)
        """
        path = (
            registry_path
            or "/Users/jonah/.claude/agent-definitions/agent-registry.yaml"
        )

        try:
            logger.info(f"Reloading registry from {path}")

            with open(path) as f:
                self.registry = yaml.safe_load(f)

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
            raise


# Example usage and testing
if __name__ == "__main__":
    from pathlib import Path

    registry_path = (
        Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml"
    )

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
