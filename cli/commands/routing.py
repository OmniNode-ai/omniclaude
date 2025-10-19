"""Routing decision command for logging agent routing decisions."""

import json

import click

from ..utils.db import get_db_cursor
from ..utils.validators import (
    validate_agent_name,
    validate_confidence_score,
    validate_json_array,
    validate_json_string,
    validate_non_negative_integer,
    validate_required_field,
    validate_routing_strategy,
)


@click.command("routing-decision")
@click.option("--request", "-r", required=True, help="User request text")
@click.option("--agent", "-a", required=True, help="Selected agent name")
@click.option(
    "--confidence", "-c", type=float, required=True, help="Confidence score (0.0-1.0)"
)
@click.option(
    "--alternatives", type=str, default="[]", help="JSON array of alternative agents"
)
@click.option("--reasoning", type=str, default="", help="Reasoning for agent selection")
@click.option(
    "--strategy", "-s", default="enhanced_fuzzy_matching", help="Routing strategy used"
)
@click.option(
    "--context", type=str, default="{}", help="JSON object with additional context"
)
@click.option(
    "--routing-time",
    "-t",
    type=int,
    default=0,
    help="Routing decision time in milliseconds",
)
def routing_decision(
    request: str,
    agent: str,
    confidence: float,
    alternatives: str,
    reasoning: str,
    strategy: str,
    context: str,
    routing_time: int,
):
    """Record an agent routing decision to the database.

    Example:
        omniclaude-db routing-decision \\
            --request "Implement CLI tool" \\
            --agent agent-workflow-coordinator \\
            --confidence 0.95 \\
            --alternatives '[{"agent": "agent-code-architect", "confidence": 0.72}]' \\
            --reasoning "Multi-step development task" \\
            --strategy enhanced_fuzzy_matching \\
            --context '{"domain": "cli_development"}' \\
            --routing-time 45
    """
    try:
        # Validate inputs
        request = validate_required_field(request, "request")
        agent = validate_agent_name(agent)
        confidence = validate_confidence_score(confidence)
        alternatives_json = validate_json_array(alternatives)
        strategy = validate_routing_strategy(strategy)
        context_json = validate_json_string(context)
        routing_time = validate_non_negative_integer(routing_time, "routing_time")

        # Insert into database
        query = """
            INSERT INTO agent_routing_decisions (
                user_request,
                selected_agent,
                confidence_score,
                alternatives,
                reasoning,
                routing_strategy,
                context,
                routing_time_ms
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
        """

        with get_db_cursor() as cursor:
            cursor.execute(
                query,
                (
                    request,
                    agent,
                    confidence,
                    json.dumps(alternatives_json),
                    reasoning,
                    strategy,
                    json.dumps(context_json),
                    routing_time,
                ),
            )
            result = cursor.fetchone()

        click.secho("✓ Routing decision recorded successfully", fg="green", bold=True)
        click.echo(f"  ID: {result['id']}")
        click.echo(f"  Agent: {agent}")
        click.echo(f"  Confidence: {confidence:.2%}")
        click.echo(f"  Strategy: {strategy}")
        click.echo(f"  Timestamp: {result['created_at']}")

    except click.BadParameter as e:
        click.secho(f"✗ Validation error: {e}", fg="red", bold=True)
        raise click.Abort()
    except Exception as e:
        click.secho(f"✗ Database error: {e}", fg="red", bold=True)
        raise click.Abort()
