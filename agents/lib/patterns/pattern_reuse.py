#!/usr/bin/env python3
"""
Pattern Reuse - Apply stored patterns to new code generation tasks.

Part of IV-002 (Knowledge Application) quality gate integration.
Intelligently applies stored patterns to enhance code generation.

Reuse Strategy:
1. Generate query embedding from generation context
2. Query similar patterns from storage
3. Filter by reuse_conditions
4. Rank by relevance to current task
5. Apply pattern with context adaptation

ONEX v2.0 Compliance:
- Type-safe pattern application
- Context-aware pattern adaptation
- Performance tracking (<500ms target)
"""

import logging
from typing import Any

from jinja2 import StrictUndefined, Template

from ..models.model_code_pattern import ModelCodePattern, ModelPatternMatch
from .pattern_storage import PatternStorage

logger = logging.getLogger(__name__)


class PatternReuse:
    """
    Apply stored patterns to new code generation tasks.

    Provides:
    - Pattern discovery based on generation context
    - Reuse condition validation
    - Pattern adaptation to current context
    - Template rendering with Jinja2
    - Usage tracking

    Example:
        reuse = PatternReuse(pattern_storage)
        patterns = await reuse.find_applicable_patterns({
            "node_type": "effect",
            "framework": "onex",
            "operation": "database_write"
        })
        for pattern in patterns:
            adapted = await reuse.apply_pattern(pattern.pattern, context)
    """

    def __init__(
        self, pattern_storage: PatternStorage, embedding_generator: Any = None
    ) -> None:
        """
        Initialize pattern reuse system.

        Args:
            pattern_storage: PatternStorage instance for querying patterns
            embedding_generator: Optional embedding generator for query vectors
                                If None, uses simple text-based matching
        """
        self.storage = pattern_storage
        self.embedding_generator = embedding_generator

    async def find_applicable_patterns(
        self,
        generation_context: dict[str, Any],
        pattern_type: str | None = None,
        max_patterns: int = 5,
        min_similarity: float = 0.7,
    ) -> list[ModelPatternMatch]:
        """
        Find patterns applicable to current generation task.

        Workflow:
        1. Generate query embedding from context
        2. Query similar patterns from storage
        3. Filter by reuse_conditions
        4. Rank by relevance

        Args:
            generation_context: Current generation context
            pattern_type: Optional filter by pattern type
            max_patterns: Maximum patterns to return
            min_similarity: Minimum similarity threshold

        Returns:
            List of applicable pattern matches
        """
        # Generate query embedding
        query_embedding = await self._generate_query_embedding(generation_context)

        # Query similar patterns
        candidates = await self.storage.query_similar_patterns(
            query_embedding=query_embedding,
            pattern_type=pattern_type,
            limit=max_patterns * 2,  # Get extra for filtering
            min_confidence=0.6,  # Lower threshold, will filter later
        )

        # Filter by reuse conditions
        applicable = []
        for match in candidates:
            if self._check_reuse_conditions(match.pattern, generation_context):
                # Update match with applicability details
                match.applicable = True
                match.match_reason = self._generate_match_reason(
                    match.pattern, generation_context, match.similarity_score
                )
                applicable.append(match)

        # Filter by minimum similarity
        applicable = [m for m in applicable if m.similarity_score >= min_similarity]

        # Rank by relevance (similarity * confidence * success_rate)
        applicable.sort(
            key=lambda m: (
                m.similarity_score * m.pattern.confidence_score * m.pattern.success_rate
            ),
            reverse=True,
        )

        logger.info(
            f"Found {len(applicable)} applicable patterns from {len(candidates)} candidates"
        )
        return applicable[:max_patterns]

    async def apply_pattern(
        self, pattern: ModelCodePattern, target_context: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Apply pattern to current generation.

        Workflow:
        1. Validate pattern applicability
        2. Adapt pattern template to context
        3. Render template with Jinja2
        4. Return adapted result

        Args:
            pattern: Pattern to apply
            target_context: Target context for adaptation

        Returns:
            Dictionary with adapted pattern:
            - "code": Generated code from pattern
            - "pattern_id": Applied pattern ID
            - "pattern_name": Pattern name
            - "success": Whether application succeeded
        """
        try:
            # Merge source context with target context
            merged_context = {**pattern.source_context, **target_context}

            # Render pattern template with strict undefined checking
            template = Template(pattern.pattern_template, undefined=StrictUndefined)
            generated_code = template.render(**merged_context)

            # Track usage (async, don't wait)
            await self.storage.update_pattern_usage(
                pattern.pattern_id, success=True, quality_score=0.8
            )

            logger.info(
                f"Applied pattern {pattern.pattern_name} ({pattern.pattern_id})"
            )

            return {
                "code": generated_code,
                "pattern_id": pattern.pattern_id,
                "pattern_name": pattern.pattern_name,
                "pattern_type": pattern.pattern_type.value,
                "success": True,
                "context": merged_context,
            }

        except Exception as e:
            logger.error(f"Failed to apply pattern {pattern.pattern_id}: {e}")

            # Track failed usage
            await self.storage.update_pattern_usage(
                pattern.pattern_id, success=False, quality_score=0.0
            )

            return {
                "code": "",
                "pattern_id": pattern.pattern_id,
                "pattern_name": pattern.pattern_name,
                "pattern_type": pattern.pattern_type.value,
                "success": False,
                "error": str(e),
            }

    def _check_reuse_conditions(
        self, pattern: ModelCodePattern, context: dict[str, Any]
    ) -> bool:
        """
        Check if pattern's reuse conditions are met.

        Validates that context matches pattern requirements using OR logic:
        at least one condition must match.

        Args:
            pattern: Pattern to check
            context: Current generation context

        Returns:
            True if at least one condition is met, False otherwise
        """
        if not pattern.reuse_conditions:
            # No conditions specified, pattern is always applicable
            return True

        # Check each condition - return True if ANY match (OR logic)
        for condition in pattern.reuse_conditions:
            if self._evaluate_condition(condition, context):
                logger.debug(
                    f"Pattern {pattern.pattern_id} matched condition: {condition}"
                )
                return True

        logger.debug(f"Pattern {pattern.pattern_id} failed all conditions")
        return False

    def _evaluate_condition(self, condition: str, context: dict[str, Any]) -> bool:
        """
        Evaluate a single reuse condition.

        Conditions can be:
        - "key exists": Check if key is in context
        - "key: value": Check if context[key] == value
        - "key matches pattern": Check if key matches regex
        - Free-form text: Check if mentioned in context values

        Args:
            condition: Condition string
            context: Context to evaluate

        Returns:
            True if condition is met
        """
        # Parse condition
        if " matches " in condition:
            # "key matches pattern" format (check this first to avoid conflicts with :)
            import re

            parts = condition.split(" matches ", 1)
            key = parts[0].strip()
            pattern = parts[1].strip()

            if key in context:
                return bool(re.search(pattern, str(context[key])))
            return False

        elif ":" in condition:
            # "key: value" format
            key, value = condition.split(":", 1)
            key = key.strip()
            value = value.strip()

            if key in context:
                context_value = str(context[key]).lower()
                # Check if value matches (exact or contains)
                return value.lower() == context_value or value.lower() in context_value
            return False

        else:
            # Free-form text - check if key words are mentioned anywhere
            condition_lower = condition.lower()
            # Split condition into words and check if any significant word appears
            condition_words = [w for w in condition_lower.split() if len(w) > 3]

            for value in context.values():
                value_lower = str(value).lower()
                # Check exact match first
                if condition_lower in value_lower:
                    return True
                # Check if any significant word from condition appears
                if condition_words and any(
                    word in value_lower for word in condition_words
                ):
                    return True

            return False

    def _generate_match_reason(
        self, pattern: ModelCodePattern, context: dict[str, Any], similarity: float
    ) -> str:
        """
        Generate human-readable explanation for why pattern matched.

        Args:
            pattern: Matched pattern
            context: Generation context
            similarity: Similarity score

        Returns:
            Match reason string
        """
        reasons = [f"Similarity: {similarity:.0%}"]

        # Check context overlap
        common_keys = set(pattern.source_context.keys()) & set(context.keys())
        if common_keys:
            reasons.append(f"Shared context: {', '.join(common_keys)}")

        # Check pattern type match
        if context.get("pattern_type") == pattern.pattern_type.value:
            reasons.append("Exact pattern type match")

        # Check high success rate
        if pattern.success_rate >= 0.9:
            reasons.append(f"High success rate: {pattern.success_rate:.0%}")

        return " | ".join(reasons)

    async def _generate_query_embedding(self, context: dict[str, Any]) -> list[float]:
        """
        Generate query embedding from generation context.

        If embedding_generator is provided, uses it to generate embedding.
        Otherwise, generates a simple hash-based embedding.

        Args:
            context: Generation context

        Returns:
            Query embedding vector
        """
        if self.embedding_generator:
            # Use provided embedding generator
            context_text = " ".join(f"{k}: {v}" for k, v in context.items())
            return await self.embedding_generator.generate(context_text)

        # Fallback: Simple hash-based embedding (384 dimensions)
        import hashlib

        context_str = str(sorted(context.items()))
        hash_bytes = hashlib.sha384(context_str.encode()).digest()

        # Convert to normalized vector
        embedding = [float(b) / 255.0 for b in hash_bytes]
        return embedding

    async def get_pattern_recommendations(
        self, context: dict[str, Any], top_n: int = 3
    ) -> list[dict[str, Any]]:
        """
        Get top pattern recommendations for current context.

        Returns simplified recommendations suitable for display.

        Args:
            context: Generation context
            top_n: Number of recommendations

        Returns:
            List of recommendation dictionaries
        """
        matches = await self.find_applicable_patterns(
            context, max_patterns=top_n, min_similarity=0.6
        )

        recommendations = []
        for match in matches:
            recommendations.append(
                {
                    "pattern_id": match.pattern.pattern_id,
                    "pattern_name": match.pattern.pattern_name,
                    "pattern_type": match.pattern.pattern_type.value,
                    "similarity": match.similarity_score,
                    "confidence": match.pattern.confidence_score,
                    "success_rate": match.pattern.success_rate,
                    "usage_count": match.pattern.usage_count,
                    "match_reason": match.match_reason,
                    "example_usage": (
                        match.pattern.example_usage[0]
                        if match.pattern.example_usage
                        else None
                    ),
                }
            )

        return recommendations

    async def apply_best_pattern(
        self, context: dict[str, Any], pattern_type: str | None = None
    ) -> dict[str, Any] | None:
        """
        Find and apply the best matching pattern.

        Convenience method for single-pattern application.

        Args:
            context: Generation context
            pattern_type: Optional pattern type filter

        Returns:
            Applied pattern result or None if no patterns found
        """
        matches = await self.find_applicable_patterns(
            context, pattern_type=pattern_type, max_patterns=1, min_similarity=0.7
        )

        if not matches:
            logger.info("No applicable patterns found")
            return None

        best_match = matches[0]
        return await self.apply_pattern(best_match.pattern, context)
