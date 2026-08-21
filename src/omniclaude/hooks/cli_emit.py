# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CLI entry point for hook event emission.

The CLI boundary for emitting Claude Code hook events
to Kafka. It wraps the async emission logic with asyncio.run() and a hard
wall-clock timeout to ensure hooks never block Claude Code.

Design Decisions (OMN-1400):
    - Uses asyncio.run() to bridge sync CLI to async Kafka emission
    - 3s hard wall-clock timeout on entire emit path (configurable via
      KAFKA_HOOK_TIMEOUT_SECONDS env var for slow networks)
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
import os
import sys
import uuid
from collections.abc import Awaitable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar
from uuid import UUID, uuid4

import click

# =============================================================================
# Version Detection
# =============================================================================

try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as get_version

    __version__ = get_version("omniclaude")
except (ImportError, PackageNotFoundError):
    # Fallback for editable installs or when package metadata unavailable
    __version__ = "0.1.0-dev"

from omnibase_core.enums.hooks.claude_code import EnumClaudeCodeHookEventType
from omnibase_core.models.intelligence import ModelToolExecutionContent

from omniclaude.hooks.handler_event_emitter import (
    ModelClaudeHookEventConfig,
    emit_claude_hook_event,
    emit_prompt_submitted,
    emit_session_ended,
    emit_session_started,
    emit_tool_executed,
)
from omniclaude.hooks.models import ModelEventPublishResult
from omniclaude.hooks.schemas import HookSource, SessionEndReason
from omniclaude.hooks.spool_drain import (
    DrainConfig,
    SpoolDrainError,
    drain_spool,
    key_fingerprint,
    resolve_api_base_url,
    resolve_api_key,
    resolve_spool_dir,
)
from omniclaude.hooks.topics import TopicBase, build_topic

# Configure logging for hook context
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)
T = TypeVar("T")

# =============================================================================
# Constants
# =============================================================================

# Default timeout for entire emit path (in seconds)
_DEFAULT_TIMEOUT: float = 3.0


def _parse_timeout() -> float:
    """Parse timeout from env var with fallback to default.

    This function safely parses the KAFKA_HOOK_TIMEOUT_SECONDS environment
    variable, falling back to the default timeout if the value is invalid,
    non-positive, or not set.

    Returns:
        The parsed timeout value, or _DEFAULT_TIMEOUT if parsing fails.
    """
    raw = os.environ.get("KAFKA_HOOK_TIMEOUT_SECONDS", "")
    if not raw:
        return _DEFAULT_TIMEOUT
    try:
        value = float(raw)
        if value <= 0:
            logger.warning(
                "invalid_timeout_non_positive",
                extra={"value": raw, "default": _DEFAULT_TIMEOUT},
            )
            return _DEFAULT_TIMEOUT
        return value
    except ValueError:
        logger.warning(
            "invalid_timeout_not_numeric",
            extra={"value": raw, "default": _DEFAULT_TIMEOUT},
        )
        return _DEFAULT_TIMEOUT


# Hard wall-clock timeout for entire emit path (in seconds)
# This is the absolute maximum time we allow before abandoning the operation
# Can be overridden by KAFKA_HOOK_TIMEOUT_SECONDS env var (useful for slow networks)
EMIT_TIMEOUT_SECONDS: float = _parse_timeout()


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


def run_with_timeout(  # noqa: UP047 - repo validators still parse with pre-PEP 695 syntax.
    coro: Awaitable[T], timeout: float = EMIT_TIMEOUT_SECONDS
) -> T | None:
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

    async def with_timeout() -> T | None:
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
    except Exception as e:  # noqa: BLE001 — boundary: CLI hook must never raise
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
@click.option(
    "--json", "from_json", is_flag=True, help="Read event data from stdin JSON."
)
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
            click.echo(
                f"[DRY RUN] Would emit session.started: session_id={sid}, cwd={cwd}"
            )
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
            logger.warning(
                "session_started_failed", extra={"error": result.error_message}
            )

    except Exception as e:  # noqa: BLE001 — boundary: CLI hook must never raise
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
@click.option(
    "--duration", default=None, type=float, help="Session duration in seconds."
)
@click.option("--tools-count", default=0, type=int, help="Number of tools used.")
@click.option(
    "--json", "from_json", is_flag=True, help="Read event data from stdin JSON."
)
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
            tools_count = data.get(
                "tools_used_count", data.get("tools_count", tools_count)
            )

        if dry_run:
            click.echo(
                f"[DRY RUN] Would emit session.ended: session_id={sid}, reason={reason}"
            )
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
            logger.warning(
                "session_ended_failed", extra={"error": result.error_message}
            )

    except Exception as e:  # noqa: BLE001 — boundary: CLI hook must never raise
        logger.warning("session_ended_error", extra={"error": str(e)})

    sys.exit(0)


