#!/usr/bin/env python3
"""
Tests for Pattern Feedback System (Phase 7 Stream 5)

Tests the pattern feedback collection, analysis, and tuning system
to ensure ≥90% precision target is achievable.
"""

import pytest
import asyncio
from uuid import uuid4
from typing import Dict, Any, List
from datetime import datetime, timezone

# Import the modules we're testing
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.pattern_feedback import (
    PatternFeedback,
    PatternAnalysis,
    PatternFeedbackCollector
)
from lib.pattern_tuner import (
    PatternTuner,
    ThresholdConfig,
    TuningStrategy,
    TuningResult,
    ABTestConfig
)
from lib.patterns.pattern_matcher import PatternMatcher, PatternType


@pytest.fixture
def mock_persistence():
    """Mock persistence for testing"""
    class MockPersistence:
        def __init__(self):
            self.feedback_records: List[Dict[str, Any]] = []
            self.pattern_feedbacks: Dict[str, List[Dict[str, Any]]] = {}

        async def _ensure_pool(self):
            # Mock pool
            class MockConnection:
                def __init__(self, parent):
                    self.parent = parent

                async def fetch(self, query, *args):
                    # Extract pattern name from query if present
                    if "WHERE pattern_name = $1" in query:
                        pattern_name = args[0] if args else None
                        return [
                            r for r in self.parent.feedback_records
                            if r.get('pattern_name') == pattern_name
                        ]
                    return self.parent.feedback_records

                async def fetchrow(self, query, *args):
                    rows = await self.fetch(query, *args)
                    return rows[0] if rows else None

                async def fetchval(self, query, *args):
                    return uuid4()

                async def execute(self, query, *args):
                    pass

            class MockPool:
                def __init__(self, parent):
                    self.parent = parent

                def acquire(self):
                    return MockAcquire(self.parent)

            class MockAcquire:
                def __init__(self, parent):
                    self.parent = parent

                async def __aenter__(self):
                    return MockConnection(self.parent)

                async def __aexit__(self, *args):
                    pass

            pool = MockPool(self)
            return pool

        async def record_pattern_feedback(
            self,
            session_id,
            pattern_name,
            detected_confidence,
            actual_pattern,
            feedback_type,
            user_provided=False,
            contract_json=None
        ):
            feedback_id = uuid4()
            record = {
                'id': feedback_id,
                'session_id': session_id,
                'pattern_name': pattern_name,
                'detected_confidence': detected_confidence,
                'actual_pattern': actual_pattern,
                'feedback_type': feedback_type,
                'user_provided': user_provided,
                'contract_json': contract_json,
                'false_positives': [],
                'false_negatives': [],
                'created_at': datetime.now(timezone.utc)
            }

            self.feedback_records.append(record)

            # Add to pattern-specific tracking
            if pattern_name not in self.pattern_feedbacks:
                self.pattern_feedbacks[pattern_name] = []
            self.pattern_feedbacks[pattern_name].append(record)

            return feedback_id

        async def get_pattern_feedback_analysis(self, pattern_name=None):
            if pattern_name:
                return [
                    {
                        'pattern_name': pattern_name,
                        'feedback_type': 'correct',
                        'feedback_count': len(self.pattern_feedbacks.get(pattern_name, [])),
                        'avg_confidence': 0.85
                    }
                ]
            else:
                # Return all patterns
                return [
                    {
                        'pattern_name': p,
                        'feedback_type': 'correct',
                        'feedback_count': len(records),
                        'avg_confidence': 0.85
                    }
                    for p, records in self.pattern_feedbacks.items()
                ]

        async def close(self):
            pass

    return MockPersistence()


@pytest.fixture
def feedback_collector(mock_persistence):
    """Create feedback collector with mock persistence"""
    return PatternFeedbackCollector(persistence=mock_persistence)


@pytest.fixture
def pattern_tuner(mock_persistence):
    """Create pattern tuner with mock persistence"""
    return PatternTuner(persistence=mock_persistence)


