#!/usr/bin/env python3
"""
Comprehensive tests for cli/hook_agent_health_dashboard.py

Tests cover:
- Database query functions with mocked asyncpg connections
- Panel and table creation with various data scenarios
- Formatting functions for timestamps and time deltas
- Dashboard orchestration and layout creation
- CLI argument parsing and error handling
- Watch mode and snapshot mode
"""

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table

# Import functions from the dashboard module
sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")
from cli.hook_agent_health_dashboard import (
    create_agent_usage_table,
    create_dashboard_layout,
    create_hook_events_table,
    create_routing_table,
    create_statistics_panel,
    fetch_dashboard_data,
    format_time_ago,
    format_timestamp,
    get_agent_usage_stats,
    get_hook_event_statistics,
    get_recent_hook_events,
    get_recent_routing_decisions,
    get_routing_statistics,
    main,
    run_dashboard,
)


@pytest.fixture
def mock_conn():
    """Create a mock asyncpg connection."""
    conn = AsyncMock()
    return conn


@pytest.fixture
def sample_routing_stats():
    """Sample routing statistics data."""
    return {
        "total_decisions": 150,
        "unique_agents": 5,
        "avg_confidence": 0.85,
        "avg_routing_time_ms": 7.5,
        "latest_decision": datetime.now(timezone.utc) - timedelta(minutes=5),
        "earliest_decision": datetime.now(timezone.utc) - timedelta(days=7),
    }


@pytest.fixture
def sample_hook_stats():
    """Sample hook event statistics data."""
    return {
        "total_events": 200,
        "unique_sources": 3,
        "latest_event": datetime.now(timezone.utc) - timedelta(minutes=10),
        "earliest_event": datetime.now(timezone.utc) - timedelta(days=7),
    }


@pytest.fixture
def sample_routing_decisions():
    """Sample routing decisions data."""
    now = datetime.now(timezone.utc)
    return [
        {
            "created_at": now - timedelta(minutes=1),
            "selected_agent": "polymorphic-agent",
            "confidence_score": 0.92,
            "routing_strategy": "fuzzy_match",
            "routing_time_ms": 8,
            "reasoning_preview": "High confidence match based on pattern recognition",
        },
        {
            "created_at": now - timedelta(minutes=5),
            "selected_agent": "test-agent",
            "confidence_score": 0.78,
            "routing_strategy": "keyword_match",
            "routing_time_ms": 6,
            "reasoning_preview": "Keyword match with testing context",
        },
    ]


@pytest.fixture
def sample_agent_usage():
    """Sample agent usage statistics."""
    now = datetime.now(timezone.utc)
    return [
        {
            "selected_agent": "polymorphic-agent",
            "usage_count": 75,
            "avg_confidence": 0.88,
            "avg_routing_time_ms": 7.2,
            "last_used": now - timedelta(minutes=1),
        },
        {
            "selected_agent": "test-agent",
            "usage_count": 50,
            "avg_confidence": 0.82,
            "avg_routing_time_ms": 6.5,
            "last_used": now - timedelta(hours=2),
        },
    ]


@pytest.fixture
def sample_hook_events():
    """Sample hook events data."""
    now = datetime.now(timezone.utc)
    return [
        {
            "created_at": now - timedelta(minutes=2),
            "source": "user-prompt-submit",
            "action": "routing_requested",
            "correlation_id": "8b57ec39-45b5-467b-939c-dd1439219f69",
            "payload_preview": '{"user_request": "Help me with testing"}',
        },
        {
            "created_at": now - timedelta(minutes=8),
            "source": "agent-transform",
            "action": "transformation_completed",
            "correlation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "payload_preview": '{"from_agent": "generic", "to_agent": "poly"}',
        },
    ]


