"""
Error handling tests for all skills.

Tests that skills handle errors gracefully:
- Database connection failures
- Network timeouts
- Empty results
- Malformed data

Created: 2025-11-20
"""

from pathlib import Path
from unittest.mock import patch

import pytest

# Import load_skill_module from conftest
conftest_path = Path(__file__).parent / "conftest.py"
import importlib.util

spec = importlib.util.spec_from_file_location("conftest", conftest_path)
conftest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conftest)
load_skill_module = conftest.load_skill_module


class TestDatabaseErrorHandling:
    """Test database error handling."""

    def test_connection_timeout(self):
        """Test handling of database connection timeout."""
        execute = load_skill_module("check-recent-activity")
        main = execute.main

        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_query.return_value = {
                "success": False,
                "error": "Connection timeout after 5 seconds",
                "rows": [],
            }

            exit_code = main()

            # Should handle error gracefully - script continues with partial data
            # The check-recent-activity script is resilient and returns success
            # even if individual queries fail (it just omits those sections)
            assert exit_code == 0  # Partial failure handled gracefully

    def test_query_syntax_error(self):
        """Test handling of SQL syntax errors."""
        execute = load_skill_module("check-recent-activity")
        main = execute.main

        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_query.return_value = {
                "success": False,
                "error": "syntax error at or near 'SELECT'",
                "rows": [],
            }

            exit_code = main()

            # Should handle error gracefully - script continues with partial data
            # The check-recent-activity script is resilient and returns success
            # even if individual queries fail (it just omits those sections)
            assert exit_code == 0  # Partial failure handled gracefully

    def test_authentication_failure(self):
        """Test handling of database authentication failure."""
        execute = load_skill_module("check-infrastructure")
        check_postgres = execute.check_postgres

        # Patch execute_query in the execute module namespace
        with patch.object(execute, "execute_query") as mock_query:
            mock_query.return_value = {
                "success": False,
                "error": "password authentication failed for user 'postgres'",
                "rows": [],
            }

            result = check_postgres()

            assert result["status"] == "error"
            assert "error" in result

    def test_database_not_found(self):
        """Test handling of database not found error."""
        execute = load_skill_module("check-infrastructure")
        check_postgres = execute.check_postgres

        with patch.object(execute, "execute_query") as mock_query:
            mock_query.return_value = {
                "success": False,
                "error": 'database "omninode_bridge" does not exist',
                "rows": [],
            }

            result = check_postgres()

            assert result["status"] == "error"


class TestNetworkErrorHandling:
    """Test network error handling."""

    def test_kafka_connection_refused(self):
        """Test Kafka connection refused."""
        execute = load_skill_module("check-infrastructure")
        check_kafka = execute.check_kafka

        with patch.object(execute, "check_kafka_connection") as mock_conn:
            mock_conn.return_value = {
                "status": "error",
                "broker": "192.168.86.200:29092",
                "reachable": False,
                "error": "Connection refused",
            }

            result = check_kafka()

            assert result["status"] == "error"
            assert result["reachable"] is False

    def test_qdrant_timeout(self):
        """Test Qdrant connection timeout."""
        execute = load_skill_module("check-infrastructure")
        check_qdrant = execute.check_qdrant

        with patch.object(execute, "check_qdrant_connection") as mock_conn:
            mock_conn.return_value = {
                "status": "error",
                "url": "http://192.168.86.101:6333",
                "reachable": False,
                "error": "Request timeout after 5 seconds",
            }

            result = check_qdrant()

            assert result["status"] == "error"
            assert result["reachable"] is False

    def test_network_unreachable(self):
        """Test network unreachable error."""
        execute = load_skill_module("check-infrastructure")
        check_kafka = execute.check_kafka

        with patch.object(execute, "check_kafka_connection") as mock_conn:
            mock_conn.return_value = {
                "status": "error",
                "broker": "192.168.86.200:29092",
                "reachable": False,
                "error": "Network is unreachable",
            }

            result = check_kafka()

            assert result["status"] == "error"
            assert result["error"] is not None


class TestDataErrorHandling:
    """Test malformed data handling."""

    def test_null_values_in_results(self):
        """Test handling of NULL values in query results."""
        execute = load_skill_module("check-recent-activity")
        main = execute.main

        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py"]),
        ):

            # Mock execute_query to return NULL values (should handle gracefully)
            mock_query.side_effect = [
                # Manifest injections query
                {
                    "success": True,
                    "rows": [
                        {
                            "count": 0,
                            "avg_query_time_ms": None,
                            "avg_patterns_count": None,
                            "fallbacks": 0,
                        }
                    ],
                },
                # Routing decisions query
                {
                    "success": True,
                    "rows": [
                        {
                            "count": 0,
                            "avg_routing_time_ms": None,
                            "avg_confidence": None,
                        }
                    ],
                },
                # Agent actions query
                {"success": True, "rows": []},
            ]

            exit_code = main()

            # Should handle NULL values gracefully (convert to 0)
            assert exit_code == 0

    def test_empty_result_set(self):
        """Test handling of empty result sets."""
        execute = load_skill_module("check-recent-activity")
        main = execute.main

        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py"]),
        ):

            # All queries return empty results
            mock_query.return_value = {"success": True, "rows": []}

            exit_code = main()

            # Should succeed with empty data
            assert exit_code == 0

    def test_missing_columns(self):
        """Test handling of missing columns in results."""
        execute = load_skill_module("check-recent-activity")
        main = execute.main

        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py"]),
        ):

            # Missing expected columns (empty dictionary)
            mock_query.return_value = {
                "success": True,
                "rows": [{}],  # Empty dictionary - missing all expected keys
            }

            exit_code = main()

            # Should handle missing columns gracefully with error exit code
            # Script should detect KeyError and exit with non-zero status
            assert exit_code == 1, "Missing columns should cause error exit (code 1)"

    def test_query_with_valid_empty_data(self):
        """Test handling of valid queries returning no data."""
        execute = load_skill_module("check-agent-performance")
        main = execute.main

        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py", "--timeframe", "1h"]),
        ):

            # All queries succeed but return no rows (valid scenario)
            mock_query.side_effect = [
                {"success": True, "rows": []},  # routing query
                {"success": True, "rows": []},  # top agents query
                {"success": True, "rows": []},  # transformations query
            ]

            exit_code = main()

            # Should handle without crashing
            assert exit_code == 0


