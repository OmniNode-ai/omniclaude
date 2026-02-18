# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""LLM-based routing handler - uses Qwen-14B for agent selection.

Implements ProtocolAgentRouting by:
1. Using TriggerMatcher.match() for candidate generation (same as HandlerRoutingDefault)
2. Building a structured prompt with candidate names + descriptions + user prompt
3. Calling Qwen-14B via httpx (OpenAI-compatible chat completions API)
4. Parsing the response to extract the selected_agent name
5. Falling back to HandlerRoutingDefault behavior when the LLM is unavailable

Flow:
    ModelRoutingRequest
        -> check explicit agent request (@agent-name, "use agent-X")
        -> if explicit: return ModelRoutingResult(routing_policy="explicit_request")
        -> else: TriggerMatcher.match() -> collect candidates
        -> if no candidates: fallback_default
        -> else: build structured prompt, call Qwen-14B (temperature=0.0, max_tokens=50)
        -> parse response -> validate agent name exists in registry
        -> return ModelRoutingResult(routing_policy="trigger_match", routing_path="local")
        -> on LLM failure: fallback to highest-confidence trigger candidate
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

import httpx

from omniclaude.nodes.node_agent_routing_compute._internal import (
    ConfidenceScorer,
    TriggerMatcher,
)
from omniclaude.nodes.node_agent_routing_compute.handler_routing_default import (
    _clamp,
    build_registry_dict,
    create_explicit_result,
    extract_explicit_agent,
)
from omniclaude.nodes.node_agent_routing_compute.models import (
    ModelConfidenceBreakdown,
    ModelRoutingCandidate,
    ModelRoutingRequest,
    ModelRoutingResult,
)

__all__ = ["HandlerRoutingLlm"]

logger = logging.getLogger(__name__)


# Default fallback agent when no matches exceed threshold
_FALLBACK_AGENT = "polymorphic-agent"

# Maximum number of candidates to present to the LLM
_MAX_CANDIDATES = 5

# Prompt version — increment when the prompt template changes, so callers
# can detect prompt-driven regressions via the metadata field.
_ROUTING_PROMPT_VERSION = "1.0.0"

# Default LLM request settings
_LLM_TEMPERATURE = 0.0
_LLM_MAX_TOKENS = 50

# LLM call timeout in seconds (must stay well within routing budget)
_LLM_TIMEOUT_SECONDS = 4.0


def _build_routing_prompt(candidates: list[ModelRoutingCandidate], prompt: str) -> str:
    """Build a structured prompt for LLM-based agent selection.

    Presents the user prompt and candidate agents to the LLM, requesting
    the name of the single best-matching agent. The format is intentionally
    terse to stay within ``max_tokens=50`` on the response side.

    Args:
        candidates: Ranked candidate agents (max _MAX_CANDIDATES).
        prompt: The original user prompt to route.

    Returns:
        A formatted prompt string ready for chat completions.
    """
    lines: list[str] = [
        "Select the best agent for the following user request.",
        "Respond with ONLY the agent name, nothing else.",
        "",
        "Available agents:",
    ]
    for candidate in candidates:
        lines.append(f"  - {candidate.agent_name}: {candidate.match_reason}")
    lines += [
        "",
        f'User request: "{prompt[:500]}"',
        "",
        "Agent name:",
    ]
    return "\n".join(lines)


def _parse_agent_from_response(
    response_text: str, known_agents: set[str]
) -> str | None:
    """Extract a valid agent name from the LLM response.

    Strips whitespace and punctuation, then checks the text for any known
    agent name. Matching is case-insensitive and substring-based to handle
    minor LLM verbosity (e.g. "agent-debugger." or "The agent is agent-debugger").

    Args:
        response_text: Raw text from the LLM completion.
        known_agents: Set of valid agent names from the registry.

    Returns:
        The matched agent name, or None if no valid name was found.
    """
    text = response_text.strip().lower()

    # First try exact match (most common with temperature=0.0)
    if text in known_agents:
        return text

    # Try to find any known agent name as a substring.
    # Sort longest-first so more-specific names (e.g. "agent-api-architect")
    # are matched before shorter prefix names (e.g. "agent-api").
    for agent_name in sorted(known_agents, key=lambda n: (-len(n), n)):
        if agent_name in text:
            return agent_name

    return None


