#!/usr/bin/env python3
"""
Parallel Generation Performance Benchmark

Demonstrates 3x+ throughput improvement with parallel node generation.

Setup:
    Run from project root with proper PYTHONPATH:

        cd /path/to/omniclaude
        PYTHONPATH=/path/to/omniclaude python agents/parallel_execution/parallel_benchmark.py

    Or install the package in development mode:

        pip install -e .
"""

import asyncio
import tempfile
import time
from uuid import uuid4

from agents.lib.codegen_workflow import CodegenWorkflow
from agents.lib.simple_prd_analyzer import PRDAnalyzer
from agents.tests.fixtures.phase4_fixtures import EFFECT_NODE_PRD


async def benchmark_sequential_generation(num_nodes: int = 6) -> float:
    """
    Benchmark sequential node generation.

    Args:
        num_nodes: Number of nodes to generate

    Returns:
        Total time in seconds
    """
    print(f"\n=== Sequential Generation Benchmark ({num_nodes} nodes) ===")

    workflow = CodegenWorkflow(enable_parallel=False)
    analyzer = PRDAnalyzer()

    # Analyze PRD once
    analysis = await analyzer.analyze_prd(EFFECT_NODE_PRD)

    # Generate specified number of nodes
    node_types = ["EFFECT", "COMPUTE", "REDUCER"] * (num_nodes // 3 + 1)
    node_types = node_types[:num_nodes]

    with tempfile.TemporaryDirectory() as temp_dir:
        start_time = time.time()

        generated_nodes, total_files = await workflow._generate_nodes_sequential(
            session_id=uuid4(),
            node_types=node_types,
            prd_analysis=analysis,
            microservice_name="benchmark",
            domain="perf_test",
            output_directory=temp_dir,
        )

        total_time = time.time() - start_time

    print(f"Nodes generated: {len(generated_nodes)}/{num_nodes}")
    print(f"Total time: {total_time:.2f}s")
    print(f"Time per node: {total_time/num_nodes:.2f}s")

    return total_time


async def benchmark_parallel_generation(
    num_nodes: int = 6, max_workers: int = 3
) -> float:
    """
    Benchmark parallel node generation.

    Args:
        num_nodes: Number of nodes to generate
        max_workers: Number of parallel workers

    Returns:
        Total time in seconds
    """
    print(
        f"\n=== Parallel Generation Benchmark ({num_nodes} nodes, {max_workers} workers) ==="
    )

    workflow = CodegenWorkflow(enable_parallel=True, max_workers=max_workers)
    analyzer = PRDAnalyzer()

    # Analyze PRD once
    analysis = await analyzer.analyze_prd(EFFECT_NODE_PRD)

    # Generate specified number of nodes
    node_types = ["EFFECT", "COMPUTE", "REDUCER"] * (num_nodes // 3 + 1)
    node_types = node_types[:num_nodes]

    with tempfile.TemporaryDirectory() as temp_dir:
        start_time = time.time()

        generated_nodes, total_files = await workflow._generate_nodes_parallel(
            session_id=uuid4(),
            node_types=node_types,
            prd_analysis=analysis,
            microservice_name="benchmark",
            domain="perf_test",
            output_directory=temp_dir,
        )

        total_time = time.time() - start_time

    print(f"Nodes generated: {len(generated_nodes)}/{num_nodes}")
    print(f"Total time: {total_time:.2f}s")
    print(f"Time per node: {total_time/num_nodes:.2f}s")

    return total_time


async def run_comprehensive_benchmark():
    """Run comprehensive benchmark with multiple configurations"""

    print("\n" + "=" * 60)
    print("PARALLEL NODE GENERATION PERFORMANCE BENCHMARK")
    print("=" * 60)

    # Configuration
    configurations = [
        {"num_nodes": 3, "workers": 3, "name": "Small (3 nodes)"},
        {"num_nodes": 6, "workers": 3, "name": "Medium (6 nodes)"},
        {"num_nodes": 9, "workers": 3, "name": "Large (9 nodes)"},
    ]

    results = []

    for config in configurations:
        print(f"\n\n{'=' * 60}")
        print(f"Configuration: {config['name']}")
        print(f"{'=' * 60}")

        num_nodes = config["num_nodes"]
        workers = config["workers"]

        # Sequential
        sequential_time = await benchmark_sequential_generation(num_nodes)

        # Parallel
        parallel_time = await benchmark_parallel_generation(num_nodes, workers)

        # Calculate metrics
        speedup = sequential_time / parallel_time if parallel_time > 0 else 0
        throughput_improvement = (speedup - 1) * 100

        result = {
            "config": config["name"],
            "nodes": num_nodes,
            "workers": workers,
            "sequential_time": sequential_time,
            "parallel_time": parallel_time,
            "speedup": speedup,
            "throughput_improvement": throughput_improvement,
        }
        results.append(result)

        print(f"\n--- Results for {config['name']} ---")
        print(
            f"Sequential: {sequential_time:.2f}s ({sequential_time/num_nodes:.2f}s per node)"
        )
        print(
            f"Parallel:   {parallel_time:.2f}s ({parallel_time/num_nodes:.2f}s per node)"
        )
        print(f"Speedup:    {speedup:.2f}x")
        print(f"Throughput: {throughput_improvement:+.1f}%")

    # Summary table
    print("\n\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(
        f"{'Configuration':<20} {'Nodes':<8} {'Workers':<10} {'Speedup':<10} {'Improvement':<15}"
    )
    print("-" * 60)

    for r in results:
        print(
            f"{r['config']:<20} {r['nodes']:<8} {r['workers']:<10} {r['speedup']:.2f}x{'':<6} {r['throughput_improvement']:+.1f}%"
        )

    # Target achievement check
    print("\n" + "=" * 60)
    print("TARGET ACHIEVEMENT")
    print("=" * 60)

    target_speedup = 3.0
    best_speedup = max(r["speedup"] for r in results)
    avg_speedup = sum(r["speedup"] for r in results) / len(results)

    print(f"Target Speedup:  {target_speedup:.1f}x")
    print(
        f"Best Speedup:    {best_speedup:.2f}x {'✓' if best_speedup >= target_speedup else '✗'}"
    )
    print(
        f"Average Speedup: {avg_speedup:.2f}x {'✓' if avg_speedup >= target_speedup else '✗'}"
    )

    if best_speedup >= target_speedup:
        print(f"\n✓ SUCCESS: Achieved {target_speedup:.1f}x+ speedup target!")
    elif best_speedup >= 2.0:
        print(
            f"\n⚠ PARTIAL: Achieved {best_speedup:.2f}x speedup (target: {target_speedup:.1f}x)"
        )
    else:
        print(
            f"\n✗ BELOW TARGET: Only {best_speedup:.2f}x speedup (target: {target_speedup:.1f}x)"
        )

    print("\n" + "=" * 60)

    return results


if __name__ == "__main__":
    print("Starting parallel generation performance benchmark...")
    results = asyncio.run(run_comprehensive_benchmark())
    print("\nBenchmark complete!")
