# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Default routing handler - wraps _internal/ pure-Python logic with typed models.

Implements ProtocolAgentRouting by:
1. Converting ModelRoutingRequest (typed) -> dict format for _internal/ modules
2. Running TriggerMatcher and ConfidenceScorer (pure Python, zero ONEX imports)
3. Converting dict results -> ModelRoutingResult (typed)

Flow:
    ModelRoutingRequest
        -> check explicit agent request (@agent-name, "use agent-X")
        -> if explicit: return ModelRoutingResult(routing_policy="explicit_request")
        -> else: TriggerMatcher.match() -> ConfidenceScorer.score()
        -> sort by confidence, take top results
        -> return ModelRoutingResult(routing_policy="trigger_match")
        -> if no matches: return fallback ModelRoutingResult(routing_policy="fallback_default")
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from omniclaude.nodes.node_agent_routing_compute._internal import (
    ConfidenceScorer,
    TriggerMatcher,
)
from omniclaude.nodes.node_agent_routing_compute._internal.confidence_scoring import (
    AgentData,
)
from omniclaude.nodes.node_agent_routing_compute._internal.trigger_matching import (
    AgentRegistry,
)
from omniclaude.nodes.node_agent_routing_compute.models import (
    ModelConfidenceBreakdown,
    ModelRoutingCandidate,
    ModelRoutingRequest,
    ModelRoutingResult,
)

__all__ = ["HandlerRoutingDefault"]

logger = logging.getLogger(__name__)

# Default fallback agent when no matches exceed threshold
_FALLBACK_AGENT = "polymorphic-agent"

# Maximum number of candidates to include in result
_MAX_CANDIDATES = 5


