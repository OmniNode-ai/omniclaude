# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for session_id auto-injection via CLAUDE_CODE_SESSION_ID in emit_client_wrapper (OMN-10753)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _make_emit_client_wrapper():
    """Import emit_client_wrapper from the plugin hooks lib."""
    import importlib
    import sys

    # Ensure we get a fresh module without cached client state
    mod_name = "emit_client_wrapper"
    if mod_name in sys.modules:
        del sys.modules[mod_name]

    import importlib.util
    from pathlib import Path

    lib_path = (
        Path(__file__).parent.parent.parent
        / "plugins"
        / "onex"
        / "hooks"
        / "lib"
        / "emit_client_wrapper.py"
    )
    spec = importlib.util.spec_from_file_location(mod_name, lib_path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


@pytest.fixture
def wrapper_mod():
    return _make_emit_client_wrapper()


def test_emit_event_injects_session_id_from_env(wrapper_mod) -> None:
    """emit_event injects session_id from CLAUDE_CODE_SESSION_ID when payload has none."""
    session_id = "55f47499-eec1-4906-9fe7-c1ca86e4e459"
    captured_payload: dict = {}

    mock_client = MagicMock()

    def capture_emit(event_type, payload):
        captured_payload.update(payload)
        return "event-id-123"

    mock_client.emit_sync = capture_emit

    with (
        patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": session_id}),
        patch.object(wrapper_mod, "_get_client", return_value=mock_client),
    ):
        # Use a known supported event type
        result = wrapper_mod.emit_event("session.started", {})

    assert result is True
    assert captured_payload.get("session_id") == session_id


def test_emit_event_preserves_existing_session_id(wrapper_mod) -> None:
    """emit_event does NOT overwrite session_id already in payload."""
    session_id_env = "env-session-uuid"
    session_id_payload = "payload-session-uuid"
    captured_payload: dict = {}

    mock_client = MagicMock()

    def capture_emit(event_type, payload):
        captured_payload.update(payload)
        return "event-id-456"

    mock_client.emit_sync = capture_emit

    with (
        patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": session_id_env}),
        patch.object(wrapper_mod, "_get_client", return_value=mock_client),
    ):
        result = wrapper_mod.emit_event(
            "session.started", {"session_id": session_id_payload}
        )

    assert result is True
    assert captured_payload.get("session_id") == session_id_payload


def test_emit_event_no_session_id_when_env_unset(wrapper_mod) -> None:
    """emit_event does not inject session_id when CLAUDE_CODE_SESSION_ID is unset."""
    captured_payload: dict = {}

    mock_client = MagicMock()

    def capture_emit(event_type, payload):
        captured_payload.update(payload)
        return "event-id-789"

    mock_client.emit_sync = capture_emit

    env_without_session = {
        k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"
    }
    with (
        patch.dict("os.environ", env_without_session, clear=True),
        patch.object(wrapper_mod, "_get_client", return_value=mock_client),
    ):
        result = wrapper_mod.emit_event("session.started", {})

    assert result is True
    assert "session_id" not in captured_payload
