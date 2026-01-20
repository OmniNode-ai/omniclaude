"""
Performance Benchmark and Improvement Measurement

Measures the performance gains from implemented optimizations:
- Parallel RAG queries vs sequential
- Parallel model calls vs sequential
- Batch database operations vs individual
- Circuit breaker effectiveness
- Retry manager efficiency
- Context optimization impact
- Agent analytics performance
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents.lib.input_validator import ValidationResult

from agents.lib.agent_analytics import AgentAnalytics, track_agent_performance
from agents.lib.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    call_with_breaker,
)
from agents.lib.context_optimizer import ContextOptimizer
from agents.lib.input_validator import InputValidator
from agents.lib.performance_monitor import PerformanceMonitor
from agents.lib.performance_optimization import BatchOperation, PerformanceOptimizer
from agents.lib.retry_manager import RetryConfig, RetryManager, execute_with_retry
from agents.parallel_execution.context_manager import ContextManager
from agents.parallel_execution.quorum_validator import (
    QuorumResult,
    QuorumValidator,
    ValidationDecision,
)


class PerformanceBenchmark:
    """Comprehensive performance benchmarking for all optimizations."""

    def __init__(self):
        self.results = {}
        self.context_manager = ContextManager()
        self.quorum_validator = QuorumValidator()
        self.performance_optimizer = PerformanceOptimizer()
        self.circuit_breaker = CircuitBreaker(
            "benchmark_breaker", CircuitBreakerConfig()
        )
        self.retry_manager = RetryManager()
        self.performance_monitor = PerformanceMonitor()
        self.input_validator = InputValidator()
        self.context_optimizer = ContextOptimizer()
        self.agent_analytics = AgentAnalytics()

    async def benchmark_parallel_rag_queries(self) -> dict[str, Any]:
        """Benchmark parallel vs sequential RAG queries."""
        print("Benchmarking parallel RAG queries...")

        rag_queries = [
            "python fibonacci algorithm",
            "recursive function implementation",
            "dynamic programming optimization",
            "memoization techniques",
            "time complexity analysis",
        ]

        # Test parallel execution
        start_time = time.time()
        parallel_context = await self.context_manager.gather_global_context(
            user_prompt="Generate a Python function to calculate fibonacci numbers",
            rag_queries=rag_queries,
            max_rag_results=5,
        )
        parallel_duration = time.time() - start_time

        # Test sequential execution (simulated)
        start_time = time.time()
        sequential_context = await self._simulate_sequential_rag(rag_queries)
        sequential_duration = time.time() - start_time

        improvement = (
            (sequential_duration - parallel_duration) / sequential_duration
        ) * 100

        return {
            "parallel_duration": parallel_duration,
            "sequential_duration": sequential_duration,
            "improvement_percent": improvement,
            "speedup_factor": sequential_duration / parallel_duration,
            "context_items_parallel": len(parallel_context),
            "context_items_sequential": len(sequential_context),
        }

    async def _simulate_sequential_rag(self, rag_queries: list[str]) -> dict[str, Any]:
        """Simulate sequential RAG query execution."""
        context_items = {}

        for query in rag_queries:
            # Simulate RAG query delay
            await asyncio.sleep(0.1)
            context_items[f"sequential_{query}"] = {
                "content": f"Sequential result for {query}",
                "relevance": 0.8,
                "source": "sequential_rag",
            }

        return context_items

    async def benchmark_parallel_model_calls(self) -> dict[str, Any]:
        """Benchmark parallel vs sequential model calls."""
        print("Benchmarking parallel model calls...")

        task_breakdown = {
            "tasks": [
                {
                    "id": "task1",
                    "description": "Generate fibonacci function",
                    "input_data": {"node_type": "code_generation"},
                }
            ]
        }

        # Test parallel execution
        start_time = time.time()
        parallel_result = await self.quorum_validator.validate_intent(
            user_prompt="Generate a Python function to calculate fibonacci numbers",
            task_breakdown=task_breakdown,
        )
        parallel_duration = time.time() - start_time

        # Test sequential execution (simulated)
        start_time = time.time()
        sequential_result = await self._simulate_sequential_models()
        sequential_duration = time.time() - start_time

        improvement = (
            (sequential_duration - parallel_duration) / sequential_duration
        ) * 100

        return {
            "parallel_duration": parallel_duration,
            "sequential_duration": sequential_duration,
            "improvement_percent": improvement,
            "speedup_factor": sequential_duration / parallel_duration,
            "parallel_decision": parallel_result.decision.value,
            "sequential_decision": sequential_result.decision.value,
        }

    async def _simulate_sequential_models(self) -> QuorumResult:
        """Simulate sequential model calls."""
        # Simulate calling models one by one
        await asyncio.sleep(0.2)  # Simulate model call delay

        return QuorumResult(
            decision=ValidationDecision.PASS,
            confidence=0.8,
            deficiencies=[],
            scores={"model1": 0.8, "model2": 0.7, "model3": 0.9},
            model_responses=[],
        )

    async def benchmark_batch_database_operations(self) -> dict[str, Any]:
        """Benchmark batch vs individual database operations."""
        print("Benchmarking batch database operations...")

        # Test data
        test_data = [
            {
                "id": str(uuid.uuid4()),
                "value": i,
                "timestamp": datetime.now().isoformat(),
            }
            for i in range(100)
        ]

        # Test batch operation
        start_time = time.time()
        batch_op = BatchOperation(
            operation_type="insert",
            table_name="benchmark_test",
            data=test_data,
        )
        await self.performance_optimizer.batch_write_with_pooling([batch_op])
        batch_duration = time.time() - start_time

        # Test individual operations (simulated)
        start_time = time.time()
        await self._simulate_individual_operations(test_data)
        individual_duration = time.time() - start_time

        improvement = (
            (individual_duration - batch_duration) / individual_duration
        ) * 100

        return {
            "batch_duration": batch_duration,
            "individual_duration": individual_duration,
            "improvement_percent": improvement,
            "speedup_factor": individual_duration / batch_duration,
            "records_processed": len(test_data),
            "batch_efficiency": len(test_data) / batch_duration,
        }

    async def _simulate_individual_operations(
        self, test_data: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Simulate individual database operations."""
        results = []

        for record in test_data:
            # Simulate individual insert delay
            await asyncio.sleep(0.001)
            results.append({"id": record["id"], "status": "inserted"})

        return {"results": results, "count": len(results)}

    async def benchmark_circuit_breaker_effectiveness(self) -> dict[str, Any]:
        """Benchmark circuit breaker effectiveness."""
        print("Benchmarking circuit breaker effectiveness...")

        config = CircuitBreakerConfig(
            failure_threshold=3, timeout_seconds=1.0, success_threshold=2
        )

        # Test with failing service
        failure_count = 0

        async def failing_service():
            nonlocal failure_count
            failure_count += 1
            raise Exception(f"Service failure {failure_count}")

        start_time = time.time()

        # Test circuit breaker with failing service
        try:
            await call_with_breaker(
                breaker_name="benchmark_breaker", config=config, func=failing_service
            )
        except Exception:
            pass  # Expected to fail

        circuit_breaker_duration = time.time() - start_time

        # Test without circuit breaker (would keep trying)
        start_time = time.time()

        try:
            for _ in range(10):  # Simulate 10 attempts without circuit breaker
                try:
                    await failing_service()
                except Exception:
                    pass  # nosec B110 - intentional: benchmark measures failure handling overhead
        except Exception:
            pass  # nosec B110 - intentional: benchmark wrapper catches all for timing

        no_circuit_breaker_duration = time.time() - start_time

        improvement = (
            (no_circuit_breaker_duration - circuit_breaker_duration)
            / no_circuit_breaker_duration
        ) * 100

        return {
            "circuit_breaker_duration": circuit_breaker_duration,
            "no_circuit_breaker_duration": no_circuit_breaker_duration,
            "improvement_percent": improvement,
            "failure_count": failure_count,
            "circuit_breaker_efficiency": failure_count / circuit_breaker_duration,
        }

    async def benchmark_retry_manager_efficiency(self) -> dict[str, Any]:
        """Benchmark retry manager efficiency."""
        print("Benchmarking retry manager efficiency...")

        retry_config = RetryConfig(
            max_retries=5, base_delay=0.1, max_delay=1.0, backoff_multiplier=2.0
        )

        attempt_count = 0

        async def flaky_service():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise Exception(f"Service failure {attempt_count}")
            return f"Success on attempt {attempt_count}"

        # Test with retry manager
        start_time = time.time()

        result = await execute_with_retry(
            retry_manager=self.retry_manager, config=retry_config, func=flaky_service
        )

        retry_duration = time.time() - start_time

        # Test without retry manager (would fail immediately)
        start_time = time.time()

        try:
            await flaky_service()
        except Exception:
            pass  # Expected to fail

        no_retry_duration = time.time() - start_time

        return {
            "retry_duration": retry_duration,
            "no_retry_duration": no_retry_duration,
            "success_with_retry": result is not None,
            "attempts_made": attempt_count,
            "retry_efficiency": attempt_count / retry_duration,
        }

    async def benchmark_context_optimization(self) -> dict[str, Any]:
        """Benchmark context optimization impact."""
        print("Benchmarking context optimization...")

        # Test with optimization enabled
        start_time = time.time()

        optimized_context = await self.context_manager.gather_global_context(
            user_prompt="Generate a Python function to calculate fibonacci numbers",
            rag_queries=["python", "fibonacci", "algorithm"],
            max_rag_results=5,
            enable_optimization=True,
        )

        optimized_duration = time.time() - start_time

        # Test without optimization
        start_time = time.time()

        unoptimized_context = await self.context_manager.gather_global_context(
            user_prompt="Generate a Python function to calculate fibonacci numbers",
            rag_queries=["python", "fibonacci", "algorithm"],
            max_rag_results=5,
            enable_optimization=False,
        )

        unoptimized_duration = time.time() - start_time

        improvement = (
            (unoptimized_duration - optimized_duration) / unoptimized_duration
        ) * 100

        return {
            "optimized_duration": optimized_duration,
            "unoptimized_duration": unoptimized_duration,
            "improvement_percent": improvement,
            "speedup_factor": unoptimized_duration / optimized_duration,
            "optimized_context_items": len(optimized_context),
            "unoptimized_context_items": len(unoptimized_context),
        }

    async def benchmark_agent_analytics_performance(self) -> dict[str, Any]:
        """Benchmark agent analytics performance."""
        print("Benchmarking agent analytics performance...")

        # Test agent performance tracking
        run_id = str(uuid.uuid4())

        start_time = time.time()

        # Track multiple agent performances
        for i in range(10):
            await track_agent_performance(
                agent_id=f"agent_{i % 3}",
                task_type="code_generation",
                success=i % 4 != 0,  # 75% success rate
                duration_ms=1000 + (i * 100),
                run_id=run_id,
                metadata={"complexity": "high", "language": "python"},
            )

        tracking_duration = time.time() - start_time

        # Test analytics queries
        start_time = time.time()

        summary = await self.agent_analytics.get_agent_performance_summary(days=1)
        recommendations = await self.agent_analytics.get_agent_recommendations(
            task_type="code_generation", limit=3
        )

        analytics_duration = time.time() - start_time

        return {
            "tracking_duration": tracking_duration,
            "analytics_duration": analytics_duration,
            "total_duration": tracking_duration + analytics_duration,
            "agents_tracked": 10,
            "summary_available": summary is not None,
            "recommendations_count": len(recommendations),
            "tracking_efficiency": 10 / tracking_duration,
            "analytics_efficiency": 2 / analytics_duration,  # 2 queries
        }

    async def benchmark_input_validation_performance(self) -> dict[str, Any]:
        """Benchmark input validation performance."""
        print("Benchmarking input validation performance...")

        # Test data
        test_inputs = [
            {
                "user_prompt": "Generate a Python function to calculate fibonacci numbers",
                "tasks_data": {
                    "tasks": [
                        {
                            "id": f"task_{i}",
                            "description": f"Task {i} description",
                            "input_data": {"node_type": "code_generation"},
                        }
                    ]
                },
            }
            for i in range(50)
        ]

        # Test validation performance
        start_time = time.time()

        # validate_and_sanitize returns Union[ValidationResult, dict[str, Any]]
        # When called with user_prompt/tasks_data params, it returns dict with 'is_valid' key
        # When called with user_input/input_type params, it returns ValidationResult
        validation_results: list[dict[str, Any]] = []
        for test_input in test_inputs:
            user_prompt_str = str(test_input["user_prompt"])
            tasks_data_dict = test_input["tasks_data"]
            # Using user_prompt/tasks_data pattern - returns dict[str, Any]
            result: dict[str, Any] | ValidationResult = (
                await self.input_validator.validate_and_sanitize(
                    user_prompt=user_prompt_str,
                    tasks_data=(
                        tasks_data_dict if isinstance(tasks_data_dict, dict) else None
                    ),
                )
            )
            # When using user_prompt/tasks_data, returns dict with 'is_valid' key
            if isinstance(result, dict):
                validation_results.append(result)
            else:
                # Handle ValidationResult case (returned when using user_input/input_type)
                validation_results.append(
                    {
                        "is_valid": result.is_valid,
                        "errors": result.errors,
                    }
                )

        validation_duration = time.time() - start_time

        # Calculate statistics
        valid_count = sum(
            1 for result in validation_results if result.get("is_valid", False)
        )
        invalid_count = len(validation_results) - valid_count

        return {
            "validation_duration": validation_duration,
            "inputs_processed": len(test_inputs),
            "valid_inputs": valid_count,
            "invalid_inputs": invalid_count,
            "validation_rate": len(test_inputs) / validation_duration,
            "success_rate": valid_count / len(test_inputs),
        }

    async def run_comprehensive_benchmark(self) -> dict[str, Any]:
        """Run comprehensive benchmark of all optimizations."""
        print("Running comprehensive performance benchmark...")
        print("=" * 60)

        start_time = time.time()

        # Run all benchmarks
        benchmarks = {
            "parallel_rag_queries": await self.benchmark_parallel_rag_queries(),
            "parallel_model_calls": await self.benchmark_parallel_model_calls(),
            "batch_database_operations": await self.benchmark_batch_database_operations(),
            "circuit_breaker_effectiveness": await self.benchmark_circuit_breaker_effectiveness(),
            "retry_manager_efficiency": await self.benchmark_retry_manager_efficiency(),
            "context_optimization": await self.benchmark_context_optimization(),
            "agent_analytics_performance": await self.benchmark_agent_analytics_performance(),
            "input_validation_performance": await self.benchmark_input_validation_performance(),
        }

        total_duration = time.time() - start_time

        # Calculate overall statistics
        total_improvements = []
        for benchmark_name, results in benchmarks.items():
            if "improvement_percent" in results:
                total_improvements.append(results["improvement_percent"])

        avg_improvement = (
            sum(total_improvements) / len(total_improvements)
            if total_improvements
            else 0
        )

        # Generate summary
        summary = {
            "benchmark_timestamp": datetime.now().isoformat(),
            "total_benchmark_duration": total_duration,
            "benchmarks": benchmarks,
            "overall_statistics": {
                "average_improvement_percent": avg_improvement,
                "benchmarks_run": len(benchmarks),
                "total_improvements": len(total_improvements),
            },
        }

        return summary

    def print_benchmark_results(self, results: dict[str, Any]) -> None:
        """Print benchmark results in a formatted way."""
        print("\n" + "=" * 60)
        print("PERFORMANCE BENCHMARK RESULTS")
        print("=" * 60)

        print(f"Benchmark completed at: {results['benchmark_timestamp']}")
        print(
            f"Total benchmark duration: {results['total_benchmark_duration']:.2f} seconds"
        )
        print(
            f"Average improvement: {results['overall_statistics']['average_improvement_percent']:.1f}%"
        )
        print()

        for benchmark_name, benchmark_results in results["benchmarks"].items():
            print(f"📊 {benchmark_name.replace('_', ' ').title()}")
            print("-" * 40)

            if "improvement_percent" in benchmark_results:
                print(f"  Improvement: {benchmark_results['improvement_percent']:.1f}%")
                print(f"  Speedup: {benchmark_results.get('speedup_factor', 1):.2f}x")

            if "parallel_duration" in benchmark_results:
                print(f"  Parallel: {benchmark_results['parallel_duration']:.3f}s")
                print(f"  Sequential: {benchmark_results['sequential_duration']:.3f}s")

            if "batch_duration" in benchmark_results:
                print(f"  Batch: {benchmark_results['batch_duration']:.3f}s")
                print(f"  Individual: {benchmark_results['individual_duration']:.3f}s")

            if "validation_duration" in benchmark_results:
                print(
                    f"  Validation rate: {benchmark_results['validation_rate']:.1f} inputs/sec"
                )
                print(f"  Success rate: {benchmark_results['success_rate']:.1%}")

            print()

        print("=" * 60)
        print("BENCHMARK COMPLETE")
        print("=" * 60)


async def main() -> None:
    """Main benchmark execution."""
    benchmark = PerformanceBenchmark()

    # Run comprehensive benchmark
    results = await benchmark.run_comprehensive_benchmark()

    # Print results
    benchmark.print_benchmark_results(results)

    # Save results to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"benchmark_results_{timestamp}.json"

    with open(filename, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\nResults saved to: {filename}")


if __name__ == "__main__":
    asyncio.run(main())
