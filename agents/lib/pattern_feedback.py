#!/usr/bin/env python3
"""
Pattern Feedback System - Agent Framework

Collects and analyzes pattern matching feedback to improve pattern recognition
precision and achieve ≥90% accuracy through continuous learning.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from .persistence import CodegenPersistence


logger = logging.getLogger(__name__)


@dataclass
class PatternFeedback:
    """
    Pattern matching feedback record.

    Captures details about pattern detection accuracy including false
    positives/negatives for continuous learning.
    """

    session_id: UUID
    detected_pattern: str
    detected_confidence: float
    actual_pattern: str
    feedback_type: str  # 'correct', 'incorrect', 'partial', 'adjusted'
    capabilities_matched: List[str] = field(default_factory=list)
    false_positives: List[str] = field(default_factory=list)
    false_negatives: List[str] = field(default_factory=list)
    user_provided: bool = False
    contract_json: Optional[Dict[str, Any]] = None


@dataclass
class PatternAnalysis:
    """
    Analysis results for pattern feedback.

    Provides metrics and recommendations for improving pattern matching.
    """

    pattern_name: str
    sufficient_data: bool
    sample_count: int
    precision: float
    recall: Optional[float] = None
    f1_score: Optional[float] = None
    correct_count: int = 0
    incorrect_count: int = 0
    partial_count: int = 0
    false_positive_counts: Dict[str, int] = field(default_factory=dict)
    false_negative_counts: Dict[str, int] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    suggested_threshold: Optional[float] = None


class PatternFeedbackCollector:
    """
    Collect and learn from pattern matching feedback.

    Features:
    - Record pattern detection results (manual + automated)
    - Identify false positives/negatives
    - Analyze pattern precision and recall
    - Generate improvement recommendations
    - Support A/B testing of pattern strategies

    Performance target: <50ms for feedback recording
    Precision target: ≥90%
    """

    def __init__(self, persistence: Optional[CodegenPersistence] = None):
        """
        Initialize pattern feedback collector.

        Args:
            persistence: Optional persistence layer (creates default if not provided)
        """
        self.persistence = persistence or CodegenPersistence()
        self.logger = logging.getLogger(__name__)

        # Cache for analysis results (to avoid repeated DB queries)
        self._analysis_cache: Dict[str, tuple[PatternAnalysis, datetime]] = {}
        self._cache_ttl_seconds = 300  # 5 minutes

    async def record_feedback(
        self, feedback: PatternFeedback, user_provided: bool = False
    ) -> UUID:
        """
        Record pattern matching feedback.

        Args:
            feedback: Feedback data
            user_provided: Whether feedback came from user validation

        Returns:
            UUID of the recorded feedback

        Raises:
            Exception: If recording fails
        """
        try:
            start_time = datetime.now(timezone.utc)

            # Calculate learning weight (user feedback is higher priority)
            learning_weight = 2.0 if user_provided or feedback.user_provided else 1.0

            # Record to database
            feedback_id = await self.persistence.record_pattern_feedback(
                session_id=feedback.session_id,
                pattern_name=feedback.detected_pattern,
                detected_confidence=feedback.detected_confidence,
                actual_pattern=feedback.actual_pattern,
                feedback_type=feedback.feedback_type,
                user_provided=user_provided or feedback.user_provided,
                contract_json=feedback.contract_json,
            )

            # Update false positives/negatives if provided
            if feedback.false_positives or feedback.false_negatives:
                await self._update_fp_fn_tracking(
                    feedback_id, feedback.false_positives, feedback.false_negatives
                )

            # Clear analysis cache for this pattern
            self._invalidate_cache(feedback.detected_pattern)

            duration_ms = (
                datetime.now(timezone.utc) - start_time
            ).total_seconds() * 1000

            self.logger.info(
                f"Recorded pattern feedback: {feedback.feedback_type} "
                f"(detected={feedback.detected_pattern}, "
                f"actual={feedback.actual_pattern}, "
                f"weight={learning_weight}, duration={duration_ms:.1f}ms)"
            )

            return feedback_id

        except Exception as e:
            self.logger.error(f"Failed to record pattern feedback: {str(e)}")
            raise

    async def analyze_feedback(
        self, pattern_name: str, min_samples: int = 20, use_cache: bool = True
    ) -> PatternAnalysis:
        """
        Analyze feedback for a pattern to identify improvement opportunities.

        Args:
            pattern_name: Pattern to analyze
            min_samples: Minimum feedback samples required for analysis
            use_cache: Whether to use cached analysis results

        Returns:
            Analysis results with metrics and recommendations
        """
        # Check cache first
        if use_cache and pattern_name in self._analysis_cache:
            cached_analysis, cached_time = self._analysis_cache[pattern_name]
            age_seconds = (datetime.now(timezone.utc) - cached_time).total_seconds()

            if age_seconds < self._cache_ttl_seconds:
                self.logger.debug(f"Using cached analysis for {pattern_name}")
                return cached_analysis

        # Fetch feedback records from database
        feedback_records = await self._get_pattern_feedback_details(pattern_name)

        if len(feedback_records) < min_samples:
            analysis = PatternAnalysis(
                pattern_name=pattern_name,
                sufficient_data=False,
                sample_count=len(feedback_records),
                precision=0.0,
            )
            return analysis

        # Calculate metrics
        total = len(feedback_records)
        correct = sum(
            1 for r in feedback_records if r.get("feedback_type") == "correct"
        )
        incorrect = sum(
            1 for r in feedback_records if r.get("feedback_type") == "incorrect"
        )
        partial = sum(
            1 for r in feedback_records if r.get("feedback_type") == "partial"
        )
        sum(1 for r in feedback_records if r.get("feedback_type") == "adjusted")

        # Precision: correct / total predictions
        precision = correct / total if total > 0 else 0.0

        # Recall: correct / (correct + false_negatives)
        # This requires tracking what patterns were missed
        recall = None  # TODO: Implement recall tracking in future iteration
        f1_score = None  # F1 score requires recall (not yet implemented)

        # Identify common false positives
        all_false_positives: List[str] = []
        for r in feedback_records:
            fps = r.get("false_positives", [])
            if fps:
                all_false_positives.extend(fps)

        false_positive_counts = dict(Counter(all_false_positives).most_common(10))

        # Identify common false negatives
        all_false_negatives: List[str] = []
        for r in feedback_records:
            fns = r.get("false_negatives", [])
            if fns:
                all_false_negatives.extend(fns)

        false_negative_counts = dict(Counter(all_false_negatives).most_common(10))

        # Generate recommendations
        recommendations = self._generate_recommendations(
            precision, false_positive_counts, false_negative_counts, feedback_records
        )

        # Suggest confidence threshold
        suggested_threshold = self._calculate_suggested_threshold(
            precision, feedback_records
        )

        analysis = PatternAnalysis(
            pattern_name=pattern_name,
            sufficient_data=True,
            sample_count=total,
            precision=precision,
            recall=recall,
            f1_score=f1_score,
            correct_count=correct,
            incorrect_count=incorrect,
            partial_count=partial,
            false_positive_counts=false_positive_counts,
            false_negative_counts=false_negative_counts,
            recommendations=recommendations,
            suggested_threshold=suggested_threshold,
        )

        # Cache the analysis
        self._analysis_cache[pattern_name] = (analysis, datetime.now(timezone.utc))

        self.logger.info(
            f"Pattern analysis for '{pattern_name}': "
            f"precision={precision:.1%}, samples={total}, "
            f"suggestions={len(recommendations)}"
        )

        return analysis

    async def get_all_pattern_analyses(
        self, min_samples: int = 20
    ) -> List[PatternAnalysis]:
        """
        Get analyses for all patterns with sufficient data.

        Args:
            min_samples: Minimum samples required per pattern

        Returns:
            List of pattern analyses sorted by precision (ascending)
        """
        # Get all pattern names from feedback analysis view
        all_feedback = await self.persistence.get_pattern_feedback_analysis()

        # Get unique pattern names
        pattern_names = set(fb["pattern_name"] for fb in all_feedback)

        # Analyze each pattern
        analyses: List[PatternAnalysis] = []
        for pattern_name in pattern_names:
            try:
                analysis = await self.analyze_feedback(pattern_name, min_samples)
                if analysis.sufficient_data:
                    analyses.append(analysis)
            except Exception as e:
                self.logger.warning(
                    f"Failed to analyze pattern '{pattern_name}': {str(e)}"
                )

        # Sort by precision (lowest first - these need most attention)
        analyses.sort(key=lambda a: a.precision)

        return analyses

    async def tune_pattern_threshold(
        self, pattern_name: str, target_precision: float = 0.90
    ) -> Optional[float]:
        """
        Tune confidence threshold for pattern based on feedback.

        Uses feedback data to recommend optimal confidence threshold
        that achieves target precision.

        Args:
            pattern_name: Pattern to tune
            target_precision: Target precision (default 0.90 = 90%)

        Returns:
            Recommended confidence threshold (0.0-1.0) or None if insufficient data
        """
        analysis = await self.analyze_feedback(pattern_name)

        if not analysis.sufficient_data:
            self.logger.warning(
                f"Insufficient data to tune threshold for '{pattern_name}'"
            )
            return None

        current_precision = analysis.precision

        # Simple threshold tuning logic
        # TODO: Implement more sophisticated ML-based tuning
        if current_precision >= 0.95:
            # Very good, can lower threshold to catch more patterns
            recommended = 0.65
            self.logger.info(
                f"Pattern '{pattern_name}' precision {current_precision:.1%} "
                f"is excellent. Recommending lower threshold {recommended} to increase recall."
            )
        elif current_precision >= target_precision:
            # Good, maintain current threshold
            recommended = 0.70
            self.logger.info(
                f"Pattern '{pattern_name}' precision {current_precision:.1%} "
                f"meets target. Recommending threshold {recommended}."
            )
        elif current_precision >= 0.80:
            # Acceptable, slightly raise threshold
            recommended = 0.75
            self.logger.info(
                f"Pattern '{pattern_name}' precision {current_precision:.1%} "
                f"below target. Recommending higher threshold {recommended}."
            )
        else:
            # Poor, significantly raise threshold
            recommended = 0.85
            self.logger.warning(
                f"Pattern '{pattern_name}' precision {current_precision:.1%} "
                f"is low. Recommending much higher threshold {recommended}."
            )

        return recommended

    async def get_global_precision_metrics(self) -> Dict[str, Any]:
        """
        Get global pattern matching precision metrics.

        Returns:
            Dictionary with overall precision metrics
        """
        all_analyses = await self.get_all_pattern_analyses(min_samples=10)

        if not all_analyses:
            return {
                "overall_precision": 0.0,
                "patterns_analyzed": 0,
                "patterns_meeting_target": 0,
                "target_precision": 0.90,
                "needs_improvement": [],
            }

        # Calculate weighted average precision
        total_samples = sum(a.sample_count for a in all_analyses)
        weighted_precision = (
            sum(a.precision * a.sample_count for a in all_analyses) / total_samples
            if total_samples > 0
            else 0.0
        )

        # Count patterns meeting target
        target_precision = 0.90
        patterns_meeting_target = sum(
            1 for a in all_analyses if a.precision >= target_precision
        )

        # Identify patterns needing improvement
        needs_improvement = [
            {
                "pattern": a.pattern_name,
                "precision": a.precision,
                "samples": a.sample_count,
                "recommendations": a.recommendations,
            }
            for a in all_analyses
            if a.precision < target_precision
        ]

        return {
            "overall_precision": weighted_precision,
            "patterns_analyzed": len(all_analyses),
            "patterns_meeting_target": patterns_meeting_target,
            "target_precision": target_precision,
            "needs_improvement": needs_improvement,
            "best_patterns": [
                {"pattern": a.pattern_name, "precision": a.precision}
                for a in all_analyses[-5:]  # Top 5
            ],
            "worst_patterns": [
                {"pattern": a.pattern_name, "precision": a.precision}
                for a in all_analyses[:5]  # Bottom 5
            ],
        }

    def _generate_recommendations(
        self,
        precision: float,
        false_positive_counts: Dict[str, int],
        false_negative_counts: Dict[str, int],
        feedback_records: List[Dict[str, Any]],
    ) -> List[str]:
        """Generate improvement recommendations based on analysis."""
        recommendations = []

        # Precision-based recommendations
        if precision < 0.90:
            recommendations.append(
                f"Precision {precision:.1%} is below 90% target. "
                "Consider raising confidence threshold or refining pattern keywords."
            )

            # Top false positives
            if false_positive_counts:
                top_fp = max(false_positive_counts.items(), key=lambda x: x[1])
                recommendations.append(
                    f"Reduce false positives for '{top_fp[0]}' "
                    f"(occurred {top_fp[1]} times). "
                    "Add exclusion keywords or adjust pattern weights."
                )

            # Top false negatives
            if false_negative_counts:
                top_fn = max(false_negative_counts.items(), key=lambda x: x[1])
                recommendations.append(
                    f"Reduce false negatives for '{top_fn[0]}' "
                    f"(missed {top_fn[1]} times). "
                    "Add inclusion keywords or lower threshold for this capability."
                )

        # Confidence distribution recommendations
        avg_confidence = (
            sum(r.get("detected_confidence", 0) for r in feedback_records)
            / len(feedback_records)
            if feedback_records
            else 0
        )

        if avg_confidence < 0.70:
            recommendations.append(
                f"Average confidence {avg_confidence:.1%} is low. "
                "Pattern keywords may not be well-aligned with use cases."
            )

        return recommendations

    def _calculate_suggested_threshold(
        self, precision: float, feedback_records: List[Dict[str, Any]]
    ) -> float:
        """Calculate suggested confidence threshold based on feedback."""
        # Analyze confidence distribution of correct vs incorrect predictions
        correct_confidences = [
            r.get("detected_confidence", 0.5)
            for r in feedback_records
            if r.get("feedback_type") == "correct"
        ]

        incorrect_confidences = [
            r.get("detected_confidence", 0.5)
            for r in feedback_records
            if r.get("feedback_type") == "incorrect"
        ]

        if not correct_confidences or not incorrect_confidences:
            # Not enough data for sophisticated calculation
            if precision >= 0.90:
                return 0.70
            else:
                return 0.80

        # Find threshold that maximizes precision
        # Simple approach: use median of incorrect predictions as threshold
        import statistics

        threshold = statistics.median(incorrect_confidences)

        # Ensure threshold is reasonable (0.65 - 0.90)
        threshold = max(0.65, min(0.90, threshold))

        return float(threshold)

    async def _get_pattern_feedback_details(
        self, pattern_name: str
    ) -> List[Dict[str, Any]]:
        """
        Get detailed pattern feedback records.

        This is a helper that fetches raw feedback records from the database.
        """
        pool = await self.persistence._ensure_pool()
        if pool is None:
            return []
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM pattern_feedback_log
                WHERE pattern_name = $1
                ORDER BY created_at DESC
                """,
                pattern_name,
            )
            return [dict(row) for row in rows]

    async def _update_fp_fn_tracking(
        self, feedback_id: UUID, false_positives: List[str], false_negatives: List[str]
    ) -> None:
        """
        Update false positive/negative tracking for feedback record.

        Note: The database schema already supports arrays for these fields,
        but we need to update them separately since the record_pattern_feedback
        function doesn't handle them.
        """
        pool = await self.persistence._ensure_pool()
        if pool is None:
            return
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE pattern_feedback_log
                SET
                    false_positives = $2,
                    false_negatives = $3
                WHERE id = $1
                """,
                feedback_id,
                false_positives,
                false_negatives,
            )

    def _invalidate_cache(self, pattern_name: str) -> None:
        """Invalidate cached analysis for a pattern."""
        if pattern_name in self._analysis_cache:
            del self._analysis_cache[pattern_name]
            self.logger.debug(f"Invalidated cache for pattern '{pattern_name}'")

    async def cleanup(self) -> None:
        """Cleanup resources."""
        await self.persistence.close()
