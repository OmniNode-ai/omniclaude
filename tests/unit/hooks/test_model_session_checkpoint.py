# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for ModelSessionCheckpoint and EnumCheckpointReason."""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from omniclaude.hooks.model_session_checkpoint import (
    EnumCheckpointReason,
    ModelSessionCheckpoint,
)


@pytest.mark.unit
class TestEnumCheckpointReason:
    """Tests for EnumCheckpointReason enum."""

    def test_all_variants_exist(self) -> None:
        assert set(EnumCheckpointReason) == {
            "context_limit",
            "session_limit",
            "weekly_limit",
            "explicit",
        }

    def test_values_are_strings(self) -> None:
        for reason in EnumCheckpointReason:
            assert isinstance(reason, str)
            assert isinstance(reason.value, str)


@pytest.mark.unit
class TestModelSessionCheckpoint:
    """Tests for ModelSessionCheckpoint model."""

    def _make_checkpoint(self, **overrides: object) -> ModelSessionCheckpoint:
        defaults: dict[str, object] = {
            "session_id": "test-session-123",
            "checkpoint_reason": EnumCheckpointReason.CONTEXT_LIMIT,
            "created_at": "2026-04-02T10:00:00Z",
            "reset_at": "2026-04-02T11:00:00Z",
            "resume_prompt": "Continue ticket-pipeline for OMN-7300",
            "active_epic": "OMN-7281",
            "active_tickets": ["OMN-7283", "OMN-7284"],
            "active_prs": ["omniclaude#1070"],
            "pipeline_state": "ticket-pipeline:implement",
            "context_percent": 87,
            "session_percent": 45,
            "weekly_percent": 20,
            "working_directory": "/tmp/test-worktree/omniclaude",  # noqa: S108
            "git_branch": "jonahgabriel/omn-7283-checkpoint-model",
            "worktree_path": "/tmp/test-worktree/omniclaude",  # noqa: S108
        }
        defaults.update(overrides)
        return ModelSessionCheckpoint(**defaults)  # type: ignore[arg-type]

    def test_valid_checkpoint(self) -> None:
        cp = self._make_checkpoint()
        assert cp.session_id == "test-session-123"
        assert cp.checkpoint_reason == EnumCheckpointReason.CONTEXT_LIMIT
        assert cp.context_percent == 87

    def test_yaml_roundtrip(self) -> None:
        cp = self._make_checkpoint()
        data = yaml.dump(cp.model_dump(mode="json"), default_flow_style=False)
        loaded = ModelSessionCheckpoint.model_validate(yaml.safe_load(data))
        assert loaded == cp

    def test_minimal_checkpoint(self) -> None:
        """Only required fields — all optional fields default to None/empty."""
        cp = ModelSessionCheckpoint(
            session_id="minimal",
            checkpoint_reason=EnumCheckpointReason.EXPLICIT,
            created_at="2026-04-02T10:00:00Z",
            resume_prompt="Resume work",
        )
        assert cp.active_epic is None
        assert cp.active_tickets == []
        assert cp.active_prs == []
        assert cp.context_percent is None

    def test_frozen(self) -> None:
        cp = self._make_checkpoint()
        with pytest.raises(ValidationError):
            cp.session_id = "changed"  # type: ignore[misc]

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            self._make_checkpoint(unknown_field="value")

    def test_context_percent_bounds(self) -> None:
        """Percentage must be 0-100."""
        self._make_checkpoint(context_percent=0)
        self._make_checkpoint(context_percent=100)
        with pytest.raises(ValidationError):
            self._make_checkpoint(context_percent=-1)
        with pytest.raises(ValidationError):
            self._make_checkpoint(context_percent=101)

    def test_schema_version_default(self) -> None:
        cp = self._make_checkpoint()
        assert cp.schema_version == "1.0.0"

    def test_all_reasons(self) -> None:
        """Each checkpoint reason creates a valid model."""
        for reason in EnumCheckpointReason:
            cp = self._make_checkpoint(checkpoint_reason=reason)
            assert cp.checkpoint_reason == reason
