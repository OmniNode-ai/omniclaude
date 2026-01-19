"""
Comprehensive tests for cli/commands/query.py
==============================================

Tests all CLI query commands with extensive coverage:
- query routing (routing decision records)
- query transformations (transformation event records)
- query performance (router performance metrics)
- query stats (aggregate statistics)
- Output formatting (table, json, csv)
- Error handling and edge cases

Setup:
    Run with pytest from project root:

        pytest agents/tests/cli/test_query_commands.py -v

Coverage target: 85%+
"""

import json
from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from cli.commands.query import (
    _display_results,
    query,
)
from click.testing import CliRunner

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def runner():
    """Create Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_db_cursor():
    """Mock database cursor with RealDictCursor behavior."""
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=None)
    return mock_cursor


@pytest.fixture
def sample_routing_results():
    """Sample routing decision results."""
    return [
        {
            "id": 1,
            "user_request": "Help me debug an error",
            "selected_agent": "agent-debug-intelligence",
            "confidence_score": 0.95,
            "routing_strategy": "enhanced_fuzzy_matching",
            "routing_time_ms": 45,
            "created_at": datetime.now(),
        },
        {
            "id": 2,
            "user_request": "Create an API endpoint",
            "selected_agent": "agent-api-architect",
            "confidence_score": 0.88,
            "routing_strategy": "enhanced_fuzzy_matching",
            "routing_time_ms": 52,
            "created_at": datetime.now() - timedelta(hours=1),
        },
    ]


@pytest.fixture
def sample_transformation_results():
    """Sample transformation event results."""
    return [
        {
            "id": 1,
            "source_agent": "polymorphic-agent",
            "target_agent": "agent-debug-intelligence",
            "transformation_reason": "Specialized debugging required",
            "confidence_score": 0.92,
            "transformation_duration_ms": 120,
            "success": True,
            "created_at": datetime.now(),
        },
        {
            "id": 2,
            "source_agent": "polymorphic-agent",
            "target_agent": "agent-api-architect",
            "transformation_reason": "API design expertise needed",
            "confidence_score": 0.85,
            "transformation_duration_ms": 95,
            "success": True,
            "created_at": datetime.now() - timedelta(hours=2),
        },
    ]


@pytest.fixture
def sample_performance_results():
    """Sample performance metrics results."""
    return [
        {
            "id": 1,
            "query_text": "debug error",
            "routing_duration_ms": 45,
            "cache_hit": True,
            "trigger_match_strategy": "exact_match",
            "candidates_evaluated": 3,
            "created_at": datetime.now(),
        },
        {
            "id": 2,
            "query_text": "create api",
            "routing_duration_ms": 67,
            "cache_hit": False,
            "trigger_match_strategy": "fuzzy_match",
            "candidates_evaluated": 5,
            "created_at": datetime.now() - timedelta(minutes=30),
        },
    ]


@pytest.fixture
def sample_stats_routing():
    """Sample routing statistics."""
    return {
        "total": 150,
        "avg_confidence": 0.87,
        "avg_routing_time": 52.3,
        "unique_agents": 8,
    }


@pytest.fixture
def sample_stats_transformation():
    """Sample transformation statistics."""
    return {
        "total": 45,
        "successful": 42,
        "avg_duration": 105.7,
    }


@pytest.fixture
def sample_stats_performance():
    """Sample performance statistics."""
    return {
        "total": 200,
        "avg_duration": 48.5,
        "cache_hits": 120,
        "avg_candidates": 4.2,
    }


# ============================================================================
# Query Routing Tests
# ============================================================================


class TestQueryRouting:
    """Test query routing command."""

    def test_query_routing_basic(self, runner, mock_db_cursor, sample_routing_results):
        """Test basic routing query with default parameters."""
        mock_db_cursor.fetchall.return_value = sample_routing_results

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["routing"])

        assert result.exit_code == 0
        assert "Routing Decisions" in result.output
        assert "agent-debug-intelligence" in result.output

    def test_query_routing_with_agent_filter(
        self, runner, mock_db_cursor, sample_routing_results
    ):
        """Test routing query with agent name filter."""
        filtered = [sample_routing_results[0]]
        mock_db_cursor.fetchall.return_value = filtered

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(
                query, ["routing", "--agent", "agent-debug-intelligence"]
            )

        assert result.exit_code == 0
        assert "agent-debug-intelligence" in result.output
        mock_db_cursor.execute.assert_called_once()
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "selected_agent = %s" in sql
        assert "agent-debug-intelligence" in params

    def test_query_routing_with_strategy_filter(
        self, runner, mock_db_cursor, sample_routing_results
    ):
        """Test routing query with strategy filter."""
        mock_db_cursor.fetchall.return_value = sample_routing_results

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(
                query, ["routing", "--strategy", "enhanced_fuzzy_matching"]
            )

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "routing_strategy = %s" in sql
        assert "enhanced_fuzzy_matching" in params

    def test_query_routing_with_confidence_filters(
        self, runner, mock_db_cursor, sample_routing_results
    ):
        """Test routing query with min/max confidence filters."""
        mock_db_cursor.fetchall.return_value = [sample_routing_results[0]]

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(
                query, ["routing", "--min-confidence", "0.9", "--max-confidence", "1.0"]
            )

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "confidence_score >= %s" in sql
        assert "confidence_score <= %s" in sql
        assert 0.9 in params
        assert 1.0 in params

    def test_query_routing_with_hours_filter(
        self, runner, mock_db_cursor, sample_routing_results
    ):
        """Test routing query with hours filter."""
        mock_db_cursor.fetchall.return_value = sample_routing_results

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["routing", "--hours", "24"])

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "created_at >= %s" in sql
        # Verify datetime calculation (approximate check)
        assert any(isinstance(p, datetime) for p in params)

    def test_query_routing_with_limit(
        self, runner, mock_db_cursor, sample_routing_results
    ):
        """Test routing query with custom limit."""
        mock_db_cursor.fetchall.return_value = sample_routing_results

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["routing", "--limit", "20"])

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "LIMIT %s" in sql
        assert 20 in params

    def test_query_routing_json_format(
        self, runner, mock_db_cursor, sample_routing_results
    ):
        """Test routing query with JSON output format."""
        mock_db_cursor.fetchall.return_value = sample_routing_results

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["routing", "--format", "json"])

        assert result.exit_code == 0
        # Verify JSON output
        output_data = json.loads(result.output)
        assert isinstance(output_data, list)
        assert len(output_data) == 2
        assert output_data[0]["selected_agent"] == "agent-debug-intelligence"

    def test_query_routing_csv_format(
        self, runner, mock_db_cursor, sample_routing_results
    ):
        """Test routing query with CSV output format."""
        mock_db_cursor.fetchall.return_value = sample_routing_results

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["routing", "--format", "csv"])

        assert result.exit_code == 0
        # Verify CSV headers
        assert "id,user_request,selected_agent" in result.output
        assert "agent-debug-intelligence" in result.output

    def test_query_routing_no_results(self, runner, mock_db_cursor):
        """Test routing query with no matching results."""
        mock_db_cursor.fetchall.return_value = []

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["routing", "--agent", "nonexistent"])

        assert result.exit_code == 0
        assert "No routing decisions found" in result.output

    def test_query_routing_multiple_filters(
        self, runner, mock_db_cursor, sample_routing_results
    ):
        """Test routing query with multiple combined filters."""
        mock_db_cursor.fetchall.return_value = [sample_routing_results[0]]

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(
                query,
                [
                    "routing",
                    "--agent",
                    "agent-debug-intelligence",
                    "--min-confidence",
                    "0.9",
                    "--hours",
                    "12",
                    "--limit",
                    "5",
                ],
            )

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "selected_agent = %s" in sql
        assert "confidence_score >= %s" in sql
        assert "created_at >= %s" in sql
        assert 5 in params  # limit

    def test_query_routing_database_error(self, runner, mock_db_cursor):
        """Test routing query with database error."""
        mock_db_cursor.execute.side_effect = Exception("Database connection failed")

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["routing"])

        assert result.exit_code == 1  # click.Abort
        assert "Query error" in result.output


# ============================================================================
# Query Transformations Tests
# ============================================================================


class TestQueryTransformations:
    """Test query transformations command."""

    def test_query_transformations_basic(
        self, runner, mock_db_cursor, sample_transformation_results
    ):
        """Test basic transformations query."""
        mock_db_cursor.fetchall.return_value = sample_transformation_results

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["transformations"])

        assert result.exit_code == 0
        assert "Transformation Events" in result.output
        assert "polymorphic-agent" in result.output

    def test_query_transformations_with_source_filter(
        self, runner, mock_db_cursor, sample_transformation_results
    ):
        """Test transformations query with source agent filter."""
        mock_db_cursor.fetchall.return_value = sample_transformation_results

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(
                query, ["transformations", "--source", "polymorphic-agent"]
            )

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "source_agent = %s" in sql
        assert "polymorphic-agent" in params

    def test_query_transformations_with_target_filter(
        self, runner, mock_db_cursor, sample_transformation_results
    ):
        """Test transformations query with target agent filter."""
        mock_db_cursor.fetchall.return_value = [sample_transformation_results[0]]

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(
                query, ["transformations", "--target", "agent-debug-intelligence"]
            )

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "target_agent = %s" in sql
        assert "agent-debug-intelligence" in params

    def test_query_transformations_success_filter(
        self, runner, mock_db_cursor, sample_transformation_results
    ):
        """Test transformations query with success filter."""
        mock_db_cursor.fetchall.return_value = sample_transformation_results

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["transformations", "--success"])

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "success = %s" in sql
        assert True in params

    def test_query_transformations_failure_filter(
        self, runner, mock_db_cursor, sample_transformation_results
    ):
        """Test transformations query with failure filter."""
        failed = [dict(sample_transformation_results[0], success=False)]
        mock_db_cursor.fetchall.return_value = failed

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["transformations", "--failure"])

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "success = %s" in sql
        assert False in params

    def test_query_transformations_with_hours(
        self, runner, mock_db_cursor, sample_transformation_results
    ):
        """Test transformations query with hours filter."""
        mock_db_cursor.fetchall.return_value = sample_transformation_results

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["transformations", "--hours", "48"])

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "created_at >= %s" in sql

    def test_query_transformations_json_format(
        self, runner, mock_db_cursor, sample_transformation_results
    ):
        """Test transformations query with JSON format."""
        mock_db_cursor.fetchall.return_value = sample_transformation_results

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["transformations", "--format", "json"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert len(output_data) == 2
        assert output_data[0]["source_agent"] == "polymorphic-agent"

    def test_query_transformations_no_results(self, runner, mock_db_cursor):
        """Test transformations query with no results."""
        mock_db_cursor.fetchall.return_value = []

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["transformations"])

        assert result.exit_code == 0
        assert "No transformation events found" in result.output

    def test_query_transformations_combined_filters(
        self, runner, mock_db_cursor, sample_transformation_results
    ):
        """Test transformations query with multiple filters."""
        mock_db_cursor.fetchall.return_value = [sample_transformation_results[0]]

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(
                query,
                [
                    "transformations",
                    "--source",
                    "polymorphic-agent",
                    "--success",
                    "--hours",
                    "24",
                ],
            )

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "source_agent = %s" in sql
        assert "success = %s" in sql
        assert "created_at >= %s" in sql

    def test_query_transformations_error(self, runner, mock_db_cursor):
        """Test transformations query with error."""
        mock_db_cursor.execute.side_effect = Exception("Query failed")

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["transformations"])

        assert result.exit_code == 1
        assert "Query error" in result.output


# ============================================================================
# Query Performance Tests
# ============================================================================


class TestQueryPerformance:
    """Test query performance command."""

    def test_query_performance_basic(
        self, runner, mock_db_cursor, sample_performance_results
    ):
        """Test basic performance query."""
        mock_db_cursor.fetchall.return_value = sample_performance_results

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["performance"])

        assert result.exit_code == 0
        assert "Performance Metrics" in result.output
        assert "debug error" in result.output

    def test_query_performance_with_strategy_filter(
        self, runner, mock_db_cursor, sample_performance_results
    ):
        """Test performance query with strategy filter."""
        mock_db_cursor.fetchall.return_value = [sample_performance_results[0]]

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["performance", "--strategy", "exact_match"])

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "trigger_match_strategy = %s" in sql
        assert "exact_match" in params

    def test_query_performance_cache_hit_filter(
        self, runner, mock_db_cursor, sample_performance_results
    ):
        """Test performance query with cache hit filter."""
        mock_db_cursor.fetchall.return_value = [sample_performance_results[0]]

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["performance", "--cache-hit"])

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "cache_hit = %s" in sql
        assert True in params

    def test_query_performance_cache_miss_filter(
        self, runner, mock_db_cursor, sample_performance_results
    ):
        """Test performance query with cache miss filter."""
        mock_db_cursor.fetchall.return_value = [sample_performance_results[1]]

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["performance", "--cache-miss"])

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "cache_hit = %s" in sql
        assert False in params

    def test_query_performance_max_duration_filter(
        self, runner, mock_db_cursor, sample_performance_results
    ):
        """Test performance query with max duration filter."""
        mock_db_cursor.fetchall.return_value = [sample_performance_results[0]]

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["performance", "--max-duration", "50"])

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "routing_duration_ms <= %s" in sql
        assert 50 in params

    def test_query_performance_with_hours(
        self, runner, mock_db_cursor, sample_performance_results
    ):
        """Test performance query with hours filter."""
        mock_db_cursor.fetchall.return_value = sample_performance_results

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["performance", "--hours", "6"])

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "created_at >= %s" in sql

    def test_query_performance_csv_format(
        self, runner, mock_db_cursor, sample_performance_results
    ):
        """Test performance query with CSV format."""
        mock_db_cursor.fetchall.return_value = sample_performance_results

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["performance", "--format", "csv"])

        assert result.exit_code == 0
        assert "id,query_text,routing_duration_ms" in result.output

    def test_query_performance_no_results(self, runner, mock_db_cursor):
        """Test performance query with no results."""
        mock_db_cursor.fetchall.return_value = []

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["performance"])

        assert result.exit_code == 0
        assert "No performance metrics found" in result.output

    def test_query_performance_combined_filters(
        self, runner, mock_db_cursor, sample_performance_results
    ):
        """Test performance query with multiple filters."""
        mock_db_cursor.fetchall.return_value = [sample_performance_results[0]]

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(
                query,
                [
                    "performance",
                    "--cache-hit",
                    "--max-duration",
                    "100",
                    "--hours",
                    "12",
                ],
            )

        assert result.exit_code == 0
        sql, params = mock_db_cursor.execute.call_args[0]
        assert "cache_hit = %s" in sql
        assert "routing_duration_ms <= %s" in sql
        assert "created_at >= %s" in sql

    def test_query_performance_error(self, runner, mock_db_cursor):
        """Test performance query with error."""
        mock_db_cursor.execute.side_effect = Exception("Connection lost")

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["performance"])

        assert result.exit_code == 1
        assert "Query error" in result.output


# ============================================================================
# Query Stats Tests
# ============================================================================


class TestQueryStats:
    """Test query stats command."""

    def test_query_stats_success(
        self,
        runner,
        mock_db_cursor,
        sample_stats_routing,
        sample_stats_transformation,
        sample_stats_performance,
    ):
        """Test stats query with all statistics."""
        # Mock will be called three times for three different queries
        mock_db_cursor.fetchone.side_effect = [
            sample_stats_routing,
            sample_stats_transformation,
            sample_stats_performance,
        ]

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["stats"])

        assert result.exit_code == 0
        assert "Database Statistics" in result.output
        assert "Routing Decisions:" in result.output
        assert "Total: 150" in result.output
        assert "87.00%" in result.output  # avg confidence
        assert "Transformation Events:" in result.output
        assert "Total: 45" in result.output
        assert "Performance Metrics:" in result.output
        assert "Total: 200" in result.output

    def test_query_stats_with_null_values(self, runner, mock_db_cursor):
        """Test stats query with null/zero values."""
        mock_db_cursor.fetchone.side_effect = [
            {
                "total": 0,
                "avg_confidence": None,
                "avg_routing_time": None,
                "unique_agents": 0,
            },
            {"total": 0, "successful": 0, "avg_duration": None},
            {
                "total": 0,
                "avg_duration": None,
                "cache_hits": 0,
                "avg_candidates": None,
            },
        ]

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["stats"])

        assert result.exit_code == 0
        assert "Total: 0" in result.output
        assert "Avg Confidence: N/A" in result.output
        assert "Avg Routing Time: N/A" in result.output

    def test_query_stats_success_rate_calculation(self, runner, mock_db_cursor):
        """Test stats query success rate calculation."""
        mock_db_cursor.fetchone.side_effect = [
            {
                "total": 100,
                "avg_confidence": 0.85,
                "avg_routing_time": 50.0,
                "unique_agents": 5,
            },
            {"total": 50, "successful": 45, "avg_duration": 100.0},
            {
                "total": 200,
                "avg_duration": 45.0,
                "cache_hits": 150,
                "avg_candidates": 4.0,
            },
        ]

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["stats"])

        assert result.exit_code == 0
        assert "Success Rate: 90.0%" in result.output  # 45/50 * 100
        assert "Cache Hit Rate: 75.0%" in result.output  # 150/200 * 100

    def test_query_stats_database_error(self, runner, mock_db_cursor):
        """Test stats query with database error."""
        mock_db_cursor.fetchone.side_effect = Exception("Database error")

        with patch("cli.commands.query.get_db_cursor", return_value=mock_db_cursor):
            result = runner.invoke(query, ["stats"])

        assert result.exit_code == 1
        assert "Query error" in result.output


# ============================================================================
# Display Results Helper Tests
# ============================================================================


class TestDisplayResults:
    """Test _display_results helper function."""

    def test_display_results_table_format(self, sample_routing_results):
        """Test table format display."""
        with (
            patch("cli.commands.query.click.echo") as mock_echo,
            patch("cli.commands.query.click.secho") as mock_secho,
        ):
            _display_results(sample_routing_results, "table", "Test Results")

        # Verify secho called for title
        assert mock_secho.called
        title_call = mock_secho.call_args_list[0]
        assert "Test Results" in str(title_call)

        # Verify echo called for table and count
        assert mock_echo.called
        echo_calls = [str(call) for call in mock_echo.call_args_list]
        assert any("Total records: 2" in call for call in echo_calls)

    def test_display_results_json_format(self, sample_routing_results):
        """Test JSON format display."""
        with patch("cli.commands.query.click.echo") as mock_echo:
            _display_results(sample_routing_results, "json", "Test Results")

        # Verify JSON output
        assert mock_echo.called
        json_output = mock_echo.call_args[0][0]
        data = json.loads(json_output)
        assert len(data) == 2
        assert "created_at" in data[0]
        # Datetime should be converted to ISO format string
        assert isinstance(data[0]["created_at"], str)

    def test_display_results_csv_format(self, sample_routing_results):
        """Test CSV format display."""
        with patch("sys.stdout", new=StringIO()) as fake_out:
            _display_results(sample_routing_results, "csv", "Test Results")

        output = fake_out.getvalue()
        # Verify CSV headers
        assert "id,user_request,selected_agent" in output
        # Verify data rows
        assert "agent-debug-intelligence" in output
        assert "agent-api-architect" in output

    def test_display_results_empty_results(self):
        """Test display with empty results list."""
        with patch("cli.commands.query.click.echo") as mock_echo:
            _display_results([], "table", "Empty Results")

        # Should still be called but with minimal output
        assert mock_echo.called

    def test_display_results_datetime_conversion(self):
        """Test datetime objects are properly converted in JSON format."""
        test_data = [
            {
                "id": 1,
                "timestamp": datetime(2024, 1, 1, 12, 0, 0),
                "name": "test",
            }
        ]

        with patch("cli.commands.query.click.echo") as mock_echo:
            _display_results(test_data, "json", "Test")

        json_output = mock_echo.call_args[0][0]
        data = json.loads(json_output)
        # Verify datetime converted to ISO format
        assert data[0]["timestamp"] == "2024-01-01T12:00:00"
        assert isinstance(data[0]["timestamp"], str)


# ============================================================================
# Integration Tests
# ============================================================================


class TestQueryIntegration:
    """Integration tests for query commands."""

    def test_query_group_exists(self, runner):
        """Test that query command group exists."""
        result = runner.invoke(query, ["--help"])
        assert result.exit_code == 0
        assert "Query database records" in result.output
        assert "routing" in result.output
        assert "transformations" in result.output
        assert "performance" in result.output
        assert "stats" in result.output

    def test_routing_help(self, runner):
        """Test routing command help."""
        result = runner.invoke(query, ["routing", "--help"])
        assert result.exit_code == 0
        assert "--agent" in result.output
        assert "--strategy" in result.output
        assert "--min-confidence" in result.output
        assert "--format" in result.output

    def test_transformations_help(self, runner):
        """Test transformations command help."""
        result = runner.invoke(query, ["transformations", "--help"])
        assert result.exit_code == 0
        assert "--source" in result.output
        assert "--target" in result.output
        assert "--success" in result.output

    def test_performance_help(self, runner):
        """Test performance command help."""
        result = runner.invoke(query, ["performance", "--help"])
        assert result.exit_code == 0
        assert "--strategy" in result.output
        assert "--cache-hit" in result.output
        assert "--max-duration" in result.output

    def test_stats_help(self, runner):
        """Test stats command help."""
        result = runner.invoke(query, ["stats", "--help"])
        assert result.exit_code == 0
        assert "aggregate statistics" in result.output