class TestPatternFeedbackCollector:
    """Test PatternFeedbackCollector functionality"""

    @pytest.mark.asyncio
    async def test_record_feedback_basic(self, feedback_collector):
        """Test basic feedback recording"""
        feedback = PatternFeedback(
            session_id=uuid4(),
            detected_pattern="CRUD",
            detected_confidence=0.85,
            actual_pattern="CRUD",
            feedback_type="correct",
            capabilities_matched=["create_user", "update_user"],
            false_positives=[],
            false_negatives=[]
        )

        feedback_id = await feedback_collector.record_feedback(feedback)

        assert feedback_id is not None
        assert len(feedback_collector.persistence.feedback_records) == 1

    @pytest.mark.asyncio
    async def test_record_feedback_with_fp_fn(self, feedback_collector):
        """Test feedback recording with false positives/negatives"""
        feedback = PatternFeedback(
            session_id=uuid4(),
            detected_pattern="TRANSFORMATION",
            detected_confidence=0.75,
            actual_pattern="TRANSFORMATION",
            feedback_type="partial",
            capabilities_matched=["transform_data"],
            false_positives=["validate_input"],
            false_negatives=["convert_format"]
        )

        feedback_id = await feedback_collector.record_feedback(feedback)

        assert feedback_id is not None
        record = feedback_collector.persistence.feedback_records[0]
        assert record['feedback_type'] == 'partial'

    @pytest.mark.asyncio
    async def test_analyze_feedback_insufficient_data(self, feedback_collector):
        """Test analysis with insufficient data"""
        # Record only a few feedback items
        for _ in range(5):
            feedback = PatternFeedback(
                session_id=uuid4(),
                detected_pattern="CRUD",
                detected_confidence=0.80,
                actual_pattern="CRUD",
                feedback_type="correct"
            )
            await feedback_collector.record_feedback(feedback)

        analysis = await feedback_collector.analyze_feedback("CRUD", min_samples=20)

        assert not analysis.sufficient_data
        assert analysis.sample_count == 5

    @pytest.mark.asyncio
    async def test_analyze_feedback_sufficient_data(self, feedback_collector):
        """Test analysis with sufficient data"""
        # Record 30 feedback items (20 correct, 10 incorrect)
        for i in range(30):
            feedback = PatternFeedback(
                session_id=uuid4(),
                detected_pattern="CRUD",
                detected_confidence=0.80,
                actual_pattern="CRUD",
                feedback_type="correct" if i < 20 else "incorrect"
            )
            await feedback_collector.record_feedback(feedback)

        analysis = await feedback_collector.analyze_feedback("CRUD", min_samples=20)

        assert analysis.sufficient_data
        assert analysis.sample_count == 30
        assert analysis.precision > 0.0  # Should have some precision
        assert analysis.correct_count == 20
        assert analysis.incorrect_count == 10

    @pytest.mark.asyncio
    async def test_analyze_feedback_high_precision(self, feedback_collector):
        """Test analysis with high precision patterns"""
        # Record 25 feedback items (24 correct, 1 incorrect)
        for i in range(25):
            feedback = PatternFeedback(
                session_id=uuid4(),
                detected_pattern="TRANSFORMATION",
                detected_confidence=0.85,
                actual_pattern="TRANSFORMATION",
                feedback_type="correct" if i < 24 else "incorrect"
            )
            await feedback_collector.record_feedback(feedback)

        analysis = await feedback_collector.analyze_feedback("TRANSFORMATION", min_samples=20)

        assert analysis.sufficient_data
        assert analysis.precision >= 0.90  # Should be 96% (24/25)
        # High precision patterns may not have recommendations if already meeting target
        assert analysis.recommendations is not None

    @pytest.mark.asyncio
    async def test_tune_pattern_threshold_high_precision(self, feedback_collector):
        """Test threshold tuning for high precision patterns"""
        # Record high precision pattern data
        for i in range(30):
            feedback = PatternFeedback(
                session_id=uuid4(),
                detected_pattern="AGGREGATION",
                detected_confidence=0.90,
                actual_pattern="AGGREGATION",
                feedback_type="correct" if i < 29 else "incorrect"
            )
            await feedback_collector.record_feedback(feedback)

        threshold = await feedback_collector.tune_pattern_threshold(
            "AGGREGATION",
            target_precision=0.90
        )

        # High precision should suggest lower threshold to increase recall
        assert threshold is not None
        assert 0.60 <= threshold <= 0.75

    @pytest.mark.asyncio
    async def test_tune_pattern_threshold_low_precision(self, feedback_collector):
        """Test threshold tuning for low precision patterns"""
        # Record low precision pattern data
        for i in range(30):
            feedback = PatternFeedback(
                session_id=uuid4(),
                detected_pattern="ORCHESTRATION",
                detected_confidence=0.70,
                actual_pattern="ORCHESTRATION",
                feedback_type="correct" if i < 20 else "incorrect"
            )
            await feedback_collector.record_feedback(feedback)

        threshold = await feedback_collector.tune_pattern_threshold(
            "ORCHESTRATION",
            target_precision=0.90
        )

        # Low precision should suggest higher threshold
        assert threshold is not None
        assert threshold >= 0.75

    @pytest.mark.asyncio
    async def test_global_precision_metrics(self, feedback_collector):
        """Test global precision metrics calculation"""
        # Record feedback for multiple patterns
        patterns = ["CRUD", "TRANSFORMATION", "AGGREGATION"]

        for pattern in patterns:
            for i in range(25):
                feedback = PatternFeedback(
                    session_id=uuid4(),
                    detected_pattern=pattern,
                    detected_confidence=0.80,
                    actual_pattern=pattern,
                    feedback_type="correct" if i < 22 else "incorrect"
                )
                await feedback_collector.record_feedback(feedback)

        metrics = await feedback_collector.get_global_precision_metrics()

        assert metrics['patterns_analyzed'] > 0
        assert 0.0 <= metrics['overall_precision'] <= 1.0
        assert metrics['target_precision'] == 0.90


