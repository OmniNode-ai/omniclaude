#!/usr/bin/env python3
"""
Intelligence-Enhanced Node Generation Example

Demonstrates how to generate ONEX nodes with intelligence context
for production-quality code generation.
"""

import asyncio
from pathlib import Path

from agents.lib.models.intelligence_context import (
    IntelligenceContext,
    get_default_intelligence,
)
from agents.lib.omninode_template_engine import OmniNodeTemplateEngine
from agents.lib.simple_prd_analyzer import SimplePRDAnalysisResult, SimplifiedPRD


async def example_with_custom_intelligence():
    """
    Example 1: Generate node with custom intelligence context.

    This example shows how to provide specific intelligence gathered
    from RAG queries or domain expertise.
    """
    print("=" * 80)
    print("Example 1: Node Generation with Custom Intelligence")
    print("=" * 80)

    # Create PRD analysis
    prd = SimplifiedPRD(
        description="High-performance PostgreSQL CRUD operations with connection pooling",
        features=[
            "Create records with validation",
            "Read records with pagination",
            "Update records with optimistic locking",
            "Delete records with cascade handling",
        ],
        functional_requirements=[
            "Support connection pooling (min 5, max 20 connections)",
            "Implement circuit breaker for database failures",
            "Use prepared statements for all queries",
            "Handle constraint violations gracefully",
            "Implement retry logic with exponential backoff",
        ],
        extracted_keywords=["database", "postgresql", "crud", "connection-pool"],
    )

    prd_analysis = SimplePRDAnalysisResult(
        parsed_prd=prd,
        recommended_node_type="EFFECT",
        recommended_mixins=["MixinRetry", "MixinEventBus", "MixinConnectionPool"],
        external_systems=["PostgreSQL"],
        decomposition_result=type(
            "obj",
            (object,),
            {
                "tasks": [
                    type(
                        "obj",
                        (object,),
                        {"title": "Implement connection pool management"},
                    )(),
                    type(
                        "obj", (object,), {"title": "Add prepared statement caching"}
                    )(),
                    type("obj", (object,), {"title": "Implement circuit breaker"})(),
                ]
            },
        )(),
        confidence_score=0.95,
        quality_baseline={},
        session_id="example-session-1",
        correlation_id="example-correlation-1",
    )

    # Create custom intelligence context (simulating RAG-gathered intelligence)
    intelligence = IntelligenceContext(
        node_type_patterns=[
            "Use connection pooling (min 5, max 20 connections)",
            "Implement circuit breaker with 50% failure threshold",
            "Use retry logic with exponential backoff (max 3 retries)",
            "Always use prepared statements for SQL queries",
            "Implement proper transaction management with rollback",
            "Use timeout mechanisms for all database operations (5s default)",
            "Log all database errors with correlation_id for debugging",
            "Validate inputs before executing queries",
        ],
        common_operations=["create", "read", "update", "delete", "batch_insert"],
        required_mixins=[
            "MixinRetry",
            "MixinConnectionPool",
            "MixinCircuitBreaker",
            "MixinEventBus",
        ],
        performance_targets={
            "query_time_ms": 10,
            "connection_timeout_ms": 5000,
            "max_pool_wait_ms": 1000,
        },
        error_scenarios=[
            "Connection timeout",
            "Constraint violation (unique, foreign key)",
            "Deadlock detection and retry",
            "Pool exhaustion",
            "Transaction rollback",
        ],
        domain_best_practices=[
            "Use prepared statements to prevent SQL injection",
            "Always use transactions for write operations",
            "Implement row-level locking for updates",
            "Use pagination for large result sets",
            "Batch operations when possible (bulk insert/update)",
        ],
        anti_patterns=[
            "Avoid SELECT * queries",
            "Don't hold connections longer than necessary",
            "Never concatenate user input into SQL queries",
        ],
        testing_recommendations=[
            "Mock database connections in unit tests",
            "Test connection pool exhaustion scenarios",
            "Test deadlock handling and retry logic",
            "Verify prepared statement caching works",
        ],
        security_considerations=[
            "Use parameterized queries (prepared statements)",
            "Validate all user inputs before queries",
            "Implement rate limiting for write operations",
            "Use least-privilege database credentials",
        ],
        rag_sources=[
            "postgresql_connection_pooling_patterns",
            "database_best_practices_2024",
            "onex_effect_node_examples",
        ],
        confidence_score=0.92,
    )

    # Generate node with intelligence
    engine = OmniNodeTemplateEngine(enable_cache=False)

    output_dir = Path("./generated_nodes/example_with_intelligence")
    output_dir.mkdir(parents=True, exist_ok=True)

    result = await engine.generate_node(
        analysis_result=prd_analysis,
        node_type="EFFECT",
        microservice_name="postgres_crud",
        domain="data_services",
        output_directory=str(output_dir),
        intelligence=intelligence,
    )

    print("\n✅ Node generated successfully!")
    print(f"   Output path: {result['output_path']}")
    print(f"   Main file: {result['main_file']}")
    print(f"   Generated {len(result['generated_files'])} additional files")
    print(f"   Intelligence confidence: {intelligence.confidence_score:.0%}")

    # Show snippet of generated code
    main_file_path = Path(result["main_file"])
    if main_file_path.exists():
        generated_code = main_file_path.read_text(encoding="utf-8")

        # Extract docstring
        docstring_start = generated_code.find('"""')
        if docstring_start != -1:
            docstring_end = generated_code.find('"""', docstring_start + 3)
            if docstring_end != -1:
                docstring = generated_code[docstring_start : docstring_end + 3]
                print("\n📝 Generated Node Docstring (Intelligence-Enhanced):")
                print("-" * 80)
                print(docstring)
                print("-" * 80)

    return result


