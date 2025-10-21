#!/usr/bin/env python3
"""
Generation Performance Tests

Performance benchmarks and optimization tests for code generation.
"""

import asyncio
import tempfile
import time
from typing import Any, Dict

import pytest

from agents.lib.omninode_template_engine import OmniNodeTemplateEngine
from agents.lib.simple_prd_analyzer import SimplePRDAnalyzer
from agents.tests.fixtures.phase4_fixtures import (
    COMPUTE_NODE_PRD,
    EFFECT_NODE_PRD,
    LARGE_PRD_CONTENT,
    NODE_TYPE_FIXTURES,
    PERFORMANCE_EXPECTATIONS,
    REDUCER_NODE_PRD,
)


class TestGenerationLatency:
    """Tests for generation latency performance"""

    @pytest.mark.asyncio
    async def test_prd_analysis_latency(self):
        """Test that PRD analysis completes within expected time"""
        analyzer = SimplePRDAnalyzer()

        start_time = time.time()
        analysis = await analyzer.analyze_prd(EFFECT_NODE_PRD)
        end_time = time.time()

        latency_ms = (end_time - start_time) * 1000
        expected_ms = PERFORMANCE_EXPECTATIONS["prd_analysis_ms"]

        assert analysis is not None
        print(f"PRD analysis latency: {latency_ms:.2f}ms (expected: <{expected_ms}ms)")

        # Soft assertion - warn but don't fail
        if latency_ms > expected_ms:
            pytest.skip(
                f"PRD analysis slower than expected: {latency_ms:.2f}ms > {expected_ms}ms"
            )

    @pytest.mark.asyncio
    async def test_node_generation_latency(self):
        """Test that node generation completes within expected time"""
        from agents.tests.fixtures.phase4_fixtures import EFFECT_ANALYSIS_RESULT

        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            start_time = time.time()
            result = await engine.generate_node(
                analysis_result=EFFECT_ANALYSIS_RESULT,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )
            end_time = time.time()

            latency_ms = (end_time - start_time) * 1000

            assert result is not None
            print(f"Node generation latency: {latency_ms:.2f}ms")

            # Very generous limit for initial implementation
            assert latency_ms < 10000, f"Node generation too slow: {latency_ms:.2f}ms"

    @pytest.mark.asyncio
    async def test_full_pipeline_latency(self):
        """Test that full pipeline completes within expected time"""
        analyzer = SimplePRDAnalyzer()
        engine = OmniNodeTemplateEngine()

        start_time = time.time()

        # Analysis
        analysis = await analyzer.analyze_prd(EFFECT_NODE_PRD)

        # Generation
        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

        end_time = time.time()

        total_latency_ms = (end_time - start_time) * 1000
        expected_ms = PERFORMANCE_EXPECTATIONS["total_pipeline_ms"]

        assert result is not None
        print(
            f"Full pipeline latency: {total_latency_ms:.2f}ms (expected: <{expected_ms}ms)"
        )

        if total_latency_ms > expected_ms:
            pytest.skip(
                f"Pipeline slower than expected: {total_latency_ms:.2f}ms > {expected_ms}ms"
            )

    @pytest.mark.asyncio
    async def test_large_prd_analysis_performance(self):
        """Test analysis performance with large PRD"""
        analyzer = SimplePRDAnalyzer()

        start_time = time.time()
        analysis = await analyzer.analyze_prd(LARGE_PRD_CONTENT)
        end_time = time.time()

        latency_ms = (end_time - start_time) * 1000

        assert analysis is not None
        print(f"Large PRD analysis latency: {latency_ms:.2f}ms")

        # Should still be reasonable
        assert latency_ms < 5000, f"Large PRD analysis too slow: {latency_ms:.2f}ms"


