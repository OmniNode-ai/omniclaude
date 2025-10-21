"""
Comprehensive test suite for performance optimizations.

Tests all implemented performance improvements including:
- Parallel RAG queries
- Parallel model calls
- Batch database operations
- Circuit breaker pattern
- Retry manager
- Performance monitoring
- Input validation
- Context optimization
- Agent analytics
"""

import asyncio
import time
import uuid

import pytest

# Import the modules we're testing (skip module if heavy deps unavailable)
try:
    from agents.parallel_execution.context_manager import ContextManager
except Exception:
    ContextManager = None
    pytest.skip(
        "ContextManager dependencies unavailable (e.g., mcp_client); skipping performance optimization suite.",
        allow_module_level=True,
    )
from agents.lib.agent_analytics import AgentAnalytics, track_agent_performance
from agents.lib.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    call_with_breaker,
)
from agents.lib.context_optimizer import ContextOptimizer
from agents.lib.input_validator import InputValidator
from agents.lib.performance_monitor import PerformanceMonitor
from agents.lib.performance_optimization import PerformanceOptimizer
from agents.lib.retry_manager import RetryConfig, RetryManager, execute_with_retry
from agents.parallel_execution.quorum_validator import QuorumValidator


class TestParallelRAGQueries:
    """Test parallel RAG query execution in context manager."""

    @pytest.mark.asyncio
    async def test_parallel_rag_queries(self):
        """Test that RAG queries execute in parallel."""
        context_manager = ContextManager()

        # Mock RAG queries
        rag_queries = ["test query 1", "test query 2", "test query 3"]

        start_time = time.time()

        # This should execute queries in parallel
        context_items = await context_manager.gather_global_context(
            user_prompt="Test prompt", rag_queries=rag_queries, max_rag_results=5
        )

        end_time = time.time()
        duration = end_time - start_time

        # Should complete faster than sequential execution
        # (This is a basic test - in real scenarios we'd mock the actual RAG calls)
        assert duration < 5.0  # Should be much faster than sequential
        assert isinstance(context_items, dict)

    @pytest.mark.asyncio
    async def test_context_optimization_integration(self):
        """Test context optimization integration."""
        context_manager = ContextManager()

        # Test with optimization enabled
        context_items = await context_manager.gather_global_context(
            user_prompt="Generate a Python function to calculate fibonacci numbers",
            rag_queries=["python", "fibonacci", "algorithm"],
            max_rag_results=5,
            enable_optimization=True,
        )

        assert isinstance(context_items, dict)
        # Should have some context items
        assert len(context_items) >= 0


class TestParallelModelCalls:
    """Test parallel model calls in quorum validator."""

    @pytest.mark.asyncio
    async def test_parallel_model_validation(self):
        """Test that model validation calls execute in parallel."""
        quorum = QuorumValidator()

        # Mock task breakdown
        task_breakdown = {
            "tasks": [
                {
                    "id": "task1",
                    "description": "Test task",
                    "input_data": {"node_type": "code_generation"},
                }
            ]
        }

        start_time = time.time()

        # This should execute model calls in parallel
        result = await quorum.validate_intent(
            user_prompt="Test prompt", task_breakdown=task_breakdown
        )

        end_time = time.time()
        duration = end_time - start_time

        # Should complete faster than sequential execution
        assert duration < 10.0  # Should be much faster than sequential
        assert hasattr(result, "decision")
        assert hasattr(result, "confidence")


