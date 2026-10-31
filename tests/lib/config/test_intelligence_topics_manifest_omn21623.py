# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""IntelligenceConfig reads its code-analysis topics from topics.yaml (OMN-21623)."""

from __future__ import annotations

from pathlib import Path

import pytest

from omniclaude.lib.config import intelligence_config


@pytest.mark.unit
def test_topics_come_from_the_manifest() -> None:
    assert (
        intelligence_config.TOPIC_CODE_ANALYSIS_REQUESTED
        == "onex.cmd.omniintelligence.code-analysis.v1"
    )
    assert (
        intelligence_config.TOPIC_CODE_ANALYSIS_COMPLETED
        == "onex.evt.omniintelligence.code-analysis-completed.v1"
    )
    assert (
        intelligence_config.TOPIC_CODE_ANALYSIS_FAILED
        == "onex.evt.omniintelligence.code-analysis-failed.v1"
    )


@pytest.mark.unit
def test_module_source_holds_no_topic_literal() -> None:
    source = Path(intelligence_config.__file__).read_text(encoding="utf-8")
    assert '"onex.' not in source
    assert "'onex." not in source
