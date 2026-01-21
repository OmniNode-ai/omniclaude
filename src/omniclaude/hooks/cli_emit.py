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
import uuid
from typing import Any
from uuid import UUID, uuid4

import click

# =============================================================================
# Version Detection
# =============================================================================

try:
    from importlib.metadata import version as get_version

    __version__ = get_version("omniclaude")
except Exception:
    # Fallback for editable installs or when package metadata unavailable
    __version__ = "0.1.0-dev"

from omniclaude.hooks.handler_event_emitter import (
    emit_prompt_submitted,
    emit_session_ended,
    emit_session_started,
    emit_tool_executed,
)
from omniclaude.hooks.schemas import HookSource, SessionEndReason

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
# UUID Helpers
# =============================================================================


def _string_to_uuid(value: str) -> UUID:
    """Convert a string to a UUID deterministically.

    This function enables consistent UUID generation from arbitrary string
    identifiers, which is critical for event correlation across hook events.

    Deterministic UUID Strategy:
        - If the input is already a valid UUID string (e.g., from Claude Code),
          it is parsed directly to preserve the original identity.
        - If the input is an arbitrary string (e.g., a session name or custom ID),
          uuid5 with NAMESPACE_DNS is used to generate a deterministic UUID.
          This ensures the same string always produces the same UUID, enabling
          reliable event correlation across session.started, prompt.submitted,
          tool.executed, and session.ended events.

    Why uuid5 with NAMESPACE_DNS?
        - uuid5 uses SHA-1 hashing, providing deterministic output for a given
          namespace + name combination.
        - NAMESPACE_DNS is a well-known namespace that ensures uniqueness when
          combined with the input string.
        - The same (namespace, name) pair will always generate the same UUID,
          even across different machines or process restarts.

    Args:
        value: A string to convert. Can be either:
            - A valid UUID string (e.g., "550e8400-e29b-41d4-a716-446655440000")
            - An arbitrary identifier (e.g., "my-session-123", "abc123")

    Returns:
        A UUID object. Either the parsed UUID if valid, or a deterministic
        uuid5-generated UUID from the input string.

    Examples:
        >>> _string_to_uuid("550e8400-e29b-41d4-a716-446655440000")
        UUID('550e8400-e29b-41d4-a716-446655440000')

        >>> _string_to_uuid("my-session-123")  # Same input = same output
        UUID('...')  # Deterministic, reproducible UUID

        >>> _string_to_uuid("my-session-123") == _string_to_uuid("my-session-123")
        True
    """
    try:
        return UUID(value)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_DNS, value)


# =============================================================================
# Timeout Wrapper
# =============================================================================


def run_with_timeout(coro: Any, timeout: float = EMIT_TIMEOUT_SECONDS) -> Any:
    """Run an async coroutine with a cooperative timeout.

    This function wraps asyncio.run() with asyncio.wait_for() for timeout handling.
    Note that asyncio.wait_for uses cooperative cancellation - the timeout only
    triggers at await points. If the coroutine performs blocking I/O or CPU-bound
    work without yielding, the timeout cannot interrupt it.

    For hook event emission, this is acceptable because:
    - Kafka operations are async and yield frequently
    - The timeout is a best-effort safeguard, not a hard guarantee

    Args:
        coro: The coroutine to run.
        timeout: Maximum time in seconds before cooperative cancellation.

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
        click.echo(f"omniclaude-emit {__version__}")
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
        # Parse session_id as UUID or generate deterministic UUID from string
        sid = _string_to_uuid(session_id)

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
                hook_source=HookSource(source),
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
        # Parse session_id as UUID or generate deterministic UUID from string
        sid = _string_to_uuid(session_id)

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
                reason=SessionEndReason(reason),
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
        # Parse session_id as UUID or generate deterministic UUID from string
        sid = _string_to_uuid(session_id)

        # Parse prompt_id as UUID, generate deterministic UUID from string, or random if not provided
        pid = _string_to_uuid(prompt_id) if prompt_id else uuid4()

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
        # Parse session_id as UUID or generate deterministic UUID from string
        sid = _string_to_uuid(session_id)

        # Parse execution_id as UUID, generate deterministic UUID from string, or random if not provided
        eid = _string_to_uuid(execution_id) if execution_id else uuid4()

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
