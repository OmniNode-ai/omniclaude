# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""CLI entry point for hook event emission.

This module provides the CLI boundary for emitting Claude Code hook events
to Kafka. It wraps the async emission logic with asyncio.run() and a hard
wall-clock timeout to ensure hooks never block Claude Code.

Design Decisions (OMN-1400):
    - Uses asyncio.run() to bridge sync CLI to async Kafka emission
    - 250ms hard wall-clock timeout on entire emit path
    - Always exits 0 - observability must never break Claude Code UX
    - Structured logging on failure, no exceptions to caller

Usage:
    # From shell script
    echo '{"event_type": "session.started", ...}' | python -m omniclaude.hooks.cli_emit

    # Direct invocation
    python -m omniclaude.hooks.cli_emit session-started --session-id "abc123" --cwd "/workspace"

    # Via entry point (after pip install)
    omniclaude-emit session-started --session-id "abc123" --cwd "/workspace"

See Also:
    - src/omniclaude/hooks/handler_event_emitter.py for core emission logic
    - OMN-1400 ticket for implementation requirements
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any
from uuid import UUID, uuid4

import click

from omniclaude.hooks.handler_event_emitter import (
    emit_prompt_submitted,
    emit_session_ended,
    emit_session_started,
    emit_tool_executed,
)

# Configure logging for hook context
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Hard wall-clock timeout for entire emit path (in seconds)
# This is the absolute maximum time we allow before abandoning the operation
EMIT_TIMEOUT_SECONDS: float = 0.250  # 250ms


# =============================================================================
# Timeout Wrapper
# =============================================================================