@cli.command("prompt-submitted")
@click.option("--session-id", required=True, help="Session UUID or string ID.")
@click.option(
    "--prompt-id", default=None, help="Prompt UUID (generated if not provided)."
)
@click.option("--preview", default="", help="Sanitized prompt preview (max 100 chars).")
@click.option("--length", default=0, type=int, help="Original prompt length.")
@click.option("--intent", default=None, help="Detected intent if available.")
@click.option(
    "--json", "from_json", is_flag=True, help="Read event data from stdin JSON."
)
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
    # ONEX: exempt - CLI command parameters defined by click decorators
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
            click.echo(
                f"[DRY RUN] Would emit prompt.submitted: session_id={sid}, length={length}"
            )
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
            logger.warning(
                "prompt_submitted_failed", extra={"error": result.error_message}
            )

    except Exception as e:  # noqa: BLE001 — boundary: CLI hook must never raise
        logger.warning("prompt_submitted_error", extra={"error": str(e)})

    sys.exit(0)


@cli.command("tool-executed")
@click.option("--session-id", required=True, help="Session UUID or string ID.")
@click.option(
    "--execution-id",
    default=None,
    help="Tool execution UUID (generated if not provided).",
)
@click.option(
    "--tool-name", required=True, help="Name of the tool (Read, Write, Bash, etc.)."
)
@click.option("--success/--failure", default=True, help="Whether the tool succeeded.")
@click.option(
    "--duration-ms", default=None, type=int, help="Execution duration in milliseconds."
)
@click.option("--summary", default=None, help="Brief summary of the result.")
@click.option(
    "--json", "from_json", is_flag=True, help="Read event data from stdin JSON."
)
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
    # ONEX: exempt - CLI command parameters defined by click decorators
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
            click.echo(
                f"[DRY RUN] Would emit tool.executed: session_id={sid}, tool={tool_name}"
            )
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
            logger.warning(
                "tool_executed_failed", extra={"error": result.error_message}
            )

    except Exception as e:  # noqa: BLE001 — boundary: CLI hook must never raise
        logger.warning("tool_executed_error", extra={"error": str(e)})

    sys.exit(0)


@cli.command("claude-hook-event")
@click.option("--session-id", required=True, help="Session UUID or string ID.")
@click.option(
    "--event-type",
    required=True,
    type=click.Choice([e.value for e in EnumClaudeCodeHookEventType]),
    help="The Claude Code hook event type.",
)
@click.option(
    "--prompt", default=None, help="The full prompt text (for UserPromptSubmit)."
)
@click.option(
    "--correlation-id", default=None, help="Correlation UUID for distributed tracing."
)
@click.option(
    "--json", "from_json", is_flag=True, help="Read event data from stdin JSON."
)
@click.option("--dry-run", is_flag=True, help="Parse and validate but don't emit.")
def cmd_claude_hook_event(
    session_id: str,
    event_type: str,
    prompt: str | None,
    correlation_id: str | None,
    from_json: bool,
    dry_run: bool,
) -> None:
    """Emit a Claude hook event to the omniintelligence topic.

    This command emits events in the format expected by omniintelligence's
    NodeClaudeHookEventEffect for intelligence processing and learning.
    """
    # ONEX: exempt - CLI command parameters defined by click decorators
    try:
        # Parse correlation_id if provided
        corr_id = _string_to_uuid(correlation_id) if correlation_id else None

        if from_json:
            # Read additional data from stdin
            stdin_content = sys.stdin.read()
            try:
                data = json.loads(stdin_content)
            except json.JSONDecodeError as e:
                logger.warning(
                    "invalid_stdin_json",
                    extra={"error": str(e), "content_length": len(stdin_content)},
                )
                sys.exit(0)  # Fail soft - observability must never break Claude Code
            event_type = data.get("event_type", event_type)
            prompt = data.get("prompt", data.get("payload", {}).get("prompt", prompt))
            if data.get("correlation_id"):
                corr_id = _string_to_uuid(data["correlation_id"])

        # Convert string event type to enum
        hook_event_type = EnumClaudeCodeHookEventType(event_type)

        if dry_run:
            click.echo(
                f"[DRY RUN] Would emit claude-hook-event: "
                f"session_id={session_id}, event_type={event_type}"
            )
            return

        # OMN-6884: correlation_id defaults to uuid4() in the config dataclass,
        # so only pass it explicitly when the caller provided one.
        config_kwargs: dict[str, object] = {
            "event_type": hook_event_type,
            "session_id": session_id,
            "prompt": prompt,
        }
        if corr_id is not None:
            config_kwargs["correlation_id"] = corr_id
        config = ModelClaudeHookEventConfig(**config_kwargs)  # type: ignore[arg-type]  # Why: dict[str, object] **kwargs to typed model fields

        result = run_with_timeout(emit_claude_hook_event(config))

        if result and result.success:
            logger.debug("claude_hook_event_emitted", extra={"topic": result.topic})
        elif result:
            logger.warning(
                "claude_hook_event_failed", extra={"error": result.error_message}
            )

    except Exception as e:  # noqa: BLE001 — boundary: CLI hook must never raise
        logger.warning("claude_hook_event_error", extra={"error": str(e)})

    # Always exit 0 - observability must never break Claude Code
    sys.exit(0)


