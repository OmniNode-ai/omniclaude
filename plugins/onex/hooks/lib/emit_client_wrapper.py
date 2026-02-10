#!/usr/bin/env python3
"""Emit Client Wrapper - Python Client for Hook Event Emission.

This module provides the client-side interface for all hooks to emit events via
the emit daemon using a built-in socket client (no external dependencies).

Design Decisions:
    - **Python-only**: Uses a stdlib-only _SocketEmitClient (socket + json, no external deps)
    - **Single emission**: Hook sends once, daemon handles fan-out to multiple topics
    - **Non-blocking**: Never raises exceptions that would break hooks

Event Types:
    - session.started: Claude Code session initialization
    - session.ended: Claude Code session termination
    - prompt.submitted: User prompt submission (daemon fans out to 2 topics)
    - tool.executed: Tool execution completion

Example Usage:
    ```python
    from emit_client_wrapper import emit_event, daemon_available

    # Check if daemon is available
    if daemon_available():
        print("Daemon is running")

    # Emit an event (returns True on success, False on failure)
    success = emit_event(
        event_type="prompt.submitted",
        payload={"prompt_preview": "Hello", "session_id": "abc123"},
        timeout_ms=50,
    )
    ```

CLI Usage:
    ```bash
    # Emit an event from shell script
    python -m emit_client_wrapper emit \
        --event-type "prompt.submitted" \
        --payload '{"session_id": "abc123", "prompt_preview": "Hello"}'

    # Check daemon availability
    python -m emit_client_wrapper ping

    # Get status
    python -m emit_client_wrapper status
    ```

Related Tickets:
    - OMN-1631: Emit daemon integration
    - OMN-1632: Hook migration to daemon

.. versionadded:: 0.2.0
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import concurrent.futures
import json
import logging
import os
import socket
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar, cast

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Default socket path (matches daemon default)
# NOTE: /tmp is standard for Unix domain sockets - not a security issue
DEFAULT_SOCKET_PATH = Path("/tmp/omniclaude-emit.sock")  # noqa: S108

# Default timeout for emit operations (milliseconds) - used by CLI interface
DEFAULT_TIMEOUT_MS = 50

# Default client timeout (seconds) - controls EmitClient socket timeout
# Can be overridden via OMNICLAUDE_EMIT_TIMEOUT environment variable
DEFAULT_CLIENT_TIMEOUT_SECONDS = 5.0

# Supported event types (must match daemon's EventRegistry)
SUPPORTED_EVENT_TYPES = frozenset(
    [
        "session.started",
        "session.ended",
        "session.outcome",
        "prompt.submitted",
        "tool.executed",
        "injection.recorded",
        "context.utilization",  # OMN-1889
        "agent.match",  # OMN-1889
        "latency.breakdown",  # OMN-1889
        "routing.decision",  # PR-92 - Routing decision emission via daemon
        "routing.feedback",  # OMN-1892 - Routing feedback for reinforcement
        "routing.skipped",  # OMN-1892 - Routing feedback skipped (guardrail gate)
        "notification.blocked",  # OMN-1831 - Slack notifications via emit daemon
        "notification.completed",  # OMN-1831 - Slack notifications via emit daemon
        "phase.metrics",  # OMN-2027 - Phase instrumentation metrics
    ]
)

# =============================================================================
# Async Context Detection and Thread Execution
# =============================================================================


def _is_in_async_context() -> bool:
    """Check if we're currently inside a running event loop.

    Returns:
        True if called from within a running async event loop, False otherwise.
    """
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


T = TypeVar("T")

# Module-level executor for _run_sync_in_thread to avoid per-call thread
# creation/teardown overhead. Cleaned up on interpreter exit via atexit.
_thread_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
atexit.register(_thread_executor.shutdown, wait=False)


def _run_sync_in_thread(func: Callable[[], T]) -> T:  # noqa: UP047 - Python 3.11 compat
    """Run a sync function in a separate thread.

    This is used when sync methods that internally call run_until_complete()
    are invoked from within an async context. Running in a thread avoids
    the "cannot use sync methods from async context" error.

    Args:
        func: Zero-argument callable to execute in the thread.

    Returns:
        The result of calling func().

    Raises:
        Exception: Any exception raised by func() is re-raised.
    """
    future = _thread_executor.submit(func)
    return future.result()


# =============================================================================
# Minimal Socket Client (no external dependencies)
# =============================================================================


class _SocketEmitClient:
    """Minimal emit daemon client using raw Unix domain sockets.

    Implements the newline-delimited JSON protocol expected by the emit daemon.
    Protocol:
        Request:  ``{"event_type": "...", "payload": {...}}\\n``
        Response: ``{"status": "queued", "event_id": "..."}\\n``
        Ping:     ``{"command": "ping"}\\n``
        Pong:     ``{"status": "ok", "queue_size": N, "spool_size": N}\\n``

    This replaces the former ``omnibase_infra.runtime.emit_daemon.client.EmitClient``
    which was removed in OMN-1945 and moved to omniclaude3.

    .. versionadded:: 0.2.1
    """

    __slots__ = ("_socket_path", "_timeout")

    _MAX_RESPONSE_BYTES = 1_048_576  # 1 MB safety cap on daemon responses

    def __init__(self, socket_path: str, timeout: float) -> None:
        self._socket_path = socket_path
        self._timeout = timeout

    def _request(self, data: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON request and return the parsed response."""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self._timeout)
        try:
            sock.connect(self._socket_path)
            sock.sendall(json.dumps(data).encode("utf-8") + b"\n")
            # Read response (daemon always sends newline-terminated JSON)
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                total += len(chunk)
                if total > self._MAX_RESPONSE_BYTES:
                    raise ConnectionError(
                        f"Daemon response exceeded {self._MAX_RESPONSE_BYTES} bytes"
                    )
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
            # Parse only the first newline-terminated line (ignore trailing data)
            raw = b"".join(chunks).split(b"\n", 1)[0].decode("utf-8").strip()
            if not raw:
                raise ConnectionError("Daemon closed connection without responding")
            return cast("dict[str, Any]", json.loads(raw))
        finally:
            sock.close()

    def emit_sync(self, event_type: str, payload: dict[str, Any]) -> str:
        """Emit event synchronously, returns event_id."""
        response = self._request({"event_type": event_type, "payload": payload})
        if response.get("status") == "queued":
            return str(response.get("event_id", ""))
        raise RuntimeError(response.get("reason", f"Unexpected response: {response}"))

    def is_daemon_running_sync(self) -> bool:
        """Return True if daemon responds to ping."""
        try:
            response = self._request({"command": "ping"})
            return response.get("status") == "ok"
        except Exception:
            return False


