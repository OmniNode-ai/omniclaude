# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for SessionCheckpointWriter — atomic YAML persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from omniclaude.hooks.model_session_checkpoint import (
    EnumCheckpointReason,
    ModelSessionCheckpoint,
)
from omniclaude.hooks.session_checkpoint_writer import SessionCheckpointWriter


def _make_checkpoint(**overrides: object) -> ModelSessionCheckpoint:
    defaults: dict[str, object] = {
        "session_id": "test-session",
        "checkpoint_reason": EnumCheckpointReason.CONTEXT_LIMIT,
        "created_at": "2026-04-02T10:00:00Z",
        "reset_at": "2026-04-02T11:00:00Z",
        "resume_prompt": "Continue work on OMN-7283",
        "context_percent": 92,
    }
    defaults.update(overrides)
    return ModelSessionCheckpoint(**defaults)  # type: ignore[arg-type]


@pytest.mark.unit
class TestSessionCheckpointWriter:
    """Tests for checkpoint write/read/clear lifecycle."""

    def test_write_creates_file(self, tmp_path: Path) -> None:
        writer = SessionCheckpointWriter(state_dir=tmp_path)
        cp = _make_checkpoint()
        path = writer.write(cp)
        assert path.exists()
        assert path.name == "checkpoint.yaml"
        assert "orchestrator" in str(path)

    def test_write_read_roundtrip(self, tmp_path: Path) -> None:
        writer = SessionCheckpointWriter(state_dir=tmp_path)
        cp = _make_checkpoint()
        writer.write(cp)
        loaded = writer.read()
        assert loaded == cp

    def test_read_returns_none_when_missing(self, tmp_path: Path) -> None:
        writer = SessionCheckpointWriter(state_dir=tmp_path)
        assert writer.read() is None

    def test_clear_removes_file(self, tmp_path: Path) -> None:
        writer = SessionCheckpointWriter(state_dir=tmp_path)
        writer.write(_make_checkpoint())
        assert writer.checkpoint_path.exists()
        writer.clear()
        assert not writer.checkpoint_path.exists()
        assert writer.read() is None

    def test_clear_idempotent(self, tmp_path: Path) -> None:
        """Clear on non-existent file does not raise."""
        writer = SessionCheckpointWriter(state_dir=tmp_path)
        writer.clear()  # should not raise

    def test_atomic_write_no_tmp_remains(self, tmp_path: Path) -> None:
        writer = SessionCheckpointWriter(state_dir=tmp_path)
        writer.write(_make_checkpoint())
        tmp_file = writer.checkpoint_path.with_suffix(".yaml.tmp")
        assert not tmp_file.exists()

    def test_overwrite_existing(self, tmp_path: Path) -> None:
        writer = SessionCheckpointWriter(state_dir=tmp_path)
        cp1 = _make_checkpoint(session_id="first")
        cp2 = _make_checkpoint(session_id="second")
        writer.write(cp1)
        writer.write(cp2)
        loaded = writer.read()
        assert loaded is not None
        assert loaded.session_id == "second"

    def test_read_corrupt_file(self, tmp_path: Path) -> None:
        writer = SessionCheckpointWriter(state_dir=tmp_path)
        writer.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        writer.checkpoint_path.write_text("not: valid: yaml: [[[")
        assert writer.read() is None

    def test_checkpoint_path_structure(self, tmp_path: Path) -> None:
        writer = SessionCheckpointWriter(state_dir=tmp_path)
        expected = tmp_path / "orchestrator" / "checkpoint.yaml"
        assert writer.checkpoint_path == expected
