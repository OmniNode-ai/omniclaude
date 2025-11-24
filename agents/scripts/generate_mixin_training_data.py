#!/usr/bin/env python3
# ruff: noqa: S311
"""
Training Data Generator for Mixin Compatibility Learning

Generates realistic training data for mixin compatibility ML model by simulating
known compatibility patterns and edge cases.

Note: Uses Python's random module for training data generation (not cryptographic).

Author: OmniClaude Autonomous Code Generation System
Phase: 7 Stream 4

Setup:
    Run from project root with proper PYTHONPATH:

        cd /path/to/omniclaude
        PYTHONPATH=/path/to/omniclaude python agents/scripts/generate_mixin_training_data.py --samples 200

    Or install the package in development mode:

        pip install -e .

Usage:
    python agents/scripts/generate_mixin_training_data.py --samples 200
"""

import argparse
import asyncio
import logging
import random
from typing import List, Tuple

from agents.lib.mixin_features import MixinFeatureExtractor
from agents.lib.persistence import CodegenPersistence


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Compatibility rules based on domain knowledge
COMPATIBILITY_RULES = {
    # Highly compatible pairs (same category, complementary)
    "highly_compatible": [
        ("MixinLogging", "MixinMetrics"),  # Both observability
        ("MixinLogging", "MixinHealthCheck"),  # Both infrastructure
        ("MixinRetry", "MixinCircuitBreaker"),  # Both resilience
        ("MixinRetry", "MixinTimeout"),  # Both resilience
        ("MixinCaching", "MixinMetrics"),  # Performance + monitoring
        ("MixinValidation", "MixinSecurity"),  # Both business logic
        ("MixinTransaction", "MixinConnection"),  # Both data access
        ("MixinEventBus", "MixinMetrics"),  # Messaging + monitoring
        ("MixinHealthCheck", "MixinMetrics"),  # Monitoring + observability
        ("MixinAuthorization", "MixinAudit"),  # Security + compliance
    ],
    # Compatible pairs (different categories but complementary)
    "compatible": [
        ("MixinLogging", "MixinRetry"),  # Infrastructure + resilience
        ("MixinValidation", "MixinLogging"),  # Business + infrastructure
        ("MixinCaching", "MixinLogging"),  # Performance + observability
        ("MixinTransaction", "MixinLogging"),  # Data access + observability
        ("MixinEventBus", "MixinLogging"),  # Messaging + observability
        ("MixinSecurity", "MixinLogging"),  # Security + observability
        ("MixinRetry", "MixinLogging"),  # Resilience + observability
        ("MixinCircuitBreaker", "MixinMetrics"),  # Resilience + monitoring
        ("MixinRateLimiter", "MixinMetrics"),  # Resilience + monitoring
        ("MixinValidation", "MixinRetry"),  # Business + resilience
    ],
    # Potentially incompatible pairs (lifecycle conflicts)
    "uncertain": [
        ("MixinCaching", "MixinTransaction"),  # Cache + transaction state
        ("MixinCircuitBreaker", "MixinRetry"),  # Overlapping retry logic
        ("MixinTransaction", "MixinRetry"),  # Transaction + retry complexity
        ("MixinCaching", "MixinCircuitBreaker"),  # State management conflicts
        ("MixinRateLimiter", "MixinCircuitBreaker"),  # Overlapping protection
    ],
    # Incompatible pairs (conflicting functionality)
    "incompatible": [
        ("MixinCaching", "MixinCaching"),  # Duplicate functionality
        ("MixinTransaction", "MixinTransaction"),  # Duplicate transactions
        ("MixinRetry", "MixinRetry"),  # Duplicate retry logic
        ("MixinCircuitBreaker", "MixinCircuitBreaker"),  # Duplicate circuit breakers
        ("MixinConnection", "MixinConnection"),  # Duplicate connections
    ],
}


# Node type specific compatibility patterns
NODE_TYPE_PATTERNS = {
    "EFFECT": {
        "preferred_mixins": [
            "MixinTransaction",
            "MixinConnection",
            "MixinValidation",
            "MixinLogging",
            "MixinMetrics",
            "MixinRetry",
        ],
        "avoid_mixins": [],
    },
    "COMPUTE": {
        "preferred_mixins": [
            "MixinValidation",
            "MixinLogging",
            "MixinMetrics",
            "MixinCaching",
        ],
        "avoid_mixins": [
            "MixinTransaction",
            "MixinConnection",
        ],  # Compute should be pure
    },
    "REDUCER": {
        "preferred_mixins": [
            "MixinTransaction",
            "MixinConnection",
            "MixinLogging",
            "MixinMetrics",
            "MixinValidation",
        ],
        "avoid_mixins": [],
    },
    "ORCHESTRATOR": {
        "preferred_mixins": [
            "MixinEventBus",
            "MixinLogging",
            "MixinMetrics",
            "MixinCircuitBreaker",
            "MixinRetry",
            "MixinHealthCheck",
        ],
        "avoid_mixins": [
            "MixinTransaction"
        ],  # Orchestrator shouldn't manage transactions
    },
}