async def example_with_default_intelligence():
    """
    Example 2: Generate node with default intelligence.

    This example shows how default intelligence is automatically
    applied when no custom intelligence is provided.
    """
    print("\n" + "=" * 80)
    print("Example 2: Node Generation with Default Intelligence")
    print("=" * 80)

    # Create simple PRD
    prd = SimplifiedPRD(
        description="Data transformation and validation microservice",
        features=["Transform data", "Validate schemas", "Calculate metrics"],
        functional_requirements=[
            "Transform input data to target schema",
            "Validate data against JSON schemas",
            "Calculate aggregation metrics",
        ],
        extracted_keywords=["transform", "validate", "compute"],
    )

    prd_analysis = SimplePRDAnalysisResult(
        parsed_prd=prd,
        recommended_node_type="COMPUTE",
        recommended_mixins=["MixinCaching", "MixinValidation"],
        external_systems=[],
        decomposition_result=type(
            "obj",
            (object,),
            {
                "tasks": [
                    type("obj", (object,), {"title": "Implement transformations"})(),
                ]
            },
        )(),
        confidence_score=0.88,
        quality_baseline={},
        session_id="example-session-2",
        correlation_id="example-correlation-2",
    )

    # Generate node WITHOUT custom intelligence (will use defaults)
    engine = OmniNodeTemplateEngine(enable_cache=False)

    output_dir = Path("./generated_nodes/example_with_defaults")
    output_dir.mkdir(parents=True, exist_ok=True)

    result = await engine.generate_node(
        analysis_result=prd_analysis,
        node_type="COMPUTE",
        microservice_name="data_transformer",
        domain="processing",
        output_directory=str(output_dir),
        intelligence=None,  # No intelligence - will use defaults
    )

    print("\n✅ Node generated with default intelligence!")
    print(f"   Output path: {result['output_path']}")
    print(f"   Main file: {result['main_file']}")
    print("   Default intelligence applied for COMPUTE node")

    # Show what default intelligence looks like
    default_intel = get_default_intelligence("COMPUTE")
    print("\n📊 Default COMPUTE Intelligence Applied:")
    print(f"   Confidence: {default_intel.confidence_score:.0%}")
    print(f"   Patterns: {len(default_intel.node_type_patterns)}")
    print("   Example patterns:")
    for pattern in default_intel.node_type_patterns[:3]:
        print(f"      - {pattern}")

    return result


async def example_all_node_types():
    """
    Example 3: Generate all 4 node types with default intelligence.

    Demonstrates intelligence-enhanced generation for all node types.
    """
    print("\n" + "=" * 80)
    print("Example 3: All Node Types with Default Intelligence")
    print("=" * 80)

    node_types = {
        "EFFECT": {
            "description": "External I/O and database operations",
            "microservice_name": "database_writer",
        },
        "COMPUTE": {
            "description": "Pure data transformations and calculations",
            "microservice_name": "data_processor",
        },
        "REDUCER": {
            "description": "Event aggregation and state management",
            "microservice_name": "event_aggregator",
        },
        "ORCHESTRATOR": {
            "description": "Workflow coordination and orchestration",
            "microservice_name": "workflow_coordinator",
        },
    }

    engine = OmniNodeTemplateEngine(enable_cache=False)
    results = {}

    for node_type, config in node_types.items():
        print(f"\n🔧 Generating {node_type} node...")

        # Get default intelligence for this type
        intelligence = get_default_intelligence(node_type)

        prd = SimplifiedPRD(
            description=config["description"],
            features=["Feature 1", "Feature 2"],
            functional_requirements=["Requirement 1"],
            extracted_keywords=["test"],
        )

        prd_analysis = SimplePRDAnalysisResult(
            parsed_prd=prd,
            recommended_node_type=node_type,
            recommended_mixins=[],
            external_systems=[],
            decomposition_result=type("obj", (object,), {"tasks": []})(),  # Empty tasks
            confidence_score=0.9,
            quality_baseline={},
            session_id=f"example-session-{node_type}",
            correlation_id=f"example-correlation-{node_type}",
        )

        output_dir = Path(f"./generated_nodes/example_{node_type.lower()}")
        output_dir.mkdir(parents=True, exist_ok=True)

        result = await engine.generate_node(
            analysis_result=prd_analysis,
            node_type=node_type,
            microservice_name=config["microservice_name"],
            domain="examples",
            output_directory=str(output_dir),
            intelligence=intelligence,
        )

        results[node_type] = result
        print(f"   ✅ {node_type} node generated at {result['output_path']}")
        print(f"   📊 Default patterns applied: {len(intelligence.node_type_patterns)}")

    print("\n" + "=" * 80)
    print("Summary: All 4 node types generated with intelligence!")
    print("=" * 80)
    for node_type, result in results.items():
        print(f"   {node_type}: {result['main_file']}")

    return results


async def main():
    """Run all examples."""
    print("\n" + "=" * 80)
    print("Intelligence-Enhanced Node Generation Examples")
    print("=" * 80)

    # Example 1: Custom intelligence
    await example_with_custom_intelligence()

    # Example 2: Default intelligence
    await example_with_default_intelligence()

    # Example 3: All node types
    await example_all_node_types()

    print("\n" + "=" * 80)
    print("✅ All examples completed successfully!")
    print("=" * 80)
    print("\nGenerated nodes are in: ./generated_nodes/")
    print("\nKey Takeaways:")
    print("1. Custom intelligence provides RAG-gathered best practices")
    print("2. Default intelligence ensures quality even without RAG")
    print("3. All 4 node types benefit from intelligence injection")
    print("4. Generated code includes documentation and pattern hints")
    print("")


if __name__ == "__main__":
    asyncio.run(main())
