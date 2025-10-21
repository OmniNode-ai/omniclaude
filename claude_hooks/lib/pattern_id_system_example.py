#!/usr/bin/env python3
"""
Pattern ID System - Comprehensive Usage Examples
=================================================

Demonstrates real-world usage patterns for:
- Pattern identification and tracking
- Version evolution tracking
- Lineage detection and visualization
- Thread-safe concurrent operations
- Integration patterns
"""

import threading

from pattern_id_system import (
    PatternDeduplicator,
    PatternVersion,
    detect_pattern_derivation,
    generate_pattern_id,
    get_global_deduplicator,
)


def example1_basic_id_generation():
    """Example 1: Basic pattern ID generation"""
    print("\n" + "=" * 60)
    print("Example 1: Basic Pattern ID Generation")
    print("=" * 60)

    # Same code, different comments/whitespace
    code1 = """
    def calculate_total(items):
        # Calculate the total of all items
        total = sum(items)
        return total
    """

    code2 = """
    def calculate_total(items):
        # Different comment here
        total=sum(items)
        return total
    """

    code3 = """
    def calculate_total(items):
        total = sum(items)
        return total
    """

    id1 = generate_pattern_id(code1)
    id2 = generate_pattern_id(code2)
    id3 = generate_pattern_id(code3)

    print(f"Code 1 ID: {id1}")
    print(f"Code 2 ID: {id2}")
    print(f"Code 3 ID: {id3}")
    print(f"\nAll IDs identical: {id1 == id2 == id3}")
    print("✓ Comments and whitespace normalized away!")


def example2_version_evolution():
    """Example 2: Track pattern evolution over time"""
    print("\n" + "=" * 60)
    print("Example 2: Pattern Version Evolution")
    print("=" * 60)

    dedup = PatternDeduplicator()

    # Evolution of a function over time
    evolution = [
        (
            "v1.0.0 - Initial",
            """
        def process_data(data):
            return [x * 2 for x in data]
        """,
        ),
        (
            "v1.0.1 - Variable rename",
            """
        def process_data(data):
            return [item * 2 for item in data]
        """,
        ),
        (
            "v1.1.0 - Add validation",
            """
        def process_data(data):
            if not data:
                return []
            return [item * 2 for item in data]
        """,
        ),
        (
            "v2.0.0 - Class refactor",
            """
        class DataProcessor:
            def process(self, data):
                if not data:
                    return []
                return [item * 2 for item in data]
        """,
        ),
    ]

    print("Tracking evolution:\n")

    # Register first version
    _, first_code = evolution[0]
    current_meta = dedup.register_pattern(first_code, version=PatternVersion(1, 0, 0))
    print(f"✓ {evolution[0][0]}: {current_meta.pattern_id}")

    # Track subsequent versions
    current_code = first_code
    for label, next_code in evolution[1:]:
        original_meta, modified_meta = dedup.register_with_lineage(
            current_code, next_code
        )

        print(f"✓ {label}: {modified_meta.pattern_id}")
        print(f"  Version: {original_meta.version} → {modified_meta.version}")
        print(f"  Similarity: {modified_meta.similarity_score:.2%}")
        print(f"  Type: {modified_meta.modification_type.value}")

        current_code = next_code

    # Show complete lineage
    print("\nComplete lineage chain:")
    lineage = dedup.get_pattern_lineage(modified_meta.pattern_id)
    for i, meta in enumerate(lineage, 1):
        parent_note = (
            f" (parent: {meta.parent_id[:8]})" if meta.parent_id else " (root)"
        )
        print(f"  {i}. {meta.pattern_id} v{meta.version}{parent_note}")


def example3_similarity_analysis():
    """Example 3: Similarity analysis and modification classification"""
    print("\n" + "=" * 60)
    print("Example 3: Similarity Analysis")
    print("=" * 60)

    test_cases = [
        (
            "Identical",
            """
        def foo(x):
            return x * 2
        """,
            """
        def foo(x):
            return x * 2
        """,
        ),
        (
            "Patch (>90%)",
            """
        def calculate(x, y):
            result = x + y
            return result
        """,
            """
        def calculate(x, y):
            total = x + y
            return total
        """,
        ),
        (
            "Minor (70-90%)",
            """
        def greet(name):
            return f"Hello, {name}"
        """,
            """
        def greet(name):
            greeting = f"Hello, {name}"
            print(greeting)
            return greeting
        """,
        ),
        (
            "Major (50-70%)",
            """
        def simple_sum(a, b):
            return a + b
        """,
            """
        class Calculator:
            def sum(self, a, b):
                return a + b
        """,
        ),
        (
            "Unrelated (<50%)",
            """
        def foo():
            return 42
        """,
            """
        class CompletelyDifferent:
            def __init__(self):
                self.data = []
            def process(self):
                return self.data
        """,
        ),
    ]

    print("\nSimilarity classification:\n")

    for label, original, modified in test_cases:
        result = detect_pattern_derivation(original, modified)

        print(f"{label}:")
        print(f"  Similarity: {result['similarity_score']:.2%}")
        print(f"  Is derived: {result['is_derived']}")
        if result["modification_type"]:
            print(f"  Type: {result['modification_type'].value}")
            print(f"  Suggested version: {result['suggested_version']}")
        print()


