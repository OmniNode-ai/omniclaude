"""Query command for retrieving database records with filters."""

from datetime import datetime, timedelta
from typing import Optional

import click
from tabulate import tabulate

from ..utils.db import get_db_cursor


@click.group("query")
def query():
    """Query database records with various filters."""
    pass


@query.command("routing")
@click.option("--agent", "-a", help="Filter by agent name")
@click.option("--strategy", "-s", help="Filter by routing strategy")
@click.option("--min-confidence", type=float, help="Minimum confidence score")
@click.option("--max-confidence", type=float, help="Maximum confidence score")
@click.option("--hours", "-h", type=int, help="Records from last N hours")
@click.option("--limit", "-l", type=int, default=10, help="Maximum records to return")
@click.option("--format", "-f", type=click.Choice(["table", "json", "csv"]), default="table", help="Output format")
def query_routing(
    agent: Optional[str],
    strategy: Optional[str],
    min_confidence: Optional[float],
    max_confidence: Optional[float],
    hours: Optional[int],
    limit: int,
    format: str,
):
    """Query routing decision records.

    Example:
        omniclaude-db query routing --agent agent-workflow-coordinator --limit 5
        omniclaude-db query routing --strategy enhanced_fuzzy_matching --hours 24
        omniclaude-db query routing --min-confidence 0.8 --format json
    """
    try:
        # Build query
        conditions = []
        params = []

        if agent:
            conditions.append("selected_agent = %s")
            params.append(agent)

        if strategy:
            conditions.append("routing_strategy = %s")
            params.append(strategy)

        if min_confidence is not None:
            conditions.append("confidence_score >= %s")
            params.append(min_confidence)

        if max_confidence is not None:
            conditions.append("confidence_score <= %s")
            params.append(max_confidence)

        if hours:
            conditions.append("created_at >= %s")
            params.append(datetime.now() - timedelta(hours=hours))

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            SELECT
                id,
                user_request,
                selected_agent,
                confidence_score,
                routing_strategy,
                routing_time_ms,
                created_at
            FROM agent_routing_decisions
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s
        """
        params.append(limit)

        with get_db_cursor() as cursor:
            cursor.execute(sql, tuple(params))
            results = cursor.fetchall()

        if not results:
            click.echo("No routing decisions found matching the criteria.")
            return

        _display_results(results, format, "Routing Decisions")

    except Exception as e:
        click.secho(f"✗ Query error: {e}", fg="red", bold=True)
        raise click.Abort()


@query.command("transformations")
@click.option("--source", "-s", help="Filter by source agent")
@click.option("--target", "-t", help="Filter by target agent")
@click.option("--success/--failure", default=None, help="Filter by success status")
@click.option("--hours", "-h", type=int, help="Records from last N hours")
@click.option("--limit", "-l", type=int, default=10, help="Maximum records to return")
@click.option("--format", "-f", type=click.Choice(["table", "json", "csv"]), default="table", help="Output format")
def query_transformations(
    source: Optional[str],
    target: Optional[str],
    success: Optional[bool],
    hours: Optional[int],
    limit: int,
    format: str,
):
    """Query transformation event records.

    Example:
        omniclaude-db query transformations --target agent-code-architect
        omniclaude-db query transformations --success --hours 24
    """
    try:
        # Build query
        conditions = []
        params = []

        if source:
            conditions.append("source_agent = %s")
            params.append(source)

        if target:
            conditions.append("target_agent = %s")
            params.append(target)

        if success is not None:
            conditions.append("success = %s")
            params.append(success)

        if hours:
            conditions.append("created_at >= %s")
            params.append(datetime.now() - timedelta(hours=hours))

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            SELECT
                id,
                source_agent,
                target_agent,
                transformation_reason,
                confidence_score,
                transformation_duration_ms,
                success,
                created_at
            FROM agent_transformation_events
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s
        """
        params.append(limit)

        with get_db_cursor() as cursor:
            cursor.execute(sql, tuple(params))
            results = cursor.fetchall()

        if not results:
            click.echo("No transformation events found matching the criteria.")
            return

        _display_results(results, format, "Transformation Events")

    except Exception as e:
        click.secho(f"✗ Query error: {e}", fg="red", bold=True)
        raise click.Abort()