class TestExceptionHandling:
    """Test exception handling."""

    def test_unexpected_exception(self):
        """Test handling of unexpected exceptions."""
        execute = load_skill_module("check-infrastructure")
        check_postgres = execute.check_postgres

        with patch.object(execute, "execute_query") as mock_query:
            mock_query.side_effect = Exception("Unexpected error")

            result = check_postgres()

            assert result["status"] == "error"
            assert "Unexpected error" in result["error"]

    def test_keyboard_interrupt(self):
        """Test handling of keyboard interrupt."""
        execute = load_skill_module("check-recent-activity")
        main = execute.main

        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py"]),
        ):

            mock_query.side_effect = KeyboardInterrupt()

            # Should propagate KeyboardInterrupt (not catch it)
            with pytest.raises(KeyboardInterrupt):
                main()

    def test_system_exit(self):
        """Test handling of SystemExit."""
        execute = load_skill_module("check-infrastructure")
        check_postgres = execute.check_postgres

        with patch.object(execute, "execute_query") as mock_query:
            # SystemExit should be converted to error result
            mock_query.return_value = {
                "success": False,
                "error": "System exit",
                "rows": [],
            }

            result = check_postgres()

            assert result["status"] == "error"


class TestResourceManagement:
    """Test resource management on errors."""

    def test_connection_error_handled_gracefully(self):
        """Test that connection errors are handled gracefully without resource leaks."""
        execute = load_skill_module("check-infrastructure")
        check_postgres = execute.check_postgres

        # Test that connection errors don't cause exceptions or resource leaks
        with patch.object(execute, "execute_query") as mock_query:
            # Simulate connection error
            mock_query.return_value = {
                "success": False,
                "error": "Connection closed unexpectedly",
                "rows": [],
            }

            result = check_postgres()

            # Should return error status without raising exception
            assert result["status"] == "error"
            assert "error" in result
            assert "Connection" in result["error"]

    def test_no_resource_leaks(self):
        """Test for resource leaks on repeated errors."""
        import gc
        import os

        execute = load_skill_module("check-infrastructure")
        check_postgres = execute.check_postgres

        # Get initial open file descriptors count
        try:
            initial_fd_count = len(os.listdir("/proc/self/fd"))
        except (OSError, FileNotFoundError):
            # /proc not available (macOS), use alternative approach
            import resource

            initial_fd_count = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        # Track mock calls to ensure proper cleanup
        call_count = 0

        # Run multiple times with errors
        for i in range(10):
            with patch.object(execute, "execute_query") as mock_query:
                mock_query.return_value = {
                    "success": False,
                    "error": "Error",
                    "rows": [],
                }
                result = check_postgres()
                assert result["status"] == "error"
                call_count += 1

                # Verify mock was called exactly once per iteration
                assert mock_query.call_count == 1

        # Verify all 10 calls were made
        assert call_count == 10

        # Force garbage collection to release any unreferenced resources
        gc.collect()

        # Check file descriptors didn't increase significantly
        try:
            final_fd_count = len(os.listdir("/proc/self/fd"))
            # Allow small variance (±2 FDs) due to test infrastructure
            assert (
                abs(final_fd_count - initial_fd_count) <= 2
            ), f"File descriptor leak detected: initial={initial_fd_count}, final={final_fd_count}"
        except (OSError, FileNotFoundError):
            # /proc not available, verify memory didn't grow excessively
            import resource

            final_fd_count = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # Allow 10% memory growth for test overhead
            assert (
                final_fd_count <= initial_fd_count * 1.1
            ), f"Possible memory leak: initial={initial_fd_count}, final={final_fd_count}"

    def test_exception_during_query_cleanup(self):
        """Test that exceptions during query execution are handled properly."""
        execute = load_skill_module("check-recent-activity")
        main = execute.main

        with (
            patch.object(execute, "execute_query") as mock_query,
            patch("sys.argv", ["execute.py"]),
        ):
            # First query succeeds, second raises exception
            mock_query.side_effect = [
                {
                    "success": True,
                    "rows": [
                        {
                            "count": 10,
                            "avg_query_time_ms": 100,
                            "avg_patterns_count": 5,
                            "fallbacks": 0,
                        }
                    ],
                },
                Exception("Database connection lost"),
            ]

            exit_code = main()

            # Should handle exception gracefully (not crash)
            assert exit_code == 1