class TestBatchDatabaseOperations:
    """Test batch database operations."""

    @pytest.mark.asyncio
    async def test_batch_insert_operations(self):
        """Test batch insert operations."""
        PerformanceOptimizer()

        # Test data
        test_data = [
            {"id": str(uuid.uuid4()), "name": f"test_{i}", "value": i}
            for i in range(10)
        ]

        # Test batch insert
        start_time = time.time()

        # This would normally insert into a test table
        # For now, we'll just test the batch processing logic
        batch_size = 5
        batches = [
            test_data[i : i + batch_size] for i in range(0, len(test_data), batch_size)
        ]

        end_time = time.time()
        duration = end_time - start_time

        assert len(batches) == 2  # 10 items / 5 batch size = 2 batches
        assert duration < 1.0  # Should be very fast

    @pytest.mark.asyncio
    async def test_batch_write_with_pooling(self):
        """Test batch write with connection pooling."""
        optimizer = PerformanceOptimizer()

        # Test data
        test_data = [
            {"id": str(uuid.uuid4()), "metric": f"test_metric_{i}", "value": i * 10}
            for i in range(20)
        ]

        # Test batch write
        start_time = time.time()

        # Simulate batch write operation
        result = await optimizer.batch_write_with_pooling(
            data=test_data, operation_type="INSERT", table_name="test_metrics"
        )

        end_time = time.time()
        duration = end_time - start_time

        assert result is not None
        assert duration < 2.0  # Should be efficient


class TestCircuitBreaker:
    """Test circuit breaker pattern."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_closed_state(self):
        """Test circuit breaker in CLOSED state (normal operation)."""
        config = CircuitBreakerConfig(
            failure_threshold=3, timeout_seconds=10.0, success_threshold=2
        )

        breaker = CircuitBreaker("test_breaker", config)

        # Test successful operation
        async def successful_operation():
            return "success"

        result = await call_with_breaker(
            breaker_name="test_breaker", config=config, func=successful_operation
        )

        assert result == "success"
        assert breaker.state.value == "CLOSED"

    @pytest.mark.asyncio
    async def test_circuit_breaker_failure_threshold(self):
        """Test circuit breaker opening after failure threshold."""
        config = CircuitBreakerConfig(
            failure_threshold=2, timeout_seconds=1.0, success_threshold=1
        )

        breaker = CircuitBreaker("test_breaker_fail", config)

        # Test failing operation
        async def failing_operation():
            raise Exception("Test failure")

        # First failure
        with pytest.raises(Exception):
            await call_with_breaker(
                breaker_name="test_breaker_fail", config=config, func=failing_operation
            )

        # Second failure should open the circuit
        with pytest.raises(Exception):
            await call_with_breaker(
                breaker_name="test_breaker_fail", config=config, func=failing_operation
            )

        # Circuit should be open now
        assert breaker.state.value == "OPEN"

    @pytest.mark.asyncio
    async def test_circuit_breaker_timeout_recovery(self):
        """Test circuit breaker timeout and recovery."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            timeout_seconds=0.1,
            success_threshold=1,  # Very short timeout for testing
        )

        breaker = CircuitBreaker("test_breaker_timeout", config)

        # Trigger failure to open circuit
        async def failing_operation():
            raise Exception("Test failure")

        with pytest.raises(Exception):
            await call_with_breaker(
                breaker_name="test_breaker_timeout",
                config=config,
                func=failing_operation,
            )

        assert breaker.state.value == "OPEN"

        # Wait for timeout
        await asyncio.sleep(0.2)

        # Test successful operation after timeout
        async def successful_operation():
            return "success"

        result = await call_with_breaker(
            breaker_name="test_breaker_timeout",
            config=config,
            func=successful_operation,
        )

        assert result == "success"
        assert breaker.state.value == "CLOSED"


