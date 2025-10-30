#!/usr/bin/env python3
"""
Test script for Agent Router Event Consumer Service.

Tests routing accuracy by sending various prompts via Kafka events
and verifying routing decisions in the database.

Requirements:
- Kafka/Redpanda running (192.168.86.200:29092)
- PostgreSQL running (192.168.86.200:5436)
- Environment variables configured in .env

Usage:
    python3 agents/services/test_router_consumer.py
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

# Import routing event client
try:
    from routing_event_client import RoutingEventClient

    print("✅ Imported RoutingEventClient successfully")
except ImportError as e:
    print(f"❌ Failed to import RoutingEventClient: {e}")
    sys.exit(1)

# PostgreSQL imports
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    POSTGRES_AVAILABLE = True
except ImportError:
    print("⚠️  psycopg2 not available - database verification disabled")
    POSTGRES_AVAILABLE = False


class RouterConsumerTester:
    """Test harness for router consumer service."""

    def __init__(self):
        # Load configuration from environment
        self.kafka_bootstrap = os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:29092"
        )
        self.postgres_host = os.getenv("POSTGRES_HOST", "192.168.86.200")
        self.postgres_port = int(os.getenv("POSTGRES_PORT", "5436"))
        self.postgres_db = os.getenv("POSTGRES_DATABASE", "omninode_bridge")
        self.postgres_user = os.getenv("POSTGRES_USER", "postgres")
        self.postgres_password = os.getenv("POSTGRES_PASSWORD", "")

        # Test cases with expected routing
        self.test_cases = [
            {
                "user_request": "Help me implement ONEX patterns",
                "expected_agents": ["onex-architect", "polymorphic-agent"],
                "context": {"domain": "onex_architecture"},
            },
            {
                "user_request": "Debug my database queries",
                "expected_agents": [
                    "debug-intelligence",
                    "database-specialist",
                    "polymorphic-agent",
                ],
                "context": {"domain": "debugging"},
            },
            {
                "user_request": "Create a REST API",
                "expected_agents": ["api-architect", "polymorphic-agent"],
                "context": {"domain": "api_development"},
            },
            {
                "user_request": "@polymorphic-agent analyze this code",
                "expected_agents": ["polymorphic-agent"],  # Explicit selection
                "context": {},
            },
        ]

        self.results = []

    def print_header(self, title):
        """Print formatted section header."""
        print("\n" + "=" * 70)
        print(f"  {title}")
        print("=" * 70)

    async def test_routing_request(self, test_case, client):
        """
        Test a single routing request.

        Args:
            test_case: Test case dictionary
            client: RoutingEventClient instance

        Returns:
            Result dictionary with success/failure and metrics
        """
        user_request = test_case["user_request"]
        expected_agents = test_case["expected_agents"]
        context = test_case["context"]

        print(f"\n📤 Testing: {user_request}")
        print(f"   Expected agents: {', '.join(expected_agents)}")

        start_time = time.time()

        try:
            # Request routing
            recommendations = await client.request_routing(
                user_request=user_request,
                context=context,
                max_recommendations=5,
                timeout_ms=10000,
            )

            routing_time_ms = (time.time() - start_time) * 1000

            if not recommendations:
                print("   ❌ No recommendations received")
                return {
                    "success": False,
                    "user_request": user_request,
                    "error": "No recommendations received",
                    "routing_time_ms": routing_time_ms,
                }

            # Extract selected agent
            selected_agent = recommendations[0]["agent_name"]
            confidence_score = recommendations[0]["confidence"]["total"]

            # Check if selected agent is in expected list
            agent_match = selected_agent in expected_agents
            status = "✅" if agent_match else "⚠️"

            print(f"   {status} Selected: {selected_agent}")
            print(f"   📊 Confidence: {confidence_score:.2%}")
            print(f"   ⏱️  Routing time: {routing_time_ms:.1f}ms")

            # Show alternatives
            if len(recommendations) > 1:
                print("   📝 Alternatives:")
                for i, rec in enumerate(recommendations[1:4], 1):
                    print(
                        f"      {i}. {rec['agent_name']} ({rec['confidence']['total']:.2%})"
                    )

            return {
                "success": True,
                "agent_match": agent_match,
                "user_request": user_request,
                "selected_agent": selected_agent,
                "confidence_score": confidence_score,
                "routing_time_ms": routing_time_ms,
                "recommendations_count": len(recommendations),
            }

        except Exception as e:
            routing_time_ms = (time.time() - start_time) * 1000
            print(f"   ❌ Error: {e}")
            return {
                "success": False,
                "user_request": user_request,
                "error": str(e),
                "routing_time_ms": routing_time_ms,
            }

    def verify_database_logging(self):
        """
        Verify routing decisions were logged to PostgreSQL.

        Returns:
            List of recent routing decisions from database
        """
        if not POSTGRES_AVAILABLE:
            print("⚠️  Database verification skipped (psycopg2 not available)")
            return []

        if not self.postgres_password:
            print("⚠️  Database verification skipped (POSTGRES_PASSWORD not set)")
            return []

        self.print_header("Database Verification")

        try:
            # Connect to PostgreSQL
            conn = psycopg2.connect(
                host=self.postgres_host,
                port=self.postgres_port,
                database=self.postgres_db,
                user=self.postgres_user,
                password=self.postgres_password,
            )

            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Query recent routing decisions (last 10 minutes)
                query = """
                    SELECT
                        selected_agent,
                        confidence_score,
                        routing_time_ms,
                        routing_strategy,
                        created_at,
                        user_request
                    FROM agent_routing_decisions
                    WHERE created_at >= NOW() - INTERVAL '10 minutes'
                    ORDER BY created_at DESC
                    LIMIT 10
                """
                cursor.execute(query)
                results = cursor.fetchall()

                if not results:
                    print("⚠️  No recent routing decisions found in database")
                    return []

                print(f"\n✅ Found {len(results)} recent routing decision(s):\n")

                for i, row in enumerate(results, 1):
                    print(f"{i}. Agent: {row['selected_agent']}")
                    print(f"   Confidence: {row['confidence_score']:.2%}")
                    print(f"   Routing time: {row['routing_time_ms']}ms")
                    print(f"   Strategy: {row['routing_strategy']}")
                    print(f"   Created: {row['created_at']}")
                    print(f"   Request: {row['user_request'][:80]}...")
                    print()

                conn.close()
                return results

        except Exception as e:
            print(f"❌ Database verification failed: {e}")
            return []

    async def run_tests(self):
        """Run all test cases."""
        self.print_header("Agent Router Consumer Service Tests")

        print("\n📋 Configuration:")
        print(f"   Kafka: {self.kafka_bootstrap}")
        print(
            f"   PostgreSQL: {self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
        print(f"   Test cases: {len(self.test_cases)}")

        # Initialize routing event client
        print("\n🔧 Initializing routing event client...")
        client = RoutingEventClient(
            bootstrap_servers=self.kafka_bootstrap,
            request_timeout_ms=10000,
        )

        try:
            await client.start()
            print("✅ Routing event client started successfully")

            # Run test cases
            self.print_header("Running Test Cases")

            for test_case in self.test_cases:
                result = await self.test_routing_request(test_case, client)
                self.results.append(result)

                # Brief delay between tests
                await asyncio.sleep(0.5)

        except Exception as e:
            print(f"❌ Test execution failed: {e}")
            raise

        finally:
            await client.stop()
            print("\n✅ Routing event client stopped")

        # Verify database logging
        db_results = self.verify_database_logging()

        # Print summary
        self.print_summary(db_results)

    def print_summary(self, db_results):
        """Print test summary."""
        self.print_header("Test Summary")

        # Calculate statistics
        total_tests = len(self.results)
        successful_tests = sum(1 for r in self.results if r["success"])
        failed_tests = total_tests - successful_tests
        agent_matches = sum(1 for r in self.results if r.get("agent_match", False))

        # Routing time statistics
        routing_times = [r["routing_time_ms"] for r in self.results if r["success"]]
        avg_routing_time = (
            sum(routing_times) / len(routing_times) if routing_times else 0
        )
        max_routing_time = max(routing_times) if routing_times else 0

        print("\n📊 Results:")
        print(f"   Total tests: {total_tests}")
        print(f"   Successful: {successful_tests}")
        print(f"   Failed: {failed_tests}")
        print(f"   Agent matches: {agent_matches}/{successful_tests}")
        print(
            f"   Match rate: {(agent_matches/successful_tests*100):.1f}%"
            if successful_tests > 0
            else "N/A"
        )

        print("\n⏱️  Performance:")
        print(f"   Average routing time: {avg_routing_time:.1f}ms")
        print(f"   Max routing time: {max_routing_time:.1f}ms")
        print(
            "   Target: <500ms ✅"
            if max_routing_time < 500
            else "   Target: <500ms ⚠️  (exceeded)"
        )

        print("\n💾 Database:")
        print(f"   Recent decisions logged: {len(db_results)}")

        # Overall status
        print(f"\n{'=' * 70}")
        if (
            failed_tests == 0
            and agent_matches == successful_tests
            and max_routing_time < 500
        ):
            print("✅ ALL TESTS PASSED")
        elif failed_tests == 0:
            print("⚠️  TESTS PASSED WITH WARNINGS")
        else:
            print("❌ SOME TESTS FAILED")
        print(f"{'=' * 70}\n")


async def main():
    """Main entry point."""
    # Load environment variables
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        print(f"Loading environment from: {env_file}")
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key, value)

    # Run tests
    tester = RouterConsumerTester()
    await tester.run_tests()


if __name__ == "__main__":
    asyncio.run(main())
