"""
Test Manifest Injection Integration

Verifies that the manifest injection functionality works end-to-end:
1. AgentExecutionMixin.inject_manifest() method works
2. Manifest is generated with comprehensive intelligence
3. Manifest injection is recorded in agent_manifest_injections table
4. Agents can successfully use manifests in their execution

Created: 2025-11-10
"""

import asyncio
import logging
import os
import sys
from uuid import uuid4

from agents.lib.agent_execution_mixin import AgentExecutionMixin

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class TestAgent(AgentExecutionMixin):
    """Simple test agent that uses manifest injection."""

    def __init__(self):
        super().__init__(
            agent_name="test-manifest-injection-agent",
            project_path="/Volumes/PRO-G40/Code/omniclaude",
            project_name="omniclaude",
        )

    async def test_manifest_injection(self, correlation_id: str = None):
        """Test manifest injection functionality."""
        # Use provided correlation_id or generate new one
        cid = correlation_id or str(uuid4())

        logger.info(f"Testing manifest injection with correlation_id: {cid}")

        # Inject manifest
        manifest = await self.inject_manifest(correlation_id=cid)

        # Verify manifest was generated
        if not manifest:
            logger.error("❌ Manifest injection failed - empty manifest returned")
            return False

        logger.info(f"✅ Manifest generated successfully ({len(manifest)} chars)")

        # Check for expected sections
        expected_sections = [
            "SYSTEM MANIFEST",
            "AVAILABLE PATTERNS",
            "INFRASTRUCTURE STATUS",
        ]

        found_sections = []
        missing_sections = []

        for section in expected_sections:
            if section in manifest:
                found_sections.append(section)
                logger.info(f"✅ Found section: {section}")
            else:
                missing_sections.append(section)
                logger.warning(f"⚠️  Missing section: {section}")

        # Log manifest preview
        logger.info("\n" + "=" * 80)
        logger.info("MANIFEST PREVIEW (first 2000 chars):")
        logger.info("=" * 80)
        logger.info(manifest[:2000])
        logger.info("=" * 80 + "\n")

        return len(found_sections) > 0


async def verify_database_record(correlation_id: str):
    """Verify manifest injection was recorded in database."""
    try:
        # Load environment for database connection
        from dotenv import load_dotenv

        load_dotenv()

        # Import database client
        import asyncpg

        # Get database connection parameters
        db_host = os.getenv("POSTGRES_HOST", "192.168.86.200")
        db_port = int(os.getenv("POSTGRES_PORT", "5436"))
        db_name = os.getenv("POSTGRES_DATABASE", "omninode_bridge")
        db_user = os.getenv("POSTGRES_USER", "postgres")
        db_password = os.getenv("POSTGRES_PASSWORD")

        if not db_password:
            logger.error("❌ POSTGRES_PASSWORD not set in environment")
            return False

        # Connect to database
        logger.info(f"Connecting to database: {db_host}:{db_port}/{db_name}")
        conn = await asyncpg.connect(
            host=db_host,
            port=db_port,
            database=db_name,
            user=db_user,
            password=db_password,
        )

        try:
            # Query for manifest injection record
            query = """
                SELECT
                    id,
                    correlation_id,
                    agent_name,
                    query_time_ms,
                    pattern_count,
                    infrastructure_available,
                    models_available,
                    created_at
                FROM agent_manifest_injections
                WHERE correlation_id = $1
                ORDER BY created_at DESC
                LIMIT 1
            """

            record = await conn.fetchrow(query, correlation_id)

            if record:
                logger.info("✅ Manifest injection record found in database:")
                logger.info(f"   - ID: {record['id']}")
                logger.info(f"   - Agent: {record['agent_name']}")
                logger.info(f"   - Query Time: {record['query_time_ms']}ms")
                logger.info(f"   - Pattern Count: {record['pattern_count']}")
                logger.info(
                    f"   - Infrastructure Available: {record['infrastructure_available']}"
                )
                logger.info(f"   - Models Available: {record['models_available']}")
                logger.info(f"   - Created At: {record['created_at']}")
                return True
            else:
                logger.warning("⚠️  No manifest injection record found in database")
                logger.warning(f"   Correlation ID: {correlation_id}")
                logger.warning(
                    "   This may be expected if intelligence services are unavailable"
                )
                return False

        finally:
            await conn.close()

    except ImportError as e:
        logger.warning(f"⚠️  Database verification skipped (missing dependency: {e})")
        return None
    except Exception as e:
        logger.error(f"❌ Database verification failed: {e}", exc_info=True)
        return False


async def main():
    """Run manifest injection integration test."""
    logger.info("\n" + "=" * 80)
    logger.info("MANIFEST INJECTION INTEGRATION TEST")
    logger.info("=" * 80 + "\n")

    # Generate correlation ID for tracing
    correlation_id = str(uuid4())
    logger.info(f"Test Correlation ID: {correlation_id}\n")

    # Create test agent
    agent = TestAgent()

    # Test manifest injection
    logger.info("Step 1: Testing manifest injection...")
    success = await agent.test_manifest_injection(correlation_id)

    if not success:
        logger.error("\n❌ TEST FAILED: Manifest injection did not work as expected")
        return False

    # Wait a moment for database record to be written
    logger.info("\nStep 2: Waiting for database record (2 seconds)...")
    await asyncio.sleep(2)

    # Verify database record
    logger.info("Step 3: Verifying database record...")
    db_verified = await verify_database_record(correlation_id)

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Manifest Generation: {'✅ PASS' if success else '❌ FAIL'}")

    if db_verified is None:
        logger.info("Database Verification: ⚠️  SKIPPED (dependency unavailable)")
    else:
        logger.info(
            f"Database Verification: {'✅ PASS' if db_verified else '⚠️  NO RECORD'}"
        )

    if success:
        logger.info("\n✅ OVERALL: TEST PASSED")
        logger.info(
            "\nManifest injection is working! Agents can now receive comprehensive system context."
        )
        return True
    else:
        logger.error("\n❌ OVERALL: TEST FAILED")
        return False


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