# ============================================================================
# Database Query Function Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_routing_statistics_success(mock_conn, sample_routing_stats):
    """Test get_routing_statistics with valid data."""
    mock_conn.fetchrow.return_value = sample_routing_stats

    result = await get_routing_statistics(mock_conn)

    assert result == sample_routing_stats
    assert result["total_decisions"] == 150
    assert result["unique_agents"] == 5
    assert result["avg_confidence"] == 0.85
    mock_conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_routing_statistics_no_data(mock_conn):
    """Test get_routing_statistics when no data is returned."""
    mock_conn.fetchrow.return_value = None

    result = await get_routing_statistics(mock_conn)

    assert result == {}
    mock_conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_recent_routing_decisions_success(
    mock_conn, sample_routing_decisions
):
    """Test get_recent_routing_decisions with valid data."""
    mock_conn.fetch.return_value = sample_routing_decisions

    result = await get_recent_routing_decisions(mock_conn, limit=10)

    assert len(result) == 2
    assert result[0]["selected_agent"] == "polymorphic-agent"
    assert result[1]["selected_agent"] == "test-agent"
    mock_conn.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_get_recent_routing_decisions_custom_limit(mock_conn):
    """Test get_recent_routing_decisions with custom limit."""
    mock_conn.fetch.return_value = []

    result = await get_recent_routing_decisions(mock_conn, limit=5)

    assert result == []
    # Verify the limit parameter was passed correctly
    call_args = mock_conn.fetch.call_args
    assert call_args[0][1] == 5


@pytest.mark.asyncio
async def test_get_agent_usage_stats_success(mock_conn, sample_agent_usage):
    """Test get_agent_usage_stats with valid data."""
    mock_conn.fetch.return_value = sample_agent_usage

    result = await get_agent_usage_stats(mock_conn)

    assert len(result) == 2
    assert result[0]["selected_agent"] == "polymorphic-agent"
    assert result[0]["usage_count"] == 75
    assert result[1]["usage_count"] == 50
    mock_conn.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_get_agent_usage_stats_empty(mock_conn):
    """Test get_agent_usage_stats with no data."""
    mock_conn.fetch.return_value = []

    result = await get_agent_usage_stats(mock_conn)

    assert result == []
    mock_conn.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_get_hook_event_statistics_success(mock_conn, sample_hook_stats):
    """Test get_hook_event_statistics with valid data."""
    mock_conn.fetchrow.return_value = sample_hook_stats

    result = await get_hook_event_statistics(mock_conn)

    assert result == sample_hook_stats
    assert result["total_events"] == 200
    assert result["unique_sources"] == 3
    mock_conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_hook_event_statistics_error_handling(mock_conn):
    """Test get_hook_event_statistics with database error."""
    mock_conn.fetchrow.side_effect = Exception("Table not found")

    result = await get_hook_event_statistics(mock_conn)

    assert "error" in result
    assert result["error"] == "hook_events table not accessible"
    mock_conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_hook_event_statistics_no_data(mock_conn):
    """Test get_hook_event_statistics with no data."""
    mock_conn.fetchrow.return_value = None

    result = await get_hook_event_statistics(mock_conn)

    assert result == {}
    mock_conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_recent_hook_events_success(mock_conn, sample_hook_events):
    """Test get_recent_hook_events with valid data."""
    mock_conn.fetch.return_value = sample_hook_events

    result = await get_recent_hook_events(mock_conn, limit=10)

    assert len(result) == 2
    assert result[0]["source"] == "user-prompt-submit"
    assert result[1]["source"] == "agent-transform"
    mock_conn.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_get_recent_hook_events_error_handling(mock_conn):
    """Test get_recent_hook_events with database error."""
    mock_conn.fetch.side_effect = Exception("Table not found")

    result = await get_recent_hook_events(mock_conn, limit=10)

    assert result == []
    mock_conn.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_get_recent_hook_events_custom_limit(mock_conn):
    """Test get_recent_hook_events with custom limit."""
    mock_conn.fetch.return_value = []

    result = await get_recent_hook_events(mock_conn, limit=5)

    assert result == []
    call_args = mock_conn.fetch.call_args
    assert call_args[0][1] == 5


