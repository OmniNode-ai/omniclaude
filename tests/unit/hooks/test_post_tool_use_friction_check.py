# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

import json
import sys
from pathlib import Path

import pytest

_HOOKS_LIB = str(
    Path(__file__).resolve().parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
_SHARED_PATH = str(
    Path(__file__).resolve().parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "skills"
    / "_shared"
)
for p in [_HOOKS_LIB, _SHARED_PATH]:
    if p not in sys.path:
        sys.path.insert(0, p)

from post_tool_use_friction_check import check_tool_for_friction


@pytest.mark.unit
class TestPostToolUseFrictionCheck:
    def test_failed_skill_records_friction(self, tmp_path: Path):
        registry = tmp_path / "friction.ndjson"
        tool_info = {
            "tool_name": "Skill",
            "tool_response": {
                "status": "failed",
                "skill_name": "deploy",
                "error": "CI check failed",
            },
        }
        check_tool_for_friction(tool_info, session_id="s1", registry_path=registry)
        assert registry.exists()
        record = json.loads(registry.read_text().strip())
        assert record["surface"] == "tooling/skill-failed"

    def test_successful_skill_no_friction(self, tmp_path: Path):
        registry = tmp_path / "friction.ndjson"
        tool_info = {
            "tool_name": "Skill",
            "tool_response": {"status": "success", "skill_name": "deploy"},
        }
        check_tool_for_friction(tool_info, session_id="s1", registry_path=registry)
        assert not registry.exists()

    def test_non_skill_tool_no_friction(self, tmp_path: Path):
        registry = tmp_path / "friction.ndjson"
        tool_info = {
            "tool_name": "Read",
            "tool_response": {"content": "file contents"},
        }
        check_tool_for_friction(tool_info, session_id="s1", registry_path=registry)
        assert not registry.exists()

    def test_blocked_skill_records_friction(self, tmp_path: Path):
        registry = tmp_path / "friction.ndjson"
        tool_info = {
            "tool_name": "Skill",
            "tool_response": {
                "status": "blocked",
                "skill_name": "merge",
                "blocked_reason": "merge conflict",
            },
        }
        check_tool_for_friction(tool_info, session_id="s1", registry_path=registry)
        record = json.loads(registry.read_text().strip())
        assert record["surface"] == "tooling/skill-blocked"
        assert record["severity"] == "high"