class TestPatternTuner:
    """Test PatternTuner functionality"""

    @pytest.mark.asyncio
    async def test_tune_pattern_precision_first(self, pattern_tuner, mock_persistence):
        """Test pattern tuning with precision-first strategy"""
        # Add feedback data
        for i in range(30):
            await mock_persistence.record_pattern_feedback(
                session_id=uuid4(),
                pattern_name="CRUD",
                detected_confidence=0.75,
                actual_pattern="CRUD",
                feedback_type="correct" if i < 24 else "incorrect",
                user_provided=False
            )

        result = await pattern_tuner.tune_pattern(
            "CRUD",
            strategy=TuningStrategy.PRECISION_FIRST,
            min_samples=20
        )

        assert result.pattern_name == "CRUD"
        assert result.original_threshold > 0
        assert result.tuned_threshold > 0
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_tune_pattern_balanced(self, pattern_tuner, mock_persistence):
        """Test pattern tuning with balanced strategy"""
        # Add feedback data
        for i in range(25):
            await mock_persistence.record_pattern_feedback(
                session_id=uuid4(),
                pattern_name="TRANSFORMATION",
                detected_confidence=0.80,
                actual_pattern="TRANSFORMATION",
                feedback_type="correct" if i < 20 else "incorrect"
            )

        result = await pattern_tuner.tune_pattern(
            "TRANSFORMATION",
            strategy=TuningStrategy.BALANCED,
            min_samples=20
        )

        assert result.strategy_used == TuningStrategy.BALANCED
        assert len(result.recommendations) > 0

    @pytest.mark.asyncio
    async def test_apply_tuning_high_confidence(self, pattern_tuner, mock_persistence):
        """Test applying tuning with high confidence"""
        # Create mock tuning result
        tuning_result = TuningResult(
            pattern_name="CRUD",
            original_threshold=0.70,
            tuned_threshold=0.75,
            original_precision=0.85,
            estimated_precision=0.92,
            improvement=0.07,
            confidence=0.85,
            strategy_used=TuningStrategy.BALANCED,
            recommendations=["Raise threshold slightly"]
        )

        success = await pattern_tuner.apply_tuning(
            tuning_result,
            create_ab_test=False,
            min_confidence=0.70
        )

        assert success
        assert pattern_tuner._threshold_configs["CRUD"].confidence_threshold == 0.75

    @pytest.mark.asyncio
    async def test_apply_tuning_low_confidence(self, pattern_tuner):
        """Test applying tuning with low confidence"""
        tuning_result = TuningResult(
            pattern_name="ORCHESTRATION",
            original_threshold=0.70,
            tuned_threshold=0.80,
            original_precision=0.75,
            estimated_precision=0.82,
            improvement=0.07,
            confidence=0.50,  # Low confidence
            strategy_used=TuningStrategy.PRECISION_FIRST,
            recommendations=[]
        )

        success = await pattern_tuner.apply_tuning(
            tuning_result,
            create_ab_test=False,
            min_confidence=0.70
        )

        # Should fail due to low confidence
        assert not success

    @pytest.mark.asyncio
    async def test_create_ab_test(self, pattern_tuner):
        """Test A/B test creation"""
        test_config = await pattern_tuner.create_ab_test(
            pattern_name="TRANSFORMATION",
            threshold_a=0.70,
            threshold_b=0.80,
            traffic_split=0.5,
            min_samples=100
        )

        assert test_config.pattern_name == "TRANSFORMATION"
        assert test_config.variant_a.confidence_threshold == 0.70
        assert test_config.variant_b.confidence_threshold == 0.80
        assert test_config.status == "running"

    @pytest.mark.asyncio
    async def test_evaluate_ab_test(self, pattern_tuner, mock_persistence):
        """Test A/B test evaluation"""
        # Create A/B test
        test_config = await pattern_tuner.create_ab_test(
            pattern_name="CRUD",
            threshold_a=0.70,
            threshold_b=0.80,
            traffic_split=0.5,
            min_samples=20
        )

        # Add sufficient feedback
        for i in range(25):
            await mock_persistence.record_pattern_feedback(
                session_id=uuid4(),
                pattern_name="CRUD",
                detected_confidence=0.75,
                actual_pattern="CRUD",
                feedback_type="correct" if i < 22 else "incorrect"
            )

        winner = await pattern_tuner.evaluate_ab_test(test_config.test_id)

        assert winner in ['a', 'b']
        assert test_config.status == "completed"

    @pytest.mark.asyncio
    async def test_rollback_pattern(self, pattern_tuner):
        """Test pattern configuration rollback"""
        # Set a custom threshold
        pattern_tuner._update_threshold_config("AGGREGATION", 0.85)

        # Rollback
        success = await pattern_tuner.rollback_pattern("AGGREGATION")

        assert success
        # Should be back to default
        assert pattern_tuner._threshold_configs["AGGREGATION"].confidence_threshold == 0.70