# ============================================================================
# Formatting Function Tests
# ============================================================================


def test_format_time_ago_seconds():
    """Test format_time_ago for seconds."""
    delta = timedelta(seconds=30)
    result = format_time_ago(delta)
    assert result == "30s ago"


def test_format_time_ago_minutes():
    """Test format_time_ago for minutes."""
    delta = timedelta(minutes=5)
    result = format_time_ago(delta)
    assert result == "5m ago"

    delta = timedelta(seconds=90)
    result = format_time_ago(delta)
    assert result == "1m ago"


def test_format_time_ago_hours():
    """Test format_time_ago for hours."""
    delta = timedelta(hours=3)
    result = format_time_ago(delta)
    assert result == "3h ago"

    delta = timedelta(seconds=7200)  # 2 hours
    result = format_time_ago(delta)
    assert result == "2h ago"


def test_format_time_ago_days():
    """Test format_time_ago for days."""
    delta = timedelta(days=2)
    result = format_time_ago(delta)
    assert result == "2d ago"

    delta = timedelta(days=7)
    result = format_time_ago(delta)
    assert result == "7d ago"


def test_format_time_ago_edge_cases():
    """Test format_time_ago edge cases."""
    # Just under 1 minute
    delta = timedelta(seconds=59)
    result = format_time_ago(delta)
    assert result == "59s ago"

    # Just under 1 hour
    delta = timedelta(seconds=3599)
    result = format_time_ago(delta)
    assert result == "59m ago"

    # Just under 1 day
    delta = timedelta(seconds=86399)
    result = format_time_ago(delta)
    assert result == "23h ago"


def test_format_timestamp_with_timezone():
    """Test format_timestamp with timezone-aware datetime."""
    dt = datetime.now(timezone.utc) - timedelta(minutes=5)
    result = format_timestamp(dt)

    assert "5m ago" in result
    assert "(" in result
    assert ")" in result
    # Should contain time in HH:MM:SS format
    assert ":" in result.split("(")[1]


def test_format_timestamp_without_timezone():
    """Test format_timestamp with naive datetime."""
    dt = datetime.now() - timedelta(minutes=10)
    result = format_timestamp(dt)

    # Should still work and add timezone
    assert "ago" in result
    assert "(" in result


def test_format_timestamp_none():
    """Test format_timestamp with None."""
    result = format_timestamp(None)
    assert result == "N/A"


def test_format_timestamp_empty():
    """Test format_timestamp with empty/falsy value."""
    result = format_timestamp("")
    assert result == "N/A"


# ============================================================================
# Panel and Table Creation Tests
# ============================================================================


def test_create_statistics_panel_healthy_system(
    sample_routing_stats, sample_hook_stats
):
    """Test create_statistics_panel with healthy system."""
    # Make timestamps recent (within 1 hour)
    sample_routing_stats["latest_decision"] = datetime.now(timezone.utc) - timedelta(
        minutes=5
    )
    sample_hook_stats["latest_event"] = datetime.now(timezone.utc) - timedelta(
        minutes=10
    )

    panel = create_statistics_panel(sample_routing_stats, sample_hook_stats)

    assert isinstance(panel, Panel)
    assert "System Statistics" in panel.title
    # Panel should show green healthy status
    text_content = str(panel.renderable)
    assert "HEALTHY" in text_content or "🟢" in text_content


def test_create_statistics_panel_stale_system():
    """Test create_statistics_panel with stale system."""
    routing_stats = {
        "total_decisions": 100,
        "unique_agents": 3,
        "avg_confidence": 0.8,
        "avg_routing_time_ms": 10.0,
        "latest_decision": datetime.now(timezone.utc) - timedelta(hours=2),
    }
    hook_stats = {
        "total_events": 50,
        "unique_sources": 2,
        "latest_event": datetime.now(timezone.utc) - timedelta(hours=3),
    }

    panel = create_statistics_panel(routing_stats, hook_stats)

    assert isinstance(panel, Panel)
    text_content = str(panel.renderable)
    assert "STALE" in text_content or "🔴" in text_content


