# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for ModelSkillRequest.

Covers:
- skill_path must end in SKILL.md (ValidationError otherwise)
- skill_path cannot be empty (ValidationError)
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from omniclaude.nodes.shared.models.model_skill_request import ModelSkillRequest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_request(**overrides: object) -> ModelSkillRequest:
    defaults: dict[str, object] = {
        "skill_name": "pr-review",
        "skill_path": "/some/path/to/SKILL.md",
        "args": {},
        "correlation_id": uuid4(),
    }
    defaults.update(overrides)
    return ModelSkillRequest(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelSkillRequestValidation:
    """Validation rules for ModelSkillRequest.skill_path."""

    def test_skill_path_must_end_in_skill_md(self) -> None:
        """Paths that do not end in SKILL.md are rejected."""
        with pytest.raises(ValidationError, match=r"SKILL\.md"):
            _valid_request(skill_path="/some/path/README.md")

    def test_skill_path_cannot_be_empty(self) -> None:
        """Empty skill_path is rejected."""
        with pytest.raises(ValidationError):
            _valid_request(skill_path="")

    def test_skill_path_valid_absolute(self) -> None:
        """An absolute path ending in SKILL.md is accepted."""
        req = _valid_request(skill_path="/plugins/onex/skills/pr-review/SKILL.md")
        assert req.skill_path == "/plugins/onex/skills/pr-review/SKILL.md"

    def test_skill_path_valid_relative(self) -> None:
        """A relative path ending in SKILL.md is accepted."""
        req = _valid_request(skill_path="skills/some-skill/SKILL.md")
        assert req.skill_path == "skills/some-skill/SKILL.md"

    def test_model_is_frozen(self) -> None:
        """ModelSkillRequest instances are immutable."""
        req = _valid_request()
        with pytest.raises(ValidationError):
            req.skill_name = "changed"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        """Unknown fields raise ValidationError (extra='forbid')."""
        with pytest.raises(ValidationError):
            ModelSkillRequest(
                skill_name="pr-review",
                skill_path="/path/SKILL.md",
                args={},
                correlation_id=uuid4(),
                unknown_field="oops",  # type: ignore[call-arg]
            )

    def test_skill_name_whitespace_only_is_rejected(self) -> None:
        """A whitespace-only skill_name is rejected."""
        with pytest.raises(ValidationError):
            _valid_request(skill_name="   ")

    def test_args_empty_key_is_rejected(self) -> None:
        """An empty string key in args is rejected."""
        with pytest.raises(ValidationError):
            _valid_request(args={"": "val"})

    def test_args_whitespace_key_is_rejected(self) -> None:
        """A whitespace-only key in args is rejected."""
        with pytest.raises(ValidationError):
            _valid_request(args={" ": "val"})
