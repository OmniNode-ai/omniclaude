# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""SD-06: Assert adversarial-rubric.md is bundled in the plugin and SKILL.md uses plugin-relative path."""

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).parents[2] / "plugins" / "onex"
RUBRIC_PATH = PLUGIN_ROOT / "prompts" / "adversarial-rubric.md"
SKILL_PATH = PLUGIN_ROOT / "skills" / "adversarial_pipeline" / "SKILL.md"
OMNI_HOME_PATTERN = re.compile(r"\$OMNI_HOME")


def test_rubric_bundled_in_plugin() -> None:
    assert RUBRIC_PATH.exists(), f"adversarial-rubric.md not found at {RUBRIC_PATH}"
    assert RUBRIC_PATH.stat().st_size > 0, "adversarial-rubric.md is empty"


def test_skill_uses_plugin_relative_path() -> None:
    content = SKILL_PATH.read_text()
    assert not OMNI_HOME_PATTERN.search(content), (
        "SKILL.md still references $OMNI_HOME — must use plugin-relative path"
    )
    assert "plugins/onex/prompts/adversarial-rubric.md" in content, (
        "SKILL.md does not reference bundled rubric path"
    )
