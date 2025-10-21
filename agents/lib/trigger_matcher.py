"""
Enhanced Trigger Matcher - Phase 1
==================================

Provides fuzzy matching and scoring for agent triggers.
Uses multiple matching strategies:
- Exact substring matching
- Fuzzy string similarity (SequenceMatcher)
- Keyword overlap scoring
- Capability matching
"""

import re
from difflib import SequenceMatcher
from typing import Dict, List, Tuple


class EnhancedTriggerMatcher:
    """
    Advanced trigger matching with fuzzy logic and scoring.

    Builds an inverted index of triggers for fast lookup and provides
    multiple matching strategies with confidence scoring.
    """

    def __init__(self, agent_registry: Dict):
        """
        Initialize matcher with agent registry.

        Args:
            agent_registry: Loaded YAML registry with agent definitions
        """
        self.registry = agent_registry
        self.trigger_index = self._build_trigger_index()

    def _build_trigger_index(self) -> Dict[str, List[str]]:
        """
        Build inverted index of triggers -> agent names.

        Returns:
            Dictionary mapping lowercase triggers to list of agent names
        """
        index = {}
        for agent_name, agent_data in self.registry["agents"].items():
            triggers = agent_data.get("activation_triggers", [])
            for trigger in triggers:
                trigger_lower = trigger.lower()
                if trigger_lower not in index:
                    index[trigger_lower] = []
                index[trigger_lower].append(agent_name)
        return index

    def match(self, user_request: str) -> List[Tuple[str, float, str]]:
        """
        Match user request against agent triggers.

        Uses multiple scoring strategies:
        1. Exact trigger match (score: 1.0)
        2. Fuzzy trigger match (score: 0.7-0.9 based on similarity)
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

            # 1. Exact trigger match
            for trigger in triggers:
                if trigger.lower() in user_lower:
                    scores.append((1.0, f"Exact match: '{trigger}'"))

            # 2. Fuzzy trigger match
            for trigger in triggers:
                similarity = self._fuzzy_match(trigger.lower(), user_lower)
                if similarity > 0.7:
                    scores.append(
                        (
                            similarity * 0.9,
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

        # Sort by confidence
        matches.sort(key=lambda x: x[1], reverse=True)

        return matches

    def _extract_keywords(self, text: str) -> List[str]:
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
        # Check if trigger is substring first
        if trigger in text:
            return 1.0

        # Use SequenceMatcher for similarity
        return SequenceMatcher(None, trigger, text).ratio()

    def _keyword_overlap_score(self, keywords: List[str], triggers: List[str]) -> float:
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

    def _capability_match_score(
        self, keywords: List[str], capabilities: List[str]
    ) -> float:
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


# Standalone test
if __name__ == "__main__":
    from pathlib import Path

    import yaml

    registry_path = (
        Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml"
    )

    if registry_path.exists():
        with open(registry_path) as f:
            registry = yaml.safe_load(f)

        matcher = EnhancedTriggerMatcher(registry)

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
