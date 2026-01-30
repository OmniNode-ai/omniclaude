#!/usr/bin/env python3
"""Emit Client Wrapper - Hybrid Python + Shell Fallback for Hook Event Emission.

This module provides the client-side interface for all hooks to emit events via
the emit daemon. It uses a hybrid approach with Python as the primary path and
shell (socat/netcat) as a fallback escape hatch.

Design Decisions:
    - **Hybrid approach**: Python primary (uses EmitClient from omnibase_infra),
      shell fallback as escape hatch when Python fails
    - **Fallback policy**: Daemon-owned, gated by consecutive failure count
    - **Single emission**: Hook sends once, daemon handles fan-out to multiple topics
    - **Non-blocking**: Never raises exceptions that would break hooks

Event Types:
    - session.started: Claude Code session initialization
    - session.ended: Claude Code session termination
    - prompt.submitted: User prompt submission (daemon fans out to 2 topics)
    - tool.executed: Tool execution completion

Example Usage:
    ```python
    from emit_client_wrapper import emit_event, daemon_available, get_fallback_status

    # Check if daemon is available
    if daemon_available():
        print("Daemon is running")

    # Emit an event (returns True on success, False on failure)
    success = emit_event(
        event_type="prompt.submitted",
        payload={"prompt": "Hello", "session_id": "abc123"},
        timeout_ms=50,
    )

    # Check fallback status
    status = get_fallback_status()
    print(f"Consecutive failures: {status['consecutive_failures']}")
    print(f"Fallback allowed: {status['fallback_allowed']}")
    ```

CLI Usage:
    ```bash
    # Emit an event from shell script
    python -m emit_client_wrapper emit \
        --event-type "prompt.submitted" \
        --payload '{"session_id": "abc123", "prompt": "Hello"}'

    # Check daemon availability
    python -m emit_client_wrapper ping

    # Get fallback status
    python -m emit_client_wrapper status
    ```

Related Tickets:
    - OMN-1631: Emit daemon integration
    - OMN-1632: Hook migration to daemon

.. versionadded:: 0.2.0
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omnibase_infra.runtime.emit_daemon.client import EmitClient

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Default socket path (matches daemon default)
# NOTE: /tmp is standard for Unix domain sockets - not a security issue
DEFAULT_SOCKET_PATH = Path("/tmp/omniclaude-emit.sock")  # noqa: S108

# Default timeout for emit operations (milliseconds)
DEFAULT_TIMEOUT_MS = 50

# Consecutive failures before fallback is allowed
# Set high initially to prefer daemon path, but allow escape hatch
FALLBACK_THRESHOLD = 5

# Supported event types (must match daemon's EventRegistry)
SUPPORTED_EVENT_TYPES = frozenset(
    [
        "session.started",
        "session.ended",
        "prompt.submitted",
        "tool.executed",
    ]
)

# =============================================================================
# State Management (thread-safe)
# =============================================================================

_state_lock = threading.Lock()
_consecutive_failures = 0
_python_client_available: bool | None = None  # None = not yet checked
_emit_client: EmitClient | None = None


def _increment_failures() -> int:
    """Increment consecutive failure count and return new value."""
    global _consecutive_failures
    with _state_lock:
        _consecutive_failures += 1
        return _consecutive_failures


def _reset_failures() -> None:
    """Reset consecutive failure count to zero."""
    global _consecutive_failures
    with _state_lock:
        _consecutive_failures = 0


def _get_failure_count() -> int:
    """Get current consecutive failure count."""
    with _state_lock:
        return _consecutive_failures


# =============================================================================
# Python Client Initialization
# =============================================================================


def _check_python_client() -> bool:
    """Check if Python EmitClient is available (lazy initialization).

    Returns:
        True if EmitClient can be imported and instantiated.
    """
    global _python_client_available, _emit_client

    with _state_lock:
        if _python_client_available is not None:
            return _python_client_available

    # Try to import and instantiate EmitClient
    try:
        from omnibase_infra.runtime.emit_daemon.client import EmitClient

        # Create client with default settings
        socket_path = os.environ.get("OMNICLAUDE_EMIT_SOCKET", str(DEFAULT_SOCKET_PATH))
        client = EmitClient(socket_path=socket_path, timeout=5.0)

        with _state_lock:
            _emit_client = client
            _python_client_available = True

        logger.debug("Python EmitClient initialized successfully")
        return True

    except ImportError as e:
        logger.warning(f"EmitClient import failed (will use shell fallback): {e}")
        with _state_lock:
            _python_client_available = False
        return False

    except Exception as e:
        logger.warning(
            f"EmitClient initialization failed (will use shell fallback): {e}"
        )
        with _state_lock:
            _python_client_available = False
        return False


def _get_python_client() -> EmitClient | None:
    """Get the Python EmitClient instance if available.

    Returns:
        EmitClient instance or None if not available.
    """
    if not _check_python_client():
        return None

    with _state_lock:
        return _emit_client


# =============================================================================
# Shell Fallback Implementation
# =============================================================================


def _find_shell_tool() -> str | None:
    """Find available shell tool for Unix socket communication.

    Checks for socat first (preferred), then netcat variants.

    Returns:
        Path to the tool binary, or None if none available.
    """
    # Prefer socat for better Unix socket support
    for tool in ["socat", "nc", "netcat", "ncat"]:
        path = shutil.which(tool)
        if path:
            logger.debug(f"Found shell tool for fallback: {tool} at {path}")
            return path

    return None


def _emit_via_shell(
    event_type: str,
    payload: dict[str, object],
    timeout_ms: int,
    socket_path: Path,
) -> bool:
    """Emit event using shell tool (socat/netcat) as fallback.

    Protocol:
        Request: {"event_type": "...", "payload": {...}}\n
        Response: {"status": "queued", "event_id": "..."}\n

    Args:
        event_type: Semantic event type.
        payload: Event payload dictionary.
        timeout_ms: Timeout in milliseconds.
        socket_path: Path to daemon's Unix socket.

    Returns:
        True if event was queued successfully, False otherwise.
    """
    tool = _find_shell_tool()
    if not tool:
        logger.warning("No shell tool (socat/nc) available for fallback")
        return False

    # Build request JSON
    request = {"event_type": event_type, "payload": payload}
    request_json = json.dumps(request) + "\n"

    # Build command based on tool
    timeout_sec = max(1, timeout_ms // 1000)  # At least 1 second
    tool_name = os.path.basename(tool)

    if tool_name == "socat":
        # socat - best Unix socket support
        cmd = [
            tool,
            "-t",
            str(timeout_sec),
            "-",
            f"UNIX-CONNECT:{socket_path}",
        ]
    else:
        # netcat variants (nc, netcat, ncat)
        # -U for Unix socket, -w for timeout
        cmd = [
            tool,
            "-U",
            str(socket_path),
            "-w",
            str(timeout_sec),
        ]

    try:
        # Run with input/output
        result = subprocess.run(
            cmd,
            input=request_json,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 1,  # Extra second for overhead
            check=False,
        )

        if result.returncode != 0:
            logger.warning(
                f"Shell fallback failed (rc={result.returncode}): {result.stderr}"
            )
            return False

        # Parse response
        if not result.stdout.strip():
            logger.warning("Shell fallback: empty response from daemon")
            return False

        try:
            response = json.loads(result.stdout.strip())
        except json.JSONDecodeError as e:
            logger.warning(f"Shell fallback: invalid JSON response: {e}")
            return False

        # Check status
        status = response.get("status")
        if status == "queued":
            event_id = response.get("event_id", "unknown")
            logger.debug(f"Shell fallback: event queued with id={event_id}")
            return True
        elif status == "error":
            reason = response.get("reason", "unknown")
            logger.warning(f"Shell fallback: daemon error: {reason}")
            return False
        else:
            logger.warning(f"Shell fallback: unexpected status: {status}")
            return False

    except subprocess.TimeoutExpired:
        logger.warning(f"Shell fallback: timeout after {timeout_sec}s")
        return False
    except FileNotFoundError:
        logger.warning(f"Shell fallback: tool not found: {tool}")
        return False
    except OSError as e:
        logger.warning(f"Shell fallback: OS error: {e}")
        return False
    except Exception as e:
        logger.warning(f"Shell fallback: unexpected error: {e}")
        return False


# =============================================================================
# Public API
# =============================================================================


def emit_event(
    event_type: str,
    payload: dict[str, object],
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> bool:
    """Emit event to daemon. Returns True on success, False on failure.

    Uses Python EmitClient as primary path. Falls back to shell (socat/netcat)
    if Python client is unavailable or after consecutive failures exceed threshold.

    This function is designed to be non-blocking and will never raise exceptions.
    Failures are logged as warnings and tracked for fallback gating.

    Args:
        event_type: Semantic event type. Must be one of:
            - "session.started"
            - "session.ended"
            - "prompt.submitted"
            - "tool.executed"
        payload: Event payload dictionary. Required fields depend on event type
            (see daemon's EventRegistry for requirements).
        timeout_ms: Timeout in milliseconds for the emit operation.
            Defaults to 50ms to minimize hook latency impact.

    Returns:
        True if the event was successfully queued by the daemon.
        False if the emission failed (daemon unavailable, validation error, etc.).

    Example:
        >>> success = emit_event(
        ...     event_type="prompt.submitted",
        ...     payload={"prompt": "Hello", "session_id": "abc123"},
        ... )
        >>> print(f"Event emitted: {success}")
        Event emitted: True
    """
    # Validate event type
    if event_type not in SUPPORTED_EVENT_TYPES:
        logger.warning(
            f"Unsupported event type: {event_type}. "
            f"Supported: {sorted(SUPPORTED_EVENT_TYPES)}"
        )
        return False

    # Get socket path from environment or use default
    socket_path = Path(
        os.environ.get("OMNICLAUDE_EMIT_SOCKET", str(DEFAULT_SOCKET_PATH))
    )

    # Check if fallback is allowed (consecutive failures exceeded threshold)
    failures = _get_failure_count()
    use_fallback = failures >= FALLBACK_THRESHOLD

    # Try Python client first (unless fallback threshold exceeded)
    if not use_fallback:
        client = _get_python_client()
        if client is not None:
            try:
                # Use sync method for hooks (simpler, no event loop needed)
                event_id = client.emit_sync(event_type, payload)
                logger.debug(f"Event emitted via Python client: {event_id}")
                _reset_failures()  # Success - reset failure counter
                return True

            except Exception as e:
                logger.warning(f"Python client emit failed: {e}")
                count = _increment_failures()
                logger.debug(f"Consecutive failures: {count}/{FALLBACK_THRESHOLD}")

                # If we just hit the threshold, log it
                if count == FALLBACK_THRESHOLD:
                    logger.warning(
                        f"Fallback threshold reached ({FALLBACK_THRESHOLD} failures). "
                        "Switching to shell fallback."
                    )

    # Fall back to shell
    logger.debug("Using shell fallback for event emission")
    success = _emit_via_shell(event_type, payload, timeout_ms, socket_path)

    if success:
        # Shell fallback succeeded - consider resetting or decrementing failures
        # For now, keep the counter to encourage Python path recovery
        pass
    else:
        # Both paths failed
        _increment_failures()

    return success


def daemon_available() -> bool:
    """Check if daemon is running and accepting connections.

    Attempts to ping the daemon to verify it is operational.
    This is a relatively expensive operation (socket connection + round-trip)
    so should not be called on every emit.

    Returns:
        True if daemon responds to ping, False otherwise.

    Example:
        >>> if daemon_available():
        ...     print("Daemon is ready")
        ... else:
        ...     print("Daemon is not running")
    """
    client = _get_python_client()
    if client is None:
        # Python client not available - check socket file exists
        socket_path = Path(
            os.environ.get("OMNICLAUDE_EMIT_SOCKET", str(DEFAULT_SOCKET_PATH))
        )
        return socket_path.exists()

    try:
        return client.is_daemon_running_sync()
    except Exception as e:
        logger.debug(f"Daemon ping failed: {e}")
        return False


def get_fallback_status() -> dict[str, object]:
    """Return fallback status including consecutive failures and fallback state.

    Returns:
        Dictionary with:
            - consecutive_failures: Number of consecutive Python client failures
            - fallback_threshold: Threshold before fallback is activated
            - fallback_allowed: Whether fallback is currently allowed
            - python_client_available: Whether Python EmitClient is importable
            - socket_path: Path to daemon socket

    Example:
        >>> status = get_fallback_status()
        >>> print(f"Failures: {status['consecutive_failures']}")
        >>> print(f"Fallback allowed: {status['fallback_allowed']}")
    """
    failures = _get_failure_count()
    python_available = _check_python_client()
    socket_path = os.environ.get("OMNICLAUDE_EMIT_SOCKET", str(DEFAULT_SOCKET_PATH))

    return {
        "consecutive_failures": failures,
        "fallback_threshold": FALLBACK_THRESHOLD,
        "fallback_allowed": failures >= FALLBACK_THRESHOLD,
        "python_client_available": python_available,
        "socket_path": socket_path,
    }


def reset_fallback_state() -> None:
    """Reset fallback state (for testing or recovery).

    Resets the consecutive failure counter to zero, allowing the Python
    client path to be tried again.
    """
    _reset_failures()
    logger.debug("Fallback state reset")


# =============================================================================
# CLI Entry Point
# =============================================================================


def _cli_emit(args: argparse.Namespace) -> int:
    """CLI handler for emit command."""
    try:
        payload = json.loads(args.payload)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON payload: {e}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print("Error: Payload must be a JSON object", file=sys.stderr)
        return 1

    timeout_ms = args.timeout or DEFAULT_TIMEOUT_MS
    success = emit_event(args.event_type, payload, timeout_ms)

    if success:
        print("Event emitted successfully")
        return 0
    else:
        print("Failed to emit event", file=sys.stderr)
        return 1


def _cli_ping(_args: argparse.Namespace) -> int:
    """CLI handler for ping command."""
    if daemon_available():
        print("Daemon is available")
        return 0
    else:
        print("Daemon is not available", file=sys.stderr)
        return 1


def _cli_status(args: argparse.Namespace) -> int:
    """CLI handler for status command."""
    status = get_fallback_status()

    if args.json:
        print(json.dumps(status, indent=2))
    else:
        print(f"Consecutive failures: {status['consecutive_failures']}")
        print(f"Fallback threshold: {status['fallback_threshold']}")
        print(f"Fallback allowed: {status['fallback_allowed']}")
        print(f"Python client available: {status['python_client_available']}")
        print(f"Socket path: {status['socket_path']}")

    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for emit_client_wrapper.

    Args:
        argv: Command line arguments (defaults to sys.argv[1:])

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    parser = argparse.ArgumentParser(
        description="Emit client wrapper for hook event emission",
        prog="emit_client_wrapper",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # emit command
    emit_parser = subparsers.add_parser(
        "emit",
        help="Emit an event to the daemon",
    )
    emit_parser.add_argument(
        "--event-type",
        "-e",
        required=True,
        choices=sorted(SUPPORTED_EVENT_TYPES),
        help="Event type to emit",
    )
    emit_parser.add_argument(
        "--payload",
        "-p",
        required=True,
        help="Event payload as JSON string",
    )
    emit_parser.add_argument(
        "--timeout",
        "-t",
        type=int,
        default=DEFAULT_TIMEOUT_MS,
        help=f"Timeout in milliseconds (default: {DEFAULT_TIMEOUT_MS})",
    )
    emit_parser.set_defaults(func=_cli_emit)

    # ping command
    ping_parser = subparsers.add_parser(
        "ping",
        help="Check if daemon is available",
    )
    ping_parser.set_defaults(func=_cli_ping)

    # status command
    status_parser = subparsers.add_parser(
        "status",
        help="Get fallback status",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    status_parser.set_defaults(func=_cli_status)

    args = parser.parse_args(argv)

    # Configure logging
    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
    else:
        logging.basicConfig(
            level=logging.WARNING,
            format="%(levelname)s: %(message)s",
        )

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    # Public API
    "emit_event",
    "daemon_available",
    "get_fallback_status",
    "reset_fallback_state",
    # Constants
    "SUPPORTED_EVENT_TYPES",
    "DEFAULT_SOCKET_PATH",
    "DEFAULT_TIMEOUT_MS",
    "FALLBACK_THRESHOLD",
    # CLI
    "main",
]