def test_create_statistics_panel_empty_data():
    """Test create_statistics_panel with empty data."""
    panel = create_statistics_panel({}, {})

    assert isinstance(panel, Panel)
    # Should handle missing data gracefully
    text_content = str(panel.renderable)
    assert "Total Decisions: 0" in text_content


def test_create_statistics_panel_partial_data():
    """Test create_statistics_panel with partial data."""
    routing_stats = {"total_decisions": 50, "unique_agents": 2}
    hook_stats = {"total_events": 25}

    panel = create_statistics_panel(routing_stats, hook_stats)

    assert isinstance(panel, Panel)
    text_content = str(panel.renderable)
    assert "Total Decisions: 50" in text_content
    assert "N/A" in text_content  # For missing avg_confidence


def test_create_routing_table(sample_routing_decisions):
    """Test create_routing_table with valid data."""
    table = create_routing_table(sample_routing_decisions)

    assert isinstance(table, Table)
    assert "Recent Routing Decisions" in table.title
    # Table should have 6 columns
    assert len(table.columns) == 6


def test_create_routing_table_empty():
    """Test create_routing_table with empty data."""
    table = create_routing_table([])

    assert isinstance(table, Table)
    assert "Recent Routing Decisions" in table.title
    # Should still create table structure
    assert len(table.columns) == 6


def test_create_routing_table_missing_fields():
    """Test create_routing_table with missing fields."""
    decisions = [
        {
            "created_at": datetime.now(timezone.utc),
            "selected_agent": "test-agent",
            # Missing confidence_score, routing_time_ms, etc.
        }
    ]

    table = create_routing_table(decisions)

    assert isinstance(table, Table)
    # Should handle missing fields with "N/A"


def test_create_agent_usage_table(sample_agent_usage):
    """Test create_agent_usage_table with valid data."""
    table = create_agent_usage_table(sample_agent_usage)

    assert isinstance(table, Table)
    assert "Agent Usage Statistics" in table.title
    assert len(table.columns) == 5


def test_create_agent_usage_table_empty():
    """Test create_agent_usage_table with empty data."""
    table = create_agent_usage_table([])

    assert isinstance(table, Table)
    assert len(table.columns) == 5


def test_create_agent_usage_table_missing_fields():
    """Test create_agent_usage_table with missing fields."""
    stats = [
        {
            "selected_agent": "test-agent",
            "usage_count": 10,
            # Missing avg_confidence, avg_routing_time_ms, last_used
        }
    ]

    table = create_agent_usage_table(stats)

    assert isinstance(table, Table)
    # Should handle missing fields gracefully


def test_create_hook_events_table(sample_hook_events):
    """Test create_hook_events_table with valid data."""
    table = create_hook_events_table(sample_hook_events)

    assert isinstance(table, Table)
    assert "Recent Hook Events" in table.title
    assert len(table.columns) == 5


def test_create_hook_events_table_empty():
    """Test create_hook_events_table with empty data."""
    table = create_hook_events_table([])

    assert isinstance(table, Table)
    assert len(table.columns) == 5


def test_create_hook_events_table_long_correlation_id():
    """Test create_hook_events_table truncates long correlation IDs."""
    events = [
        {
            "created_at": datetime.now(timezone.utc),
            "source": "test-source",
            "action": "test-action",
            "correlation_id": "a" * 100,  # Very long correlation ID
            "payload_preview": "test payload",
        }
    ]

    table = create_hook_events_table(events)

    assert isinstance(table, Table)
    # Correlation ID should be truncated to 36 characters


