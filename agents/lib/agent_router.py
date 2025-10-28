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

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml

# Use absolute imports to avoid relative import issues
try:
    from capability_index import CapabilityIndex
    from confidence_scorer import ConfidenceScore, ConfidenceScorer
    from result_cache import ResultCache
    from trigger_matcher import EnhancedTriggerMatcher
except ImportError:
    # Fallback to relative imports if used as a package
    from .capability_index import CapabilityIndex
    from .confidence_scorer import ConfidenceScore, ConfidenceScorer
    from .result_cache import ResultCache
    from .trigger_matcher import EnhancedTriggerMatcher


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
        registry_path: str = "/Users/jonah/.claude/agent-definitions/agent-registry.yaml",
        cache_ttl: int = 3600,
    ):
        """
        Initialize enhanced router.

        Args:
            registry_path: Path to agent registry YAML file
            cache_ttl: Cache time-to-live in seconds (default: 1 hour)
        """
        # Load registry
        with open(registry_path) as f:
            self.registry = yaml.safe_load(f)

        # Initialize components
        self.trigger_matcher = EnhancedTriggerMatcher(self.registry)
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
        self.routing_stats["total_routes"] += 1
        context = context or {}

        # 1. Check cache
        cached = self.cache.get(user_request, context)
        if cached is not None:
            self.routing_stats["cache_hits"] += 1
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
                return result

        # 3. Trigger-based matching with scoring
        self.routing_stats["fuzzy_matches"] += 1
        trigger_matches = self.trigger_matcher.match(user_request)

        # 4. Score each match
        recommendations = []
        for agent_name, trigger_score, match_reason in trigger_matches:
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

        # 5. Sort by confidence
        recommendations.sort(key=lambda x: x.confidence.total, reverse=True)

        # 6. Limit to max recommendations
        recommendations = recommendations[:max_recommendations]

        # 7. Cache results
        self.cache.set(user_request, recommendations, context)

        return recommendations

    def _extract_explicit_agent(self, text: str) -> Optional[str]:
        """
        Extract explicit agent name from request.

        Supports patterns:
        - "use agent-X"
        - "@agent-X"
        - "agent-X" at start of text

        Args:
            text: User's input text

        Returns:
            Agent name if found and valid, None otherwise
        """
        text_lower = text.lower()

        # Patterns for explicit agent requests
        patterns = [
            r"use\s+(agent-[\w-]+)",
            r"@(agent-[\w-]+)",
            r"^(agent-[\w-]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                agent_name = match.group(1)
                # Verify agent exists in registry
                if agent_name in self.registry["agents"]:
                    return agent_name

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

        with open(path) as f:
            self.registry = yaml.safe_load(f)

        # Rebuild components
        self.trigger_matcher = EnhancedTriggerMatcher(self.registry)
        self.capability_index = CapabilityIndex(path)

        # Clear cache since definitions changed
        self.cache.clear()


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
