#!/usr/bin/env python3
"""
Mixin Feature Extractor - ML-Powered Mixin Compatibility

Extracts features from mixin pairs and node types to train ML models for
compatibility prediction and recommendation.

Author: OmniClaude Autonomous Code Generation System
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MixinFeatureVector:
    """
    Feature vector for mixin compatibility prediction.

    Attributes:
        mixin_a_features: Encoded features for first mixin
        mixin_b_features: Encoded features for second mixin
        node_type_features: Encoded features for node type
        interaction_features: Features capturing mixin interactions
        combined_vector: Full feature vector for ML model
    """

    mixin_a_features: np.ndarray
    mixin_b_features: np.ndarray
    node_type_features: np.ndarray
    interaction_features: np.ndarray
    combined_vector: np.ndarray


@dataclass
class MixinCharacteristics:
    """
    Characteristics of a mixin for feature extraction.

    Attributes:
        name: Mixin name
        category: Mixin category (infrastructure, business, etc.)
        async_safe: Whether mixin supports async operations
        state_modifying: Whether mixin modifies state
        resource_intensive: Whether mixin uses significant resources
        external_dependencies: List of external system dependencies
        lifecycle_hooks: Lifecycle methods the mixin uses
        compatibility_tags: Tags describing compatibility characteristics
    """

    name: str
    category: str
    async_safe: bool = True
    state_modifying: bool = False
    resource_intensive: bool = False
    external_dependencies: list[str] = field(default_factory=list)
    lifecycle_hooks: list[str] = field(default_factory=list)
    compatibility_tags: set[str] = field(default_factory=set)


class MixinFeatureExtractor:
    """
    Extract features from mixin combinations for ML training and prediction.

    Features extracted:
    - Mixin categorical features (one-hot encoded)
    - Node type features
    - Compatibility characteristics (async, state, resources)
    - Interaction features (dependency conflicts, lifecycle conflicts)
    - Historical success patterns
    """

    # Mixin categories for feature extraction
    MIXIN_CATEGORIES = {
        # Infrastructure mixins
        "MixinCaching": "infrastructure",
        "MixinLogging": "infrastructure",
        "MixinMetrics": "infrastructure",
        "MixinHealthCheck": "infrastructure",
        "MixinEventBus": "infrastructure",
        # Resilience mixins
        "MixinRetry": "resilience",
        "MixinCircuitBreaker": "resilience",
        "MixinTimeout": "resilience",
        "MixinRateLimiter": "resilience",
        # Business logic mixins
        "MixinValidation": "business",
        "MixinSecurity": "business",
        "MixinAuthorization": "business",
        "MixinAudit": "business",
        # Data access mixins
        "MixinTransaction": "data_access",
        "MixinConnection": "data_access",
        "MixinRepository": "data_access",
    }

    # Node type compatibility profiles
    NODE_TYPE_PROFILES = {
        "EFFECT": {
            "async_required": True,
            "state_modifying": True,
            "resource_intensive": True,
            "external_access": True,
        },
        "COMPUTE": {
            "async_required": False,
            "state_modifying": False,
            "resource_intensive": False,
            "external_access": False,
        },
        "REDUCER": {
            "async_required": True,
            "state_modifying": True,
            "resource_intensive": True,
            "external_access": True,
        },
        "ORCHESTRATOR": {
            "async_required": True,
            "state_modifying": False,
            "resource_intensive": False,
            "external_access": True,
        },
    }

    # Known mixin characteristics
    MIXIN_CHARACTERISTICS: dict[str, MixinCharacteristics] = {}

    @classmethod
    def initialize_mixin_characteristics(cls):
        """Initialize known mixin characteristics database"""
        if cls.MIXIN_CHARACTERISTICS:
            return  # Already initialized

        cls.MIXIN_CHARACTERISTICS = {
            "MixinCaching": MixinCharacteristics(
                name="MixinCaching",
                category="infrastructure",
                async_safe=True,
                state_modifying=True,
                resource_intensive=True,
                external_dependencies=["Redis", "Memcached"],
                lifecycle_hooks=["on_init", "on_cleanup"],
                compatibility_tags={"cache", "performance", "state"},
            ),
            "MixinLogging": MixinCharacteristics(
                name="MixinLogging",
                category="infrastructure",
                async_safe=True,
                state_modifying=False,
                resource_intensive=False,
                external_dependencies=[],
                lifecycle_hooks=["on_init"],
                compatibility_tags={"logging", "observability"},
            ),
            "MixinMetrics": MixinCharacteristics(
                name="MixinMetrics",
                category="infrastructure",
                async_safe=True,
                state_modifying=False,
                resource_intensive=False,
                external_dependencies=["Prometheus", "StatsD"],
                lifecycle_hooks=["on_init", "on_cleanup"],
                compatibility_tags={"metrics", "observability", "performance"},
            ),
            "MixinHealthCheck": MixinCharacteristics(
                name="MixinHealthCheck",
                category="infrastructure",
                async_safe=True,
                state_modifying=False,
                resource_intensive=False,
                external_dependencies=[],
                lifecycle_hooks=["on_init"],
                compatibility_tags={"health", "monitoring"},
            ),
            "MixinEventBus": MixinCharacteristics(
                name="MixinEventBus",
                category="infrastructure",
                async_safe=True,
                state_modifying=False,
                resource_intensive=False,
                external_dependencies=["Kafka", "Redpanda"],
                lifecycle_hooks=["on_init", "on_cleanup"],
                compatibility_tags={"events", "messaging"},
            ),
            "MixinRetry": MixinCharacteristics(
                name="MixinRetry",
                category="resilience",
                async_safe=True,
                state_modifying=False,
                resource_intensive=False,
                external_dependencies=[],
                lifecycle_hooks=[],
                compatibility_tags={"retry", "resilience", "fault-tolerance"},
            ),
            "MixinCircuitBreaker": MixinCharacteristics(
                name="MixinCircuitBreaker",
                category="resilience",
                async_safe=True,
                state_modifying=True,
                resource_intensive=False,
                external_dependencies=[],
                lifecycle_hooks=["on_init"],
                compatibility_tags={"circuit-breaker", "resilience", "fault-tolerance"},
            ),
            "MixinTimeout": MixinCharacteristics(
                name="MixinTimeout",
                category="resilience",
                async_safe=True,
                state_modifying=False,
                resource_intensive=False,
                external_dependencies=[],
                lifecycle_hooks=[],
                compatibility_tags={"timeout", "resilience"},
            ),
            "MixinRateLimiter": MixinCharacteristics(
                name="MixinRateLimiter",
                category="resilience",
                async_safe=True,
                state_modifying=True,
                resource_intensive=False,
                external_dependencies=["Redis"],
                lifecycle_hooks=["on_init"],
                compatibility_tags={"rate-limit", "resilience", "throttling"},
            ),
            "MixinValidation": MixinCharacteristics(
                name="MixinValidation",
                category="business",
                async_safe=True,
                state_modifying=False,
                resource_intensive=False,
                external_dependencies=[],
                lifecycle_hooks=[],
                compatibility_tags={"validation", "business-logic"},
            ),
            "MixinSecurity": MixinCharacteristics(
                name="MixinSecurity",
                category="business",
                async_safe=True,
                state_modifying=False,
                resource_intensive=False,
                external_dependencies=[],
                lifecycle_hooks=["on_init"],
                compatibility_tags={"security", "encryption", "auth"},
            ),
            "MixinAuthorization": MixinCharacteristics(
                name="MixinAuthorization",
                category="business",
                async_safe=True,
                state_modifying=False,
                resource_intensive=False,
                external_dependencies=["AuthService"],
                lifecycle_hooks=[],
                compatibility_tags={"authorization", "security", "rbac"},
            ),
            "MixinAudit": MixinCharacteristics(
                name="MixinAudit",
                category="business",
                async_safe=True,
                state_modifying=True,
                resource_intensive=False,
                external_dependencies=["AuditLog"],
                lifecycle_hooks=["on_init", "on_cleanup"],
                compatibility_tags={"audit", "logging", "compliance"},
            ),
            "MixinTransaction": MixinCharacteristics(
                name="MixinTransaction",
                category="data_access",
                async_safe=True,
                state_modifying=True,
                resource_intensive=True,
                external_dependencies=["Database"],
                lifecycle_hooks=["on_init", "on_commit", "on_rollback"],
                compatibility_tags={"transaction", "database", "state"},
            ),
            "MixinConnection": MixinCharacteristics(
                name="MixinConnection",
                category="data_access",
                async_safe=True,
                state_modifying=False,
                resource_intensive=True,
                external_dependencies=["Database"],
                lifecycle_hooks=["on_init", "on_cleanup"],
                compatibility_tags={"connection", "database", "pooling"},
            ),
            "MixinRepository": MixinCharacteristics(
                name="MixinRepository",
                category="data_access",
                async_safe=True,
                state_modifying=True,
                resource_intensive=False,
                external_dependencies=["Database"],
                lifecycle_hooks=["on_init"],
                compatibility_tags={"repository", "data-access", "crud"},
            ),
        }

    def __init__(self):
        """Initialize feature extractor"""
        self.logger = logging.getLogger(__name__)

        # Initialize mixin characteristics
        self.initialize_mixin_characteristics()

        # Build feature encoding indices
        self.mixin_to_idx = {
            mixin: idx for idx, mixin in enumerate(sorted(self.MIXIN_CATEGORIES.keys()))
        }
        self.node_type_to_idx = {
            node_type: idx
            for idx, node_type in enumerate(
                ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]
            )
        }
        self.category_to_idx = {
            category: idx
            for idx, category in enumerate(
                ["infrastructure", "resilience", "business", "data_access"]
            )
        }

        # Feature dimensions
        self.mixin_feature_dim = len(self.mixin_to_idx)
        self.node_type_feature_dim = len(self.node_type_to_idx)
        self.node_type_profile_dim = 4  # Profile features for node type
        self.category_feature_dim = len(self.category_to_idx)
        self.characteristic_feature_dim = 10  # Binary characteristics
        self.interaction_feature_dim = 15  # Interaction features

        self.total_feature_dim = (
            self.mixin_feature_dim * 2  # Two mixins
            + self.category_feature_dim * 2  # Two categories
            + self.node_type_feature_dim  # Node type one-hot
            + self.node_type_profile_dim  # Node type profile characteristics
            + self.characteristic_feature_dim * 2  # Characteristics for both mixins
            + self.interaction_feature_dim  # Interaction features
        )

        self.logger.info(
            f"Initialized MixinFeatureExtractor with {self.total_feature_dim} features"
        )

    def extract_features(
        self,
        mixin_a: str,
        mixin_b: str,
        node_type: str,
        historical_data: dict[str, Any] | None = None,
    ) -> MixinFeatureVector:
        """
        Extract feature vector for mixin pair and node type.

        Args:
            mixin_a: First mixin name
            mixin_b: Second mixin name
            node_type: Node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
            historical_data: Optional historical compatibility data

        Returns:
            MixinFeatureVector with all extracted features
        """
        # Ensure canonical ordering for consistency (alphabetical)
        if mixin_a > mixin_b:
            mixin_a, mixin_b = mixin_b, mixin_a

        # Extract mixin-specific features
        mixin_a_features = self._extract_mixin_features(mixin_a)
        mixin_b_features = self._extract_mixin_features(mixin_b)

        # Extract node type features
        node_type_features = self._extract_node_type_features(node_type)

        # Extract interaction features
        interaction_features = self._extract_interaction_features(
            mixin_a, mixin_b, node_type, historical_data
        )

        # Combine all features
        combined_vector = np.concatenate(
            [
                mixin_a_features,
                mixin_b_features,
                node_type_features,
                interaction_features,
            ]
        )

        return MixinFeatureVector(
            mixin_a_features=mixin_a_features,
            mixin_b_features=mixin_b_features,
            node_type_features=node_type_features,
            interaction_features=interaction_features,
            combined_vector=combined_vector,
        )

    def _extract_mixin_features(self, mixin_name: str) -> np.ndarray:
        """
        Extract features for a single mixin.

        Features:
        - One-hot encoding of mixin name
        - One-hot encoding of category
        - Binary characteristics (async_safe, state_modifying, etc.)

        Args:
            mixin_name: Mixin name

        Returns:
            Feature vector for the mixin
        """
        features = []

        # One-hot encoding of mixin name
        mixin_one_hot = np.zeros(self.mixin_feature_dim)
        if mixin_name in self.mixin_to_idx:
            mixin_one_hot[self.mixin_to_idx[mixin_name]] = 1.0
        features.append(mixin_one_hot)

        # Get mixin characteristics
        characteristics = self.MIXIN_CHARACTERISTICS.get(mixin_name)
        if characteristics:
            # One-hot encoding of category
            category_one_hot = np.zeros(self.category_feature_dim)
            if characteristics.category in self.category_to_idx:
                category_one_hot[self.category_to_idx[characteristics.category]] = 1.0
            features.append(category_one_hot)

            # Binary characteristics
            char_features = np.array(
                [
                    1.0 if characteristics.async_safe else 0.0,
                    1.0 if characteristics.state_modifying else 0.0,
                    1.0 if characteristics.resource_intensive else 0.0,
                    float(
                        len(characteristics.external_dependencies)
                    ),  # Number of dependencies
                    float(
                        len(characteristics.lifecycle_hooks)
                    ),  # Number of lifecycle hooks
                    1.0 if "cache" in characteristics.compatibility_tags else 0.0,
                    1.0 if "resilience" in characteristics.compatibility_tags else 0.0,
                    1.0 if "security" in characteristics.compatibility_tags else 0.0,
                    1.0 if "database" in characteristics.compatibility_tags else 0.0,
                    1.0 if "messaging" in characteristics.compatibility_tags else 0.0,
                ]
            )
            features.append(char_features)
        else:
            # Unknown mixin - use zero vectors
            features.append(np.zeros(self.category_feature_dim))
            features.append(np.zeros(self.characteristic_feature_dim))

        return np.concatenate(features)

    def _extract_node_type_features(self, node_type: str) -> np.ndarray:
        """
        Extract features for node type.

        Features:
        - One-hot encoding of node type
        - Binary characteristics from node type profile

        Args:
            node_type: Node type

        Returns:
            Feature vector for node type
        """
        # One-hot encoding
        node_type_one_hot = np.zeros(self.node_type_feature_dim)
        if node_type in self.node_type_to_idx:
            node_type_one_hot[self.node_type_to_idx[node_type]] = 1.0

        # Node type profile characteristics
        profile = self.NODE_TYPE_PROFILES.get(node_type, {})
        profile_features = np.array(
            [
                1.0 if profile.get("async_required", False) else 0.0,
                1.0 if profile.get("state_modifying", False) else 0.0,
                1.0 if profile.get("resource_intensive", False) else 0.0,
                1.0 if profile.get("external_access", False) else 0.0,
            ]
        )

        return np.concatenate([node_type_one_hot, profile_features])

    def _extract_interaction_features(
        self,
        mixin_a: str,
        mixin_b: str,
        node_type: str,
        historical_data: dict[str, Any] | None = None,
    ) -> np.ndarray:
        """
        Extract interaction features between mixin pair and node type.

        Features:
        - Category compatibility (same vs different)
        - Lifecycle hook conflicts
        - External dependency conflicts
        - State modification conflicts
        - Historical success rate
        - Historical failure patterns

        Args:
            mixin_a: First mixin
            mixin_b: Second mixin
            node_type: Node type
            historical_data: Optional historical compatibility data

        Returns:
            Interaction feature vector
        """
        char_a = self.MIXIN_CHARACTERISTICS.get(mixin_a)
        char_b = self.MIXIN_CHARACTERISTICS.get(mixin_b)

        if not char_a or not char_b:
            # Unknown mixins - return zero features
            return np.zeros(self.interaction_feature_dim)

        # Category compatibility
        same_category = 1.0 if char_a.category == char_b.category else 0.0

        # Lifecycle hook overlap
        hooks_a = set(char_a.lifecycle_hooks)
        hooks_b = set(char_b.lifecycle_hooks)
        hook_overlap = float(len(hooks_a & hooks_b))
        hook_conflict = 1.0 if hook_overlap > 0 else 0.0

        # External dependency overlap
        deps_a = set(char_a.external_dependencies)
        deps_b = set(char_b.external_dependencies)
        dep_overlap = float(len(deps_a & deps_b))

        # State modification conflict
        both_modify_state = (
            1.0 if (char_a.state_modifying and char_b.state_modifying) else 0.0
        )

        # Resource intensity
        both_resource_intensive = (
            1.0 if (char_a.resource_intensive and char_b.resource_intensive) else 0.0
        )

        # Compatibility tag overlap
        tags_a = char_a.compatibility_tags
        tags_b = char_b.compatibility_tags
        tag_overlap = float(len(tags_a & tags_b))

        # Node type compatibility
        self.NODE_TYPE_PROFILES.get(node_type, {})
        async_compatible = 1.0 if (char_a.async_safe and char_b.async_safe) else 0.0

        # Historical features
        if historical_data:
            historical_success_rate = historical_data.get("success_rate", 0.5)
            historical_total_tests = (
                min(historical_data.get("total_tests", 0), 100) / 100.0
            )  # Normalize
            historical_avg_compatibility = historical_data.get("avg_compatibility", 0.5)
        else:
            historical_success_rate = 0.5  # Neutral prior
            historical_total_tests = 0.0
            historical_avg_compatibility = 0.5

        # Combine interaction features
        interaction_features = np.array(
            [
                same_category,
                hook_overlap,
                hook_conflict,
                dep_overlap,
                both_modify_state,
                both_resource_intensive,
                tag_overlap,
                async_compatible,
                historical_success_rate,
                historical_total_tests,
                historical_avg_compatibility,
                # Additional derived features
                (
                    1.0 if (same_category and tag_overlap > 0) else 0.0
                ),  # Strong category + tag match
                (
                    1.0 if (hook_conflict and both_modify_state) else 0.0
                ),  # High conflict potential
                float(len(deps_a) + len(deps_b)),  # Total external dependencies
                (
                    1.0
                    if (
                        char_a.category == "data_access"
                        or char_b.category == "data_access"
                    )
                    else 0.0
                ),
            ]
        )

        return interaction_features

    def batch_extract_features(
        self,
        mixin_pairs: list[tuple[str, str, str]],
        historical_data_map: dict[tuple[str, str, str], dict[str, Any]] | None = None,
    ) -> np.ndarray:
        """
        Extract features for multiple mixin pairs efficiently.

        Args:
            mixin_pairs: List of (mixin_a, mixin_b, node_type) tuples
            historical_data_map: Optional map of historical data per pair

        Returns:
            2D numpy array of shape (n_samples, n_features)
        """
        feature_vectors = []

        for mixin_a, mixin_b, node_type in mixin_pairs:
            historical_data = None
            if historical_data_map:
                # Try both orderings
                key1 = (mixin_a, mixin_b, node_type)
                key2 = (mixin_b, mixin_a, node_type)
                historical_data = historical_data_map.get(
                    key1, historical_data_map.get(key2)
                )

            feature_vector = self.extract_features(
                mixin_a, mixin_b, node_type, historical_data
            )
            feature_vectors.append(feature_vector.combined_vector)

        return np.array(feature_vectors)

    def get_feature_names(self) -> list[str]:
        """
        Get human-readable feature names for interpretability.

        Returns:
            List of feature names matching feature vector indices
        """
        feature_names = []

        # Mixin A features
        for mixin in sorted(self.mixin_to_idx.keys()):
            feature_names.append(f"mixin_a_{mixin}")
        for category in sorted(self.category_to_idx.keys()):
            feature_names.append(f"mixin_a_category_{category}")
        for char in [
            "async_safe",
            "state_modifying",
            "resource_intensive",
            "n_dependencies",
            "n_lifecycle_hooks",
            "tag_cache",
            "tag_resilience",
            "tag_security",
            "tag_database",
            "tag_messaging",
        ]:
            feature_names.append(f"mixin_a_{char}")

        # Mixin B features (same structure)
        for mixin in sorted(self.mixin_to_idx.keys()):
            feature_names.append(f"mixin_b_{mixin}")
        for category in sorted(self.category_to_idx.keys()):
            feature_names.append(f"mixin_b_category_{category}")
        for char in [
            "async_safe",
            "state_modifying",
            "resource_intensive",
            "n_dependencies",
            "n_lifecycle_hooks",
            "tag_cache",
            "tag_resilience",
            "tag_security",
            "tag_database",
            "tag_messaging",
        ]:
            feature_names.append(f"mixin_b_{char}")

        # Node type features
        for node_type in ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]:
            feature_names.append(f"node_type_{node_type}")
        for profile_char in [
            "async_required",
            "state_modifying",
            "resource_intensive",
            "external_access",
        ]:
            feature_names.append(f"node_profile_{profile_char}")

        # Interaction features
        interaction_feature_names = [
            "same_category",
            "hook_overlap",
            "hook_conflict",
            "dep_overlap",
            "both_modify_state",
            "both_resource_intensive",
            "tag_overlap",
            "async_compatible",
            "historical_success_rate",
            "historical_total_tests",
            "historical_avg_compatibility",
            "category_tag_match",
            "high_conflict_potential",
            "total_dependencies",
            "involves_data_access",
        ]
        feature_names.extend(interaction_feature_names)

        return feature_names


__all__ = ["MixinCharacteristics", "MixinFeatureExtractor", "MixinFeatureVector"]
