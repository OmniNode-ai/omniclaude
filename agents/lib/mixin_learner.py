#!/usr/bin/env python3
"""
Mixin Compatibility Learner - ML-Powered Recommendations

Trains machine learning models to predict mixin compatibility and provide
intelligent recommendations for mixin combinations based on historical data.

Author: OmniClaude Autonomous Code Generation System
Target Accuracy: ≥95%

SECURITY NOTE:
    This module uses pickle for ML model serialization (standard Python ML practice).
    Pickle can execute arbitrary code during deserialization. Security measures:

    1. Model files are generated internally by this system (not from external sources)
    2. Model paths are controlled (not user-provided)
    3. Files are stored in trusted local directory (.cache/models/)
    4. Only load models from trusted sources

    For production deployments with untrusted model sources, consider:
    - Using joblib with compression instead of raw pickle
    - Implementing file integrity checks (SHA-256 hashes)
    - Using model signing/verification
    - Restricting file permissions (0600)

    References:
    - https://docs.python.org/3/library/pickle.html#module-pickle (security warnings)
    - https://owasp.org/www-community/vulnerabilities/Deserialization_of_untrusted_data
"""

import asyncio
import logging
import pickle  # noqa: S403 - pickle usage documented in module docstring
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Tuple

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import cross_val_score, train_test_split

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
    cross_val_scores: list[float]
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

    DEFAULT_MODEL_PATH = (
        Path(__file__).parent.parent / "models" / "mixin_compatibility_rf.pkl"
    )
    DEFAULT_METRICS_PATH = (
        Path(__file__).parent.parent / "models" / "mixin_compatibility_metrics.pkl"
    )

    def __init__(
        self,
        model_path: Path | None = None,
        auto_train: bool = False,
        min_confidence_threshold: float = 0.7,
        persistence: CodegenPersistence | None = None,
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

        # ML models
        self.model: RandomForestClassifier | None = None
        self.gb_model: GradientBoostingClassifier | None = None
        self.metrics: ModelMetrics | None = None

        # Feature extractor
        self.feature_extractor = MixinFeatureExtractor()

        # Persistence
        self.persistence = persistence or CodegenPersistence()

        # Feature cache for performance
        self._feature_cache: dict[tuple[str, str, str], np.ndarray] = {}

        # Prediction cache for even faster repeated predictions
        self._prediction_cache: dict[tuple[str, str, str], tuple[int, np.ndarray]] = {}

        # Load existing model if available
        if self.model_path.exists():
            self._load_model()
            self.logger.info(f"Loaded model from {self.model_path}")
        elif auto_train:
            # Schedule async training
            asyncio.create_task(self.train_model())

    def _load_model(self):
        """
        Load trained model and metrics from disk.

        Security: Model files are generated internally by this system in a trusted
        directory. For production with untrusted sources, implement file integrity
        checks before loading. See module docstring for security considerations.
        """
        try:
            # Load ML model (generated internally, trusted source)
            with open(self.model_path, "rb") as f:
                self.model = pickle.load(  # noqa: S301 - internal model files only
                    f
                )  # nosec B301

            if self.metrics_path.exists():
                # Load model metrics (generated internally, trusted source)
                with open(self.metrics_path, "rb") as f:
                    self.metrics = pickle.load(f)  # noqa: S301  # nosec B301

            self.logger.info("Successfully loaded model and metrics")

        except Exception as e:
            self.logger.error(f"Failed to load model: {e}")
            self.model = None
            self.metrics = None

    def _save_model(self):
        """Save trained model and metrics to disk"""
        try:
            with open(self.model_path, "wb") as f:
                pickle.dump(self.model, f)

            with open(self.metrics_path, "wb") as f:
                pickle.dump(self.metrics, f)

            self.logger.info(f"Saved model to {self.model_path}")

        except Exception as e:
            self.logger.error(f"Failed to save model: {e}")

    async def train_model(
        self, min_samples: int = 50, test_size: float = 0.2, cross_val_folds: int = 5
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

        # Prepare features and labels (X is ML convention for features)
        X, y, historical_map = self._prepare_training_data(training_data)  # noqa: N806

        # Split train/test (X_train, X_test are ML conventions)
        X_train, X_test, y_train, y_test = train_test_split(  # noqa: N806
            X, y, test_size=test_size, random_state=42, stratify=y
        )

        # Train ensemble of Random Forest and Gradient Boosting for better accuracy
        rf_model = RandomForestClassifier(
            n_estimators=200,  # More trees for better ensemble
            max_depth=20,  # Allow deeper trees for complex patterns
            min_samples_split=3,  # More flexible splitting
            min_samples_leaf=1,  # Allow finer granularity
            max_features="sqrt",  # Use sqrt of features for each split
            random_state=42,
            n_jobs=-1,
            class_weight="balanced",  # Handle imbalanced data
            bootstrap=True,
            oob_score=True,  # Out-of-bag score for validation
        )

        gb_model = GradientBoostingClassifier(
            n_estimators=150,
            max_depth=10,
            learning_rate=0.1,
            min_samples_split=3,
            min_samples_leaf=1,
            random_state=42,
            subsample=0.9,
        )

        self.logger.info("Training ensemble models (RF + GB)...")
        rf_model.fit(X_train, y_train)
        gb_model.fit(X_train, y_train)

        # Use Random Forest as primary model (better for this task)
        self.model = rf_model
        self.gb_model = gb_model  # Store GB model for ensemble predictions

        # Evaluate with ensemble voting
        rf_pred = rf_model.predict(X_test)
        gb_pred = gb_model.predict(X_test)

        # Ensemble prediction: use RF for primary, GB to break ties or boost confidence
        y_pred_list: list[int] = []
        for i in range(len(X_test)):
            if rf_pred[i] == gb_pred[i]:
                y_pred_list.append(int(rf_pred[i]))
            else:
                # When models disagree, use RF probability
                rf_proba = rf_model.predict_proba(X_test[i : i + 1])[0]
                y_pred_list.append(1 if rf_proba[1] > 0.6 else 0)
        y_pred = np.array(y_pred_list)

        rf_model.predict_proba(X_test)

        # Calculate metrics
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, average="binary", zero_division=0)
        recall = recall_score(y_test, y_pred, average="binary", zero_division=0)
        f1 = f1_score(y_test, y_pred, average="binary", zero_division=0)

        # Cross-validation
        cv_scores = cross_val_score(
            self.model, X_train, y_train, cv=cross_val_folds, scoring="accuracy"
        )

        self.metrics = ModelMetrics(
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1,
            cross_val_scores=cv_scores.tolist(),
            training_samples=len(X_train),
            test_samples=len(X_test),
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

        # Clear both caches after retraining to ensure consistency
        self._feature_cache.clear()
        self._prediction_cache.clear()

        return self.metrics

    async def _fetch_training_data(self) -> list[dict[str, Any]]:
        """
        Fetch training data from mixin_compatibility_matrix.

        Returns:
            List of compatibility records with features
        """
        pool = await self.persistence._ensure_pool()
        if pool is None:
            return []
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
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
            """
            )

            return [dict(row) for row in rows]

    def _prepare_training_data(
        self, training_data: list[dict[str, Any]]
    ) -> tuple[np.ndarray, np.ndarray, dict[tuple[str, str, str], dict[str, Any]]]:
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
            mixin_a = record["mixin_a"]
            mixin_b = record["mixin_b"]
            node_type = record["node_type"]

            # Calculate label (compatible if success_rate > 0.5)
            success_count = record["success_count"]
            failure_count = record["failure_count"]
            total_tests = success_count + failure_count

            if total_tests == 0:
                continue  # Skip records with no tests

            success_rate = success_count / total_tests
            label = 1 if success_rate > 0.5 else 0  # Binary classification

            mixin_pairs.append((mixin_a, mixin_b, node_type))
            labels.append(label)

            # Store historical data for feature extraction
            key = (mixin_a, mixin_b, node_type)
            # Use explicit None check to preserve zero compatibility scores
            compatibility = (
                record["compatibility_score"]
                if record["compatibility_score"] is not None
                else 0.5
            )
            historical_map[key] = {
                "success_rate": success_rate,
                "total_tests": total_tests,
                "avg_compatibility": float(compatibility),
            }

        # Extract features
        feature_matrix = self.feature_extractor.batch_extract_features(
            mixin_pairs, historical_map
        )

        return feature_matrix, np.array(labels), historical_map

    async def _fetch_historical_data(
        self, mixin_a: str, mixin_b: str, node_type: str
    ) -> dict[str, Any] | None:
        """
        Fetch historical data for mixin pair from database.

        Args:
            mixin_a: First mixin
            mixin_b: Second mixin
            node_type: Node type

        Returns:
            Historical data dict or None if not found
        """
        try:
            pool = await self.persistence._ensure_pool()
            if pool is None:
                return None
            async with pool.acquire() as conn:
                # Try both orderings
                row = await conn.fetchrow(
                    """
                    SELECT
                        success_count,
                        failure_count,
                        compatibility_score
                    FROM mixin_compatibility_matrix
                    WHERE (mixin_a = $1 AND mixin_b = $2 OR mixin_a = $2 AND mixin_b = $1)
                        AND node_type = $3
                    ORDER BY last_tested DESC
                    LIMIT 1
                """,
                    mixin_a,
                    mixin_b,
                    node_type,
                )

                if row:
                    total_tests = row["success_count"] + row["failure_count"]
                    if total_tests > 0:
                        # Use explicit None check to preserve zero compatibility scores
                        compatibility = (
                            row["compatibility_score"]
                            if row["compatibility_score"] is not None
                            else 0.5
                        )
                        return {
                            "success_rate": row["success_count"] / total_tests,
                            "total_tests": total_tests,
                            "avg_compatibility": float(compatibility),
                        }
        except Exception as e:
            self.logger.debug(f"Could not fetch historical data: {e}")

        return None

    def predict_compatibility(
        self,
        mixin_a: str,
        mixin_b: str,
        node_type: str,
        historical_data: dict[str, Any] | None = None,
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

        # Create canonical cache key (alphabetically sorted)
        sorted_mixins = sorted([mixin_a, mixin_b])
        cache_key: tuple[str, str, str] = (
            sorted_mixins[0],
            sorted_mixins[1],
            node_type,
        )

        # Check prediction cache first (fastest path)
        if cache_key in self._prediction_cache:
            cached_prediction, probabilities = self._prediction_cache[cache_key]
            confidence = float(probabilities[int(cached_prediction)])

            # Apply structural adjustments even for cached predictions
            prediction, confidence = self._adjust_confidence(
                mixin_a, mixin_b, node_type, cached_prediction, confidence
            )
        else:
            # Check feature cache
            if cache_key in self._feature_cache:
                feature_vector = self._feature_cache[cache_key]
            else:
                # Extract features
                features = self.feature_extractor.extract_features(
                    mixin_a, mixin_b, node_type, historical_data
                )
                feature_vector = features.combined_vector

                # Cache features for future use
                self._feature_cache[cache_key] = feature_vector

                # Limit feature cache size to prevent memory bloat
                if len(self._feature_cache) > 1000:
                    # Remove oldest 100 entries
                    keys_to_remove = list(self._feature_cache.keys())[:100]
                    for key in keys_to_remove:
                        del self._feature_cache[key]

            # Predict using features (avoid unnecessary reshape by using view)
            # Use np.atleast_2d for faster reshape
            feature_2d = np.atleast_2d(feature_vector)
            prediction = self.model.predict(feature_2d)[0]
            probabilities = self.model.predict_proba(feature_2d)[0]

            # Cache prediction result
            self._prediction_cache[cache_key] = (prediction, probabilities)

            # Limit prediction cache size
            if len(self._prediction_cache) > 1000:
                keys_to_remove = list(self._prediction_cache.keys())[:100]
                for key in keys_to_remove:
                    del self._prediction_cache[key]

            # Confidence is the probability of the predicted class
            confidence = float(probabilities[int(prediction)])

            # Apply confidence adjustment and possible prediction override
            prediction, confidence = self._adjust_confidence(
                mixin_a, mixin_b, node_type, prediction, confidence
            )

        # Generate explanation (pass None for features as it's only used for metadata)
        explanation = self._generate_explanation(
            mixin_a, mixin_b, node_type, prediction, confidence, None
        )

        return MixinPrediction(
            mixin_a=mixin_a,
            mixin_b=mixin_b,
            node_type=node_type,
            compatible=bool(prediction),
            confidence=confidence,
            learned_from_samples=self.metrics.training_samples if self.metrics else 0,
            explanation=explanation,
        )

    def _adjust_confidence(
        self,
        mixin_a: str,
        mixin_b: str,
        node_type: str,
        prediction: int,
        base_confidence: float,
    ) -> Tuple[int, float]:
        """
        Adjust prediction and confidence based on strong structural indicators.
        Can override model prediction when structural evidence is very strong.

        Args:
            mixin_a: First mixin
            mixin_b: Second mixin
            node_type: Node type
            prediction: Predicted compatibility (0 or 1)
            base_confidence: Base confidence from model

        Returns:
            Tuple of (adjusted_prediction, adjusted_confidence)
        """
        char_a = MixinFeatureExtractor.MIXIN_CHARACTERISTICS.get(mixin_a)
        char_b = MixinFeatureExtractor.MIXIN_CHARACTERISTICS.get(mixin_b)

        if not char_a or not char_b:
            return prediction, base_confidence

        # Calculate structural compatibility score
        compat_score = 0.0
        incompat_score = 0.0

        # Positive indicators (compatibility)
        if char_a.category == char_b.category:
            compat_score += 0.15  # Same category is strong positive

        if char_a.async_safe and char_b.async_safe:
            compat_score += 0.08

        shared_tags = char_a.compatibility_tags & char_b.compatibility_tags
        if len(shared_tags) >= 1:
            compat_score += 0.10 * len(shared_tags)

        # Only flag state conflict if BOTH modify state
        if not (char_a.state_modifying and char_b.state_modifying):
            compat_score += 0.08

        # Check for complementary infrastructure mixins
        infra_pairs = [
            ("MixinLogging", "MixinMetrics"),
            ("MixinLogging", "MixinHealthCheck"),
            ("MixinMetrics", "MixinHealthCheck"),
            ("MixinRetry", "MixinCircuitBreaker"),
            ("MixinRetry", "MixinTimeout"),
            ("MixinCircuitBreaker", "MixinTimeout"),
            ("MixinTransaction", "MixinConnection"),
            ("MixinConnection", "MixinRepository"),
            ("MixinTransaction", "MixinRepository"),
        ]
        if (mixin_a, mixin_b) in infra_pairs or (mixin_b, mixin_a) in infra_pairs:
            compat_score += 0.25  # Known complementary pairs

        # Negative indicators (incompatibility)
        if mixin_a == mixin_b:
            incompat_score += 0.40  # Duplicate

        if char_a.state_modifying and char_b.state_modifying:
            incompat_score += 0.15  # Both modify state (potential conflict)

        if char_a.resource_intensive and char_b.resource_intensive:
            incompat_score += 0.10

        # Only flag lifecycle conflict if >1 shared hooks
        hooks_a = set(char_a.lifecycle_hooks)
        hooks_b = set(char_b.lifecycle_hooks)
        shared_hooks = hooks_a & hooks_b
        if len(shared_hooks) >= 2:
            incompat_score += 0.12

        # Determine if structural evidence is strong enough to override
        net_score = compat_score - incompat_score

        if net_score > 0.30:  # Strong compatibility evidence
            # Override to compatible if model predicted incompatible
            if prediction == 0:
                self.logger.debug(
                    f"Overriding incompatible prediction for {mixin_a}+{mixin_b}: "
                    f"structural score {net_score:.2f}"
                )
                prediction = 1
            # Boost confidence
            adjusted_confidence = min(max(base_confidence + 0.20, 0.75), 0.95)
        elif net_score < -0.30:  # Strong incompatibility evidence
            # Override to incompatible if model predicted compatible
            if prediction == 1:
                self.logger.debug(
                    f"Overriding compatible prediction for {mixin_a}+{mixin_b}: "
                    f"structural score {net_score:.2f}"
                )
                prediction = 0
            # Boost confidence
            adjusted_confidence = min(max(base_confidence + 0.20, 0.75), 0.95)
        else:  # Moderate evidence - just adjust confidence
            boost = max(0.0, abs(net_score) * 0.5)
            adjusted_confidence = min(base_confidence + boost, 0.95)

        return prediction, adjusted_confidence

    def _generate_explanation(
        self,
        mixin_a: str,
        mixin_b: str,
        node_type: str,
        prediction: int,
        confidence: float,
        features: Any,
    ) -> str:
        """Generate human-readable explanation for prediction"""
        char_a = MixinFeatureExtractor.MIXIN_CHARACTERISTICS.get(mixin_a)
        char_b = MixinFeatureExtractor.MIXIN_CHARACTERISTICS.get(mixin_b)

        if not char_a or not char_b:
            return (
                f"Prediction based on learned patterns (confidence: {confidence:.2%})"
            )

        explanations = []

        # Category compatibility
        if char_a.category == char_b.category:
            explanations.append(f"Both mixins are in '{char_a.category}' category")
        else:
            explanations.append(
                f"Mixins from different categories: '{char_a.category}' and '{char_b.category}'"
            )

        # Lifecycle conflicts
        hooks_a = set(char_a.lifecycle_hooks)
        hooks_b = set(char_b.lifecycle_hooks)
        if hooks_a & hooks_b:
            explanations.append(
                f"Shared lifecycle hooks: {', '.join(hooks_a & hooks_b)}"
            )

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
            explanations.append(
                f"Common capabilities: {', '.join(list(tags_a & tags_b)[:3])}"
            )

        result = "compatible" if prediction else "incompatible"
        explanation = f"Predicted {result} ({confidence:.2%} confidence). " + "; ".join(
            explanations[:3]
        )

        return explanation

    def recommend_mixins(
        self,
        node_type: str,
        required_capabilities: list[str],
        existing_mixins: list[str] | None = None,
        max_recommendations: int = 5,
    ) -> list[tuple[str, float, str]]:
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
                prediction = self.predict_compatibility(
                    existing_mixin, mixin, node_type
                )
                if (
                    not prediction.compatible
                    or prediction.confidence < self.min_confidence_threshold
                ):
                    compatible_with_all = False
                    break
                min_confidence = min(min_confidence, prediction.confidence)

            if not compatible_with_all:
                continue

            # Check if mixin provides required capabilities
            char = MixinFeatureExtractor.MIXIN_CHARACTERISTICS[mixin]
            capability_match = sum(
                1
                for cap in required_capabilities
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
        self, node_type: str, required_capabilities: list[str]
    ) -> list[tuple[str, float, str]]:
        """Fallback rule-based recommendations when model not available"""
        recommendations = []

        capability_map = {
            "cache": "MixinCaching",
            "caching": "MixinCaching",
            "logging": "MixinLogging",
            "metrics": "MixinMetrics",
            "health": "MixinHealthCheck",
            "monitoring": "MixinHealthCheck",
            "events": "MixinEventBus",
            "messaging": "MixinEventBus",
            "retry": "MixinRetry",
            "resilience": "MixinRetry",
            "circuit": "MixinCircuitBreaker",
            "timeout": "MixinTimeout",
            "validation": "MixinValidation",
            "security": "MixinSecurity",
            "auth": "MixinAuthorization",
            "audit": "MixinAudit",
            "transaction": "MixinTransaction",
            "database": "MixinConnection",
        }

        seen_mixins = set()
        for cap in required_capabilities:
            cap_lower = cap.lower()
            for keyword, mixin in capability_map.items():
                if keyword in cap_lower and mixin not in seen_mixins:
                    recommendations.append(
                        (mixin, 0.5, f"Rule-based match for '{cap}'")
                    )
                    seen_mixins.add(mixin)

        return recommendations

    async def update_from_feedback(
        self,
        mixin_a: str,
        mixin_b: str,
        node_type: str,
        success: bool,
        retrain_threshold: int = 100,
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
            mixin_a=mixin_a, mixin_b=mixin_b, node_type=node_type, success=success
        )

        # Check if retraining needed
        training_data = await self._fetch_training_data()
        if (
            self.metrics
            and len(training_data) >= self.metrics.training_samples + retrain_threshold
        ):
            self.logger.info(f"Retraining model with {len(training_data)} samples...")
            await self.train_model()

    def get_metrics(self) -> ModelMetrics | None:
        """Get current model metrics"""
        return self.metrics

    def is_trained(self) -> bool:
        """Check if model is trained"""
        return self.model is not None


__all__ = ["MixinLearner", "MixinPrediction", "ModelMetrics"]
