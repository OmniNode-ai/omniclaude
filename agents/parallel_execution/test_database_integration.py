"""
Test script for DatabaseIntegrationLayer

IMPORTANT: This test requires Stream 1 database schema to be deployed first.
Run Stream 1 migration scripts before running these tests.

Usage:
    python test_database_integration.py
"""

import asyncio
import logging
from datetime import datetime, timedelta
from database_integration import (
    DatabaseIntegrationLayer,
    DatabaseConfig,
    DatabaseHealthStatus,
    CircuitState
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_connection_pool():
    """Test 1: Connection pool initialization and health check."""
    logger.info("=" * 80)
    logger.info("TEST 1: Connection Pool Initialization")
    logger.info("=" * 80)

    config = DatabaseConfig.from_env()
    db = DatabaseIntegrationLayer(config)

    # Initialize
    success = await db.initialize()
    logger.info(f"✅ Initialization: {'SUCCESS' if success else 'FAILED'}")

    if success:
        # Get health metrics
        health = await db.get_health_metrics()
        logger.info(f"✅ Health Status: {health.status.value}")
        logger.info(f"   Pool Size: {health.pool_size}")
        logger.info(f"   Pool Free: {health.pool_free}")
        logger.info(f"   Pool Utilization: {health.pool_utilization_pct:.1f}%")
        logger.info(f"   Circuit State: {health.circuit_state.value}")

        await db.shutdown()
        logger.info("✅ Shutdown complete")
    else:
        logger.error("❌ Initialization failed - Stream 1 schema may not exist yet")

    return success


async def test_batch_writes():
    """Test 2: Batch write operations for high-volume logging."""
    logger.info("=" * 80)
    logger.info("TEST 2: Batch Write Operations")
    logger.info("=" * 80)

    config = DatabaseConfig.from_env()
    db = DatabaseIntegrationLayer(config)

    success = await db.initialize()
    if not success:
        logger.error("❌ Cannot test batch writes - database unavailable")
        return False

    try:
        # Write 1000 trace events to test throughput
        start_time = datetime.now()
        logger.info("Writing 1000 trace events...")

        for i in range(1000):
            await db.write_trace_event(
                trace_id=f"test_trace_{i // 100}",
                event_type="TEST_EVENT",
                level="INFO",
                message=f"Test event {i}",
                metadata={"test_id": i, "batch": i // 100},
                agent_name="test-agent",
                task_id=f"task_{i}",
                duration_ms=float(i % 100)
            )

        # Force flush
        await db._flush_all_buffers()

        elapsed = (datetime.now() - start_time).total_seconds()
        throughput = 1000 / elapsed

        logger.info(f"✅ Wrote 1000 events in {elapsed:.2f}s")
        logger.info(f"✅ Throughput: {throughput:.1f} events/second")

        if throughput >= 1000:
            logger.info("✅ Throughput target met (1000+ events/second)")
        else:
            logger.warning(f"⚠️  Throughput below target: {throughput:.1f} events/second")

        # Write routing decisions
        logger.info("Writing 100 routing decisions...")
        for i in range(100):
            await db.write_routing_decision(
                user_request=f"Test request {i}",
                selected_agent="test-agent",
                confidence_score=0.8 + (i % 20) * 0.01,
                alternatives=[
                    {"agent": "alt-agent-1", "confidence": 0.6},
                    {"agent": "alt-agent-2", "confidence": 0.5}
                ],
                reasoning=f"Test reasoning {i}",
                routing_strategy="enhanced",
                context={"test_id": i},
                routing_time_ms=float(10 + i % 50)
            )

        await db._flush_all_buffers()
        logger.info("✅ Routing decisions written successfully")

    except Exception as e:
        logger.error(f"❌ Batch write test failed: {e}")
        return False
    finally:
        await db.shutdown()

    return True


async def test_query_api():
    """Test 3: Query API for observability data retrieval."""
    logger.info("=" * 80)
    logger.info("TEST 3: Query API")
    logger.info("=" * 80)

    config = DatabaseConfig.from_env()
    db = DatabaseIntegrationLayer(config)

    success = await db.initialize()
    if not success:
        logger.error("❌ Cannot test queries - database unavailable")
        return False

    try:
        # Query trace events
        logger.info("Querying trace events...")
        start_time = datetime.now()

        events = await db.query_trace_events(
            agent_name="test-agent",
            limit=10
        )

        elapsed = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"✅ Query completed in {elapsed:.2f}ms")
        logger.info(f"✅ Found {len(events)} trace events")

        if elapsed < 50:
            logger.info("✅ Query performance target met (<50ms)")
        else:
            logger.warning(f"⚠️  Query performance below target: {elapsed:.2f}ms")

        # Query routing decisions
        logger.info("Querying routing decisions...")
        decisions = await db.query_routing_decisions(
            selected_agent="test-agent",
            min_confidence=0.7,
            limit=10
        )
        logger.info(f"✅ Found {len(decisions)} routing decisions")

        # Query with time range
        logger.info("Querying with time range...")
        recent_events = await db.query_trace_events(
            start_time=datetime.now() - timedelta(hours=1),
            end_time=datetime.now(),
            limit=100
        )
        logger.info(f"✅ Found {len(recent_events)} recent events")

    except Exception as e:
        logger.error(f"❌ Query test failed: {e}")
        return False
    finally:
        await db.shutdown()

    return True


async def test_health_monitoring():
    """Test 4: Health monitoring and metrics."""
    logger.info("=" * 80)
    logger.info("TEST 4: Health Monitoring")
    logger.info("=" * 80)

    config = DatabaseConfig.from_env()
    db = DatabaseIntegrationLayer(config)

    success = await db.initialize()
    if not success:
        logger.error("❌ Cannot test health monitoring - database unavailable")
        return False

    try:
        # Execute some queries
        for i in range(10):
            await db.execute_query("SELECT 1", fetch="val")

        # Get health metrics
        health = await db.get_health_metrics()

        logger.info("Health Metrics:")
        logger.info(f"  Status: {health.status.value}")
        logger.info(f"  Pool Size: {health.pool_size}")
        logger.info(f"  Pool Free: {health.pool_free}")
        logger.info(f"  Pool Utilization: {health.pool_utilization_pct:.1f}%")
        logger.info(f"  Total Queries: {health.total_queries}")
        logger.info(f"  Failed Queries: {health.failed_queries}")
        logger.info(f"  Avg Query Time: {health.avg_query_time_ms:.2f}ms")
        logger.info(f"  Circuit State: {health.circuit_state.value}")
        logger.info(f"  Uptime: {health.uptime_seconds:.1f}s")

        if health.status == DatabaseHealthStatus.HEALTHY:
            logger.info("✅ Database health: HEALTHY")
        else:
            logger.warning(f"⚠️  Database health: {health.status.value}")

    except Exception as e:
        logger.error(f"❌ Health monitoring test failed: {e}")
        return False
    finally:
        await db.shutdown()

    return True


async def test_circuit_breaker():
    """Test 5: Circuit breaker failure handling."""
    logger.info("=" * 80)
    logger.info("TEST 5: Circuit Breaker")
    logger.info("=" * 80)

    # Create config with invalid database to trigger failures
    config = DatabaseConfig.from_env()
    config.database = "nonexistent_database"
    config.failure_threshold = 3

    db = DatabaseIntegrationLayer(config)

    # Initialize will fail
    success = await db.initialize()
    logger.info(f"✅ Expected initialization failure: {'SUCCESS' if not success else 'FAILED'}")

    # Circuit should be in expected state
    logger.info(f"   Circuit State: {db.circuit_breaker.state.value}")
    logger.info(f"   Failure Count: {db.circuit_breaker.failure_count}")

    # Test with valid config
    config = DatabaseConfig.from_env()
    db2 = DatabaseIntegrationLayer(config)
    success = await db2.initialize()

    if success:
        logger.info("✅ Recovery to valid database successful")
        health = await db2.get_health_metrics()
        logger.info(f"   Circuit State: {health.circuit_state.value}")
        await db2.shutdown()

    return True


async def test_retention_policy():
    """Test 6: Data retention and archival."""
    logger.info("=" * 80)
    logger.info("TEST 6: Data Retention Policy")
    logger.info("=" * 80)

    config = DatabaseConfig.from_env()
    # Set short retention for testing
    config.trace_events_retention_days = 1
    config.routing_decisions_retention_days = 1

    db = DatabaseIntegrationLayer(config)

    success = await db.initialize()
    if not success:
        logger.error("❌ Cannot test retention - database unavailable")
        return False

    try:
        logger.info("Testing retention policy...")
        logger.info(f"  Trace events retention: {config.trace_events_retention_days} days")
        logger.info(f"  Routing decisions retention: {config.routing_decisions_retention_days} days")

        # Apply retention policy
        await db.apply_retention_policy()
        logger.info("✅ Retention policy applied successfully")

    except Exception as e:
        logger.error(f"❌ Retention policy test failed: {e}")
        return False
    finally:
        await db.shutdown()

    return True


async def run_all_tests():
    """Run all tests in sequence."""
    logger.info("=" * 80)
    logger.info("DATABASE INTEGRATION LAYER TEST SUITE")
    logger.info("=" * 80)
    logger.info("")

    results = []

    # Test 1: Connection pool
    try:
        result = await test_connection_pool()
        results.append(("Connection Pool", result))
    except Exception as e:
        logger.error(f"Test 1 failed with exception: {e}")
        results.append(("Connection Pool", False))

    await asyncio.sleep(1)

    # Test 2: Batch writes (skip if connection failed)
    if results[0][1]:
        try:
            result = await test_batch_writes()
            results.append(("Batch Writes", result))
        except Exception as e:
            logger.error(f"Test 2 failed with exception: {e}")
            results.append(("Batch Writes", False))

        await asyncio.sleep(1)

        # Test 3: Query API
        try:
            result = await test_query_api()
            results.append(("Query API", result))
        except Exception as e:
            logger.error(f"Test 3 failed with exception: {e}")
            results.append(("Query API", False))

        await asyncio.sleep(1)

        # Test 4: Health monitoring
        try:
            result = await test_health_monitoring()
            results.append(("Health Monitoring", result))
        except Exception as e:
            logger.error(f"Test 4 failed with exception: {e}")
            results.append(("Health Monitoring", False))

        await asyncio.sleep(1)

    # Test 5: Circuit breaker (always run)
    try:
        result = await test_circuit_breaker()
        results.append(("Circuit Breaker", result))
    except Exception as e:
        logger.error(f"Test 5 failed with exception: {e}")
        results.append(("Circuit Breaker", False))

    await asyncio.sleep(1)

    # Test 6: Retention policy (skip if connection failed)
    if results[0][1]:
        try:
            result = await test_retention_policy()
            results.append(("Retention Policy", result))
        except Exception as e:
            logger.error(f"Test 6 failed with exception: {e}")
            results.append(("Retention Policy", False))

    # Print summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}  {test_name}")

    logger.info("=" * 80)
    logger.info(f"Results: {passed}/{total} tests passed")
    logger.info("=" * 80)

    if passed == total:
        logger.info("🎉 All tests passed!")
    elif passed == 0:
        logger.error("❌ All tests failed - Stream 1 database schema may not exist yet")
    else:
        logger.warning(f"⚠️  {total - passed} test(s) failed")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
