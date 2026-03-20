#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Delegation Daemon — Unix socket server with Valkey classification cache.

Provides a persistent daemon process that handles delegation requests over a
Unix domain socket, caching classification results in Valkey to avoid repeated
cold-start costs from TaskClassifier + pydantic imports.

Protocol:
    - Request: newline-delimited JSON on the socket
      ``{"prompt": "...", "correlation_id": "...", "session_id": "..."}``
    - Response: JSON dict from ``orchestrate_delegation()``

Architecture mirrors ``_SocketEmitClient`` from ``emit_client_wrapper.py``:
    - socketserver.UnixStreamServer + StreamRequestHandler
    - PID file for lifecycle management
    - Graceful degradation when Valkey is unavailable

Socket: ``/tmp/omniclaude-delegation.sock`` (env override: OMNICLAUDE_DELEGATION_SOCKET)
PID:    ``/tmp/omniclaude-delegation.pid``

Related Tickets:
    - OMN-5537: Implement delegation daemon
    - OMN-5510: Wire delegation orchestrator

.. versionadded:: 0.9.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import signal
import socket
import socketserver
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# sys.path setup (module-level, idempotent) — mirrors delegation_orchestrator.py
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).parent
_SRC_PATH = _SCRIPT_DIR.parent.parent.parent.parent / "src"
if _SRC_PATH.exists() and str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

_LIB_DIR = str(_SCRIPT_DIR)
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_SOCKET_PATH = "/tmp/omniclaude-delegation.sock"  # noqa: S108
DEFAULT_PID_PATH = "/tmp/omniclaude-delegation.pid"  # noqa: S108
CACHE_TTL_SECONDS = 300
CACHE_SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Module-level imports (after path setup)
# ---------------------------------------------------------------------------
try:
    from omniclaude.lib.task_classifier import TaskClassifier
except ImportError:  # pragma: no cover
    TaskClassifier = None  # type: ignore[assignment,misc]

try:
    from delegation_orchestrator import (  # type: ignore[import-not-found]
        orchestrate_delegation,
    )
except ImportError:  # pragma: no cover
    orchestrate_delegation = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Valkey client (lazy singleton)
# ---------------------------------------------------------------------------
_valkey_client: Any = None
_valkey_init_attempted = False


def _get_valkey() -> Any:
    """Return a Valkey client instance, or None if unavailable.

    Lazy singleton: connects once, returns cached client on subsequent calls.
    Broad exception catch ensures hook never breaks on Valkey issues.
    """
    global _valkey_client, _valkey_init_attempted
    if _valkey_init_attempted:
        return _valkey_client
    _valkey_init_attempted = True
    try:
        import valkey  # type: ignore[import-untyped]

        _valkey_client = valkey.Valkey(
            host=os.environ.get("VALKEY_HOST", "localhost"),
            port=int(os.environ.get("VALKEY_PORT", "16379")),
            socket_timeout=0.5,
            socket_connect_timeout=0.5,
        )
        # Probe connection
        _valkey_client.ping()
        logger.debug(
            "Valkey connected at %s:%s",
            _valkey_client.connection_pool.connection_kwargs.get("host"),
            _valkey_client.connection_pool.connection_kwargs.get("port"),
        )
    except Exception as exc:
        logger.debug("Valkey unavailable (non-fatal): %s", exc)
        _valkey_client = None
    return _valkey_client


def _reset_valkey() -> None:
    """Reset the Valkey singleton (for testing)."""
    global _valkey_client, _valkey_init_attempted
    _valkey_client = None
    _valkey_init_attempted = False


# ---------------------------------------------------------------------------
# Classification with caching
# ---------------------------------------------------------------------------