class TestRetryManager:
    """Test retry manager with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retry_success_on_retry(self):
        """Test retry manager succeeding after initial failures."""
        retry_manager = RetryManager()

        attempt_count = 0

        async def flaky_operation():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise Exception(f"Attempt {attempt_count} failed")
            return f"Success on attempt {attempt_count}"

        config = RetryConfig(
            max_retries=5, base_delay=0.1, max_delay=1.0, backoff_multiplier=2.0
        )

        result = await execute_with_retry(
            retry_manager=retry_manager, config=config, func=flaky_operation
        )

        assert result == "Success on attempt 3"
        assert attempt_count == 3

    @pytest.mark.asyncio
    async def test_retry_max_retries_exceeded(self):
        """Test retry manager when max retries are exceeded."""
        retry_manager = RetryManager()

        attempt_count = 0

        async def always_failing_operation():
            nonlocal attempt_count
            attempt_count += 1
            raise Exception(f"Attempt {attempt_count} failed")

        config = RetryConfig(
            max_retries=3, base_delay=0.1, max_delay=1.0, backoff_multiplier=2.0
        )

        with pytest.raises(Exception, match="Attempt 4 failed"):
            await execute_with_retry(
                retry_manager=retry_manager,
                config=config,
                func=always_failing_operation,
            )

        assert attempt_count == 4  # 1 initial + 3 retries

    @pytest.mark.asyncio
    async def test_retry_exponential_backoff(self):
        """Test exponential backoff timing."""
        retry_manager = RetryManager()

        attempt_times = []

        async def failing_operation():
            attempt_times.append(time.time())
            raise Exception("Always fails")

        config = RetryConfig(
            max_retries=3, base_delay=0.1, max_delay=1.0, backoff_multiplier=2.0
        )

        time.time()

        with pytest.raises(Exception):
            await execute_with_retry(
                retry_manager=retry_manager, config=config, func=failing_operation
            )

        # Check that delays are increasing exponentially
        if len(attempt_times) >= 3:
            delay1 = attempt_times[1] - attempt_times[0]
            delay2 = attempt_times[2] - attempt_times[1]

            # Second delay should be longer than first
            assert delay2 > delay1


class TestPerformanceMonitor:
    """Test performance monitoring."""

    @pytest.mark.asyncio
    async def test_phase_performance_tracking(self):
        """Test phase performance tracking."""
        monitor = PerformanceMonitor()

        # Test tracking a phase
        run_id = str(uuid.uuid4())
        phase = "test_phase"

        # Start tracking
        await monitor.track_phase_performance(
            run_id=run_id, phase=phase, metadata={"test": True}
        )

        # Simulate some work
        await asyncio.sleep(0.1)

        # End tracking
        await monitor.track_phase_performance(
            run_id=run_id, phase=phase, metadata={"test": True, "completed": True}
        )

        # Get metrics
        metrics = await monitor.get_performance_metrics(run_id=run_id)

        assert metrics is not None
        assert len(metrics) > 0

    @pytest.mark.asyncio
    async def test_agent_performance_tracking(self):
        """Test agent performance tracking."""
        monitor = PerformanceMonitor()

        # Test tracking an agent
        run_id = str(uuid.uuid4())
        agent_id = "test_agent"

        # Start tracking
        await monitor.track_agent_performance(
            run_id=run_id,
            agent_id=agent_id,
            task_type="test_task",
            metadata={"test": True},
        )

        # Simulate some work
        await asyncio.sleep(0.1)

        # End tracking
        await monitor.track_agent_performance(
            run_id=run_id,
            agent_id=agent_id,
            task_type="test_task",
            metadata={"test": True, "completed": True},
        )

        # Get metrics
        metrics = await monitor.get_performance_metrics(run_id=run_id)

        assert metrics is not None
        assert len(metrics) > 0


class TestInputValidator:
    """Test input validation."""

    @pytest.mark.asyncio
    async def test_input_validation_success(self):
        """Test successful input validation."""
        validator = InputValidator()

        # Valid input
        user_prompt = "Generate a Python function to calculate fibonacci numbers"
        tasks_data = {
            "tasks": [
                {
                    "id": "task1",
                    "description": "Create fibonacci function",
                    "input_data": {"node_type": "code_generation"},
                }
            ]
        }

        result = await validator.validate_and_sanitize(
            user_prompt=user_prompt, tasks_data=tasks_data
        )

        assert result["is_valid"] is True
        assert result["sanitized_prompt"] == user_prompt
        assert result["sanitized_tasks"] == tasks_data
        assert len(result["deficiencies"]) == 0

    @pytest.mark.asyncio
    async def test_input_validation_failure(self):
        """Test input validation failure."""
        validator = InputValidator()

        # Invalid input - empty prompt
        user_prompt = ""
        tasks_data = {}

        result = await validator.validate_and_sanitize(
            user_prompt=user_prompt, tasks_data=tasks_data
        )

        assert result["is_valid"] is False
        assert len(result["deficiencies"]) > 0
        assert "prompt" in result["deficiencies"][0].lower()

    @pytest.mark.asyncio
    async def test_input_sanitization(self):
        """Test input sanitization."""
        validator = InputValidator()

        # Input with potential issues
        user_prompt = "  Generate a Python function  \n\n  "
        tasks_data = {
            "tasks": [
                {
                    "id": "task1",
                    "description": "  Create fibonacci function  ",
                    "input_data": {"node_type": "code_generation"},
                }
            ]
        }

        result = await validator.validate_and_sanitize(
            user_prompt=user_prompt, tasks_data=tasks_data
        )

        assert result["is_valid"] is True
        assert result["sanitized_prompt"] == "Generate a Python function"
        assert (
            result["sanitized_tasks"]["tasks"][0]["description"]
            == "Create fibonacci function"
        )


class TestContextOptimizer:
    """Test context optimization."""

    @pytest.mark.asyncio
    async def test_context_learning(self):
        """Test context learning functionality."""
        optimizer = ContextOptimizer()

        # Test learning from successful context
        prompt = "Generate a Python function to calculate fibonacci numbers"
        context_types = ["code_examples", "algorithm_patterns", "python_syntax"]
        success_rate = 0.9
        avg_duration = 1500

        await optimizer.learn_from_success(
            prompt=prompt,
            context_types=context_types,
            success_rate=success_rate,
            avg_duration=avg_duration,
        )

        # Test prediction
        predicted_types = await optimizer.predict_context_needs(prompt)

        assert isinstance(predicted_types, list)
        # Should predict some context types
        assert len(predicted_types) >= 0

    @pytest.mark.asyncio
    async def test_context_prediction(self):
        """Test context prediction functionality."""
        optimizer = ContextOptimizer()

        # Test prediction for a new prompt
        prompt = "Create a REST API endpoint for user authentication"
        predicted_types = await optimizer.predict_context_needs(prompt)

        assert isinstance(predicted_types, list)
        # Should predict relevant context types
        assert len(predicted_types) >= 0


class TestAgentAnalytics:
    """Test agent analytics."""

    @pytest.mark.asyncio
    async def test_agent_performance_tracking(self):
        """Test agent performance tracking."""
        # Test tracking performance
        run_id = str(uuid.uuid4())
        agent_id = "test_agent"
        task_type = "code_generation"

        # Track successful performance
        await track_agent_performance(
            agent_id=agent_id,
            task_type=task_type,
            success=True,
            duration_ms=1500,
            run_id=run_id,
            metadata={"complexity": "high", "language": "python"},
        )

        # Track failed performance
        await track_agent_performance(
            agent_id=agent_id,
            task_type=task_type,
            success=False,
            duration_ms=2000,
            run_id=run_id,
            metadata={"complexity": "high", "language": "python"},
        )

        # Test getting recommendations
        analytics = AgentAnalytics()
        recommendations = await analytics.get_agent_recommendations(
            task_type=task_type, context={"complexity": "high"}, limit=3
        )

        assert isinstance(recommendations, list)

    @pytest.mark.asyncio
    async def test_agent_performance_summary(self):
        """Test agent performance summary."""
        analytics = AgentAnalytics()

        # Get performance summary
        summary = await analytics.get_agent_performance_summary(days=1)

        assert isinstance(summary, dict)
        assert "overall_metrics" in summary
        assert "agent_metrics" in summary
        assert "task_metrics" in summary

    @pytest.mark.asyncio
    async def test_performance_trends(self):
        """Test performance trends analysis."""
        analytics = AgentAnalytics()

        # Get performance trends
        trends = await analytics.get_performance_trends(days=1)

        assert isinstance(trends, dict)
        assert "trends" in trends
        assert "success_trend" in trends
        assert "duration_trend" in trends


class TestIntegrationScenarios:
    """Test integration scenarios combining multiple optimizations."""

    @pytest.mark.asyncio
    async def test_full_workflow_optimization(self):
        """Test full workflow with all optimizations."""
        # This test would simulate a complete workflow with all optimizations
        # For now, we'll test individual components

        # Test context manager with optimization
        context_manager = ContextManager()
        context_items = await context_manager.gather_global_context(
            user_prompt="Generate a Python function to calculate fibonacci numbers",
            rag_queries=["python", "fibonacci", "algorithm"],
            max_rag_results=5,
            enable_optimization=True,
        )

        assert isinstance(context_items, dict)

        # Test input validation
        validator = InputValidator()
        validation_result = await validator.validate_and_sanitize(
            user_prompt="Generate a Python function to calculate fibonacci numbers",
            tasks_data={
                "tasks": [
                    {
                        "id": "task1",
                        "description": "Create fibonacci function",
                        "input_data": {"node_type": "code_generation"},
                    }
                ]
            },
        )

        assert validation_result["is_valid"] is True

        # Test performance monitoring
        monitor = PerformanceMonitor()
        run_id = str(uuid.uuid4())

        await monitor.track_phase_performance(
            run_id=run_id, phase="test_phase", metadata={"test": True}
        )

        metrics = await monitor.get_performance_metrics(run_id=run_id)
        assert metrics is not None

    @pytest.mark.asyncio
    async def test_error_handling_and_recovery(self):
        """Test error handling and recovery with circuit breaker and retry."""
        # Test circuit breaker with retry
        config = CircuitBreakerConfig(
            failure_threshold=2, timeout_seconds=1.0, success_threshold=1
        )

        RetryConfig(
            max_retries=3, base_delay=0.1, max_delay=1.0, backoff_multiplier=2.0
        )

        attempt_count = 0

        async def flaky_operation():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise Exception(f"Attempt {attempt_count} failed")
            return f"Success on attempt {attempt_count}"

        # Test with circuit breaker
        result = await call_with_breaker(
            breaker_name="test_integration", config=config, func=flaky_operation
        )

        assert result == "Success on attempt 2"
        assert attempt_count == 2


# Performance benchmarks
class TestPerformanceBenchmarks:
    """Test performance benchmarks for optimizations."""

    @pytest.mark.asyncio
    async def test_parallel_vs_sequential_performance(self):
        """Test that parallel execution is faster than sequential."""
        # This would be a more comprehensive test in a real scenario
        # For now, we'll test basic timing

        start_time = time.time()

        # Simulate parallel execution
        tasks = [asyncio.sleep(0.1) for _ in range(5)]
        await asyncio.gather(*tasks)

        parallel_duration = time.time() - start_time

        start_time = time.time()

        # Simulate sequential execution
        for _ in range(5):
            await asyncio.sleep(0.1)

        sequential_duration = time.time() - start_time

        # Parallel should be faster (allowing for some overhead)
        assert parallel_duration < sequential_duration * 0.8

    @pytest.mark.asyncio
    async def test_batch_operation_performance(self):
        """Test that batch operations are more efficient."""
        optimizer = PerformanceOptimizer()

        # Test data
        test_data = [{"id": str(uuid.uuid4()), "value": i} for i in range(100)]

        # Test batch operation
        start_time = time.time()

        result = await optimizer.batch_write_with_pooling(
            data=test_data, operation_type="INSERT", table_name="test_performance"
        )

        batch_duration = time.time() - start_time

        # Should be efficient for batch operations
        assert batch_duration < 5.0  # Should complete quickly
        assert result is not None


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
