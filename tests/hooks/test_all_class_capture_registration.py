# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""All-class hook capture registration (OMN-16979).

The event registry alone is not a producer. These checks pin the installed
Claude hook surface and the actual lifecycle seam: a skill-started record must
be appended from PreToolUse, while the terminal record is emitted only after
the tool has returned.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_JSON = _ROOT / "plugins/onex/hooks/hooks.json"
_INVENTORY = _ROOT / "plugins/onex/hooks/contracts/hook_inventory.yaml"
_SCRIPTS = _ROOT / "plugins/onex/hooks/scripts"
_EVENT_REGISTRY = _ROOT / "plugins/onex/lib/event_registry/omniclaude.yaml"


def _registered(event: str, matcher: str) -> set[str]:
    hooks = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
    return {
        Path(hook["command"]).name
        for group in hooks[event]
        if group.get("matcher") == matcher
        for hook in group["hooks"]
    }


def test_content_bearing_capture_producers_are_registered_and_inventory_declared() -> (
    None
):
    expected = {
        ("PreToolUse", "Skill"): {"pre_tool_use_skill_started.sh"},
        ("PostToolUse", "Skill"): {"post-tool-use-quality.sh"},
        ("PostToolUse", "Bash"): {"post_tool_use_output_capture_metadata.sh"},
    }
    inventory = yaml.safe_load(_INVENTORY.read_text(encoding="utf-8"))
    declared = {entry["script"] for entry in inventory["expected_hooks"]}

    for (event, matcher), scripts in expected.items():
        assert scripts <= _registered(event, matcher)
        assert scripts <= declared


def test_skill_started_and_completed_use_the_real_hook_boundaries() -> None:
    started = (_SCRIPTS / "pre_tool_use_skill_started.sh").read_text(encoding="utf-8")
    completed = (_SCRIPTS / "post-tool-use-quality.sh").read_text(encoding="utf-8")

    assert '"skill.started"' in started
    assert '"skill.completed"' not in started
    assert '"skill.completed"' in completed
    assert '"skill.started"' not in completed
    assert "tool_use_id" in started
    assert "tool_use_id" in completed
    assert 'SKILL_SESSION_ID=$(echo "$TOOL_INFO"' in completed
    assert '_SKILL_CORR_ID="${ONEX_CORRELATION_ID:-$SKILL_SESSION_ID}"' in completed


def test_all_content_bearing_producers_use_the_contract_transform() -> None:
    registry = yaml.safe_load(_EVENT_REGISTRY.read_text(encoding="utf-8"))
    expected = {
        "session.started": "onex.evt.omniclaude.session-started.v1",
        "session.ended": "onex.evt.omniclaude.session-ended.v1",
        "prompt.submitted": "onex.evt.omniclaude.prompt-submitted.v1",
        "tool.executed": "onex.evt.omniclaude.tool-executed.v1",
        "skill.started": "onex.evt.omniclaude.skill-started.v1",
        "skill.completed": "onex.evt.omniclaude.skill-completed.v1",
        "tool.output.captured": "onex.evt.omnimarket.tool-output-captured.v1",
    }

    for event, topic in expected.items():
        rules = registry["events"][event]["fan_out"]
        rule = next(rule for rule in rules if rule["topic"] == topic)
        assert rule.get("transform") == "redact_capture"


def test_new_semantic_capture_producers_supply_their_required_fields() -> None:
    """The local emit client accepts semantic events only after daemon validation."""
    registry = yaml.safe_load(_EVENT_REGISTRY.read_text(encoding="utf-8"))
    producer_fields = {
        "skill.started": {"run_id", "skill_name", "repo_id", "correlation_id"},
        "skill.completed": {
            "run_id",
            "skill_name",
            "repo_id",
            "correlation_id",
            "status",
        },
        "tool.output.captured": {
            "tool_name",
            "suppression_decision",
            "correlation_id",
            "session_id",
            "tool_use_id",
            "artifact_ref",
            "command_type",
            "original_bytes",
            "original_lines",
        },
    }

    for event_type, fields in producer_fields.items():
        required = set(registry["events"][event_type]["required_fields"])
        assert required <= fields, f"{event_type} producer omits {required - fields}"
