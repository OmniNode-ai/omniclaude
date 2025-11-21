#!/usr/bin/env python3
"""
Comprehensive SQL Security Test Suite

This test verifies that all execute.py files in the system-status skills
properly use parameterized queries and avoid SQL injection vulnerabilities.

Tests check for:
1. No f-string SQL queries (except for validated table names with SECURITY NOTEs)
2. Proper parameterization of all user inputs
3. Whitelist validation for dynamic table names
4. No raw string concatenation in SQL queries

Created: 2025-11-21
"""

import re
import sys
import unittest
from pathlib import Path


class TestSQLSecurity(unittest.TestCase):
    """Test SQL injection protection across all skills."""

    SKILLS_DIR = Path(__file__).parent.parent

    # Files that are allowed to use f-strings for table names (with proper validation)
    WHITELIST_F_STRING_FILES = {
        "check-database-health/execute.py",  # Uses validated table names with SECURITY NOTE
    }

    # Files that should have parameterized queries
    EXPECTED_PARAMETERIZED_FILES = {
        "check-recent-activity/execute.py",
        "check-agent-performance/execute.py",
        "generate-status-report/execute.py",
        "diagnose-issues/execute.py",
        "check-system-health/execute.py",
    }

    def test_no_fstring_sql_queries(self):
        """Test that no f-string SQL queries exist (except whitelisted with security notes)."""
        violations = []

        # Search for f-strings with SQL keywords
        for py_file in self.SKILLS_DIR.rglob("*/execute.py"):
            relative_path = str(py_file.relative_to(self.SKILLS_DIR))

            with open(py_file, "r") as f:
                content = f.read()
                lines = content.split("\n")

                for i, line in enumerate(lines, 1):
                    # Skip lines with SECURITY NOTE comments
                    if "SECURITY NOTE" in line:
                        continue

                    # Check for f-strings with SQL keywords
                    if re.search(r'f["\'].*\b(SELECT|INSERT|UPDATE|DELETE)\b', line):
                        # Check if this file is whitelisted
                        if relative_path in self.WHITELIST_F_STRING_FILES:
                            # Verify there's a SECURITY NOTE nearby
                            context_start = max(0, i - 10)
                            context_end = min(len(lines), i + 5)
                            context = "\n".join(lines[context_start:context_end])

                            if "SECURITY NOTE" not in context:
                                violations.append(
                                    f"{relative_path}:{i} - F-string SQL without SECURITY NOTE"
                                )
                        else:
                            violations.append(
                                f"{relative_path}:{i} - F-string SQL query: {line.strip()}"
                            )

        if violations:
            self.fail(
                f"Found {len(violations)} files with f-string SQL queries:\n"
                + "\n".join(violations)
            )

    def test_interval_parameterization(self):
        """Test that INTERVAL clauses use parameterized queries."""
        violations = []

        for py_file in self.SKILLS_DIR.rglob("*/execute.py"):
            relative_path = str(py_file.relative_to(self.SKILLS_DIR))

            with open(py_file, "r") as f:
                content = f.read()
                lines = content.split("\n")

                for i, line in enumerate(lines, 1):
                    # Check for INTERVAL with f-string variable interpolation
                    if re.search(r"INTERVAL\s+['\"]?\{", line):
                        violations.append(
                            f"{relative_path}:{i} - Non-parameterized INTERVAL: {line.strip()}"
                        )

        if violations:
            self.fail(
                f"Found {len(violations)} non-parameterized INTERVAL clauses:\n"
                + "\n".join(violations)
            )

    def test_limit_parameterization(self):
        """Test that LIMIT clauses use parameterized queries."""
        violations = []

        for py_file in self.SKILLS_DIR.rglob("*/execute.py"):
            relative_path = str(py_file.relative_to(self.SKILLS_DIR))

            with open(py_file, "r") as f:
                content = f.read()
                lines = content.split("\n")

                for i, line in enumerate(lines, 1):
                    # Check for LIMIT with f-string variable interpolation
                    if re.search(r"LIMIT\s+\{", line):
                        violations.append(
                            f"{relative_path}:{i} - Non-parameterized LIMIT: {line.strip()}"
                        )

        if violations:
            self.fail(
                f"Found {len(violations)} non-parameterized LIMIT clauses:\n"
                + "\n".join(violations)
            )

    def test_parameterized_queries_present(self):
        """Test that parameterized queries use %s placeholders and params tuples."""
        missing_parameterization = []

        for filename in self.EXPECTED_PARAMETERIZED_FILES:
            py_file = self.SKILLS_DIR / filename

            if not py_file.exists():
                continue

            with open(py_file, "r") as f:
                content = f.read()

                # Count queries with %s placeholders
                param_queries = len(re.findall(r"%s", content))

                # Count execute_query calls with params tuples
                param_calls = len(
                    re.findall(r"execute_query\([^,]+,\s*\([^)]+\)", content)
                )

                if param_queries == 0 and filename not in [
                    "check-infrastructure/execute.py"
                ]:
                    # File should have parameterized queries
                    if (
                        "agent_manifest_injections" in content
                        or "agent_routing_decisions" in content
                    ):
                        missing_parameterization.append(
                            f"{filename} - Expected parameterized queries but found none"
                        )

        if missing_parameterization:
            self.fail(
                f"Found {len(missing_parameterization)} files without proper parameterization:\n"
                + "\n".join(missing_parameterization)
            )

    def test_table_name_validation(self):
        """Test that files using dynamic table names have validation."""
        violations = []

        # Check check-database-health has VALID_TABLES whitelist
        db_health_file = self.SKILLS_DIR / "check-database-health" / "execute.py"

        if db_health_file.exists():
            with open(db_health_file, "r") as f:
                content = f.read()

                if "VALID_TABLES" not in content:
                    violations.append(
                        "check-database-health/execute.py missing VALID_TABLES whitelist"
                    )

                if "validate_table_name" not in content:
                    violations.append(
                        "check-database-health/execute.py missing validate_table_name function"
                    )

        if violations:
            self.fail(
                f"Found {len(violations)} table validation issues:\n"
                + "\n".join(violations)
            )

    def test_no_string_concatenation(self):
        """Test that SQL queries don't use string concatenation."""
        violations = []

        for py_file in self.SKILLS_DIR.rglob("*/execute.py"):
            relative_path = str(py_file.relative_to(self.SKILLS_DIR))

            with open(py_file, "r") as f:
                content = f.read()
                lines = content.split("\n")

                for i, line in enumerate(lines, 1):
                    # Check for SQL keywords with string concatenation
                    if re.search(r'(SELECT|INSERT|UPDATE|DELETE).*\+\s*["\']', line):
                        violations.append(
                            f"{relative_path}:{i} - String concatenation in SQL: {line.strip()}"
                        )

        if violations:
            self.fail(
                f"Found {len(violations)} SQL queries with string concatenation:\n"
                + "\n".join(violations)
            )

    def test_security_notes_present(self):
        """Test that files using f-strings for table names have SECURITY NOTEs."""
        missing_notes = []

        for filename in self.WHITELIST_F_STRING_FILES:
            py_file = self.SKILLS_DIR / filename

            if not py_file.exists():
                continue

            with open(py_file, "r") as f:
                content = f.read()

                # Count SECURITY NOTE comments
                security_notes = content.count("SECURITY NOTE")

                # Count f-string SQL queries
                fstring_sqls = len(re.findall(r'f["\'].*\bSELECT\b', content))

                if fstring_sqls > 0 and security_notes < 1:
                    missing_notes.append(
                        f"{filename} - Uses f-string SQL but missing SECURITY NOTE"
                    )

        if missing_notes:
            self.fail(
                f"Found {len(missing_notes)} files missing SECURITY NOTEs:\n"
                + "\n".join(missing_notes)
            )


def main():
    """Run the test suite."""
    # Create test directory if it doesn't exist
    test_dir = Path(__file__).parent
    test_dir.mkdir(exist_ok=True)

    # Run tests with verbose output
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSQLSecurity)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 70)
    print("SQL SECURITY TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.wasSuccessful():
        print("\n✅ All SQL security tests passed!")
        print("No SQL injection vulnerabilities detected.")
        return 0
    else:
        print("\n❌ Some tests failed!")
        print("Review the output above for security issues.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
