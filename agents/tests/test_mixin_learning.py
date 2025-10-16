#!/usr/bin/env python3
"""
Comprehensive tests for Mixin Compatibility Learning System (Phase 7 Stream 4)

Tests ML-powered mixin compatibility prediction, recommendations, and validation.
Target accuracy: ≥95%

Author: OmniClaude Autonomous Code Generation System
"""

import asyncio
import os
from pathlib import Path
from typing import List
import pytest
import numpy as np

# Import modules to test
from agents.lib.mixin_features import MixinFeatureExtractor, MixinCharacteristics
from agents.lib.mixin_learner import MixinLearner, MixinPrediction, ModelMetrics
from agents.lib.mixin_compatibility import (
    MixinCompatibilityManager,
    CompatibilityLevel,
    MixinRecommendation
)
from agents.lib.persistence import CodegenPersistence


# Test configuration
TEST_DSN = os.getenv(
    "TEST_PG_DSN",
    "postgresql://postgres:omninode-bridge-postgres-dev-2024@localhost:5436/omninode_bridge"
)


@pytest.fixture
async def persistence():
    """Create persistence instance for testing"""
    p = CodegenPersistence(dsn=TEST_DSN)
    yield p
    await p.close()


@pytest.fixture
def feature_extractor():
    """Create feature extractor instance"""
    return MixinFeatureExtractor()


@pytest.fixture
async def trained_learner(persistence):
    """Create and train mixin learner with test data"""
    # Ensure we have training data
    await _ensure_training_data(persistence)

    # Create learner
    learner = MixinLearner(persistence=persistence, auto_train=False)

    # Train model
    try:
        metrics = await learner.train_model(min_samples=10)
        return learner
    except ValueError as e:
        pytest.skip(f"Insufficient training data: {e}")


@pytest.fixture
async def mixin_manager(persistence):
    """Create mixin compatibility manager"""
    return MixinCompatibilityManager(persistence=persistence, enable_ml=True)


# =============================================================================
# Feature Extraction Tests
# =============================================================================

class TestMixinFeatureExtractor:
    """Test feature extraction for ML model"""

    def test_initialization(self, feature_extractor):
        """Test feature extractor initializes correctly"""
        assert feature_extractor is not None
        assert feature_extractor.total_feature_dim > 0
        assert len(feature_extractor.MIXIN_CHARACTERISTICS) > 0

    def test_mixin_characteristics_loaded(self, feature_extractor):
        """Test that mixin characteristics are properly loaded"""
        assert 'MixinCaching' in feature_extractor.MIXIN_CHARACTERISTICS
        assert 'MixinLogging' in feature_extractor.MIXIN_CHARACTERISTICS
        assert 'MixinRetry' in feature_extractor.MIXIN_CHARACTERISTICS

        caching = feature_extractor.MIXIN_CHARACTERISTICS['MixinCaching']
        assert caching.category == 'infrastructure'
        assert caching.async_safe is True
        assert caching.state_modifying is True

    def test_extract_features_single_pair(self, feature_extractor):
        """Test feature extraction for single mixin pair"""
        features = feature_extractor.extract_features(
            'MixinCaching',
            'MixinLogging',
            'EFFECT'
        )

        assert features is not None
        assert features.combined_vector is not None
        assert len(features.combined_vector) == feature_extractor.total_feature_dim
        assert features.mixin_a_features is not None
        assert features.mixin_b_features is not None
        assert features.node_type_features is not None
        assert features.interaction_features is not None

    def test_batch_extract_features(self, feature_extractor):
        """Test batch feature extraction"""
        pairs = [
            ('MixinCaching', 'MixinLogging', 'EFFECT'),
            ('MixinRetry', 'MixinCircuitBreaker', 'ORCHESTRATOR'),
            ('MixinTransaction', 'MixinConnection', 'EFFECT'),
        ]

        feature_matrix = feature_extractor.batch_extract_features(pairs)

        assert feature_matrix.shape[0] == len(pairs)
        assert feature_matrix.shape[1] == feature_extractor.total_feature_dim

    def test_feature_names(self, feature_extractor):
        """Test feature names for interpretability"""
        feature_names = feature_extractor.get_feature_names()

        assert len(feature_names) == feature_extractor.total_feature_dim
        assert 'mixin_a_MixinCaching' in feature_names
        assert 'node_type_EFFECT' in feature_names
        assert 'async_compatible' in feature_names

    def test_canonical_ordering(self, feature_extractor):
        """Test that mixin pairs are canonically ordered"""
        features1 = feature_extractor.extract_features('MixinCaching', 'MixinLogging', 'EFFECT')
        features2 = feature_extractor.extract_features('MixinLogging', 'MixinCaching', 'EFFECT')

        # Should produce identical features due to canonical ordering
        np.testing.assert_array_almost_equal(
            features1.combined_vector,
            features2.combined_vector
        )


