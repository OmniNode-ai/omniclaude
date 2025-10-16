#!/usr/bin/env python3
"""
Pattern Matcher for Phase 5 Code Generation

Analyzes contract capabilities to identify applicable code generation patterns.
Provides confidence scoring and pattern composition support.

Phase 7 Enhancement: Integrates feedback learning for improved precision (≥90% target).
"""

import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class PatternType(str, Enum):
    """Types of code generation patterns"""
    CRUD = "crud"
    TRANSFORMATION = "transformation"
    AGGREGATION = "aggregation"
    ORCHESTRATION = "orchestration"


@dataclass
class PatternMatch:
    """Represents a pattern match with confidence score"""
    pattern_type: PatternType
    confidence: float  # 0.0 to 1.0
    matched_keywords: List[str]
    capability_name: str
    suggested_method_name: str
    context: Dict[str, Any]


class PatternMatcher:
    """
    Analyzes capabilities to identify applicable code generation patterns.

    Uses keyword matching, verb analysis, and semantic patterns to determine
    which code generation patterns best fit a given capability.

    Phase 7 Enhancement: Integrates with PatternFeedbackCollector for
    continuous learning and adaptive threshold tuning to achieve ≥90% precision.
    """

    # Pattern detection keywords
    CRUD_KEYWORDS = {
        'create', 'insert', 'add', 'new', 'save', 'store',
        'read', 'get', 'fetch', 'retrieve', 'find', 'query', 'select',
        'update', 'modify', 'edit', 'change', 'patch', 'set',
        'delete', 'remove', 'destroy', 'drop', 'erase'
    }

    TRANSFORMATION_KEYWORDS = {
        'transform', 'convert', 'parse', 'format', 'map', 'filter',
        'translate', 'encode', 'decode', 'serialize', 'deserialize',
        'normalize', 'validate', 'sanitize', 'clean', 'process'
    }

    AGGREGATION_KEYWORDS = {
        'aggregate', 'reduce', 'sum', 'count', 'average', 'mean',
        'group', 'batch', 'collect', 'accumulate', 'combine',
        'merge', 'join', 'union', 'consolidate', 'summarize',
        'statistics', 'compute', 'calculate', 'tally', 'total',
        'persist', 'store', 'results'
    }

    ORCHESTRATION_KEYWORDS = {
        'orchestrate', 'coordinate', 'workflow', 'sequence', 'parallel',
        'execute', 'run', 'schedule', 'trigger', 'dispatch',
        'manage', 'control', 'supervise', 'monitor', 'handle'
    }

    def __init__(self, use_learned_thresholds: bool = True):
        """
        Initialize pattern matcher.

        Args:
            use_learned_thresholds: Whether to use feedback-learned thresholds
        """
        self.logger = logging.getLogger(__name__)
        self.use_learned_thresholds = use_learned_thresholds

        # Default confidence thresholds (can be overridden by learned values)
        self._confidence_thresholds: Dict[PatternType, float] = {
            PatternType.CRUD: 0.70,
            PatternType.TRANSFORMATION: 0.70,
            PatternType.AGGREGATION: 0.70,
            PatternType.ORCHESTRATION: 0.70
        }

        # Learned thresholds (loaded from feedback system)
        self._learned_thresholds: Dict[str, float] = {}

    def match_patterns(
        self,
        capability: Dict[str, Any],
        max_matches: int = 3
    ) -> List[PatternMatch]:
        """
        Identify patterns that match the given capability.

        Args:
            capability: Capability dictionary from contract
            max_matches: Maximum number of pattern matches to return

        Returns:
            List of PatternMatch objects sorted by confidence (descending)
        """
        matches = []

        # Extract capability information
        capability_name = capability.get("name", "")
        capability_type = capability.get("type", "")
        capability_desc = capability.get("description", "")

        # Combine all text for analysis
        all_text = f"{capability_name} {capability_type} {capability_desc}".lower()

        # Check each pattern type
        matches.extend(self._check_crud_pattern(capability_name, all_text, capability))
        matches.extend(self._check_transformation_pattern(capability_name, all_text, capability))
        matches.extend(self._check_aggregation_pattern(capability_name, all_text, capability))
        matches.extend(self._check_orchestration_pattern(capability_name, all_text, capability))

        # Filter by learned thresholds if enabled
        if self.use_learned_thresholds:
            matches = self._apply_learned_thresholds(matches)

        # Sort by confidence (descending) and limit results
        matches.sort(key=lambda m: m.confidence, reverse=True)

        self.logger.debug(
            f"Found {len(matches)} pattern matches for capability '{capability_name}' "
            f"(returning top {max_matches})"
        )

        return matches[:max_matches]

    def set_learned_threshold(self, pattern_name: str, threshold: float) -> None:
        """
        Set learned threshold for a pattern.

        Args:
            pattern_name: Pattern name (e.g., 'CRUD', 'TRANSFORMATION')
            threshold: Confidence threshold (0.0-1.0)
        """
        self._learned_thresholds[pattern_name] = threshold
        self.logger.info(
            f"Updated learned threshold for '{pattern_name}': {threshold:.2f}"
        )

    def get_threshold(self, pattern_type: PatternType) -> float:
        """
        Get current threshold for pattern type.

        Returns learned threshold if available, otherwise default.

        Args:
            pattern_type: Pattern type

        Returns:
            Confidence threshold
        """
        # Check for learned threshold first
        pattern_name = pattern_type.value.upper()
        if pattern_name in self._learned_thresholds:
            return self._learned_thresholds[pattern_name]

        # Fall back to default
        return self._confidence_thresholds.get(pattern_type, 0.70)

    def _apply_learned_thresholds(
        self,
        matches: List[PatternMatch]
    ) -> List[PatternMatch]:
        """
        Filter matches by learned confidence thresholds.

        Args:
            matches: List of pattern matches

        Returns:
            Filtered list of matches meeting learned thresholds
        """
        filtered = []

        for match in matches:
            threshold = self.get_threshold(match.pattern_type)

            if match.confidence >= threshold:
                filtered.append(match)
            else:
                self.logger.debug(
                    f"Filtered out {match.pattern_type.value} match "
                    f"(confidence {match.confidence:.2f} < threshold {threshold:.2f})"
                )

        return filtered

    def match_single_best_pattern(
        self,
        capability: Dict[str, Any]
    ) -> Optional[PatternMatch]:
        """
        Find the single best pattern match for a capability.

        Args:
            capability: Capability dictionary from contract

        Returns:
            Best PatternMatch or None if no match found
        """
        matches = self.match_patterns(capability, max_matches=1)
        return matches[0] if matches else None

    def _check_crud_pattern(
        self,
        capability_name: str,
        text: str,
        capability: Dict[str, Any]
    ) -> List[PatternMatch]:
        """Check if capability matches CRUD pattern"""
        matched_keywords = [kw for kw in self.CRUD_KEYWORDS if kw in text]

        if not matched_keywords:
            return []

        # Calculate confidence based on keyword matches and context
        confidence = self._calculate_confidence(
            matched_keywords,
            self.CRUD_KEYWORDS,
            text,
            capability
        )

        # Determine CRUD operation type
        operation = self._determine_crud_operation(matched_keywords, text)

        return [PatternMatch(
            pattern_type=PatternType.CRUD,
            confidence=confidence,
            matched_keywords=matched_keywords,
            capability_name=capability_name,
            suggested_method_name=self._generate_method_name(capability_name),
            context={
                "operation": operation,
                "database_interaction": True,
                "capability_type": capability.get("type", "operation")
            }
        )]

    def _check_transformation_pattern(
        self,
        capability_name: str,
        text: str,
        capability: Dict[str, Any]
    ) -> List[PatternMatch]:
        """Check if capability matches Transformation pattern"""
        matched_keywords = [kw for kw in self.TRANSFORMATION_KEYWORDS if kw in text]

        if not matched_keywords:
            return []

        confidence = self._calculate_confidence(
            matched_keywords,
            self.TRANSFORMATION_KEYWORDS,
            text,
            capability
        )

        return [PatternMatch(
            pattern_type=PatternType.TRANSFORMATION,
            confidence=confidence,
            matched_keywords=matched_keywords,
            capability_name=capability_name,
            suggested_method_name=self._generate_method_name(capability_name),
            context={
                "pure_function": True,
                "streaming_capable": any(kw in text for kw in ['stream', 'large', 'batch']),
                "capability_type": capability.get("type", "compute")
            }
        )]

    def _check_aggregation_pattern(
        self,
        capability_name: str,
        text: str,
        capability: Dict[str, Any]
    ) -> List[PatternMatch]:
        """Check if capability matches Aggregation pattern"""
        matched_keywords = [kw for kw in self.AGGREGATION_KEYWORDS if kw in text]

        if not matched_keywords:
            return []

        confidence = self._calculate_confidence(
            matched_keywords,
            self.AGGREGATION_KEYWORDS,
            text,
            capability
        )

        return [PatternMatch(
            pattern_type=PatternType.AGGREGATION,
            confidence=confidence,
            matched_keywords=matched_keywords,
            capability_name=capability_name,
            suggested_method_name=self._generate_method_name(capability_name),
            context={
                "stateful": True,
                "windowing": any(kw in text for kw in ['window', 'time', 'period']),
                "capability_type": capability.get("type", "reducer")
            }
        )]

    def _check_orchestration_pattern(
        self,
        capability_name: str,
        text: str,
        capability: Dict[str, Any]
    ) -> List[PatternMatch]:
        """Check if capability matches Orchestration pattern"""
        matched_keywords = [kw for kw in self.ORCHESTRATION_KEYWORDS if kw in text]

        if not matched_keywords:
            return []

        confidence = self._calculate_confidence(
            matched_keywords,
            self.ORCHESTRATION_KEYWORDS,
            text,
            capability
        )

        return [PatternMatch(
            pattern_type=PatternType.ORCHESTRATION,
            confidence=confidence,
            matched_keywords=matched_keywords,
            capability_name=capability_name,
            suggested_method_name=self._generate_method_name(capability_name),
            context={
                "multi_step": True,
                "parallel_capable": 'parallel' in text,
                "compensation": any(kw in text for kw in ['rollback', 'compensate', 'undo']),
                "capability_type": capability.get("type", "orchestrator")
            }
        )]

    def _calculate_confidence(
        self,
        matched_keywords: List[str],
        pattern_keywords: set,
        text: str,
        capability: Dict[str, Any]
    ) -> float:
        """
        Calculate confidence score for pattern match.

        Factors:
        - Exact match bonus (high confidence for explicit type matches)
        - Keyword match ratio (40%)
        - Primary keyword presence (30%)
        - Context alignment (30%)
        """
        capability_type = capability.get("type", "").lower()
        capability_name = capability.get("name", "").lower()

        # Exact match bonus: if capability type or name exactly matches a pattern keyword
        # This indicates an explicit, unambiguous match (e.g., type="create" for CRUD)
        exact_match = (capability_type in pattern_keywords or
                      capability_name in pattern_keywords)

        if exact_match:
            # Exact matches get high base confidence (0.75)
            # This ensures they pass the 0.70 threshold while allowing proper
            # aggregation scaling: perfect CRUD (4/4) -> 1.0, partial (2/4) -> 0.875
            base_confidence = 0.75

            # Small boost for multiple keyword matches (better context)
            keyword_bonus = min(len(matched_keywords) * 0.02, 0.10)

            return min(base_confidence + keyword_bonus, 0.95)

        # Standard confidence calculation for fuzzy matches
        # Keyword match ratio
        match_ratio = len(matched_keywords) / len(pattern_keywords)
        keyword_score = min(match_ratio * 4.0, 1.0)  # Scale to 0-1

        # Primary keyword bonus (first word match)
        first_word = text.split()[0] if text.split() else ""
        primary_bonus = 0.3 if first_word in matched_keywords else 0.0

        # Context alignment (capability type matches expected type)
        context_score = 0.3 if any(
            kw in capability_type for kw in matched_keywords
        ) else 0.15

        total = (keyword_score * 0.4) + primary_bonus + context_score

        return min(total, 1.0)

    def _determine_crud_operation(
        self,
        matched_keywords: List[str],
        text: str
    ) -> str:
        """Determine specific CRUD operation type"""
        # Check for specific operation keywords
        if any(kw in matched_keywords for kw in ['create', 'insert', 'add', 'new']):
            return 'create'
        elif any(kw in matched_keywords for kw in ['read', 'get', 'fetch', 'retrieve']):
            return 'read'
        elif any(kw in matched_keywords for kw in ['update', 'modify', 'edit', 'change']):
            return 'update'
        elif any(kw in matched_keywords for kw in ['delete', 'remove', 'destroy']):
            return 'delete'
        else:
            # Default based on first keyword
            return matched_keywords[0] if matched_keywords else 'operation'

    def _generate_method_name(self, capability_name: str) -> str:
        """Generate a Python method name from capability name"""
        # Convert to snake_case
        name = re.sub(r'[^\w\s-]', '', capability_name.lower())
        name = re.sub(r'[-\s]+', '_', name)
        name = re.sub(r'_+', '_', name).strip('_')

        return name if name else "execute_operation"
