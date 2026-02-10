# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Pattern query CLI for debugging learned_patterns in PostgreSQL.

This CLI tool provides direct access to the learned_patterns table and related
event tables for debugging pattern discovery and injection pipelines.

Usage:
    omni-patterns list [--status STATUS] [--domain DOMAIN] [--limit N] [--json]
    omni-patterns get <pattern_id> [--json]
    omni-patterns stats [--json]
    omni-patterns tail [--follow] [--limit N]

See Also:
    - OMN-1806 ticket for requirements
    - sql/migrations/002_create_learned_patterns.sql for schema
"""

from __future__ import annotations

import json as json_module
import time
from datetime import UTC, datetime, timedelta

# ONEX: exempt - CLI debugging tool uses dynamic DB row types
from typing import TYPE_CHECKING, Any, cast

import click
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from psycopg2.extensions import connection as PgConnection

# Type alias for database rows (RealDictCursor returns dict-like objects)
Row = dict[str, Any]

# =============================================================================
# Version Detection
# =============================================================================

try:
    from importlib.metadata import version as get_version

    __version__ = get_version("omniclaude")
except Exception:
    __version__ = "0.1.0-dev"

# =============================================================================
# Console Setup
# =============================================================================

console = Console()
error_console = Console(stderr=True)


# =============================================================================
# Database Connection
# =============================================================================


def get_db_connection() -> PgConnection:
    """Create a database connection using settings.

    Returns:
        PostgreSQL connection object.

    Raises:
        click.ClickException: If connection fails or settings are missing.
    """
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        from omniclaude.config.settings import settings

        # Validate required settings
        if not settings.postgres_host:
            raise click.ClickException(
                "POSTGRES_HOST not configured. Set in .env or environment."
            )
        if not settings.postgres_port:
            raise click.ClickException(
                "POSTGRES_PORT not configured. Set in .env or environment."
            )
        if not settings.postgres_database:
            raise click.ClickException(
                "POSTGRES_DATABASE not configured. Set in .env or environment."
            )

        # Get DB credential from settings (not hardcoded)
        db_pass = settings.get_effective_postgres_password()
        if not db_pass:
            raise click.ClickException(
                "POSTGRES_PASSWORD not configured. Set in .env or environment."
            )

        conn = psycopg2.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            database=settings.postgres_database,
            user=settings.postgres_user or "postgres",
            password=db_pass,  # noqa: S106 - loaded from settings, not hardcoded
            cursor_factory=RealDictCursor,
            connect_timeout=5,
        )
        return conn

    except ImportError as e:
        raise click.ClickException(f"Missing dependency: {e}. Install psycopg2-binary.")

    except Exception as e:
        error_type = type(e).__name__
        raise click.ClickException(f"Database connection failed ({error_type}): {e}")


# =============================================================================
# CLI Group
# =============================================================================


@click.group(invoke_without_command=True)
@click.option("--version", is_flag=True, help="Show version and exit.")
@click.pass_context
def cli(ctx: click.Context, version: bool) -> None:
    """OmniClaude pattern query CLI for debugging.

    Query learned_patterns and related event tables directly from PostgreSQL.

    Examples:

        # List all validated patterns
        omni-patterns list --status=validated

        # Get details for a specific pattern
        omni-patterns get a1b2c3d4-...

        # Show pattern statistics
        omni-patterns stats

        # Watch for new pattern events
        omni-patterns tail --follow
    """
    if version:
        click.echo(f"omni-patterns {__version__}")
        ctx.exit(0)

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# =============================================================================
# List Command
# =============================================================================


@cli.command("list")
@click.option(
    "--status",
    type=click.Choice(["candidate", "provisional", "validated", "deprecated"]),
    help="Filter by pattern status.",
)
@click.option("--domain", help="Filter by domain_id.")
@click.option("--limit", default=50, type=int, help="Maximum patterns to return.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def cmd_list(
    status: str | None,
    domain: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """List patterns with optional filtering.

    Examples:

        omni-patterns list
        omni-patterns list --status=validated --limit=10
        omni-patterns list --domain=code_review --json
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Build query with optional filters
            conditions = ["is_current = TRUE"]
            # ONEX: exempt - CLI debugging tool uses dynamic DB query parameters
            params: list[Any] = []

            if status:
                conditions.append("status = %s")
                params.append(status)

            if domain:
                conditions.append("domain_id = %s")
                params.append(domain)

            where_clause = " AND ".join(conditions)
            params.append(limit)

            query = f"""
                SELECT
                    id,
                    pattern_signature,
                    domain_id,
                    status,
                    quality_score,
                    confidence,
                    recurrence_count,
                    injection_count_rolling_20,
                    success_count_rolling_20,
                    first_seen_at,
                    last_seen_at
                FROM learned_patterns
                WHERE {where_clause}
                ORDER BY quality_score DESC NULLS LAST, last_seen_at DESC
                LIMIT %s
            """  # nosec B608

            cur.execute(query, params)
            rows = cast("list[Row]", cur.fetchall())

            if as_json:
                # Convert to JSON-serializable format
                output = []
                for row in rows:
                    item = dict(row)
                    # Convert datetime objects to ISO strings
                    for key in ["first_seen_at", "last_seen_at"]:
                        if item.get(key):
                            item[key] = item[key].isoformat()
                    # Convert UUID to string
                    if item.get("id"):
                        item["id"] = str(item["id"])
                    output.append(item)
                click.echo(json_module.dumps(output, indent=2))
            else:
                if not rows:
                    console.print("[yellow]No patterns found.[/yellow]")
                    return

                table = Table(title=f"Learned Patterns ({len(rows)} results)")
                table.add_column("ID", style="dim", max_width=12)
                table.add_column("Signature", style="cyan", max_width=30)
                table.add_column("Domain", style="blue")
                table.add_column("Status", style="green")
                table.add_column("Quality", justify="right")
                table.add_column("Uses", justify="right")
                table.add_column("Success", justify="right")

                for row in rows:
                    # Calculate success rate from rolling metrics
                    inj_count = row.get("injection_count_rolling_20") or 0
                    succ_count = row.get("success_count_rolling_20") or 0
                    success_rate = (
                        f"{(succ_count / inj_count * 100):.0f}%"
                        if inj_count > 0
                        else "N/A"
                    )

                    # Truncate ID for display
                    pattern_id = str(row["id"])[:8] + "..."

                    # Color status
                    status_display = row["status"]
                    if status_display == "validated":
                        status_display = f"[green]{status_display}[/green]"
                    elif status_display == "deprecated":
                        status_display = f"[red]{status_display}[/red]"
                    elif status_display == "candidate":
                        status_display = f"[yellow]{status_display}[/yellow]"

                    table.add_row(
                        pattern_id,
                        row["pattern_signature"][:30],
                        row["domain_id"],
                        status_display,
                        f"{row['quality_score']:.2f}"
                        if row["quality_score"]
                        else "N/A",
                        str(row["recurrence_count"]),
                        success_rate,
                    )

                console.print(table)

    finally:
        conn.close()