@query.command("performance")
@click.option("--strategy", "-s", help="Filter by trigger match strategy")
@click.option("--cache-hit/--cache-miss", default=None, help="Filter by cache status")
@click.option("--max-duration", type=int, help="Maximum duration in milliseconds")
@click.option("--hours", "-h", type=int, help="Records from last N hours")
@click.option("--limit", "-l", type=int, default=10, help="Maximum records to return")
@click.option("--format", "-f", type=click.Choice(["table", "json", "csv"]), default="table", help="Output format")
def query_performance(
    strategy: Optional[str],
    cache_hit: Optional[bool],
    max_duration: Optional[int],
    hours: Optional[int],
    limit: int,
    format: str,
):
    """Query router performance metrics.

    Example:
        omniclaude-db query performance --cache-hit --hours 24
        omniclaude-db query performance --max-duration 100 --format csv
    """
    try:
        # Build query
        conditions = []
        params = []

        if strategy:
            conditions.append("trigger_match_strategy = %s")
            params.append(strategy)

        if cache_hit is not None:
            conditions.append("cache_hit = %s")
            params.append(cache_hit)

        if max_duration is not None:
            conditions.append("routing_duration_ms <= %s")
            params.append(max_duration)

        if hours:
            conditions.append("created_at >= %s")
            params.append(datetime.now() - timedelta(hours=hours))

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            SELECT
                id,
                query_text,
                routing_duration_ms,
                cache_hit,
                trigger_match_strategy,
                candidates_evaluated,
                created_at
            FROM router_performance_metrics
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s
        """
        params.append(limit)

        with get_db_cursor() as cursor:
            cursor.execute(sql, tuple(params))
            results = cursor.fetchall()

        if not results:
            click.echo("No performance metrics found matching the criteria.")
            return

        _display_results(results, format, "Performance Metrics")

    except Exception as e:
        click.secho(f"✗ Query error: {e}", fg="red", bold=True)
        raise click.Abort()


@query.command("stats")
def query_stats():
    """Display aggregate statistics across all tables."""
    try:
        # Routing decisions stats
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) as total,
                    AVG(confidence_score) as avg_confidence,
                    AVG(routing_time_ms) as avg_routing_time,
                    COUNT(DISTINCT selected_agent) as unique_agents
                FROM agent_routing_decisions
            """
            )
            routing_stats = cursor.fetchone()

        # Transformation stats
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
                    AVG(transformation_duration_ms) as avg_duration
                FROM agent_transformation_events
            """
            )
            transformation_stats = cursor.fetchone()

        # Performance stats
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) as total,
                    AVG(routing_duration_ms) as avg_duration,
                    SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) as cache_hits,
                    AVG(candidates_evaluated) as avg_candidates
                FROM router_performance_metrics
            """
            )
            performance_stats = cursor.fetchone()

        # Display stats
        click.secho("\n📊 Database Statistics", fg="cyan", bold=True)

        click.secho("\nRouting Decisions:", fg="yellow", bold=True)
        click.echo(f"  Total: {routing_stats['total']}")
        click.echo(
            f"  Avg Confidence: {routing_stats['avg_confidence']:.2%}"
            if routing_stats["avg_confidence"]
            else "  Avg Confidence: N/A"
        )
        click.echo(
            f"  Avg Routing Time: {routing_stats['avg_routing_time']:.0f}ms"
            if routing_stats["avg_routing_time"]
            else "  Avg Routing Time: N/A"
        )
        click.echo(f"  Unique Agents: {routing_stats['unique_agents']}")

        click.secho("\nTransformation Events:", fg="yellow", bold=True)
        click.echo(f"  Total: {transformation_stats['total']}")
        click.echo(f"  Successful: {transformation_stats['successful']}")
        if transformation_stats["total"] > 0:
            success_rate = (transformation_stats["successful"] / transformation_stats["total"]) * 100
            click.echo(f"  Success Rate: {success_rate:.1f}%")
        click.echo(
            f"  Avg Duration: {transformation_stats['avg_duration']:.0f}ms"
            if transformation_stats["avg_duration"]
            else "  Avg Duration: N/A"
        )

        click.secho("\nPerformance Metrics:", fg="yellow", bold=True)
        click.echo(f"  Total: {performance_stats['total']}")
        click.echo(
            f"  Avg Duration: {performance_stats['avg_duration']:.0f}ms"
            if performance_stats["avg_duration"]
            else "  Avg Duration: N/A"
        )
        click.echo(f"  Cache Hits: {performance_stats['cache_hits']}")
        if performance_stats["total"] > 0:
            cache_hit_rate = (performance_stats["cache_hits"] / performance_stats["total"]) * 100
            click.echo(f"  Cache Hit Rate: {cache_hit_rate:.1f}%")
        click.echo(
            f"  Avg Candidates: {performance_stats['avg_candidates']:.1f}"
            if performance_stats["avg_candidates"]
            else "  Avg Candidates: N/A"
        )

    except Exception as e:
        click.secho(f"✗ Query error: {e}", fg="red", bold=True)
        raise click.Abort()


def _display_results(results, format: str, title: str):
    """Display query results in specified format."""
    if format == "json":
        import json

        # Convert datetime objects to strings
        for row in results:
            for key, value in row.items():
                if isinstance(value, datetime):
                    row[key] = value.isoformat()
        click.echo(json.dumps(list(results), indent=2))

    elif format == "csv":
        import csv
        import sys

        if results:
            writer = csv.DictWriter(sys.stdout, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)

    else:  # table format
        click.secho(f"\n{title}", fg="cyan", bold=True)
        if results:
            headers = list(results[0].keys())
            rows = [list(row.values()) for row in results]
            click.echo(tabulate(rows, headers=headers, tablefmt="grid"))
        click.echo(f"\nTotal records: {len(results)}\n")
