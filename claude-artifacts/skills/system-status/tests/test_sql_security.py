"""
SQL security tests - Verify parameterized queries and no string interpolation.

Tests that all SQL queries use proper parameterization instead of:
- f-strings
- String concatenation
- .format() calls

**IMPORTANT**: Test "failures" indicate real security issues in production code.
If these tests fail, the PRODUCTION CODE needs to be fixed (not the tests).

Expected behavior:
  ✅ All tests pass → Production code is secure
  ❌ Tests fail → Security vulnerabilities found in skills (fix production code)

Created: 2025-11-20
"""

import re
import sys
from pathlib import Path

import pytest

# Import load_skill_module from conftest
conftest_path = Path(__file__).parent / "conftest.py"
import importlib.util

spec = importlib.util.spec_from_file_location("conftest", conftest_path)
conftest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conftest)
load_skill_module = conftest.load_skill_module


class TestSQLParameterization:
    """Test that all SQL queries use parameterized queries."""

    @pytest.fixture
    def skill_paths(self):
        """Get all skill execute.py files."""
        base_path = Path(__file__).parent.parent
        return list(base_path.glob("*/execute.py"))

    def test_no_fstring_in_sql(self, skill_paths):
        """Verify no f-strings are used in SQL queries."""
        violations = []

        for skill_file in skill_paths:
            content = skill_file.read_text()

            # Look for SQL query patterns with f-strings
            # Pattern: f""" or f''' or f" or f'
            fstring_pattern = re.compile(
                r'f["\']["\'][\'"]\s*(SELECT|INSERT|UPDATE|DELETE)', re.IGNORECASE
            )

            matches = fstring_pattern.findall(content)
            if matches:
                violations.append(
                    {
                        "file": skill_file.name,
                        "skill": skill_file.parent.name,
                        "count": len(matches),
                    }
                )

        assert (
            len(violations) == 0
        ), f"Found {len(violations)} files with f-string SQL queries:\n" + "\n".join(
            f"  - {v['skill']}/{v['file']}: {v['count']} violations" for v in violations
        )

    def test_no_string_concat_in_sql(self, skill_paths):
        """Verify no string concatenation in SQL queries."""
        violations = []

        for skill_file in skill_paths:
            content = skill_file.read_text()

            # Look for string concatenation patterns in SQL
            # Pattern: "SELECT ... " + variable
            concat_pattern = re.compile(
                r'["\']["\']["\'].*?(SELECT|INSERT|UPDATE|DELETE).*?["\']["\']["\'].*?\+',
                re.IGNORECASE,
            )

            if concat_pattern.search(content):
                violations.append(
                    {
                        "file": skill_file.name,
                        "skill": skill_file.parent.name,
                    }
                )

        assert len(violations) == 0, (
            f"Found {len(violations)} files with string concatenation in SQL:\n"
            + "\n".join(f"  - {v['skill']}/{v['file']}" for v in violations)
        )

    def test_uses_parameterized_queries(self, skill_paths):
        """Verify SQL queries use %s or %(name)s parameterization when needed."""
        # Skills that don't use SQL (use Kafka/Qdrant/Docker instead)
        non_sql_skills = {
            "check-kafka-topics",
            "check-pattern-discovery",
            "check-service-status",
        }

        files_with_dynamic_sql = []
        files_with_params = []

        for skill_file in skill_paths:
            content = skill_file.read_text()

            # Skip skills that don't use SQL
            if skill_file.parent.name in non_sql_skills:
                continue

            # Check if file has SQL queries with dynamic content (placeholders)
            # Static queries (like COUNT(*) FROM information_schema WHERE table_schema = 'public')
            # don't need parameterization because they don't accept user input
            has_dynamic_sql = False
            if re.search(r"(SELECT|INSERT|UPDATE|DELETE)", content, re.IGNORECASE):
                # Check for SQL placeholder patterns that require parameterization
                # %s in SQL context (not Python logging format strings)
                # Exclude %(asctime)s, %(levelname)s, %(name)s, %(message)s (logging formats)
                logging_formats = r"%\((asctime|levelname|name|message|filename|lineno|funcName|pathname)\)s"
                sql_placeholders = re.findall(r"%s|%\([\w_]+\)s", content)
                # Filter out logging format strings
                sql_placeholders = [
                    p for p in sql_placeholders if not re.match(logging_formats, p)
                ]
                if sql_placeholders:
                    has_dynamic_sql = True

            if has_dynamic_sql:
                files_with_dynamic_sql.append(skill_file.parent.name)

                # Check if file uses parameterized queries (psycopg2 %s or params=)
                # Matches: params=(...) or execute_query(..., (...)) or execute_query(..., params=...)
                # Use DOTALL flag to handle multi-line execute_query calls
                if re.search(r"params\s*=", content) or re.search(
                    r"execute_query\s*\([^,]+,\s*\([^)]+\)", content, re.DOTALL
                ):
                    files_with_params.append(skill_file.parent.name)

        # All files with dynamic SQL should use parameterized queries
        files_missing_params = set(files_with_dynamic_sql) - set(files_with_params)

        assert len(files_missing_params) == 0, (
            f"Found {len(files_missing_params)} files with SQL but no parameterization:\n"
            + "\n".join(f"  - {name}" for name in sorted(files_missing_params))
        )

    def test_interval_concatenation_safe(self, skill_paths):
        """Verify INTERVAL concatenation is parameterized (not string-based)."""
        violations = []

        for skill_file in skill_paths:
            content = skill_file.read_text()

            # Look for unsafe INTERVAL patterns
            # Safe:   INTERVAL %s
            # Unsafe: INTERVAL '" + timeframe + "'
            unsafe_interval = re.compile(r'INTERVAL\s*["\'].*?\+', re.IGNORECASE)

            if unsafe_interval.search(content):
                violations.append(
                    {
                        "file": skill_file.name,
                        "skill": skill_file.parent.name,
                    }
                )

        assert len(violations) == 0, (
            f"Found {len(violations)} files with unsafe INTERVAL concatenation:\n"
            + "\n".join(f"  - {v['skill']}/{v['file']}" for v in violations)
        )


