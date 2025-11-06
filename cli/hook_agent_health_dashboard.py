#!/usr/bin/env python3
"""
Hook/Agent Health Dashboard

Monitors the health of the hook/agent routing system by querying:
- agent_routing_decisions table (routing history)
- hook_events table (hook execution history)
- System health metrics

Usage:
    poetry run python cli/hook_agent_health_dashboard.py
    poetry run python cli/hook_agent_health_dashboard.py --watch  # Auto-refresh every 10s
"""

import asyncio

# Add config for type-safe settings
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import asyncpg
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import settings

# Database configuration
DB_CONFIG = {
    "host": "localhost",
    "port": 5436,
    "user": "postgres",
    "password": settings.get_effective_postgres_password(),
    "database": "omninode_bridge",
}

console = Console()


async def get_routing_statistics(conn: asyncpg.Connection) -> dict[str, Any]:
    """Get agent routing decision statistics."""
    query = """
    SELECT
        COUNT(*) as total_decisions,
        COUNT(DISTINCT selected_agent) as unique_agents,
        AVG(confidence_score) as avg_confidence,
        AVG(routing_time_ms) as avg_routing_time_ms,
        MAX(created_at) as latest_decision,
        MIN(created_at) as earliest_decision
    FROM agent_routing_decisions
    WHERE created_at >= NOW() - INTERVAL '7 days'
    """
    row = await conn.fetchrow(query)
    return dict(row) if row else {}


async def get_recent_routing_decisions(
    conn: asyncpg.Connection, limit: int = 10
) -> list[dict[str, Any]]:
    """Get recent agent routing decisions."""
    query = """
    SELECT
        created_at,
        selected_agent,
        confidence_score,
        routing_strategy,
        routing_time_ms,
        LEFT(reasoning, 100) as reasoning_preview
    FROM agent_routing_decisions
    ORDER BY created_at DESC
    LIMIT $1
    """
    rows = await conn.fetch(query, limit)
    return [dict(row) for row in rows]


async def get_agent_usage_stats(
    conn: asyncpg.Connection,
) -> list[dict[str, Any]]:
    """Get agent usage statistics."""
    query = """
    SELECT
        selected_agent,
        COUNT(*) as usage_count,
        AVG(confidence_score) as avg_confidence,
        AVG(routing_time_ms) as avg_routing_time_ms,
        MAX(created_at) as last_used
    FROM agent_routing_decisions
    WHERE created_at >= NOW() - INTERVAL '7 days'
    GROUP BY selected_agent
    ORDER BY usage_count DESC
    LIMIT 10
    """
    rows = await conn.fetch(query)
    return [dict(row) for row in rows]


async def get_hook_event_statistics(conn: asyncpg.Connection) -> dict[str, Any]:
    """Get hook event statistics."""
    query = """
    SELECT
        COUNT(*) as total_events,
        COUNT(DISTINCT source) as unique_sources,
        MAX(created_at) as latest_event,
        MIN(created_at) as earliest_event
    FROM hook_events
    WHERE created_at >= NOW() - INTERVAL '7 days'
    """
    try:
        row = await conn.fetchrow(query)
        return dict(row) if row else {}
    except Exception:
        return {"error": "hook_events table not accessible"}


async def get_recent_hook_events(
    conn: asyncpg.Connection, limit: int = 10
) -> list[dict[str, Any]]:
    """Get recent hook events."""
    query = """
    SELECT
        created_at,
        source,
        action,
        metadata->>'correlation_id' as correlation_id,
        LEFT(payload::text, 50) as payload_preview
    FROM hook_events
    ORDER BY created_at DESC
    LIMIT $1
    """
    try:
        rows = await conn.fetch(query, limit)
        return [dict(row) for row in rows]
    except Exception:
        return []


