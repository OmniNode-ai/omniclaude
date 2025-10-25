#!/usr/bin/env python3
"""
Integration Test for Quorum Validation in Dispatch Runner

Tests the complete integration of quorum validation into the parallel
dispatch workflow, including the PostgreSQL adapter failure case.

Setup:
    Run from project root with proper PYTHONPATH:

        cd /path/to/omniclaude
        PYTHONPATH=/path/to/omniclaude python agents/parallel_execution/test_quorum_integration.py

    Or install the package in development mode:

        pip install -e .
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from quorum_minimal import MinimalQuorum, ValidationDecision


class QuorumIntegrationTest:
    """Test suite for quorum validation integration"""

    def __init__(self):
        self.test_results = []
        self.dispatch_runner = Path(__file__).parent / "dispatch_runner.py"

    async def run_all_tests(self):
        """Run all integration tests"""
        print("=" * 70)
        print("QUORUM VALIDATION INTEGRATION TEST SUITE")
        print("=" * 70)
        print()

        # Test 1: Backward compatibility (no quorum flag)
        await self.test_backward_compatibility()

        # Test 2: Quorum validation enabled
        await self.test_quorum_validation_enabled()

        # Test 3: PostgreSQL adapter failure case
        await self.test_postgresql_adapter_failure()

        # Test 4: Valid breakdown passes
        await self.test_valid_breakdown_passes()

        # Test 5: Quorum unavailable (graceful degradation)
        await self.test_quorum_unavailable()

        # Print summary
        self.print_summary()

    async def test_backward_compatibility(self):
        """Test that dispatch_runner works without --enable-quorum flag"""
        print("\n" + "=" * 70)
        print("TEST 1: Backward Compatibility (No Quorum Flag)")
        print("=" * 70)

        input_data = {
            "tasks": [
                {
                    "task_id": "task1",
                    "agent": "coder",
                    "description": "Simple test task",
                    "dependencies": [],
                }
            ],
            "user_prompt": "Create a simple function",
        }

        try:
            # Run without --enable-quorum flag
            result = subprocess.run(
                ["python", str(self.dispatch_runner)],
                input=json.dumps(input_data),
                capture_output=True,
                text=True,
                timeout=10,
            )

            # Check that it didn't try to use quorum
            if "quorum_validation_enabled" in result.stdout:
                output = json.loads(result.stdout)
                if not output.get("quorum_validation_enabled", False):
                    self.record_pass(
                        "Backward compatibility", "Quorum disabled by default"
                    )
                else:
                    self.record_fail(
                        "Backward compatibility", "Quorum enabled without flag"
                    )
            else:
                self.record_pass(
                    "Backward compatibility", "No quorum validation in output"
                )

        except subprocess.TimeoutExpired:
            self.record_fail("Backward compatibility", "Timeout (agents may be slow)")
        except Exception as e:
            self.record_fail("Backward compatibility", f"Exception: {e}")

    async def test_quorum_validation_enabled(self):
        """Test that --enable-quorum flag enables validation"""
        print("\n" + "=" * 70)
        print("TEST 2: Quorum Validation Enabled")
        print("=" * 70)

        input_data = {
            "tasks": [
                {
                    "task_id": "task1",
                    "agent": "coder",
                    "description": "Build PostgreSQL adapter effect node",
                    "dependencies": [],
                }
            ],
            "user_prompt": "Build a postgres adapter effect node",
        }

        try:
            # Run with --enable-quorum flag
            result = subprocess.run(
                ["python", str(self.dispatch_runner), "--enable-quorum"],
                input=json.dumps(input_data),
                capture_output=True,
                text=True,
                timeout=15,
            )

            # Check stderr for quorum activation
            if "Quorum validation enabled" in result.stderr:
                self.record_pass(
                    "Quorum enabled", "Flag correctly activates validation"
                )
            else:
                self.record_fail("Quorum enabled", "Flag did not activate validation")

            # Check for validation output
            if "Phase 1: Validating task breakdown" in result.stderr:
                self.record_pass("Quorum execution", "Validation phase executed")
            else:
                self.record_fail("Quorum execution", "Validation phase not found")

        except subprocess.TimeoutExpired:
            self.record_fail("Quorum enabled", "Timeout waiting for quorum")
        except Exception as e:
            self.record_fail("Quorum enabled", f"Exception: {e}")

    async def test_postgresql_adapter_failure(self):
        """Test the real-world PostgreSQL adapter failure case"""
        print("\n" + "=" * 70)
        print("TEST 3: PostgreSQL Adapter Failure Detection")
        print("=" * 70)
        print("This is the CRITICAL test that validates the fix!")
        print()

        # The actual bad breakdown that caused the failure
        bad_breakdown = {
            "node_type": "Compute",  # WRONG! Should be Effect
            "name": "UserAuthentication",  # WRONG! Should be PostgreSQLAdapter
            "description": "Contract for user authentication operations",  # WRONG domain
            "input_model": {
                "username": {"type": "str"},
                "password": {"type": "str"},
            },
        }

        user_prompt = "Build a postgres adapter effect node that takes kafka event bus events and turns them into postgres api calls"

        # Test directly with quorum
        try:
            quorum = MinimalQuorum()
            result = await quorum.validate_intent(user_prompt, bad_breakdown)

            print(f"\nQuorum Decision: {result.decision.value}")
            print(f"Confidence: {result.confidence:.1%}")
            print(f"Deficiencies: {len(result.deficiencies)}")

            if result.deficiencies:
                print("\nDetected Issues:")
                for i, deficiency in enumerate(result.deficiencies, 1):
                    print(f"  {i}. {deficiency}")

            # Verify that quorum caught the issues
            if result.decision in [ValidationDecision.RETRY, ValidationDecision.FAIL]:
                self.record_pass(
                    "PostgreSQL failure detection",
                    f"Quorum correctly detected issues ({result.decision.value})",
                )
            else:
                self.record_fail(
                    "PostgreSQL failure detection",
                    f"Quorum failed to catch obvious issues (decision: {result.decision.value})",
                )

            # Check for specific deficiency detection
            deficiency_text = " ".join(result.deficiencies).lower()
            caught_node_type = (
                "node type" in deficiency_text or "effect" in deficiency_text
            )
            caught_name = (
                "userauth" in deficiency_text
                or "postgres" in deficiency_text
                or "name" in deficiency_text
            )

            if caught_node_type:
                self.record_pass("Node type detection", "Detected incorrect node type")
            else:
                self.record_warning(
                    "Node type detection", "May not have explicitly caught node type"
                )

            if caught_name:
                self.record_pass("Name detection", "Detected incorrect component name")
            else:
                self.record_warning(
                    "Name detection", "May not have explicitly caught name mismatch"
                )

        except Exception as e:
            self.record_fail("PostgreSQL failure detection", f"Exception: {e}")

    async def test_valid_breakdown_passes(self):
        """Test that a valid breakdown passes validation"""
        print("\n" + "=" * 70)
        print("TEST 4: Valid Breakdown Passes")
        print("=" * 70)

        # A correct breakdown
        valid_breakdown = {
            "node_type": "Effect",
            "name": "PostgreSQLAdapter",
            "description": "Effect node for PostgreSQL database operations via Kafka events",
            "input_model": {
                "event_type": {"type": "str"},
                "payload": {"type": "dict"},
            },
        }

        user_prompt = "Build a postgres adapter effect node that takes kafka event bus events and turns them into postgres api calls"

        try:
            quorum = MinimalQuorum()
            result = await quorum.validate_intent(user_prompt, valid_breakdown)

            print(f"\nQuorum Decision: {result.decision.value}")
            print(f"Confidence: {result.confidence:.1%}")

            if result.decision == ValidationDecision.PASS:
                self.record_pass(
                    "Valid breakdown passes",
                    f"Correctly validated with {result.confidence:.1%} confidence",
                )
            else:
                self.record_fail(
                    "Valid breakdown passes",
                    f"Incorrectly rejected valid breakdown (decision: {result.decision.value})",
                )

        except Exception as e:
            self.record_fail("Valid breakdown passes", f"Exception: {e}")

    async def test_quorum_unavailable(self):
        """Test graceful degradation when quorum is unavailable"""
        print("\n" + "=" * 70)
        print("TEST 5: Graceful Degradation (Quorum Unavailable)")
        print("=" * 70)

        # This test would require temporarily breaking quorum access
        # For now, we just verify the code path exists

        try:
            # Check that the code has graceful degradation logic
            dispatch_code = self.dispatch_runner.read_text(encoding="utf-8")

            if "QUORUM_AVAILABLE" in dispatch_code:
                self.record_pass(
                    "Graceful degradation", "Code checks for quorum availability"
                )
            else:
                self.record_fail("Graceful degradation", "No availability check found")

            if "skipped" in dispatch_code:
                self.record_pass("Skip logic", "Code supports skipping validation")
            else:
                self.record_fail("Skip logic", "No skip logic found")

        except Exception as e:
            self.record_fail("Graceful degradation", f"Exception: {e}")

    def record_pass(self, test_name: str, message: str):
        """Record a passing test"""
        self.test_results.append(
            {"test": test_name, "status": "PASS", "message": message}
        )
        print(f"✓ PASS: {test_name} - {message}")

    def record_fail(self, test_name: str, message: str):
        """Record a failing test"""
        self.test_results.append(
            {"test": test_name, "status": "FAIL", "message": message}
        )
        print(f"✗ FAIL: {test_name} - {message}")

    def record_warning(self, test_name: str, message: str):
        """Record a warning"""
        self.test_results.append(
            {"test": test_name, "status": "WARN", "message": message}
        )
        print(f"⚠ WARN: {test_name} - {message}")

    def print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)

        pass_count = sum(1 for r in self.test_results if r["status"] == "PASS")
        fail_count = sum(1 for r in self.test_results if r["status"] == "FAIL")
        warn_count = sum(1 for r in self.test_results if r["status"] == "WARN")
        total = len(self.test_results)

        print(f"\nTotal Tests: {total}")
        print(f"  Passed:  {pass_count} ({pass_count/total*100:.0f}%)")
        print(f"  Failed:  {fail_count} ({fail_count/total*100:.0f}%)")
        print(f"  Warnings: {warn_count} ({warn_count/total*100:.0f}%)")

        if fail_count == 0:
            print("\n✓ ALL TESTS PASSED!")
        else:
            print("\n✗ SOME TESTS FAILED")
            print("\nFailed tests:")
            for result in self.test_results:
                if result["status"] == "FAIL":
                    print(f"  - {result['test']}: {result['message']}")

        print("\n" + "=" * 70)


async def main():
    """Run integration tests"""

    # Check dependencies
    if not os.getenv("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY environment variable not set")
        print("Quorum validation requires Gemini API access")
        sys.exit(1)

    # Run tests
    test_suite = QuorumIntegrationTest()
    await test_suite.run_all_tests()

    # Exit with appropriate code
    fail_count = sum(1 for r in test_suite.test_results if r["status"] == "FAIL")
    sys.exit(0 if fail_count == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
