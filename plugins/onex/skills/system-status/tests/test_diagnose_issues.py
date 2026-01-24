"""
Integration tests for diagnose-issues skill.

Tests:
- Issue detection
- Severity classification
- Recommendation generation
- Multi-component analysis

Created: 2025-11-20
"""

from pathlib import Path
from unittest.mock import patch

# Import load_skill_module from conftest
conftest_path = Path(__file__).parent / "conftest.py"
import importlib.util

spec = importlib.util.spec_from_file_location("conftest", conftest_path)
conftest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conftest)
load_skill_module = conftest.load_skill_module


# Import from diagnose-issues/execute.py

# Load the diagnose-issues execute module
execute = load_skill_module("diagnose-issues")
main = execute.main


class TestDiagnoseIssues:
    """Test diagnose-issues skill."""

    def test_detect_kafka_issues(self):
        """Test detection of Kafka issues."""
        with (
            patch.object(execute, "check_kafka_connection") as mock_kafka,
            patch.object(execute, "execute_query") as mock_db,
            patch.object(execute, "check_qdrant_connection") as mock_qdrant,
            patch.object(execute, "list_containers") as mock_containers,
            patch("sys.argv", ["execute.py"]),
        ):
            # Mock Kafka failure
            mock_kafka.return_value = {
                "reachable": False,
                "error": "Connection refused",
            }

            # Mock successful PostgreSQL and Qdrant
            mock_db.return_value = {"success": True, "rows": []}
            mock_qdrant.return_value = {"reachable": True}

            # Mock successful Docker
            mock_containers.return_value = {"success": True, "containers": []}

            exit_code = main()

            # Kafka issue is critical, expect exit code 2
            assert exit_code == 2

    def test_detect_postgres_issues(self):
        """Test detection of PostgreSQL issues."""
        with (
            patch.object(execute, "check_kafka_connection") as mock_kafka,
            patch.object(execute, "execute_query") as mock_db,
            patch.object(execute, "check_qdrant_connection") as mock_qdrant,
            patch.object(execute, "list_containers") as mock_containers,
            patch("sys.argv", ["execute.py"]),
        ):
            # Mock PostgreSQL failure
            mock_db.return_value = {
                "success": False,
                "error": "Connection timeout",
            }

            # Mock successful Kafka and Qdrant
            mock_kafka.return_value = {"reachable": True}
            mock_qdrant.return_value = {"reachable": True}

            # Mock successful Docker
            mock_containers.return_value = {"success": True, "containers": []}

            exit_code = main()

            # PostgreSQL issue is critical, expect exit code 2
            assert exit_code == 2

    def test_detect_qdrant_issues(self):
        """Test detection of Qdrant issues."""
        with (
            patch.object(execute, "check_kafka_connection") as mock_kafka,
            patch.object(execute, "execute_query") as mock_db,
            patch.object(execute, "check_qdrant_connection") as mock_qdrant,
            patch.object(execute, "list_containers") as mock_containers,
            patch("sys.argv", ["execute.py"]),
        ):
            # Mock Qdrant failure
            mock_qdrant.return_value = {
                "reachable": False,
                "error": "Service unavailable",
            }

            # Mock successful Kafka and PostgreSQL
            mock_kafka.return_value = {"reachable": True}
            mock_db.return_value = {"success": True, "rows": []}

            # Mock successful Docker
            mock_containers.return_value = {"success": True, "containers": []}

            exit_code = main()

            # Qdrant issue is critical, expect exit code 2
            assert exit_code == 2

    def test_no_issues_detected(self):
        """Test when no issues are detected (empty containers scenario).

        Verifies that when all services are healthy and accessible:
        1. check_kafka_connection returns reachable=True
        2. execute_query returns success=True with empty results
        3. check_qdrant_connection returns reachable=True
        4. list_containers returns success=True with empty container list
        5. main() returns exit code 0 (healthy system)

        Mock Return Value Structure:
        - Kafka: {"reachable": True} - no error field needed when healthy
        - PostgreSQL: {"success": True, "rows": []} - empty results are valid
        - Qdrant: {"reachable": True} - no error field needed when healthy
        - Docker: {"success": True, "containers": []} - no containers to report issues
        """
        with (
            patch.object(execute, "check_kafka_connection") as mock_kafka,
            patch.object(execute, "execute_query") as mock_db,
            patch.object(execute, "check_qdrant_connection") as mock_qdrant,
            patch.object(execute, "list_containers") as mock_containers,
            patch.object(execute, "get_container_status") as mock_container_status,
            patch("sys.argv", ["execute.py"]),
        ):
            # Mock all services healthy (minimal required fields - no "error" when successful)
            mock_kafka.return_value = {"reachable": True}
            mock_db.return_value = {"success": True, "rows": []}
            mock_qdrant.return_value = {"reachable": True}
            mock_containers.return_value = {"success": True, "containers": []}
            # get_container_status won't be called with empty containers, but mock it for safety
            mock_container_status.return_value = {"success": True, "restart_count": 0}

            exit_code = main()

            # Verify infrastructure checks were called
            assert mock_kafka.called, "Kafka check should be called"
            assert mock_db.called, "Database check should be called"
            assert mock_qdrant.called, "Qdrant check should be called"
            assert mock_containers.called, "Docker containers check should be called"

            # No issues, expect exit code 0 (healthy)
            assert exit_code == 0, "Exit code should be 0 when all services are healthy"

    def test_no_issues_with_healthy_containers(self):
        """Test when containers exist but all are healthy.

        This is a more comprehensive no-issues test that includes running
        containers to verify that healthy containers don't generate issues.
        """
        with (
            patch.object(execute, "check_kafka_connection") as mock_kafka,
            patch.object(execute, "execute_query") as mock_db,
            patch.object(execute, "check_qdrant_connection") as mock_qdrant,
            patch.object(execute, "list_containers") as mock_containers,
            patch.object(execute, "get_container_status") as mock_container_status,
            patch("sys.argv", ["execute.py"]),
        ):
            # Mock all infrastructure services healthy
            mock_kafka.return_value = {"reachable": True}
            mock_db.return_value = {"success": True, "rows": []}
            mock_qdrant.return_value = {"reachable": True}

            # Mock running containers that are all healthy
            mock_containers.return_value = {
                "success": True,
                "containers": [
                    {
                        "name": "archon-intelligence",
                        "state": "running",
                        "status": "healthy",
                    },
                    {"name": "archon-qdrant", "state": "running", "status": "healthy"},
                ],
            }

            # Mock container status with low restart count (below threshold)
            mock_container_status.return_value = {"success": True, "restart_count": 0}

            exit_code = main()

            # Verify all checks were called
            assert mock_kafka.called, "Kafka check should be called"
            assert mock_db.called, "Database check should be called"
            assert mock_qdrant.called, "Qdrant check should be called"
            assert mock_containers.called, "Docker containers check should be called"
            # get_container_status should be called for each container
            assert mock_container_status.call_count == 2, (
                "Container status should be checked for each container"
            )

            # No issues, expect exit code 0 (healthy)
            assert exit_code == 0, (
                "Exit code should be 0 when all containers are healthy"
            )

    def test_severity_classification(self):
        """Test issue severity classification."""
        with (
            patch.object(execute, "check_kafka_connection") as mock_kafka,
            patch.object(execute, "execute_query") as mock_db,
            patch.object(execute, "check_qdrant_connection") as mock_qdrant,
            patch.object(execute, "list_containers") as mock_containers,
            patch("sys.argv", ["execute.py"]),
        ):
            # Mock PostgreSQL failure (critical)
            mock_db.return_value = {
                "success": False,
                "error": "Connection refused",
            }

            # Mock successful Kafka and Qdrant
            mock_kafka.return_value = {"reachable": True}
            mock_qdrant.return_value = {"reachable": True}

            # Mock successful Docker
            mock_containers.return_value = {"success": True, "containers": []}

            exit_code = main()

            # Critical issue, expect exit code 2
            assert exit_code == 2
