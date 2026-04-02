# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for memory fabric client."""

import sys
from pathlib import Path

import pytest

# hooks/lib modules live under plugins/onex/hooks/lib/ and use sys.path shimming
_HOOKS_LIB = str(
    Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"
)
if _HOOKS_LIB not in sys.path:
    sys.path.insert(0, _HOOKS_LIB)

from memory_fabric_client import (
    format_learnings_markdown,  # type: ignore[import-untyped]
)


@pytest.mark.unit
class TestFormatLearningsMarkdown:
    def test_formats_single_learning(self) -> None:
        learnings = [
            {
                "resolution_summary": "Fixed by adding --extend-exclude.",
                "task_type": "ci_fix",
                "age_days": 3,
                "similarity": 0.92,
                "match_type": "error_signature",
            },
        ]
        md = format_learnings_markdown(learnings)
        assert "## Recent Agent Learnings" in md
        assert "3 days ago" in md
        assert "ci_fix" in md
        assert "--extend-exclude" in md

    def test_empty_returns_empty(self) -> None:
        assert format_learnings_markdown([]) == ""

    def test_limits_to_max(self) -> None:
        learnings = [
            {
                "resolution_summary": f"Learning {i}.",
                "task_type": "feature",
                "age_days": i,
                "similarity": 0.8,
                "match_type": "task_context",
            }
            for i in range(10)
        ]
        md = format_learnings_markdown(learnings, max_display=3)
        assert md.count("- [") == 3