def create_statistics_panel(routing_stats: dict, hook_stats: dict) -> Panel:
    """Create statistics overview panel."""
    now = datetime.now(timezone.utc)

    # Routing statistics
    total_decisions = routing_stats.get("total_decisions", 0)
    unique_agents = routing_stats.get("unique_agents", 0)
    avg_confidence = routing_stats.get("avg_confidence", 0)
    avg_routing_time = routing_stats.get("avg_routing_time_ms", 0)
    latest_decision = routing_stats.get("latest_decision")

    # Hook statistics
    total_events = hook_stats.get("total_events", 0)
    unique_sources = hook_stats.get("unique_sources", 0)
    latest_event = hook_stats.get("latest_event")

    # Check if system is healthy
    routing_healthy = latest_decision and (now - latest_decision) < timedelta(hours=1)
    hook_healthy = latest_event and (now - latest_event) < timedelta(hours=1)

    routing_status = "🟢 HEALTHY" if routing_healthy else "🔴 STALE"
    hook_status = "🟢 HEALTHY" if hook_healthy else "🔴 STALE"

    text = Text()
    text.append("System Health\n", style="bold cyan")
    text.append(f"  Routing: {routing_status}\n")
    text.append(f"  Hooks: {hook_status}\n\n")

    text.append("Routing Statistics (7 days)\n", style="bold yellow")
    text.append(f"  Total Decisions: {total_decisions}\n")
    text.append(f"  Unique Agents: {unique_agents}\n")
    text.append(
        f"  Avg Confidence: {avg_confidence:.2f}\n"
        if avg_confidence
        else "  Avg Confidence: N/A\n"
    )
    text.append(
        f"  Avg Routing Time: {avg_routing_time:.1f}ms\n"
        if avg_routing_time
        else "  Avg Routing Time: N/A\n"
    )
    if latest_decision:
        time_ago = now - latest_decision
        text.append(f"  Latest Decision: {format_time_ago(time_ago)}\n")

    text.append("\nHook Statistics (7 days)\n", style="bold yellow")
    text.append(f"  Total Events: {total_events}\n")
    text.append(f"  Unique Sources: {unique_sources}\n")
    if latest_event:
        time_ago = now - latest_event
        text.append(f"  Latest Event: {format_time_ago(time_ago)}\n")

    return Panel(text, title="📊 System Statistics", border_style="cyan")


def create_routing_table(decisions: list[dict]) -> Table:
    """Create routing decisions table."""
    table = Table(title="Recent Routing Decisions", show_lines=True)
    table.add_column("Time", style="cyan")
    table.add_column("Agent", style="green")
    table.add_column("Confidence", style="yellow")
    table.add_column("Strategy", style="magenta")
    table.add_column("Time (ms)", style="blue")
    table.add_column("Reasoning", style="white")

    for decision in decisions:
        created_at = decision.get("created_at")
        time_str = format_timestamp(created_at) if created_at else "N/A"

        confidence = decision.get("confidence_score")
        confidence_str = f"{confidence:.2f}" if confidence else "N/A"

        routing_time = decision.get("routing_time_ms")
        routing_time_str = str(routing_time) if routing_time else "N/A"

        table.add_row(
            time_str,
            decision.get("selected_agent", "N/A"),
            confidence_str,
            decision.get("routing_strategy", "N/A"),
            routing_time_str,
            decision.get("reasoning_preview", "N/A"),
        )

    return table


def create_agent_usage_table(agent_stats: list[dict]) -> Table:
    """Create agent usage statistics table."""
    table = Table(title="Agent Usage Statistics (7 days)", show_lines=True)
    table.add_column("Agent", style="green")
    table.add_column("Usage Count", style="cyan")
    table.add_column("Avg Confidence", style="yellow")
    table.add_column("Avg Time (ms)", style="blue")
    table.add_column("Last Used", style="magenta")

    for stat in agent_stats:
        avg_conf = stat.get("avg_confidence")
        avg_conf_str = f"{avg_conf:.2f}" if avg_conf else "N/A"

        avg_time = stat.get("avg_routing_time_ms")
        avg_time_str = f"{avg_time:.1f}" if avg_time else "N/A"

        last_used = stat.get("last_used")
        last_used_str = format_timestamp(last_used) if last_used else "N/A"

        table.add_row(
            stat.get("selected_agent", "N/A"),
            str(stat.get("usage_count", 0)),
            avg_conf_str,
            avg_time_str,
            last_used_str,
        )

    return table


