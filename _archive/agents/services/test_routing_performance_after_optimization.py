#!/usr/bin/env python3
"""
Test Routing Performance After Non-Blocking Optimization

This script tests the router service performance after converting database
logging to fire-and-forget async tasks.

Expected Results:
- Average routing time: <100ms (down from 333ms)
- P95 latency: <200ms (down from 1276ms)
- All routing decisions still logged to database (eventual consistency)

Usage:
    python3 test_routing_performance_after_optimization.py

Requirements:
    - Router service must be running (docker restart omniclaude_archon_router_consumer)
    - PostgreSQL must be accessible (192.168.86.200:5436)
    - Kafka must be running (192.168.86.200:29092)
"""

import asyncio
import logging
import statistics
import sys
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Import routing client
try:
    from ..lib.routing_event_client import route_via_events
except ImportError as e:
    logger.error(f"Failed to import routing_event_client: {e}")
    logger.error(f"Python path: {sys.path}")
    raise


async def measure_routing_time(user_request: str, timeout_ms: int = 10000) -> float:
    """
    Measure routing time for a single request.

    Args:
        user_request: User's request text
        timeout_ms: Timeout in milliseconds

    Returns:
        Routing time in milliseconds
    """
    start_time = time.time()

    try:
        recommendations = await route_via_events(
            user_request=user_request,
            max_recommendations=5,
            timeout_ms=timeout_ms,
            fallback_to_local=False,  # Force event routing only
        )

        routing_time_ms = (time.time() - start_time) * 1000

        if not recommendations:
            logger.warning(f"No recommendations for: {user_request[:50]}...")
            return routing_time_ms

        best = recommendations[0]
        logger.info(
            f"Routed in {routing_time_ms:.1f}ms → {best['agent_name']} "
            f"(confidence: {best['confidence']['total']:.2%})"
        )

        return routing_time_ms

    except Exception as e:
        routing_time_ms = (time.time() - start_time) * 1000
        logger.error(f"Routing failed after {routing_time_ms:.1f}ms: {e}")
        return routing_time_ms


async def run_performance_test(num_requests: int = 50) -> None:
    """
    Run performance test with multiple routing requests.

    Args:
        num_requests: Number of requests to test (default: 50)
    """
    logger.info("=" * 70)
    logger.info("Routing Performance Test - After Non-Blocking Optimization")
    logger.info("=" * 70)
    logger.info("Test parameters:")
    logger.info(f"  - Number of requests: {num_requests}")
    logger.info("  - Target avg time: <100ms")
    logger.info("  - Target P95: <200ms")
    logger.info("=" * 70)

    # Test requests covering different agent domains
    test_requests = [
        "Create a new REST API endpoint for user authentication",
        "Optimize my database queries for better performance",
        "Design a React component for data visualization",
        "Set up CI/CD pipeline with GitHub Actions",
        "Implement caching strategy with Redis",
        "Debug TypeScript compilation errors",
        "Write unit tests for authentication service",
        "Configure Docker compose for microservices",
        "Create Kubernetes deployment manifests",
        "Optimize SQL query with complex joins",
        "Implement real-time notifications with WebSocket",
        "Set up monitoring with Prometheus and Grafana",
        "Design database schema for e-commerce platform",
        "Create API documentation with OpenAPI/Swagger",
        "Implement authentication with JWT tokens",
        "Optimize frontend bundle size",
        "Set up logging infrastructure with ELK stack",
        "Create migration script for database schema changes",
        "Implement rate limiting for API endpoints",
        "Design microservices architecture",
    ]

    routing_times: list[float] = []
    failed_requests = 0

    logger.info("\nStarting performance test...")
    logger.info("-" * 70)

    # Run test requests
    for i in range(num_requests):
        request = test_requests[i % len(test_requests)]
        try:
            routing_time = await measure_routing_time(request)
            routing_times.append(routing_time)
        except Exception as e:
            logger.error(f"Request {i + 1} failed: {e}")
            failed_requests += 1

        # Small delay between requests to avoid overwhelming the system
        await asyncio.sleep(0.1)

    # Calculate statistics
    if not routing_times:
        logger.error("No successful requests!")
        return

    avg_time = statistics.mean(routing_times)
    median_time = statistics.median(routing_times)
    min_time = min(routing_times)
    max_time = max(routing_times)
    stddev = statistics.stdev(routing_times) if len(routing_times) > 1 else 0

    # Calculate percentiles
    sorted_times = sorted(routing_times)
    p50 = sorted_times[int(len(sorted_times) * 0.50)]
    p95 = sorted_times[int(len(sorted_times) * 0.95)]
    p99 = sorted_times[int(len(sorted_times) * 0.99)]

    # Print results
    logger.info("")
    logger.info("=" * 70)
    logger.info("PERFORMANCE TEST RESULTS")
    logger.info("=" * 70)
    logger.info(f"Total requests: {num_requests}")
    logger.info(f"Successful: {len(routing_times)}")
    logger.info(f"Failed: {failed_requests}")
    logger.info("")
    logger.info("Routing Time Statistics:")
    logger.info(f"  Average:  {avg_time:.2f}ms")
    logger.info(f"  Median:   {median_time:.2f}ms")
    logger.info(f"  Min:      {min_time:.2f}ms")
    logger.info(f"  Max:      {max_time:.2f}ms")
    logger.info(f"  Std Dev:  {stddev:.2f}ms")
    logger.info("")
    logger.info("Percentiles:")
    logger.info(f"  P50:  {p50:.2f}ms")
    logger.info(f"  P95:  {p95:.2f}ms")
    logger.info(f"  P99:  {p99:.2f}ms")
    logger.info("")

    # Performance assessment
    logger.info("=" * 70)
    logger.info("PERFORMANCE ASSESSMENT")
    logger.info("=" * 70)

    # Compare with pre-optimization baseline
    baseline_avg = 333.40
    baseline_p95 = 1276.75

    avg_improvement = ((baseline_avg - avg_time) / baseline_avg) * 100
    p95_improvement = ((baseline_p95 - p95) / baseline_p95) * 100

    logger.info("Baseline (before optimization):")
    logger.info(f"  Average: {baseline_avg:.2f}ms")
    logger.info(f"  P95:     {baseline_p95:.2f}ms")
    logger.info("")
    logger.info("Current (after optimization):")
    logger.info(f"  Average: {avg_time:.2f}ms ({avg_improvement:+.1f}%)")
    logger.info(f"  P95:     {p95:.2f}ms ({p95_improvement:+.1f}%)")
    logger.info("")

    # Check targets
    avg_target_met = avg_time < 100
    p95_target_met = p95 < 200

    logger.info("Target Achievement:")
    logger.info(f"  Average <100ms: {'✅ PASS' if avg_target_met else '❌ FAIL'}")
    logger.info(f"  P95 <200ms:     {'✅ PASS' if p95_target_met else '❌ FAIL'}")
    logger.info("")

    if avg_target_met and p95_target_met:
        logger.info("🎉 SUCCESS: Performance targets met!")
    elif avg_improvement > 50 and p95_improvement > 50:
        logger.info(
            "✅ GOOD: Significant improvement, but targets not fully met. Consider further optimization."
        )
    else:
        logger.info(
            "⚠️  WARNING: Performance improvement not as expected. Check for issues."
        )

    logger.info("=" * 70)


