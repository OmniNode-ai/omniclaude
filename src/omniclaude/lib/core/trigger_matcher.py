"""
Trigger Matcher - Phase 1
==========================

Provides fuzzy matching and scoring for agent triggers.
Uses multiple matching strategies:
- Exact substring matching
- Fuzzy string similarity (SequenceMatcher)
- Keyword overlap scoring
- Capability matching
"""

import re
from difflib import SequenceMatcher


class TriggerMatcher:
    """
    Advanced trigger matching with fuzzy logic and scoring.

    Builds an inverted index of triggers for fast lookup and provides
    multiple matching strategies with confidence scoring.
    """

    def __init__(self, agent_registry: dict):
        """
        Initialize matcher with agent registry.

        Args:
            agent_registry: Loaded YAML registry with agent definitions

        Raises:
            ValueError: If registry structure is invalid (missing 'agents' key
                or agents is not a dictionary)
        """
        self._validate_registry(agent_registry)
        self.registry = agent_registry
        self.trigger_index = self._build_trigger_index()

    def _validate_registry(self, registry: dict) -> None:
        """
        Validate registry structure before use.

        Args:
            registry: Registry dictionary to validate

        Raises:
            ValueError: If registry structure is invalid
        """
        if not isinstance(registry, dict):
            raise ValueError(f"Registry must be a dictionary, got {type(registry).__name__}")
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
        """
        Build inverted index of triggers -> agent names.

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
        """
        Match user request against agent triggers.

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
        matches = []

        # Extract keywords from request
        keywords = self._extract_keywords(user_request)

        for agent_name, agent_data in self.registry["agents"].items():
            triggers = agent_data.get("activation_triggers", [])

            # Calculate match scores
            scores = []

            # 1. Exact trigger match with word boundary checks
            for trigger in triggers:
                if self._exact_match_with_word_boundaries(trigger, user_lower):
                    # Apply context filtering for short triggers
                    if self._is_context_appropriate(trigger, user_request, agent_name):
                        scores.append((1.0, f"Exact match: '{trigger}'"))

            # 2. Fuzzy trigger match with context filtering
            for trigger in triggers:
                similarity = self._fuzzy_match(trigger.lower(), user_lower)
                if similarity > 0.7:
                    # Apply context filtering for short triggers
                    if self._is_context_appropriate(trigger, user_request, agent_name):
                        scores.append(
                            (
                                similarity * 0.9,
                                f"Fuzzy match: '{trigger}' ({similarity:.0%})",
                            )
                        )

            # 3. Keyword overlap
            keyword_score = self._keyword_overlap_score(keywords, triggers)
            if keyword_score > 0.5:
                scores.append((keyword_score * 0.8, f"Keyword overlap ({keyword_score:.0%})"))

            # 4. Capability match
            capabilities = agent_data.get("capabilities", [])
            cap_score = self._capability_match_score(keywords, capabilities)
            if cap_score > 0.5:
                scores.append((cap_score * 0.7, f"Capability match ({cap_score:.0%})"))

            if scores:
                # Take best score
                best_score, reason = max(scores, key=lambda x: x[0])
                matches.append((agent_name, best_score, reason))

        # Sort by confidence
        matches.sort(key=lambda x: x[1], reverse=True)

        return matches

    def _extract_keywords(self, text: str) -> list[str]:
        """
        Extract meaningful keywords from text.

        Filters out common stopwords and short words.

        Args:
            text: Input text

        Returns:
            List of extracted keywords
        """
        # Common stopwords to filter
        stopwords = {
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

        # Split on whitespace and punctuation
        words = re.findall(r"\b\w+\b", text.lower())

        # Filter stopwords and short words
        keywords = [w for w in words if w not in stopwords and len(w) > 2]

        return keywords

    def _fuzzy_match(self, trigger: str, text: str) -> float:
        """
        Calculate fuzzy match score using SequenceMatcher.

        Args:
            trigger: Trigger phrase to match
            text: User input text

        Returns:
            Similarity score (0.0-1.0)
        """
        # Check if trigger matches with word boundaries first
        if self._exact_match_with_word_boundaries(trigger, text):
            return 1.0

        # For better fuzzy matching, check against individual words in the text
        # not just the entire text (which fails for length differences)
        words = re.findall(r"\b\w+\b", text.lower())

        # Check similarity against each word
        best_word_score = 0.0
        for word in words:
            word_score = SequenceMatcher(None, trigger, word).ratio()
            best_word_score = max(best_word_score, word_score)

        # Also check against entire text (for multi-word triggers)
        full_text_score = SequenceMatcher(None, trigger, text).ratio()

        # Return the best score
        return max(best_word_score, full_text_score)

    def _keyword_overlap_score(self, keywords: list[str], triggers: list[str]) -> float:
        """
        Calculate keyword overlap score.

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

    def _capability_match_score(self, keywords: list[str], capabilities: list[str]) -> float:
        """
        Calculate capability match score.

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
        """
        Check if trigger matches with word boundaries.

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

    def _is_context_appropriate(self, trigger: str, user_request: str, agent_name: str) -> bool:
        """
        Check if trigger match is contextually appropriate.

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

        # HIGH-CONFIDENCE TECHNICAL TRIGGERS
        # These domain-specific keywords are unambiguous and don't require action context
        # They should always match when present in user requests
        high_confidence_triggers = {
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

        # Bypass strict action context requirement for high-confidence triggers
        if trigger_lower in high_confidence_triggers:
            return True

        # Check for technical/architectural context first (strongest signal)
        # These patterns indicate NOT an agent invocation
        technical_patterns = [
            r"\bpolymorphic\s+(architecture|design|pattern|approach|system|code|style)\b",
            r"\bpolymorphism\b",
            r"\bpollyanna\b",
            r"\b(the|a|an)\s+polymorphic\s+(design|pattern|architecture|approach)\b",
            r"\busing\s+polymorphi",  # "using polymorphism"
            r"\b(poly|polly)\s+(suggested|mentioned|said|thinks|believes)\b",  # Casual reference
        ]

        for pattern in technical_patterns:
            if re.search(pattern, request_lower):
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
                r"\b" + re.escape(trigger_lower) + r"\b.*(agent|coordinator|for workflow)",
            ]
            for pattern in action_patterns:
                if re.search(pattern, request_lower):
                    return True
            # No action context found for long trigger
            return False

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

        for pattern in action_patterns:
            if re.search(pattern, request_lower):
                return True  # Strong signal of agent invocation

        # Default for short triggers without action context: REJECT
        # This is more conservative but prevents false positives
        return False


# Standalone test
if __name__ == "__main__":
    from pathlib import Path

    import yaml

    registry_path = Path.home() / ".claude" / "agents" / "onex" / "agent-registry.yaml"

    if registry_path.exists():
        with open(registry_path) as f:
            registry = yaml.safe_load(f)

        matcher = TriggerMatcher(registry)

        # Test queries
        test_queries = [
            "debug this error",
            "optimize my database queries",
            "review API security",
            "create CI/CD pipeline",
        ]

        for query in test_queries:
            print(f"\nQuery: {query}")
            matches = matcher.match(query)[:3]  # Top 3
            for agent, score, reason in matches:
                print(f"  {agent}: {score:.2f} - {reason}")
    else:
        print(f"Registry not found at: {registry_path}")
