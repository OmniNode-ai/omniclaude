#!/usr/bin/env python3
"""
Pattern Registry for Phase 5 Code Generation

Central registry of all available code generation patterns.
Provides pattern lookup, caching, and priority ordering.
"""

import logging
from typing import Any, Dict, List, Optional

from .aggregation_pattern import AggregationPattern
from .crud_pattern import CRUDPattern
from .orchestration_pattern import OrchestrationPattern
from .pattern_matcher import PatternMatch, PatternType
from .transformation_pattern import TransformationPattern


logger = logging.getLogger(__name__)


class PatternRegistry:
    """
    Central registry for code generation patterns.

    Manages pattern instances, provides lookup by name or capability,
    and handles pattern priority ordering.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._patterns: Dict[PatternType, Any] = {}
        self._pattern_cache: Dict[str, Any] = {}
        self._initialize_patterns()

    def _initialize_patterns(self):
        """Initialize all available patterns"""
        try:
            self._patterns[PatternType.CRUD] = CRUDPattern()
            self._patterns[PatternType.TRANSFORMATION] = TransformationPattern()
            self._patterns[PatternType.AGGREGATION] = AggregationPattern()
            self._patterns[PatternType.ORCHESTRATION] = OrchestrationPattern()

            self.logger.info(f"Initialized {len(self._patterns)} patterns")

        except Exception as e:
            self.logger.error(f"Failed to initialize patterns: {str(e)}")
            raise

    def get_pattern(self, pattern_type: PatternType) -> Optional[Any]:
        """
        Get pattern instance by type.

        Args:
            pattern_type: Type of pattern to retrieve

        Returns:
            Pattern instance or None if not found
        """
        pattern = self._patterns.get(pattern_type)

        if not pattern:
            self.logger.warning(f"Pattern not found: {pattern_type}")

        return pattern

    def get_all_patterns(self) -> Dict[PatternType, Any]:
        """
        Get all registered patterns.

        Returns:
            Dictionary of pattern_type -> pattern_instance
        """
        return self._patterns.copy()

    def generate_code_for_pattern(
        self,
        pattern_match: PatternMatch,
        capability: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[str]:
        """
        Generate code using the matched pattern.

        Args:
            pattern_match: Pattern match result
            capability: Capability definition
            context: Additional generation context

        Returns:
            Generated code string or None if generation fails
        """
        try:
            pattern = self.get_pattern(pattern_match.pattern_type)

            if not pattern:
                self.logger.error(f"Pattern not found: {pattern_match.pattern_type}")
                return None

            # Merge pattern context with provided context
            full_context = {**pattern_match.context, **context}

            # Generate code
            code = pattern.generate(capability, full_context)

            self.logger.info(
                f"Generated code for capability '{capability.get('name')}' "
                f"using {pattern_match.pattern_type} pattern"
            )

            return code

        except Exception as e:
            self.logger.error(
                f"Code generation failed for pattern {pattern_match.pattern_type}: {str(e)}"
            )
            return None

    def get_required_imports_for_pattern(self, pattern_type: PatternType) -> List[str]:
        """
        Get required imports for a pattern.

        Args:
            pattern_type: Type of pattern

        Returns:
            List of import statements
        """
        pattern = self.get_pattern(pattern_type)

        if not pattern:
            return []

        return pattern.get_required_imports()

    def get_required_mixins_for_pattern(self, pattern_type: PatternType) -> List[str]:
        """
        Get required mixins for a pattern.

        Args:
            pattern_type: Type of pattern

        Returns:
            List of mixin names
        """
        pattern = self.get_pattern(pattern_type)

        if not pattern:
            return []

        return pattern.get_required_mixins()

    def matches_capability(
        self, pattern_type: PatternType, capability: Dict[str, Any]
    ) -> float:
        """
        Check if pattern matches capability.

        Args:
            pattern_type: Type of pattern
            capability: Capability definition

        Returns:
            Confidence score (0.0 to 1.0)
        """
        pattern = self.get_pattern(pattern_type)

        if not pattern:
            return 0.0

        return pattern.matches(capability)

    def get_pattern_priorities(self) -> Dict[PatternType, int]:
        """
        Get pattern priority ordering.

        Higher priority patterns are preferred when multiple patterns match.

        Returns:
            Dictionary of pattern_type -> priority (higher = more priority)
        """
        return {
            PatternType.CRUD: 100,  # Highest priority for database operations
            PatternType.AGGREGATION: 80,  # High priority for reducers
            PatternType.TRANSFORMATION: 70,  # Medium priority for compute
            PatternType.ORCHESTRATION: 90,  # High priority for orchestrators
        }

    def get_pattern_compatibility(self) -> Dict[PatternType, List[PatternType]]:
        """
        Get pattern compatibility matrix.

        Shows which patterns can be composed together.

        Returns:
            Dictionary of pattern_type -> list of compatible patterns
        """
        return {
            PatternType.CRUD: [
                PatternType.TRANSFORMATION,  # Transform before/after CRUD
                PatternType.AGGREGATION,  # Aggregate CRUD results
            ],
            PatternType.TRANSFORMATION: [
                PatternType.CRUD,  # Transform data for CRUD
                PatternType.AGGREGATION,  # Transform aggregated data
                PatternType.TRANSFORMATION,  # Chain transformations
            ],
            PatternType.AGGREGATION: [
                PatternType.TRANSFORMATION,  # Transform before aggregation
                PatternType.CRUD,  # Persist aggregated data
            ],
            PatternType.ORCHESTRATION: [
                PatternType.CRUD,  # Orchestrate CRUD operations
                PatternType.TRANSFORMATION,  # Orchestrate transformations
                PatternType.AGGREGATION,  # Orchestrate aggregations
            ],
        }

    def can_compose_patterns(
        self, pattern1: PatternType, pattern2: PatternType
    ) -> bool:
        """
        Check if two patterns can be composed together.

        Args:
            pattern1: First pattern type
            pattern2: Second pattern type

        Returns:
            True if patterns are compatible
        """
        compatibility = self.get_pattern_compatibility()
        return pattern2 in compatibility.get(pattern1, [])

    def clear_cache(self):
        """Clear pattern cache"""
        self._pattern_cache.clear()
        self.logger.debug("Pattern cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Cache statistics dictionary
        """
        return {
            "cache_size": len(self._pattern_cache),
            "pattern_count": len(self._patterns),
            "patterns_registered": list(self._patterns.keys()),
        }