def _classify_with_cache(prompt: str, correlation_id: str) -> dict[str, Any] | None:
    """Classify a prompt, using Valkey cache when available.

    Cache key: ``delegation:classify:<sha256(prompt[:500])>``
    Cache value: JSON with ``schema_version``, ``intent``, ``confidence``,
    ``delegatable``, ``cached_at``.

    Returns:
        Classification dict with at least ``intent``, ``confidence``,
        ``delegatable`` keys, or None if classification fails entirely.
    """
    cache_key = (
        f"delegation:classify:{hashlib.sha256(prompt[:500].encode()).hexdigest()}"
    )

    # Try cache first
    vk = _get_valkey()
    if vk is not None:
        try:
            cached_raw = vk.get(cache_key)
            if cached_raw is not None:
                cached = json.loads(cached_raw)
                if cached.get("schema_version") == CACHE_SCHEMA_VERSION:
                    logger.debug(
                        "Cache hit for %s (correlation=%s)",
                        cache_key[:40],
                        correlation_id,
                    )
                    return cached
                logger.debug(
                    "Cache schema mismatch (got %s, want %s) — treating as miss",
                    cached.get("schema_version"),
                    CACHE_SCHEMA_VERSION,
                )
        except Exception as exc:
            logger.debug("Valkey get failed (non-fatal): %s", exc)

    # Cache miss or Valkey unavailable — classify directly
    if TaskClassifier is None:
        logger.debug("TaskClassifier unavailable")
        return None

    try:
        classifier = TaskClassifier()
        score = classifier.is_delegatable(prompt)
        result: dict[str, Any] = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "intent": score.intent.value
            if hasattr(score.intent, "value")
            else str(score.intent),
            "confidence": score.confidence,
            "delegatable": score.delegatable,
            "cached_at": datetime.now(UTC).isoformat(),
        }

        # Store in cache
        if vk is not None:
            try:
                vk.set(cache_key, json.dumps(result), ex=CACHE_TTL_SECONDS)
            except Exception as exc:
                logger.debug("Valkey set failed (non-fatal): %s", exc)

        return result
    except Exception as exc:
        logger.debug("Classification failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Request handling
# ---------------------------------------------------------------------------


def _handle_request(data: bytes) -> bytes:
    """Parse a JSON request and return a JSON response.

    Request format: ``{"prompt": "...", "correlation_id": "...", "session_id": "..."}``
    Response: dict from ``orchestrate_delegation()`` or error dict.
    """
    try:
        req = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return json.dumps(
            {"delegated": False, "reason": f"invalid_json: {exc}"}
        ).encode()

    if not isinstance(req, dict) or "prompt" not in req:
        return json.dumps(
            {"delegated": False, "reason": "missing_field: prompt"}
        ).encode()

    prompt = req["prompt"]
    correlation_id = req.get("correlation_id", "")
    session_id = req.get("session_id", "")

    if orchestrate_delegation is None:
        return json.dumps(
            {"delegated": False, "reason": "orchestrator_unavailable"}
        ).encode()

    # Get cached classification
    cached_classification = _classify_with_cache(prompt, correlation_id)

    try:
        result = orchestrate_delegation(
            prompt=prompt,
            session_id=session_id,
            correlation_id=correlation_id,
            cached_classification=cached_classification,
        )
        return json.dumps(result).encode()
    except Exception as exc:
        logger.debug("orchestrate_delegation failed: %s", exc)
        return json.dumps(
            {"delegated": False, "reason": f"orchestration_error: {type(exc).__name__}"}
        ).encode()


# ---------------------------------------------------------------------------
# Socket server
# ---------------------------------------------------------------------------


class DelegationHandler(socketserver.StreamRequestHandler):
    """Handle a single delegation request on the Unix socket."""

    def handle(self) -> None:
        try:
            line = self.rfile.readline()
            if not line:
                return
            response = _handle_request(line.strip())
            self.wfile.write(response + b"\n")
            self.wfile.flush()
        except Exception as exc:
            logger.debug("Handler error: %s", exc)


class DelegationServer(socketserver.UnixStreamServer):
    """Unix domain socket server for delegation requests."""

    allow_reuse_address = True


# ---------------------------------------------------------------------------
# Daemon lifecycle
# ---------------------------------------------------------------------------


def _get_socket_path() -> str:
    return os.environ.get("OMNICLAUDE_DELEGATION_SOCKET", DEFAULT_SOCKET_PATH)


def _get_pid_path() -> str:
    return os.environ.get("OMNICLAUDE_DELEGATION_PID", DEFAULT_PID_PATH)


def _cleanup_stale(socket_path: str, pid_path: str) -> None:
    """Remove stale PID file and socket if the process is dead."""
    if os.path.exists(pid_path):
        try:
            with open(pid_path) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)  # check if alive
            # Process is alive — don't clean up
            return
        except (OSError, ValueError):
            # Process dead or PID file corrupt — clean up
            pass
        try:
            Path(pid_path).unlink(missing_ok=True)
        except OSError:
            pass

    if os.path.exists(socket_path):
        try:
            Path(socket_path).unlink(missing_ok=True)
        except OSError:
            pass


