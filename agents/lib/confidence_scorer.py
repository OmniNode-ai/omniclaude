"""
Confidence Scorer - Phase 1
===========================

Calculates comprehensive confidence scores for agent matches.

Confidence Components (weighted):
1. Trigger Score (40%) - How well triggers match the request
2. Context Score (30%) - Domain and context alignment
3. Capability Score (20%) - Capability relevance
4. Historical Score (10%) - Past success rates
"""

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ConfidenceScore:
    """
    Confidence score with detailed breakdown.

    Attributes:
        total: Overall confidence (0.0-1.0)
        trigger_score: Trigger matching score (0.0-1.0)
        context_score: Context alignment score (0.0-1.0)
        capability_score: Capability match score (0.0-1.0)
        historical_score: Historical success score (0.0-1.0)
        explanation: Human-readable explanation
    """

    total: float  # 0.0-1.0
    trigger_score: float
    context_score: float
    capability_score: float
    historical_score: float
    explanation: str


class ConfidenceScorer:
    """
    Calculate confidence scores for agent matches.

    Uses weighted scoring across multiple dimensions:
    - Trigger match quality (40%)
    - Context alignment (30%)
    - Capability relevance (20%)
    - Historical performance (10%)
    """

    # Component weights
    WEIGHT_TRIGGER = 0.4
    WEIGHT_CONTEXT = 0.3
    WEIGHT_CAPABILITY = 0.2
    WEIGHT_HISTORICAL = 0.1

    def __init__(self):
        """Initialize confidence scorer."""
        # Historical success rates (loaded from tracking data)
        # In Phase 2+, this would come from actual usage tracking
        self.historical_success = {}

    def score(
        self,
        agent_name: str,
        agent_data: Dict[str, Any],
        user_request: str,
        context: Dict[str, Any],
        trigger_score: float,
    ) -> ConfidenceScore:
        """
        Calculate comprehensive confidence score.

        Args:
            agent_name: Name of the agent being scored
            agent_data: Agent metadata from registry
            user_request: User's input text
            context: Current execution context
            trigger_score: Pre-calculated trigger match score

        Returns:
            ConfidenceScore object with breakdown and explanation
        """

        # 1. Trigger score (from matcher) - 40% weight
        weighted_trigger = trigger_score * self.WEIGHT_TRIGGER

        # 2. Context score - 30% weight
        context_score = self._calculate_context_score(agent_data, context)
        weighted_context = context_score * self.WEIGHT_CONTEXT

        # 3. Capability score - 20% weight
        capability_score = self._calculate_capability_score(agent_data, user_request)
        weighted_capability = capability_score * self.WEIGHT_CAPABILITY

        # 4. Historical score - 10% weight
        historical_score = self._calculate_historical_score(agent_name, user_request)
        weighted_historical = historical_score * self.WEIGHT_HISTORICAL

        # Total score
        total = (
            weighted_trigger
            + weighted_context
            + weighted_capability
            + weighted_historical
        )

        # Generate explanation
        explanation = self._generate_explanation(
            agent_name, trigger_score, context_score, capability_score, historical_score
        )

        return ConfidenceScore(
            total=total,
            trigger_score=trigger_score,
            context_score=context_score,
            capability_score=capability_score,
            historical_score=historical_score,
            explanation=explanation,
        )

    def _calculate_context_score(self, agent_data: Dict, context: Dict) -> float:
        """
        Score based on context alignment.

        Checks if agent's domain matches current context.

        Args:
            agent_data: Agent metadata
            context: Current execution context

        Returns:
            Context alignment score (0.0-1.0)
        """
        agent_context = agent_data.get("domain_context", "general")

        # Check if context matches
        current_context = context.get("domain", "general")

        if agent_context == current_context:
            # Perfect domain match
            return 1.0
        elif agent_context == "general" or current_context == "general":
            # General agents work in any domain
            return 0.7
        else:
            # Domain mismatch
            return 0.4

    def _calculate_capability_score(self, agent_data: Dict, request: str) -> float:
        """
        Score based on capability match.

        Measures how many agent capabilities are mentioned in request.

        Args:
            agent_data: Agent metadata
            request: User's input text

        Returns:
            Capability match score (0.0-1.0)
        """
        capabilities = agent_data.get("capabilities", [])

        if not capabilities:
            # No capabilities defined - neutral score
            return 0.5

        # Extract keywords from request
        request_lower = request.lower()

        # Check if any capability mentioned
        matches = sum(1 for cap in capabilities if cap.lower() in request_lower)

        # Return proportional score
        return min(matches / len(capabilities), 1.0)

    def _calculate_historical_score(self, agent_name: str, request: str) -> float:
        """
        Score based on historical success.

        In Phase 1, returns default 0.5.
        In future phases, will use actual usage tracking.

        Args:
            agent_name: Name of the agent
            request: User's input text

        Returns:
            Historical success score (0.0-1.0)
        """
        # Default score if no history
        if agent_name not in self.historical_success:
            return 0.5

        result = self.historical_success[agent_name].get("overall", 0.5)
        return float(result) if result is not None else 0.5

    def _generate_explanation(
        self,
        agent_name: str,
        trigger_score: float,
        context_score: float,
        capability_score: float,
        historical_score: float,
    ) -> str:
        """
        Generate human-readable explanation.

        Creates a natural language summary of why the agent was recommended.

        Args:
            agent_name: Name of the agent
            trigger_score: Trigger match score
            context_score: Context alignment score
            capability_score: Capability match score
            historical_score: Historical success score

        Returns:
            Human-readable explanation string
        """
        parts = []

        # Trigger match explanation
        if trigger_score > 0.8:
            parts.append("Strong trigger match")
        elif trigger_score > 0.6:
            parts.append("Good trigger match")
        else:
            parts.append("Moderate trigger match")

        # Context alignment explanation
        if context_score > 0.8:
            parts.append("perfect context alignment")
        elif context_score > 0.6:
            parts.append("good context fit")

        # Capability match explanation
        if capability_score > 0.6:
            parts.append("relevant capabilities")

        # Historical performance explanation
        if historical_score > 0.7:
            parts.append("proven track record")

        return f"{agent_name}: {', '.join(parts)}"

    def update_historical_data(self, agent_name: str, success_rate: float):
        """
        Update historical success rate for an agent.

        Used to track agent performance over time.

        Args:
            agent_name: Name of the agent
            success_rate: Success rate (0.0-1.0)
        """
        if agent_name not in self.historical_success:
            self.historical_success[agent_name] = {}

        self.historical_success[agent_name]["overall"] = success_rate


# Standalone test
if __name__ == "__main__":
    scorer = ConfidenceScorer()

    # Test scoring
    test_agent_data = {
        "title": "Debug Intelligence Agent",
        "domain_context": "debugging",
        "capabilities": ["error_analysis", "root_cause", "debugging"],
    }

    test_context = {"domain": "debugging"}

    result = scorer.score(
        agent_name="agent-debug-intelligence",
        agent_data=test_agent_data,
        user_request="debug this performance error",
        context=test_context,
        trigger_score=0.85,
    )

    print(f"Total Confidence: {result.total:.2f}")
    print("Breakdown:")
    print(f"  Trigger:    {result.trigger_score:.2f}")
    print(f"  Context:    {result.context_score:.2f}")
    print(f"  Capability: {result.capability_score:.2f}")
    print(f"  Historical: {result.historical_score:.2f}")
    print(f"\nExplanation: {result.explanation}")