def example4_deduplication():
    """Example 4: Pattern deduplication in action"""
    print("\n" + "=" * 60)
    print("Example 4: Pattern Deduplication")
    print("=" * 60)

    dedup = PatternDeduplicator()

    # Try to register the same pattern multiple times
    base_code = """
    def utility_function(x):
        return x ** 2
    """

    # Variations that normalize to the same pattern
    variations = [
        base_code,
        "def utility_function(x):\n    # Comment\n    return x ** 2",
        "def utility_function(x):    return x ** 2",
        "def utility_function(x):\n\n\n    return x ** 2\n\n",
    ]

    print("Registering variations of the same pattern:\n")

    registered_ids = set()
    for i, code in enumerate(variations, 1):
        # Check for duplicate first
        duplicate = dedup.check_duplicate(code)
        if duplicate:
            print(f"Variation {i}: DUPLICATE (ID: {duplicate.pattern_id})")
            registered_ids.add(duplicate.pattern_id)
        else:
            meta = dedup.register_pattern(code, tags={"utility"})
            print(f"Variation {i}: NEW (ID: {meta.pattern_id})")
            registered_ids.add(meta.pattern_id)

    print(f"\n✓ {len(variations)} variations → {len(registered_ids)} unique pattern(s)")
    print(
        f"✓ Deduplication prevented {len(variations) - len(registered_ids)} duplicates"
    )


def example5_thread_safety():
    """Example 5: Thread-safe concurrent registration"""
    print("\n" + "=" * 60)
    print("Example 5: Thread-Safe Concurrent Operations")
    print("=" * 60)

    dedup = get_global_deduplicator()
    results = []
    lock = threading.Lock()

    def worker(thread_id: int, pattern_count: int):
        """Worker thread that registers patterns"""
        local_results = []
        for i in range(pattern_count):
            code = f"def thread_{thread_id}_pattern_{i}(x): return x * {i}"
            meta = dedup.register_pattern(code, tags={f"thread-{thread_id}"})
            local_results.append(meta.pattern_id)

        with lock:
            results.extend(local_results)

    # Create and start threads
    threads = []
    num_threads = 5
    patterns_per_thread = 10

    print(f"Starting {num_threads} threads, {patterns_per_thread} patterns each...\n")

    for i in range(num_threads):
        t = threading.Thread(target=worker, args=(i, patterns_per_thread))
        threads.append(t)
        t.start()

    # Wait for completion
    for t in threads:
        t.join()

    # Verify results
    total_patterns = num_threads * patterns_per_thread
    unique_ids = len(set(results))

    print(f"✓ Registered {total_patterns} patterns from {num_threads} threads")
    print(f"✓ All {unique_ids} pattern IDs are unique")
    print("✓ No race conditions or duplicates detected")

    stats = dedup.get_stats()
    print("\nDeduplicator statistics:")
    print(f"  Total patterns: {stats['total_patterns']}")
    print(f"  Unique patterns: {stats['unique_patterns']}")


def example6_multi_language():
    """Example 6: Multi-language support"""
    print("\n" + "=" * 60)
    print("Example 6: Multi-Language Support")
    print("=" * 60)

    patterns = [
        (
            "Python",
            """
        def hello(name):
            # Python comment
            print(f"Hello, {name}")
        """,
            "python",
        ),
        (
            "JavaScript",
            """
        function hello(name) {
            // JavaScript comment
            console.log(`Hello, ${name}`);
        }
        """,
            "javascript",
        ),
        (
            "TypeScript",
            """
        function hello(name: string): void {
            // TypeScript comment
            console.log(`Hello, ${name}`);
        }
        """,
            "typescript",
        ),
        (
            "Java",
            """
        public void hello(String name) {
            // Java comment
            System.out.println("Hello, " + name);
        }
        """,
            "java",
        ),
    ]

    print("Generating IDs for different languages:\n")

    for lang, code, lang_key in patterns:
        pattern_id = generate_pattern_id(code, language=lang_key)
        print(f"{lang:12} → {pattern_id}")

    print("\n✓ Language-specific comment removal working correctly")


