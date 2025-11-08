#!/usr/bin/env python3
"""
Integration test: Demonstrate manifest output with deduplicated patterns.

This script creates a mock manifest with deduplicated patterns to show
the actual output format that will be seen in agent manifests.
"""

# Mock pattern data (simulating what comes from Qdrant)
patterns_data = {
    "available": [
        {
            "name": "Dependency Injection Pattern",
            "confidence": 0.85,
            "node_types": ["EFFECT"],
            "instance_count": 23,
            "all_node_types": ["COMPUTE", "EFFECT", "REDUCER"],
            "all_domains": ["analytics", "data_processing", "identity", "monitoring"],
            "all_services": ["analytics_service", "data_service", "user_service"],
            "all_files": ["file1.py", "file2.py"],  # Truncated for demo
        },
        {
            "name": "Event Bus Communication Pattern",
            "confidence": 0.92,
            "node_types": ["EFFECT"],
            "instance_count": 8,
            "all_node_types": ["EFFECT"],
            "all_domains": ["event_processing", "messaging"],
            "all_services": ["event_service", "kafka_service"],
            "all_files": ["event_publisher.py", "event_consumer.py"],
        },
        {
            "name": "State Management Pattern",
            "confidence": 0.88,
            "node_types": ["REDUCER"],
            "instance_count": 1,  # Single instance - will display normally
            "all_node_types": ["REDUCER"],
            "all_domains": ["state"],
            "all_services": ["state_service"],
            "all_files": ["state_manager.py"],
            "file": "state_manager.py",  # Original file path for single instance
        },
    ],
    "total_count": 3,
    "original_count": 32,  # 23 + 8 + 1 = 32 original patterns
    "duplicates_removed": 29,  # 32 - 3 = 29 duplicates
    "collections_queried": {
        "execution_patterns": 15,
        "code_patterns": 17,
    },
}


def format_patterns_demo(patterns_data):
    """Format patterns section (matches manifest_injector.py implementation)."""
    output = ["AVAILABLE PATTERNS:"]

    patterns = patterns_data.get("available", [])
    collections_queried = patterns_data.get("collections_queried", {})
    duplicates_removed = patterns_data.get("duplicates_removed", 0)
    original_count = patterns_data.get("original_count", len(patterns))

    if not patterns:
        output.append("  (No patterns discovered - use built-in patterns)")
        return "\n".join(output)

    # Show collection statistics
    if collections_queried:
        output.append(
            f"  Collections: execution_patterns ({collections_queried.get('execution_patterns', 0)}), "
            f"code_patterns ({collections_queried.get('code_patterns', 0)})"
        )

        # Show deduplication metrics if duplicates were removed
        if duplicates_removed > 0:
            output.append(
                f"  Deduplication: {duplicates_removed} duplicates removed "
                f"({original_count} → {len(patterns)} unique patterns)"
            )

        output.append("")

    # Show patterns
    display_limit = 20
    for pattern in patterns[:display_limit]:
        # Get instance count (defaults to 1 if not present)
        instance_count = pattern.get("instance_count", 1)

        # Format pattern name with instance count for duplicates
        if instance_count > 1:
            pattern_header = (
                f"  • {pattern['name']} ({pattern.get('confidence', 0):.0%} confidence) "
                f"[{instance_count} instances]"
            )
        else:
            pattern_header = (
                f"  • {pattern['name']} ({pattern.get('confidence', 0):.0%} confidence)"
            )

        output.append(pattern_header)

        # Show aggregated node types (from all instances)
        all_node_types = pattern.get("all_node_types", pattern.get("node_types", []))
        if all_node_types:
            output.append(f"    Node Types: {', '.join(all_node_types)}")

        # Show domains for multi-instance patterns
        all_domains = pattern.get("all_domains", [])
        if all_domains and instance_count > 1:
            domains_str = ", ".join(all_domains[:3])  # Show first 3 domains
            if len(all_domains) > 3:
                domains_str += f", +{len(all_domains) - 3} more"
            output.append(f"    Domains: {domains_str}")

        # Show representative file (only for single instance or if needed)
        if instance_count == 1 and pattern.get("file"):
            output.append(f"    File: {pattern['file']}")
        elif instance_count > 1:
            file_count = len(pattern.get("all_files", []))
            if file_count > 0:
                output.append(f"    Files: {file_count} files across services")

    if len(patterns) > display_limit:
        output.append(f"  ... and {len(patterns) - display_limit} more patterns")

    output.append("")
    output.append(f"  Total: {len(patterns)} unique patterns available")

    return "\n".join(output)


def main():
    """Generate and display manifest output."""
    print("=" * 70)
    print("MANIFEST OUTPUT EXAMPLE (With Pattern Deduplication)")
    print("=" * 70)
    print()

    manifest_output = format_patterns_demo(patterns_data)
    print(manifest_output)

    print()
    print("=" * 70)
    print("TOKEN SAVINGS ANALYSIS")
    print("=" * 70)
    print()

    # Calculate token savings
    original_count = patterns_data["original_count"]
    unique_count = patterns_data["total_count"]
    duplicates_removed = patterns_data["duplicates_removed"]

    # Estimate tokens (rough approximation)
    # Without deduplication: ~25 tokens per pattern
    # With deduplication: ~40 tokens per grouped pattern + ~15 tokens per unique pattern
    tokens_without_dedup = original_count * 25
    tokens_with_dedup = unique_count * 40  # Assuming 2 multi-instance, 1 single
    tokens_saved = tokens_without_dedup - tokens_with_dedup
    reduction_pct = (tokens_saved / tokens_without_dedup) * 100

    print(f"Before deduplication:")
    print(f"  {original_count} patterns x ~25 tokens = ~{tokens_without_dedup} tokens")
    print()
    print(f"After deduplication:")
    print(
        f"  {unique_count} unique patterns x ~40 tokens = ~{tokens_with_dedup} tokens"
    )
    print()
    print(f"Savings: ~{tokens_saved} tokens ({reduction_pct:.1f}% reduction)")
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
