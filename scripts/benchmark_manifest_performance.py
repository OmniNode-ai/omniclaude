#!/usr/bin/env python3
"""
Performance Benchmark Script - Manifest Generation with Relevance Scoring

Measures end-to-end manifest generation performance including:
1. Task classification time
2. Pattern query time (Qdrant)
3. Relevance scoring time
4. Schema query time
5. Infrastructure query time
6. Total end-to-end time

Tests with different prompt complexities and pattern counts to identify bottlenecks.

Performance Targets:
- Task classification: <5ms
- Relevance scoring: <10ms (150 patterns)
- Pattern query: <500ms
- Total end-to-end: <2000ms

Usage:
    python3 scripts/benchmark_manifest_performance.py

Requirements:
- PostgreSQL running with omninode_bridge database
- Qdrant running with code_patterns and execution_patterns collections
- Kafka/Redpanda running
- Environment variables configured in .env
"""

import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

# Load environment variables from .env file
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)
except ImportError:
    print(
        "⚠️  Warning: python-dotenv not installed. Using environment variables from shell."
    )
    print("   Install with: pip install python-dotenv")

# Add agents/lib to Python path for imports
agents_lib_path = Path(__file__).parent.parent / "agents" / "lib"
sys.path.insert(0, str(agents_lib_path))

# Add project root for config imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import required modules
from manifest_injector import ManifestInjector
from relevance_scorer import RelevanceScorer
from task_classifier import TaskClassifier, TaskContext

# Import Pydantic Settings for type-safe configuration
from config import settings


@dataclass
class BenchmarkResult:
    """Result from a single benchmark run."""

    prompt_type: str
    pattern_count: int
    task_classification_time_ms: float
    pattern_query_time_ms: float
    relevance_scoring_time_ms: float
    schema_query_time_ms: float
    infrastructure_query_time_ms: float
    total_time_ms: float
    patterns_retrieved: int
    patterns_after_filtering: int
    cache_hit: bool
    error: Optional[str] = None


@dataclass
class BenchmarkReport:
    """Aggregated benchmark report."""

    results: List[BenchmarkResult]
    summary: Dict[str, Any]


# Test prompts with different complexities
TEST_PROMPTS = {
    "simple": "Debug the database connection error",
    "medium": "Implement a new EFFECT node for user authentication with PostgreSQL persistence",
    "complex": (
        "Create a complete ONEX workflow with EFFECT, COMPUTE, and REDUCER nodes "
        "for processing agent routing decisions from Kafka, storing results in PostgreSQL, "
        "and publishing metrics to the event bus"
    ),
}