class HandlerRoutingLlm:
    """LLM-based routing handler that uses Qwen-14B to select agents.

    Uses TriggerMatcher for fast candidate generation, then delegates
    the final selection to Qwen-14B (via OpenAI-compatible API). Falls
    back to the highest-confidence trigger candidate when the LLM is
    unavailable or returns an unrecognized agent name.

    Attributes:
        handler_key: Registry key for handler lookup.
    """

    def __init__(
        self,
        llm_url: str,
        model_name: str = "Qwen2.5-14B",
        timeout: float = _LLM_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize the LLM routing handler.

        Args:
            llm_url: Base URL for the OpenAI-compatible chat completions
                endpoint (e.g. "http://192.168.86.100:8200").
            model_name: Model identifier sent in the API request.
            timeout: HTTP request timeout in seconds.
        """
        self._llm_url = llm_url.rstrip("/")
        self._model_name = model_name
        self._timeout = timeout

    @property
    def handler_key(self) -> str:
        """Backend identifier for handler routing."""
        return "llm"

    async def compute_routing(
        self,
        request: ModelRoutingRequest,
        correlation_id: UUID | None = None,
    ) -> ModelRoutingResult:
        """Compute a routing decision using LLM-based agent selection.

        Generates candidates via TriggerMatcher, then asks Qwen-14B to
        select the best one. Falls back to the highest-confidence trigger
        candidate when the LLM call fails or returns an unrecognised name.

        Args:
            request: Routing request with prompt, agent registry, and thresholds.
            correlation_id: Optional override for tracing. Falls back to
                request.correlation_id if None.

        Returns:
            ModelRoutingResult with selected agent and routing metadata,
            including ``routing_prompt_version`` in the candidates tuple's
            match_reason for the winning candidate.
        """
        cid = correlation_id or request.correlation_id

        # 1. Convert registry to dict format expected by TriggerMatcher
        registry_dict = build_registry_dict(request)
        agent_names = set(registry_dict["agents"].keys())

        # 2. Check for explicit agent request (@agent-name, "use agent-X")
        explicit_agent = extract_explicit_agent(request.prompt, agent_names)
        if explicit_agent is not None:
            logger.debug(
                "Explicit agent request detected: %s (correlation_id=%s)",
                explicit_agent,
                cid,
            )
            return create_explicit_result(explicit_agent)

        # 3. Run TriggerMatcher to generate candidates
        try:
            matcher = TriggerMatcher(registry_dict)
            trigger_matches = matcher.match(request.prompt)
        except Exception:
            logger.exception("TriggerMatcher.match() failed (correlation_id=%s)", cid)
            trigger_matches = []

        # 4. Score candidates via ConfidenceScorer
        scorer = ConfidenceScorer()
        candidates: list[ModelRoutingCandidate] = []

        for agent_name, trigger_score, match_reason in trigger_matches:
            agent_data = registry_dict["agents"].get(agent_name, {})
            try:
                confidence = scorer.score(
                    agent_name=agent_name,
                    agent_data=agent_data,
                    user_request=request.prompt,
                    context={},
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

        # 5. Sort by confidence, cap at _MAX_CANDIDATES
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        candidates = candidates[:_MAX_CANDIDATES]

        # 6. No trigger candidates: fall through to fallback
        if not candidates:
            return self._make_fallback(
                candidates=(),
                reason="No agents matched any trigger patterns",
            )

        # 7. Filter by confidence threshold
        above_threshold = [
            c for c in candidates if c.confidence >= request.confidence_threshold
        ]
        if not above_threshold:
            reason = (
                f"Best match {candidates[0].agent_name} "
                f"({candidates[0].confidence:.2f}) below "
                f"threshold {request.confidence_threshold:.2f}"
            )
            return self._make_fallback(candidates=tuple(candidates), reason=reason)

        # 8. Ask LLM to pick the best candidate.
        # Only pass the names of above-threshold candidates as valid choices so
        # the LLM cannot select an agent that failed to meet the confidence
        # threshold.
        above_threshold_names = {c.agent_name for c in above_threshold}
        selected_agent = await self._ask_llm(
            candidates=above_threshold,
            prompt=request.prompt,
            agent_names=above_threshold_names,
            correlation_id=cid,
        )

        # 9. LLM did not return a usable name: fall back to top trigger match
        if selected_agent is None:
            best = above_threshold[0]
            logger.info(
                "LLM returned no valid agent; using top trigger match %s "
                "(correlation_id=%s)",
                best.agent_name,
                cid,
            )
            return ModelRoutingResult(
                selected_agent=best.agent_name,
                confidence=best.confidence,
                confidence_breakdown=best.confidence_breakdown,
                routing_policy="trigger_match",
                routing_path="local",
                candidates=tuple(candidates),
                fallback_reason="LLM unavailable or returned unrecognised agent; "
                "using top trigger match",
            )

        # 10. Build result with LLM-selected agent
        # Find the candidate record for the LLM's choice (for its breakdown)
        llm_candidate = next(
            (c for c in candidates if c.agent_name == selected_agent),
            above_threshold[
                0
            ],  # safe: selected_agent was validated against agent_names
        )

        # Capture the winning candidate's confidence breakdown for the result
        breakdown = llm_candidate.confidence_breakdown
        logger.debug(
            "LLM selected %s (routing_prompt_version=%s, correlation_id=%s)",
            selected_agent,
            _ROUTING_PROMPT_VERSION,
            cid,
        )

        # Rebuild candidates tuple with prompt version annotation on winner
        annotated_candidates = tuple(
            ModelRoutingCandidate(
                agent_name=c.agent_name,
                confidence=c.confidence,
                confidence_breakdown=c.confidence_breakdown,
                match_reason=(
                    f"{c.match_reason} [llm_selected, prompt_v{_ROUTING_PROMPT_VERSION}]"
                    if c.agent_name == selected_agent
                    else c.match_reason
                ),
            )
            for c in candidates
        )

        return ModelRoutingResult(
            selected_agent=selected_agent,
            confidence=llm_candidate.confidence,
            confidence_breakdown=breakdown,
            routing_policy="trigger_match",
            routing_path="local",
            candidates=annotated_candidates,
            fallback_reason=None,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _ask_llm(
        self,
        candidates: list[ModelRoutingCandidate],
        prompt: str,
        agent_names: set[str],
        correlation_id: UUID,
    ) -> str | None:
        """Send a chat completion request and parse the agent name from the response.

        Args:
            candidates: Ranked candidates to present to the LLM.
            prompt: The original user prompt.
            agent_names: All valid agent names (for response validation).
            correlation_id: For logging.

        Returns:
            A validated agent name from the LLM, or None on failure.
        """
        routing_prompt = _build_routing_prompt(candidates, prompt)

        payload = {
            "model": self._model_name,
            "messages": [{"role": "user", "content": routing_prompt}],
            "temperature": _LLM_TEMPERATURE,
            "max_tokens": _LLM_MAX_TOKENS,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._llm_url}/v1/chat/completions",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            logger.warning(
                "LLM routing call timed out after %.1fs (correlation_id=%s)",
                self._timeout,
                correlation_id,
            )
            return None
        except httpx.HTTPError as exc:
            logger.warning(
                "LLM routing HTTP error: %s (correlation_id=%s)",
                exc,
                correlation_id,
            )
            return None
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning(
                "LLM routing response parse error: %s (correlation_id=%s)",
                exc,
                correlation_id,
            )
            return None

        try:
            raw_text: str = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning(
                "LLM routing response missing expected fields: %s (correlation_id=%s)",
                exc,
                correlation_id,
            )
            return None

        selected = _parse_agent_from_response(raw_text, agent_names)
        if selected is None:
            logger.warning(
                "LLM returned unrecognised agent name %r (correlation_id=%s)",
                raw_text[:100],
                correlation_id,
            )
        return selected

    @staticmethod
    def _make_fallback(
        candidates: tuple[ModelRoutingCandidate, ...],
        reason: str,
    ) -> ModelRoutingResult:
        """Return a fallback routing result.

        Args:
            candidates: All evaluated candidates (may be empty).
            reason: Human-readable reason for the fallback.

        Returns:
            ModelRoutingResult with routing_policy="fallback_default".
        """
        return ModelRoutingResult(
            selected_agent=_FALLBACK_AGENT,
            confidence=0.0,
            confidence_breakdown=ModelConfidenceBreakdown(
                total=0.0,
                trigger_score=0.0,
                context_score=0.0,
                capability_score=0.0,
                historical_score=0.0,
                explanation=f"Fallback: {reason}",
            ),
            routing_policy="fallback_default",
            routing_path="local",
            candidates=candidates,
            fallback_reason=reason,
        )
