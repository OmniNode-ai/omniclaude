# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""E2E proof-of-life: session-ID bridge flows through emit_event to daemon payload.

Creates a Unix-socket stub daemon in a background thread, monkeypatches
OMNICLAUDE_EMIT_SOCKET and CLAUDE_CODE_SESSION_ID, then verifies:

1. emit_event() delivers a payload with session_id == canonical value.
2. resolve_session_id() returns the canonical value even when legacy aliases
   are set to conflicting values.

Marked unit (not integration) — requires no live infra.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGINS_LIB = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"


def _load_module(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# Unix-socket stub daemon
# ---------------------------------------------------------------------------


class _StubDaemon:
    """Minimal Unix-domain-socket daemon that records received payloads."""

    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path
        self.received: list[dict[str, object]] = []
        self._sock: socket.socket | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.socket_path)
        self._sock.listen(5)
        self._sock.settimeout(0.5)
        t = threading.Thread(target=self._serve, daemon=True)
        t.start()

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                assert self._sock
                conn, _ = self._sock.accept()
            except (TimeoutError, OSError):
                continue
            self._handle(conn)

    def _handle(self, conn: socket.socket) -> None:
        try:
            data = b""
            while b"\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            line = data.split(b"\n", 1)[0].strip()
            if line:
                msg = json.loads(line.decode("utf-8"))
                if msg.get("command") == "ping":
                    conn.sendall(json.dumps({"status": "ok"}).encode() + b"\n")
                else:
                    payload = msg.get("payload", {})
                    self.received.append(payload)
                    conn.sendall(
                        json.dumps({"status": "queued", "event_id": "stub-1"}).encode()
                        + b"\n"
                    )
        except Exception:  # noqa: BLE001
            pass
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_emit_event_carries_canonical_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """emit_event payload must contain session_id == CLAUDE_CODE_SESSION_ID value."""
    # Use a short temp dir — AF_UNIX paths are limited to ~104 chars on macOS.
    tmp_dir = tempfile.mkdtemp(prefix="e2e_", dir="/tmp")
    socket_path = os.path.join(tmp_dir, "s.sock")
    daemon = _StubDaemon(socket_path)
    daemon.start()

    monkeypatch.setenv("OMNICLAUDE_EMIT_SOCKET", socket_path)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "e2e-canonical-uuid-XYZ")
    for legacy in ("CLAUDE_SESSION_ID", "ONEX_SESSION_ID", "SESSION_ID"):
        monkeypatch.setenv(legacy, "legacy-should-not-win")

    try:
        # Load session_id resolver fresh so it picks up patched env vars.
        sid_mod = _load_module("session_id_e2e_ecw", _PLUGINS_LIB / "session_id.py")
        resolve = sid_mod.resolve_session_id
        resolved = resolve()

        # Load emit_client_wrapper fresh so it picks up the patched socket path.
        mod_path = _PLUGINS_LIB / "emit_client_wrapper.py"
        mod_name = "emit_client_wrapper_e2e"
        spec = importlib.util.spec_from_file_location(mod_name, mod_path)
        assert spec and spec.loader
        ecw = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = ecw
        spec.loader.exec_module(ecw)  # type: ignore[union-attr]

        # Emit an event with the canonically resolved session_id in the payload.
        emit_event = ecw.emit_event
        emit_event("session.started", {"session_id": resolved, "agent_name": "test"})
        time.sleep(0.2)

        assert daemon.received, "Stub daemon received no events"
        session_ids = [str(p.get("session_id", "")) for p in daemon.received]
        assert any(sid == "e2e-canonical-uuid-XYZ" for sid in session_ids), (
            f"Expected canonical session_id in payloads, got: {session_ids}"
        )
    finally:
        daemon.stop()
        sys.modules.pop("emit_client_wrapper", None)
        sys.modules.pop(mod_name, None)
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_resolve_session_id_canonical_wins_over_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_session_id() returns CLAUDE_CODE_SESSION_ID even when legacy aliases set."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "canonical-wins")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "legacy-claude")
    monkeypatch.setenv("ONEX_SESSION_ID", "legacy-onex")
    monkeypatch.setenv("SESSION_ID", "legacy-session")

    mod = _load_module("session_id_e2e", _PLUGINS_LIB / "session_id.py")
    resolve = mod.resolve_session_id
    assert resolve() == "canonical-wins"


def test_resolve_session_id_falls_back_when_canonical_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_session_id() falls through to legacy aliases when canonical is unset."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "fallback-claude")
    monkeypatch.delenv("ONEX_SESSION_ID", raising=False)
    monkeypatch.delenv("SESSION_ID", raising=False)

    mod = _load_module("session_id_e2e2", _PLUGINS_LIB / "session_id.py")
    resolve = mod.resolve_session_id
    assert resolve() == "fallback-claude"
