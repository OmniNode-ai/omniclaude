# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for dispatch outcome evaluation TopicBase registration."""

from __future__ import annotations

import pytest

from omniclaude.hooks.topics import TopicBase, build_topic

pytestmark = pytest.mark.unit


def _dispatch_outcome_evaluated_topic() -> str:
    return ".".join(
        (
            "onex",
            "evt",
            "omniintelligence",
            "dispatch-outcome-evaluated",
            "v1",
        )
    )


def test_dispatch_outcome_evaluated_topicbase_value() -> None:
    assert TopicBase.DISPATCH_OUTCOME_EVALUATED.value == (
        _dispatch_outcome_evaluated_topic()
    )


def test_build_topic_dispatch_outcome_evaluated_returns_canonical_topic() -> None:
    assert build_topic(TopicBase.DISPATCH_OUTCOME_EVALUATED) == (
        _dispatch_outcome_evaluated_topic()
    )
