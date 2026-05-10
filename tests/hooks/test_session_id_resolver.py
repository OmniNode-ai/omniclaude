# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for resolve_session_id() canonical helper (OMN-XXXX)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _load():
    spec = importlib.util.spec_from_file_location(
        "session_id",
        Path(__file__).parent.parent.parent
        / "plugins"
        / "onex"
        / "hooks"
        / "lib"
        / "session_id.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_returns_claude_code_session_id_when_set(monkeypatch):
    mod = _load()
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc-123")
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("ONEX_SESSION_ID", raising=False)
    monkeypatch.delenv("SESSION_ID", raising=False)
    assert mod.resolve_session_id() == "abc-123"


def test_returns_default_when_canonical_unset(monkeypatch):
    mod = _load()
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("ONEX_SESSION_ID", raising=False)
    monkeypatch.delenv("SESSION_ID", raising=False)
    assert mod.resolve_session_id() == "unknown"
    assert mod.resolve_session_id(default="") == ""
    assert mod.resolve_session_id(default=None) is None


def test_legacy_fallback_chain_when_canonical_missing(monkeypatch):
    mod = _load()
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "legacy-claude-1")
    monkeypatch.setenv("SESSION_ID", "legacy-session-2")
    monkeypatch.setenv("ONEX_SESSION_ID", "legacy-onex-3")
    # Documented order: CLAUDE_CODE_SESSION_ID > CLAUDE_SESSION_ID > ONEX_SESSION_ID > SESSION_ID
    assert mod.resolve_session_id() == "legacy-claude-1"


def test_canonical_wins_over_all_legacy(monkeypatch):
    mod = _load()
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "winner")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "loser-1")
    monkeypatch.setenv("ONEX_SESSION_ID", "loser-2")
    monkeypatch.setenv("SESSION_ID", "loser-3")
    assert mod.resolve_session_id() == "winner"


def test_empty_string_canonical_falls_through(monkeypatch):
    mod = _load()
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "fallback")
    assert mod.resolve_session_id() == "fallback"
