# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression guard for the OMN-13244 measurement baseline (OMN-13846).

Context: OMN-13835 (PR #1831) auto-merged despite a hold and restored the full
onex hook surface, destroying the deliberate OMN-13244 measurement baseline
(``{"hooks": {}}``). The disabled hooks are context-injection hooks whose
latency/usefulness is being measured -- they must stay disabled until an
explicit operator decision re-registers them.

OMN-13856 (operator-approved, 2026-07-02) carved ONE exception into that
baseline: the Done-flip durable-evidence guard, re-registered as the minimal
"Option A" carve-out (no fake Done). OMN-14330 carves a second, equally
targeted exception: the OMN-7018 worktree canonical-root guard, extracted
into a dedicated ``pre_tool_use_worktree_guard.sh`` script containing ONLY
the ``git worktree add`` canonical-root check -- not the rest of
``pre_tool_use_bash_guard.sh`` / ``bash_guard.py`` (destructive-command
HARD_BLOCK, ``--no-verify`` enforcement, ``gh pr merge`` mismatch blocking,
SOFT_ALERT, CONTEXT_ADVISORY), which remain unregistered. OMN-15062 carves a
third, narrowly-scoped exception: a ``SubagentStop`` secret-leak guard that
blocks a subagent's final report from completing when it matches a known
secret pattern -- a security control, not a re-enable of the disabled
context-injection/measurement hooks (real incident: a 2026-07-24
credential-investigation subagent's final report echoed a raw credential).
Everything else stays disabled. These tests therefore lock in a *narrowed*
baseline:

1. ``plugins/onex/hooks/hooks.json`` registers EXACTLY the Done-flip guard,
   the worktree canonical-root guard, and the SubagentStop secret-leak guard,
   and nothing else, while retaining the ``$schema`` / ``description`` /
   ``version`` metadata keys.
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


# The hooks re-registered by the OMN-13856 + OMN-14330 + OMN-15062 carve-outs,
# in hooks.json registration order.
_DONE_FLIP_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_done_flip_guard.sh"
)
_WORKTREE_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_worktree_guard.sh"
)
_SUBAGENT_STOP_SECRET_LEAK_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/subagent_stop_secret_leak_guard.sh"
)


def test_hooks_json_is_narrowed_option_a_baseline() -> None:
    """hooks.json registers EXACTLY the Done-flip + worktree + secret-leak guards.

    The OMN-13244 measurement baseline stays intact for every context-injection
    hook; the operator-approved OMN-13856, OMN-14330, and OMN-15062 carve-outs
    re-register exactly three guards — the Done-flip durable-evidence gate, the
    OMN-7018 worktree canonical-root gate, and the SubagentStop secret-leak gate
    — and nothing else. Any additional registration means the disabled
    measurement hooks were re-enabled without an explicit operator decision (see
    OMN-13846); removal of any entry means the corresponding guard regressed.
    """
    data = json.loads(_HOOKS_JSON.read_text())
    hooks = data.get("hooks", {})

    # Exactly two event classes, PreToolUse and SubagentStop, are registered.
    assert set(hooks.keys()) == {"PreToolUse", "SubagentStop"}, (
        "hooks.json must register ONLY PreToolUse and SubagentStop for the "
        "OMN-13856/OMN-14330/OMN-15062 carve-outs (measurement baseline otherwise "
        f"intact). Found event classes: {sorted(hooks.keys())!r}"
    )

    # Exactly two PreToolUse commands are wired: Done-flip guard, then worktree guard.
    commands = [
        hook.get("command", "")
        for group in hooks["PreToolUse"]
        for hook in group.get("hooks", [])
    ]
    assert commands == [_DONE_FLIP_GUARD_COMMAND, _WORKTREE_GUARD_COMMAND], (
        "hooks.json PreToolUse must register EXACTLY the Done-flip durable-evidence "
        "guard and the worktree canonical-root guard and nothing else (OMN-13856 + "
        "OMN-14330 carve-outs). A different or additional command means either the "
        "measurement baseline was re-enabled without an operator decision "
        f"(OMN-13846) or one of the guards regressed. Found: {commands!r}"
    )

    # The matchers must target the Linear write tools that flip Done, then Bash.
    matchers = [group.get("matcher", "") for group in hooks["PreToolUse"]]
    assert matchers == ["^mcp__linear-server__(save_issue|update_issue)$", "Bash"], (
        f"Done-flip guard must match Linear save_issue/update_issue and the "
        f"worktree guard must match Bash. Found: {matchers!r}"
    )

    # Exactly one SubagentStop command is wired: the secret-leak guard.
    subagent_stop_commands = [
        hook.get("command", "")
        for group in hooks["SubagentStop"]
        for hook in group.get("hooks", [])
    ]
    assert subagent_stop_commands == [_SUBAGENT_STOP_SECRET_LEAK_GUARD_COMMAND], (
        "hooks.json SubagentStop must register EXACTLY the secret-leak guard "
        f"(OMN-15062 carve-out). Found: {subagent_stop_commands!r}"
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


def test_bash_guard_and_bash_guard_py_remain_on_disk_unregistered() -> None:
    """pre_tool_use_bash_guard.sh + bash_guard.py stay on disk, unregistered.

    The OMN-14330 carve-out extracts a dedicated, minimal worktree-only script
    rather than registering the full bash guard (which bundles destructive-
    command HARD_BLOCK, ``--no-verify`` enforcement, ``gh pr merge`` mismatch
    blocking, SOFT_ALERT, and CONTEXT_ADVISORY checks alongside the worktree
    check). Both files must remain present so re-registering the full guard
    later is a one-line config add and an explicit operator decision.
    """
    for rel_path in (
        "plugins/onex/hooks/scripts/pre_tool_use_bash_guard.sh",
        "plugins/onex/hooks/lib/bash_guard.py",
    ):
        path = _REPO_ROOT / rel_path
        assert path.is_file(), f"Expected file missing: {rel_path}"

    data = json.loads(_HOOKS_JSON.read_text())
    hooks = data.get("hooks", {})
    commands = [
        hook.get("command", "")
        for group in hooks.get("PreToolUse", [])
        for hook in group.get("hooks", [])
    ]
    assert not any(cmd.endswith("pre_tool_use_bash_guard.sh") for cmd in commands), (
        "pre_tool_use_bash_guard.sh must NOT be registered by the OMN-14330 "
        "carve-out — only the dedicated pre_tool_use_worktree_guard.sh is."
    )