# =============================================================================
# Client Initialization (thread-safe, lazy)
# =============================================================================

_client_lock = threading.Lock()
_emit_client: _SocketEmitClient | None = None
_client_initialized = False


def _get_client() -> _SocketEmitClient | None:
    """Get or create the emit client instance (lazy, thread-safe).

    The client object is cached, but each request opens a fresh socket
    connection (connection-per-request pattern, not persistent).

    Returns:
        _SocketEmitClient instance or None if initialization fails.
    """
    global _emit_client, _client_initialized

    with _client_lock:
        if _client_initialized:
            return _emit_client

        try:
            socket_path = os.environ.get(
                "OMNICLAUDE_EMIT_SOCKET", str(DEFAULT_SOCKET_PATH)
            )
            timeout_seconds = float(
                os.environ.get(
                    "OMNICLAUDE_EMIT_TIMEOUT", str(DEFAULT_CLIENT_TIMEOUT_SECONDS)
                )
            )
            _emit_client = _SocketEmitClient(
                socket_path=socket_path, timeout=timeout_seconds
            )
            logger.debug(
                f"EmitClient initialized (socket={socket_path}, timeout={timeout_seconds}s)"
            )

        except Exception as e:
            logger.warning(f"EmitClient initialization failed: {e}")
            _emit_client = None

        _client_initialized = True
        return _emit_client


def reset_client() -> None:
    """Reset the cached EmitClient, forcing reconnection on next emit.

    Use this function when:
    - The daemon has been restarted and the cached connection may be stale
    - You want to force re-reading of environment variables (socket path, timeout)
    - Testing scenarios that require a fresh client state

    This function is thread-safe.

    Example:
        >>> from emit_client_wrapper import emit_event, reset_client
        >>>
        >>> # Daemon was restarted, force reconnection
        >>> reset_client()
        >>> success = emit_event("session.started", {"session_id": "abc123"})
    """
    global _emit_client, _client_initialized

    with _client_lock:
        _emit_client = None
        _client_initialized = False
        logger.debug("EmitClient reset, will reconnect on next emit")


# =============================================================================
# Public API
# =============================================================================


