# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Pattern query CLI for debugging learned_patterns in PostgreSQL.

DISABLED (OMN-2058): learned_patterns table moved to omniintelligence
as part of DB-SPLIT-07. All commands are disabled pending API integration
(OMN-2059).

Usage:
    omni-patterns list [--status STATUS] [--domain DOMAIN] [--limit N] [--json]
    omni-patterns get <pattern_id> [--json]
    omni-patterns stats [--json]
    omni-patterns tail [--follow] [--limit N]

See Also:
    - OMN-2058: DB-SPLIT-07 clean break
    - OMN-2059: Follow-up for omniintelligence API integration
"""

from __future__ import annotations

from typing import Any

import click
from rich.console import Console

# Type alias for database rows (retained for API compatibility)
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

_DISABLED_MSG = (
    "learned_patterns table moved to omniintelligence (OMN-2059). "
    "CLI disabled pending API integration."
)


# =============================================================================
# CLI Group
# =============================================================================


@click.group(invoke_without_command=True)
@click.option("--version", is_flag=True, help="Show version and exit.")
@click.pass_context
def cli(ctx: click.Context, version: bool) -> None:
    """OmniClaude pattern query CLI for debugging.

    DISABLED (OMN-2058): learned_patterns table moved to omniintelligence.
    All commands are disabled pending API integration (OMN-2059).
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

    DISABLED (OMN-2058): learned_patterns moved to omniintelligence.
    """
    raise click.ClickException(_DISABLED_MSG)


# =============================================================================
# Get Command
# =============================================================================


@cli.command("get")
@click.argument("pattern_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def cmd_get(pattern_id: str, as_json: bool) -> None:
    """Get detailed information about a specific pattern.

    DISABLED (OMN-2058): learned_patterns moved to omniintelligence.
    """
    raise click.ClickException(_DISABLED_MSG)


# =============================================================================
# Stats Command
# =============================================================================


@cli.command("stats")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def cmd_stats(as_json: bool) -> None:
    """Show pattern statistics and recent activity.

    DISABLED (OMN-2058): learned_patterns moved to omniintelligence.
    """
    raise click.ClickException(_DISABLED_MSG)


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

    DISABLED (OMN-2058): learned_patterns moved to omniintelligence.
    """
    raise click.ClickException(_DISABLED_MSG)


# =============================================================================
# Entry Point
# =============================================================================


def main() -> None:
    """Main entry point for CLI."""
    cli()


if __name__ == "__main__":
    main()
