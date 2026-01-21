"""
Relevance Scorer - Keyword-based scoring for manifest items.

Scores patterns and schemas by relevance to user's task using:
1. Keyword matching (60% weight)
2. Task-specific heuristics (40% weight)

Part of Phase 3: Relevance Scoring implementation.
"""

from pathlib import Path
from typing import Any

# Import TaskClassifier types with fallback for standalone usage
try:
    from .task_classifier import TaskContext, TaskIntent
except ImportError:
    # Standalone usage: add lib directory to path
    import sys

    _lib_path = Path(__file__).parent
    if str(_lib_path) not in sys.path:
        sys.path.insert(0, str(_lib_path))

    from task_classifier import TaskContext, TaskIntent  # noqa: F811


class RelevanceScorer:
    """
    Score manifest items by relevance to user's task.

    Uses keyword-based scoring (no embeddings initially):
    1. Keyword matching - 60% weight
    2. Task-specific heuristics - 40% weight
    """

    def __init__(self):
        """Initialize relevance scorer."""
        pass

    def score_pattern_relevance(
        self,
        pattern: dict[str, Any],
        task_context: TaskContext,
        user_prompt: str,
    ) -> float:
        """
        Score pattern relevance (0.0 - 1.0).

        Args:
            pattern: Pattern dict with name, description, node_types, etc.
            task_context: Classified task context
            user_prompt: Original user prompt

        Returns:
            Relevance score (0.0 = irrelevant, 1.0 = highly relevant)
        """
        score = 0.0

        # 1. Keyword matching (50% weight)
        keyword_score = self._compute_keyword_match(pattern, task_context)
        score += keyword_score * 0.5

        # 2. Task-specific heuristics (30% weight)
        heuristic_score = self._compute_heuristic_score(pattern, task_context)
        score += heuristic_score * 0.3

        # 3. Entity matching (20% weight) - NEW
        entity_score = self._compute_entity_match(pattern, task_context, user_prompt)
        score += entity_score * 0.2

        return min(score, 1.0)

    def score_schema_relevance(
        self,
        schema: dict[str, Any],
        task_context: TaskContext,
        user_prompt: str,
    ) -> float:
        """
        Score database schema relevance (0.0 - 1.0).

        Args:
            schema: Schema dict with table_name, columns, etc.
            task_context: Classified task context
            user_prompt: Original user prompt

        Returns:
            Relevance score (0.0 = irrelevant, 1.0 = highly relevant)
        """
        score = 0.0

        table_name = schema.get("table_name", "").lower()
        prompt_lower = user_prompt.lower()

        # Direct table name match in prompt = highly relevant
        if table_name in prompt_lower:
            score += 1.0

        # Table name contains keywords
        for keyword in task_context.keywords:
            if keyword in table_name:
                score += 0.3

        # Mentioned in entities
        if table_name in [e.lower() for e in task_context.entities]:
            score += 0.5

        return min(score, 1.0)

    def _compute_keyword_match(
        self,
        pattern: dict[str, Any],
        task_context: TaskContext,
    ) -> float:
        """
        Compute keyword match score.

        Args:
            pattern: Pattern dict with name, description, etc.
            task_context: Classified task context

        Returns:
            Score between 0.0 and 1.0
        """
        pattern_name = pattern.get("name", "").lower()
        pattern_description = pattern.get("description", "").lower()
        pattern_text = pattern_name + " " + pattern_description

        if not task_context.keywords:
            return 0.0

        # Count matches in full text
        matches = sum(1 for kw in task_context.keywords if kw in pattern_text)

        # Bonus for matches in pattern name (more significant)
        name_matches = sum(1 for kw in task_context.keywords if kw in pattern_name)

        # Base score from all matches
        base_score = matches / len(task_context.keywords)

        # Boost score if keywords appear in pattern name (30% bonus)
        if name_matches > 0:
            name_boost = (name_matches / len(task_context.keywords)) * 0.3
            return min(base_score + name_boost, 1.0)

        return base_score

    def _compute_entity_match(
        self,
        pattern: dict[str, Any],
        task_context: TaskContext,
        user_prompt: str,
    ) -> float:
        """
        Compute entity match score.

        Checks if entities (file names, table names, service names) from the prompt
        appear in the pattern name or description.

        Args:
            pattern: Pattern dict with name, description, etc.
            task_context: Classified task context
            user_prompt: Original user prompt

        Returns:
            Score between 0.0 and 1.0
        """
        pattern_name = pattern.get("name", "").lower()
        pattern_description = pattern.get("description", "").lower()
        pattern_text = pattern_name + " " + pattern_description
        prompt_lower = user_prompt.lower()

        score = 0.0

        # Check for entity matches in pattern text
        if task_context.entities:
            entity_matches = sum(
                1 for entity in task_context.entities if entity.lower() in pattern_text
            )
            if entity_matches > 0:
                score += 0.5

        # Check for service mentions (PostgreSQL, Kafka, etc.)
        if task_context.mentioned_services:
            service_matches = sum(
                1
                for service in task_context.mentioned_services
                if service.lower() in pattern_text
            )
            if service_matches > 0:
                score += 0.5

        # Bonus: Direct keyword from prompt appears in pattern name
        # (e.g., "connection" in prompt → "Connection" in pattern name)
        prompt_words = set(prompt_lower.split())
        # Filter out common words
        common_words = {
            "the",
            "a",
            "an",
            "in",
            "on",
            "at",
            "to",
            "for",
            "with",
            "from",
            "by",
        }
        significant_words = prompt_words - common_words

        name_word_matches = sum(
            1 for word in significant_words if len(word) > 3 and word in pattern_name
        )
        if name_word_matches > 0:
            score += 0.3

        return min(score, 1.0)

    def _compute_heuristic_score(
        self,
        pattern: dict[str, Any],
        task_context: TaskContext,
    ) -> float:
        """
        Compute task-specific heuristic score.

        Examples:
        - If implementing EFFECT node, boost EFFECT patterns
        - If debugging, boost error handling patterns

        Args:
            pattern: Pattern dict with name, node_types, etc.
            task_context: Classified task context

        Returns:
            Score between 0.0 and 1.0
        """
        score = 0.0

        # Node type matching (for IMPLEMENT tasks)
        if task_context.mentioned_node_types:
            pattern_node_types = pattern.get("node_types", [])
            if any(
                nt in pattern_node_types for nt in task_context.mentioned_node_types
            ):
                score += 1.0

        # DEBUG task heuristics
        if task_context.primary_intent == TaskIntent.DEBUG:
            pattern_name = pattern.get("name", "").lower()
            if any(
                term in pattern_name
                for term in [
                    "error",
                    "debug",
                    "exception",
                    "logging",
                    "troubleshooting",
                ]
            ):
                score += 0.5

        # DATABASE task heuristics
        if task_context.primary_intent == TaskIntent.DATABASE:
            pattern_name = pattern.get("name", "").lower()
            if any(
                term in pattern_name for term in ["database", "sql", "query", "schema"]
            ):
                score += 0.5

        return min(score, 1.0)
