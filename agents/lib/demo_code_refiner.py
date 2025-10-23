#!/usr/bin/env python3
"""
Code Refiner Demo - Pattern Matcher & Applicator

Demonstrates how to use ProductionPatternMatcher and CodeRefiner to
apply production ONEX patterns to generated code.

Usage:
    python -m agents.lib.demo_code_refiner
"""

import asyncio
import os
from pathlib import Path

from agents.lib.code_refiner import CodeRefiner, ProductionPatternMatcher

# ============================================================================
# Sample Generated Code (Before Refinement)
# ============================================================================

SAMPLE_EFFECT_NODE = '''
"""Database writer effect node."""

class NodeDatabaseWriterEffect:
    """Writes data to database."""

    def __init__(self, db_client):
        self.db_client = db_client

    def execute_effect(self, contract):
        """Execute database write."""
        # Write to database
        result = self.db_client.write(
            table=contract.table_name,
            data=contract.data
        )
        return result
'''

SAMPLE_COMPUTE_NODE = '''
"""Text classifier compute node."""

class NodeTextClassifierCompute:
    """Classifies text into categories."""

    def execute_compute(self, input_state):
        """Execute classification."""
        text = input_state.text
        # Simple keyword-based classification
        if "error" in text.lower():
            category = "error"
        elif "warning" in text.lower():
            category = "warning"
        else:
            category = "info"

        return {"category": category, "confidence": 0.8}
'''


# ============================================================================
# Demo Functions
# ============================================================================


def demo_pattern_matcher():
    """Demonstrate ProductionPatternMatcher usage."""
    print("\n" + "=" * 80)
    print("DEMO 1: ProductionPatternMatcher")
    print("=" * 80)

    matcher = ProductionPatternMatcher()

    # Find similar Effect nodes
    print("\n--- Finding similar Effect nodes for 'database' domain ---")
    effect_nodes = matcher.find_similar_nodes("effect", "database", limit=3)
    print(f"\nFound {len(effect_nodes)} similar Effect nodes:")
    for i, node_path in enumerate(effect_nodes, 1):
        print(f"  {i}. {node_path.name}")

    # Extract patterns from first node
    if effect_nodes:
        print(f"\n--- Extracting patterns from {effect_nodes[0].name} ---")
        pattern = matcher.extract_patterns(effect_nodes[0])
        print("\nExtracted Pattern:")
        print(f"  Node Type: {pattern.node_type}")
        print(f"  Domain: {pattern.domain}")
        print(f"  Confidence: {pattern.confidence:.2f}")
        print(f"  Imports: {len(pattern.imports)}")
        print(f"  Method Signatures: {len(pattern.method_signatures)}")
        print(f"  Error Handling Patterns: {len(pattern.error_handling)}")
        print(f"  Transaction Management: {len(pattern.transaction_management)}")
        print(f"  Metrics Tracking: {len(pattern.metrics_tracking)}")

        # Show sample imports
        print("\n  Sample Imports (first 5):")
        for imp in pattern.imports[:5]:
            print(f"    {imp}")

        # Show sample method signatures
        print("\n  Sample Method Signatures:")
        for sig in pattern.method_signatures[:3]:
            print(f"    {sig}")

    # Find similar Compute nodes
    print("\n--- Finding similar Compute nodes for 'classification' domain ---")
    compute_nodes = matcher.find_similar_nodes("compute", "classification", limit=2)
    print(f"\nFound {len(compute_nodes)} similar Compute nodes:")
    for i, node_path in enumerate(compute_nodes, 1):
        print(f"  {i}. {node_path.name}")