class TestSQLInjectionPrevention:
    """Test SQL injection attack prevention."""

    def test_malicious_limit_rejected(self):
        """Test that malicious limit values are rejected."""
        execute = load_skill_module("check-recent-activity")
        validate_limit = execute.validate_limit

        malicious_inputs = [
            "10; DROP TABLE agent_routing_decisions;",
            "10 OR 1=1",
            "10' OR '1'='1",
            "10/**/OR/**/1=1",
        ]

        for malicious in malicious_inputs:
            with pytest.raises(Exception):
                validate_limit(malicious)

    def test_malicious_timeframe_rejected(self):
        """Test that malicious timeframe values are rejected."""
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
        from timeframe_helper import parse_timeframe

        malicious_inputs = [
            "5m; DROP TABLE agent_routing_decisions;",
            "5m' OR '1'='1",
            "1h/**/UNION/**/SELECT",
            "'; DELETE FROM agent_routing_decisions WHERE '1'='1",
        ]

        for malicious in malicious_inputs:
            with pytest.raises(ValueError):
                parse_timeframe(malicious)

    def test_no_raw_user_input_in_queries(self, tmp_path):
        """Test that user input is never directly inserted into queries."""
        # Create a test script that simulates unsafe query
        unsafe_code = """
def execute_unsafe_query(limit):
    query = f"SELECT * FROM table LIMIT {limit}"  # UNSAFE
    return query
"""
        test_file = tmp_path / "unsafe.py"
        test_file.write_text(unsafe_code)

        # Verify we can detect this pattern
        content = test_file.read_text()
        assert re.search(
            r'f["\'].*?{.*?}', content
        ), "Should detect f-string interpolation"

        # Verify our actual skills don't have this pattern
        base_path = Path(__file__).parent.parent
        for skill_file in base_path.glob("*/execute.py"):
            content = skill_file.read_text()

            # Check for f-string with SQL and variable interpolation
            unsafe_pattern = re.compile(
                r'f["\']["\'][\'"]\s*(SELECT|INSERT|UPDATE|DELETE).*?{', re.IGNORECASE
            )

            assert not unsafe_pattern.search(
                content
            ), f"Found unsafe query in {skill_file.parent.name}/{skill_file.name}"
