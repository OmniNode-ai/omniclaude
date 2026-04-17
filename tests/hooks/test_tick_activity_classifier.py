# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for tick_activity_classifier — idle-watchdog tick classifier [OMN-9053].

Replaces the OMN-9036 stub `cron-idle-watchdog.sh` with real classification logic
so overnight silence-as-compliance (retro §4.4) stops producing friction on every
tick. Coverage follows plan Task 9 spec:
    - observational tools (Read/Grep/gh-view/etc) -> ActivityKind.OBSERVATIONAL
    - mutating tools (Write/Edit/Agent/git-push/gh-api-PATCH) -> ActivityKind.MUTATING
    - is_idle_tick True when mutating/total < min_ratio (default 0.1)
    - is_idle_tick False when mix of observational and mutating calls
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import tick_activity_classifier  # noqa: E402
from tick_activity_classifier import (  # noqa: E402
    ActivityKind,
    classify_tool_call,
    is_idle_tick,
)

pytestmark = pytest.mark.unit


def test_observational_tools_classified_correctly() -> None:
    assert (
        classify_tool_call({"name": "Bash", "input": {"command": "gh pr view 1234"}})
        == ActivityKind.OBSERVATIONAL
    )
    assert (
        classify_tool_call({"name": "Read", "input": {"file_path": "/tmp/x"}})
        == ActivityKind.OBSERVATIONAL
    )
    assert (
        classify_tool_call({"name": "Grep", "input": {"pattern": "foo"}})
        == ActivityKind.OBSERVATIONAL
    )


def test_mutating_tools_classified_correctly() -> None:
    assert (
        classify_tool_call(
            {"name": "Bash", "input": {"command": "gh api --method PATCH ..."}}
        )
        == ActivityKind.MUTATING
    )
    assert classify_tool_call({"name": "Write", "input": {}}) == ActivityKind.MUTATING
    assert classify_tool_call({"name": "Edit", "input": {}}) == ActivityKind.MUTATING
    assert classify_tool_call({"name": "Agent", "input": {}}) == ActivityKind.MUTATING


def test_idle_tick_when_all_observational() -> None:
    calls = [{"name": "Bash", "input": {"command": "gh pr view 1"}}] * 5
    assert is_idle_tick(calls) is True


def test_active_tick_when_mix() -> None:
    calls = [
        {"name": "Bash", "input": {"command": "gh pr view 1"}},
        {"name": "Bash", "input": {"command": "git push"}},
    ]
    assert is_idle_tick(calls) is False


def test_module_exports_activitykind_values() -> None:
    assert ActivityKind.OBSERVATIONAL.value == "observational"
    assert ActivityKind.MUTATING.value == "mutating"
    assert tick_activity_classifier.ActivityKind is ActivityKind