class HandlerRoutingDefault:
    """Default routing handler using trigger matching and confidence scoring.

    Wraps the pure-Python _internal/ modules (TriggerMatcher, ConfidenceScorer)
    with typed ONEX model conversion. This is the ONLY place where ONEX model
    imports meet the internal dict-based logic.

    Attributes:
        handler_key: Registry key for handler lookup.
    """

    @property
    def handler_key(self) -> str:
        """Backend identifier for handler routing."""
        return "default"

    async def compute_routing(
        self,
        request: ModelRoutingRequest,
        correlation_id: UUID | None = None,
    ) -> ModelRoutingResult:
        """Compute a routing decision for a user prompt.

        Evaluates the prompt against all agents in the registry using
        trigger matching and confidence scoring.

        Args:
            request: Routing request with prompt, agent registry, and thresholds.
            correlation_id: Optional override for tracing. Falls back to
                request.correlation_id if None.

        Returns:
            ModelRoutingResult with selected agent, confidence breakdown,
            and all evaluated candidates.
        """
        cid = correlation_id or request.correlation_id

        # 1. Convert ModelRoutingRequest.agent_registry to dict format
        #    TriggerMatcher expects: {"agents": {name: {"activation_triggers": [...], ...}}}
        registry_dict = self._build_registry_dict(request)
        agent_names = set(registry_dict["agents"].keys())

        # 2. Check for explicit agent request (@agent-name, "use agent-X")
        explicit_agent = self._extract_explicit_agent(request.prompt, agent_names)
        if explicit_agent is not None:
            logger.debug(
                "Explicit agent request detected: %s (correlation_id=%s)",
                explicit_agent,
                cid,
            )
            return self._create_explicit_result(explicit_agent)

        # 3. Run TriggerMatcher.match() to get trigger matches
        # TriggerMatcher is instantiated per-call because the agent registry
        # is part of the request and may vary between invocations.
        try:
            matcher = TriggerMatcher(registry_dict)
            trigger_matches = matcher.match(request.prompt)
        except Exception:
            logger.exception("TriggerMatcher.match() failed (correlation_id=%s)", cid)
            trigger_matches = []

        # 4. For each match, run ConfidenceScorer.score()
        # Phase 1: context={} means historical_score always returns 0.5 (default).
        # request.historical_stats is accepted but not yet forwarded to the scorer.
        # Phase 2+ will populate context with historical_stats for real scoring.
        scorer = ConfidenceScorer()
        candidates: list[ModelRoutingCandidate] = []

        for agent_name, trigger_score, match_reason in trigger_matches:
            agent_data = registry_dict["agents"].get(agent_name, {})
            try:
                confidence = scorer.score(
                    agent_name=agent_name,
                    agent_data=agent_data,
                    user_request=request.prompt,
                    context={},  # Phase 1: no historical context yet
                    trigger_score=trigger_score,
                )
            except Exception:
                logger.warning(
                    "ConfidenceScorer.score() failed for %s (correlation_id=%s)",
                    agent_name,
                    cid,
                    exc_info=True,
                )
                continue

            breakdown = ModelConfidenceBreakdown(
                total=_clamp(confidence.total),
                trigger_score=_clamp(confidence.trigger_score),
                context_score=_clamp(confidence.context_score),
                capability_score=_clamp(confidence.capability_score),
                historical_score=_clamp(confidence.historical_score),
                explanation=confidence.explanation,
            )

            candidates.append(
                ModelRoutingCandidate(
                    agent_name=agent_name,
                    confidence=_clamp(confidence.total),
                    confidence_breakdown=breakdown,
                    match_reason=match_reason,
                )
            )

        # 5. Sort by confidence, take top results
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        candidates = candidates[:_MAX_CANDIDATES]

        # 6. Filter by confidence threshold
        above_threshold = [
            c for c in candidates if c.confidence >= request.confidence_threshold
        ]

        # 7. Return result
        if above_threshold:
            best = above_threshold[0]
            logger.debug(
                "Routing to %s (confidence=%.2f, correlation_id=%s)",
                best.agent_name,
                best.confidence,
                cid,
            )
            return ModelRoutingResult(
                selected_agent=best.agent_name,
                confidence=best.confidence,
                confidence_breakdown=best.confidence_breakdown,
                routing_policy="trigger_match",
                routing_path="local",
                candidates=tuple(candidates),
                fallback_reason=None,
            )

        # 8. Fallback - no matches above threshold
        fallback_reason = (
            f"No agents matched above threshold {request.confidence_threshold:.2f}"
            if not candidates
            else (
                f"Best match {candidates[0].agent_name} "
                f"({candidates[0].confidence:.2f}) below "
                f"threshold {request.confidence_threshold:.2f}"
            )
        )
        logger.debug(
            "Falling back to %s: %s (correlation_id=%s)",
            _FALLBACK_AGENT,
            fallback_reason,
            cid,
        )
        return ModelRoutingResult(
            selected_agent=_FALLBACK_AGENT,
            confidence=0.0,
            confidence_breakdown=ModelConfidenceBreakdown(
                total=0.0,
                trigger_score=0.0,
                context_score=0.0,
                capability_score=0.0,
                historical_score=0.0,
                explanation=f"Fallback: {fallback_reason}",
            ),
            routing_policy="fallback_default",
            routing_path="local",
            candidates=tuple(candidates),
            fallback_reason=fallback_reason,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_registry_dict(request: ModelRoutingRequest) -> AgentRegistry:
        """Convert typed ModelAgentDefinition tuple to dict format.

        TriggerMatcher expects::

            {"agents": {
                "agent-name": {
                    "activation_triggers": [...],
                    "title": "...",
                    "capabilities": [...],
                    "domain_context": "...",
                    "definition_path": "...",
                },
                ...
            }}

        The mapping is:
            ModelAgentDefinition.explicit_triggers + context_triggers -> activation_triggers
            ModelAgentDefinition.description       -> title
            ModelAgentDefinition.capabilities      -> capabilities
            ModelAgentDefinition.domain_context     -> domain_context
            ModelAgentDefinition.definition_path   -> definition_path
        """
        agents: dict[str, AgentData] = {}
        for agent_def in request.agent_registry:
            agents[agent_def.name] = {
                "activation_triggers": list(agent_def.explicit_triggers)
                + list(agent_def.context_triggers),
                "title": agent_def.description or agent_def.name,
                "capabilities": list(agent_def.capabilities),
                "domain_context": agent_def.domain_context,
                "definition_path": agent_def.definition_path or "",
            }
        return {"agents": agents}

    @staticmethod
    def _extract_explicit_agent(text: str, known_agents: set[str]) -> str | None:
        """Extract explicit agent name from request.

        Ported AS-IS from AgentRouter._extract_explicit_agent.

        Supports patterns:
        - "use agent-X" - Specific agent request
        - "@agent-X" - Specific agent request
        - "agent-X" at start of text - Specific agent request
        - "use an agent", "spawn an agent", etc. - Generic request -> polymorphic-agent

        Args:
            text: User's input text
            known_agents: Set of agent names present in the registry

        Returns:
            Agent name if found and valid, None otherwise.
        """
        try:
            text_lower = text.lower()

            # Patterns for specific agent requests (with agent name)
            # \b prevents false positives: "reuse agent-X", "misuse agent-X"
            specific_patterns = [
                r"\buse\s+(agent-[\w-]+)",  # "use agent-researcher"
                r"@(agent-[\w-]+)",  # "@agent-researcher"
                r"^(agent-[\w-]+)",  # "agent-researcher" at start
            ]

            # Check specific patterns first
            for pattern in specific_patterns:
                match = re.search(pattern, text_lower)
                if match:
                    agent_name = match.group(1)
                    # Verify agent exists in registry
                    if agent_name in known_agents:
                        logger.debug(
                            "Extracted explicit agent: %s (pattern=%s)",
                            agent_name,
                            pattern,
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
                    default_agent = _FALLBACK_AGENT
                    # Verify polymorphic-agent exists in registry
                    if default_agent in known_agents:
                        logger.debug(
                            "Generic agent request matched, using default: %s",
                            default_agent,
                        )
                        return default_agent
                    else:
                        logger.warning(
                            "Generic agent request matched but %s not in registry",
                            default_agent,
                        )

            return None

        except Exception:
            logger.warning(
                "Failed to extract explicit agent from: %s",
                text[:50],
                exc_info=True,
            )
            return None

    @staticmethod
    def _create_explicit_result(
        agent_name: str,
    ) -> ModelRoutingResult:
        """Create a routing result for an explicitly requested agent.

        Ported from AgentRouter._create_explicit_recommendation.
        Explicit requests always have 1.0 confidence across all dimensions.

        Args:
            agent_name: The explicitly requested agent name.

        Returns:
            ModelRoutingResult with routing_policy="explicit_request" and
            confidence=1.0.
        """
        breakdown = ModelConfidenceBreakdown(
            total=1.0,
            trigger_score=1.0,
            context_score=1.0,
            capability_score=1.0,
            historical_score=1.0,
            explanation="Explicit agent request",
        )
        candidate = ModelRoutingCandidate(
            agent_name=agent_name,
            confidence=1.0,
            confidence_breakdown=breakdown,
            match_reason="Explicitly requested by user",
        )
        return ModelRoutingResult(
            selected_agent=agent_name,
            confidence=1.0,
            confidence_breakdown=breakdown,
            routing_policy="explicit_request",
            routing_path="local",
            candidates=(candidate,),
            fallback_reason=None,
        )


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a float to [lo, hi] range.

    Protects against floating-point drift that could violate Pydantic
    field constraints (ge=0.0, le=1.0).
    """
    return max(lo, min(hi, value))
