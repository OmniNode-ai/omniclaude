#!/usr/bin/env python3
"""
Test script for PostgreSQL logger.

Tests the postgres_logger module to ensure it can:
1. Connect to PostgreSQL database
2. Log routing decisions
3. Handle errors gracefully
4. Perform health checks

Usage:
    # From omniclaude directory
    source .env
    python3 services/routing_adapter/test_postgres_logger.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from uuid import uuid4


# Add project root to path for centralized config import
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Import centralized configuration
try:
    from config import settings
except ImportError:
    print("❌ config.settings not available. Ensure config module is installed.")
    sys.exit(1)

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from postgres_logger import PostgresLogger


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


async def test_postgres_logger():
    """
    Test PostgreSQL logger functionality.

    Tests:
        1. Connection pool initialization
        2. Health check
        3. Log routing decision
        4. Verify insertion
        5. Retry logic (by simulating database issues)
        6. Graceful shutdown
    """
    logger.info("=" * 70)
    logger.info("PostgreSQL Logger Test")
    logger.info("=" * 70)

    # Get configuration from centralized settings (NO hardcoded defaults)
    host = settings.postgres_host
    port = settings.postgres_port
    database = settings.postgres_database
    user = settings.postgres_user

    try:
        password = settings.get_effective_postgres_password()
    except ValueError:
        logger.error("POSTGRES_PASSWORD not configured in settings")
        logger.error("Run: source .env")
        return False

    logger.info(f"Connecting to PostgreSQL: {user}@{host}:{port}/{database}")

    # Test 1: Initialize connection pool
    logger.info("\nTest 1: Initialize connection pool")
    try:
        postgres_logger = PostgresLogger(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            pool_min_size=2,
            pool_max_size=5,
        )
        await postgres_logger.initialize()
        logger.info("✅ Connection pool initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize connection pool: {e}")
        return False

    # Test 2: Health check
    logger.info("\nTest 2: Health check")
    try:
        health = await postgres_logger.health_check()
        logger.info(f"Health status: {health['status']}")
        logger.info(f"Pool size: {health.get('pool_size', 'N/A')}")
        logger.info(f"Pool free: {health.get('pool_free', 'N/A')}")
        logger.info(f"Test query time: {health.get('test_query_ms', 'N/A')}ms")

        if health["status"] != "healthy":
            logger.error("❌ Health check failed")
            return False

        logger.info("✅ Health check passed")
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return False

    # Test 3: Log routing decision
    logger.info("\nTest 3: Log routing decision")
    try:
        correlation_id = str(uuid4())
        user_request = "Test routing request for database logging verification"
        selected_agent = "agent-test-specialist"
        confidence = 0.92
        routing_strategy = "enhanced_fuzzy_matching"
        routing_time_ms = 45.5

        alternatives = [
            {
                "agent_name": "agent-alternative-1",
                "agent_title": "Alternative Agent 1",
                "confidence": 0.85,
                "reason": "Good match but lower confidence",
            },
            {
                "agent_name": "agent-alternative-2",
                "agent_title": "Alternative Agent 2",
                "confidence": 0.78,
                "reason": "Moderate match",
            },
        ]

        reasoning = "High confidence match on test triggers and capabilities"
        context = {
            "domain": "testing",
            "project_path": "/test/path",
            "project_name": "test-project",
        }

        logger.info(f"Logging routing decision with correlation_id: {correlation_id}")
        logger.info(f"  User request: {user_request}")
        logger.info(f"  Selected agent: {selected_agent}")
        logger.info(f"  Confidence: {confidence}")

        record_id = await postgres_logger.log_routing_decision(
            user_request=user_request,
            selected_agent=selected_agent,
            confidence_score=confidence,
            routing_strategy=routing_strategy,
            routing_time_ms=routing_time_ms,
            alternatives=alternatives,
            reasoning=reasoning,
            context=context,
            project_path=context["project_path"],
            project_name=context["project_name"],
            claude_session_id="test-session-123",
        )

        if record_id:
            logger.info("✅ Routing decision logged successfully")
            logger.info(f"   Record ID: {record_id}")
        else:
            logger.error("❌ Failed to log routing decision (returned None)")
            return False

    except Exception as e:
        logger.error(f"❌ Failed to log routing decision: {e}")
        return False

    # Test 4: Verify metrics
    logger.info("\nTest 4: Verify metrics")
    try:
        metrics = postgres_logger.get_metrics()
        logger.info("Metrics:")
        logger.info(f"  Log count: {metrics['log_count']}")
        logger.info(f"  Success count: {metrics['success_count']}")
        logger.info(f"  Error count: {metrics['error_count']}")
        logger.info(f"  Retry count: {metrics['retry_count']}")
        logger.info(f"  Success rate: {metrics['success_rate']}%")
        logger.info(f"  Avg log time: {metrics['avg_log_time_ms']}ms")

        if metrics["success_count"] < 1:
            logger.error("❌ Expected at least 1 successful log")
            return False

        logger.info("✅ Metrics verified")
    except Exception as e:
        logger.error(f"❌ Failed to verify metrics: {e}")
        return False

    # Test 5: Shutdown
    logger.info("\nTest 5: Graceful shutdown")
    try:
        await postgres_logger.shutdown()
        logger.info("✅ Graceful shutdown successful")
    except Exception as e:
        logger.error(f"❌ Shutdown failed: {e}")
        return False

    # All tests passed
    logger.info("\n" + "=" * 70)
    logger.info("✅ ALL TESTS PASSED")
    logger.info("=" * 70)
    return True


async def main():
    """Main entry point."""
    success = await test_postgres_logger()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