class PerformanceBenchmark:
    """Performance benchmark runner for manifest generation."""

    def __init__(self):
        """Initialize benchmark runner."""
        self.classifier = TaskClassifier()
        self.scorer = RelevanceScorer()
        self.results: List[BenchmarkResult] = []

        # Verify environment
        self._verify_environment()

    def _verify_environment(self) -> None:
        """Verify required configuration from Pydantic settings."""
        # Set QDRANT_URL in environment for legacy code compatibility
        if not os.environ.get("QDRANT_URL"):
            os.environ["QDRANT_URL"] = str(settings.qdrant_url)
            print(
                f"ℹ️  Using QDRANT_URL from Pydantic settings: {os.environ['QDRANT_URL']}"
            )

        # Validate required settings
        validation_errors = settings.validate_required_services()

        if validation_errors:
            print(f"❌ Configuration validation failed:")
            for error in validation_errors:
                print(f"   - {error}")
            print("\n   Available configuration:")
            print(f"      POSTGRES_HOST={settings.postgres_host}")
            print(f"      POSTGRES_PORT={settings.postgres_port}")
            print(f"      KAFKA_BOOTSTRAP_SERVERS={settings.kafka_bootstrap_servers}")
            print(f"      QDRANT_URL={settings.qdrant_url}")
            print("\n   Ensure .env file exists with proper configuration")
            print("   Or run: source .env")
            sys.exit(1)

        print("✅ Configuration validated from Pydantic settings")

    async def benchmark_task_classification(self, prompt: str) -> float:
        """
        Benchmark task classification performance.

        Args:
            prompt: User prompt to classify

        Returns:
            Classification time in milliseconds
        """
        start_time = time.perf_counter()
        self.classifier.classify(prompt)
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return elapsed_ms

    async def benchmark_relevance_scoring(
        self,
        patterns: List[Dict[str, Any]],
        task_context: TaskContext,
        user_prompt: str,
    ) -> float:
        """
        Benchmark relevance scoring performance.

        Args:
            patterns: List of patterns to score
            task_context: Classified task context
            user_prompt: User prompt

        Returns:
            Scoring time in milliseconds
        """
        start_time = time.perf_counter()

        for pattern in patterns:
            self.scorer.score_pattern_relevance(pattern, task_context, user_prompt)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return elapsed_ms

    async def benchmark_single_run(
        self,
        prompt: str,
        prompt_type: str,
        pattern_limit: int = 150,
        force_refresh: bool = False,
    ) -> BenchmarkResult:
        """
        Run a single benchmark iteration.

        Args:
            prompt: User prompt to test
            prompt_type: Type of prompt (simple/medium/complex)
            pattern_limit: Maximum patterns to retrieve
            force_refresh: Force refresh cache

        Returns:
            BenchmarkResult with detailed timing breakdown
        """
        correlation_id = str(uuid4())

        try:
            # 1. Benchmark task classification
            classification_start = time.perf_counter()
            task_context = self.classifier.classify(prompt)
            classification_time_ms = (time.perf_counter() - classification_start) * 1000

            # 2. Benchmark manifest generation with instrumentation
            async with ManifestInjector(enable_cache=not force_refresh) as injector:
                manifest_start = time.perf_counter()

                # Generate manifest
                manifest = await injector.generate_dynamic_manifest_async(
                    correlation_id=correlation_id,
                    user_prompt=prompt,
                    force_refresh=force_refresh,
                )

                total_time_ms = (time.perf_counter() - manifest_start) * 1000

                # Extract timing data from query_times
                query_times = injector._current_query_times or {}
                pattern_query_time_ms = query_times.get("patterns", 0)
                schema_query_time_ms = query_times.get("database_schemas", 0)
                infrastructure_query_time_ms = query_times.get("infrastructure", 0)

                # Get pattern counts
                patterns = manifest.get("patterns", {}).get("available", [])
                patterns_retrieved = len(patterns)

                # 3. Benchmark relevance scoring separately
                # (manifest_injector already applies scoring internally, but we measure it standalone)
                if patterns:
                    relevance_scoring_time_ms = await self.benchmark_relevance_scoring(
                        patterns, task_context, prompt
                    )
                else:
                    relevance_scoring_time_ms = 0

                # Count patterns after filtering (from manifest)
                # Note: The manifest_injector applies relevance filtering internally
                patterns_after_filtering = len(patterns)

                # Check if cache was hit
                cache_hit = pattern_query_time_ms < 50  # Cache hits are typically <50ms

                return BenchmarkResult(
                    prompt_type=prompt_type,
                    pattern_count=pattern_limit,
                    task_classification_time_ms=classification_time_ms,
                    pattern_query_time_ms=pattern_query_time_ms,
                    relevance_scoring_time_ms=relevance_scoring_time_ms,
                    schema_query_time_ms=schema_query_time_ms,
                    infrastructure_query_time_ms=infrastructure_query_time_ms,
                    total_time_ms=total_time_ms,
                    patterns_retrieved=patterns_retrieved,
                    patterns_after_filtering=patterns_after_filtering,
                    cache_hit=cache_hit,
                )

        except Exception as e:
            print(f"❌ Benchmark failed for {prompt_type}: {e}")
            return BenchmarkResult(
                prompt_type=prompt_type,
                pattern_count=pattern_limit,
                task_classification_time_ms=0,
                pattern_query_time_ms=0,
                relevance_scoring_time_ms=0,
                schema_query_time_ms=0,
                infrastructure_query_time_ms=0,
                total_time_ms=0,
                patterns_retrieved=0,
                patterns_after_filtering=0,
                cache_hit=False,
                error=str(e),
            )

    async def run_benchmark_suite(
        self,
        iterations: int = 3,
    ) -> BenchmarkReport:
        """
        Run complete benchmark suite.

        Tests:
        - 3 prompt complexities (simple, medium, complex)
        - Multiple iterations for statistical significance
        - Cache warmup + cache hit scenarios

        Args:
            iterations: Number of iterations per test case

        Returns:
            BenchmarkReport with aggregated results
        """
        print("\n" + "=" * 80)
        print("MANIFEST GENERATION PERFORMANCE BENCHMARK")
        print("=" * 80)
        print("\nTest Configuration:")
        print(f"  - Prompt types: {len(TEST_PROMPTS)}")
        print(f"  - Iterations per test: {iterations}")
        print(f"  - Total test runs: {len(TEST_PROMPTS) * iterations}")
        print("\n" + "-" * 80)

        results = []

        for prompt_type, prompt in TEST_PROMPTS.items():
            print(f"\n📝 Testing: {prompt_type.upper()} prompt")
            print(f"   Prompt: \"{prompt[:60]}{'...' if len(prompt) > 60 else ''}\"")

            # First run: Cache miss (force refresh)
            print("\n   Iteration 1 (cache miss)...")
            result = await self.benchmark_single_run(
                prompt=prompt,
                prompt_type=prompt_type,
                force_refresh=True,
            )
            results.append(result)
            self._print_result(result, iteration=1)

            # Subsequent runs: Cache hits
            for i in range(2, iterations + 1):
                print(f"\n   Iteration {i} (cache hit expected)...")
                result = await self.benchmark_single_run(
                    prompt=prompt,
                    prompt_type=prompt_type,
                    force_refresh=False,
                )
                results.append(result)
                self._print_result(result, iteration=i)

        # Generate report
        report = self._generate_report(results)

        return report

    def _print_result(self, result: BenchmarkResult, iteration: int) -> None:
        """Print single benchmark result."""
        if result.error:
            print(f"      ❌ Error: {result.error}")
            return

        cache_status = "HIT" if result.cache_hit else "MISS"
        print(f"      Cache: {cache_status}")
        print(f"      Task classification: {result.task_classification_time_ms:.2f}ms")
        print(f"      Pattern query: {result.pattern_query_time_ms:.2f}ms")
        print(f"      Relevance scoring: {result.relevance_scoring_time_ms:.2f}ms")
        print(f"      Schema query: {result.schema_query_time_ms:.2f}ms")
        print(
            f"      Infrastructure query: {result.infrastructure_query_time_ms:.2f}ms"
        )
        print(f"      Total time: {result.total_time_ms:.2f}ms")
        print(
            f"      Patterns: {result.patterns_retrieved} retrieved, {result.patterns_after_filtering} after filtering"
        )

        # Performance indicators
        if result.total_time_ms < 2000:
            print("      ✅ EXCELLENT - Under 2000ms target")
        elif result.total_time_ms < 5000:
            print("      ⚠️  ACCEPTABLE - Over target but under 5000ms")
        else:
            print("      ❌ ISSUE - Significantly over 2000ms target")

    def _generate_report(self, results: List[BenchmarkResult]) -> BenchmarkReport:
        """Generate aggregated benchmark report."""
        # Filter out errors
        valid_results = [r for r in results if r.error is None]

        if not valid_results:
            return BenchmarkReport(
                results=results,
                summary={"error": "No valid results"},
            )

        # Group by prompt type
        by_prompt_type = {}
        for result in valid_results:
            if result.prompt_type not in by_prompt_type:
                by_prompt_type[result.prompt_type] = []
            by_prompt_type[result.prompt_type].append(result)

        # Calculate statistics
        summary = {
            "total_runs": len(results),
            "valid_runs": len(valid_results),
            "failed_runs": len([r for r in results if r.error is not None]),
            "by_prompt_type": {},
            "overall": {},
        }

        # Per-prompt-type statistics
        for prompt_type, prompt_results in by_prompt_type.items():
            summary["by_prompt_type"][prompt_type] = self._calculate_stats(
                prompt_results
            )

        # Overall statistics
        summary["overall"] = self._calculate_stats(valid_results)

        # Performance targets check
        summary["performance_assessment"] = self._assess_performance(valid_results)

        return BenchmarkReport(results=results, summary=summary)

    def _calculate_stats(self, results: List[BenchmarkResult]) -> Dict[str, Any]:
        """Calculate statistics for a set of results."""
        return {
            "count": len(results),
            "task_classification_ms": {
                "mean": statistics.mean(
                    [r.task_classification_time_ms for r in results]
                ),
                "median": statistics.median(
                    [r.task_classification_time_ms for r in results]
                ),
                "min": min([r.task_classification_time_ms for r in results]),
                "max": max([r.task_classification_time_ms for r in results]),
            },
            "pattern_query_ms": {
                "mean": statistics.mean([r.pattern_query_time_ms for r in results]),
                "median": statistics.median([r.pattern_query_time_ms for r in results]),
                "min": min([r.pattern_query_time_ms for r in results]),
                "max": max([r.pattern_query_time_ms for r in results]),
            },
            "relevance_scoring_ms": {
                "mean": statistics.mean([r.relevance_scoring_time_ms for r in results]),
                "median": statistics.median(
                    [r.relevance_scoring_time_ms for r in results]
                ),
                "min": min([r.relevance_scoring_time_ms for r in results]),
                "max": max([r.relevance_scoring_time_ms for r in results]),
            },
            "total_time_ms": {
                "mean": statistics.mean([r.total_time_ms for r in results]),
                "median": statistics.median([r.total_time_ms for r in results]),
                "min": min([r.total_time_ms for r in results]),
                "max": max([r.total_time_ms for r in results]),
            },
            "patterns": {
                "mean_retrieved": statistics.mean(
                    [r.patterns_retrieved for r in results]
                ),
                "mean_after_filtering": statistics.mean(
                    [r.patterns_after_filtering for r in results]
                ),
            },
            "cache_hit_rate": sum([1 for r in results if r.cache_hit])
            / len(results)
            * 100,
        }

    def _assess_performance(self, results: List[BenchmarkResult]) -> Dict[str, Any]:
        """Assess performance against targets."""
        assessment = {
            "targets": {
                "task_classification_ms": 5,
                "relevance_scoring_ms": 10,
                "pattern_query_ms": 500,
                "total_time_ms": 2000,
            },
            "results": {},
        }

        # Check each target
        avg_classification = statistics.mean(
            [r.task_classification_time_ms for r in results]
        )
        avg_scoring = statistics.mean([r.relevance_scoring_time_ms for r in results])
        avg_pattern_query = statistics.mean([r.pattern_query_time_ms for r in results])
        avg_total = statistics.mean([r.total_time_ms for r in results])

        assessment["results"]["task_classification"] = {
            "average_ms": avg_classification,
            "target_ms": 5,
            "meets_target": avg_classification < 5,
            "status": "✅ PASS" if avg_classification < 5 else "❌ FAIL",
        }

        assessment["results"]["relevance_scoring"] = {
            "average_ms": avg_scoring,
            "target_ms": 10,
            "meets_target": avg_scoring < 10,
            "status": "✅ PASS" if avg_scoring < 10 else "❌ FAIL",
        }

        assessment["results"]["pattern_query"] = {
            "average_ms": avg_pattern_query,
            "target_ms": 500,
            "meets_target": avg_pattern_query < 500,
            "status": "✅ PASS" if avg_pattern_query < 500 else "⚠️  OVER TARGET",
        }

        assessment["results"]["total_time"] = {
            "average_ms": avg_total,
            "target_ms": 2000,
            "meets_target": avg_total < 2000,
            "status": "✅ PASS" if avg_total < 2000 else "❌ FAIL",
        }

        return assessment

    def print_report(self, report: BenchmarkReport) -> None:
        """Print formatted benchmark report."""
        print("\n" + "=" * 80)
        print("PERFORMANCE BENCHMARK REPORT")
        print("=" * 80)

        summary = report.summary

        if "error" in summary:
            print(f"\n❌ Error: {summary['error']}")
            return

        print("\n📊 Overall Statistics:")
        print(f"   Total runs: {summary['total_runs']}")
        print(f"   Valid runs: {summary['valid_runs']}")
        print(f"   Failed runs: {summary['failed_runs']}")

        # Overall performance
        overall = summary["overall"]
        print("\n⏱️  Average Timings (across all prompts):")
        print(
            f"   Task classification: {overall['task_classification_ms']['mean']:.2f}ms (median: {overall['task_classification_ms']['median']:.2f}ms)"
        )
        print(
            f"   Pattern query: {overall['pattern_query_ms']['mean']:.2f}ms (median: {overall['pattern_query_ms']['median']:.2f}ms)"
        )
        print(
            f"   Relevance scoring: {overall['relevance_scoring_ms']['mean']:.2f}ms (median: {overall['relevance_scoring_ms']['median']:.2f}ms)"
        )
        print(
            f"   Total time: {overall['total_time_ms']['mean']:.2f}ms (median: {overall['total_time_ms']['median']:.2f}ms)"
        )
        print(f"\n   Cache hit rate: {overall['cache_hit_rate']:.1f}%")

        # Per-prompt-type breakdown
        print("\n📝 Breakdown by Prompt Type:")
        for prompt_type, stats in summary["by_prompt_type"].items():
            print(f"\n   {prompt_type.upper()}:")
            print(
                f"      Classification: {stats['task_classification_ms']['mean']:.2f}ms"
            )
            print(f"      Pattern query: {stats['pattern_query_ms']['mean']:.2f}ms")
            print(
                f"      Relevance scoring: {stats['relevance_scoring_ms']['mean']:.2f}ms"
            )
            print(f"      Total: {stats['total_time_ms']['mean']:.2f}ms")
            print(
                f"      Patterns: {stats['patterns']['mean_retrieved']:.0f} retrieved → {stats['patterns']['mean_after_filtering']:.0f} after filtering"
            )

        # Performance assessment
        print("\n🎯 Performance Target Assessment:")
        assessment = summary["performance_assessment"]
        for metric, result in assessment["results"].items():
            print(f"\n   {metric.replace('_', ' ').title()}:")
            print(f"      Average: {result['average_ms']:.2f}ms")
            print(f"      Target: {result['target_ms']}ms")
            print(f"      Status: {result['status']}")

        # Final verdict
        all_pass = all(r["meets_target"] for r in assessment["results"].values())
        print("\n" + "=" * 80)
        if all_pass:
            print("✅ VERDICT: All performance targets met!")
        else:
            print(
                "⚠️  VERDICT: Some performance targets not met. Review bottlenecks above."
            )
        print("=" * 80 + "\n")

        # Export to JSON
        output_file = Path(__file__).parent.parent / "benchmark_results.json"
        with open(output_file, "w") as f:
            json.dump(
                {
                    "summary": summary,
                    "results": [
                        {
                            "prompt_type": r.prompt_type,
                            "pattern_count": r.pattern_count,
                            "task_classification_time_ms": r.task_classification_time_ms,
                            "pattern_query_time_ms": r.pattern_query_time_ms,
                            "relevance_scoring_time_ms": r.relevance_scoring_time_ms,
                            "total_time_ms": r.total_time_ms,
                            "patterns_retrieved": r.patterns_retrieved,
                            "patterns_after_filtering": r.patterns_after_filtering,
                            "cache_hit": r.cache_hit,
                            "error": r.error,
                        }
                        for r in report.results
                    ],
                },
                f,
                indent=2,
            )
        print(f"📄 Detailed results exported to: {output_file}")


async def main():
    """Run performance benchmark."""
    benchmark = PerformanceBenchmark()
    report = await benchmark.run_benchmark_suite(iterations=3)
    benchmark.print_report(report)


if __name__ == "__main__":
    asyncio.run(main())
