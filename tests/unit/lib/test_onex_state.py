# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the ONEX state directory path resolver."""

from __future__ import annotations

import os

import pytest

from plugins.onex.hooks.lib.onex_state import (
    ensure_state_dir,
    ensure_state_path,
    log_path,
    state_path,
    state_root,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ONEX_STATE_DIR before each test so tests are isolated."""
    monkeypatch.delenv("ONEX_STATE_DIR", raising=False)


class TestStateRoot:
    """Tests for state_root()."""

    def test_reads_from_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        assert state_root() == tmp_path

    def test_missing_env_raises(self) -> None:
        with pytest.raises(RuntimeError, match="ONEX_STATE_DIR is not set"):
            state_root()

    def test_blank_env_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ONEX_STATE_DIR", "   ")
        with pytest.raises(RuntimeError, match="ONEX_STATE_DIR is not set"):
            state_root()

    def test_tilde_expansion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ONEX_STATE_DIR", "~/onex-state")
        result = state_root()
        assert "~" not in str(result)
        assert str(result).endswith("onex-state")


class TestStatePath:
    """Tests for state_path()."""

    def test_subdir_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        p = state_path("logs", "session.log")
        assert str(p) == os.path.join(str(tmp_path), "logs", "session.log")

    def test_does_not_create(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        p = state_path("does", "not", "exist")
        assert not p.parent.exists()


class TestEnsureStateDir:
    """Tests for ensure_state_dir()."""

    def test_creates_directory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        p = ensure_state_dir("pipelines", "run-1")
        assert p.is_dir()


class TestEnsureStatePath:
    """Tests for ensure_state_path()."""

    def test_creates_parent_only(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        p = ensure_state_path("logs", "hook.log")
        # Parent (logs/) must exist, but the file itself must not
        assert p.parent.is_dir()
        assert not p.exists()


class TestLogPath:
    """Tests for log_path()."""

    def test_returns_path_under_logs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        p = log_path("my.log")
        assert str(p) == os.path.join(str(tmp_path), "logs", "my.log")
        assert p.parent.is_dir()