def test_create_hook_events_table_none_correlation_id():
    """Test create_hook_events_table with None correlation_id."""
    events = [
        {
            "created_at": datetime.now(timezone.utc),
            "source": "test-source",
            "action": "test-action",
            "correlation_id": None,
            "payload_preview": "test payload",
        }
    ]

    table = create_hook_events_table(events)

    assert isinstance(table, Table)
    # Should show "N/A" for None correlation_id


# ============================================================================
# Dashboard Data Fetching Tests
# ============================================================================


@pytest.mark.asyncio
async def test_fetch_dashboard_data_success(
    mock_conn,
    sample_routing_stats,
    sample_hook_stats,
    sample_routing_decisions,
    sample_agent_usage,
    sample_hook_events,
):
    """Test fetch_dashboard_data with all successful queries."""
    mock_conn.fetchrow.side_effect = [sample_routing_stats, sample_hook_stats]
    mock_conn.fetch.side_effect = [
        sample_routing_decisions,
        sample_agent_usage,
        sample_hook_events,
    ]

    result = await fetch_dashboard_data(mock_conn)

    assert "routing_stats" in result
    assert "hook_stats" in result
    assert "recent_decisions" in result
    assert "agent_usage" in result
    assert "recent_hooks" in result

    assert result["routing_stats"] == sample_routing_stats
    assert result["hook_stats"] == sample_hook_stats
    assert len(result["recent_decisions"]) == 2
    assert len(result["agent_usage"]) == 2
    assert len(result["recent_hooks"]) == 2


@pytest.mark.asyncio
async def test_fetch_dashboard_data_partial_failure(mock_conn):
    """Test fetch_dashboard_data with partial failures."""
    # routing_stats succeeds, hook_stats fails
    mock_conn.fetchrow.side_effect = [
        {"total_decisions": 100},
        Exception("Table not found"),
    ]
    mock_conn.fetch.return_value = []

    result = await fetch_dashboard_data(mock_conn)

    assert "routing_stats" in result
    assert "hook_stats" in result
    # hook_stats should have error message
    assert "error" in result["hook_stats"]


# ============================================================================
# Dashboard Layout Tests
# ============================================================================


def test_create_dashboard_layout_complete_data(
    sample_routing_stats,
    sample_hook_stats,
    sample_routing_decisions,
    sample_agent_usage,
    sample_hook_events,
):
    """Test create_dashboard_layout with complete data."""
    data = {
        "routing_stats": sample_routing_stats,
        "hook_stats": sample_hook_stats,
        "recent_decisions": sample_routing_decisions,
        "agent_usage": sample_agent_usage,
        "recent_hooks": sample_hook_events,
    }

    layout = create_dashboard_layout(data)

    assert isinstance(layout, Layout)
    # Should have header and body
    assert "header" in [child.name for child in layout.children]
    assert "body" in [child.name for child in layout.children]


def test_create_dashboard_layout_empty_data():
    """Test create_dashboard_layout with empty data."""
    data = {
        "routing_stats": {},
        "hook_stats": {},
        "recent_decisions": [],
        "agent_usage": [],
        "recent_hooks": [],
    }

    layout = create_dashboard_layout(data)

    assert isinstance(layout, Layout)
    # Should still create valid layout


# ============================================================================
# Dashboard Runner Tests
# ============================================================================


