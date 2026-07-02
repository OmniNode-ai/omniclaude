# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression guard for the OMN-13244 measurement baseline (OMN-13846).

Context: OMN-13835 (PR #1831) auto-merged despite a hold and restored the full
onex hook surface, destroying the deliberate OMN-13244 measurement baseline
(``{"hooks": {}}``). The disabled hooks are context-injection hooks whose
latency/usefulness is being measured -- they must stay disabled until an
explicit operator decision re-registers them.

OMN-13856 (operator-approved, 2026-07-02) carves ONE exception into that
baseline: the Done-flip durable-evidence guard is re-registered as the minimal
"Option A" carve-out (no fake Done). Everything else stays disabled. These tests
therefore lock in a *narrowed* baseline:

1. ``plugins/onex/hooks/hooks.json`` registers EXACTLY the Done-flip guard and
   nothing else, while retaining the ``$schema`` / ``description`` / ``version``
   metadata keys.
2. The skill-substitution guard machinery (module, config YAML, wrapper
   script, tests) REMAINS on disk -- unregistered, so activating it later is
   a one-line config add and an explicit operator decision, not a code
   restore.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).parent.parent.parent
_HOOKS_JSON = _REPO_ROOT / "plugins" / "onex" / "hooks" / "hooks.json"

# Skill-substitution guard machinery that must remain on disk (unregistered).
_GUARD_FILES = (
    "plugins/onex/hooks/scripts/pre_tool_use_skill_substitution_guard.sh",
    "src/omniclaude/hooks/pre_tool_use_skill_substitution_guard.py",
    "src/omniclaude/hooks/raw_command_to_skill.yaml",
    "tests/unit/hooks/test_pre_tool_use_skill_substitution_guard.py",
)


# The ONLY hook re-registered by the OMN-13856 Option A carve-out.
_DONE_FLIP_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_done_flip_guard.sh"
)


def test_hooks_json_is_narrowed_option_a_baseline() -> None:
    """hooks.json registers EXACTLY the Done-flip guard (OMN-13856 carve-out).

    The OMN-13244 measurement baseline stays intact for every context-injection
    hook; the operator-approved OMN-13856 carve-out re-registers ONE guard — the
    Done-flip durable-evidence gate — and nothing else. Any additional
    registration means the disabled measurement hooks were re-enabled without an
    explicit operator decision (see OMN-13846); a removal of this entry means the
    fake-Done gate regressed.
    """
    data = json.loads(_HOOKS_JSON.read_text())
    hooks = data.get("hooks", {})

    # Exactly one event class, PreToolUse, is registered.
    assert set(hooks.keys()) == {"PreToolUse"}, (
        "hooks.json must register ONLY PreToolUse for the OMN-13856 Option A "
        f"carve-out (measurement baseline otherwise intact). Found event classes: "
        f"{sorted(hooks.keys())!r}"
    )

    # Exactly one command is wired, and it is the Done-flip guard.
    commands = [
        hook.get("command", "")
        for group in hooks["PreToolUse"]
        for hook in group.get("hooks", [])
    ]
    assert commands == [_DONE_FLIP_GUARD_COMMAND], (
        "hooks.json PreToolUse must register EXACTLY the Done-flip durable-evidence "
        "guard and nothing else (OMN-13856 Option A carve-out). A different or "
        "additional command means either the measurement baseline was re-enabled "
        "without an operator decision (OMN-13846) or the fake-Done gate regressed. "
        f"Found: {commands!r}"
    )

    # The matcher must target the Linear write tools that flip Done.
    matchers = [group.get("matcher", "") for group in hooks["PreToolUse"]]
    assert matchers == ["^mcp__linear-server__(save_issue|update_issue)$"], (
        f"Done-flip guard must match Linear save_issue/update_issue. Found: {matchers!r}"
    )


def test_hooks_json_retains_metadata_keys() -> None:
    """The baseline keeps the $schema/description/version metadata keys."""
    data = json.loads(_HOOKS_JSON.read_text())
    for key in ("$schema", "description", "version"):
        assert key in data, f"hooks.json baseline missing metadata key: {key!r}"


@pytest.mark.parametrize("rel_path", _GUARD_FILES)
def test_skill_substitution_guard_machinery_remains_on_disk(rel_path: str) -> None:
    """Guard files must remain on disk (unregistered) for a one-line re-enable.

    Disabling in hooks.json must NOT delete the skill-substitution guard
    machinery -- keeping it on disk means activating the guard later is a
    pure config change (register in hooks.json) and an explicit operator
    decision.
    """
    path = _REPO_ROOT / rel_path
    assert path.is_file(), (
        f"Skill-substitution guard file missing: {rel_path}. The OMN-13244 baseline "
        "unregisters the guard but must retain its machinery on disk so re-enabling "
        "is a one-line config add (see OMN-13846)."
    )
