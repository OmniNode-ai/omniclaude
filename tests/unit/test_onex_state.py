# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for the centralized ONEX state path resolver."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reload_module():
    """Force re-import so env changes take effect."""
    import omniclaude.hooks.lib.onex_state as mod

    yield
    importlib.reload(mod)


@pytest.mark.unit
def test_state_root_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "state"))
    from omniclaude.hooks.lib.onex_state import state_root

    result = state_root()
    assert result == (tmp_path / "state").resolve()


@pytest.mark.unit
def test_state_root_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONEX_STATE_DIR", raising=False)
    from omniclaude.hooks.lib.onex_state import state_root

    with pytest.raises(RuntimeError, match="ONEX_STATE_DIR"):
        state_root()


@pytest.mark.unit
def test_blank_state_root_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", "   ")
    from omniclaude.hooks.lib.onex_state import state_root

    with pytest.raises(RuntimeError, match="ONEX_STATE_DIR"):
        state_root()


@pytest.mark.unit
def test_tilde_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", "~/onex-state")
    from omniclaude.hooks.lib.onex_state import state_root

    result = state_root()
    assert "~" not in str(result)
    assert result == (Path.home() / "onex-state").resolve()


@pytest.mark.unit
def test_state_path_joins_parts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "state"))
    from omniclaude.hooks.lib.onex_state import state_path

    result = state_path("pipelines", "OMN-1234", "state.yaml")
    assert (
        result
        == (tmp_path / "state" / "pipelines" / "OMN-1234" / "state.yaml").resolve()
    )


@pytest.mark.unit
def test_ensure_state_dir_creates_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "state"))
    from omniclaude.hooks.lib.onex_state import ensure_state_dir

    result = ensure_state_dir("pipelines", "OMN-1234")
    assert result.is_dir()
    assert result == (tmp_path / "state" / "pipelines" / "OMN-1234").resolve()


@pytest.mark.unit
def test_ensure_state_path_creates_parent_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "state"))
    from omniclaude.hooks.lib.onex_state import ensure_state_path

    result = ensure_state_path("logs", "hooks.log")
    assert result.parent.is_dir()
    assert not result.exists()


@pytest.mark.unit
def test_log_path_shorthand(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "state"))
    from omniclaude.hooks.lib.onex_state import log_path

    result = log_path("hooks.log")
    assert result == (tmp_path / "state" / "logs" / "hooks.log").resolve()
    assert result.parent.is_dir()


@pytest.mark.unit
def test_state_path_does_not_create_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "nonexistent"))
    from omniclaude.hooks.lib.onex_state import state_path

    result = state_path("some", "deep", "path")
    assert not result.parent.exists()
