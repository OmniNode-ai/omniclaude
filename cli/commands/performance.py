"""Performance command for logging router performance metrics."""

import json

import click

from ..utils.db import get_db_cursor
from ..utils.validators import (
    validate_json_string,
    validate_non_negative_integer,
    validate_positive_integer,
    validate_required_field,
    validate_trigger_match_strategy,
)


@click.command("performance")
@click.option("--query", "-q", required=True, help="Query text that was routed")
@click.option("--duration", "-d", type=int, required=True, help="Routing duration in milliseconds")
@click.option("--cache-hit/--cache-miss", default=False, help="Whether result was from cache")
@click.option("--strategy", "-s", required=True, help="Trigger match strategy used")
@click.option("--confidence-breakdown", "-c", type=str, default="{}", help="JSON object with confidence breakdown")
@click.option("--candidates", "-n", type=int, default=1, help="Number of candidates evaluated")
def performance(
    query: str,
    duration: int,
    cache_hit: bool,
    strategy: str,
    confidence_breakdown: str,
    candidates: int,
):
    """Record router performance metrics to the database.

    Example:
        omniclaude-db performance \\
            --query "Implement CLI tool" \\
            --duration 45 \\
            --cache-miss \\
            --strategy enhanced_fuzzy_matching \\
            --confidence-breakdown '{"trigger": 0.95, "context": 0.92}' \\
            --candidates 3
    """
    try:
        # Validate inputs
        query = validate_required_field(query, "query")
        duration = validate_non_negative_integer(duration, "duration")
        strategy = validate_trigger_match_strategy(strategy)
        confidence_json = validate_json_string(confidence_breakdown)
        candidates = validate_positive_integer(candidates, "candidates")

        # Insert into database
        sql = """
            INSERT INTO router_performance_metrics (
                query_text,
                routing_duration_ms,
                cache_hit,
                trigger_match_strategy,
                confidence_components,
                candidates_evaluated
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
        """

        with get_db_cursor() as cursor:
            cursor.execute(
                sql,
                (
                    query,
                    duration,
                    cache_hit,
                    strategy,
                    json.dumps(confidence_json),
                    candidates,
                ),
            )
            result = cursor.fetchone()

        cache_status = "HIT" if cache_hit else "MISS"
        cache_color = "cyan" if cache_hit else "yellow"

        click.secho("✓ Performance metrics recorded successfully", fg="green", bold=True)
        click.echo(f"  ID: {result['id']}")
        click.echo(f"  Duration: {duration}ms")
        click.secho(f"  Cache: {cache_status}", fg=cache_color)
        click.echo(f"  Strategy: {strategy}")
        click.echo(f"  Candidates: {candidates}")
        click.echo(f"  Timestamp: {result['created_at']}")

    except click.BadParameter as e:
        click.secho(f"✗ Validation error: {e}", fg="red", bold=True)
        raise click.Abort()
    except Exception as e:
        click.secho(f"✗ Database error: {e}", fg="red", bold=True)
        raise click.Abort()
