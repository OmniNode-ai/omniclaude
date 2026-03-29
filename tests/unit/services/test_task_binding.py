# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for TaskBinding service — dual persistence of task_id binding."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from omniclaude.services.task_binding import TaskBinding


@pytest.mark.unit
class TestTaskBinding:
    """Verify bind/clear/detect_existing operations per Doctrine D1."""

    def test_bind_sets_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONEX_TASK_ID", raising=False)
        binding = TaskBinding(state_dir=tmp_path)
        binding.bind("OMN-1234")
        assert os.environ.get("ONEX_TASK_ID") == "OMN-1234"

    def test_bind_writes_state_file(self, tmp_path: Path) -> None:
        binding = TaskBinding(state_dir=tmp_path)
        binding.bind("OMN-1234")
        state_file = tmp_path / ".onex_state" / "active_session.yaml"
        assert state_file.exists()
        content = yaml.safe_load(state_file.read_text())
        assert content["task_id"] == "OMN-1234"

    def test_bind_state_file_contains_metadata(self, tmp_path: Path) -> None:
        binding = TaskBinding(state_dir=tmp_path)
        binding.bind("OMN-5678")
        state_file = tmp_path / ".onex_state" / "active_session.yaml"
        content = yaml.safe_load(state_file.read_text())
        assert content["task_id"] == "OMN-5678"
        assert "bound_at" in content

    def test_bind_overwrites_previous_binding(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONEX_TASK_ID", raising=False)
        binding = TaskBinding(state_dir=tmp_path)
        binding.bind("OMN-1111")
        binding.bind("OMN-2222")
        assert os.environ.get("ONEX_TASK_ID") == "OMN-2222"
        state_file = tmp_path / ".onex_state" / "active_session.yaml"
        content = yaml.safe_load(state_file.read_text())
        assert content["task_id"] == "OMN-2222"

    def test_clear_removes_binding(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONEX_TASK_ID", raising=False)
        binding = TaskBinding(state_dir=tmp_path)
        binding.bind("OMN-1234")
        binding.clear()
        assert os.environ.get("ONEX_TASK_ID") is None
        state_file = tmp_path / ".onex_state" / "active_session.yaml"
        assert not state_file.exists()

    def test_clear_is_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONEX_TASK_ID", raising=False)
        binding = TaskBinding(state_dir=tmp_path)
        binding.clear()  # should not raise even with no prior binding

    def test_detect_existing_returns_task_id(self, tmp_path: Path) -> None:
        binding = TaskBinding(state_dir=tmp_path)
        binding.bind("OMN-5678")
        # New instance reads from state file, not memory
        binding_2 = TaskBinding(state_dir=tmp_path)
        assert binding_2.detect_existing() == "OMN-5678"

    def test_detect_existing_returns_none_when_no_state(self, tmp_path: Path) -> None:
        binding = TaskBinding(state_dir=tmp_path)
        assert binding.detect_existing() is None

    def test_detect_existing_returns_none_after_clear(self, tmp_path: Path) -> None:
        binding = TaskBinding(state_dir=tmp_path)
        binding.bind("OMN-9999")
        binding.clear()
        assert binding.detect_existing() is None

    def test_state_dir_defaults_to_cwd(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ONEX_TASK_ID", raising=False)
        binding = TaskBinding()
        binding.bind("OMN-3333")
        state_file = tmp_path / ".onex_state" / "active_session.yaml"
        assert state_file.exists()

    def test_bind_validates_task_id_format(self, tmp_path: Path) -> None:
        binding = TaskBinding(state_dir=tmp_path)
        with pytest.raises(ValueError, match="task_id"):
            binding.bind("")
        with pytest.raises(ValueError, match="task_id"):
            binding.bind("   ")