# =============================================================================
# Tool Content Emission (OMN-1701)
# =============================================================================
# Emits tool execution content using ModelToolExecutionContent from omnibase_core.
# Used by omniintelligence for pattern learning from Claude Code tool executions.
# =============================================================================


def _emit_tool_content(content: ModelToolExecutionContent) -> ModelEventPublishResult:
    """Emit a tool content event via node_emit_daemon (OMN-10837).

    Routes through the daemon socket client instead of a direct EventBusKafka
    connection. The daemon provides circuit-breaker, exponential backoff, and
    disk-spool durability — eliminating the legacy embedded-publisher crash-loop
    path that had no retry on Redpanda restart.

    Args:
        content: The tool execution content model to emit.

    Returns:
        ModelEventPublishResult indicating success or failure.
    """
    import os
    import sys

    # Resolve emit_client_wrapper from the plugin lib directory.
    # The module path is constructed relative to CLAUDE_PLUGIN_ROOT so the
    # hook works both from the source tree and from the plugin cache.
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    hooks_lib = os.path.join(plugin_root, "hooks", "lib") if plugin_root else ""
    if hooks_lib and hooks_lib not in sys.path:
        sys.path.insert(0, hooks_lib)

    topic = build_topic(TopicBase.TOOL_CONTENT)

    try:
        from emit_client_wrapper import emit_event

        payload = json.loads(content.model_dump_json())
        success = emit_event("tool.content", payload)

        if success:
            logger.debug(
                "tool_content_emitted_via_daemon",
                extra={
                    "topic": topic,
                    "tool_name": content.tool_name_raw,
                    "session_id": content.session_id,
                },
            )
            return ModelEventPublishResult(
                success=True, topic=topic, partition=None, offset=None
            )

        logger.warning(
            "tool_content_daemon_rejected",
            extra={"topic": topic, "tool_name": content.tool_name_raw},
        )
        return ModelEventPublishResult(
            success=False,
            topic=topic,
            error_message="emit_event returned False (daemon unavailable or validation failed)",
        )

    except Exception as e:  # noqa: BLE001 — boundary: emit must degrade not crash
        error_msg = f"{type(e).__name__}: {e!s}"
        logger.warning(
            "tool_content_publish_failed",
            extra={"topic": topic, "error": error_msg},
        )
        return ModelEventPublishResult(
            success=False,
            topic=topic,
            error_message=error_msg[:1000],
        )


