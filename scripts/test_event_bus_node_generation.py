#!/usr/bin/env python3
"""
Test Stage 4.5 Event Bus Integration
Generate test nodes for all 4 ONEX types and validate integration.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict


# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.lib.generation_pipeline import GenerationPipeline


async def generate_test_node(
    node_type: str, service_name: str, domain: str, description: str, output_dir: Path
) -> Dict[str, Any]:
    """Generate a test node with Stage 4.5 integration."""

    print(f"\n{'='*80}")
    print(f"Generating {node_type} node: {service_name}")
    print(f"{'='*80}")

    pipeline = GenerationPipeline(
        enable_intelligence_gathering=False,  # Skip for faster testing
        enable_compilation_testing=False,  # Skip for faster testing
        interactive_mode=False,
    )

    # Create output directory
    node_output_dir = output_dir / service_name
    node_output_dir.mkdir(parents=True, exist_ok=True)

    # Build prompt for pipeline
    prompt = f"""
Create a {node_type.upper()} node for {service_name}.

Domain: {domain}
Description: {description}

Business Requirements:
- Handle basic {node_type} operations
- Provide health check endpoint
- Implement error handling
- Support metrics collection

Technical Requirements:
- Use ONEX architecture patterns
- Implement proper type hints
- Include comprehensive error handling
- Follow naming conventions (Node{service_name.title().replace('_', '')}{node_type.title()})
"""

    # Execute pipeline
    result = await pipeline.execute(
        prompt=prompt,
        output_directory=str(node_output_dir),
    )

    # Convert PipelineResult to dict for compatibility
    result_dict = {
        "status": result.status,
        "main_file": result.output_path,
        "generated_files": result.generated_files or [],
        "stages": [
            {
                "stage_name": stage.stage_name,
                "status": (
                    stage.status.value
                    if hasattr(stage.status, "value")
                    else str(stage.status)
                ),
                "duration_ms": (
                    (stage.end_time - stage.start_time).total_seconds() * 1000
                    if stage.end_time and stage.start_time
                    else 0
                ),
                "metadata": stage.metadata or {},
            }
            for stage in result.stages
        ],
        "node_type": result.node_type,
        "service_name": result.service_name,
        "domain": result.domain,
    }

    # Extract event bus integration status from stage 4.5
    stage45 = next(
        (s for s in result.stages if s.stage_name == "event_bus_integration"), None
    )
    if stage45 and stage45.metadata:
        result_dict["event_bus_integrated"] = stage45.metadata.get(
            "event_bus_code_injected", False
        )
        result_dict["startup_script"] = stage45.metadata.get(
            "startup_script_path", None
        )

    print(f"\n✅ Generation completed: {service_name}")
    print(f"   Status: {result.status}")
    print(f"   Main file: {result.output_path}")
    print(f"   Event bus integrated: {result_dict.get('event_bus_integrated', False)}")
    print(f"   Startup script: {result_dict.get('startup_script', 'N/A')}")

    # Check generated files
    generated_files = result.generated_files or []
    print(f"\n   Generated files ({len(generated_files)}):")
    for file_path in generated_files:
        file_size = Path(file_path).stat().st_size if Path(file_path).exists() else 0
        print(f"   - {Path(file_path).name} ({file_size:,} bytes)")

    # Clean up pipeline
    await pipeline.cleanup_async()

    return result_dict


async def validate_stage45_integration(node_result: Dict[str, Any]) -> Dict[str, bool]:
    """Validate Stage 4.5 integration for a generated node."""

    validation = {
        "event_bus_integrated": False,
        "startup_script_exists": False,
        "introspection_method_present": False,
        "lifecycle_methods_present": False,
        "event_imports_present": False,
    }

    main_file = node_result.get("main_file")
    if not main_file or not Path(main_file).exists():
        print(f"❌ Main file not found: {main_file}")
        return validation

    # Read node file
    with open(main_file, "r") as f:
        content = f.read()

    # Check for event bus integration markers
    validation["event_bus_integrated"] = (
        "EVENT_BUS_AVAILABLE" in content and "EventPublisher" in content
    )

    validation["event_imports_present"] = (
        "from omniarchon.events.publisher import EventPublisher" in content
        or "EventPublisher = None" in content
    )

    validation["introspection_method_present"] = (
        "_publish_introspection_event" in content
    )

    validation["lifecycle_methods_present"] = (
        "async def initialize(self)" in content
        and "async def shutdown(self)" in content
    )

    # Check for startup script
    startup_script = node_result.get("startup_script")
    if startup_script and Path(startup_script).exists():
        validation["startup_script_exists"] = True

    return validation


async def main():
    """Main test execution."""

    print("\n" + "=" * 80)
    print("STAGE 4.5 EVENT BUS INTEGRATION - TEST SUITE")
    print("=" * 80)

    # Test configuration
    test_nodes = [
        {
            "node_type": "effect",
            "service_name": "test_stage45_effect",
            "domain": "testing",
            "description": "Test Effect node with Stage 4.5 event bus integration",
        },
        {
            "node_type": "compute",
            "service_name": "test_stage45_compute",
            "domain": "testing",
            "description": "Test Compute node with Stage 4.5 event bus integration",
        },
        {
            "node_type": "reducer",
            "service_name": "test_stage45_reducer",
            "domain": "testing",
            "description": "Test Reducer node with Stage 4.5 event bus integration",
        },
        {
            "node_type": "orchestrator",
            "service_name": "test_stage45_orchestrator",
            "domain": "testing",
            "description": "Test Orchestrator node with Stage 4.5 event bus integration",
        },
    ]

    # Output directory
    output_dir = Path(__file__).parent.parent / "generated_test_nodes" / "stage45"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nOutput directory: {output_dir}")
    print(f"Test nodes: {len(test_nodes)}")

    # Generate all test nodes
    results = []
    for config in test_nodes:
        try:
            result = await generate_test_node(
                node_type=config["node_type"],
                service_name=config["service_name"],
                domain=config["domain"],
                description=config["description"],
                output_dir=output_dir,
            )
            results.append((config["node_type"], result))
        except Exception as e:
            print(f"\n❌ Failed to generate {config['node_type']} node: {e}")
            results.append((config["node_type"], {"error": str(e)}))

    # Validate all nodes
    print("\n" + "=" * 80)
    print("VALIDATION RESULTS")
    print("=" * 80)

    validation_results = []
    for node_type, result in results:
        if "error" in result:
            print(f"\n❌ {node_type.upper()}: FAILED GENERATION")
            print(f"   Error: {result['error']}")
            continue

        print(f"\n{node_type.upper()} Node Validation:")
        validation = await validate_stage45_integration(result)
        validation_results.append((node_type, validation))

        for check, passed in validation.items():
            status = "✅" if passed else "❌"
            print(f"   {status} {check.replace('_', ' ').title()}: {passed}")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    total_nodes = len(test_nodes)
    successful_generations = sum(1 for _, r in results if "error" not in r)

    print(f"\nGeneration Success Rate: {successful_generations}/{total_nodes}")

    if validation_results:
        # Calculate validation metrics
        validation_metrics = {
            "event_bus_integrated": 0,
            "startup_script_exists": 0,
            "introspection_method_present": 0,
            "lifecycle_methods_present": 0,
            "event_imports_present": 0,
        }

        for _, validation in validation_results:
            for key, value in validation.items():
                if value:
                    validation_metrics[key] += 1

        print("\nValidation Metrics:")
        for metric, count in validation_metrics.items():
            percentage = (count / len(validation_results)) * 100
            print(
                f"   {metric.replace('_', ' ').title()}: {count}/{len(validation_results)} ({percentage:.1f}%)"
            )

        # Overall Stage 4.5 completion
        all_passed = all(all(v.values()) for _, v in validation_results)

        if all_passed:
            print("\n✅ Stage 4.5 Integration: COMPLETE")
            print("   All node types have full event bus integration")
        else:
            print("\n⚠️  Stage 4.5 Integration: PARTIAL")
            print("   Some validation checks failed")

    # Performance check
    print("\n" + "=" * 80)
    print("PERFORMANCE ANALYSIS")
    print("=" * 80)

    for node_type, result in results:
        if "error" in result:
            continue

        stages = result.get("stages", [])
        stage45 = next(
            (s for s in stages if s.get("stage_name") == "event_bus_integration"), None
        )

        if stage45:
            duration = stage45.get("duration_ms", 0)
            status = stage45.get("status", "unknown")
            print(f"\n{node_type.upper()} - Stage 4.5:")
            print(f"   Duration: {duration:.2f}ms")
            print(f"   Status: {status}")

            # Check if it's within performance target
            if duration > 0:
                total_duration = sum(s.get("duration_ms", 0) for s in stages)
                overhead = (
                    (duration / total_duration * 100) if total_duration > 0 else 0
                )
                print(f"   Overhead: {overhead:.2f}% of total pipeline")

                if overhead < 5.0:
                    print("   ✅ Within target (<5%)")
                else:
                    print("   ⚠️  Above target (>5%)")


if __name__ == "__main__":
    asyncio.run(main())