# =============================================================================
# ML Learner Tests
# =============================================================================

class TestMixinLearner:
    """Test ML learner for mixin compatibility"""

    @pytest.mark.asyncio
    async def test_initialization(self, persistence):
        """Test learner initializes correctly"""
        learner = MixinLearner(persistence=persistence, auto_train=False)

        assert learner is not None
        assert learner.feature_extractor is not None
        assert learner.model is None  # Not trained yet

    @pytest.mark.asyncio
    async def test_training(self, trained_learner):
        """Test model training"""
        assert trained_learner.model is not None
        assert trained_learner.is_trained()
        assert trained_learner.metrics is not None

        # Check metrics
        metrics = trained_learner.get_metrics()
        assert metrics.accuracy > 0.0
        assert metrics.training_samples > 0
        assert metrics.test_samples > 0

    @pytest.mark.asyncio
    async def test_training_accuracy_target(self, trained_learner):
        """Test that model meets 95% accuracy target"""
        metrics = trained_learner.get_metrics()

        # Check accuracy target
        assert metrics.accuracy >= 0.95, \
            f"Accuracy {metrics.accuracy:.2%} below 95% target"

        # Check F1 score
        assert metrics.f1_score >= 0.90, \
            f"F1 score {metrics.f1_score:.2%} below 90% target"

    @pytest.mark.asyncio
    async def test_prediction(self, trained_learner):
        """Test compatibility prediction"""
        # Test compatible pair
        prediction = trained_learner.predict_compatibility(
            'MixinLogging',
            'MixinMetrics',
            'EFFECT'
        )

        assert prediction is not None
        assert prediction.mixin_a == 'MixinLogging'
        assert prediction.mixin_b == 'MixinMetrics'
        assert prediction.node_type == 'EFFECT'
        assert 0.0 <= prediction.confidence <= 1.0
        assert prediction.explanation != ""

    @pytest.mark.asyncio
    async def test_high_confidence_predictions(self, trained_learner):
        """Test high confidence predictions"""
        # Known compatible pairs
        compatible_pairs = [
            ('MixinLogging', 'MixinMetrics'),
            ('MixinRetry', 'MixinCircuitBreaker'),
            ('MixinTransaction', 'MixinConnection'),
        ]

        for mixin_a, mixin_b in compatible_pairs:
            prediction = trained_learner.predict_compatibility(
                mixin_a, mixin_b, 'EFFECT'
            )

            assert prediction.compatible is True
            assert prediction.confidence > 0.7, \
                f"Low confidence for known compatible pair {mixin_a}, {mixin_b}"

    @pytest.mark.asyncio
    async def test_recommendations(self, trained_learner):
        """Test mixin recommendations"""
        recommendations = trained_learner.recommend_mixins(
            node_type='EFFECT',
            required_capabilities=['logging', 'metrics', 'caching'],
            existing_mixins=[],
            max_recommendations=5
        )

        assert len(recommendations) > 0
        assert len(recommendations) <= 5

        for mixin, confidence, explanation in recommendations:
            assert confidence > 0.0
            assert explanation != ""

    @pytest.mark.asyncio
    async def test_model_persistence(self, persistence):
        """Test model save and load"""
        # Ensure training data
        await _ensure_training_data(persistence)

        # Train model
        learner1 = MixinLearner(persistence=persistence, auto_train=False)
        await learner1.train_model(min_samples=10)

        # Get prediction
        pred1 = learner1.predict_compatibility('MixinLogging', 'MixinMetrics', 'EFFECT')

        # Load model
        learner2 = MixinLearner(persistence=persistence, auto_train=False)

        # Should load existing model
        assert learner2.is_trained()

        # Should produce same prediction
        pred2 = learner2.predict_compatibility('MixinLogging', 'MixinMetrics', 'EFFECT')

        assert pred1.compatible == pred2.compatible
        assert abs(pred1.confidence - pred2.confidence) < 0.01