def generate_training_samples(
    num_samples: int = 200,
) -> List[Tuple[str, str, str, bool, str]]:
    """
    Generate training samples with known compatibility outcomes.

    Args:
        num_samples: Number of samples to generate

    Returns:
        List of (mixin_a, mixin_b, node_type, success, reason) tuples
    """
    samples = []

    # Initialize feature extractor to get available mixins
    feature_extractor = MixinFeatureExtractor()
    available_mixins = list(feature_extractor.MIXIN_CHARACTERISTICS.keys())
    node_types = ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]

    # Generate samples from known compatibility rules (70% of data)
    rule_samples = int(num_samples * 0.7)

    for _ in range(rule_samples):
        # Randomly select compatibility level
        level = random.choices(
            list(COMPATIBILITY_RULES.keys()),
            weights=[30, 40, 20, 10],
            k=1,  # More compatible than incompatible
        )[0]

        pairs = COMPATIBILITY_RULES[level]
        mixin_a, mixin_b = random.choice(pairs)
        node_type = random.choice(node_types)

        # Determine success based on level
        if level == "highly_compatible":
            success_rate = random.uniform(0.95, 1.0)
        elif level == "compatible":
            success_rate = random.uniform(0.75, 0.95)
        elif level == "uncertain":
            random.choice([True, False])
            success_rate = random.uniform(0.4, 0.7)
        else:  # incompatible
            success_rate = random.uniform(0.0, 0.3)

        # Generate multiple test results for this combination
        num_tests = random.randint(3, 15)
        success_count = int(num_tests * success_rate)
        failure_count = num_tests - success_count

        reason = f"Generated from {level} rule"

        # Add sample with test counts
        samples.append(
            (mixin_a, mixin_b, node_type, success_count, failure_count, reason)
        )

    # Generate random samples (30% of data) for unknown combinations
    random_samples = num_samples - rule_samples

    for _ in range(random_samples):
        mixin_a, mixin_b = random.sample(available_mixins, 2)
        node_type = random.choice(node_types)

        # Check node type preferences
        node_pattern = NODE_TYPE_PATTERNS[node_type]

        # Calculate base compatibility
        char_a = feature_extractor.MIXIN_CHARACTERISTICS[mixin_a]
        char_b = feature_extractor.MIXIN_CHARACTERISTICS[mixin_b]

        # Same category bonus
        same_category = char_a.category == char_b.category
        success_prob = 0.7 if same_category else 0.5

        # Node type preference adjustment
        if (
            mixin_a in node_pattern["preferred_mixins"]
            or mixin_b in node_pattern["preferred_mixins"]
        ):
            success_prob += 0.15
        if (
            mixin_a in node_pattern["avoid_mixins"]
            or mixin_b in node_pattern["avoid_mixins"]
        ):
            success_prob -= 0.25

        # Lifecycle conflict penalty
        hooks_a = set(char_a.lifecycle_hooks)
        hooks_b = set(char_b.lifecycle_hooks)
        if hooks_a & hooks_b:
            success_prob -= 0.2

        # State modification conflict
        if char_a.state_modifying and char_b.state_modifying:
            success_prob -= 0.15

        # Clamp probability
        success_prob = max(0.1, min(0.95, success_prob))

        # Generate test results
        num_tests = random.randint(3, 12)
        success_count = int(num_tests * success_prob)
        failure_count = num_tests - success_count

        reason = "Generated from random sampling with heuristics"

        samples.append(
            (mixin_a, mixin_b, node_type, success_count, failure_count, reason)
        )

    logger.info(f"Generated {len(samples)} training samples")
    return samples


async def populate_database(samples: List[Tuple[str, str, str, int, int, str]]):
    """
    Populate database with training samples.

    Args:
        samples: List of training samples
    """
    persistence = CodegenPersistence()

    try:
        for idx, (
            mixin_a,
            mixin_b,
            node_type,
            success_count,
            failure_count,
            reason,
        ) in enumerate(samples):
            # Update compatibility matrix multiple times to simulate test history
            for _ in range(success_count):
                await persistence.update_mixin_compatibility(
                    mixin_a=mixin_a,
                    mixin_b=mixin_b,
                    node_type=node_type,
                    success=True,
                    resolution_pattern=f"Success: {reason}",
                )

            for _ in range(failure_count):
                await persistence.update_mixin_compatibility(
                    mixin_a=mixin_a,
                    mixin_b=mixin_b,
                    node_type=node_type,
                    success=False,
                    conflict_reason=f"Conflict: {reason}",
                )

            if (idx + 1) % 20 == 0:
                logger.info(f"Populated {idx + 1}/{len(samples)} samples")

        logger.info(f"Successfully populated {len(samples)} training samples")

    finally:
        await persistence.close()


async def generate_and_populate(num_samples: int):
    """Generate training data and populate database"""
    logger.info(f"Generating {num_samples} training samples...")

    samples = generate_training_samples(num_samples)

    logger.info("Populating database...")
    await populate_database(samples)

    logger.info("Training data generation complete!")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Generate mixin compatibility training data"
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=200,
        help="Number of training samples to generate (default: 200)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )

    args = parser.parse_args()

    # Set random seed for reproducibility
    random.seed(args.seed)

    # Run async generation
    asyncio.run(generate_and_populate(args.samples))


if __name__ == "__main__":
    main()
