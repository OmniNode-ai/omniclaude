#!/usr/bin/env python3
"""
Generate and display a real manifest for creating an orchestrator node.

This shows exactly what intelligence would be injected into an agent's context
when asked to create an orchestrator node for a node generation pipeline.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add agents to path
sys.path.insert(0, str(Path(__file__).parent / "agents"))

from lib.manifest_injector import ManifestInjector
from lib.task_classifier import TaskClassifier


async def show_orchestrator_manifest():
    """Generate and display manifest for orchestrator node creation"""

    print("=" * 100)
    print("MANIFEST GENERATION: Create Orchestrator Node for Node Generation Pipeline")
    print("=" * 100)
    print()

    # The user's request
    user_prompt = (
        "Create an orchestrator node to orchestrate our node generation pipeline"
    )

    print("📝 User Prompt:")
    print(f"   {user_prompt}")
    print()

    # Classify the task
    classifier = TaskClassifier()
    task_context = classifier.classify(user_prompt)

    print("🎯 Task Classification:")
    print(f"   Primary Intent: {task_context.primary_intent.value}")
    print(f"   Keywords: {task_context.keywords}")
    print()

    # Generate the manifest
    print("🔄 Generating manifest from intelligence system...")
    print()

    injector = ManifestInjector()

    import uuid

    correlation_id = str(uuid.uuid4())

    # Query patterns directly (bypass the full manifest for now to see patterns)
    print("   Querying patterns from Qdrant (archon_vectors collection)...")
    pattern_result = await injector._query_patterns_direct_qdrant(
        correlation_id=correlation_id,
        collections=["archon_vectors"],  # Use the collection that works
        limit_per_collection=20,
        task_context=task_context,
        user_prompt=user_prompt,
    )

    # Also generate the full manifest
    manifest = await injector.generate_dynamic_manifest_async(
        correlation_id=correlation_id,
        user_prompt=user_prompt,
        force_refresh=True,  # Get fresh data for this demo
    )

    print("=" * 100)
    print("📊 MANIFEST GENERATION COMPLETE")
    print("=" * 100)
    print()

    # Show metadata
    metadata = manifest.get("manifest_metadata", {})
    print("📋 Manifest Metadata:")
    print(f"   Version: {metadata.get('version')}")
    print(f"   Generated: {metadata.get('generated_at')}")
    print(f"   Source: {metadata.get('source')}")
    print(f"   Total Query Time: {metadata.get('total_query_time_ms')}ms")
    print()

    # Show patterns discovered (from direct query)
    available_patterns = pattern_result.get("patterns", [])

    # Also check manifest patterns
    manifest_patterns = manifest.get("patterns", {}).get("available", [])

    print(f"   Direct query returned: {len(available_patterns)} patterns")
    print(f"   Manifest contains: {len(manifest_patterns)} patterns")
    print()

    print("=" * 100)
    print(f"🎯 PATTERNS DISCOVERED: {len(available_patterns)} patterns")
    print("=" * 100)
    print()

    if available_patterns:
        print("Top 10 Most Relevant Patterns:")
        print("-" * 100)
        print(f"{'#':<3} {'Pattern Name':<50} {'Score':<8} {'File':<30}")
        print("-" * 100)

        for i, pattern in enumerate(available_patterns[:10], 1):
            name = pattern.get("name", "Unknown")[:48]
            score = pattern.get("hybrid_score", pattern.get("confidence", 0))
            file_path = pattern.get("file", "")
            file_name = Path(file_path).name if file_path else "N/A"

            print(f"{i:<3} {name:<50} {score:<8.4f} {file_name:<30}")

        print()

        # Show detailed breakdown for top 3 patterns
        print("=" * 100)
        print("📖 DETAILED PATTERN BREAKDOWN (Top 3)")
        print("=" * 100)
        print()

        for i, pattern in enumerate(available_patterns[:3], 1):
            print(f"Pattern #{i}: {pattern.get('name', 'Unknown')}")
            print("-" * 100)

            # Description
            desc = pattern.get("description", "No description")
            print(f"  Description: {desc[:200]}")
            if len(desc) > 200:
                print(f"               {desc[200:400]}...")
            print()

            # Score breakdown
            score_breakdown = pattern.get("score_breakdown", {})
            if score_breakdown:
                print("  Score Breakdown:")
                print(f"    • Keyword:  {score_breakdown.get('keyword_score', 0):.4f}")
                print(f"    • Semantic: {score_breakdown.get('semantic_score', 0):.4f}")
                print(f"    • Quality:  {score_breakdown.get('quality_score', 0):.4f}")
                print(
                    f"    • Success:  {score_breakdown.get('success_rate_score', 0):.4f}"
                )
                print(f"    → Hybrid:   {pattern.get('hybrid_score', 0):.4f}")
            else:
                print(f"  Confidence: {pattern.get('confidence', 0):.4f}")
            print()

            # Node types
            node_types = pattern.get("node_types", [])
            if node_types:
                print(f"  Node Types: {', '.join(node_types)}")

            # Use cases
            use_cases = pattern.get("use_cases", [])
            if use_cases:
                print(f"  Use Cases: {', '.join(use_cases[:3])}")

            # File path
            file_path = pattern.get("file", pattern.get("file_path", ""))
            if file_path:
                print(f"  Source File: {file_path}")

            print()

    # Show infrastructure context
    infrastructure = manifest.get("infrastructure", {})
    print("=" * 100)
    print("🏗️  INFRASTRUCTURE CONTEXT")
    print("=" * 100)
    print()

    remote_services = infrastructure.get("remote_services", {})
    if remote_services:
        print("Remote Services:")
        for service_name, service_info in remote_services.items():
            status = service_info.get("status", "unknown")
            print(f"  • {service_name}: {status}")
        print()

    # Show debug intelligence (if any)
    debug_intel = manifest.get("debug_intelligence", {})
    similar_workflows = debug_intel.get("similar_workflows", {})

    if similar_workflows:
        successes = similar_workflows.get("successes", [])
        failures = similar_workflows.get("failures", [])

        print("=" * 100)
        print("🧠 DEBUG INTELLIGENCE (Historical Patterns)")
        print("=" * 100)
        print()

        if successes:
            print(f"✅ Successful Approaches ({len(successes)} found):")
            for workflow in successes[:3]:
                print(f"  • {workflow.get('description', 'No description')}")
            print()

        if failures:
            print(f"❌ Failed Approaches to Avoid ({len(failures)} found):")
            for workflow in failures[:3]:
                print(f"  • {workflow.get('description', 'No description')}")
            print()

    # Show manifest structure
    print("=" * 100)
    print("📄 MANIFEST STRUCTURE")
    print("=" * 100)
    print()

    print("Manifest Sections:")
    for section_name in manifest.keys():
        section_data = manifest[section_name]
        if isinstance(section_data, dict):
            print(f"  • {section_name}: {len(section_data)} keys")
        elif isinstance(section_data, list):
            print(f"  • {section_name}: {len(section_data)} items")
        else:
            print(f"  • {section_name}: {type(section_data).__name__}")

    print()
    print("=" * 100)
    print("✅ MANIFEST DISPLAY COMPLETE")
    print("=" * 100)
    print()
    print("This manifest would be injected into the agent's prompt context,")
    print("providing comprehensive intelligence for creating the orchestrator node.")
    print()
    print(f"Total manifest size: {len(str(manifest))} characters")


if __name__ == "__main__":
    import sys

    # Verify POSTGRES_PASSWORD is set
    if not os.environ.get("POSTGRES_PASSWORD"):
        print("❌ ERROR: POSTGRES_PASSWORD environment variable not set")
        print("   Please run: source .env")
        sys.exit(1)

    asyncio.run(show_orchestrator_manifest())