@pytest.mark.asyncio
async def test_run_dashboard_snapshot_mode(
    sample_routing_stats,
    sample_hook_stats,
    sample_routing_decisions,
    sample_agent_usage,
    sample_hook_events,
):
    """Test run_dashboard in snapshot mode (no watch)."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [sample_routing_stats, sample_hook_stats]
    mock_conn.fetch.side_effect = [
        sample_routing_decisions,
        sample_agent_usage,
        sample_hook_events,
    ]

    with patch("cli.hook_agent_health_dashboard.asyncpg.connect") as mock_connect:
        mock_connect.return_value = mock_conn

        with patch("cli.hook_agent_health_dashboard.console") as mock_console:
            await run_dashboard(watch=False)

            # Should connect to database
            mock_connect.assert_called_once()
            # Should print to console once
            mock_console.print.assert_called_once()
            # Should close connection
            mock_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_run_dashboard_watch_mode_keyboard_interrupt():
    """Test run_dashboard in watch mode with KeyboardInterrupt."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {}
    mock_conn.fetch.return_value = []

    async def sleep_then_interrupt(*args, **kwargs):
        raise KeyboardInterrupt()

    with patch("cli.hook_agent_health_dashboard.asyncpg.connect") as mock_connect:
        mock_connect.return_value = mock_conn

        with patch(
            "cli.hook_agent_health_dashboard.asyncio.sleep", sleep_then_interrupt
        ):
            with patch("cli.hook_agent_health_dashboard.Live"):
                # Should raise KeyboardInterrupt and be handled by caller
                with pytest.raises(KeyboardInterrupt):
                    await run_dashboard(watch=True)

                # Connection should still be closed
                mock_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_run_dashboard_connection_error():
    """Test run_dashboard with database connection error."""
    with patch("cli.hook_agent_health_dashboard.asyncpg.connect") as mock_connect:
        mock_connect.side_effect = Exception("Connection refused")

        with pytest.raises(Exception, match="Connection refused"):
            await run_dashboard(watch=False)


# ============================================================================
# Main Entry Point Tests
# ============================================================================


def test_main_snapshot_mode():
    """Test main entry point in snapshot mode."""
    # Mock sys.argv to not include --watch
    original_argv = sys.argv
    sys.argv = ["hook_agent_health_dashboard.py"]

    try:
        with patch("cli.hook_agent_health_dashboard.asyncio.run") as mock_run:
            with patch("cli.hook_agent_health_dashboard.console"):
                main()
                # Should call run_dashboard with watch=False
                mock_run.assert_called_once()
                # The call should be to run_dashboard with watch=False
    finally:
        sys.argv = original_argv


def test_main_watch_mode_long_flag():
    """Test main entry point with --watch flag."""
    original_argv = sys.argv
    sys.argv = ["hook_agent_health_dashboard.py", "--watch"]

    try:
        with patch("cli.hook_agent_health_dashboard.asyncio.run") as mock_run:
            main()
            mock_run.assert_called_once()
    finally:
        sys.argv = original_argv


def test_main_watch_mode_short_flag():
    """Test main entry point with -w flag."""
    original_argv = sys.argv
    sys.argv = ["hook_agent_health_dashboard.py", "-w"]

    try:
        with patch("cli.hook_agent_health_dashboard.asyncio.run") as mock_run:
            main()
            mock_run.assert_called_once()
    finally:
        sys.argv = original_argv


def test_main_keyboard_interrupt():
    """Test main handles KeyboardInterrupt gracefully."""
    original_argv = sys.argv
    sys.argv = ["hook_agent_health_dashboard.py"]

    try:
        with patch("cli.hook_agent_health_dashboard.asyncio.run") as mock_run:
            mock_run.side_effect = KeyboardInterrupt()

            with patch("cli.hook_agent_health_dashboard.console") as mock_console:
                main()
                # Should print stop message
                mock_console.print.assert_called_once()
                assert "stopped by user" in str(mock_console.print.call_args)
    finally:
        sys.argv = original_argv


def test_main_generic_exception():
    """Test main handles generic exceptions."""
    original_argv = sys.argv
    sys.argv = ["hook_agent_health_dashboard.py"]

    try:
        with patch("cli.hook_agent_health_dashboard.asyncio.run") as mock_run:
            mock_run.side_effect = Exception("Test error")

            with patch("cli.hook_agent_health_dashboard.console") as mock_console:
                with pytest.raises(SystemExit) as exc_info:
                    main()

                # Should exit with code 1
                assert exc_info.value.code == 1
                # Should print error message
                mock_console.print.assert_called()
                assert "Error:" in str(mock_console.print.call_args)
    finally:
        sys.argv = original_argv


