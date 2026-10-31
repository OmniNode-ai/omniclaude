# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""scripts/demo_runner.py resolves its topics through topic_registry.yaml (OMN-21623)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

_RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "demo_runner.py"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("demo_runner_omn21623", _RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_demo_topics_resolve_from_the_registry_in_order() -> None:
    runner = _load_runner()
    assert runner._DEMO_EVT_TOPICS == [
        "onex.evt.omniclaude.session-started.v1",
        "onex.evt.omniclaude.prompt-submitted.v1",
        "onex.evt.omniclaude.tool-executed.v1",
        "onex.evt.omniclaude.session-ended.v1",
        "onex.evt.omniclaude.session-outcome.v1",
    ]
    assert runner._DEMO_CMD_TOPICS == [
        "onex.cmd.omniintelligence.claude-hook-event.v1",
        "onex.cmd.omniintelligence.tool-content.v1",
    ]


@pytest.mark.unit
def test_runner_source_holds_no_topic_literal() -> None:
    source = _RUNNER.read_text(encoding="utf-8")
    assert (
        re.search(r"onex\.(?:cmd|evt)\.[a-z0-9_-]+\.[a-z0-9._-]+\.v[0-9]+", source)
        is None
    )