# =============================================================================
# Get Command
# =============================================================================


@cli.command("get")
@click.argument("pattern_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def cmd_get(pattern_id: str, as_json: bool) -> None:
    """Get detailed information about a specific pattern.

    PATTERN_ID can be a full UUID or a partial prefix.

    Examples:

        omni-patterns get a1b2c3d4-e5f6-7890-abcd-ef1234567890
        omni-patterns get a1b2c3d4
        omni-patterns get a1b2c3d4 --json
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Support partial ID matching
            if len(pattern_id) < 36:
                query = """
                    SELECT *
                    FROM learned_patterns
                    WHERE id::text LIKE %s
                    LIMIT 1
                """
                cur.execute(query, (f"{pattern_id}%",))
            else:
                query = """
                    SELECT *
                    FROM learned_patterns
                    WHERE id = %s::uuid
                """
                cur.execute(query, (pattern_id,))

            row = cast("Row | None", cur.fetchone())

            if not row:
                raise click.ClickException(f"Pattern not found: {pattern_id}")

            if as_json:
                # Convert to JSON-serializable format
                output = dict(row)
                for key, value in output.items():
                    if hasattr(value, "isoformat"):
                        output[key] = value.isoformat()
                    elif hasattr(value, "__iter__") and not isinstance(value, str):
                        output[key] = list(value) if value else []
                output["id"] = str(output["id"])
                if output.get("supersedes"):
                    output["supersedes"] = str(output["supersedes"])
                if output.get("superseded_by"):
                    output["superseded_by"] = str(output["superseded_by"])
                click.echo(json_module.dumps(output, indent=2, default=str))
            else:
                # Rich formatted output
                console.print()
                console.print(
                    f"[bold cyan]Pattern:[/bold cyan] {row['pattern_signature']}"
                )
                console.print(f"[bold]ID:[/bold] {row['id']}")
                console.print(
                    f"[bold]Domain:[/bold] {row['domain_id']} (v{row['domain_version']})"
                )

                # Status with color
                status = row["status"]
                status_color = {
                    "validated": "green",
                    "deprecated": "red",
                    "candidate": "yellow",
                    "provisional": "blue",
                }.get(status, "white")
                console.print(
                    f"[bold]Status:[/bold] [{status_color}]{status}[/{status_color}]"
                )

                console.print(
                    f"[bold]Quality Score:[/bold] {row['quality_score']:.3f}"
                    if row["quality_score"]
                    else "[bold]Quality Score:[/bold] N/A"
                )
                console.print(f"[bold]Confidence:[/bold] {row['confidence']:.3f}")
                console.print(
                    f"[bold]Recurrence:[/bold] {row['recurrence_count']} times over {row['distinct_days_seen']} days"
                )

                # Success rate
                inj_count = row.get("injection_count_rolling_20") or 0
                succ_count = row.get("success_count_rolling_20") or 0
                if inj_count > 0:
                    rate = succ_count / inj_count * 100
                    console.print(
                        f"[bold]Success Rate:[/bold] {rate:.0f}% ({succ_count}/{inj_count} rolling)"
                    )
                else:
                    console.print("[bold]Success Rate:[/bold] No injections yet")

                if row.get("failure_streak", 0) > 0:
                    console.print(
                        f"[bold red]Failure Streak:[/bold red] {row['failure_streak']}"
                    )

                # Timestamps
                console.print(f"[bold]First Seen:[/bold] {row['first_seen_at']}")
                console.print(f"[bold]Last Seen:[/bold] {row['last_seen_at']}")

                if row.get("promoted_at"):
                    console.print(f"[bold]Promoted At:[/bold] {row['promoted_at']}")
                if row.get("deprecated_at"):
                    console.print(
                        f"[bold red]Deprecated At:[/bold red] {row['deprecated_at']}"
                    )
                    if row.get("deprecation_reason"):
                        console.print(
                            f"[bold red]Reason:[/bold red] {row['deprecation_reason']}"
                        )

                # Compiled snippet
                if row.get("compiled_snippet"):
                    console.print()
                    console.print("[bold]Compiled Snippet:[/bold]")
                    console.print(f"  {row['compiled_snippet'][:500]}...")
                    if row.get("compiled_token_count"):
                        console.print(
                            f"  [dim]({row['compiled_token_count']} tokens)[/dim]"
                        )

                # Version info
                console.print()
                console.print(
                    f"[dim]Version: {row['version']} | Current: {row['is_current']}[/dim]"
                )
                if row.get("supersedes"):
                    console.print(f"[dim]Supersedes: {row['supersedes']}[/dim]")
                if row.get("superseded_by"):
                    console.print(f"[dim]Superseded by: {row['superseded_by']}[/dim]")

    finally:
        conn.close()


# =============================================================================
# Stats Command
# =============================================================================


@cli.command("stats")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def cmd_stats(as_json: bool) -> None:
    """Show pattern statistics and recent activity.

    Displays counts by status and activity in the last 24 hours.

    Examples:

        omni-patterns stats
        omni-patterns stats --json
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            stats: dict[str, Any] = {}  # ONEX: exempt - CLI debugging tool

            # Count by status
            cur.execute("""
                SELECT status, COUNT(*) as count
                FROM learned_patterns
                WHERE is_current = TRUE
                GROUP BY status
                ORDER BY status
            """)
            status_counts = {
                row["status"]: row["count"] for row in cast("list[Row]", cur.fetchall())
            }
            stats["by_status"] = status_counts
            stats["total"] = sum(status_counts.values())

            # Last 24h activity
            yesterday = datetime.now(UTC) - timedelta(days=1)

            # New patterns
            cur.execute(
                """
                SELECT COUNT(*) as count
                FROM learned_patterns
                WHERE first_seen_at >= %s
            """,
                (yesterday,),
            )
            row = cast("Row | None", cur.fetchone())
            stats["new_24h"] = row["count"] if row else 0

            # Injections
            cur.execute(
                """
                SELECT COUNT(*) as count
                FROM pattern_injections
                WHERE injected_at >= %s
            """,
                (yesterday,),
            )
            row = cast("Row | None", cur.fetchone())
            stats["injections_24h"] = row["count"] if row else 0

            # Feedback events
            cur.execute(
                """
                SELECT COUNT(*) as count
                FROM pattern_feedback_log
                WHERE created_at >= %s
            """,
                (yesterday,),
            )
            row = cast("Row | None", cur.fetchone())
            stats["feedback_24h"] = row["count"] if row else 0

            # Lifecycle events
            cur.execute(
                """
                SELECT COUNT(*) as count
                FROM pattern_lineage_events
                WHERE timestamp >= %s
            """,
                (yesterday,),
            )
            row = cast("Row | None", cur.fetchone())
            stats["lifecycle_events_24h"] = row["count"] if row else 0

            if as_json:
                click.echo(json_module.dumps(stats, indent=2))
            else:
                console.print()
                console.print("[bold]Pattern Statistics[/bold]")
                console.print()

                console.print(f"[bold]Total Patterns:[/bold] {stats['total']}")
                for status, count in sorted(status_counts.items()):
                    color = {
                        "validated": "green",
                        "deprecated": "red",
                        "candidate": "yellow",
                        "provisional": "blue",
                    }.get(status, "white")
                    console.print(f"  - [{color}]{status}[/{color}]: {count}")

                console.print()
                console.print("[bold]Last 24 Hours:[/bold]")
                console.print(f"  - New patterns: {stats['new_24h']}")
                console.print(f"  - Injections: {stats['injections_24h']}")
                console.print(f"  - Feedback events: {stats['feedback_24h']}")
                console.print(f"  - Lifecycle events: {stats['lifecycle_events_24h']}")

    finally:
        conn.close()


# =============================================================================
# Tail Command
# =============================================================================


@cli.command("tail")
@click.option("--follow", "-f", is_flag=True, help="Continuously poll for new events.")
@click.option("--limit", default=20, type=int, help="Number of recent events to show.")
@click.option(
    "--interval",
    default=2.0,
    type=float,
    help="Poll interval in seconds (with --follow).",
)
def cmd_tail(follow: bool, limit: int, interval: float) -> None:
    """Tail recent pattern events for debugging.

    Shows events from pattern_injections, pattern_lineage_events,
    and pattern_feedback_log tables.

    Examples:

        omni-patterns tail
        omni-patterns tail --follow
        omni-patterns tail --limit=50 --follow --interval=5
    """
    conn = get_db_connection()
    last_seen: dict[str, datetime] = {
        "injection": datetime.min.replace(tzinfo=UTC),
        "lineage": datetime.min.replace(tzinfo=UTC),
        "feedback": datetime.min.replace(tzinfo=UTC),
    }

    def fetch_events(  # ONEX: exempt - CLI debugging tool
        since: dict[str, datetime],
    ) -> list[dict[str, Any]]:
        """Fetch events from all tables since the given timestamps."""
        events: list[dict[str, Any]] = []  # ONEX: exempt - CLI debugging tool

        with conn.cursor() as cur:
            # Pattern injections
            cur.execute(
                """
                SELECT
                    'INJECTION' as event_type,
                    injection_id as id,
                    injected_at as timestamp,
                    session_id,
                    array_length(pattern_ids, 1) as pattern_count,
                    injection_context as context,
                    outcome_success
                FROM pattern_injections
                WHERE injected_at > %s
                ORDER BY injected_at DESC
                LIMIT %s
            """,
                (since["injection"], limit),
            )
            for row in cast("list[Row]", cur.fetchall()):
                events.append(dict(row))

            # Pattern lineage events
            cur.execute(
                """
                SELECT
                    'LIFECYCLE' as event_type,
                    id,
                    timestamp,
                    pattern_id,
                    event_type as lifecycle_event,
                    event_subtype,
                    success
                FROM pattern_lineage_events
                WHERE timestamp > %s
                ORDER BY timestamp DESC
                LIMIT %s
            """,
                (since["lineage"], limit),
            )
            for row in cast("list[Row]", cur.fetchall()):
                events.append(dict(row))

            # Pattern feedback
            cur.execute(
                """
                SELECT
                    'FEEDBACK' as event_type,
                    id,
                    created_at as timestamp,
                    pattern_name,
                    feedback_type,
                    detected_confidence,
                    user_provided
                FROM pattern_feedback_log
                WHERE created_at > %s
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (since["feedback"], limit),
            )
            for row in cast("list[Row]", cur.fetchall()):
                events.append(dict(row))

        # Sort all events by timestamp
        events.sort(
            key=lambda e: e.get("timestamp") or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return events[:limit]

    try:
        # Initial fetch
        events = fetch_events(last_seen)

        if not events and not follow:
            console.print("[yellow]No recent events found.[/yellow]")
            return

        # Print initial events (oldest first for chronological order)
        for event in reversed(events):
            _print_event(event)
            # Update last seen timestamps
            ts = event.get("timestamp")
            if ts:
                if event["event_type"] == "INJECTION":
                    last_seen["injection"] = max(last_seen["injection"], ts)
                elif event["event_type"] == "LIFECYCLE":
                    last_seen["lineage"] = max(last_seen["lineage"], ts)
                elif event["event_type"] == "FEEDBACK":
                    last_seen["feedback"] = max(last_seen["feedback"], ts)

        if follow:
            console.print("[dim]Watching for new events... (Ctrl+C to stop)[/dim]")
            try:
                while True:
                    time.sleep(interval)
                    new_events = fetch_events(last_seen)
                    for event in reversed(new_events):
                        _print_event(event)
                        ts = event.get("timestamp")
                        if ts:
                            if event["event_type"] == "INJECTION":
                                last_seen["injection"] = max(last_seen["injection"], ts)
                            elif event["event_type"] == "LIFECYCLE":
                                last_seen["lineage"] = max(last_seen["lineage"], ts)
                            elif event["event_type"] == "FEEDBACK":
                                last_seen["feedback"] = max(last_seen["feedback"], ts)
            except KeyboardInterrupt:
                console.print("\n[dim]Stopped.[/dim]")

    finally:
        conn.close()


def _print_event(event: dict[str, Any]) -> None:  # ONEX: exempt - CLI debugging tool
    """Print a single event in a formatted line."""
    ts = event.get("timestamp")
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "unknown"

    event_type = event.get("event_type", "UNKNOWN")

    if event_type == "INJECTION":
        session = str(event.get("session_id", ""))[:8]
        count = event.get("pattern_count") or 0
        context = event.get("context", "unknown")
        outcome = event.get("outcome_success")
        outcome_str = ""
        if outcome is True:
            outcome_str = " [green]success[/green]"
        elif outcome is False:
            outcome_str = " [red]failure[/red]"
        console.print(
            f"[dim]{ts_str}[/dim] [cyan]INJECTION[/cyan]  "
            f"session={session}... patterns={count} context={context}{outcome_str}"
        )

    elif event_type == "LIFECYCLE":
        pattern_id = str(event.get("pattern_id", ""))[:12]
        lifecycle = event.get("lifecycle_event", "unknown")
        subtype = event.get("event_subtype")
        success = event.get("success")
        success_str = (
            " [green]ok[/green]"
            if success
            else " [red]fail[/red]"
            if success is False
            else ""
        )
        subtype_str = f"/{subtype}" if subtype else ""
        console.print(
            f"[dim]{ts_str}[/dim] [yellow]LIFECYCLE[/yellow]  "
            f"pattern={pattern_id}... event={lifecycle}{subtype_str}{success_str}"
        )

    elif event_type == "FEEDBACK":
        pattern = event.get("pattern_name", "unknown")
        feedback_type = event.get("feedback_type", "unknown")
        confidence = event.get("detected_confidence")
        user = event.get("user_provided")
        confidence_str = f" conf={confidence:.2f}" if confidence else ""
        user_str = " [bold]user[/bold]" if user else ""
        console.print(
            f"[dim]{ts_str}[/dim] [magenta]FEEDBACK[/magenta]   "
            f"pattern={pattern} type={feedback_type}{confidence_str}{user_str}"
        )


# =============================================================================
# Entry Point
# =============================================================================


def main() -> None:
    """Main entry point for CLI."""
    cli()


if __name__ == "__main__":
    main()
