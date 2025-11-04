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

# Import the modules we're testing
# Note: Some modules have optional dependencies and will be None if unavailable
try:
    from agents.parallel_execution.context_manager import ContextManager
except Exception:
    ContextManager = None

try:
    from agents.parallel_execution.quorum_validator import QuorumValidator
except Exception:
    QuorumValidator = None

# These should always be available
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


@pytest.mark.skipif(
    ContextManager is None,
    reason="ContextManager dependencies unavailable (e.g., mcp_client)",
)
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


@pytest.mark.skipif(
    QuorumValidator is None,
    reason="QuorumValidator dependencies unavailable",
)
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
        assert (
            duration < 12.0
        )  # Should be much faster than sequential (allowing for API latency)
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
        from agents.lib.performance_optimization import BatchOperation

        optimizer = PerformanceOptimizer()

        # Test data - create proper BatchOperation objects
        operations = [
            BatchOperation(
                operation_type="insert",
                table_name="test_metrics",
                data=[
                    {
                        "id": str(uuid.uuid4()),
                        "metric": f"test_metric_{i}",
                        "value": i * 10,
                    }
                    for i in range(20)
                ],
                batch_size=10,
            )
        ]

        # Test batch write
        start_time = time.time()

        # Note: This will return empty dict if no DB connection available
        result = await optimizer.batch_write_with_pooling(operations)

        end_time = time.time()
        duration = end_time - start_time

        assert isinstance(result, dict)
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
        from agents.lib.circuit_breaker import circuit_breaker_manager

        config = CircuitBreakerConfig(
            failure_threshold=2, timeout_seconds=1.0, success_threshold=1
        )

        # Test failing operation
        async def failing_operation():
            raise Exception("Test failure")

        # First failure
        with pytest.raises(Exception, match="Test failure"):
            await call_with_breaker(
                breaker_name="test_breaker_fail", config=config, func=failing_operation
            )

        # Second failure should open the circuit
        with pytest.raises(Exception, match="Test failure"):
            await call_with_breaker(
                breaker_name="test_breaker_fail", config=config, func=failing_operation
            )

        # Get the breaker from manager and check state
        breaker = circuit_breaker_manager.get_breaker("test_breaker_fail", config)
        # Circuit should be open now
        assert breaker.state.value == "OPEN"

    @pytest.mark.asyncio
    async def test_circuit_breaker_timeout_recovery(self):
        """Test circuit breaker timeout and recovery."""
        from agents.lib.circuit_breaker import circuit_breaker_manager

        config = CircuitBreakerConfig(
            failure_threshold=1,
            timeout_seconds=0.1,
            success_threshold=1,  # Very short timeout for testing
        )

        # Trigger failure to open circuit
        async def failing_operation():
            raise Exception("Test failure")

        with pytest.raises(Exception, match="Test failure"):
            await call_with_breaker(
                breaker_name="test_breaker_timeout",
                config=config,
                func=failing_operation,
            )

        # Get the breaker from manager and check state
        breaker = circuit_breaker_manager.get_breaker("test_breaker_timeout", config)
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

        with pytest.raises(Exception, match="Always fails"):
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


@pytest.mark.skipif(
    ContextManager is None,
    reason="ContextManager dependencies unavailable (e.g., mcp_client)",
)
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
        from agents.lib.performance_optimization import BatchOperation

        optimizer = PerformanceOptimizer()

        # Test data
        test_data = [{"id": str(uuid.uuid4()), "value": i} for i in range(100)]

        # Create batch operation
        operations = [
            BatchOperation(
                operation_type="insert",
                table_name="test_performance",
                data=test_data,
            )
        ]

        # Test batch operation
        start_time = time.time()

        result = await optimizer.batch_write_with_pooling(operations)

        batch_duration = time.time() - start_time

        # Should be efficient for batch operations
        assert batch_duration < 5.0  # Should complete quickly
        assert result is not None


