"""
Integration tests for check-infrastructure skill.

Tests:
- Kafka connectivity checks
- PostgreSQL connectivity checks
- Qdrant connectivity checks
- Component filtering
- Detailed vs summary output

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


# Load the check-infrastructure execute module
execute = load_skill_module("check-infrastructure")
main = execute.main
check_kafka = execute.check_kafka
check_postgres = execute.check_postgres
check_qdrant = execute.check_qdrant


class TestCheckInfrastructure:
    """Test check-infrastructure skill."""

    def test_check_kafka_success(self):
        """Test successful Kafka check."""
        with (
            patch.object(execute, "check_kafka_connection") as mock_conn,
            patch.object(execute, "list_topics") as mock_topics,
        ):
            mock_conn.return_value = {
                "status": "connected",
                "broker": "192.168.86.200:29092",
                "reachable": True,
                "error": None,
            }
            mock_topics.return_value = {"count": 25}

            result = check_kafka(detailed=True)

            assert result["status"] == "connected"
            assert result["reachable"] is True
            assert result["topics"] == 25
            assert result["error"] is None

    def test_check_kafka_failure(self):
        """Test Kafka check when broker is unreachable."""
        with patch.object(execute, "check_kafka_connection") as mock_conn:
            mock_conn.return_value = {
                "status": "error",
                "broker": "192.168.86.200:29092",
                "reachable": False,
                "error": "Connection timeout",
            }

            result = check_kafka(detailed=False)

            assert result["status"] == "error"
            assert result["reachable"] is False
            assert result["error"] == "Connection timeout"

    def test_check_postgres_success(self):
        """Test successful PostgreSQL check."""
        with patch.object(execute, "execute_query") as mock_query:
            mock_query.side_effect = [
                {
                    "success": True,
                    "rows": [{"count": 34}],
                    "host": "192.168.86.200",
                    "port": "5436",
                    "database": "omninode_bridge",
                },
                {
                    "success": True,
                    "rows": [{"count": 12}],
                },
            ]

            result = check_postgres(detailed=True)

            assert result["status"] == "connected"
            assert result["tables"] == 34
            assert result["connections"] == 12
            assert result["error"] is None

    def test_check_postgres_failure(self):
        """Test PostgreSQL check when database is unavailable."""
        with patch.object(execute, "execute_query") as mock_query:
            mock_query.return_value = {
                "success": False,
                "error": "Connection refused",
                "rows": [],
            }

            result = check_postgres(detailed=False)

            assert result["status"] == "error"
            assert "Connection refused" in result["error"]

    def test_check_qdrant_success(self):
        """Test successful Qdrant check."""
        with (
            patch.object(execute, "check_qdrant_connection") as mock_conn,
            patch.object(execute, "get_all_collections_stats") as mock_stats,
        ):
            mock_conn.return_value = {
                "status": "connected",
                "url": "http://192.168.86.101:6333",
                "reachable": True,
                "error": None,
            }
            mock_stats.return_value = {
                "success": True,
                "collection_count": 2,
                "total_vectors": 15689,
                "collections": {
                    "archon_vectors": {"vectors_count": 7118},
                    "code_generation_patterns": {"vectors_count": 8571},
                },
            }

            result = check_qdrant(detailed=True)

            assert result["status"] == "connected"
            assert result["reachable"] is True
            assert result["collections"] == 2
            assert result["total_vectors"] == 15689
            assert result["error"] is None

    def test_check_qdrant_failure(self):
        """Test Qdrant check when service is unavailable."""
        with patch.object(execute, "check_qdrant_connection") as mock_conn:
            mock_conn.return_value = {
                "status": "error",
                "url": "http://192.168.86.101:6333",
                "reachable": False,
                "error": "Connection timeout",
            }

            result = check_qdrant(detailed=False)

            assert result["status"] == "error"
            assert result["reachable"] is False
            assert "Connection timeout" in result["error"]

    def test_component_filtering(self):
        """Test filtering specific components."""
        # Test with only Kafka
        with (
            patch.object(execute, "check_kafka") as mock_kafka,
            patch("sys.argv", ["execute.py", "--components", "kafka"]),
        ):
            mock_kafka.return_value = {"status": "connected"}

            exit_code = main()

            assert exit_code == 0
            mock_kafka.assert_called_once()

    def test_detailed_output_flag(self):
        """Test --detailed flag includes extra stats."""
        with (
            patch.object(execute, "check_kafka_connection") as mock_conn,
            patch.object(execute, "list_topics") as mock_topics,
        ):
            mock_conn.return_value = {
                "status": "connected",
                "reachable": True,
                "error": None,
                "broker": "test",
            }
            mock_topics.return_value = {"count": 25}

            # Without detailed
            result_summary = check_kafka(detailed=False)
            assert result_summary["topics"] is None

            # With detailed
            result_detailed = check_kafka(detailed=True)
            assert result_detailed["topics"] == 25

    def test_all_components_default(self):
        """Test that all components are checked by default."""
        with (
            patch.object(execute, "check_kafka") as mock_kafka,
            patch.object(execute, "check_postgres") as mock_postgres,
            patch.object(execute, "check_qdrant") as mock_qdrant,
            patch("sys.argv", ["execute.py"]),
        ):
            mock_kafka.return_value = {"status": "connected"}
            mock_postgres.return_value = {"status": "connected"}
            mock_qdrant.return_value = {"status": "connected"}

            exit_code = main()

            assert exit_code == 0
            mock_kafka.assert_called_once()
            mock_postgres.assert_called_once()
            mock_qdrant.assert_called_once()

    def test_error_handling(self):
        """Test error handling when component check fails."""
        with (
            patch.object(execute, "check_kafka") as mock_kafka,
            patch("sys.argv", ["execute.py", "--components", "kafka"]),
        ):
            mock_kafka.side_effect = Exception("Unexpected error")

            exit_code = main()

            assert exit_code == 1
