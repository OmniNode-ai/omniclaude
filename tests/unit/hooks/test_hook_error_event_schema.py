# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for ModelHookErrorEvent schema [OMN-7157]."""

from datetime import UTC, datetime

import pytest

from omniclaude.hooks.schemas import (
    EnumHookErrorCategory,
    EnumHookErrorTier,
    ModelHookErrorEvent,
)


class TestEnumHookErrorTier:
    def test_has_three_tiers(self) -> None:
        assert set(EnumHookErrorTier) == {
            EnumHookErrorTier.INTERPRETER,
            EnumHookErrorTier.DEGRADED,
            EnumHookErrorTier.INTENTIONAL_BLOCK,
        }


class TestEnumHookErrorCategory:
    def test_has_categories(self) -> None:
        assert EnumHookErrorCategory.IMPORT_ERROR in EnumHookErrorCategory
        assert EnumHookErrorCategory.TYPE_ERROR in EnumHookErrorCategory
        assert EnumHookErrorCategory.TIMEOUT in EnumHookErrorCategory
        assert EnumHookErrorCategory.AUTH_DENIED in EnumHookErrorCategory
        assert EnumHookErrorCategory.DOD_BLOCK in EnumHookErrorCategory
        assert EnumHookErrorCategory.BASH_BLOCK in EnumHookErrorCategory
        assert EnumHookErrorCategory.FUNCTIONAL_DEGRADATION in EnumHookErrorCategory


class TestModelHookErrorEvent:
    def test_creates_with_required_fields(self) -> None:
        event = ModelHookErrorEvent(
            hook_name="pre_tool_use_dod_completion_guard",
            error_tier=EnumHookErrorTier.INTENTIONAL_BLOCK,
            error_category=EnumHookErrorCategory.DOD_BLOCK,
            error_message="No DoD evidence receipt found",
            session_id="abc-123",
            emitted_at=datetime.now(UTC),
        )
        assert event.hook_name == "pre_tool_use_dod_completion_guard"
        assert event.error_tier == EnumHookErrorTier.INTENTIONAL_BLOCK

    def test_frozen(self) -> None:
        event = ModelHookErrorEvent(
            hook_name="test",
            error_tier=EnumHookErrorTier.INTERPRETER,
            error_category=EnumHookErrorCategory.IMPORT_ERROR,
            error_message="cannot import name 'UTC'",
            session_id="abc-123",
            emitted_at=datetime.now(UTC),
        )
        with pytest.raises(Exception):
            event.hook_name = "changed"  # type: ignore[misc]

    def test_fingerprint_deterministic(self) -> None:
        kwargs = {
            "hook_name": "test",
            "error_tier": EnumHookErrorTier.INTERPRETER,
            "error_category": EnumHookErrorCategory.IMPORT_ERROR,
            "error_message": "cannot import name 'UTC'",
            "session_id": "abc-123",
            "emitted_at": datetime.now(UTC),
        }
        e1 = ModelHookErrorEvent(**kwargs)
        e2 = ModelHookErrorEvent(**kwargs)
        assert e1.fingerprint == e2.fingerprint
        assert len(e1.fingerprint) == 16  # SHA256[:16]