def start_daemon() -> None:
    """Start the delegation daemon.

    Cleans up stale PID/socket, binds the Unix socket, writes PID file,
    and enters the serve_forever loop. Sets socket permissions to 0600.
    """
    socket_path = _get_socket_path()
    pid_path = _get_pid_path()

    _cleanup_stale(socket_path, pid_path)

    if os.path.exists(socket_path):
        logger.error("Socket %s still exists (daemon may be running)", socket_path)
        sys.exit(1)

    server = DelegationServer(socket_path, DelegationHandler)

    # Restrict socket permissions
    Path(socket_path).chmod(0o600)

    # Write PID file
    with open(pid_path, "w") as f:
        f.write(str(os.getpid()))

    # Handle SIGTERM gracefully
    def _shutdown(signum: int, frame: Any) -> None:
        logger.info("Received signal %s, shutting down", signum)
        server.shutdown()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info(
        "Delegation daemon started (pid=%d, socket=%s)", os.getpid(), socket_path
    )

    try:
        server.serve_forever()
    finally:
        try:
            Path(socket_path).unlink(missing_ok=True)
        except OSError:
            pass
        try:
            Path(pid_path).unlink(missing_ok=True)
        except OSError:
            pass
        logger.info("Delegation daemon stopped")


def stop_daemon() -> bool:
    """Stop the delegation daemon by sending SIGTERM to the PID in the PID file.

    Returns True if the daemon was stopped, False if not running.
    """
    pid_path = _get_pid_path()
    socket_path = _get_socket_path()

    if not os.path.exists(pid_path):
        return False

    try:
        with open(pid_path) as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
        # Wait briefly for cleanup
        for _ in range(10):
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except OSError:
                break
        return True
    except (OSError, ValueError):
        pass
    finally:
        # Clean up files regardless
        for path in (pid_path, socket_path):
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
    return False


def health_check() -> bool:
    """Probe the daemon with a round-trip request.

    Returns True if the daemon responds, False otherwise.
    """
    socket_path = _get_socket_path()
    if not os.path.exists(socket_path):
        return False

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(socket_path)
        # Send a minimal probe (missing prompt → will get error response, but that's fine)
        probe = json.dumps({"prompt": "__health__", "correlation_id": "health"})
        sock.sendall(probe.encode() + b"\n")
        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
            if b"\n" in response:
                break
        sock.close()
        return len(response) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point: --start, --stop, --health."""
    parser = argparse.ArgumentParser(description="Delegation daemon")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--start", action="store_true", help="Start the daemon")
    group.add_argument("--stop", action="store_true", help="Stop the daemon")
    group.add_argument("--health", action="store_true", help="Check daemon health")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("DEBUG") else logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )

    if args.start:
        start_daemon()
    elif args.stop:
        if stop_daemon():
            print("Daemon stopped")
        else:
            print("Daemon not running")
    elif args.health:
        if health_check():
            print("Daemon healthy")
            sys.exit(0)
        else:
            print("Daemon not responding")
            sys.exit(1)


if __name__ == "__main__":
    main()
