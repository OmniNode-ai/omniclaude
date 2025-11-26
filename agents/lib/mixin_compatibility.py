#!/usr/bin/env python3
"""
Mixin Compatibility Manager for Agent Framework

High-level interface for mixin compatibility checking, recommendations,
and continuous learning integration.

Author: OmniClaude Autonomous Code Generation System
Phase: 7 Stream 4
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .mixin_features import MixinFeatureExtractor
from .mixin_learner import MixinLearner, MixinPrediction
from .persistence import CodegenPersistence


logger = logging.getLogger(__name__)


class CompatibilityLevel(Enum):
    """Mixin compatibility levels"""

    HIGHLY_COMPATIBLE = "highly_compatible"  # >0.9 confidence
    COMPATIBLE = "compatible"  # 0.7-0.9 confidence
    UNCERTAIN = "uncertain"  # 0.5-0.7 confidence
    INCOMPATIBLE = "incompatible"  # 0.3-0.5 confidence
    HIGHLY_INCOMPATIBLE = "highly_incompatible"  # <0.3 confidence


@dataclass
class CompatibilityCheck:
    """
    Result of compatibility check between two mixins.

    Attributes:
        mixin_a: First mixin name
        mixin_b: Second mixin name
        node_type: ONEX node type
        level: Compatibility level
        confidence: Confidence score
        reasons: List of reasons for compatibility/incompatibility
        suggestions: List of suggestions for resolution
    """

    mixin_a: str
    mixin_b: str
    node_type: str
    level: CompatibilityLevel
    confidence: float
    reasons: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


@dataclass
class MixinRecommendation:
    """
    Mixin recommendation for a specific use case.

    Attributes:
        mixin_name: Recommended mixin
        confidence: Recommendation confidence
        justification: Reason for recommendation
        compatibility_with_existing: Compatibility scores with existing mixins
    """

    mixin_name: str
    confidence: float
    justification: str
    compatibility_with_existing: Dict[str, float] = field(default_factory=dict)


@dataclass
class MixinSet:
    """
    Set of compatible mixins for a node.

    Attributes:
        node_type: ONEX node type
        mixins: List of mixin names
        overall_compatibility: Overall compatibility score
        warnings: List of potential issues
    """

    node_type: str
    mixins: List[str]
    overall_compatibility: float
    warnings: List[str] = field(default_factory=list)


class MixinCompatibilityManager:
    """
    High-level manager for mixin compatibility checking and recommendations.

    Features:
    - Check compatibility between mixin pairs
    - Validate mixin sets for nodes
    - Recommend optimal mixin combinations
    - Track and learn from compatibility feedback
    - Provide conflict resolution suggestions
    """

    def __init__(
        self,
        learner: Optional[MixinLearner] = None,
        persistence: Optional[CodegenPersistence] = None,
        enable_ml: bool = True,
    ):
        """
        Initialize compatibility manager.

        Args:
            learner: Optional ML learner instance
            persistence: Optional persistence instance
            enable_ml: Whether to enable ML predictions
        """
        self.logger = logging.getLogger(__name__)
        self.persistence = persistence or CodegenPersistence()
        self.enable_ml = enable_ml

        if enable_ml:
            self.learner: Optional[MixinLearner] = learner or MixinLearner(
                persistence=self.persistence
            )
        else:
            self.learner = None

        self.feature_extractor = MixinFeatureExtractor()

    async def check_compatibility(
        self, mixin_a: str, mixin_b: str, node_type: str
    ) -> CompatibilityCheck:
        """
        Check compatibility between two mixins for a node type.

        Args:
            mixin_a: First mixin name
            mixin_b: Second mixin name
            node_type: ONEX node type

        Returns:
            CompatibilityCheck with detailed results
        """
        # Get historical data
        historical_data = await self._get_historical_data(mixin_a, mixin_b, node_type)

        # ML prediction
        if self.enable_ml and self.learner and self.learner.is_trained():
            prediction = self.learner.predict_compatibility(
                mixin_a, mixin_b, node_type, historical_data
            )

            level = self._classify_compatibility_level(
                prediction.compatible, prediction.confidence
            )

            reasons = [prediction.explanation]
            suggestions = self._generate_suggestions(mixin_a, mixin_b, prediction)

            return CompatibilityCheck(
                mixin_a=mixin_a,
                mixin_b=mixin_b,
                node_type=node_type,
                level=level,
                confidence=prediction.confidence,
                reasons=reasons,
                suggestions=suggestions,
            )

        # Fallback to rule-based checking
        return await self._rule_based_compatibility_check(mixin_a, mixin_b, node_type)

    async def validate_mixin_set(self, mixins: List[str], node_type: str) -> MixinSet:
        """
        Validate a set of mixins for compatibility.

        Args:
            mixins: List of mixin names
            node_type: ONEX node type

        Returns:
            MixinSet with validation results
        """
        warnings = []
        compatibility_scores = []

        # Check pairwise compatibility
        for i, mixin_a in enumerate(mixins):
            for mixin_b in mixins[i + 1 :]:
                check = await self.check_compatibility(mixin_a, mixin_b, node_type)

                if check.level in [
                    CompatibilityLevel.INCOMPATIBLE,
                    CompatibilityLevel.HIGHLY_INCOMPATIBLE,
                ]:
                    warnings.append(
                        f"Potential conflict between {mixin_a} and {mixin_b}: "
                        f"{check.reasons[0] if check.reasons else 'Unknown reason'}"
                    )

                compatibility_scores.append(check.confidence)

        # Calculate overall compatibility
        if compatibility_scores:
            overall_compatibility = sum(compatibility_scores) / len(
                compatibility_scores
            )
        else:
            overall_compatibility = 1.0  # Single mixin or no mixins

        # Check node type compatibility
        node_type_warnings = self._check_node_type_compatibility(mixins, node_type)
        warnings.extend(node_type_warnings)

        return MixinSet(
            node_type=node_type,
            mixins=mixins,
            overall_compatibility=overall_compatibility,
            warnings=warnings,
        )

    async def recommend_mixins(
        self,
        node_type: str,
        required_capabilities: List[str],
        existing_mixins: Optional[List[str]] = None,
        max_recommendations: int = 5,
    ) -> List[MixinRecommendation]:
        """
        Recommend mixins for a node based on required capabilities.

        Args:
            node_type: ONEX node type
            required_capabilities: Required capabilities
            existing_mixins: Already selected mixins
            max_recommendations: Maximum recommendations

        Returns:
            List of mixin recommendations
        """
        if self.enable_ml and self.learner and self.learner.is_trained():
            # ML-based recommendations
            ml_recommendations = self.learner.recommend_mixins(
                node_type, required_capabilities, existing_mixins, max_recommendations
            )

            recommendations = []
            for mixin_name, confidence, explanation in ml_recommendations:
                # Check compatibility with existing mixins
                compatibility_scores = {}
                if existing_mixins:
                    for existing in existing_mixins:
                        check = await self.check_compatibility(
                            existing, mixin_name, node_type
                        )
                        compatibility_scores[existing] = check.confidence

                recommendations.append(
                    MixinRecommendation(
                        mixin_name=mixin_name,
                        confidence=confidence,
                        justification=explanation,
                        compatibility_with_existing=compatibility_scores,
                    )
                )

            return recommendations

        # Fallback to rule-based recommendations
        return self._rule_based_recommendations(
            node_type, required_capabilities, existing_mixins
        )

    async def record_feedback(
        self,
        mixin_a: str,
        mixin_b: str,
        node_type: str,
        success: bool,
        conflict_reason: Optional[str] = None,
        resolution_pattern: Optional[str] = None,
    ):
        """
        Record compatibility feedback for continuous learning.

        Args:
            mixin_a: First mixin
            mixin_b: Second mixin
            node_type: Node type
            success: Whether combination was successful
            conflict_reason: Optional reason for conflict
            resolution_pattern: Optional resolution pattern
        """
        # Update database
        await self.persistence.update_mixin_compatibility(
            mixin_a=mixin_a,
            mixin_b=mixin_b,
            node_type=node_type,
            success=success,
            conflict_reason=conflict_reason,
            resolution_pattern=resolution_pattern,
        )

        # Update ML model if enabled
        if self.enable_ml and self.learner:
            await self.learner.update_from_feedback(
                mixin_a, mixin_b, node_type, success
            )

    # Private helper methods

    async def _get_historical_data(
        self, mixin_a: str, mixin_b: str, node_type: str
    ) -> Optional[Dict[str, Any]]:
        """Get historical compatibility data from database"""
        record = await self.persistence.get_mixin_compatibility(
            mixin_a, mixin_b, node_type
        )

        if not record:
            # Try reverse order
            record = await self.persistence.get_mixin_compatibility(
                mixin_b, mixin_a, node_type
            )

        if record:
            success_count = record["success_count"]
            failure_count = record["failure_count"]
            total_tests = success_count + failure_count

            if total_tests > 0:
                return {
                    "success_rate": success_count / total_tests,
                    "total_tests": total_tests,
                    "avg_compatibility": float(record["compatibility_score"] or 0.5),
                }

        return None

    def _classify_compatibility_level(
        self, compatible: bool, confidence: float
    ) -> CompatibilityLevel:
        """Classify compatibility level from prediction"""
        if compatible:
            if confidence >= 0.9:
                return CompatibilityLevel.HIGHLY_COMPATIBLE
            elif confidence >= 0.7:
                return CompatibilityLevel.COMPATIBLE
            else:
                return CompatibilityLevel.UNCERTAIN
        else:
            if confidence >= 0.7:
                return CompatibilityLevel.HIGHLY_INCOMPATIBLE
            elif confidence >= 0.5:
                return CompatibilityLevel.INCOMPATIBLE
            else:
                return CompatibilityLevel.UNCERTAIN

    def _generate_suggestions(
        self, mixin_a: str, mixin_b: str, prediction: MixinPrediction
    ) -> List[str]:
        """Generate suggestions for improving compatibility"""
        suggestions = []

        if not prediction.compatible:
            char_a = MixinFeatureExtractor.MIXIN_CHARACTERISTICS.get(mixin_a)
            char_b = MixinFeatureExtractor.MIXIN_CHARACTERISTICS.get(mixin_b)

            if char_a and char_b:
                # Check for lifecycle conflicts
                hooks_a = set(char_a.lifecycle_hooks)
                hooks_b = set(char_b.lifecycle_hooks)
                if hooks_a & hooks_b:
                    suggestions.append(
                        "Consider using composition instead of multiple inheritance "
                        "to resolve lifecycle hook conflicts"
                    )

                # Check for state modification conflicts
                if char_a.state_modifying and char_b.state_modifying:
                    suggestions.append(
                        "Both mixins modify state - ensure proper ordering "
                        "and use transactions if needed"
                    )

                # Check for resource conflicts
                if char_a.resource_intensive and char_b.resource_intensive:
                    suggestions.append(
                        "Both mixins are resource-intensive - monitor performance "
                        "and consider caching strategies"
                    )

        return suggestions

    async def _rule_based_compatibility_check(
        self, mixin_a: str, mixin_b: str, node_type: str
    ) -> CompatibilityCheck:
        """Fallback rule-based compatibility checking"""
        char_a = MixinFeatureExtractor.MIXIN_CHARACTERISTICS.get(mixin_a)
        char_b = MixinFeatureExtractor.MIXIN_CHARACTERISTICS.get(mixin_b)

        if not char_a or not char_b:
            return CompatibilityCheck(
                mixin_a=mixin_a,
                mixin_b=mixin_b,
                node_type=node_type,
                level=CompatibilityLevel.UNCERTAIN,
                confidence=0.5,
                reasons=["Unknown mixins - no characteristics data"],
                suggestions=["Add mixin characteristics to database"],
            )

        # Rule-based scoring
        score = 1.0
        reasons = []

        # Same category bonus
        if char_a.category == char_b.category:
            reasons.append(f"Both mixins are in '{char_a.category}' category")
        else:
            score -= 0.1

        # Lifecycle conflicts
        hooks_a = set(char_a.lifecycle_hooks)
        hooks_b = set(char_b.lifecycle_hooks)
        if hooks_a & hooks_b:
            score -= 0.3
            reasons.append(f"Lifecycle hook conflicts: {', '.join(hooks_a & hooks_b)}")

        # State modification conflicts
        if char_a.state_modifying and char_b.state_modifying:
            score -= 0.2
            reasons.append("Both mixins modify state")

        # Determine compatibility
        compatible = score >= 0.6
        level = self._classify_compatibility_level(compatible, score)

        return CompatibilityCheck(
            mixin_a=mixin_a,
            mixin_b=mixin_b,
            node_type=node_type,
            level=level,
            confidence=score,
            reasons=reasons if reasons else ["Rule-based compatibility check"],
            suggestions=[],
        )

    def _check_node_type_compatibility(
        self, mixins: List[str], node_type: str
    ) -> List[str]:
        """Check if mixins are compatible with node type"""
        warnings = []
        node_profile = MixinFeatureExtractor.NODE_TYPE_PROFILES.get(node_type, {})

        for mixin in mixins:
            char = MixinFeatureExtractor.MIXIN_CHARACTERISTICS.get(mixin)
            if not char:
                continue

            # Check async compatibility
            if node_profile.get("async_required") and not char.async_safe:
                warnings.append(
                    f"Mixin {mixin} may not be async-safe, but {node_type} requires async"
                )

            # Check state modification compatibility
            if not node_profile.get("state_modifying") and char.state_modifying:
                warnings.append(
                    f"Mixin {mixin} modifies state, but {node_type} should be stateless"
                )

        return warnings

    def _rule_based_recommendations(
        self,
        node_type: str,
        required_capabilities: List[str],
        existing_mixins: Optional[List[str]] = None,
    ) -> List[MixinRecommendation]:
        """Fallback rule-based recommendations"""
        existing_mixins = existing_mixins or []
        recommendations = []

        # Capability-to-mixin mapping
        capability_map = {
            "cache": ["MixinCaching"],
            "logging": ["MixinLogging"],
            "metrics": ["MixinMetrics"],
            "health": ["MixinHealthCheck"],
            "events": ["MixinEventBus"],
            "retry": ["MixinRetry"],
            "circuit-breaker": ["MixinCircuitBreaker"],
            "validation": ["MixinValidation"],
            "security": ["MixinSecurity"],
            "transaction": ["MixinTransaction"],
        }

        seen_mixins = set(existing_mixins)

        for capability in required_capabilities:
            cap_lower = capability.lower()
            for keyword, mixin_list in capability_map.items():
                if keyword in cap_lower:
                    for mixin in mixin_list:
                        if mixin not in seen_mixins:
                            recommendations.append(
                                MixinRecommendation(
                                    mixin_name=mixin,
                                    confidence=0.6,
                                    justification=f"Rule-based match for '{capability}'",
                                )
                            )
                            seen_mixins.add(mixin)

        return recommendations[:5]  # Limit to 5 recommendations


__all__ = [
    "CompatibilityCheck",
    "CompatibilityLevel",
    "MixinCompatibilityManager",
    "MixinRecommendation",
    "MixinSet",
]
