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
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
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
# Agentic loop import (after path setup)
# ---------------------------------------------------------------------------
try:
    from agentic_loop import (  # type: ignore[import-not-found]
        AgenticResult,
        AgenticStatus,
        run_agentic_task,
    )
except ImportError:  # pragma: no cover
    AgenticResult = None  # type: ignore[assignment,misc]
    AgenticStatus = None  # type: ignore[assignment,misc]
    run_agentic_task = None  # type: ignore[assignment]

try:
    from agentic_quality_gate import (  # type: ignore[import-not-found]
        check_agentic_quality,
    )
except ImportError:  # pragma: no cover
    check_agentic_quality = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Agentic job types (OMN-5725)
# ---------------------------------------------------------------------------

# GC thresholds for completed/all jobs
_AGENTIC_JOB_COMPLETED_TTL_S = 60
_AGENTIC_JOB_MAX_TTL_S = 300


class AgenticJobStatus(Enum):
    """Status of an agentic background job."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgenticJob:
    """Tracks an agentic loop running in a background thread."""

    job_id: str
    session_id: str
    prompt: str
    started_at: float = field(default_factory=time.monotonic)
    completed_at: float | None = None
    status: AgenticJobStatus = AgenticJobStatus.RUNNING
    result: AgenticResult | None = None  # type: ignore[type-arg]
    error: str | None = None


# Thread-safe job store
_agentic_jobs: dict[str, AgenticJob] = {}
_agentic_jobs_lock = threading.Lock()


def _gc_agentic_jobs() -> None:
    """Remove expired agentic jobs from the store.

    Completed jobs are removed after _AGENTIC_JOB_COMPLETED_TTL_S.
    All jobs are removed after _AGENTIC_JOB_MAX_TTL_S regardless of status.
    """
    now = time.monotonic()
    with _agentic_jobs_lock:
        expired = []
        for job_id, job in _agentic_jobs.items():
            age = now - job.started_at
            if age > _AGENTIC_JOB_MAX_TTL_S or (
                job.status != AgenticJobStatus.RUNNING
                and job.completed_at is not None
                and (now - job.completed_at) > _AGENTIC_JOB_COMPLETED_TTL_S
            ):
                expired.append(job_id)
        for job_id in expired:
            del _agentic_jobs[job_id]
        if expired:
            logger.debug("GC'd %d agentic jobs", len(expired))


def _start_agentic_job(
    session_id: str,
    prompt: str,
    system_prompt: str,
    endpoint_url: str,
    working_dir: str | None = None,
) -> str:
    """Start an agentic loop in a background thread and return the job ID.

    Args:
        session_id: Session identifier for the requesting client.
        prompt: The user's task prompt.
        system_prompt: System prompt for the agentic LLM.
        endpoint_url: Base URL of the LLM endpoint.
        working_dir: Optional working directory for tool operations.

    Returns:
        A unique job_id string.
    """
    job_id = str(uuid.uuid4())[:8]
    job = AgenticJob(job_id=job_id, session_id=session_id, prompt=prompt)

    with _agentic_jobs_lock:
        _agentic_jobs[job_id] = job

    max_iterations = int(os.environ.get("AGENTIC_MAX_ITERATIONS", "10"))
    timeout_s = float(os.environ.get("AGENTIC_TIMEOUT_S", "60"))

    def _run() -> None:
        try:
            if run_agentic_task is None:
                job.status = AgenticJobStatus.FAILED
                job.error = "agentic_loop module not available"
                job.completed_at = time.monotonic()
                return

            result = run_agentic_task(
                prompt=prompt,
                system_prompt=system_prompt,
                endpoint_url=endpoint_url,
                max_iterations=max_iterations,
                timeout_s=timeout_s,
                working_dir=working_dir,
            )
            job.result = result
            if result.status == AgenticStatus.SUCCESS:
                job.status = AgenticJobStatus.COMPLETED
            else:
                job.status = AgenticJobStatus.FAILED
                job.error = result.error or result.status.value
        except Exception as exc:
            logger.debug("Agentic job %s failed: %s", job_id, exc)
            job.status = AgenticJobStatus.FAILED
            job.error = str(exc)
        finally:
            job.completed_at = time.monotonic()

    thread = threading.Thread(target=_run, name=f"agentic-{job_id}", daemon=True)
    thread.start()
    logger.info("Started agentic job %s for session %s", job_id, session_id[:8])
    return job_id


def _poll_agentic_jobs(session_id: str) -> dict[str, Any]:
    """Poll for completed agentic jobs belonging to a session.

    Returns the first completed job found, or a status dict if none are ready.
    """
    _gc_agentic_jobs()

    with _agentic_jobs_lock:
        for job_id, job in list(_agentic_jobs.items()):
            if job.session_id != session_id:
                continue
            if job.status == AgenticJobStatus.COMPLETED and job.result is not None:
                content = job.result.content or ""
                iterations = job.result.iterations
                tool_calls_count = job.result.tool_calls_count
                tool_names = sorted(job.result.tool_names_used)

                # Quality gate check (OMN-5729)
                if check_agentic_quality is not None:
                    gate_result = check_agentic_quality(
                        content=content,
                        tool_calls_count=tool_calls_count,
                        iterations=iterations,
                    )
                    if not gate_result.passed:
                        logger.info(
                            "Agentic quality gate failed for job %s: %s",
                            job_id,
                            gate_result.reason,
                        )
                        del _agentic_jobs[job_id]
                        return {
                            "agentic_completed": False,
                            "job_id": job_id,
                            "error": f"quality_gate_failed: {gate_result.reason}",
                        }

                # Remove job after delivery
                del _agentic_jobs[job_id]
                return {
                    "agentic_completed": True,
                    "job_id": job_id,
                    "content": content,
                    "iterations": iterations,
                    "tool_calls_count": tool_calls_count,
                    "tool_names": tool_names,
                }
            if job.status == AgenticJobStatus.FAILED:
                error = job.error or "unknown"
                del _agentic_jobs[job_id]
                return {
                    "agentic_completed": False,
                    "job_id": job_id,
                    "error": error,
                }
            if job.status == AgenticJobStatus.RUNNING:
                elapsed = time.monotonic() - job.started_at
                return {
                    "agentic_completed": False,
                    "job_id": job_id,
                    "status": "running",
                    "elapsed_s": round(elapsed, 1),
                }

    return {"agentic_completed": False, "status": "no_jobs"}


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
            "agentic_eligible": getattr(score, "agentic_eligible", False) is True,
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

    Request format:
      Standard: ``{"prompt": "...", "correlation_id": "...", "session_id": "..."}``
      Poll:     ``{"action": "poll_agentic", "session_id": "..."}``

    Response: dict from ``orchestrate_delegation()``, agentic dispatch, or error dict.
    """
    try:
        req = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return json.dumps(
            {"delegated": False, "reason": f"invalid_json: {exc}"}
        ).encode()

    if not isinstance(req, dict):
        return json.dumps({"delegated": False, "reason": "invalid_request"}).encode()

    # --- Action: poll_agentic (OMN-5725) ---
    action = req.get("action")
    if action == "poll_agentic":
        session_id = req.get("session_id", "")
        result = _poll_agentic_jobs(session_id)
        return json.dumps(result).encode()

    # --- Standard delegation request ---
    if "prompt" not in req:
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

        # --- Agentic dispatch (OMN-5725) ---
        # If the orchestrator signals agentic eligibility, start a background
        # agentic loop and return immediately with a job_id.
        if result.get("agentic") and run_agentic_task is not None:
            agentic_prompt = result.get("agentic_prompt", prompt)
            system_prompt = result.get("agentic_system_prompt", "")
            endpoint_url = result.get("agentic_endpoint_url", "")
            if endpoint_url and system_prompt:
                job_id = _start_agentic_job(
                    session_id=session_id,
                    prompt=agentic_prompt,
                    system_prompt=system_prompt,
                    endpoint_url=endpoint_url,
                )
                return json.dumps(
                    {
                        "delegated": False,
                        "agentic_dispatched": True,
                        "job_id": job_id,
                        "reason": "agentic_loop_started",
                    }
                ).encode()

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


class DelegationServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Threaded Unix domain socket server for delegation requests.

    ThreadingMixIn enables concurrent request handling, which is required
    for the agentic loop (OMN-5725): poll_agentic requests must be served
    while an agentic loop is running in a background thread.
    """

    allow_reuse_address = True
    daemon_threads = True


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
