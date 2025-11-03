"""
Relevance Scorer - Keyword-based scoring for manifest items.

Scores patterns and schemas by relevance to user's task using:
1. Keyword matching (60% weight)
2. Task-specific heuristics (40% weight)

Part of Phase 3: Relevance Scoring implementation.
"""

from typing import Dict, Any, List, Optional

# Import TaskClassifier types with fallback for different import contexts
try:
    from .task_classifier import TaskContext, TaskIntent
except ImportError:
    # Handle imports when module is installed in ~/.claude/agents/lib/
    import sys
    from pathlib import Path

    lib_path = Path(__file__).parent
    if str(lib_path) not in sys.path:
        sys.path.insert(0, str(lib_path))
    from task_classifier import TaskContext, TaskIntent


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
        pattern: Dict[str, Any],
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

        # 1. Keyword matching (60% weight)
        keyword_score = self._compute_keyword_match(pattern, task_context)
        score += keyword_score * 0.6

        # 2. Task-specific heuristics (40% weight)
        heuristic_score = self._compute_heuristic_score(pattern, task_context)
        score += heuristic_score * 0.4

        return min(score, 1.0)

    def score_schema_relevance(
        self,
        schema: Dict[str, Any],
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
        pattern: Dict[str, Any],
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
        pattern_text = (
            pattern.get("name", "") + " " +
            pattern.get("description", "")
        ).lower()

        if not task_context.keywords:
            return 0.0

        matches = sum(
            1 for kw in task_context.keywords
            if kw in pattern_text
        )

        # Normalize by total keywords
        return matches / len(task_context.keywords)

    def _compute_heuristic_score(
        self,
        pattern: Dict[str, Any],
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
            if any(nt in pattern_node_types for nt in task_context.mentioned_node_types):
                score += 1.0

        # DEBUG task heuristics
        if task_context.primary_intent == TaskIntent.DEBUG:
            pattern_name = pattern.get("name", "").lower()
            if any(term in pattern_name for term in ["error", "debug", "exception", "logging"]):
                score += 0.5

        # DATABASE task heuristics
        if task_context.primary_intent == TaskIntent.DATABASE:
            pattern_name = pattern.get("name", "").lower()
            if any(term in pattern_name for term in ["database", "sql", "query", "schema"]):
                score += 0.5

        return min(score, 1.0)
