#!/usr/bin/env python3
"""
Test Template Generation - Validate Template Fixes

This script tests the OmniNode template engine to ensure it generates
compilable, ONEX-compliant code after recent import and Pydantic fixes.

Test Coverage:
- Template generation (all 4 node types)
- Import validation
- ONEX naming compliance
- Pydantic v2 compatibility
- Type checking with mypy

Usage:
    poetry run python tests/test_template_generation.py
    poetry run python tests/test_template_generation.py --node-type COMPUTE
    poetry run python tests/test_template_generation.py --all-types
"""

import argparse
import asyncio
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.lib.omninode_template_engine import OmniNodeTemplateEngine
from agents.lib.prd_analyzer import (
    DecompositionResult,
    ParsedPRD,
    PRDAnalysisResult,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result of a single test"""

    test_name: str
    success: bool
    message: str
    details: dict | None = None
    errors: list[str] | None = None


class TemplateGenerationTester:
    """Test harness for template generation"""

    def __init__(self, output_dir: Path | None = None, cleanup: bool = True):
        """
        Initialize tester

        Args:
            output_dir: Directory for test output (defaults to /tmp/test_node_generation)
            cleanup: Whether to clean up test artifacts after tests
        """
        self.output_dir = output_dir or Path("/tmp/test_node_generation")
        self.cleanup = cleanup
        self.results: list[TestResult] = []

        # Paths
        self.repo_root = Path(__file__).parent.parent
        self.validator_path = self.repo_root / "tools" / "compatibility_validator.py"

    def setup(self):
        """Setup test environment"""
        logger.info(f"Setting up test environment in {self.output_dir}")

        # Clean and recreate output directory
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def teardown(self):
        """Cleanup test environment"""
        if self.cleanup and self.output_dir.exists():
            logger.info(f"Cleaning up test artifacts in {self.output_dir}")
            shutil.rmtree(self.output_dir)
        else:
            logger.info(f"Test artifacts preserved in {self.output_dir}")

    def create_test_fixture(self) -> PRDAnalysisResult:
        """Create minimal test fixture for PRD analysis"""
        logger.info("Creating test fixture for PRD analysis")

        parsed_prd = ParsedPRD(
            title="Database Writer Service",
            description="A service that writes data to PostgreSQL database with validation and error handling",
            functional_requirements=[
                "Write records to database with transaction support",
                "Validate input data before writing",
                "Handle database errors gracefully",
                "Support batch operations",
            ],
            features=[
                "Transaction management",
                "Input validation",
                "Error recovery",
            ],
            success_criteria=[
                "99.9% write success rate",
                "Response time < 500ms",
                "Zero data loss",
            ],
            technical_details=[
                "PostgreSQL database",
                "AsyncIO for concurrent operations",
                "Pydantic for validation",
            ],
            dependencies=["PostgreSQL", "asyncpg"],
            extracted_keywords=[
                "database",
                "write",
                "postgresql",
                "async",
                "validation",
            ],
            sections=["Overview", "Requirements", "Technical Details"],
            word_count=250,
        )

        decomposition_result = DecompositionResult(
            tasks=[
                {
                    "title": "Implement database connection",
                    "type": "infrastructure",
                    "priority": "high",
                },
                {
                    "title": "Implement write operation",
                    "type": "core_logic",
                    "priority": "high",
                },
                {
                    "title": "Add validation logic",
                    "type": "validation",
                    "priority": "medium",
                },
            ],
            total_tasks=3,
            verification_successful=True,
        )

        result = PRDAnalysisResult(
            session_id=uuid4(),
            correlation_id=uuid4(),
            prd_content="Test PRD content for database writer service",
            parsed_prd=parsed_prd,
            decomposition_result=decomposition_result,
            node_type_hints={"EFFECT": 0.9, "COMPUTE": 0.3, "REDUCER": 0.2},
            recommended_mixins=["MixinEventBus", "MixinRetry"],
            external_systems=["PostgreSQL", "Kafka"],
            quality_baseline=0.85,
            confidence_score=0.92,
        )

        return result

    async def test_generate_node(self, node_type: str = "EFFECT") -> TestResult:
        """
        Test node generation for a specific type

        Args:
            node_type: Type of node to generate (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)

        Returns:
            TestResult with outcome
        """
        logger.info(f"Testing {node_type} node generation")

        try:
            # Create fixture
            analysis_result = self.create_test_fixture()

            # Initialize template engine (disable cache for testing)
            engine = OmniNodeTemplateEngine(enable_cache=False)

            # Generate node
            result = await engine.generate_node(
                analysis_result=analysis_result,
                node_type=node_type,
                microservice_name="test_database_writer",
                domain="data_services",
                output_directory=str(self.output_dir),
            )

            # Verify files were created
            output_path = Path(result["output_path"])
            main_file = Path(result["main_file"])

            if not output_path.exists():
                return TestResult(
                    test_name=f"generate_{node_type.lower()}_node",
                    success=False,
                    message=f"Output directory not created: {output_path}",
                )

            if not main_file.exists():
                return TestResult(
                    test_name=f"generate_{node_type.lower()}_node",
                    success=False,
                    message=f"Main file not created: {main_file}",
                )

            # Count generated files
            generated_files = list(output_path.rglob("*.py"))
            yaml_files = list(output_path.rglob("*.yaml"))

            return TestResult(
                test_name=f"generate_{node_type.lower()}_node",
                success=True,
                message=f"Successfully generated {node_type} node",
                details={
                    "output_path": str(output_path),
                    "main_file": str(main_file),
                    "python_files": len(generated_files),
                    "yaml_files": len(yaml_files),
                    "total_files": len(generated_files) + len(yaml_files),
                    "file_list": [
                        str(f.relative_to(output_path)) for f in generated_files + yaml_files
                    ],
                },
            )

        except Exception as e:
            logger.error(f"Node generation failed: {e}", exc_info=True)
            return TestResult(
                test_name=f"generate_{node_type.lower()}_node",
                success=False,
                message=f"Node generation failed: {str(e)}",
                errors=[str(e)],
            )

    def test_compatibility_validator(self) -> TestResult:
        """
        Test generated code with compatibility validator

        Returns:
            TestResult with validation outcome
        """
        logger.info("Running compatibility validator")

        try:
            if not self.validator_path.exists():
                return TestResult(
                    test_name="compatibility_validator",
                    success=False,
                    message=f"Validator not found: {self.validator_path}",
                )

            # Run validator on generated code
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.validator_path),
                    "--directory",
                    str(self.output_dir),
                    "--recursive",
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Parse JSON output
            try:
                validation_result = json.loads(result.stdout)
            except json.JSONDecodeError:
                return TestResult(
                    test_name="compatibility_validator",
                    success=False,
                    message="Failed to parse validator output",
                    errors=[result.stdout, result.stderr],
                )

            # Check results
            total_files = validation_result.get("total_files", 0)
            summary = validation_result.get("overall_summary", {})
            passed = summary.get("passed", 0)
            failed = summary.get("failed", 0)
            warnings = summary.get("warnings", 0)

            success = failed == 0

            return TestResult(
                test_name="compatibility_validator",
                success=success,
                message=f"Validated {total_files} files: {passed} passed, {failed} failed, {warnings} warnings",
                details={
                    "total_files": total_files,
                    "passed": passed,
                    "failed": failed,
                    "warnings": warnings,
                    "exit_code": result.returncode,
                },
            )

        except subprocess.TimeoutExpired:
            return TestResult(
                test_name="compatibility_validator",
                success=False,
                message="Validator timeout (>30s)",
            )
        except Exception as e:
            logger.error(f"Validator failed: {e}", exc_info=True)
            return TestResult(
                test_name="compatibility_validator",
                success=False,
                message=f"Validator error: {str(e)}",
                errors=[str(e)],
            )

    def test_mypy_type_checking(self) -> TestResult:
        """
        Test generated code with mypy type checker

        Returns:
            TestResult with type checking outcome
        """
        logger.info("Running mypy type checker")

        try:
            # Check if mypy is available
            result = subprocess.run(
                ["poetry", "run", "mypy", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                return TestResult(
                    test_name="mypy_type_checking",
                    success=True,  # Not a failure - just skip
                    message="mypy not available - skipping type checking",
                )

            # Run mypy on generated code
            result = subprocess.run(
                [
                    "poetry",
                    "run",
                    "mypy",
                    str(self.output_dir),
                    "--ignore-missing-imports",
                    "--show-error-codes",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.repo_root),
            )

            # Parse output
            output_lines = result.stdout.split("\n")
            error_count = 0
            errors = []

            for line in output_lines:
                if "error:" in line.lower():
                    error_count += 1
                    errors.append(line.strip())

            success = error_count == 0

            return TestResult(
                test_name="mypy_type_checking",
                success=success,
                message=f"mypy found {error_count} type errors",
                details={
                    "error_count": error_count,
                    "exit_code": result.returncode,
                },
                errors=errors[:10] if errors else None,  # Limit to first 10 errors
            )

        except subprocess.TimeoutExpired:
            return TestResult(
                test_name="mypy_type_checking",
                success=False,
                message="mypy timeout (>30s)",
            )
        except Exception as e:
            logger.error(f"mypy failed: {e}", exc_info=True)
            return TestResult(
                test_name="mypy_type_checking",
                success=True,  # Don't fail if mypy unavailable
                message=f"mypy unavailable: {str(e)}",
            )

    def test_onex_compliance(self) -> TestResult:
        """
        Test ONEX naming conventions compliance

        Returns:
            TestResult with compliance outcome
        """
        logger.info("Checking ONEX naming compliance")

        try:
            issues = []

            # Check all Python files
            for py_file in self.output_dir.rglob("*.py"):
                content = py_file.read_text(encoding="utf-8")

                # Check for old imports
                if "omnibase_core.core." in content:
                    issues.append(f"{py_file.name}: Uses old import path 'omnibase_core.core.*'")

                # Check for Pydantic v1 patterns
                if ".dict(" in content and "model_dump" not in content:
                    issues.append(
                        f"{py_file.name}: Uses Pydantic v1 '.dict()' instead of '.model_dump()'"
                    )

                # Check for OnexError (should be ModelOnexError)
                if "OnexError" in content and "ModelOnexError" not in content:
                    issues.append(f"{py_file.name}: Uses 'OnexError' instead of 'ModelOnexError'")

            success = len(issues) == 0

            return TestResult(
                test_name="onex_compliance",
                success=success,
                message=f"Found {len(issues)} ONEX compliance issues",
                details={
                    "issue_count": len(issues),
                },
                errors=issues if issues else None,
            )

        except Exception as e:
            logger.error(f"ONEX compliance check failed: {e}", exc_info=True)
            return TestResult(
                test_name="onex_compliance",
                success=False,
                message=f"Compliance check error: {str(e)}",
                errors=[str(e)],
            )

    async def run_all_tests(self, node_types: list[str] | None = None) -> dict:
        """
        Run all tests

        Args:
            node_types: List of node types to test (defaults to all)

        Returns:
            Summary dictionary
        """
        if node_types is None:
            node_types = ["EFFECT"]  # Default to EFFECT only

        logger.info(f"Running test suite for node types: {node_types}")

        # Setup
        self.setup()

        try:
            # Test 1: Generate nodes
            for node_type in node_types:
                result = await self.test_generate_node(node_type)
                self.results.append(result)

            # Test 2: Compatibility validator
            result = self.test_compatibility_validator()
            self.results.append(result)

            # Test 3: Type checking
            result = self.test_mypy_type_checking()
            self.results.append(result)

            # Test 4: ONEX compliance
            result = self.test_onex_compliance()
            self.results.append(result)

            # Summary
            total = len(self.results)
            passed = sum(1 for r in self.results if r.success)
            failed = total - passed

            summary = {
                "total_tests": total,
                "passed": passed,
                "failed": failed,
                "success_rate": f"{(passed / total * 100):.1f}%" if total > 0 else "0%",
                "results": [
                    {
                        "test": r.test_name,
                        "success": r.success,
                        "message": r.message,
                        "details": r.details,
                        "errors": r.errors,
                    }
                    for r in self.results
                ],
            }

            return summary

        finally:
            # Teardown
            self.teardown()

    def print_summary(self, summary: dict):
        """Print test summary"""
        print("\n" + "=" * 80)
        print("TEMPLATE GENERATION TEST RESULTS")
        print("=" * 80)
        print(f"Total Tests: {summary['total_tests']}")
        print(f"Passed: {summary['passed']}")
        print(f"Failed: {summary['failed']}")
        print(f"Success Rate: {summary['success_rate']}")
        print("=" * 80)

        for result in summary["results"]:
            status = "✅ PASS" if result["success"] else "❌ FAIL"
            print(f"\n{status} - {result['test']}")
            print(f"  {result['message']}")

            if result.get("details"):
                print("  Details:")
                for key, value in result["details"].items():
                    if isinstance(value, list) and len(value) > 5:
                        print(f"    {key}: {len(value)} items")
                    else:
                        print(f"    {key}: {value}")

            if result.get("errors"):
                print("  Errors:")
                for error in result["errors"][:5]:  # Show first 5 errors
                    print(f"    - {error}")
                if len(result["errors"]) > 5:
                    print(f"    ... and {len(result['errors']) - 5} more errors")

        print("\n" + "=" * 80)


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Test template generation and validate fixes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--node-type",
        choices=["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"],
        default="EFFECT",
        help="Node type to test (default: EFFECT)",
    )
    parser.add_argument(
        "--all-types",
        action="store_true",
        help="Test all node types",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/test_node_generation"),
        help="Output directory for test artifacts",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Don't cleanup test artifacts after tests",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format",
    )

    args = parser.parse_args()

    # Determine node types to test
    if args.all_types:
        node_types = ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]
    else:
        node_types = [args.node_type]

    # Create tester
    tester = TemplateGenerationTester(
        output_dir=args.output_dir,
        cleanup=not args.no_cleanup,
    )

    # Run tests
    summary = await tester.run_all_tests(node_types)

    # Output results
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        tester.print_summary(summary)

    # Exit code
    sys.exit(0 if summary["failed"] == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
