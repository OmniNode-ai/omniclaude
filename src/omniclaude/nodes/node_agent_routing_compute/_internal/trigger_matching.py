# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Trigger Matcher - Phase 1.

Provides fuzzy matching and scoring for agent triggers.
Uses multiple matching strategies:
- Exact substring matching
- Fuzzy string similarity (SequenceMatcher) with tiered thresholds
- Keyword overlap scoring
- Capability matching

Ported from agent_router.py TriggerMatcher with the following source
invariants preserved:
- Deterministic iteration (sorted agent names)
- HARD_FLOOR (0.55) noise filtering
- Tiered fuzzy thresholds by trigger length
- Multi-word specificity bonus
- Technical token preservation (s3, ml, ai, etc.)
- No full-text SequenceMatcher comparison (intentionally omitted)

Pure Python - NO ONEX imports.
"""

from __future__ import annotations

import math
import re
from difflib import SequenceMatcher
from typing import TypedDict

from .confidence_scoring import AgentData

__all__ = ["AgentRegistry", "TriggerMatcher"]


class AgentRegistry(TypedDict):
    """Agent registry structure expected by TriggerMatcher."""

    agents: dict[str, AgentData]


# Hard floor: remove matches below noise threshold.
# HARD_FLOOR is a safety invariant, not a tuning knob.
HARD_FLOOR = 0.55


class TriggerMatcher:
    """Advanced trigger matching with fuzzy logic and scoring.

    Builds an inverted index of triggers for fast lookup and provides
    multiple matching strategies with confidence scoring.
    """

    # HIGH-CONFIDENCE TECHNICAL TRIGGERS
    # These domain-specific keywords are unambiguous and don't require action context.
    # They should always match when present in user requests.
    _HIGH_CONFIDENCE_TRIGGERS = frozenset(
        {
            # Debugging & Error Handling
            "debug",
            "error",
            "bug",
            "troubleshoot",
            "investigate",
            "diagnose",
            "fix",
            "resolve",
            "issue",
            "problem",
            "failure",
            "crash",
            # Testing & Quality
            "test",
            "testing",
            "quality",
            "coverage",
            "validate",
            "verify",
            # Performance & Optimization
            "optimize",
            "performance",
            "benchmark",
            "bottleneck",
            "profile",
            "efficiency",
            "speed",
            "slow",
            "latency",
            # Security & Compliance
            "security",
            "audit",
            "vulnerability",
            "penetration",
            "compliance",
            "threat",
            "risk",
            "secure",
            # Development Operations
            "deploy",
            "deployment",
            "infrastructure",
            "devops",
            "pipeline",
            "container",
            "kubernetes",
            "docker",
            "monitor",
            "observability",
            # Documentation & Research
            "document",
            "docs",
            "research",
            "analyze",
            "analysis",
            # API & Architecture
            "api",
            "endpoint",
            "microservice",
            "architecture",
            "design",
            # Frontend & Backend
            "frontend",
            "backend",
            "react",
            "typescript",
            "python",
            "fastapi",
        }
    )

    # Patterns that indicate technical/architectural usage, NOT agent invocation.
    _TECHNICAL_PATTERNS = tuple(
        re.compile(p)
        for p in (
            r"\bpolymorphic\s+(architecture|design|pattern|approach|system|code|style)\b",
            r"\bpolymorphism\b",
            r"\bpollyanna\b",
            r"\b(the|a|an)\s+polymorphic\s+(design|pattern|architecture|approach)\b",
            r"\busing\s+polymorphi",
            r"\b(poly|polly)\s+(suggested|mentioned|said|thinks|believes)\b",
        )
    )

    # Common stopwords to filter from keyword extraction
    STOPWORDS = frozenset(
        {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "as",
            "is",
            "was",
            "are",
            "were",
            "been",
            "be",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "should",
            "could",
            "may",
            "might",
            "must",
            "can",
            "this",
            "that",
            "these",
            "those",
            "i",
            "you",
            "he",
            "she",
            "it",
            "we",
            "they",
            "me",
            "him",
            "her",
            "us",
            "them",
            "my",
            "your",
            "his",
            "its",
            "our",
            "their",
        }
    )

    # Short alphanumeric technical tokens that should be preserved during
    # keyword extraction even when below the default length threshold.
    # These tokens are domain-significant (e.g., cloud services, protocols).
    _TECHNICAL_TOKENS = frozenset({"s3", "k8", "ec2", "ml", "ai", "ci", "cd", "db"})

    def __init__(self, agent_registry: AgentRegistry):
        """Initialize matcher with agent registry.

        Args:
            agent_registry: Loaded YAML registry with agent definitions

        Raises:
            ValueError: If registry structure is invalid (missing 'agents' key
                or agents is not a dictionary)
        """
        self._validate_registry(agent_registry)
        self.registry = agent_registry
        self.trigger_index = self._build_trigger_index()

    def _validate_registry(self, registry: AgentRegistry) -> None:
        """Validate registry structure before use.

        Args:
            registry: Registry dictionary to validate

        Raises:
            ValueError: If registry structure is invalid
        """
        if not isinstance(registry, dict):
            raise ValueError(
                f"Registry must be a dictionary, got {type(registry).__name__}"
            )
        if "agents" not in registry:
            raise ValueError(
                "Registry must contain 'agents' key. "
                "Expected structure: {'agents': {'agent-name': {...}, ...}}"
            )
        if not isinstance(registry["agents"], dict):
            raise ValueError(
                f"Registry 'agents' must be a dictionary, got {type(registry['agents']).__name__}"
            )

    def _build_trigger_index(self) -> dict[str, list[str]]:
        """Build inverted index of triggers -> agent names.

        Returns:
            Dictionary mapping lowercase triggers to list of agent names
        """
        index: dict[str, list[str]] = {}
        for agent_name, agent_data in self.registry["agents"].items():
            triggers = agent_data.get("activation_triggers", [])
            for trigger in triggers:
                trigger_lower = trigger.lower()
                if trigger_lower not in index:
                    index[trigger_lower] = []
                index[trigger_lower].append(agent_name)
        return index

    def match(self, user_request: str) -> list[tuple[str, float, str]]:
        """Match user request against agent triggers.

        Uses multiple scoring strategies:
        1. Exact trigger match (score: 1.0) with word boundary checks
        2. Fuzzy trigger match (score: 0.7-0.9 based on similarity) with context filtering
        3. Keyword overlap (score: 0.5-0.8 based on overlap)
        4. Capability match (score: 0.5-0.7 based on capability alignment)

        Args:
            user_request: User's input text

        Returns:
            List of (agent_name, confidence_score, match_reason)
            Sorted by confidence (highest first)
        """
        user_lower = user_request.lower()
        matches: list[tuple[str, float, str]] = []

        # Extract keywords from request
        keywords = self._extract_keywords(user_request)

        # Sort agents by name for deterministic iteration order.
        for agent_name, agent_data in sorted(self.registry["agents"].items()):
            triggers = agent_data.get("activation_triggers", [])

            # Calculate match scores
            scores: list[tuple[float, str]] = []

            # 1. Exact trigger match with word boundary checks
            for trigger in triggers:
                if self._exact_match_with_word_boundaries(trigger, user_lower):
                    # Apply context filtering for short triggers
                    if self._is_context_appropriate(trigger, user_request, agent_name):
                        scores.append((1.0, f"Exact match: '{trigger}'"))

            # 2. Fuzzy trigger match (tiered thresholds, multi-word bonus)
            for trigger in triggers:
                similarity = self._fuzzy_match(trigger.lower(), user_lower)
                if similarity > 0.7:
                    # Apply context filtering for short triggers
                    if self._is_context_appropriate(trigger, user_request, agent_name):
                        # Multi-word triggers are more specific -> monotonic bonus
                        word_count = len(trigger.split())
                        specificity_bonus = (
                            min(math.log(word_count) * 0.05, 0.08)
                            if word_count > 1
                            else 0.0
                        )
                        rank_score = similarity * 0.9 + specificity_bonus
                        scores.append(
                            (
                                rank_score,
                                f"Fuzzy match: '{trigger}' ({similarity:.0%})",
                            )
                        )

            # 3. Keyword overlap
            keyword_score = self._keyword_overlap_score(keywords, triggers)
            if keyword_score > 0.5:
                scores.append(
                    (keyword_score * 0.8, f"Keyword overlap ({keyword_score:.0%})")
                )

            # 4. Capability match
            capabilities = agent_data.get("capabilities", [])
            cap_score = self._capability_match_score(keywords, capabilities)
            if cap_score > 0.5:
                scores.append((cap_score * 0.7, f"Capability match ({cap_score:.0%})"))

            if scores:
                # Take best score
                best_score, reason = max(scores, key=lambda x: x[0])
                matches.append((agent_name, best_score, reason))

        # Hard floor: remove matches below noise threshold.
        # HARD_FLOOR is a safety invariant, not a tuning knob.
        matches = [
            (name, score, reason)
            for name, score, reason in matches
            if score >= HARD_FLOOR
        ]

        # Sort by confidence
        matches.sort(key=lambda x: x[1], reverse=True)

        return matches

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract meaningful keywords from text.

        Preserves short alphanumeric technical tokens (e.g., "s3", "k8", "ec2")
        that would otherwise be dropped by the length filter.

        Args:
            text: Input text

        Returns:
            List of extracted keywords
        """
        words = re.findall(r"\b\w+\b", text.lower())
        return [
            w
            for w in words
            if w not in self.STOPWORDS and (len(w) > 2 or w in self._TECHNICAL_TOKENS)
        ]

    @staticmethod
    def _fuzzy_threshold(trigger: str) -> float:
        """Dynamic threshold: shorter triggers need higher similarity.

        Short words (<=6 chars) like "react", "debug" have high character
        overlap with unrelated words. Longer triggers are more specific.
        """
        n = len(trigger)
        if n <= 6:
            return 0.85
        elif n <= 10:
            return 0.78
        else:
            return 0.72

    def _fuzzy_match(self, trigger: str, text: str) -> float:
        """Calculate fuzzy match score using SequenceMatcher.

        Uses tiered thresholds based on trigger length to prevent
        false positives from short-word character overlap.
        Full-text comparison is intentionally omitted (pure noise).
        Terminates early on perfect word match to avoid unnecessary iteration.

        Args:
            trigger: Trigger phrase to match
            text: User input text

        Returns:
            Similarity score (0.0-1.0)
        """
        if self._exact_match_with_word_boundaries(trigger, text):
            return 1.0

        min_threshold = self._fuzzy_threshold(trigger)

        words = re.findall(r"\b\w+\b", text.lower())
        best_word_score = 0.0
        for word in words:
            word_score = SequenceMatcher(None, trigger, word).ratio()
            if word_score >= min_threshold:
                best_word_score = max(best_word_score, word_score)
                if best_word_score >= 1.0:
                    break  # Perfect match; no further iteration needed

        return best_word_score

    def _keyword_overlap_score(self, keywords: list[str], triggers: list[str]) -> float:
        """Calculate keyword overlap score.

        Measures how many user keywords appear in agent triggers.

        Args:
            keywords: Extracted keywords from user request
            triggers: Agent's activation triggers

        Returns:
            Overlap score (0.0-1.0)
        """
        if not keywords or not triggers:
            return 0.0

        # Flatten triggers into words
        trigger_words = set()
        for trigger in triggers:
            trigger_words.update(re.findall(r"\b\w+\b", trigger.lower()))

        # Calculate overlap
        keyword_set = set(keywords)
        overlap = len(keyword_set & trigger_words)

        return overlap / len(keyword_set) if keyword_set else 0.0

    def _capability_match_score(
        self, keywords: list[str], capabilities: list[str]
    ) -> float:
        """Calculate capability match score.

        Measures how many user keywords align with agent capabilities.

        Args:
            keywords: Extracted keywords from user request
            capabilities: Agent's capabilities

        Returns:
            Capability match score (0.0-1.0)
        """
        if not keywords or not capabilities:
            return 0.0

        # Flatten capabilities into words
        capability_words = set()
        for cap in capabilities:
            capability_words.update(re.findall(r"\b\w+\b", cap.lower()))

        # Calculate overlap
        keyword_set = set(keywords)
        overlap = len(keyword_set & capability_words)

        return overlap / len(keyword_set) if keyword_set else 0.0

    def _exact_match_with_word_boundaries(self, trigger: str, text: str) -> bool:
        """Check if trigger matches with word boundaries.

        Prevents matching "poly" in "polymorphic" or "polly" in "pollyanna".
        Also prevents "use an agent" from matching "misuse an agent".

        Args:
            trigger: Trigger phrase to match
            text: User input text (lowercase)

        Returns:
            True if trigger matches as whole word(s), False otherwise
        """
        trigger_lower = trigger.lower()

        # Use word boundary regex for both single-word and multi-word triggers
        # This prevents false positives like:
        # - "use an agent" matching "misuse an agent"
        # - "spawn an agent" matching "respawn an agent"
        # - "poly" matching "polymorphic"
        pattern = r"\b" + re.escape(trigger_lower) + r"\b"
        return bool(re.search(pattern, text))

    def _is_context_appropriate(
        self, trigger: str, user_request: str, agent_name: str
    ) -> bool:
        """Check if trigger match is contextually appropriate.

        Filters out false positives where triggers like "poly" or "polly"
        appear in technical terms or casual references rather than agent invocations.

        Args:
            trigger: Matched trigger
            user_request: Full user request
            agent_name: Agent name being evaluated

        Returns:
            True if context suggests agent invocation, False for technical/casual usage
        """
        trigger_lower = trigger.lower()
        request_lower = user_request.lower()

        # Bypass strict action context requirement for high-confidence triggers
        if trigger_lower in self._HIGH_CONFIDENCE_TRIGGERS:
            return True

        # Check for technical/architectural context first (strongest signal)
        # These patterns indicate NOT an agent invocation
        for pattern in self._TECHNICAL_PATTERNS:
            if pattern.search(request_lower):
                return False  # Strong signal of technical/casual usage

        # For multi-word triggers, allow them (high confidence they're agent references)
        if len(trigger_lower.split()) > 1:
            return True

        # For longer single-word triggers (>6 chars), check if they're part of trigger list
        # "polymorphic" is 11 chars, but only allow if in action context
        if len(trigger_lower) > 6:
            # Must have action context to match
            action_patterns = [
                r"\b(use|spawn|dispatch|coordinate|invoke|call|run|execute|trigger)\b.*\b"
                + re.escape(trigger_lower)
                + r"\b",
                r"\b"
                + re.escape(trigger_lower)
                + r"\b.*(agent|coordinator|for workflow)",
            ]
            return any(re.search(pattern, request_lower) for pattern in action_patterns)

        # For short triggers like "poly" or "polly":
        # Require action/invocation context
        action_patterns = [
            r"\b(use|spawn|dispatch|coordinate|invoke|call|run|execute|trigger)\b.*\b"
            + re.escape(trigger_lower)
            + r"\b",
            r"\b"
            + re.escape(trigger_lower)
            + r"\b.*(coordinate|manage|handle|execute|for workflow)",
        ]

        return any(re.search(pattern, request_lower) for pattern in action_patterns)