async def demo_code_refiner():
    """Demonstrate CodeRefiner usage."""
    print("\n" + "=" * 80)
    print("DEMO 2: CodeRefiner")
    print("=" * 80)

    # Check for API key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("\n⚠️  GEMINI_API_KEY not set - skipping AI refinement demo")
        print("   Set GEMINI_API_KEY environment variable to enable AI refinement")
        return

    refiner = CodeRefiner()

    # Refine Effect node
    print("\n--- Refining Effect Node ---")
    print("\nOriginal Code (before refinement):")
    print("-" * 40)
    print(SAMPLE_EFFECT_NODE)
    print("-" * 40)

    context = {
        "node_type": "effect",
        "domain": "database",
        "requirements": {
            "transaction_management": True,
            "metrics_tracking": True,
        },
    }

    print("\nRefining with production patterns...")
    try:
        refined_effect = await refiner.refine_code(SAMPLE_EFFECT_NODE, "node", context)

        print("\nRefined Code (after refinement):")
        print("-" * 40)
        print(refined_effect)
        print("-" * 40)

        # Check improvements
        improvements = []
        if "async" in refined_effect and "async" not in SAMPLE_EFFECT_NODE:
            improvements.append("✓ Added async/await")
        if "transaction_manager" in refined_effect:
            improvements.append("✓ Added transaction management")
        if "_record_metric" in refined_effect:
            improvements.append("✓ Added metrics tracking")
        if "logger" in refined_effect:
            improvements.append("✓ Added logging")
        if "try:" in refined_effect and "except" in refined_effect:
            improvements.append("✓ Added error handling")

        if improvements:
            print("\nImprovements Applied:")
            for imp in improvements:
                print(f"  {imp}")
    except Exception as e:
        print(f"\n❌ Refinement failed: {e}")

    # Refine Compute node
    print("\n\n--- Refining Compute Node ---")
    print("\nOriginal Code (before refinement):")
    print("-" * 40)
    print(SAMPLE_COMPUTE_NODE)
    print("-" * 40)

    context = {
        "node_type": "compute",
        "domain": "classification",
        "requirements": {
            "pydantic_models": True,
            "type_hints": True,
        },
    }

    print("\nRefining with production patterns...")
    try:
        refined_compute = await refiner.refine_code(
            SAMPLE_COMPUTE_NODE, "node", context
        )

        print("\nRefined Code (after refinement):")
        print("-" * 40)
        print(refined_compute)
        print("-" * 40)

        # Check improvements
        improvements = []
        if "BaseModel" in refined_compute:
            improvements.append("✓ Added Pydantic models")
        if "Field" in refined_compute:
            improvements.append("✓ Added Field definitions")
        if "->" in refined_compute and "->" not in SAMPLE_COMPUTE_NODE:
            improvements.append("✓ Added type hints")
        if '"""' in refined_compute:
            improvements.append("✓ Added docstrings")

        if improvements:
            print("\nImprovements Applied:")
            for imp in improvements:
                print(f"  {imp}")
    except Exception as e:
        print(f"\n❌ Refinement failed: {e}")


def demo_pattern_caching():
    """Demonstrate pattern caching."""
    print("\n" + "=" * 80)
    print("DEMO 3: Pattern Caching")
    print("=" * 80)

    matcher = ProductionPatternMatcher()

    # First extraction (will parse file)
    print("\n--- First extraction (parsing file) ---")
    nodes = matcher.find_similar_nodes("effect", "database", limit=1)
    if nodes:
        import time

        start = time.time()
        pattern1 = matcher.extract_patterns(nodes[0])
        duration1 = (time.time() - start) * 1000
        print(f"Extracted {nodes[0].name} in {duration1:.2f}ms")
        print(f"Confidence: {pattern1.confidence:.2f}")

        # Second extraction (will use cache)
        print("\n--- Second extraction (using cache) ---")
        start = time.time()
        pattern2 = matcher.extract_patterns(nodes[0])
        duration2 = (time.time() - start) * 1000
        print(f"Extracted {nodes[0].name} in {duration2:.2f}ms")
        print(f"Confidence: {pattern2.confidence:.2f}")

        print(f"\n⚡ Cache speedup: {duration1 / duration2:.1f}x faster")
        print(f"   (Same object: {pattern1 is pattern2})")


# ============================================================================
# Main
# ============================================================================


async def main():
    """Run all demos."""
    print("\n")
    print("=" * 80)
    print(" Code Refiner Demo - Pattern Matcher & Applicator ".center(80))
    print("=" * 80)

    # Check if omniarchon repository is available
    omniarchon_path = Path(
        os.getenv(
            "OMNIARCHON_PATH",
            str(Path(__file__).resolve().parents[2] / "../omniarchon"),
        )
    )
    if not omniarchon_path.exists():
        print("\n⚠️  Warning: omniarchon repository not found")
        print(f"   Expected at: {omniarchon_path}")
        print("   Some demos may not work without production examples")

    # Demo 1: Pattern Matcher
    demo_pattern_matcher()

    # Demo 2: Code Refiner
    await demo_code_refiner()

    # Demo 3: Pattern Caching
    demo_pattern_caching()

    print("\n" + "=" * 80)
    print(" Demo Complete ".center(80))
    print("=" * 80)
    print()


if __name__ == "__main__":
    asyncio.run(main())