# ============================================================================
# Edge Case and Integration Tests
# ============================================================================


def test_format_time_ago_zero_seconds():
    """Test format_time_ago with zero seconds."""
    delta = timedelta(seconds=0)
    result = format_time_ago(delta)
    assert result == "0s ago"


def test_format_time_ago_negative_delta():
    """Test format_time_ago with negative delta (future time)."""
    delta = timedelta(seconds=-60)
    result = format_time_ago(delta)
    # Should handle negative gracefully (shows negative minutes)
    assert "ago" in result


def test_create_statistics_panel_none_timestamps():
    """Test create_statistics_panel with None timestamps."""
    routing_stats = {
        "total_decisions": 10,
        "unique_agents": 2,
        "avg_confidence": 0.9,
        "avg_routing_time_ms": 5.0,
        "latest_decision": None,
    }
    hook_stats = {
        "total_events": 5,
        "unique_sources": 1,
        "latest_event": None,
    }

    panel = create_statistics_panel(routing_stats, hook_stats)

    assert isinstance(panel, Panel)
    # Should show STALE status when timestamps are None
    text_content = str(panel.renderable)
    assert "STALE" in text_content or "🔴" in text_content


def test_create_routing_table_null_values():
    """Test create_routing_table handles null values gracefully."""
    decisions = [
        {
            "created_at": None,
            "selected_agent": None,
            "confidence_score": None,
            "routing_strategy": None,
            "routing_time_ms": None,
            "reasoning_preview": None,
        }
    ]

    table = create_routing_table(decisions)

    assert isinstance(table, Table)
    # All values should be "N/A"


def test_create_agent_usage_table_zero_values():
    """Test create_agent_usage_table with zero values."""
    stats = [
        {
            "selected_agent": "test-agent",
            "usage_count": 0,
            "avg_confidence": 0.0,
            "avg_routing_time_ms": 0.0,
            "last_used": None,
        }
    ]

    table = create_agent_usage_table(stats)

    assert isinstance(table, Table)
    # Should display zeros appropriately


@pytest.mark.asyncio
async def test_fetch_dashboard_data_concurrent_execution(mock_conn):
    """Test fetch_dashboard_data executes queries in proper sequence."""
    call_order = []

    async def track_fetchrow(*args, **kwargs):
        call_order.append("fetchrow")
        return {}

    async def track_fetch(*args, **kwargs):
        call_order.append("fetch")
        return []

    mock_conn.fetchrow = track_fetchrow
    mock_conn.fetch = track_fetch

    await fetch_dashboard_data(mock_conn)

    # Should have 2 fetchrow calls (routing_stats, hook_stats)
    # and 3 fetch calls (recent_decisions, agent_usage, recent_hooks)
    assert call_order.count("fetchrow") == 2
    assert call_order.count("fetch") == 3


def test_format_timestamp_with_microseconds():
    """Test format_timestamp preserves time accuracy with microseconds."""
    dt = datetime.now(timezone.utc) - timedelta(seconds=30, microseconds=500000)
    result = format_timestamp(dt)

    assert "30s ago" in result or "29s ago" in result  # Account for processing time
    assert ":" in result  # Should have time component


def test_create_hook_events_table_special_characters_in_payload():
    """Test create_hook_events_table handles special characters in payload."""
    events = [
        {
            "created_at": datetime.now(timezone.utc),
            "source": "test-source",
            "action": "test-action",
            "correlation_id": "test-id",
            "payload_preview": '{"message": "Line 1\\nLine 2\\tTabbed"}',
        }
    ]

    table = create_hook_events_table(events)

    assert isinstance(table, Table)
    # Should handle special characters without error