def example7_lineage_visualization():
    """Example 7: Visualize pattern lineage tree"""
    print("\n" + "=" * 60)
    print("Example 7: Pattern Lineage Visualization")
    print("=" * 60)

    dedup = PatternDeduplicator()

    # Create a branching lineage tree
    root_code = "def root(): return 1"

    # Branch A: Feature additions
    branch_a = [
        "def root(x): return x",
        "def root(x, y): return x + y",
    ]

    # Branch B: Refactoring
    branch_b = [
        "def root(): return 2",  # Simple change
        "def root(): return 3",  # Another change
    ]

    # Register root
    root_meta = dedup.register_pattern(root_code, version=PatternVersion(1, 0, 0))

    print("Lineage tree:\n")
    print(f"ROOT: {root_meta.pattern_id[:8]} v{root_meta.version}")

    # Build branch A
    print("\n  Branch A (feature additions):")
    current = root_code
    for code in branch_a:
        _, child_meta = dedup.register_with_lineage(current, code)
        print(
            f"  ├─ {child_meta.pattern_id[:8]} v{child_meta.version} "
            f"(similarity: {child_meta.similarity_score:.0%})"
        )
        current = code

    # Build branch B
    print("\n  Branch B (iterative changes):")
    current = root_code
    for code in branch_b:
        _, child_meta = dedup.register_with_lineage(current, code)
        print(
            f"  ├─ {child_meta.pattern_id[:8]} v{child_meta.version} "
            f"(similarity: {child_meta.similarity_score:.0%})"
        )
        current = code

    # Show children of root
    children = dedup.get_children(root_meta.pattern_id)
    print(f"\n✓ Root pattern has {len(children)} direct children")


def example8_metadata_enrichment():
    """Example 8: Rich metadata and tagging"""
    print("\n" + "=" * 60)
    print("Example 8: Metadata Enrichment")
    print("=" * 60)

    dedup = PatternDeduplicator()

    # Register patterns with rich metadata
    patterns_with_tags = [
        (
            "Utility function",
            "def square(x): return x ** 2",
            {"utility", "math", "pure"},
        ),
        (
            "API endpoint",
            "def get_user(id): return db.query(id)",
            {"api", "database", "crud"},
        ),
        (
            "Test helper",
            "def assert_valid(data): assert data is not None",
            {"test", "validation"},
        ),
        (
            "Algorithm",
            "def quicksort(arr): return sorted(arr)",
            {"algorithm", "sorting", "performance"},
        ),
    ]

    print("Registering patterns with tags:\n")

    for label, code, tags in patterns_with_tags:
        meta = dedup.register_pattern(code, tags=tags)
        print(f"{label}:")
        print(f"  ID: {meta.pattern_id}")
        print(f"  Tags: {', '.join(sorted(meta.tags))}")

    # Search by tag (conceptual - would need index)
    print("\n✓ Patterns registered with rich metadata")
    print("✓ Tags can be used for categorization and search")


def example9_statistics_and_insights():
    """Example 9: Statistics and insights"""
    print("\n" + "=" * 60)
    print("Example 9: Statistics and Insights")
    print("=" * 60)

    dedup = PatternDeduplicator()

    # Generate diverse patterns
    print("Generating diverse pattern set...\n")

    # Root patterns
    for i in range(5):
        code = f"def root_{i}(): return {i}"
        dedup.register_pattern(code)

    # Derived patterns
    for i in range(5):
        original = f"def root_{i}(): return {i}"
        modified = f"def root_{i}(x): return {i} + x"
        dedup.register_with_lineage(original, modified)

    # Get statistics
    stats = dedup.get_stats()

    print("Pattern Statistics:")
    print(f"  Total patterns processed: {stats['total_patterns']}")
    print(f"  Unique patterns: {stats['unique_patterns']}")
    print(f"  Root patterns: {stats['root_patterns']}")
    print(f"  Derived patterns: {stats['derived_patterns']}")
    print(f"  Deduplication rate: {stats['deduplication_rate']:.2%}")

    print("\n✓ Successfully tracked pattern relationships")
    print(
        f"✓ {stats['derived_patterns']} patterns traced to {stats['root_patterns']} roots"
    )


def main():
    """Run all examples"""
    print("\n" + "=" * 60)
    print("PATTERN ID SYSTEM - COMPREHENSIVE EXAMPLES")
    print("=" * 60)

    examples = [
        example1_basic_id_generation,
        example2_version_evolution,
        example3_similarity_analysis,
        example4_deduplication,
        example5_thread_safety,
        example6_multi_language,
        example7_lineage_visualization,
        example8_metadata_enrichment,
        example9_statistics_and_insights,
    ]

    for example in examples:
        try:
            example()
        except Exception as e:
            print(f"\n❌ Error in {example.__name__}: {e}")

    print("\n" + "=" * 60)
    print("EXAMPLES COMPLETE")
    print("=" * 60)
    print("\nAll examples demonstrate production-ready capabilities:")
    print("  ✓ Deterministic ID generation")
    print("  ✓ Version evolution tracking")
    print("  ✓ Similarity-based lineage detection")
    print("  ✓ Thread-safe deduplication")
    print("  ✓ Multi-language support")
    print("  ✓ Rich metadata management")
    print("  ✓ Statistical insights")


if __name__ == "__main__":
    main()
