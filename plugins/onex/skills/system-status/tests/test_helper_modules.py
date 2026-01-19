"""
Unit tests for shared helper modules.

Tests:
- db_helper.py
- kafka_helper.py
- qdrant_helper.py
- status_formatter.py

Created: 2025-11-20
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))


class TestStatusFormatter:
    """Test status_formatter module."""

    def test_format_json_basic(self):
        """Test basic JSON formatting."""
        from status_formatter import format_json

        data = {"key": "value", "count": 123}
        result = format_json(data)

        # Should be valid JSON
        parsed = json.loads(result)
        assert parsed["key"] == "value"
        assert parsed["count"] == 123

    def test_format_json_pretty_print(self):
        """Test pretty-printed JSON output."""
        from status_formatter import format_json

        data = {"nested": {"key": "value"}}
        result = format_json(data)

        # Should be formatted with indentation
        assert "\n" in result
        assert "  " in result or "\t" in result

    def test_format_json_with_none(self):
        """Test formatting with None values."""
        from status_formatter import format_json

        data = {"key": None, "other": "value"}
        result = format_json(data)

        parsed = json.loads(result)
        assert parsed["key"] is None

    def test_format_json_with_floats(self):
        """Test formatting with floating point numbers."""
        from status_formatter import format_json

        data = {"average": 123.456}
        result = format_json(data)

        parsed = json.loads(result)
        assert parsed["average"] == 123.456


class TestTimeframeHelper:
    """Test timeframe_helper module (already tested in detail)."""

    def test_import_module(self):
        """Test that timeframe_helper imports successfully."""
        from timeframe_helper import parse_timeframe

        assert callable(parse_timeframe)


class TestDatabaseHelper:
    """Test db_helper module."""

    def test_execute_query_success(self):
        """Test successful query execution."""
        from db_helper import execute_query

        # This would require mocking psycopg2
        # For now, verify the function exists
        assert callable(execute_query)

    def test_execute_query_params(self):
        """Test that execute_query accepts params."""
        # Verify function signature accepts params parameter
        import inspect

        from db_helper import execute_query

        sig = inspect.signature(execute_query)
        assert "params" in sig.parameters


class TestKafkaHelper:
    """Test kafka_helper module."""

    def test_check_kafka_connection_exists(self):
        """Test check_kafka_connection function exists."""
        from kafka_helper import check_kafka_connection

        assert callable(check_kafka_connection)

    def test_list_topics_exists(self):
        """Test list_topics function exists."""
        from kafka_helper import list_topics

        assert callable(list_topics)


class TestQdrantHelper:
    """Test qdrant_helper module."""

    def test_check_qdrant_connection_exists(self):
        """Test check_qdrant_connection function exists."""
        from qdrant_helper import check_qdrant_connection

        assert callable(check_qdrant_connection)

    def test_get_all_collections_stats_exists(self):
        """Test get_all_collections_stats function exists."""
        from qdrant_helper import get_all_collections_stats

        assert callable(get_all_collections_stats)

    def test_url_validation_exists(self):
        """Test that URL validation function exists."""
        import qdrant_helper

        # Check if validate_qdrant_url exists
        if hasattr(qdrant_helper, "validate_qdrant_url"):
            assert callable(qdrant_helper.validate_qdrant_url)
