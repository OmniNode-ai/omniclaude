"""Synchronous Unix socket client for the embedded event publisher.

Replaces omnibase_infra.runtime.emit_daemon.client.EmitClient which was
removed when the daemon was ported to omniclaude.publisher (OMN-1944).

Protocol: newline-delimited JSON over Unix domain socket.
    Emit:  {"event_type": "...", "payload": {...}}\\n
    Reply: {"status": "queued", "event_id": "..."}\\n

    Ping:  {"command": "ping"}\\n
    Reply: {"status": "ok", "queue_size": N, "spool_size": N}\\n
"""

from __future__ import annotations

import json
import logging
import socket

logger = logging.getLogger(__name__)

# 4 KiB is generous for a single JSON response line
_RECV_BUFSIZE = 4096


class EmitClient:
    """Synchronous client for the embedded event publisher daemon.

    Connection is lazy (opened on first call) and auto-reconnects on
    broken pipe. Thread-safety is the caller's responsibility — the
    emit_client_wrapper.py module handles this via _client_lock.

    Args:
        socket_path: Path to the daemon's Unix domain socket.
        timeout: Socket timeout in seconds for connect + send + recv.
    """

    def __init__(self, socket_path: str, timeout: float = 5.0) -> None:
        self._socket_path = socket_path
        self._timeout = timeout
        self._sock: socket.socket | None = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self) -> socket.socket:
        """Return an open socket, connecting lazily if needed."""
        if self._sock is not None:
            return self._sock
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self._timeout)
        sock.connect(self._socket_path)
        self._sock = sock
        return sock

    def _send_and_recv(self, request: dict[str, object]) -> dict[str, object]:
        """Send a request and read the response, reconnecting once on failure."""
        line = json.dumps(request).encode("utf-8") + b"\n"
        try:
            sock = self._connect()
            sock.sendall(line)
            return self._read_response(sock)
        except (BrokenPipeError, ConnectionResetError, OSError):
            # Socket went stale — close and retry once
            self.close()
            sock = self._connect()
            sock.sendall(line)
            return self._read_response(sock)

    @staticmethod
    def _read_response(sock: socket.socket) -> dict[str, object]:
        """Read until newline and parse JSON."""
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(_RECV_BUFSIZE)
            if not chunk:
                raise ConnectionResetError("daemon closed connection")
            buf += chunk
        resp_line = buf[: buf.index(b"\n")]
        return json.loads(resp_line)  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Public API (matches old omnibase_infra EmitClient interface)
    # ------------------------------------------------------------------

    def emit_sync(self, event_type: str, payload: dict[str, object]) -> str:
        """Emit an event to the daemon synchronously.

        Args:
            event_type: Semantic event type (e.g. "session.started").
            payload: Event payload dictionary.

        Returns:
            The event_id assigned by the daemon.

        Raises:
            ValueError: If the daemon returns an error response.
            ConnectionRefusedError: If the daemon is not running.
            OSError: On socket-level failures.
        """
        resp = self._send_and_recv({"event_type": event_type, "payload": payload})
        if resp.get("status") == "queued":
            return str(resp["event_id"])
        reason = resp.get("reason", "unknown error")
        raise ValueError(f"Daemon rejected event: {reason}")

    def is_daemon_running_sync(self) -> bool:
        """Ping the daemon. Returns True if it responds OK."""
        try:
            resp = self._send_and_recv({"command": "ping"})
            return resp.get("status") == "ok"
        except Exception:
            return False

    def close(self) -> None:
        """Close the socket connection."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


__all__ = ["EmitClient"]
