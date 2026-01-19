#!/usr/bin/env python3
"""
Tests for LoggingEventPublisher singleton pattern optimization.

This test suite verifies the singleton pattern eliminates ~50ms connection
overhead per call and ensures thread safety and proper resource management.

Created: 2025-11-14
Reference: PR #32 review (performance optimization)
"""

import asyncio
import time

import pytest
from agents.lib.logging_event_publisher import (
    LoggingEventPublisherContext,
    _get_global_publisher,
    publish_application_log,
    publish_audit_log,
    publish_security_log,
)


class TestSingletonPattern:
    """Test singleton pattern for convenience functions."""

    @pytest.mark.asyncio
    async def test_singleton_initialization(self):
        """Test that first call creates publisher."""
        # Reset global singleton (for testing)
        from agents.lib import logging_event_publisher

        logging_event_publisher._global_publisher = None

        # First call should create publisher
        start_time = time.time()
        publisher1 = await _get_global_publisher()
        init_duration = time.time() - start_time

        assert publisher1 is not None
        assert publisher1._started is True
        # First call includes initialization overhead
        assert init_duration < 1.0  # Should be <1s even with connection setup

    @pytest.mark.asyncio
    async def test_singleton_reuse(self):
        """Test that subsequent calls reuse connection."""
        from agents.lib import logging_event_publisher

        # Reset global singleton (for testing)
        logging_event_publisher._global_publisher = None

        # First call (initialization)
        publisher1 = await _get_global_publisher()

        # Subsequent calls should return same publisher
        start_time = time.time()
        publisher2 = await _get_global_publisher()
        reuse_duration = time.time() - start_time

        assert publisher2 is publisher1  # Same object
        assert reuse_duration < 0.01  # Should be <10ms (much faster than init)

    @pytest.mark.asyncio
    async def test_concurrent_singleton_access(self):
        """Test thread-safe singleton access with concurrent calls."""
        from agents.lib import logging_event_publisher

        # Reset global singleton (for testing)
        logging_event_publisher._global_publisher = None

        # Multiple concurrent calls should all get same publisher
        publishers = await asyncio.gather(*[_get_global_publisher() for _ in range(10)])

        # All should be the same instance
        assert len(set(id(p) for p in publishers)) == 1
        assert all(p._started for p in publishers)

    @pytest.mark.asyncio
    async def test_performance_comparison_context_manager_vs_singleton(self):
        """
        Compare performance: context manager vs singleton.

        Expected results:
        - Context manager: ~50ms per call (creates new connection each time)
        - Singleton: ~50ms first call, <5ms subsequent calls
        """
        from agents.lib import logging_event_publisher

        # Reset global singleton (for testing)
        logging_event_publisher._global_publisher = None

        # Test context manager approach (old pattern)
        context_manager_times = []
        for _ in range(3):
            start = time.time()
            async with LoggingEventPublisherContext(enable_events=False) as publisher:
                pass  # Just measure overhead
            context_manager_times.append(time.time() - start)

        avg_context_manager_time = sum(context_manager_times) / len(
            context_manager_times
        )

        # Test singleton approach (new pattern)
        singleton_times = []
        for i in range(3):
            start = time.time()
            publisher = await _get_global_publisher(enable_events=False)
            singleton_times.append(time.time() - start)

        first_call_time = singleton_times[0]  # Includes initialization
        subsequent_avg_time = sum(singleton_times[1:]) / len(singleton_times[1:])

        print("\n=== Performance Comparison ===")
        print(f"Context Manager (avg): {avg_context_manager_time*1000:.2f}ms")
        print(f"Singleton (first call): {first_call_time*1000:.2f}ms")
        print(f"Singleton (subsequent): {subsequent_avg_time*1000:.2f}ms")
        print(f"Speedup: {avg_context_manager_time / subsequent_avg_time:.1f}x faster")

        # Assertions
        assert first_call_time < 1.0  # Initialization should be <1s
        assert subsequent_avg_time < 0.01  # Reuse should be <10ms
        # Note: With enable_events=False, both approaches are very fast (<1ms)
        # so performance difference is minimal. The real benefit is seen when
        # enable_events=True and Kafka connections are involved (~50ms overhead)

    @pytest.mark.asyncio
    async def test_high_frequency_logging_performance(self):
        """
        Test performance with high-frequency logging (100 events).

        Expected results:
        - Singleton: Total time ~500ms (1st call: 50ms + 99 calls: 5ms each)
        - Context manager: Total time ~5000ms (100 calls * 50ms each)
        """
        from agents.lib import logging_event_publisher

        # Reset global singleton (for testing)
        logging_event_publisher._global_publisher = None

        num_calls = 100

        # Test singleton approach
        start = time.time()
        for i in range(num_calls):
            publisher = await _get_global_publisher(enable_events=False)
        singleton_total_time = time.time() - start

        print(f"\n=== High-Frequency Logging ({num_calls} calls) ===")
        print(f"Singleton total time: {singleton_total_time*1000:.2f}ms")
        print(f"Singleton avg per call: {singleton_total_time*1000/num_calls:.2f}ms")

        # Singleton should be fast (avg <10ms per call including first call)
        assert singleton_total_time < 1.0  # Total should be <1s
        assert singleton_total_time / num_calls < 0.01  # Avg per call should be <10ms

    @pytest.mark.asyncio
    async def test_convenience_functions_use_singleton(self):
        """Test that convenience functions use singleton pattern."""
        from agents.lib import logging_event_publisher

        # Reset global singleton (for testing)
        logging_event_publisher._global_publisher = None

        # Call convenience function multiple times
        times = []
        for i in range(10):
            start = time.time()
            result = await publish_application_log(
                service_name="test",
                instance_id="test-1",
                level="INFO",
                logger_name="test.logger",
                message="Test message",
                code="TEST",
                enable_events=False,  # Disable actual publishing
            )
            times.append(time.time() - start)

        first_call_time = times[0]
        subsequent_avg_time = sum(times[1:]) / len(times[1:])

        print("\n=== Convenience Function Performance ===")
        print(f"First call: {first_call_time*1000:.2f}ms")
        print(f"Subsequent avg: {subsequent_avg_time*1000:.2f}ms")
        print(f"Speedup: {first_call_time / subsequent_avg_time:.1f}x faster")

        # Verify singleton is created and reused
        # Note: mypy can't track that publish_application_log sets _global_publisher,
        # so it incorrectly thinks _global_publisher is always None and code after the
        # assert is unreachable. The ignore below is required for this mypy limitation.
        publisher = logging_event_publisher._global_publisher
        assert publisher is not None
        # Subsequent calls should not be significantly slower than first
        # (both should be fast since enable_events=False)
        assert subsequent_avg_time < 0.01  # type: ignore[unreachable] # mypy limitation

    @pytest.mark.asyncio
    async def test_all_convenience_functions_share_singleton(self):
        """Test that all convenience functions share the same singleton."""
        from agents.lib import logging_event_publisher

        # Reset global singleton (for testing)
        logging_event_publisher._global_publisher = None

        # Call different convenience functions
        await publish_application_log(
            service_name="test",
            instance_id="test-1",
            level="INFO",
            logger_name="test.logger",
            message="Test",
            code="TEST",
            enable_events=False,
        )

        # Store publisher after first call
        publisher1 = logging_event_publisher._global_publisher

        await publish_audit_log(
            action="test.action",
            actor="test-actor",
            resource="test-resource",
            outcome="success",
            enable_events=False,
        )

        # Store publisher after second call
        publisher2 = logging_event_publisher._global_publisher

        await publish_security_log(
            event_type="test_event",
            user_id="test-user",
            resource="test-resource",
            decision="allow",
            enable_events=False,
        )

        # Store publisher after third call
        publisher3 = logging_event_publisher._global_publisher

        # All should have created/reused the same singleton
        # Note: mypy can't track that publish_* functions set _global_publisher
        assert publisher1 is not None
        assert publisher2 is publisher1  # type: ignore[unreachable]
        assert publisher3 is publisher1  # Same instance
        # Note: _started is False when enable_events=False (expected behavior)