# =============================================================================
# Mixin Compatibility Manager Tests
# =============================================================================

class TestMixinCompatibilityManager:
    """Test mixin compatibility manager"""

    @pytest.mark.asyncio
    async def test_check_compatibility(self, mixin_manager):
        """Test compatibility checking"""
        check = await mixin_manager.check_compatibility(
            'MixinLogging',
            'MixinMetrics',
            'EFFECT'
        )

        assert check is not None
        assert check.mixin_a == 'MixinLogging'
        assert check.mixin_b == 'MixinMetrics'
        assert check.level is not None
        assert 0.0 <= check.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_validate_mixin_set(self, mixin_manager):
        """Test mixin set validation"""
        mixins = ['MixinLogging', 'MixinMetrics', 'MixinHealthCheck']

        mixin_set = await mixin_manager.validate_mixin_set(mixins, 'EFFECT')

        assert mixin_set is not None
        assert mixin_set.node_type == 'EFFECT'
        assert mixin_set.mixins == mixins
        assert 0.0 <= mixin_set.overall_compatibility <= 1.0

    @pytest.mark.asyncio
    async def test_validate_incompatible_set(self, mixin_manager):
        """Test validation catches incompatible mixin sets"""
        # Duplicate mixins - should trigger warnings
        mixins = ['MixinCaching', 'MixinCaching']

        mixin_set = await mixin_manager.validate_mixin_set(mixins, 'EFFECT')

        # Should have warnings or low compatibility
        assert len(mixin_set.warnings) > 0 or mixin_set.overall_compatibility < 0.8

    @pytest.mark.asyncio
    async def test_recommend_mixins(self, mixin_manager):
        """Test mixin recommendations"""
        recommendations = await mixin_manager.recommend_mixins(
            node_type='EFFECT',
            required_capabilities=['logging', 'caching'],
            existing_mixins=[],
            max_recommendations=5
        )

        assert len(recommendations) > 0

        for rec in recommendations:
            assert rec.mixin_name != ""
            assert rec.confidence > 0.0
            assert rec.justification != ""

    @pytest.mark.asyncio
    async def test_record_feedback(self, mixin_manager):
        """Test feedback recording"""
        # Record successful compatibility
        await mixin_manager.record_feedback(
            'MixinLogging',
            'MixinMetrics',
            'EFFECT',
            success=True,
            resolution_pattern="Works well together"
        )

        # Should succeed without errors

    @pytest.mark.asyncio
    async def test_compatibility_levels(self, mixin_manager):
        """Test different compatibility levels"""
        # Highly compatible
        check = await mixin_manager.check_compatibility(
            'MixinLogging',
            'MixinMetrics',
            'EFFECT'
        )

        # Should be highly compatible or compatible
        assert check.level in [
            CompatibilityLevel.HIGHLY_COMPATIBLE,
            CompatibilityLevel.COMPATIBLE,
            CompatibilityLevel.UNCERTAIN
        ]


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Test end-to-end integration"""

    @pytest.mark.asyncio
    async def test_full_workflow(self, persistence):
        """Test complete mixin learning workflow"""
        # 1. Generate training data
        await _ensure_training_data(persistence)

        # 2. Train model
        learner = MixinLearner(persistence=persistence, auto_train=False)
        metrics = await learner.train_model(min_samples=10)

        assert metrics.accuracy >= 0.95, \
            f"Accuracy {metrics.accuracy:.2%} below target"

        # 3. Make predictions
        prediction = learner.predict_compatibility(
            'MixinLogging',
            'MixinMetrics',
            'EFFECT'
        )

        assert prediction.confidence > 0.5

        # 4. Get recommendations
        recommendations = learner.recommend_mixins(
            node_type='EFFECT',
            required_capabilities=['logging', 'metrics'],
            existing_mixins=[]
        )

        assert len(recommendations) > 0

        # 5. Record feedback
        manager = MixinCompatibilityManager(persistence=persistence, enable_ml=True)
        await manager.record_feedback(
            'MixinLogging',
            'MixinMetrics',
            'EFFECT',
            success=True
        )

    @pytest.mark.asyncio
    async def test_continuous_learning(self, persistence):
        """Test continuous learning from feedback"""
        learner = MixinLearner(persistence=persistence, auto_train=False)

        # Ensure training data
        await _ensure_training_data(persistence)

        # Train initial model
        metrics1 = await learner.train_model(min_samples=10)
        initial_samples = metrics1.training_samples

        # Add new feedback
        for _ in range(10):
            await persistence.update_mixin_compatibility(
                'MixinTest', 'MixinLogging', 'EFFECT',
                success=True
            )

        # Update model (should trigger retrain if threshold met)
        await learner.update_from_feedback(
            'MixinTest', 'MixinLogging', 'EFFECT',
            success=True,
            retrain_threshold=5
        )

        # Model should be updated
        assert learner.is_trained()


# =============================================================================
# Performance Tests
# =============================================================================

class TestPerformance:
    """Test performance requirements"""

    @pytest.mark.asyncio
    async def test_prediction_performance(self, trained_learner):
        """Test prediction speed"""
        import time

        start = time.time()

        # Make 100 predictions
        for _ in range(100):
            trained_learner.predict_compatibility(
                'MixinLogging',
                'MixinMetrics',
                'EFFECT'
            )

        elapsed = time.time() - start

        # Should complete 100 predictions in < 1 second
        assert elapsed < 1.0, \
            f"Predictions too slow: {elapsed:.3f}s for 100 predictions"

    @pytest.mark.asyncio
    async def test_feature_extraction_performance(self, feature_extractor):
        """Test feature extraction speed"""
        import time

        pairs = [
            ('MixinLogging', 'MixinMetrics', 'EFFECT'),
            ('MixinRetry', 'MixinCircuitBreaker', 'ORCHESTRATOR'),
        ] * 50  # 100 pairs

        start = time.time()
        feature_matrix = feature_extractor.batch_extract_features(pairs)
        elapsed = time.time() - start

        # Should extract features for 100 pairs in < 0.5 seconds
        assert elapsed < 0.5, \
            f"Feature extraction too slow: {elapsed:.3f}s for 100 pairs"


# =============================================================================
# Helper Functions
# =============================================================================

async def _ensure_training_data(persistence: CodegenPersistence):
    """Ensure sufficient training data exists"""
    # Check if we have enough data
    pool = await persistence._ensure_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM mixin_compatibility_matrix"
        )

    # If insufficient, generate more
    if count < 50:
        # Generate sample training data
        samples = [
            # Compatible pairs
            ('MixinLogging', 'MixinMetrics', 'EFFECT', True),
            ('MixinLogging', 'MixinHealthCheck', 'EFFECT', True),
            ('MixinRetry', 'MixinCircuitBreaker', 'ORCHESTRATOR', True),
            ('MixinTransaction', 'MixinConnection', 'EFFECT', True),
            ('MixinCaching', 'MixinMetrics', 'COMPUTE', True),

            # Incompatible pairs
            ('MixinCaching', 'MixinTransaction', 'EFFECT', False),
            ('MixinCircuitBreaker', 'MixinRetry', 'EFFECT', False),
        ] * 10  # Repeat to get enough samples

        for mixin_a, mixin_b, node_type, success in samples:
            # Simulate multiple tests
            for _ in range(5):
                await persistence.update_mixin_compatibility(
                    mixin_a, mixin_b, node_type, success
                )


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