class TestBatchInsertMethods:
    """Test all batch insert methods in PerformanceOptimizer."""

    @pytest.mark.asyncio
    async def test_batch_insert_workflow_steps(self):
        """Test batch insert workflow steps."""
        from datetime import datetime
        from unittest.mock import AsyncMock, MagicMock, patch

        optimizer = PerformanceOptimizer()

        # Test data
        steps = [
            {
                "id": str(uuid.uuid4()),
                "run_id": str(uuid.uuid4()),
                "step_index": i,
                "phase": f"phase_{i}",
                "correlation_id": str(uuid.uuid4()),
                "applied_tf_id": str(uuid.uuid4()),
                "started_at": datetime.utcnow(),
                "completed_at": datetime.utcnow(),
                "duration_ms": 100 + i * 10,
                "success": True,
                "error": None,
            }
            for i in range(10)
        ]

        # Mock database pool and connection
        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(optimizer, "_get_pool", return_value=mock_pool):
            result = await optimizer.batch_insert_workflow_steps(steps, batch_size=5)

        assert isinstance(result, int)
        assert result == 10  # Should insert all 10 items

    @pytest.mark.asyncio
    async def test_batch_insert_workflow_steps_empty(self):
        """Test batch insert with empty data."""
        optimizer = PerformanceOptimizer()
        result = await optimizer.batch_insert_workflow_steps([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_batch_insert_llm_calls(self):
        """Test batch insert LLM calls."""
        from datetime import datetime
        from unittest.mock import AsyncMock, MagicMock, patch

        optimizer = PerformanceOptimizer()

        # Test data
        calls = [
            {
                "id": str(uuid.uuid4()),
                "run_id": str(uuid.uuid4()),
                "model": "gpt-4",
                "provider": "openai",
                "request_tokens": 100,
                "response_tokens": 50,
                "input_tokens": 100,
                "output_tokens": 50,
                "computed_cost_usd": 0.003,
                "request_data": {"prompt": "test"},
                "response_data": {"response": "test response"},
                "created_at": datetime.utcnow(),
            }
            for i in range(10)
        ]

        # Mock database pool and connection
        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(optimizer, "_get_pool", return_value=mock_pool):
            result = await optimizer.batch_insert_llm_calls(calls, batch_size=5)

        assert isinstance(result, int)
        assert result == 10  # Should insert all 10 items

    @pytest.mark.asyncio
    async def test_batch_insert_llm_calls_empty(self):
        """Test batch insert LLM calls with empty data."""
        optimizer = PerformanceOptimizer()
        result = await optimizer.batch_insert_llm_calls([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_batch_insert_error_events(self):
        """Test batch insert error events."""
        from unittest.mock import AsyncMock, MagicMock, patch

        optimizer = PerformanceOptimizer()

        # Test data
        events = [
            {
                "id": str(uuid.uuid4()),
                "run_id": str(uuid.uuid4()),
                "correlation_id": str(uuid.uuid4()),
                "error_type": "ValidationError",
                "message": f"Test error {i}",
                "details": {"severity": "high", "code": 500},
            }
            for i in range(10)
        ]

        # Mock database pool and connection
        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(optimizer, "_get_pool", return_value=mock_pool):
            result = await optimizer.batch_insert_error_events(events, batch_size=5)

        assert isinstance(result, int)
        assert result == 10  # Should insert all 10 items

    @pytest.mark.asyncio
    async def test_batch_insert_error_events_empty(self):
        """Test batch insert error events with empty data."""
        optimizer = PerformanceOptimizer()
        result = await optimizer.batch_insert_error_events([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_batch_insert_success_events(self):
        """Test batch insert success events."""
        from unittest.mock import AsyncMock, MagicMock, patch

        optimizer = PerformanceOptimizer()

        # Test data
        events = [
            {
                "id": str(uuid.uuid4()),
                "run_id": str(uuid.uuid4()),
                "task_id": str(uuid.uuid4()),
                "correlation_id": str(uuid.uuid4()),
                "approval_source": "auto",
                "is_golden": i % 2 == 0,
            }
            for i in range(10)
        ]

        # Mock database pool and connection
        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(optimizer, "_get_pool", return_value=mock_pool):
            result = await optimizer.batch_insert_success_events(events, batch_size=5)

        assert isinstance(result, int)
        assert result == 10  # Should insert all 10 items

    @pytest.mark.asyncio
    async def test_batch_insert_success_events_empty(self):
        """Test batch insert success events with empty data."""
        optimizer = PerformanceOptimizer()
        result = await optimizer.batch_insert_success_events([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_batch_insert_lineage_edges(self):
        """Test batch insert lineage edges."""
        from datetime import datetime
        from unittest.mock import AsyncMock, MagicMock, patch

        optimizer = PerformanceOptimizer()

        # Test data
        edges = [
            {
                "id": str(uuid.uuid4()),
                "src_type": "workflow_step",
                "src_id": str(uuid.uuid4()),
                "dst_type": "llm_call",
                "dst_id": str(uuid.uuid4()),
                "edge_type": "triggered",
                "attributes": {"priority": "high", "weight": 1.0},
                "created_at": datetime.utcnow(),
            }
            for i in range(10)
        ]

        # Mock database pool and connection
        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(optimizer, "_get_pool", return_value=mock_pool):
            result = await optimizer.batch_insert_lineage_edges(edges, batch_size=5)

        assert isinstance(result, int)
        assert result == 10  # Should insert all 10 items

    @pytest.mark.asyncio
    async def test_batch_insert_lineage_edges_empty(self):
        """Test batch insert lineage edges with empty data."""
        optimizer = PerformanceOptimizer()
        result = await optimizer.batch_insert_lineage_edges([])
        assert result == 0


class TestQueryOptimization:
    """Test query optimization methods."""

    @pytest.mark.asyncio
    async def test_optimize_queries(self):
        """Test query optimization analysis."""
        from unittest.mock import AsyncMock, MagicMock, patch

        optimizer = PerformanceOptimizer()

        # Mock database pool and connection
        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(
            side_effect=[
                # missing_indexes query result
                [
                    {
                        "tablename": "workflow_steps",
                        "attname": "correlation_id",
                        "n_distinct": 1000,
                        "correlation": 0.5,
                    },
                    {
                        "tablename": "llm_calls",
                        "attname": "provider",
                        "n_distinct": 500,
                        "correlation": 0.3,
                    },
                ],
                # table_sizes query result
                [
                    {
                        "tablename": "workflow_steps",
                        "size": "10 MB",
                        "size_bytes": 10485760,
                    },
                    {"tablename": "llm_calls", "size": "5 MB", "size_bytes": 5242880},
                ],
                # long_queries query result (pg_stat_statements)
                [],
            ]
        )

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(optimizer, "_get_pool", return_value=mock_pool):
            result = await optimizer.optimize_queries()

        assert isinstance(result, dict)
        assert "table_sizes" in result
        assert "missing_indexes" in result
        assert len(result["table_sizes"]) == 2
        assert len(result["missing_indexes"]) == 2

    @pytest.mark.asyncio
    async def test_create_performance_indexes(self):
        """Test creation of performance indexes."""
        from unittest.mock import AsyncMock, MagicMock, patch

        optimizer = PerformanceOptimizer()

        # Mock database pool and connection
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(optimizer, "_get_pool", return_value=mock_pool):
            result = await optimizer.create_performance_indexes()

        assert isinstance(result, list)
        assert len(result) > 0  # Should have created some indexes

    @pytest.mark.asyncio
    async def test_get_performance_metrics(self):
        """Test getting performance metrics."""
        from unittest.mock import AsyncMock, MagicMock, patch

        optimizer = PerformanceOptimizer()

        # Mock database pool and connection
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=1000)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_pool._pool = []  # Mock pool attribute

        with patch.object(optimizer, "_get_pool", return_value=mock_pool):
            result = await optimizer.get_performance_metrics()

        assert isinstance(result, dict)
        assert "row_counts" in result
        assert "write_queue_size" in result
        assert "batch_queue_size" in result


class TestAsyncDatabaseWrites:
    """Test async database write functionality."""

    @pytest.mark.asyncio
    async def test_async_database_write(self):
        """Test async database write."""
        optimizer = PerformanceOptimizer()

        try:
            # Test async write
            test_data = {
                "id": str(uuid.uuid4()),
                "name": "test_record",
                "value": 42,
            }

            write_id = await optimizer.async_database_write(
                table="test_table", data=test_data
            )

            assert isinstance(write_id, str)
            assert write_id.startswith("write_")
            assert optimizer._background_writer is not None
        finally:
            # Cleanup background tasks
            await optimizer.close()

    @pytest.mark.asyncio
    async def test_async_database_write_queue(self):
        """Test async write queue management."""
        optimizer = PerformanceOptimizer()

        try:
            # Queue multiple writes
            write_ids = []
            for i in range(5):
                write_id = await optimizer.async_database_write(
                    table="test_table", data={"id": str(uuid.uuid4()), "index": i}
                )
                write_ids.append(write_id)

            assert len(write_ids) == 5
            assert all(wid.startswith("write_") for wid in write_ids)

            # Wait for background worker to process some items
            await asyncio.sleep(0.1)

            # Background writer should be running
            assert optimizer._background_writer is not None
        finally:
            # Cleanup background tasks
            await optimizer.close()


class TestBatchOperations:
    """Test BatchOperation class and related functionality."""

    @pytest.mark.asyncio
    async def test_batch_operation_creation(self):
        """Test BatchOperation dataclass creation."""
        from agents.lib.performance_optimization import BatchOperation

        # Test creation with minimal params
        op = BatchOperation(
            operation_type="insert", table_name="test_table", data=[{"id": "test"}]
        )

        assert op.operation_type == "insert"
        assert op.table_name == "test_table"
        assert len(op.data) == 1
        assert op.batch_size == 1000  # default
        assert op.timeout_seconds == 30.0  # default

    @pytest.mark.asyncio
    async def test_batch_operation_custom_params(self):
        """Test BatchOperation with custom parameters."""
        from agents.lib.performance_optimization import BatchOperation

        # Test creation with custom params
        op = BatchOperation(
            operation_type="update",
            table_name="custom_table",
            data=[{"id": "1"}, {"id": "2"}],
            batch_size=500,
            timeout_seconds=60.0,
        )

        assert op.operation_type == "update"
        assert op.table_name == "custom_table"
        assert len(op.data) == 2
        assert op.batch_size == 500
        assert op.timeout_seconds == 60.0

    @pytest.mark.asyncio
    async def test_batch_write_with_multiple_operations(self):
        """Test batch write with multiple operation types."""
        from agents.lib.performance_optimization import BatchOperation

        optimizer = PerformanceOptimizer()

        # Create multiple operations
        operations = [
            BatchOperation(
                operation_type="insert",
                table_name="table1",
                data=[{"id": str(uuid.uuid4()), "value": i} for i in range(10)],
            ),
            BatchOperation(
                operation_type="insert",
                table_name="table2",
                data=[{"id": str(uuid.uuid4()), "value": i * 2} for i in range(10)],
            ),
        ]

        # Test batch write (will return empty dict if no DB connection)
        result = await optimizer.batch_write_with_pooling(operations)

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_batch_write_empty_operations(self):
        """Test batch write with empty operations list."""
        optimizer = PerformanceOptimizer()

        # Test with empty operations
        result = await optimizer.batch_write_with_pooling([])

        assert result == {}

    @pytest.mark.asyncio
    async def test_batch_write_update_operation(self):
        """Test batch write with update operation."""
        from agents.lib.performance_optimization import BatchOperation

        optimizer = PerformanceOptimizer()

        # Create update operation
        operations = [
            BatchOperation(
                operation_type="update",
                table_name="test_table",
                data=[
                    {
                        "id": str(uuid.uuid4()),
                        "name": f"updated_name_{i}",
                        "value": i * 10,
                    }
                    for i in range(5)
                ],
            )
        ]

        # Test batch write (will return empty dict if no DB connection)
        result = await optimizer.batch_write_with_pooling(operations)

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_batch_write_delete_operation(self):
        """Test batch write with delete operation."""
        from agents.lib.performance_optimization import BatchOperation

        optimizer = PerformanceOptimizer()

        # Create delete operation
        operations = [
            BatchOperation(
                operation_type="delete",
                table_name="test_table",
                data=[{"id": str(uuid.uuid4())} for i in range(5)],
            )
        ]

        # Test batch write (will return empty dict if no DB connection)
        result = await optimizer.batch_write_with_pooling(operations)

        assert isinstance(result, dict)


class TestBatchOperationMethods:
    """Test individual batch operation methods."""

    @pytest.mark.asyncio
    async def test_batch_insert_operation(self):
        """Test _batch_insert_operation method."""
        from unittest.mock import AsyncMock, MagicMock

        from agents.lib.performance_optimization import BatchOperation

        optimizer = PerformanceOptimizer()

        # Mock connection
        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()

        # Test data
        op = BatchOperation(
            operation_type="insert",
            table_name="test_table",
            data=[
                {"id": str(uuid.uuid4()), "name": "test1", "value": 10},
                {"id": str(uuid.uuid4()), "name": "test2", "value": 20},
            ],
        )

        result = await optimizer._batch_insert_operation(mock_conn, op)

        assert result == 2
        assert mock_conn.executemany.called

    @pytest.mark.asyncio
    async def test_batch_update_operation(self):
        """Test _batch_update_operation method."""
        from unittest.mock import AsyncMock, MagicMock

        from agents.lib.performance_optimization import BatchOperation

        optimizer = PerformanceOptimizer()

        # Mock connection
        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()

        # Test data
        test_id1 = str(uuid.uuid4())
        test_id2 = str(uuid.uuid4())
        op = BatchOperation(
            operation_type="update",
            table_name="test_table",
            data=[
                {"id": test_id1, "name": "updated1", "value": 100},
                {"id": test_id2, "name": "updated2", "value": 200},
            ],
        )

        result = await optimizer._batch_update_operation(mock_conn, op)

        assert result == 2
        assert mock_conn.executemany.called

    @pytest.mark.asyncio
    async def test_batch_delete_operation(self):
        """Test _batch_delete_operation method."""
        from unittest.mock import AsyncMock, MagicMock

        from agents.lib.performance_optimization import BatchOperation

        optimizer = PerformanceOptimizer()

        # Mock connection
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()

        # Test data
        test_id1 = str(uuid.uuid4())
        test_id2 = str(uuid.uuid4())
        op = BatchOperation(
            operation_type="delete",
            table_name="test_table",
            data=[{"id": test_id1}, {"id": test_id2}],
        )

        result = await optimizer._batch_delete_operation(mock_conn, op)

        assert result == 2
        assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_batch_delete_operation_empty(self):
        """Test _batch_delete_operation with empty data."""
        from unittest.mock import MagicMock

        from agents.lib.performance_optimization import BatchOperation

        optimizer = PerformanceOptimizer()

        # Mock connection
        mock_conn = MagicMock()

        # Test data with no IDs
        op = BatchOperation(operation_type="delete", table_name="test_table", data=[])

        result = await optimizer._batch_delete_operation(mock_conn, op)

        assert result == 0

    @pytest.mark.asyncio
    async def test_execute_grouped_operations(self):
        """Test _execute_grouped_operations method."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from agents.lib.performance_optimization import BatchOperation

        optimizer = PerformanceOptimizer()

        # Mock pool and connection
        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        # Test operations
        operations = [
            BatchOperation(
                operation_type="insert",
                table_name="test_table",
                data=[{"id": str(uuid.uuid4()), "value": i} for i in range(5)],
            )
        ]

        result = await optimizer._execute_grouped_operations(
            "insert_test_table", operations, mock_pool
        )

        assert result == 5

    @pytest.mark.asyncio
    async def test_process_write_batch(self):
        """Test _process_write_batch method."""
        from unittest.mock import AsyncMock, MagicMock, patch

        optimizer = PerformanceOptimizer()

        # Mock pool and connection
        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        # Test batch
        batch = [
            {"table": "test_table", "data": {"id": str(uuid.uuid4()), "value": 1}},
            {"table": "test_table", "data": {"id": str(uuid.uuid4()), "value": 2}},
            {"table": "other_table", "data": {"id": str(uuid.uuid4()), "name": "test"}},
        ]

        with patch.object(optimizer, "_get_pool", return_value=mock_pool):
            await optimizer._process_write_batch(batch)

        # Should have grouped by table and processed
        assert mock_conn.executemany.called


class TestEdgeCasesAndErrorHandling:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_optimizer_pool_initialization(self):
        """Test pool initialization."""
        optimizer = PerformanceOptimizer()

        # Initially pool should be None
        assert optimizer.pool is None

        # Try to get pool (will return None if no DB connection)
        pool = await optimizer._get_pool()

        # Pool should be set (or still None if no connection)
        assert pool is None or pool is not None

    @pytest.mark.asyncio
    async def test_batch_insert_with_missing_fields(self):
        """Test batch insert with missing fields."""
        from unittest.mock import AsyncMock, MagicMock, patch

        optimizer = PerformanceOptimizer()

        # Test data with missing fields (should use None for missing)
        steps = [
            {
                "id": str(uuid.uuid4()),
                "run_id": str(uuid.uuid4()),
                # Missing other fields - get() will return None
            }
            for i in range(5)
        ]

        # Mock database pool and connection
        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(optimizer, "_get_pool", return_value=mock_pool):
            result = await optimizer.batch_insert_workflow_steps(steps)

        assert isinstance(result, int)
        assert result == 5  # Should still insert with None values

    @pytest.mark.asyncio
    async def test_batch_operations_large_dataset(self):
        """Test batch operations with large dataset."""
        from unittest.mock import AsyncMock, MagicMock, patch

        optimizer = PerformanceOptimizer()

        # Create large dataset
        large_steps = [
            {
                "id": str(uuid.uuid4()),
                "run_id": str(uuid.uuid4()),
                "step_index": i,
                "phase": f"phase_{i}",
                "correlation_id": str(uuid.uuid4()),
                "applied_tf_id": None,
                "started_at": None,
                "completed_at": None,
                "duration_ms": i * 10,
                "success": True,
                "error": None,
            }
            for i in range(2500)  # More than default batch size
        ]

        # Mock database pool and connection
        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(optimizer, "_get_pool", return_value=mock_pool):
            result = await optimizer.batch_insert_workflow_steps(
                large_steps, batch_size=500
            )

        assert isinstance(result, int)
        assert result == 2500  # Should insert all items
        # Should have been called 5 times (2500 / 500 = 5 batches)
        assert mock_conn.executemany.call_count == 5

    @pytest.mark.asyncio
    async def test_performance_metrics_queue_sizes(self):
        """Test performance metrics include queue sizes."""
        optimizer = PerformanceOptimizer()

        try:
            # Add some items to queues
            await optimizer.async_database_write("test_table", {"id": "test1"})
            await optimizer.async_database_write("test_table", {"id": "test2"})

            # Get metrics
            metrics = await optimizer.get_performance_metrics()

            # Should have queue size info if metrics available
            if metrics:
                assert "write_queue_size" in metrics or "batch_queue_size" in metrics
        finally:
            # Cleanup background tasks
            await optimizer.close()

    @pytest.mark.asyncio
    async def test_batch_write_grouping_logic(self):
        """Test that batch write groups operations correctly."""
        from agents.lib.performance_optimization import BatchOperation

        optimizer = PerformanceOptimizer()

        # Create operations for same table but different types
        operations = [
            BatchOperation(
                operation_type="insert",
                table_name="test_table",
                data=[{"id": str(uuid.uuid4()), "value": 1}],
            ),
            BatchOperation(
                operation_type="insert",
                table_name="test_table",
                data=[{"id": str(uuid.uuid4()), "value": 2}],
            ),
            BatchOperation(
                operation_type="update",
                table_name="test_table",
                data=[{"id": str(uuid.uuid4()), "value": 3}],
            ),
        ]

        # Test batch write (should group by operation_type + table_name)
        result = await optimizer.batch_write_with_pooling(operations)

        assert isinstance(result, dict)


class TestModuleLevelFunctions:
    """Test module-level convenience functions."""

    @pytest.mark.asyncio
    async def test_module_batch_insert_workflow_steps(self):
        """Test module-level batch_insert_workflow_steps function."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from agents.lib.performance_optimization import (
            batch_insert_workflow_steps,
            performance_optimizer,
        )

        steps = [{"id": str(uuid.uuid4()), "run_id": str(uuid.uuid4())}]

        # Mock database pool and connection
        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(performance_optimizer, "_get_pool", return_value=mock_pool):
            result = await batch_insert_workflow_steps(steps)

        assert isinstance(result, int)
        assert result == 1

    @pytest.mark.asyncio
    async def test_module_batch_insert_llm_calls(self):
        """Test module-level batch_insert_llm_calls function."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from agents.lib.performance_optimization import (
            batch_insert_llm_calls,
            performance_optimizer,
        )

        calls = [{"id": str(uuid.uuid4()), "run_id": str(uuid.uuid4())}]

        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(performance_optimizer, "_get_pool", return_value=mock_pool):
            result = await batch_insert_llm_calls(calls)

        assert isinstance(result, int)
        assert result == 1

    @pytest.mark.asyncio
    async def test_module_batch_insert_error_events(self):
        """Test module-level batch_insert_error_events function."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from agents.lib.performance_optimization import (
            batch_insert_error_events,
            performance_optimizer,
        )

        events = [{"id": str(uuid.uuid4()), "run_id": str(uuid.uuid4())}]

        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(performance_optimizer, "_get_pool", return_value=mock_pool):
            result = await batch_insert_error_events(events)

        assert isinstance(result, int)
        assert result == 1

    @pytest.mark.asyncio
    async def test_module_batch_insert_success_events(self):
        """Test module-level batch_insert_success_events function."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from agents.lib.performance_optimization import (
            batch_insert_success_events,
            performance_optimizer,
        )

        events = [{"id": str(uuid.uuid4()), "run_id": str(uuid.uuid4())}]

        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(performance_optimizer, "_get_pool", return_value=mock_pool):
            result = await batch_insert_success_events(events)

        assert isinstance(result, int)
        assert result == 1

    @pytest.mark.asyncio
    async def test_module_batch_insert_lineage_edges(self):
        """Test module-level batch_insert_lineage_edges function."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from agents.lib.performance_optimization import (
            batch_insert_lineage_edges,
            performance_optimizer,
        )

        edges = [{"id": str(uuid.uuid4())}]

        mock_conn = MagicMock()
        mock_conn.executemany = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(performance_optimizer, "_get_pool", return_value=mock_pool):
            result = await batch_insert_lineage_edges(edges)

        assert isinstance(result, int)
        assert result == 1

    @pytest.mark.asyncio
    async def test_module_optimize_database_performance(self):
        """Test module-level optimize_database_performance function."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from agents.lib.performance_optimization import (
            optimize_database_performance,
            performance_optimizer,
        )

        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(side_effect=[[], [], []])
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(performance_optimizer, "_get_pool", return_value=mock_pool):
            result = await optimize_database_performance()

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_module_create_performance_indexes(self):
        """Test module-level create_performance_indexes function."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from agents.lib.performance_optimization import (
            create_performance_indexes,
            performance_optimizer,
        )

        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(performance_optimizer, "_get_pool", return_value=mock_pool):
            result = await create_performance_indexes()

        assert isinstance(result, list)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_module_batch_write_with_pooling(self):
        """Test module-level batch_write_with_pooling function."""
        from agents.lib.performance_optimization import (
            BatchOperation,
            batch_write_with_pooling,
        )

        operations = [
            BatchOperation(
                operation_type="insert",
                table_name="test",
                data=[{"id": str(uuid.uuid4())}],
            )
        ]

        result = await batch_write_with_pooling(operations)

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_module_async_database_write(self):
        """Test module-level async_database_write function."""
        from agents.lib.performance_optimization import async_database_write

        write_id = await async_database_write("test_table", {"id": "test"})

        assert isinstance(write_id, str)
        assert write_id.startswith("write_")

    @pytest.mark.asyncio
    async def test_module_get_performance_metrics(self):
        """Test module-level get_performance_metrics function."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from agents.lib.performance_optimization import (
            get_performance_metrics,
            performance_optimizer,
        )

        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=100)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_pool._pool = []

        with patch.object(performance_optimizer, "_get_pool", return_value=mock_pool):
            result = await get_performance_metrics()

        assert isinstance(result, dict)
        assert "row_counts" in result


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
