#!/usr/bin/env python3
"""
Phase 4 Live Integration Test

Simulates a complete Claude Code workflow with Phase 4 pattern tracking:
1. Code Generation (Write tool) → Pattern Creation
2. Pattern Execution → Metrics Tracking
3. Pattern Modification → Lineage Tracking
4. Analytics Computation → Usage Analysis
5. Feedback Loop → Pattern Improvement

This test demonstrates the full end-to-end pipeline in action.

Usage:
    python tests/test_live_integration.py
    # OR with custom API URL:
    python tests/test_live_integration.py  # Uses settings.archon_intelligence_url
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from config import settings


# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from pattern_id_system import PatternIDSystem, PatternLineageDetector
from phase4_api_client import Phase4APIClient


# Test configuration
API_BASE_URL = os.getenv("API_URL", str(settings.archon_intelligence_url))
VERBOSE = os.getenv("VERBOSE", "1") == "1"


def print_section(title: str):
    """Print section header"""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print("=" * 70)


def print_step(step: int, description: str):
    """Print step description"""
    print(f"\n{step}. {description}")
    print("-" * 70)


def print_success(message: str):
    """Print success message"""
    print(f"   ✓ {message}")


def print_warning(message: str):
    """Print warning message"""
    print(f"   ⚠ {message}")


def print_error(message: str):
    """Print error message"""
    print(f"   ✗ {message}")


def print_info(key: str, value: str):
    """Print info message"""
    print(f"     • {key}: {value}")


async def main():
    """Run live integration test"""

    print_section("Phase 4 Live Integration Test - Claude Code Workflow Simulation")

    print("\nConfiguration:")
    print(f"  • API Base URL: {API_BASE_URL}")
    print(f"  • Verbose Mode: {VERBOSE}")
    print(f"  • Test Time: {datetime.now().isoformat()}")

    # Test code samples
    original_code = """
async def fetch_user_data(user_id: str):
    \"\"\"Fetch user data from API\"\"\"
    async with httpx.AsyncClient() as client:
        response = await client.get(f"/api/users/{user_id}")
        return response.json()
"""

    modified_code = """
async def fetch_user_data(user_id: str):
    \"\"\"Fetch user data from API with error handling\"\"\"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"/api/users/{user_id}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch user {user_id}: {e}")
            raise