@cli.command("tool-content")
@click.option("--session-id", required=True, help="Session UUID or string ID.")
@click.option("--tool-name", required=True, help="Tool name (Read, Write, Edit, Bash).")
@click.option(
    "--tool-type",
    default=None,
    help="Deprecated: Tool type classification (ignored, kept for backwards compat).",
)
@click.option("--file-path", default=None, help="File path if applicable.")
@click.option(
    "--content-preview", default=None, help="Content preview (max 2000 chars)."
)
@click.option("--content-length", default=None, type=int, help="Full content length.")
@click.option("--content-hash", default=None, help="SHA256 hash of content.")
@click.option("--language", default=None, help="Detected programming language.")
@click.option("--success/--failure", default=True, help="Whether the tool succeeded.")
@click.option(
    "--duration-ms", default=None, type=float, help="Execution duration in ms."
)
@click.option(
    "--correlation-id", default=None, help="Correlation UUID for distributed tracing."
)
@click.option(
    "--json", "from_json", is_flag=True, help="Read event data from stdin JSON."
)
@click.option("--dry-run", is_flag=True, help="Parse and validate but don't emit.")
def cmd_tool_content(
    session_id: str,
    tool_name: str,
    tool_type: str | None,  # Kept for backwards compatibility, ignored
    file_path: str | None,
    content_preview: str | None,
    content_length: int | None,
    content_hash: str | None,
    language: str | None,
    success: bool,
    duration_ms: float | None,
    correlation_id: str | None,
    from_json: bool,
    dry_run: bool,
) -> None:
    """Emit tool content event for pattern learning.

    This command emits tool execution content to Kafka for pattern learning
    using the ModelToolExecutionContent model from omnibase_core.

    Example:
        omniclaude-emit tool-content \\
            --session-id abc123 \\
            --tool-name Write \\
            --file-path /workspace/src/main.py \\
            --content-preview "def main():\\n    print('hello')" \\
            --content-length 42 \\
            --language python
    """
    # ONEX: exempt - CLI command parameters defined by click decorators
    # Note: tool_type is kept for backwards compatibility but ignored
    _ = tool_type  # Explicitly mark as unused

    try:
        if from_json:
            stdin_content = sys.stdin.read()
            try:
                data = json.loads(stdin_content)
            except json.JSONDecodeError as e:
                logger.warning(
                    "invalid_stdin_json",
                    extra={"error": str(e), "content_length": len(stdin_content)},
                )
                sys.exit(0)  # Fail soft - observability must never break Claude Code

            # Override with JSON values if present
            session_id = data.get("session_id", session_id)
            tool_name = data.get("tool_name", tool_name)
            file_path = data.get("file_path", file_path)
            content_preview = data.get("content_preview", content_preview)
            content_length = data.get("content_length", content_length)
            content_hash = data.get("content_hash", content_hash)
            language = data.get("language", language)
            success = data.get("success", success)
            duration_ms = data.get("duration_ms", duration_ms)
            correlation_id = data.get("correlation_id", correlation_id)

        # Build model using factory method for automatic enum resolution
        content = ModelToolExecutionContent.from_tool_name(
            tool_name_raw=tool_name,
            file_path=file_path,
            language=language,
            content_preview=content_preview,
            content_length=content_length,
            content_hash=content_hash,
            success=success,
            duration_ms=duration_ms,
            session_id=session_id,
            correlation_id=correlation_id or str(uuid4()),
            timestamp=datetime.now(UTC),
        )

        if dry_run:
            click.echo(
                f"[DRY RUN] Would emit tool-content: "
                f"session_id={session_id}, tool={tool_name}"
            )
            click.echo(f"Payload: {content.model_dump_json(indent=2)}")
            return

        result = _emit_tool_content(content)

        if result.success:
            logger.debug("tool_content_emitted", extra={"topic": result.topic})
        else:
            logger.warning("tool_content_failed", extra={"error": result.error_message})

    except Exception as e:  # noqa: BLE001 — boundary: CLI hook must never raise
        logger.warning("tool_content_error", extra={"error": str(e)})

    # Always exit 0 - observability must never break Claude Code
    sys.exit(0)


# =============================================================================
# Spool Drain / Shipper (OMN-16090)
# =============================================================================
# Drains the local hook-event spool (written by omnibase_infra's receipt-mode
# CLI on emit-daemon failure) to the cloud gateway. This is a separate,
# explicitly-invoked command — never run inline from a hook path, so it can
# never block or slow Claude Code. See src/omniclaude/hooks/spool_drain.py
# for the durability contract (never deletes, only moves after a confirmed
# terminal status; retries transient failures with backoff; 4xx is poison).
# =============================================================================