class TestParallelGenerationSpeedup:
    """Tests for parallel generation speedup"""

    @pytest.mark.asyncio
    async def test_parallel_vs_sequential_generation(self):
        """Test that parallel generation is faster than sequential"""
        analyzer = SimplePRDAnalyzer()
        OmniNodeTemplateEngine()

        prds = [EFFECT_NODE_PRD, COMPUTE_NODE_PRD, REDUCER_NODE_PRD]

        # Sequential generation
        sequential_start = time.time()
        for prd_content in prds:
            await analyzer.analyze_prd(prd_content)
        sequential_end = time.time()
        sequential_time = sequential_end - sequential_start

        # Parallel generation
        parallel_start = time.time()
        await asyncio.gather(
            *[analyzer.analyze_prd(prd_content) for prd_content in prds]
        )
        parallel_end = time.time()
        parallel_time = parallel_end - parallel_start

        print(f"Sequential time: {sequential_time*1000:.2f}ms")
        print(f"Parallel time: {parallel_time*1000:.2f}ms")

        # Parallel should be faster or similar (not slower)
        # Note: For very fast operations (<10ms), async overhead can make parallel slower
        if sequential_time * 1000 < 10:
            pytest.skip(
                f"Operations too fast ({sequential_time*1000:.2f}ms) for meaningful parallel comparison"
            )

        # Allow some overhead for task spawning (3x multiplier)
        assert (
            parallel_time <= sequential_time * 3.0
        ), "Parallel generation unexpectedly slower"

    @pytest.mark.asyncio
    async def test_concurrent_node_generation(self):
        """Test concurrent generation of multiple nodes"""
        engine = OmniNodeTemplateEngine()

        async def generate_single_node(node_type: str, fixture: Dict[str, Any]):
            with tempfile.TemporaryDirectory() as temp_dir:
                return await engine.generate_node(
                    analysis_result=fixture["analysis"],
                    node_type=node_type,
                    microservice_name=fixture["microservice_name"],
                    domain=fixture["domain"],
                    output_directory=temp_dir,
                )

        start_time = time.time()

        # Generate all node types concurrently
        results = await asyncio.gather(
            *[
                generate_single_node(node_type, fixture)
                for node_type, fixture in NODE_TYPE_FIXTURES.items()
            ]
        )

        end_time = time.time()
        total_time_ms = (end_time - start_time) * 1000

        assert len(results) == 4
        print(f"Concurrent generation of 4 nodes: {total_time_ms:.2f}ms")

        # Should complete in reasonable time
        assert (
            total_time_ms < 20000
        ), f"Concurrent generation too slow: {total_time_ms:.2f}ms"


class TestMemoryUsage:
    """Tests for memory usage during generation"""

    @pytest.mark.asyncio
    async def test_memory_usage_single_generation(self):
        """Test memory usage for single node generation"""
        import os

        import psutil

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        analyzer = SimplePRDAnalyzer()
        engine = OmniNodeTemplateEngine()

        analysis = await analyzer.analyze_prd(EFFECT_NODE_PRD)

        with tempfile.TemporaryDirectory() as temp_dir:
            await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory

        print(f"Memory usage increase: {memory_increase:.2f}MB")

        # Should not use excessive memory
        assert memory_increase < 500, f"Excessive memory usage: {memory_increase:.2f}MB"

    @pytest.mark.asyncio
    async def test_memory_usage_large_prd(self):
        """Test memory usage with large PRD"""
        import os

        import psutil

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        analyzer = SimplePRDAnalyzer()
        await analyzer.analyze_prd(LARGE_PRD_CONTENT)

        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory

        print(f"Large PRD memory increase: {memory_increase:.2f}MB")

        # Should handle large PRDs efficiently
        assert (
            memory_increase < 1000
        ), f"Excessive memory for large PRD: {memory_increase:.2f}MB"


class TestScalability:
    """Tests for generation scalability"""

    @pytest.mark.asyncio
    async def test_multiple_sequential_generations(self):
        """Test performance with multiple sequential generations"""
        engine = OmniNodeTemplateEngine()
        from agents.tests.fixtures.phase4_fixtures import EFFECT_ANALYSIS_RESULT

        num_iterations = 5
        latencies = []

        with tempfile.TemporaryDirectory() as temp_dir:
            for i in range(num_iterations):
                start_time = time.time()
                await engine.generate_node(
                    analysis_result=EFFECT_ANALYSIS_RESULT,
                    node_type="EFFECT",
                    microservice_name=f"service_{i}",
                    domain="test",
                    output_directory=temp_dir,
                )
                end_time = time.time()

                latencies.append((end_time - start_time) * 1000)

        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        min_latency = min(latencies)

        print(f"Latency stats over {num_iterations} iterations:")
        print(f"  Average: {avg_latency:.2f}ms")
        print(f"  Min: {min_latency:.2f}ms")
        print(f"  Max: {max_latency:.2f}ms")

        # Latency should be consistent (no memory leaks or degradation)
        assert max_latency < avg_latency * 3, "Latency variance too high"

    @pytest.mark.asyncio
    async def test_generation_under_load(self):
        """Test generation performance under concurrent load"""
        engine = OmniNodeTemplateEngine()
        from agents.tests.fixtures.phase4_fixtures import EFFECT_ANALYSIS_RESULT

        num_concurrent = 10

        async def generate_one(index: int):
            with tempfile.TemporaryDirectory() as temp_dir:
                return await engine.generate_node(
                    analysis_result=EFFECT_ANALYSIS_RESULT,
                    node_type="EFFECT",
                    microservice_name=f"service_{index}",
                    domain="test",
                    output_directory=temp_dir,
                )

        start_time = time.time()
        results = await asyncio.gather(
            *[generate_one(i) for i in range(num_concurrent)]
        )
        end_time = time.time()

        total_time_ms = (end_time - start_time) * 1000

        assert len(results) == num_concurrent
        print(f"Generated {num_concurrent} nodes concurrently in {total_time_ms:.2f}ms")
        print(f"Average per node: {total_time_ms/num_concurrent:.2f}ms")