class TestPatternMatcherIntegration:
    """Test pattern matcher integration with feedback system"""

    def test_pattern_matcher_with_learned_thresholds(self):
        """Test pattern matcher using learned thresholds"""
        matcher = PatternMatcher(use_learned_thresholds=True)

        # Set learned thresholds
        matcher.set_learned_threshold("CRUD", 0.80)
        matcher.set_learned_threshold("TRANSFORMATION", 0.75)

        # Test threshold retrieval
        crud_threshold = matcher.get_threshold(PatternType.CRUD)
        assert crud_threshold == 0.80

        transform_threshold = matcher.get_threshold(PatternType.TRANSFORMATION)
        assert transform_threshold == 0.75

    def test_pattern_matcher_threshold_filtering(self):
        """Test that pattern matches are filtered by learned thresholds"""
        matcher = PatternMatcher(use_learned_thresholds=True)

        # Set high threshold
        matcher.set_learned_threshold("CRUD", 0.90)

        # Test with a capability that might match CRUD
        capability = {
            "name": "Create User Record",
            "type": "create",
            "description": "Creates a new user record in database"
        }

        matches = matcher.match_patterns(capability)

        # Should only return matches above 0.90 threshold
        for match in matches:
            if match.pattern_type == PatternType.CRUD:
                assert match.confidence >= 0.90


class TestPrecisionTargets:
    """Test that 90% precision target is achievable"""

    @pytest.mark.asyncio
    async def test_achieve_90_percent_precision(self, feedback_collector):
        """Test that we can achieve 90% precision with proper tuning"""
        # Simulate high-quality feedback data (92% precision)
        pattern_name = "CRUD"
        total_samples = 100

        for i in range(total_samples):
            feedback = PatternFeedback(
                session_id=uuid4(),
                detected_pattern=pattern_name,
                detected_confidence=0.85,
                actual_pattern=pattern_name,
                feedback_type="correct" if i < 92 else "incorrect"
            )
            await feedback_collector.record_feedback(feedback)

        # Analyze
        analysis = await feedback_collector.analyze_feedback(pattern_name, min_samples=20)

        # Should exceed 90% target
        assert analysis.precision >= 0.90, \
            f"Precision {analysis.precision:.1%} below 90% target"

    @pytest.mark.asyncio
    async def test_tuning_improves_precision(self, pattern_tuner, mock_persistence):
        """Test that tuning can improve low-precision patterns"""
        # Simulate low precision data (75%)
        for i in range(40):
            await mock_persistence.record_pattern_feedback(
                session_id=uuid4(),
                pattern_name="ORCHESTRATION",
                detected_confidence=0.65,
                actual_pattern="ORCHESTRATION",
                feedback_type="correct" if i < 30 else "incorrect"
            )

        result = await pattern_tuner.tune_pattern(
            "ORCHESTRATION",
            strategy=TuningStrategy.PRECISION_FIRST,
            min_samples=20,
            target_precision=0.90
        )

        # Should suggest higher threshold
        assert result.tuned_threshold > result.original_threshold
        # Estimated precision should improve
        assert result.estimated_precision > result.original_precision


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