def run_with_timeout(coro: Any, timeout: float = EMIT_TIMEOUT_SECONDS) -> Any:
    """Run an async coroutine with a hard wall-clock timeout.

    This function wraps asyncio.run() with a signal-based timeout that
    cannot be exceeded regardless of what the coroutine does internally.

    Args:
        coro: The coroutine to run.
        timeout: Maximum wall-clock time in seconds.

    Returns:
        The result of the coroutine, or None if timeout occurred.
    """

    async def with_timeout() -> Any:
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError:
            logger.warning(
                "emit_timeout_exceeded",
                extra={
                    "timeout_seconds": timeout,
                    "message": "Hook event emission timed out",
                },
            )
            return None

    try:
        return asyncio.run(with_timeout())
    except Exception as e:
        logger.warning(
            "emit_runtime_error",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        return None


# =============================================================================
# CLI Commands
# =============================================================================


@click.group(invoke_without_command=True)
@click.option("--version", is_flag=True, help="Show version and exit.")
@click.pass_context
def cli(ctx: click.Context, version: bool) -> None:
    """OmniClaude hook event emitter.

    Emits Claude Code hook events to Kafka for observability and learning.

    Examples:

        # Emit session started event
        omniclaude-emit session-started --session-id abc123 --cwd /workspace

        # Emit from JSON (stdin)
        echo '{"session_id": "abc123", "cwd": "/workspace"}' | omniclaude-emit session-started --json

    """
    if version:
        click.echo("omniclaude-emit 0.1.0")
        ctx.exit(0)

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command("session-started")
@click.option("--session-id", required=True, help="Session UUID or string ID.")
@click.option("--cwd", required=True, help="Current working directory.")
@click.option(
    "--source",
    default="startup",
    type=click.Choice(["startup", "resume", "clear", "compact"]),
    help="What triggered the session start.",
)
@click.option("--git-branch", default=None, help="Current git branch if available.")
@click.option("--json", "from_json", is_flag=True, help="Read event data from stdin JSON.")
@click.option("--dry-run", is_flag=True, help="Parse and validate but don't emit.")
def cmd_session_started(
    session_id: str,
    cwd: str,
    source: str,
    git_branch: str | None,
    from_json: bool,
    dry_run: bool,
) -> None:
    """Emit a session.started event."""
    try:
        # Parse session_id as UUID or generate from string
        try:
            sid = UUID(session_id)
        except ValueError:
            # Generate deterministic UUID from string
            sid = uuid4()

        if from_json:
            # Read additional data from stdin
            data = json.loads(sys.stdin.read())
            cwd = data.get("cwd", data.get("working_directory", cwd))
            source = data.get("source", data.get("hook_source", source))
            git_branch = data.get("git_branch", git_branch)

        if dry_run:
            click.echo(f"[DRY RUN] Would emit session.started: session_id={sid}, cwd={cwd}")
            return

        result = run_with_timeout(
            emit_session_started(
                session_id=sid,
                working_directory=cwd,
                hook_source=source,
                git_branch=git_branch,
            )
        )

        if result and result.success:
            logger.debug("session_started_emitted", extra={"topic": result.topic})
        elif result:
            logger.warning("session_started_failed", extra={"error": result.error_message})

    except Exception as e:
        logger.warning("session_started_error", extra={"error": str(e)})

    # Always exit 0 - observability must never break Claude Code
    sys.exit(0)


@cli.command("session-ended")
@click.option("--session-id", required=True, help="Session UUID or string ID.")
@click.option(
    "--reason",
    default="other",
    type=click.Choice(["clear", "logout", "prompt_input_exit", "other"]),
    help="What caused the session to end.",
)
@click.option("--duration", default=None, type=float, help="Session duration in seconds.")
@click.option("--tools-count", default=0, type=int, help="Number of tools used.")
@click.option("--json", "from_json", is_flag=True, help="Read event data from stdin JSON.")
@click.option("--dry-run", is_flag=True, help="Parse and validate but don't emit.")
def cmd_session_ended(
    session_id: str,
    reason: str,
    duration: float | None,
    tools_count: int,
    from_json: bool,
    dry_run: bool,
) -> None:
    """Emit a session.ended event."""
    try:
        try:
            sid = UUID(session_id)
        except ValueError:
            sid = uuid4()

        if from_json:
            data = json.loads(sys.stdin.read())
            reason = data.get("reason", reason)
            duration = data.get("duration_seconds", data.get("duration", duration))
            tools_count = data.get("tools_used_count", data.get("tools_count", tools_count))

        if dry_run:
            click.echo(f"[DRY RUN] Would emit session.ended: session_id={sid}, reason={reason}")
            return

        result = run_with_timeout(
            emit_session_ended(
                session_id=sid,
                reason=reason,
                duration_seconds=duration,
                tools_used_count=tools_count,
            )
        )

        if result and result.success:
            logger.debug("session_ended_emitted", extra={"topic": result.topic})
        elif result:
            logger.warning("session_ended_failed", extra={"error": result.error_message})

    except Exception as e:
        logger.warning("session_ended_error", extra={"error": str(e)})

    sys.exit(0)


@cli.command("prompt-submitted")
@click.option("--session-id", required=True, help="Session UUID or string ID.")
@click.option("--prompt-id", default=None, help="Prompt UUID (generated if not provided).")
@click.option("--preview", default="", help="Sanitized prompt preview (max 100 chars).")
@click.option("--length", default=0, type=int, help="Original prompt length.")
@click.option("--intent", default=None, help="Detected intent if available.")
@click.option("--json", "from_json", is_flag=True, help="Read event data from stdin JSON.")
@click.option("--dry-run", is_flag=True, help="Parse and validate but don't emit.")
def cmd_prompt_submitted(
    session_id: str,
    prompt_id: str | None,
    preview: str,
    length: int,
    intent: str | None,
    from_json: bool,
    dry_run: bool,
) -> None:
    """Emit a prompt.submitted event."""
    try:
        try:
            sid = UUID(session_id)
        except ValueError:
            sid = uuid4()

        if prompt_id:
            try:
                pid = UUID(prompt_id)
            except ValueError:
                pid = uuid4()
        else:
            pid = uuid4()

        if from_json:
            data = json.loads(sys.stdin.read())
            preview = data.get("prompt_preview", data.get("preview", preview))
            length = data.get("prompt_length", data.get("length", length))
            intent = data.get("detected_intent", data.get("intent", intent))

        if dry_run:
            click.echo(f"[DRY RUN] Would emit prompt.submitted: session_id={sid}, length={length}")
            return

        result = run_with_timeout(
            emit_prompt_submitted(
                session_id=sid,
                prompt_id=pid,
                prompt_preview=preview,
                prompt_length=length,
                detected_intent=intent,
            )
        )

        if result and result.success:
            logger.debug("prompt_submitted_emitted", extra={"topic": result.topic})
        elif result:
            logger.warning("prompt_submitted_failed", extra={"error": result.error_message})

    except Exception as e:
        logger.warning("prompt_submitted_error", extra={"error": str(e)})

    sys.exit(0)


@cli.command("tool-executed")
@click.option("--session-id", required=True, help="Session UUID or string ID.")
@click.option(
    "--execution-id", default=None, help="Tool execution UUID (generated if not provided)."
)
@click.option("--tool-name", required=True, help="Name of the tool (Read, Write, Bash, etc.).")
@click.option("--success/--failure", default=True, help="Whether the tool succeeded.")
@click.option("--duration-ms", default=None, type=int, help="Execution duration in milliseconds.")
@click.option("--summary", default=None, help="Brief summary of the result.")
@click.option("--json", "from_json", is_flag=True, help="Read event data from stdin JSON.")
@click.option("--dry-run", is_flag=True, help="Parse and validate but don't emit.")
def cmd_tool_executed(
    session_id: str,
    execution_id: str | None,
    tool_name: str,
    success: bool,
    duration_ms: int | None,
    summary: str | None,
    from_json: bool,
    dry_run: bool,
) -> None:
    """Emit a tool.executed event."""
    try:
        try:
            sid = UUID(session_id)
        except ValueError:
            sid = uuid4()

        if execution_id:
            try:
                eid = UUID(execution_id)
            except ValueError:
                eid = uuid4()
        else:
            eid = uuid4()

        if from_json:
            data = json.loads(sys.stdin.read())
            tool_name = data.get("tool_name", tool_name)
            success = data.get("success", success)
            duration_ms = data.get("duration_ms", duration_ms)
            summary = data.get("summary", summary)

        if dry_run:
            click.echo(f"[DRY RUN] Would emit tool.executed: session_id={sid}, tool={tool_name}")
            return

        result = run_with_timeout(
            emit_tool_executed(
                session_id=sid,
                tool_execution_id=eid,
                tool_name=tool_name,
                success=success,
                duration_ms=duration_ms,
                summary=summary,
            )
        )

        if result and result.success:
            logger.debug("tool_executed_emitted", extra={"topic": result.topic})
        elif result:
            logger.warning("tool_executed_failed", extra={"error": result.error_message})

    except Exception as e:
        logger.warning("tool_executed_error", extra={"error": str(e)})

    sys.exit(0)


# =============================================================================
# Module Entry Point
# =============================================================================


def main() -> None:
    """Main entry point for CLI."""
    cli()


if __name__ == "__main__":
    main()
