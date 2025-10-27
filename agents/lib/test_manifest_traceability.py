#!/usr/bin/env python3
"""
Test manifest injection traceability with correlation_id.

Tests that correlation_id propagates through:
1. Manifest generation
2. Database storage
3. Query retrieval

Run with:
    python3 test_manifest_traceability.py
"""

import asyncio
import logging
import uuid

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


async def test_manifest_traceability():
    """
    Test end-to-end manifest injection traceability.
    """
    import os

    import psycopg2
    from manifest_injector import ManifestInjector

    # Generate test correlation ID
    correlation_id = str(uuid.uuid4())
    agent_name = "test-agent-traceability"

    logger.info(f"Starting traceability test with correlation_id: {correlation_id}")

    # Step 1: Generate manifest with correlation_id
    logger.info("Step 1: Generating manifest...")
    injector = ManifestInjector(
        enable_intelligence=False,  # Use fallback for testing
        enable_storage=True,
        agent_name=agent_name,
    )

    # Generate manifest (will use minimal fallback)
    manifest = injector.generate_dynamic_manifest(correlation_id)

    # Verify manifest generation
    assert manifest is not None, "Manifest generation failed"
    assert "manifest_metadata" in manifest, "Manifest missing metadata"
    logger.info(
        f"✓ Manifest generated: version={manifest['manifest_metadata'].get('version')}"
    )

    # Format manifest
    formatted = injector.format_for_prompt()
    assert len(formatted) > 0, "Formatted manifest is empty"
    logger.info(f"✓ Manifest formatted: {len(formatted)} bytes")

    # Step 2: Verify database storage
    logger.info("Step 2: Verifying database storage...")

    try:
        conn = psycopg2.connect(
            host=os.environ.get("POSTGRES_HOST", "192.168.86.200"),
            port=int(os.environ.get("POSTGRES_PORT", "5436")),
            dbname=os.environ.get("POSTGRES_DATABASE", "omninode_bridge"),
            user=os.environ.get("POSTGRES_USER", "postgres"),
            password=os.environ.get(
                "POSTGRES_PASSWORD", "omninode-bridge-postgres-dev-2024"
            ),
        )

        cursor = conn.cursor()

        # Query for our correlation_id
        cursor.execute(
            """
            SELECT
                correlation_id,
                agent_name,
                manifest_version,
                generation_source,
                is_fallback,
                patterns_count,
                total_query_time_ms,
                created_at
            FROM agent_manifest_injections
            WHERE correlation_id = %s
            """,
            (correlation_id,),
        )

        row = cursor.fetchone()

        if row:
            logger.info("✓ Database record found:")
            logger.info(f"  - correlation_id: {row[0]}")
            logger.info(f"  - agent_name: {row[1]}")
            logger.info(f"  - manifest_version: {row[2]}")
            logger.info(f"  - generation_source: {row[3]}")
            logger.info(f"  - is_fallback: {row[4]}")
            logger.info(f"  - patterns_count: {row[5]}")
            logger.info(f"  - total_query_time_ms: {row[6]}")
            logger.info(f"  - created_at: {row[7]}")

            assert str(row[0]) == correlation_id, "Correlation ID mismatch"
            assert row[1] == agent_name, "Agent name mismatch"
            assert row[4], "Expected fallback manifest"

        else:
            logger.error("✗ No database record found for correlation_id")
            raise AssertionError("Database storage verification failed")

        # Step 3: Test complete trace query
        logger.info("Step 3: Testing complete trace reconstruction...")

        cursor.execute(
            """
            SELECT
                correlation_id,
                user_request,
                selected_agent,
                confidence_score,
                routing_strategy
            FROM agent_routing_decisions
            WHERE correlation_id = %s
            """,
            (correlation_id,),
        )

        routing_row = cursor.fetchone()
        if routing_row:
            logger.info("✓ Found routing decision record")
            logger.info(f"  - selected_agent: {routing_row[2]}")
            logger.info(f"  - confidence_score: {routing_row[3]}")
        else:
            logger.info("ℹ No routing decision record (test only generated manifest)")

        # Test the complete trace view
        cursor.execute(
            """
            SELECT
                ami.correlation_id,
                ami.agent_name,
                ami.manifest_version,
                ami.patterns_count,
                ami.total_query_time_ms,
                ami.created_at
            FROM agent_manifest_injections ami
            WHERE ami.correlation_id = %s
            """,
            (correlation_id,),
        )

        trace_row = cursor.fetchone()
        if trace_row:
            logger.info("✓ Complete trace query successful")
            logger.info(f"  - Manifest recorded with {trace_row[3]} patterns")
        else:
            raise AssertionError("Trace query failed")

        cursor.close()
        conn.close()

        logger.info("\n" + "=" * 70)
        logger.info("✓ ALL TESTS PASSED")
        logger.info("=" * 70)
        logger.info(f"Correlation ID: {correlation_id}")
        logger.info("Traceability system working correctly!")
        logger.info("=" * 70)

    except psycopg2.Error as e:
        logger.error(f"✗ Database error: {e}")
        raise

    except Exception as e:
        logger.error(f"✗ Test failed: {e}")
        raise


