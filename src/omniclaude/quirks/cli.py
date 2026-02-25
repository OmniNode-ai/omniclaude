# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Quirks CLI — operator commands for the ValidatorRollout stage machine.

Commands:

    status          Print current stage for all quirk types.
    promote         Promote a quirk type to the next stage (WARN or BLOCK).
    approve-block   Record operator approval for a future WARN → BLOCK promotion.

Usage::

    uv run python -m omniclaude.quirks.cli status
    uv run python -m omniclaude.quirks.cli promote STUB_CODE --to warn
    uv run python -m omniclaude.quirks.cli approve-block STUB_CODE --approver ops@example.com

Shorthand (from quirks.cli module entry point)::

    uv run python -m quirks.cli promote STUB_CODE --to warn

Related:
    - OMN-2564: ValidatorRolloutController
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

import asyncio
import sys

import click

from omniclaude.quirks.controller import (
    ApprovalRequiredError,
    InsufficientFindingsError,
    InvalidTransitionError,
    NodeValidatorRolloutOrchestratorOrchestrator,
    PromotionError,
)
from omniclaude.quirks.enums import QuirkStage, QuirkType


def _get_controller() -> NodeValidatorRolloutOrchestratorOrchestrator:
    """Return a controller instance.

    Uses in-memory store only (no DB session factory) because this CLI is
    intended for development/operator use without requiring a live DB
    connection.  For production use, wire up a session factory via the
    Python API directly.
    """
    return NodeValidatorRolloutOrchestratorOrchestrator(db_session_factory=None)


@click.group()
def cli() -> None:
    """Quirks Detector operator commands."""


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@cli.command("status")
def status_cmd() -> None:
    """Print current stage for all quirk types."""

    async def _run() -> None:
        controller = _get_controller()
        await controller.start()
        records = await controller.get_all_stages()
        await controller.stop()

        click.echo(
            f"{'QuirkType':<25} {'Stage':<10} {'Promoted At':<30} {'Approved By'}"
        )
        click.echo("-" * 80)
        for r in records:
            promoted = r.promoted_at.isoformat() if r.promoted_at else "(initial)"
            approved = r.approved_by or ""
            stage_label = r.current_stage.value
            click.echo(
                f"{r.quirk_type.value:<25} {stage_label:<10} {promoted:<30} {approved}"
            )

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# promote
# ---------------------------------------------------------------------------


@cli.command("promote")
@click.argument("quirk_type", metavar="QUIRK_TYPE")
@click.option(
    "--to",
    "to_stage",
    required=True,
    type=click.Choice(["warn", "block"], case_sensitive=False),
    help="Target stage (warn or block).",
)
@click.option(
    "--finding-count",
    type=int,
    default=0,
    show_default=True,
    help="Finding count in last 7 days (must meet threshold).",
)
@click.option(
    "--false-positive-rate",
    type=float,
    default=None,
    help="Confirmed false-positive rate [0.0-1.0]; required for OBSERVE -> WARN.",
)
@click.option(
    "--operator",
    default=None,
    help="Operator e-mail; required for WARN → BLOCK.",
)
@click.option(
    "--notes", default=None, help="Optional notes to attach to the audit record."
)
def promote_cmd(
    quirk_type: str,
    to_stage: str,
    finding_count: int,
    false_positive_rate: float | None,
    operator: str | None,
    notes: str | None,
) -> None:
    """Promote QUIRK_TYPE to the next enforcement stage.

    QUIRK_TYPE must be one of: SYCOPHANCY, STUB_CODE, NO_TESTS,
    LOW_EFFORT_PATCH, UNSAFE_ASSUMPTION, IGNORED_INSTRUCTIONS, HALLUCINATED_API
    """
    try:
        qt = QuirkType(quirk_type.upper())
    except ValueError:
        click.echo(
            f"Error: unknown QuirkType '{quirk_type}'. "
            f"Valid values: {', '.join(v.value for v in QuirkType)}",
            err=True,
        )
        sys.exit(1)

    target = QuirkStage.WARN if to_stage.lower() == "warn" else QuirkStage.BLOCK

    async def _run() -> None:
        controller = _get_controller()
        await controller.start()
        try:
            record = await controller.promote(
                qt,
                to_stage=target,
                finding_count_7d=finding_count,
                confirmed_false_positive_rate=false_positive_rate,
                operator=operator,
                notes=notes,
            )
        except (
            InvalidTransitionError,
            InsufficientFindingsError,
            ApprovalRequiredError,
            PromotionError,
        ) as exc:
            click.echo(f"Promotion failed: {exc}", err=True)
            sys.exit(1)
        finally:
            await controller.stop()

        promoted_at = record.promoted_at.isoformat() if record.promoted_at else "(now)"
        click.echo(
            f"Promoted {qt.value}: {record.current_stage.value} at {promoted_at}"
        )

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# approve-block
# ---------------------------------------------------------------------------


@cli.command("approve-block")
@click.argument("quirk_type", metavar="QUIRK_TYPE")
@click.option(
    "--approver",
    required=True,
    help="E-mail of the approving operator.",
)
def approve_block_cmd(quirk_type: str, approver: str) -> None:
    """Record operator approval for a WARN → BLOCK promotion.

    QUIRK_TYPE must currently be in WARN stage.

    This does NOT perform the actual promotion.  Run ``promote --to block``
    afterward to complete the transition.
    """
    try:
        qt = QuirkType(quirk_type.upper())
    except ValueError:
        click.echo(
            f"Error: unknown QuirkType '{quirk_type}'. "
            f"Valid values: {', '.join(v.value for v in QuirkType)}",
            err=True,
        )
        sys.exit(1)

    async def _run() -> None:
        controller = _get_controller()
        await controller.start()
        try:
            await controller.approve_block(qt, approver=approver)
        except InvalidTransitionError as exc:
            click.echo(f"Approval failed: {exc}", err=True)
            sys.exit(1)
        finally:
            await controller.stop()

        click.echo(
            f"BLOCK approval recorded for {qt.value} by {approver}. "
            "Run 'promote --to block' to complete the transition."
        )

    asyncio.run(_run())


def main() -> None:
    """Entry point for ``uv run python -m omniclaude.quirks.cli``."""
    cli()


if __name__ == "__main__":
    main()