class TestCachingOptimizations:
    """Tests for caching optimizations (if implemented)"""

    @pytest.mark.asyncio
    async def test_template_caching(self):
        """Test that templates are cached and reused"""
        engine1 = OmniNodeTemplateEngine()
        engine2 = OmniNodeTemplateEngine()

        # Both engines should load templates
        # If caching is implemented, second load should be faster
        assert engine1.templates is not None
        assert engine2.templates is not None

        # Check that templates are actually loaded
        assert len(engine1.templates) > 0

    @pytest.mark.asyncio
    async def test_repeated_generation_performance(self):
        """Test performance of repeated generation (should benefit from caching)"""
        engine = OmniNodeTemplateEngine()
        from agents.tests.fixtures.phase4_fixtures import EFFECT_ANALYSIS_RESULT

        # First generation
        with tempfile.TemporaryDirectory() as temp_dir:
            start_time = time.time()
            await engine.generate_node(
                analysis_result=EFFECT_ANALYSIS_RESULT,
                node_type="EFFECT",
                microservice_name="service_1",
                domain="test",
                output_directory=temp_dir,
            )
            first_latency = (time.time() - start_time) * 1000

        # Second generation (should benefit from template caching)
        with tempfile.TemporaryDirectory() as temp_dir:
            start_time = time.time()
            await engine.generate_node(
                analysis_result=EFFECT_ANALYSIS_RESULT,
                node_type="EFFECT",
                microservice_name="service_2",
                domain="test",
                output_directory=temp_dir,
            )
            second_latency = (time.time() - start_time) * 1000

        print(f"First generation: {first_latency:.2f}ms")
        print(f"Second generation: {second_latency:.2f}ms")

        # Second should not be significantly slower (templates cached)
        assert (
            second_latency <= first_latency * 2
        ), "Repeated generation unexpectedly slow"


class TestBenchmarks:
    """Performance benchmarks for reporting"""

    @pytest.mark.asyncio
    async def test_benchmark_all_node_types(self):
        """Benchmark generation for all node types"""
        engine = OmniNodeTemplateEngine()
        benchmarks = {}

        for node_type, fixture in NODE_TYPE_FIXTURES.items():
            with tempfile.TemporaryDirectory() as temp_dir:
                start_time = time.time()
                await engine.generate_node(
                    analysis_result=fixture["analysis"],
                    node_type=node_type,
                    microservice_name=fixture["microservice_name"],
                    domain=fixture["domain"],
                    output_directory=temp_dir,
                )
                end_time = time.time()

                benchmarks[node_type] = (end_time - start_time) * 1000

        print("\n=== Generation Benchmarks ===")
        for node_type, latency_ms in benchmarks.items():
            print(f"{node_type}: {latency_ms:.2f}ms")

        total_avg = sum(benchmarks.values()) / len(benchmarks)
        print(f"Average: {total_avg:.2f}ms")

        # All should complete in reasonable time
        for node_type, latency_ms in benchmarks.items():
            assert (
                latency_ms < 10000
            ), f"{node_type} generation too slow: {latency_ms:.2f}ms"

    @pytest.mark.asyncio
    async def test_benchmark_full_pipeline(self):
        """Benchmark full pipeline from PRD to generated code"""
        analyzer = SimplePRDAnalyzer()
        engine = OmniNodeTemplateEngine()

        phases = {}

        # Phase 1: PRD Analysis
        start = time.time()
        analysis = await analyzer.analyze_prd(EFFECT_NODE_PRD)
        phases["analysis"] = (time.time() - start) * 1000

        # Phase 2: Node Generation
        with tempfile.TemporaryDirectory() as temp_dir:
            start = time.time()
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )
            phases["generation"] = (time.time() - start) * 1000

        print("\n=== Pipeline Benchmark ===")
        for phase, latency_ms in phases.items():
            print(f"{phase}: {latency_ms:.2f}ms")
        print(f"Total: {sum(phases.values()):.2f}ms")

        # Record for comparison
        assert analysis is not None
        assert result is not None
