"""Transformation command for logging agent transformation events."""

import click

from ..utils.db import get_db_cursor
from ..utils.validators import (
    validate_agent_name,
    validate_confidence_score,
    validate_non_negative_integer,
    validate_required_field,
)


@click.command("transformation")
@click.option("--source", "-s", required=True, help="Source agent name")
@click.option("--target", "-t", required=True, help="Target agent name")
@click.option("--reason", "-r", required=True, help="Transformation reason")
@click.option(
    "--confidence", "-c", type=float, required=True, help="Confidence score (0.0-1.0)"
)
@click.option(
    "--duration",
    "-d",
    type=int,
    default=0,
    help="Transformation duration in milliseconds",
)
@click.option("--success/--failure", default=True, help="Transformation success status")
def transformation(
    source: str,
    target: str,
    reason: str,
    confidence: float,
    duration: int,
    success: bool,
):
    """Record an agent transformation event to the database.

    Example:
        omniclaude-db transformation \\
            --source agent-workflow-coordinator \\
            --target agent-code-architect \\
            --reason "Code architecture design needed" \\
            --confidence 0.92 \\
            --duration 35 \\
            --success
    """
    try:
        # Validate inputs
        source = validate_agent_name(source)
        target = validate_agent_name(target)
        reason = validate_required_field(reason, "reason")
        confidence = validate_confidence_score(confidence)
        duration = validate_non_negative_integer(duration, "duration")

        # Insert into database
        query = """
            INSERT INTO agent_transformation_events (
                source_agent,
                target_agent,
                transformation_reason,
                confidence_score,
                transformation_duration_ms,
                success
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
        """

        with get_db_cursor() as cursor:
            cursor.execute(
                query,
                (source, target, reason, confidence, duration, success),
            )
            result = cursor.fetchone()

        status_icon = "✓" if success else "✗"
        status_color = "green" if success else "yellow"

        click.secho(
            f"{status_icon} Transformation event recorded successfully",
            fg=status_color,
            bold=True,
        )
        click.echo(f"  ID: {result['id']}")
        click.echo(f"  Source: {source}")
        click.echo(f"  Target: {target}")
        click.echo(f"  Confidence: {confidence:.2%}")
        click.echo(f"  Success: {success}")
        click.echo(f"  Timestamp: {result['created_at']}")

    except click.BadParameter as e:
        click.secho(f"✗ Validation error: {e}", fg="red", bold=True)
        raise click.Abort()
    except Exception as e:
        click.secho(f"✗ Database error: {e}", fg="red", bold=True)
        raise click.Abort()
