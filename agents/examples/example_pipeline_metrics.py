#!/usr/bin/env python3
"""
Example: Pipeline with Performance Tracking and Quality Gates

Demonstrates Week 1 Day 5 deliverables:
- Performance metrics collection
- Quality gate execution
- Metrics summary in results
"""

import asyncio
import json
import tempfile


# Mock pipeline execution for demonstration
# (Real execution requires full omnibase_core environment)


async def simulate_pipeline_execution():
    """Simulate pipeline execution with metrics."""
    print("=" * 70)
    print("GENERATION PIPELINE WITH PERFORMANCE TRACKING & QUALITY GATES")
    print("=" * 70)
    print()

    # Simulate pipeline stages with timing
    stages = [
        ("Stage 1: PRD Analysis", 4500, 5000),
        ("Stage 1.5: Intelligence Gathering", 2800, 3000),
        ("Stage 2: Contract Building", 1900, 2000),
        ("Stage 4: Code Generation", 11500, 12500),
        ("Stage 4.5: Event Bus Integration", 1800, 2000),
        ("Stage 5: Post Validation", 4600, 5000),
        ("Stage 5.5: AI Refinement", 2700, 3000),
    ]

    print("📊 PIPELINE EXECUTION:")
    print()

    total_actual = 0
    total_target = 0
    within_threshold = 0

    for stage_name, actual_ms, target_ms in stages:
        ratio = actual_ms / target_ms
        status = "✅" if ratio <= 1.1 else "⚠️"

        print(f"  {status} {stage_name}")
        print(
            f"     Actual: {actual_ms}ms | Target: {target_ms}ms | Ratio: {ratio:.2f}"
        )

        total_actual += actual_ms
        total_target += target_ms
        if ratio <= 1.1:
            within_threshold += 1

    print()
    print("🎯 QUALITY GATES:")
    print()

    gates = [
        ("SV-001", "Input Validation", "passed", "blocking"),
        ("SV-003", "Output Validation", "passed", "blocking"),
        ("QC-001", "ONEX Standards", "passed", "blocking"),
    ]

    for gate_id, gate_name, status, gate_type in gates:
        icon = "✅" if status == "passed" else "❌"
        print(f"  {icon} {gate_id}: {gate_name} ({gate_type})")

    print()
    print("=" * 70)
    print("PERFORMANCE SUMMARY")
    print("=" * 70)
    print()

    overall_ratio = total_actual / total_target

    summary = {
        "performance_metrics": {
            "total_stages": len(stages),
            "total_duration_ms": total_actual,
            "total_target_ms": total_target,
            "overall_performance_ratio": round(overall_ratio, 2),
            "stages_within_threshold": within_threshold,
            "performance_status": (
                "✅ EXCELLENT" if overall_ratio < 1.0 else "⚠️ NEEDS OPTIMIZATION"
            ),
        },
        "quality_gates": {
            "total_gates": len(gates),
            "passed": 3,
            "failed": 0,
            "has_blocking_failures": False,
            "status": "✅ ALL GATES PASSED",
        },
    }

    print(json.dumps(summary, indent=2))
    print()

    # Performance insights
    print("=" * 70)
    print("INSIGHTS")
    print("=" * 70)
    print()

    if overall_ratio < 1.0:
        savings_ms = total_target - total_actual
        savings_pct = (1 - overall_ratio) * 100
        print(f"  ⚡ Performance: {savings_pct:.1f}% UNDER BUDGET")
        print(f"  ⚡ Time saved: {savings_ms}ms ({savings_ms/1000:.2f}s)")
    else:
        excess_ms = total_actual - total_target
        excess_pct = (overall_ratio - 1) * 100
        print(f"  ⚠️  Performance: {excess_pct:.1f}% OVER BUDGET")
        print(f"  ⚠️  Time excess: {excess_ms}ms ({excess_ms/1000:.2f}s)")

    print()
    print(
        f"  📈 Stages within threshold: {within_threshold}/{len(stages)} ({within_threshold/len(stages)*100:.0f}%)"
    )
    print(f"  ✅ Quality gates passed: {len(gates)}/{len(gates)} (100%)")
    print()

    return summary


async def demonstrate_metrics_api():
    """Demonstrate metrics API usage."""
    print("=" * 70)
    print("METRICS API DEMONSTRATION")
    print("=" * 70)
    print()

    # Import models
    from agents.lib.models.model_performance_tracking import (
        MetricsCollector,
    )
    from agents.lib.models.model_quality_gate import (
        EnumQualityGate,
        QualityGateRegistry,
    )

    print("1️⃣  Creating MetricsCollector...")
    collector = MetricsCollector()
    collector.set_threshold("test_stage", target_ms=5000)
    print("   ✅ Threshold configured: 5000ms")
    print()

    print("2️⃣  Recording stage timing...")
    metric = collector.record_stage_timing("test_stage", duration_ms=4500)
    print(f"   📊 Duration: {metric.duration_ms}ms")
    print(f"   🎯 Target: {metric.target_ms}ms")
    print(f"   📈 Performance ratio: {metric.performance_ratio:.2f}")
    print(f"   ✅ Within threshold: {metric.is_within_threshold}")
    print()

    print("3️⃣  Checking quality gate...")
    registry = QualityGateRegistry()
    result = await registry.check_gate(
        EnumQualityGate.INPUT_VALIDATION,
        {"prompt": "test", "output_dir": tempfile.gettempdir()},
    )
    print(f"   🚦 Gate: {result.gate.gate_name}")
    print(f"   ✅ Status: {result.status}")
    print(f"   ⏱️  Execution time: {result.execution_time_ms}ms")
    print(f"   🎯 Target: {result.gate.performance_target_ms}ms")
    print()

    print("4️⃣  Generating summary...")
    metrics_summary = collector.get_summary()
    gates_summary = registry.get_summary()

    print("   📊 Metrics Summary:")
    print(f"      Total stages: {metrics_summary['total_stages']}")
    print(f"      Total duration: {metrics_summary['total_duration_ms']}ms")
    print(
        f"      Performance ratio: {metrics_summary['overall_performance_ratio']:.2f}"
    )
    print()

    print("   🚦 Quality Gates Summary:")
    print(f"      Total gates: {gates_summary['total_gates']}")
    print(f"      Passed: {gates_summary['passed']}")
    print(f"      Failed: {gates_summary['failed']}")
    print()


async def main():
    """Run all demonstrations."""
    # Simulate pipeline execution
    await simulate_pipeline_execution()

    print()
    print()

    # Demonstrate metrics API
    await demonstrate_metrics_api()

    print("=" * 70)
    print("DEMONSTRATION COMPLETE")
    print("=" * 70)
    print()
    print("All metrics and quality gates are now integrated into the pipeline!")
    print("See POLY-3-SUMMARY.md for complete implementation details.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
