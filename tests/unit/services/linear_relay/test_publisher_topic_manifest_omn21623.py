# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The Linear relay reads its publish topic from topics.yaml (OMN-21623)."""

from __future__ import annotations

from pathlib import Path

import pytest

from omniclaude.services.linear_relay import publisher


@pytest.mark.unit
def test_feature_dashboard_topic_comes_from_the_manifest() -> None:
    assert (
        publisher._TOPICS.get("publish_topics", "feature_dashboard_command")
        == "onex.cmd.omniclaude.feature-dashboard.v1"
    )


@pytest.mark.unit
def test_publisher_source_holds_no_topic_literal() -> None:
    source = Path(publisher.__file__).read_text(encoding="utf-8")
    assert '"onex.' not in source
    assert "'onex." not in source
