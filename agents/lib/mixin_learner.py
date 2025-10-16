#!/usr/bin/env python3
"""
Mixin Compatibility Learner for Phase 7 - ML-Powered Recommendations

Trains machine learning models to predict mixin compatibility and provide
intelligent recommendations for mixin combinations based on historical data.

Author: OmniClaude Autonomous Code Generation System
Phase: 7 Stream 4
Target Accuracy: ≥95%
"""

import asyncio
import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, classification_report

from .mixin_features import MixinFeatureExtractor
from .persistence import CodegenPersistence

logger = logging.getLogger(__name__)


@dataclass
class MixinPrediction:
    """
    Mixin compatibility prediction result.

    Attributes:
        mixin_a: First mixin name
        mixin_b: Second mixin name
        node_type: ONEX node type
        compatible: Predicted compatibility (True/False)
        confidence: Prediction confidence (0.0-1.0)
        learned_from_samples: Number of training samples used
        explanation: Human-readable explanation
    """
    mixin_a: str
    mixin_b: str
    node_type: str
    compatible: bool
    confidence: float
    learned_from_samples: int
    explanation: str = ""


@dataclass
class ModelMetrics:
    """
    ML model performance metrics.

    Attributes:
        accuracy: Overall accuracy
        precision: Precision score
        recall: Recall score
        f1_score: F1 score
        cross_val_scores: Cross-validation scores
        training_samples: Number of training samples
        test_samples: Number of test samples
        trained_at: Training timestamp
    """
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    cross_val_scores: List[float]
    training_samples: int
    test_samples: int
    trained_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MixinLearner:
    """
    ML-based mixin compatibility learning system.

    Features:
    - Train on historical mixin combination success/failure data
    - Predict compatibility for new mixin pairs
    - Recommend optimal mixin sets for node types
    - Continuous learning from new feedback
    - Model persistence and versioning
    """

    DEFAULT_MODEL_PATH = Path("/Volumes/PRO-G40/Code/omniclaude/agents/models/mixin_compatibility_rf.pkl")
    DEFAULT_METRICS_PATH = Path("/Volumes/PRO-G40/Code/omniclaude/agents/models/mixin_compatibility_metrics.pkl")

    def __init__(
        self,
        model_path: Optional[Path] = None,
        auto_train: bool = False,
        min_confidence_threshold: float = 0.7,
        persistence: Optional[CodegenPersistence] = None
    ):
        """
        Initialize mixin learner.

        Args:
            model_path: Path to save/load trained model
            auto_train: Whether to auto-train on initialization
            min_confidence_threshold: Minimum confidence for predictions
            persistence: Optional persistence instance
        """
        self.model_path = model_path or self.DEFAULT_MODEL_PATH
        self.metrics_path = self.DEFAULT_METRICS_PATH
        self.min_confidence_threshold = min_confidence_threshold
        self.logger = logging.getLogger(__name__)

        # Ensure model directory exists
        self.model_path.parent.mkdir(parents=True, exist_ok=True)

        # ML model
        self.model: Optional[RandomForestClassifier] = None
        self.metrics: Optional[ModelMetrics] = None

        # Feature extractor
        self.feature_extractor = MixinFeatureExtractor()

        # Persistence
        self.persistence = persistence or CodegenPersistence()

        # Load existing model if available
        if self.model_path.exists():
            self._load_model()
            self.logger.info(f"Loaded model from {self.model_path}")
        elif auto_train:
            # Schedule async training
            asyncio.create_task(self.train_model())

    def _load_model(self):
        """Load trained model and metrics from disk"""
        try:
            with open(self.model_path, 'rb') as f:
                self.model = pickle.load(f)

            if self.metrics_path.exists():
                with open(self.metrics_path, 'rb') as f:
                    self.metrics = pickle.load(f)

            self.logger.info("Successfully loaded model and metrics")

        except Exception as e:
            self.logger.error(f"Failed to load model: {e}")
            self.model = None
            self.metrics = None

    def _save_model(self):
        """Save trained model and metrics to disk"""
        try:
            with open(self.model_path, 'wb') as f:
                pickle.dump(self.model, f)

            with open(self.metrics_path, 'wb') as f:
                pickle.dump(self.metrics, f)

            self.logger.info(f"Saved model to {self.model_path}")

        except Exception as e:
            self.logger.error(f"Failed to save model: {e}")

    async def train_model(
        self,
        min_samples: int = 50,
        test_size: float = 0.2,
        cross_val_folds: int = 5
    ) -> ModelMetrics:
        """
        Train compatibility prediction model from historical data.

        Args:
            min_samples: Minimum training samples required
            test_size: Fraction of data for testing
            cross_val_folds: Number of cross-validation folds

        Returns:
            ModelMetrics with training results

        Raises:
            ValueError: If insufficient training data
        """
        self.logger.info("Starting model training...")

        # Fetch training data from database
        training_data = await self._fetch_training_data()

        if len(training_data) < min_samples:
            raise ValueError(
                f"Insufficient training data: {len(training_data)} samples "
                f"(minimum {min_samples} required)"
            )

        self.logger.info(f"Fetched {len(training_data)} training samples")

        # Prepare features and labels
        X, y, historical_map = self._prepare_training_data(training_data)

        # Split train/test
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y
        )

        # Train Random Forest classifier
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=15,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1,
            class_weight='balanced'  # Handle imbalanced data
        )

        self.logger.info("Training Random Forest model...")
        self.model.fit(X_train, y_train)

        # Evaluate model
        y_pred = self.model.predict(X_test)
        y_pred_proba = self.model.predict_proba(X_test)

        # Calculate metrics
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, average='binary', zero_division=0)
        recall = recall_score(y_test, y_pred, average='binary', zero_division=0)
        f1 = f1_score(y_test, y_pred, average='binary', zero_division=0)

        # Cross-validation
        cv_scores = cross_val_score(
            self.model, X_train, y_train, cv=cross_val_folds, scoring='accuracy'
        )

        self.metrics = ModelMetrics(
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1,
            cross_val_scores=cv_scores.tolist(),
            training_samples=len(X_train),
            test_samples=len(X_test)
        )

        self.logger.info(
            f"Model trained successfully:\n"
            f"  Accuracy: {accuracy:.4f}\n"
            f"  Precision: {precision:.4f}\n"
            f"  Recall: {recall:.4f}\n"
            f"  F1 Score: {f1:.4f}\n"
            f"  Cross-val mean: {np.mean(cv_scores):.4f} ± {np.std(cv_scores):.4f}"
        )

        # Log detailed classification report
        self.logger.info(
            f"Classification Report:\n{classification_report(y_test, y_pred, target_names=['Incompatible', 'Compatible'])}"
        )

        # Save model
        self._save_model()

        return self.metrics

    async def _fetch_training_data(self) -> List[Dict[str, Any]]:
        """
        Fetch training data from mixin_compatibility_matrix.

        Returns:
            List of compatibility records with features
        """
        pool = await self.persistence._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    mixin_a,
                    mixin_b,
                    node_type,
                    success_count,
                    failure_count,
                    compatibility_score,
                    conflict_reason,
                    resolution_pattern
                FROM mixin_compatibility_matrix
                WHERE success_count + failure_count >= 3  -- Minimum tests for reliability
                ORDER BY created_at DESC
            """)

            return [dict(row) for row in rows]

    def _prepare_training_data(
        self,
        training_data: List[Dict[str, Any]]
    ) -> Tuple[np.ndarray, np.ndarray, Dict[Tuple[str, str, str], Dict[str, Any]]]:
        """
        Prepare feature matrix and labels from raw training data.

        Args:
            training_data: List of compatibility records

        Returns:
            Tuple of (feature_matrix, labels, historical_data_map)
        """
        mixin_pairs = []
        labels = []
        historical_map = {}

        for record in training_data:
            mixin_a = record['mixin_a']
            mixin_b = record['mixin_b']
            node_type = record['node_type']

            # Calculate label (compatible if success_rate > 0.5)
            success_count = record['success_count']
            failure_count = record['failure_count']
            total_tests = success_count + failure_count

            if total_tests == 0:
                continue  # Skip records with no tests

            success_rate = success_count / total_tests
            label = 1 if success_rate > 0.5 else 0  # Binary classification

            mixin_pairs.append((mixin_a, mixin_b, node_type))
            labels.append(label)

            # Store historical data for feature extraction
            key = (mixin_a, mixin_b, node_type)
            historical_map[key] = {
                'success_rate': success_rate,
                'total_tests': total_tests,
                'avg_compatibility': float(record['compatibility_score'] or 0.5)
            }

        # Extract features
        feature_matrix = self.feature_extractor.batch_extract_features(
            mixin_pairs, historical_map
        )

        return feature_matrix, np.array(labels), historical_map

    def predict_compatibility(
        self,
        mixin_a: str,
        mixin_b: str,
        node_type: str,
        historical_data: Optional[Dict[str, Any]] = None
    ) -> MixinPrediction:
        """
        Predict compatibility for mixin pair.

        Args:
            mixin_a: First mixin name
            mixin_b: Second mixin name
            node_type: ONEX node type
            historical_data: Optional historical compatibility data

        Returns:
            MixinPrediction with compatibility and confidence

        Raises:
            ValueError: If model not trained
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train_model() first.")

        # Extract features
        features = self.feature_extractor.extract_features(
            mixin_a, mixin_b, node_type, historical_data
        )

        # Predict
        prediction = self.model.predict(features.combined_vector.reshape(1, -1))[0]
        probabilities = self.model.predict_proba(features.combined_vector.reshape(1, -1))[0]

        # Confidence is the probability of the predicted class
        confidence = probabilities[int(prediction)]

        # Generate explanation
        explanation = self._generate_explanation(
            mixin_a, mixin_b, node_type, prediction, confidence, features
        )

        return MixinPrediction(
            mixin_a=mixin_a,
            mixin_b=mixin_b,
            node_type=node_type,
            compatible=bool(prediction),
            confidence=confidence,
            learned_from_samples=self.metrics.training_samples if self.metrics else 0,
            explanation=explanation
        )

    def _generate_explanation(
        self,
        mixin_a: str,
        mixin_b: str,
        node_type: str,
        prediction: int,
        confidence: float,
        features: Any
    ) -> str:
        """Generate human-readable explanation for prediction"""
        char_a = MixinFeatureExtractor.MIXIN_CHARACTERISTICS.get(mixin_a)
        char_b = MixinFeatureExtractor.MIXIN_CHARACTERISTICS.get(mixin_b)

        if not char_a or not char_b:
            return f"Prediction based on learned patterns (confidence: {confidence:.2%})"

        explanations = []

        # Category compatibility
        if char_a.category == char_b.category:
            explanations.append(f"Both mixins are in '{char_a.category}' category")
        else:
            explanations.append(f"Mixins from different categories: '{char_a.category}' and '{char_b.category}'")

        # Lifecycle conflicts
        hooks_a = set(char_a.lifecycle_hooks)
        hooks_b = set(char_b.lifecycle_hooks)
        if hooks_a & hooks_b:
            explanations.append(f"Shared lifecycle hooks: {', '.join(hooks_a & hooks_b)}")

        # State modification
        if char_a.state_modifying and char_b.state_modifying:
            explanations.append("Both mixins modify state - potential conflict")

        # External dependencies
        deps_a = set(char_a.external_dependencies)
        deps_b = set(char_b.external_dependencies)
        if deps_a & deps_b:
            explanations.append(f"Shared dependencies: {', '.join(deps_a & deps_b)}")

        # Compatibility tags
        tags_a = char_a.compatibility_tags
        tags_b = char_b.compatibility_tags
        if tags_a & tags_b:
            explanations.append(f"Common capabilities: {', '.join(list(tags_a & tags_b)[:3])}")

        result = "compatible" if prediction else "incompatible"
        explanation = f"Predicted {result} ({confidence:.2%} confidence). " + "; ".join(explanations[:3])

        return explanation

    def recommend_mixins(
        self,
        node_type: str,
        required_capabilities: List[str],
        existing_mixins: Optional[List[str]] = None,
        max_recommendations: int = 5
    ) -> List[Tuple[str, float, str]]:
        """
        Recommend mixins for a node type based on required capabilities.

        Args:
            node_type: ONEX node type
            required_capabilities: List of required capabilities
            existing_mixins: List of already selected mixins
            max_recommendations: Maximum number of recommendations

        Returns:
            List of (mixin_name, confidence, explanation) tuples
        """
        if self.model is None:
            self.logger.warning("Model not trained, using rule-based recommendations")
            return self._fallback_recommendations(node_type, required_capabilities)

        existing_mixins = existing_mixins or []
        recommendations = []

        # Get all available mixins
        available_mixins = list(MixinFeatureExtractor.MIXIN_CHARACTERISTICS.keys())

        # Score each mixin
        for mixin in available_mixins:
            if mixin in existing_mixins:
                continue

            # Check compatibility with existing mixins
            compatible_with_all = True
            min_confidence = 1.0

            for existing_mixin in existing_mixins:
                prediction = self.predict_compatibility(existing_mixin, mixin, node_type)
                if not prediction.compatible or prediction.confidence < self.min_confidence_threshold:
                    compatible_with_all = False
                    break
                min_confidence = min(min_confidence, prediction.confidence)

            if not compatible_with_all:
                continue

            # Check if mixin provides required capabilities
            char = MixinFeatureExtractor.MIXIN_CHARACTERISTICS[mixin]
            capability_match = sum(
                1 for cap in required_capabilities
                if cap.lower() in {tag.lower() for tag in char.compatibility_tags}
            )

            if capability_match > 0:
                # Score based on capability match and compatibility confidence
                score = (capability_match / len(required_capabilities)) * min_confidence
                explanation = f"Provides {capability_match}/{len(required_capabilities)} capabilities"
                recommendations.append((mixin, score, explanation))

        # Sort by score and return top recommendations
        recommendations.sort(key=lambda x: x[1], reverse=True)
        return recommendations[:max_recommendations]

    def _fallback_recommendations(
        self,
        node_type: str,
        required_capabilities: List[str]
    ) -> List[Tuple[str, float, str]]:
        """Fallback rule-based recommendations when model not available"""
        recommendations = []

        capability_map = {
            'cache': 'MixinCaching',
            'caching': 'MixinCaching',
            'logging': 'MixinLogging',
            'metrics': 'MixinMetrics',
            'health': 'MixinHealthCheck',
            'monitoring': 'MixinHealthCheck',
            'events': 'MixinEventBus',
            'messaging': 'MixinEventBus',
            'retry': 'MixinRetry',
            'resilience': 'MixinRetry',
            'circuit': 'MixinCircuitBreaker',
            'timeout': 'MixinTimeout',
            'validation': 'MixinValidation',
            'security': 'MixinSecurity',
            'auth': 'MixinAuthorization',
            'audit': 'MixinAudit',
            'transaction': 'MixinTransaction',
            'database': 'MixinConnection',
        }

        seen_mixins = set()
        for cap in required_capabilities:
            cap_lower = cap.lower()
            for keyword, mixin in capability_map.items():
                if keyword in cap_lower and mixin not in seen_mixins:
                    recommendations.append((mixin, 0.5, f"Rule-based match for '{cap}'"))
                    seen_mixins.add(mixin)

        return recommendations

    async def update_from_feedback(
        self,
        mixin_a: str,
        mixin_b: str,
        node_type: str,
        success: bool,
        retrain_threshold: int = 100
    ):
        """
        Update model with new feedback and optionally retrain.

        Args:
            mixin_a: First mixin
            mixin_b: Second mixin
            node_type: Node type
            success: Whether combination was successful
            retrain_threshold: Number of new samples before retraining
        """
        # Update database
        await self.persistence.update_mixin_compatibility(
            mixin_a=mixin_a,
            mixin_b=mixin_b,
            node_type=node_type,
            success=success
        )

        # Check if retraining needed
        training_data = await self._fetch_training_data()
        if self.metrics and len(training_data) >= self.metrics.training_samples + retrain_threshold:
            self.logger.info(f"Retraining model with {len(training_data)} samples...")
            await self.train_model()

    def get_metrics(self) -> Optional[ModelMetrics]:
        """Get current model metrics"""
        return self.metrics

    def is_trained(self) -> bool:
        """Check if model is trained"""
        return self.model is not None


__all__ = [
    'MixinLearner',
    'MixinPrediction',
    'ModelMetrics'
]