@cli.command("drain")
@click.option(
    "--spool-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Spool directory. Default: $ONEX_STATE_DIR/emit_spool (fails fast if unset).",
)
@click.option(
    "--base-url",
    default=None,
    help="Gateway base URL. Default: $ONEX_API_BASE_URL (fails fast if unset).",
)
@click.option(
    "--source",
    default="local_macos_claude_hooks",
    help="Producer runtime profile stamped on every batch.",
)
@click.option(
    "--batch-size", type=int, default=250, help="Events per batch (contract cap: 250)."
)
@click.option(
    "--limit", type=int, default=0, help="Max spool files to consider (0 = all)."
)
@click.option(
    "--max-batches", type=int, default=0, help="Stop after N batches (0 = no cap)."
)
@click.option(
    "--dry-run", is_flag=True, help="Frame and report; no network, no file moves."
)
@click.option(
    "--require-status",
    type=click.Choice(["completed", "published"]),
    default="completed",
    help="Status a workflow must reach before its files are moved to shipped/.",
)
@click.option("--poll-attempts", type=int, default=20)
@click.option("--poll-interval", type=float, default=3.0)
@click.option("--timeout", type=float, default=30.0)
@click.option(
    "--retry-attempts",
    type=int,
    default=3,
    help="Retries for transient (5xx/connection) submit failures.",
)
@click.option(
    "--json", "as_json", is_flag=True, help="Print the drain summary as JSON."
)
def cmd_drain(
    spool_dir: Path | None,
    base_url: str | None,
    source: str,
    batch_size: int,
    limit: int,
    max_batches: int,
    dry_run: bool,
    require_status: str,
    poll_attempts: int,
    poll_interval: float,
    timeout: float,
    retry_attempts: int,
    as_json: bool,
) -> None:
    """Drain the local hook-event spool to the gateway (POST /v1/workflows).

    Never invoked from a hook — this is an explicit operator/cron command.
    Credentials are resolved by name from ONEX_GATEWAY_API_KEY or
    ONEX_GATEWAY_API_KEY_FILE; fails fast if neither is set.
    """
    try:
        resolved_spool_dir = resolve_spool_dir(spool_dir)
        resolved_base_url = resolve_api_base_url(base_url)
        # Dry-run needs no credential — it makes no network call.
        api_key = "" if dry_run else resolve_api_key()
        if not dry_run:
            click.echo(
                f"credential: len={len(api_key)} fp={key_fingerprint(api_key)}",
                err=True,
            )

        config = DrainConfig(
            spool_dir=resolved_spool_dir,
            base_url=resolved_base_url,
            api_key=api_key,
            source=source,
            batch_size=batch_size,
            limit=limit,
            max_batches=max_batches,
            dry_run=dry_run,
            require_status=require_status,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
            timeout=timeout,
            retry_attempts=retry_attempts,
        )
        summary = drain_spool(config)
    except SpoolDrainError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)

    if as_json:
        click.echo(summary.model_dump_json(indent=2))
    else:
        click.echo(f"spool             : {resolved_spool_dir}")
        click.echo(f"mode              : {'DRY-RUN' if summary.dry_run else 'LIVE'}")
        click.echo(f"files present     : {summary.files_present}")
        click.echo(f"files considered  : {summary.files_considered}")
        click.echo(
            f"unique events     : {summary.unique_events} "
            f"({summary.duplicate_files_collapsed} duplicate file(s) collapsed)"
        )
        if summary.skipped:
            click.echo(f"skipped (malformed, left in spool): {len(summary.skipped)}")
            for s in summary.skipped[:10]:
                click.echo(f"  - {s.path}: {s.reason}")
        click.echo(f"batches           : {len(summary.batches)}")
        for b in summary.batches:
            click.echo(
                f"  {b.batch_sha[:12]}… events={b.event_count} confirmed={b.confirmed} "
                f"status={b.status} http={b.http_status} moved={b.files_moved}"
            )
        click.echo(f"events shipped    : {summary.events_shipped}")
        click.echo(f"remaining in spool: {summary.remaining_in_spool}")

    sys.exit(1 if summary.had_failures else 0)


# =============================================================================
# Module Entry Point
# =============================================================================


def main() -> None:
    """Main entry point for CLI."""
    cli()


if __name__ == "__main__":
    main()