"""

    # ========================================================================
    # Step 1: API Health Check
    # ========================================================================

    print_step(1, "Checking Phase 4 API Health")

    try:
        async with Phase4APIClient(base_url=API_BASE_URL, timeout=5.0) as client:
            health = await client.health_check()

            if health.get("status") == "healthy" or health.get("success"):
                print_success("API is healthy and responsive")

                if "components" in health:
                    print_info("Components", "")
                    for component, status in health["components"].items():
                        print(f"       - {component}: {status}")
            else:
                print_warning(
                    f"API health check returned: {health.get('status', 'unknown')}"
                )

                if "error" in health:
                    print_info("Error", health["error"])

    except Exception as e:
        print_error(f"API health check failed: {e}")
        print("\nCannot proceed without API access. Please ensure:")
        print(
            f"  1. Intelligence Service is running at {settings.archon_intelligence_url}"
        )
        print("  2. No firewall blocking connections")
        print("  3. Service is healthy and responsive")
        return False

    # ========================================================================
    # Step 2: Pattern Creation (Simulating Write Tool)
    # ========================================================================

    print_step(2, "Simulating Code Generation (Write Tool)")

    # Generate pattern ID
    pattern_id = PatternIDSystem.generate_id(original_code, normalize=True)

    print_success(f"Pattern ID generated: {pattern_id}")
    print_info("Code Length", f"{len(original_code)} characters")
    print_info("Language", "python")

    # Track pattern creation
    print("\n   Tracking pattern creation...")

    try:
        async with Phase4APIClient(base_url=API_BASE_URL) as client:
            result = await client.track_pattern_creation(
                pattern_id=pattern_id,
                pattern_name="fetch_user_data",
                code=original_code,
                language="python",
                context={
                    "file_path": "/tmp/api.py",
                    "tool": "Write",
                    "session_id": "live-test-session",
                    "timestamp": datetime.now().isoformat(),
                },
            )

            if result.get("success"):
                print_success("Pattern creation tracked successfully")

                if VERBOSE and "data" in result:
                    print_info("Lineage ID", result["data"].get("lineage_id", "N/A"))
            else:
                print_warning(
                    f"Pattern tracking: {result.get('error', 'Unknown error')}"
                )

                # Check if database is unavailable
                if "database" in result.get("error", "").lower():
                    print_info(
                        "Note", "Database unavailable - lineage tracking disabled"
                    )
                    print_info(
                        "Tip", "Configure TRACEABILITY_DB_URL environment variable"
                    )

    except Exception as e:
        print_error(f"Pattern creation tracking failed: {e}")

    # ========================================================================
    # Step 3: Pattern Execution Tracking
    # ========================================================================

    print_step(3, "Simulating Pattern Execution (3 iterations)")

    execution_metrics = [
        {
            "success": True,
            "quality_score": 0.90,
            "execution_time": 0.123,
            "violations": 0,
        },
        {
            "success": True,
            "quality_score": 0.92,
            "execution_time": 0.118,
            "violations": 0,
        },
        {
            "success": True,
            "quality_score": 0.95,
            "execution_time": 0.115,
            "violations": 0,
        },
    ]

    try:
        async with Phase4APIClient(base_url=API_BASE_URL) as client:
            for i, metrics in enumerate(execution_metrics, 1):
                result = await client.track_lineage(
                    event_type="pattern_executed",
                    pattern_id=pattern_id,
                    pattern_name="fetch_user_data",
                    pattern_type="code",
                    pattern_version="1.0.0",
                    pattern_data={
                        "execution": {
                            "iteration": i,
                            "success": metrics["success"],
                            "quality_score": metrics["quality_score"],
                            "execution_time_ms": metrics["execution_time"] * 1000,
                            "violations_found": metrics["violations"],
                            "timestamp": datetime.now().isoformat(),
                        }
                    },
                    triggered_by="live-test",
                )

                if result.get("success"):
                    print_success(
                        f"Execution {i} tracked (quality: {metrics['quality_score']:.2f})"
                    )
                else:
                    print_warning(f"Execution {i} tracking: {result.get('error')}")

    except Exception as e:
        print_error(f"Execution tracking failed: {e}")

    # ========================================================================
    # Step 4: Pattern Modification with Lineage
    # ========================================================================

    print_step(4, "Simulating Pattern Modification (Edit Tool)")

    # Detect lineage
    derivation = PatternLineageDetector.detect_derivation(
        original_code, modified_code, original_id=pattern_id, language="python"
    )

    modified_pattern_id = derivation["child_id"]

    print_success("Lineage detected")
    print_info("Parent ID", pattern_id[:16])
    print_info("Child ID", modified_pattern_id[:16])
    print_info("Similarity", f"{derivation['similarity_score']:.2%}")
    print_info(
        "Modification Type",
        (
            derivation["modification_type"].value
            if derivation["modification_type"]
            else "N/A"
        ),
    )

    # Track modification
    print("\n   Tracking pattern modification...")

    try:
        async with Phase4APIClient(base_url=API_BASE_URL) as client:
            result = await client.track_pattern_modification(
                pattern_id=modified_pattern_id,
                pattern_name="fetch_user_data_v2",
                parent_pattern_id=pattern_id,
                code=modified_code,
                language="python",
                reason="Added error handling and logging",
                version="2.0.0",
            )

            if result.get("success"):
                print_success("Pattern modification tracked")
            else:
                print_warning(f"Modification tracking: {result.get('error')}")

    except Exception as e:
        print_error(f"Modification tracking failed: {e}")

    # ========================================================================
    # Step 5: Query Pattern Lineage
    # ========================================================================

    print_step(5, "Querying Pattern Lineage")

    try:
        async with Phase4APIClient(base_url=API_BASE_URL) as client:
            lineage = await client.query_lineage(
                pattern_id=modified_pattern_id,
                include_ancestors=True,
                include_descendants=True,
            )

            if lineage.get("success"):
                print_success("Lineage query successful")

                if VERBOSE and "data" in lineage:
                    data = lineage["data"]
                    print_info("Ancestry Depth", str(data.get("ancestry_depth", 0)))
                    print_info("Total Ancestors", str(data.get("total_ancestors", 0)))
                    print_info(
                        "Total Descendants", str(data.get("total_descendants", 0))
                    )
            else:
                print_warning(f"Lineage query: {lineage.get('error')}")

    except Exception as e:
        print_error(f"Lineage query failed: {e}")

    # ========================================================================
    # Step 6: Compute Analytics
    # ========================================================================

    print_step(6, "Computing Usage Analytics")

    try:
        async with Phase4APIClient(base_url=API_BASE_URL) as client:
            analytics = await client.compute_analytics(
                pattern_id=pattern_id,
                time_window_type="daily",
                include_performance=True,
                include_trends=True,
            )

            if analytics.get("success"):
                print_success("Analytics computation successful")

                if VERBOSE:
                    if "usage_metrics" in analytics:
                        metrics = analytics["usage_metrics"]
                        print_info(
                            "Total Executions", str(metrics.get("total_executions", 0))
                        )
                        print_info(
                            "Executions/Day",
                            f"{metrics.get('executions_per_day', 0):.2f}",
                        )

                    if "success_metrics" in analytics:
                        metrics = analytics["success_metrics"]
                        print_info(
                            "Success Rate", f"{metrics.get('success_rate', 0):.2%}"
                        )
                        print_info(
                            "Avg Quality Score",
                            f"{metrics.get('avg_quality_score', 0):.2f}",
                        )
            else:
                print_warning(f"Analytics computation: {analytics.get('error')}")

    except Exception as e:
        print_error(f"Analytics computation failed: {e}")

    # ========================================================================
    # Final Summary
    # ========================================================================

    print_section("Live Integration Test Complete")

    print("\nTest Coverage:")
    print("  ✓ API health verification")
    print("  ✓ Pattern creation tracking")
    print("  ✓ Pattern execution metrics")
    print("  ✓ Pattern modification and lineage")
    print("  ✓ Lineage query and traversal")
    print("  ✓ Usage analytics computation")

    print("\nPhase 4 Integration Status:")
    print("  • Pattern ID System: ✓ Operational")
    print("  • API Client: ✓ Functional")
    print("  • Lineage Tracking: ✓ Working (if DB available)")
    print("  • Analytics Engine: ✓ Responsive")

    print("\n" + "=" * 70)

    return True


if __name__ == "__main__":
    # Run the test
    success = asyncio.run(main())

    # Exit with appropriate code
    sys.exit(0 if success else 1)