class TestPerformanceBenchmarks:
    """Performance benchmarks for singleton vs context manager."""

    @pytest.mark.benchmark
    def test_benchmark_context_manager_pattern(self, benchmark):
        """Benchmark context manager pattern (old approach)."""

        async def create_publisher_context_manager():
            async with LoggingEventPublisherContext(enable_events=False) as publisher:
                return publisher

        def sync_wrapper():
            return asyncio.run(create_publisher_context_manager())

        # Warmup
        asyncio.run(create_publisher_context_manager())

        # Benchmark
        result = benchmark(sync_wrapper)

    @pytest.mark.benchmark
    def test_benchmark_singleton_pattern(self, benchmark):
        """Benchmark singleton pattern (new approach)."""
        from agents.lib import logging_event_publisher

        # Reset singleton for fair comparison
        logging_event_publisher._global_publisher = None

        async def get_singleton_publisher():
            return await _get_global_publisher(enable_events=False)

        def sync_wrapper():
            return asyncio.run(get_singleton_publisher())

        # Warmup (creates singleton)
        asyncio.run(get_singleton_publisher())

        # Benchmark subsequent calls (reuses singleton)
        result = benchmark(sync_wrapper)


if __name__ == "__main__":
    """Run tests with performance reporting."""
    pytest.main(
        [
            __file__,
            "-v",
            "-s",  # Show print statements
            "--asyncio-mode=auto",
        ]
    )
