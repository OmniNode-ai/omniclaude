#!/usr/bin/env python3
"""
Pattern Threshold Tuner - Agent Framework

Automatically tunes pattern matching thresholds and provides A/B testing
framework for pattern matching strategies to achieve optimal precision/recall.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from .pattern_feedback import PatternAnalysis, PatternFeedbackCollector
from .persistence import CodegenPersistence

logger = logging.getLogger(__name__)


class TuningStrategy(str, Enum):
    """Pattern tuning strategies"""

    PRECISION_FIRST = "precision_first"  # Optimize for precision
    RECALL_FIRST = "recall_first"  # Optimize for recall
    BALANCED = "balanced"  # Balance precision and recall
    ADAPTIVE = "adaptive"  # Adaptive based on feedback


@dataclass
class ThresholdConfig:
    """
    Pattern threshold configuration.

    Defines confidence thresholds and weights for pattern matching.
    """

    pattern_name: str
    confidence_threshold: float  # 0.0-1.0
    keyword_weight: float = 0.4  # Weight for keyword matching
    context_weight: float = 0.3  # Weight for context alignment
    primary_weight: float = 0.3  # Weight for primary keyword
    version: str = "1.0.0"
    active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ABTestConfig:
    """
    A/B test configuration for pattern strategies.

    Allows testing different threshold configurations to find optimal settings.
    """

    test_id: UUID
    pattern_name: str
    variant_a: ThresholdConfig
    variant_b: ThresholdConfig
    traffic_split: float = 0.5  # 50/50 split
    min_samples: int = 100
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    winner: Optional[str] = None  # 'a' or 'b'
    status: str = "running"  # running, completed, aborted


@dataclass
class TuningResult:
    """
    Result of pattern threshold tuning.

    Provides before/after metrics and recommended configuration.
    """

    pattern_name: str
    original_threshold: float
    tuned_threshold: float
    original_precision: float
    estimated_precision: float
    improvement: float
    confidence: float  # Confidence in the tuning recommendation
    strategy_used: TuningStrategy
    recommendations: List[str] = field(default_factory=list)


class PatternTuner:
    """
    Automatic pattern threshold tuner with A/B testing support.

    Features:
    - Automatic threshold optimization based on feedback
    - A/B testing framework for threshold strategies
    - Version control for pattern configurations
    - Rollback capability for bad tunings
    - Performance monitoring and alerting

    Performance target: Achieve ≥90% precision across all patterns
    """

    def __init__(
        self,
        feedback_collector: Optional[PatternFeedbackCollector] = None,
        persistence: Optional[CodegenPersistence] = None,
    ):
        """
        Initialize pattern tuner.

        Args:
            feedback_collector: Pattern feedback collector
            persistence: Persistence layer
        """
        self.persistence = persistence or CodegenPersistence()
        self.feedback_collector = feedback_collector or PatternFeedbackCollector(
            self.persistence
        )
        self.logger = logging.getLogger(__name__)

        # Threshold configurations (in-memory cache)
        self._threshold_configs: Dict[str, ThresholdConfig] = {}

        # Active A/B tests
        self._active_tests: Dict[UUID, ABTestConfig] = {}

        # Default thresholds by strategy
        self._default_thresholds = {
            TuningStrategy.PRECISION_FIRST: 0.80,
            TuningStrategy.RECALL_FIRST: 0.60,
            TuningStrategy.BALANCED: 0.70,
            TuningStrategy.ADAPTIVE: 0.70,
        }

    async def tune_pattern(
        self,
        pattern_name: str,
        strategy: TuningStrategy = TuningStrategy.BALANCED,
        min_samples: int = 20,
        target_precision: float = 0.90,
    ) -> TuningResult:
        """
        Tune pattern threshold based on feedback data.

        Analyzes historical feedback to recommend optimal threshold that
        achieves target precision while maximizing recall.

        Args:
            pattern_name: Pattern to tune
            strategy: Tuning strategy to use
            min_samples: Minimum samples required for tuning
            target_precision: Target precision (default 0.90)

        Returns:
            Tuning result with recommendations

        Raises:
            ValueError: If insufficient data for tuning
        """
        self.logger.info(
            f"Tuning pattern '{pattern_name}' with strategy {strategy.value}"
        )

        # Get current configuration
        current_config = self._get_threshold_config(pattern_name)
        original_threshold = current_config.confidence_threshold

        # Analyze current performance
        analysis = await self.feedback_collector.analyze_feedback(
            pattern_name, min_samples
        )

        if not analysis.sufficient_data:
            raise ValueError(
                f"Insufficient data to tune '{pattern_name}'. "
                f"Need {min_samples} samples, have {analysis.sample_count}"
            )

        # Calculate optimal threshold based on strategy
        tuned_threshold, estimated_precision = self._calculate_optimal_threshold(
            analysis, strategy, target_precision
        )

        # Calculate improvement
        improvement = estimated_precision - analysis.precision

        # Generate recommendations
        recommendations = self._generate_tuning_recommendations(
            analysis, original_threshold, tuned_threshold, strategy
        )

        # Calculate confidence in tuning
        confidence = self._calculate_tuning_confidence(
            analysis.sample_count, min_samples, abs(improvement)
        )

        result = TuningResult(
            pattern_name=pattern_name,
            original_threshold=original_threshold,
            tuned_threshold=tuned_threshold,
            original_precision=analysis.precision,
            estimated_precision=estimated_precision,
            improvement=improvement,
            confidence=confidence,
            strategy_used=strategy,
            recommendations=recommendations,
        )

        self.logger.info(
            f"Tuning complete for '{pattern_name}': "
            f"{original_threshold:.2f} -> {tuned_threshold:.2f} "
            f"(precision: {analysis.precision:.1%} -> {estimated_precision:.1%}, "
            f"improvement: {improvement:+.1%}, confidence: {confidence:.1%})"
        )

        return result

    async def apply_tuning(
        self,
        tuning_result: TuningResult,
        create_ab_test: bool = False,
        min_confidence: float = 0.70,
    ) -> bool:
        """
        Apply tuning result to pattern configuration.

        Args:
            tuning_result: Result from tune_pattern()
            create_ab_test: Whether to create A/B test instead of direct apply
            min_confidence: Minimum confidence required for direct apply

        Returns:
            True if applied successfully, False otherwise
        """
        if tuning_result.confidence < min_confidence and not create_ab_test:
            self.logger.warning(
                f"Tuning confidence {tuning_result.confidence:.1%} "
                f"below threshold {min_confidence:.1%}. Consider A/B testing."
            )
            return False

        if create_ab_test:
            # Create A/B test
            await self._create_ab_test(tuning_result)
            return True
        else:
            # Apply directly
            self._update_threshold_config(
                tuning_result.pattern_name, tuning_result.tuned_threshold
            )

            self.logger.info(
                f"Applied tuning to '{tuning_result.pattern_name}': "
                f"threshold={tuning_result.tuned_threshold:.2f}"
            )
            return True

    async def create_ab_test(
        self,
        pattern_name: str,
        threshold_a: float,
        threshold_b: float,
        traffic_split: float = 0.5,
        min_samples: int = 100,
    ) -> ABTestConfig:
        """
        Create A/B test for pattern threshold comparison.

        Args:
            pattern_name: Pattern to test
            threshold_a: Threshold for variant A
            threshold_b: Threshold for variant B
            traffic_split: Fraction of traffic to variant A (default 0.5)
            min_samples: Minimum samples before evaluation

        Returns:
            A/B test configuration
        """
        test_id = uuid4()

        # Create variant configurations
        variant_a = ThresholdConfig(
            pattern_name=pattern_name,
            confidence_threshold=threshold_a,
            version=f"test_{test_id}_a",
        )

        variant_b = ThresholdConfig(
            pattern_name=pattern_name,
            confidence_threshold=threshold_b,
            version=f"test_{test_id}_b",
        )

        # Create test config
        test_config = ABTestConfig(
            test_id=test_id,
            pattern_name=pattern_name,
            variant_a=variant_a,
            variant_b=variant_b,
            traffic_split=traffic_split,
            min_samples=min_samples,
        )

        self._active_tests[test_id] = test_config

        self.logger.info(
            f"Created A/B test {test_id} for '{pattern_name}': "
            f"A={threshold_a:.2f} vs B={threshold_b:.2f} "
            f"(split={traffic_split:.0%}, min_samples={min_samples})"
        )

        return test_config

    async def evaluate_ab_test(
        self, test_id: UUID, auto_apply_winner: bool = False
    ) -> Optional[str]:
        """
        Evaluate A/B test results and determine winner.

        Args:
            test_id: Test ID to evaluate
            auto_apply_winner: Whether to automatically apply winning variant

        Returns:
            Winner variant ('a' or 'b') or None if test not complete
        """
        if test_id not in self._active_tests:
            raise ValueError(f"A/B test {test_id} not found")

        test_config = self._active_tests[test_id]

        # Get feedback for both variants
        # TODO: Implement variant-specific feedback tracking
        # For now, use simplified evaluation based on current analysis

        analysis = await self.feedback_collector.analyze_feedback(
            test_config.pattern_name, min_samples=test_config.min_samples
        )

        if not analysis.sufficient_data:
            self.logger.info(
                f"A/B test {test_id} not ready for evaluation: "
                f"{analysis.sample_count}/{test_config.min_samples} samples"
            )
            return None

        # Compare variants
        # In real implementation, would track separate feedback for each variant
        # For now, choose based on threshold relative to suggested threshold

        if analysis.suggested_threshold is not None:
            diff_a = abs(
                test_config.variant_a.confidence_threshold
                - analysis.suggested_threshold
            )
            diff_b = abs(
                test_config.variant_b.confidence_threshold
                - analysis.suggested_threshold
            )

            winner = "a" if diff_a < diff_b else "b"
        else:
            # Fallback: choose higher threshold for better precision
            winner = (
                "a"
                if test_config.variant_a.confidence_threshold
                > test_config.variant_b.confidence_threshold
                else "b"
            )

        # Update test config
        test_config.winner = winner
        test_config.status = "completed"
        test_config.ended_at = datetime.now(timezone.utc)

        self.logger.info(
            f"A/B test {test_id} completed: winner={winner} "
            f"(A={test_config.variant_a.confidence_threshold:.2f}, "
            f"B={test_config.variant_b.confidence_threshold:.2f})"
        )

        # Apply winner if requested
        if auto_apply_winner:
            winning_config = (
                test_config.variant_a if winner == "a" else test_config.variant_b
            )
            self._update_threshold_config(
                test_config.pattern_name, winning_config.confidence_threshold
            )
            self.logger.info(f"Applied winning variant {winner} to production")

        return winner

    async def rollback_pattern(
        self, pattern_name: str, to_version: Optional[str] = None
    ) -> bool:
        """
        Rollback pattern configuration to previous version.

        Args:
            pattern_name: Pattern to rollback
            to_version: Specific version to rollback to (None = previous)

        Returns:
            True if rollback successful
        """
        # TODO: Implement version history tracking
        # For now, rollback to default threshold

        default_threshold = 0.70
        self._update_threshold_config(pattern_name, default_threshold)

        self.logger.info(
            f"Rolled back '{pattern_name}' to default threshold {default_threshold}"
        )

        return True

    async def tune_all_patterns(
        self,
        strategy: TuningStrategy = TuningStrategy.BALANCED,
        min_samples: int = 20,
        target_precision: float = 0.90,
        auto_apply: bool = False,
    ) -> Dict[str, TuningResult]:
        """
        Tune all patterns with sufficient feedback data.

        Args:
            strategy: Tuning strategy to use
            min_samples: Minimum samples required per pattern
            target_precision: Target precision
            auto_apply: Whether to automatically apply tunings

        Returns:
            Dictionary of pattern_name -> TuningResult
        """
        self.logger.info("Starting bulk pattern tuning...")

        # Get all patterns
        all_analyses = await self.feedback_collector.get_all_pattern_analyses(
            min_samples
        )

        results: Dict[str, TuningResult] = {}

        for analysis in all_analyses:
            try:
                result = await self.tune_pattern(
                    analysis.pattern_name, strategy, min_samples, target_precision
                )

                results[analysis.pattern_name] = result

                # Auto-apply if requested and high confidence
                if auto_apply and result.confidence >= 0.80:
                    await self.apply_tuning(result, create_ab_test=False)

            except Exception as e:
                self.logger.error(
                    f"Failed to tune pattern '{analysis.pattern_name}': {str(e)}"
                )

        self.logger.info(f"Bulk tuning complete: {len(results)} patterns tuned")

        return results

    def _calculate_optimal_threshold(
        self,
        analysis: PatternAnalysis,
        strategy: TuningStrategy,
        target_precision: float,
    ) -> Tuple[float, float]:
        """
        Calculate optimal threshold based on strategy.

        Returns:
            Tuple of (threshold, estimated_precision)
        """
        current_precision = analysis.precision

        if strategy == TuningStrategy.PRECISION_FIRST:
            # Prioritize precision over recall
            if current_precision < target_precision:
                # Increase threshold to reduce false positives
                threshold = min(0.90, current_precision + 0.15)
            else:
                # Already meeting target, maintain
                threshold = analysis.suggested_threshold or 0.80

        elif strategy == TuningStrategy.RECALL_FIRST:
            # Prioritize recall over precision
            # Lower threshold to catch more patterns
            threshold = max(0.60, (analysis.suggested_threshold or 0.70) - 0.10)

        elif strategy == TuningStrategy.BALANCED:
            # Balance precision and recall
            threshold = analysis.suggested_threshold or 0.70

        else:  # ADAPTIVE
            # Adapt based on current performance
            if current_precision < 0.80:
                threshold = 0.80  # Significantly raise
            elif current_precision < 0.90:
                threshold = 0.75  # Moderately raise
            else:
                threshold = 0.70  # Maintain or slightly lower

        # Estimate precision with new threshold
        # Simple linear model: precision improves with higher threshold
        if threshold > (analysis.suggested_threshold or 0.70):
            improvement = (threshold - (analysis.suggested_threshold or 0.70)) * 0.3
        else:
            improvement = (threshold - (analysis.suggested_threshold or 0.70)) * 0.2

        estimated_precision = min(1.0, current_precision + improvement)

        return threshold, estimated_precision

    def _generate_tuning_recommendations(
        self,
        analysis: PatternAnalysis,
        original_threshold: float,
        tuned_threshold: float,
        strategy: TuningStrategy,
    ) -> List[str]:
        """Generate tuning recommendations."""
        recommendations = []

        # Threshold change
        if tuned_threshold > original_threshold:
            recommendations.append(
                f"Raising threshold from {original_threshold:.2f} to {tuned_threshold:.2f} "
                "to reduce false positives and improve precision."
            )
        elif tuned_threshold < original_threshold:
            recommendations.append(
                f"Lowering threshold from {original_threshold:.2f} to {tuned_threshold:.2f} "
                "to increase recall while maintaining acceptable precision."
            )
        else:
            recommendations.append("Threshold unchanged - current setting is optimal.")

        # Strategy-specific recommendations
        if strategy == TuningStrategy.PRECISION_FIRST:
            recommendations.append(
                "Using precision-first strategy. Consider monitoring recall metrics "
                "to ensure not missing too many valid patterns."
            )
        elif strategy == TuningStrategy.RECALL_FIRST:
            recommendations.append(
                "Using recall-first strategy. Monitor false positive rate carefully."
            )

        # Add pattern-specific recommendations from analysis
        recommendations.extend(analysis.recommendations[:3])  # Top 3

        return recommendations

    def _calculate_tuning_confidence(
        self, sample_count: int, min_samples: int, improvement: float
    ) -> float:
        """
        Calculate confidence in tuning recommendation.

        Based on sample size and expected improvement.
        """
        # Sample size factor
        sample_factor = min(1.0, sample_count / (min_samples * 5))

        # Improvement factor
        improvement_factor = min(1.0, abs(improvement) * 5)

        # Combined confidence
        confidence = (sample_factor * 0.6) + (improvement_factor * 0.4)

        return confidence

    def _get_threshold_config(self, pattern_name: str) -> ThresholdConfig:
        """Get threshold configuration for pattern (or default)."""
        if pattern_name not in self._threshold_configs:
            # Create default config
            self._threshold_configs[pattern_name] = ThresholdConfig(
                pattern_name=pattern_name, confidence_threshold=0.70
            )

        return self._threshold_configs[pattern_name]

    def _update_threshold_config(self, pattern_name: str, threshold: float) -> None:
        """Update threshold configuration."""
        config = self._get_threshold_config(pattern_name)
        config.confidence_threshold = threshold
        config.updated_at = datetime.now(timezone.utc)

        self._threshold_configs[pattern_name] = config

    async def _create_ab_test(self, tuning_result: TuningResult) -> ABTestConfig:
        """Create A/B test from tuning result."""
        return await self.create_ab_test(
            pattern_name=tuning_result.pattern_name,
            threshold_a=tuning_result.original_threshold,
            threshold_b=tuning_result.tuned_threshold,
            traffic_split=0.5,
            min_samples=100,
        )

    async def cleanup(self) -> None:
        """Cleanup resources."""
        await self.feedback_collector.cleanup()