async def test_query_reconstruction():
    """
    Test query to reconstruct complete execution trace.
    """
    import os

    import psycopg2

    logger.info("\nTesting complete trace reconstruction query...")

    try:
        conn = psycopg2.connect(
            host=os.environ.get("POSTGRES_HOST", "192.168.86.200"),
            port=int(os.environ.get("POSTGRES_PORT", "5436")),
            dbname=os.environ.get("POSTGRES_DATABASE", "omninode_bridge"),
            user=os.environ.get("POSTGRES_USER", "postgres"),
            password=os.environ.get(
                "POSTGRES_PASSWORD", "omninode-bridge-postgres-dev-2024"
            ),
        )

        cursor = conn.cursor()

        # Get most recent manifest injection
        cursor.execute(
            """
            SELECT
                ami.correlation_id,
                ami.agent_name,
                ami.manifest_version,
                ami.generation_source,
                ami.patterns_count,
                ami.debug_intelligence_successes,
                ami.debug_intelligence_failures,
                ami.total_query_time_ms,
                ami.agent_execution_success,
                ami.agent_quality_score,
                ami.created_at,
                ami.query_times,
                ami.sections_included
            FROM agent_manifest_injections ami
            ORDER BY ami.created_at DESC
            LIMIT 1
            """
        )

        row = cursor.fetchone()

        if row:
            logger.info("✓ Most recent manifest injection:")
            logger.info(f"  - Correlation ID: {row[0]}")
            logger.info(f"  - Agent: {row[1]}")
            logger.info(f"  - Version: {row[2]}")
            logger.info(f"  - Source: {row[3]}")
            logger.info(f"  - Patterns: {row[4]}")
            logger.info(
                f"  - Debug Intelligence: {row[5]} successes, {row[6]} failures"
            )
            logger.info(f"  - Query Time: {row[7]}ms")
            logger.info(f"  - Execution Success: {row[8]}")
            logger.info(f"  - Quality Score: {row[9]}")
            logger.info(f"  - Created: {row[10]}")
            logger.info(f"  - Query Times: {row[11]}")
            logger.info(f"  - Sections: {row[12]}")
        else:
            logger.warning("No manifest injection records found")

        cursor.close()
        conn.close()

    except Exception as e:
        logger.error(f"✗ Query reconstruction test failed: {e}")
        raise


if __name__ == "__main__":
    logger.info("=" * 70)
    logger.info("Manifest Injection Traceability Test")
    logger.info("=" * 70)

    # Run tests
    asyncio.run(test_manifest_traceability())
    asyncio.run(test_query_reconstruction())

    logger.info("\n✓ All traceability tests completed successfully!")