def create_hook_events_table(events: list[dict]) -> Table:
    """Create hook events table."""
    table = Table(title="Recent Hook Events", show_lines=True)
    table.add_column("Time", style="cyan")
    table.add_column("Source", style="green")
    table.add_column("Action", style="yellow")
    table.add_column("Correlation ID", style="magenta")
    table.add_column("Payload", style="white")

    for event in events:
        created_at = event.get("created_at")
        time_str = format_timestamp(created_at) if created_at else "N/A"

        table.add_row(
            time_str,
            event.get("source", "N/A"),
            event.get("action", "N/A"),
            (
                event.get("correlation_id", "N/A")[:36]
                if event.get("correlation_id")
                else "N/A"
            ),
            event.get("payload_preview", "N/A"),
        )

    return table


def format_timestamp(dt: datetime) -> str:
    """Format datetime for display."""
    if not dt:
        return "N/A"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    time_ago = now - dt
    return f"{format_time_ago(time_ago)} ({dt.strftime('%H:%M:%S')})"


def format_time_ago(delta: timedelta) -> str:
    """Format time delta as human-readable string."""
    seconds = delta.total_seconds()
    if seconds < 60:
        return f"{int(seconds)}s ago"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m ago"
    elif seconds < 86400:
        return f"{int(seconds / 3600)}h ago"
    else:
        return f"{int(seconds / 86400)}d ago"


async def fetch_dashboard_data(conn: asyncpg.Connection) -> dict[str, Any]:
    """Fetch all dashboard data."""
    routing_stats = await get_routing_statistics(conn)
    hook_stats = await get_hook_event_statistics(conn)
    recent_decisions = await get_recent_routing_decisions(conn, limit=10)
    agent_usage = await get_agent_usage_stats(conn)
    recent_hooks = await get_recent_hook_events(conn, limit=10)

    return {
        "routing_stats": routing_stats,
        "hook_stats": hook_stats,
        "recent_decisions": recent_decisions,
        "agent_usage": agent_usage,
        "recent_hooks": recent_hooks,
    }


def create_dashboard_layout(data: dict[str, Any]) -> Layout:
    """Create dashboard layout."""
    layout = Layout()

    # Split into header and body
    layout.split_column(
        Layout(name="header", size=15),
        Layout(name="body"),
    )

    # Header: Statistics
    layout["header"].update(
        create_statistics_panel(
            data["routing_stats"],
            data["hook_stats"],
        )
    )

    # Body: Tables
    layout["body"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )

    layout["left"].split_column(
        Layout(create_routing_table(data["recent_decisions"])),
        Layout(create_agent_usage_table(data["agent_usage"])),
    )

    layout["right"].update(create_hook_events_table(data["recent_hooks"]))

    return layout


async def run_dashboard(watch: bool = False):
    """Run the dashboard."""
    conn = await asyncpg.connect(**DB_CONFIG)

    try:
        if watch:
            # Live updating mode
            with Live(console=console, refresh_per_second=0.1) as live:
                while True:
                    data = await fetch_dashboard_data(conn)
                    layout = create_dashboard_layout(data)
                    live.update(
                        Panel(
                            layout,
                            title="🔍 Hook/Agent Health Dashboard",
                            border_style="green",
                        )
                    )
                    await asyncio.sleep(10)
        else:
            # Single snapshot
            data = await fetch_dashboard_data(conn)
            layout = create_dashboard_layout(data)
            console.print(
                Panel(
                    layout, title="🔍 Hook/Agent Health Dashboard", border_style="green"
                )
            )

    finally:
        await conn.close()


def main():
    """Main entry point."""
    watch_mode = "--watch" in sys.argv or "-w" in sys.argv

    try:
        asyncio.run(run_dashboard(watch=watch_mode))
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