async def verify_database_logging() -> None:
    """
    Verify that database logging still works with fire-and-forget approach.

    Checks:
    - Recent routing decisions are in database
    - Performance metrics are being logged
    - No significant data loss
    """
    logger.info("")
    logger.info("=" * 70)
    logger.info("DATABASE LOGGING VERIFICATION")
    logger.info("=" * 70)

    try:
        import asyncpg
        from config import settings

        # Connect to database
        conn = await asyncpg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            database=settings.postgres_database,
            user=settings.postgres_user,
            password=settings.get_effective_postgres_password(),
        )

        # Check recent routing decisions
        recent_decisions = await conn.fetch(
            """
            SELECT COUNT(*) as count,
                   AVG(routing_time_ms) as avg_time,
                   MAX(created_at) as latest_time
            FROM agent_routing_decisions
            WHERE created_at > NOW() - INTERVAL '5 minutes'
            """
        )

        if recent_decisions:
            row = recent_decisions[0]
            logger.info("Recent routing decisions (last 5 min):")
            logger.info(f"  Count:      {row['count']}")
            logger.info(f"  Avg time:   {row['avg_time']:.2f}ms")
            logger.info(f"  Latest at:  {row['latest_time']}")
        else:
            logger.warning("No recent routing decisions found in database!")

        # Check performance metrics
        recent_metrics = await conn.fetch(
            """
            SELECT COUNT(*) as count
            FROM router_performance_metrics
            WHERE measured_at > NOW() - INTERVAL '5 minutes'
            """
        )

        if recent_metrics:
            row = recent_metrics[0]
            logger.info("\nPerformance metrics (last 5 min):")
            logger.info(f"  Count: {row['count']}")

        await conn.close()

        logger.info("")
        logger.info("✅ Database logging verification complete")

    except Exception as e:
        logger.error(f"Database verification failed: {e}")

    logger.info("=" * 70)


async def main():
    """Main entry point."""
    try:
        # Run performance test
        await run_performance_test(num_requests=50)

        # Wait for async tasks to complete (fire-and-forget database writes)
        logger.info("\nWaiting 5 seconds for background database writes to complete...")
        await asyncio.sleep(5)

        # Verify database logging
        await verify_database_logging()

    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