def emit_event(
    event_type: str,
    payload: dict[str, object],
    timeout_ms: int = DEFAULT_TIMEOUT_MS,  # noqa: ARG001  # Deprecated: unused, kept for API compat
) -> bool:
    """Emit event to daemon. Returns True on success, False on failure.

    This function is designed to be non-blocking and will never raise exceptions.
    Failures are logged at appropriate levels based on error type.

    Args:
        event_type: Semantic event type. Must be one of the values in
            SUPPORTED_EVENT_TYPES (e.g., "session.started", "notification.blocked").
            See SUPPORTED_EVENT_TYPES constant for the full list.
        payload: Event payload dictionary. Required fields depend on event type
            (see daemon's EventRegistry for requirements).
        timeout_ms: **Deprecated: This parameter is accepted but ignored.**
            The actual client timeout is controlled by the OMNICLAUDE_EMIT_TIMEOUT
            environment variable (default: 5.0 seconds). Per-call timeout is not
            supported by the underlying socket protocol - the timeout applies to
            the entire client connection, not individual emit calls. This parameter
            exists solely to maintain a consistent CLI interface for shell scripts
            that may pass ``--timeout``.

    Returns:
        True if the event was successfully queued by the daemon.
        False if the emission failed (daemon unavailable, validation error, etc.).

    Note:
        **Timeout Architecture**: The EmitClient uses a single socket connection
        with a timeout set at initialization (via OMNICLAUDE_EMIT_TIMEOUT env var,
        default 5.0s). The protocol does not support per-call timeouts because:

        1. Socket operations are atomic - timeout applies to the connection
        2. The daemon processes events asynchronously after acknowledgment
        3. Per-call timeout would require reconnection overhead

        To adjust timeout behavior, set OMNICLAUDE_EMIT_TIMEOUT before the first
        emit call (client is lazily initialized).

    Note:
        **Error Classification**: Errors are logged at different levels:

        - DEBUG: Connection errors (daemon not running) - expected during startup
        - ERROR: Serialization/type errors - indicates bugs in caller code
        - WARNING: Other unexpected errors - unknown issues

    Example:
        >>> success = emit_event(
        ...     event_type="prompt.submitted",
        ...     payload={"prompt_preview": "Hello", "session_id": "abc123"},
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

    client = _get_client()
    if client is None:
        logger.debug("EmitClient not available, event dropped")
        return False

    try:
        # Use sync method for hooks (simpler, no event loop needed)
        # If we're inside an async context, run in a thread to avoid
        # "cannot use sync methods from async context" error
        if _is_in_async_context():
            event_id = _run_sync_in_thread(
                lambda: client.emit_sync(event_type, payload)
            )
        else:
            event_id = client.emit_sync(event_type, payload)
        logger.debug(f"Event emitted: {event_id}")
        return True

    except (ConnectionRefusedError, FileNotFoundError, BrokenPipeError, OSError) as e:
        # Expected during startup or when daemon is not running
        logger.debug(f"Event emission failed (daemon unavailable): {e}")
        return False

    except (json.JSONDecodeError, TypeError, ValueError) as e:
        # Indicates bugs in caller code (bad payload structure)
        logger.error(f"Event emission failed (serialization error): {e}")
        return False

    except Exception as e:
        # Unknown errors - log at WARNING for investigation
        logger.warning(f"Event emission failed (unexpected): {e}")
        return False


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
    client = _get_client()
    if client is None:
        return False

    try:
        # If we're inside an async context, run in a thread to avoid
        # "cannot use sync methods from async context" error
        if _is_in_async_context():
            return _run_sync_in_thread(client.is_daemon_running_sync)
        else:
            return client.is_daemon_running_sync()
    except Exception as e:
        logger.debug(f"Daemon ping failed: {e}")
        return False


def get_status() -> dict[str, object]:
    """Return client status information.

    Returns:
        Dictionary with:
            - client_available: Whether EmitClient is initialized
            - socket_path: Path to daemon socket
            - daemon_running: Whether daemon is responding (may be slow)

    Example:
        >>> status = get_status()
        >>> print(f"Client available: {status['client_available']}")
    """
    socket_path = os.environ.get("OMNICLAUDE_EMIT_SOCKET", str(DEFAULT_SOCKET_PATH))
    client = _get_client()

    return {
        "client_available": client is not None,
        "socket_path": socket_path,
        "daemon_running": daemon_available() if client else False,
    }


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
    status = get_status()

    if args.json:
        print(json.dumps(status, indent=2))
    else:
        print(f"Client available: {status['client_available']}")
        print(f"Socket path: {status['socket_path']}")
        print(f"Daemon running: {status['daemon_running']}")

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
        help=(
            f"Timeout in milliseconds (default: {DEFAULT_TIMEOUT_MS}). "
            "Note: Currently ignored - client timeout is controlled by "
            "OMNICLAUDE_EMIT_TIMEOUT env var"
        ),
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
        help="Get client status",
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

    return cast("int", args.func(args))


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    # Public API
    "emit_event",
    "daemon_available",
    "get_status",
    "reset_client",
    # Constants
    "SUPPORTED_EVENT_TYPES",
    "DEFAULT_SOCKET_PATH",
    "DEFAULT_TIMEOUT_MS",
    # CLI
    "main",
]
