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
OMN-15213 carves a fourth, likewise narrow exception: a ``SubagentStop``
report-contract guard that fails a lane RED when its final return is
bare-Done-class rather than the report the golden-chain contract requires
(real incident: workflow runs ``wf_00bcb6a9-f0b`` 3/5 and
``wf_1923e07f-b65`` 3/3 returned filler final text while their durable
artifacts were real). OMN-16277 carves a fifth, likewise narrow exception: a
``PostToolUse`` Bash-matcher secret-redaction guard that masks secret-shaped
patterns in raw Bash ``tool_response`` text via
``hookSpecificOutput.updatedToolOutput`` before it lands in the transcript --
a security control, not a re-enable of the disabled context-injection/
measurement hooks (real incident: two credential leaks on 2026-08-19, an
over-broad kubectl jsonpath dump of an Infisical machine-identity
``clientSecret``, and an ``env | grep`` output whose password lived
mid-URL rather than in a matched key). OMN-16162 carves a sixth exception
(S0): a SessionStart and a SessionEnd bus-mirror hook that each
direct-dispatch a single event (session-started / session-ended) to
omnimarket's ``node_event_emit_effect``, backgrounded and fail-open -- the
local-bus-mirror transport that supersedes the OMN-16090 HTTP spool-shipper
stopgap. OMN-16162 S1 extends the identical carve-out to two more events: a
UserPromptSubmit bus-mirror hook (prompt-submitted, length-only payload --
never the prompt text itself, per the onex.evt.* preview-safe invariant) and
a catch-all (matcher ``.*``) PostToolUse bus-mirror hook (tool-executed,
tool-name/timing/interrupted-flag only -- never tool_input/tool_response
content), kept as a separate registration entry from the OMN-16277
Bash-matcher secret-redaction guard so neither touches the other's payload.
None of these four hooks re-enables any of the disabled context-injection/
measurement hooks; each is a dedicated, minimal script containing ONLY the
direct-dispatch hand-off. Everything else stays disabled. These tests
therefore lock in a *narrowed* baseline:

1. ``plugins/onex/hooks/hooks.json`` registers EXACTLY the Done-flip guard,
   the worktree canonical-root guard, the PostToolUse secret-redaction guard,
   the PostToolUse bus-mirror hook, the SubagentStop secret-leak guard, the
   SubagentStop report-contract guard, the SessionStart bus-mirror hook, the
   SessionEnd bus-mirror hook, and the UserPromptSubmit bus-mirror hook, and
   nothing else, while retaining the ``$schema`` / ``description`` /
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


# The hooks re-registered by the OMN-13856 + OMN-14330 + OMN-15062 +
# OMN-15213 + OMN-16277 + OMN-16162 + OMN-16471 + OMN-16478 carve-outs, in hooks.json
# registration order.
_DONE_FLIP_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_done_flip_guard.sh"
)
_WORKTREE_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_worktree_guard.sh"
)
_LANE_LIVENESS_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_lane_liveness_guard.sh"
)
_POST_TOOL_USE_SECRET_REDACT_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post_tool_use_secret_redact_guard.sh"
)
_SUBAGENT_STOP_SECRET_LEAK_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/subagent_stop_secret_leak_guard.sh"
)
_SUBAGENT_STOP_REPORT_CONTRACT_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/subagent_stop_report_contract_guard.sh"
)
_LANE_OPEN_COMMAND = "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_lane_open.sh"
_SUBAGENT_STOP_LANE_TERMINATION_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/subagent_stop_lane_termination_guard.sh"
)
_SESSION_START_BUS_MIRROR_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session_start_bus_mirror.sh"
)
_SESSION_END_BUS_MIRROR_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session_end_bus_mirror.sh"
)
_USER_PROMPT_SUBMIT_BUS_MIRROR_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/user_prompt_submit_bus_mirror.sh"
)
_POST_TOOL_USE_BUS_MIRROR_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post_tool_use_bus_mirror.sh"
)


def test_hooks_json_is_narrowed_option_a_baseline() -> None:
    """hooks.json registers EXACTLY the Done-flip + worktree + lane-liveness + secret-leak guards.

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

    # Exactly six event classes are registered: PreToolUse, PostToolUse,
    # SubagentStop, SessionStart, SessionEnd, UserPromptSubmit.
    assert set(hooks.keys()) == {
        "PreToolUse",
        "PostToolUse",
        "SubagentStop",
        "SessionStart",
        "SessionEnd",
        "UserPromptSubmit",
    }, (
        "hooks.json must register ONLY PreToolUse, PostToolUse, SubagentStop, "
        "SessionStart, SessionEnd, and UserPromptSubmit for the OMN-13856/"
        "OMN-14330/OMN-15062/OMN-15213/OMN-16277/OMN-16162/OMN-16471/"
        "OMN-16478 carve-outs "
        f"(measurement baseline otherwise intact). Found event classes: {sorted(hooks.keys())!r}"
    )

    # Exactly four PreToolUse commands are wired: Done-flip guard, worktree
    # guard, lane-open recorder, then lane-liveness guard.
    commands = [
        hook.get("command", "")
        for group in hooks["PreToolUse"]
        for hook in group.get("hooks", [])
    ]
    assert commands == [
        _DONE_FLIP_GUARD_COMMAND,
        _WORKTREE_GUARD_COMMAND,
        _LANE_OPEN_COMMAND,
        _LANE_LIVENESS_GUARD_COMMAND,
    ], (
        "hooks.json PreToolUse must register EXACTLY the Done-flip durable-evidence "
        "guard, the worktree canonical-root guard, the lane-dispatch recorder, and "
        "the lane-liveness guard, and nothing else (OMN-13856 + OMN-14330 + "
        "OMN-16471 + OMN-16478 carve-outs). A different or additional command "
        "means either the measurement baseline was re-enabled without an operator "
        "decision (OMN-13846) or one of the guards regressed. "
        f"Found: {commands!r}"
    )

    # The matchers must target the Linear write tools that flip Done, then Bash,
    # then the agent-lane dispatch tools (OMN-16471), then SendMessage.
    matchers = [group.get("matcher", "") for group in hooks["PreToolUse"]]
    assert matchers == [
        "^mcp__linear-server__(save_issue|update_issue)$",
        "Bash",
        "^(Task|Agent|Workflow)$",
        "^SendMessage$",
    ], (
        f"Done-flip guard must match Linear save_issue/update_issue, the worktree "
        f"guard must match Bash, the lane recorder must match the dispatch tools, "
        f"and the lane-liveness guard must match SendMessage. "
        f"Found: {matchers!r}"
    )

    # Exactly two PostToolUse commands are wired: the secret-redaction guard
    # (Bash only, OMN-16277), then the catch-all bus-mirror hook (.*, OMN-16162 S1).
    post_tool_use_commands = [
        hook.get("command", "")
        for group in hooks["PostToolUse"]
        for hook in group.get("hooks", [])
    ]
    assert post_tool_use_commands == [
        _POST_TOOL_USE_SECRET_REDACT_GUARD_COMMAND,
        _POST_TOOL_USE_BUS_MIRROR_COMMAND,
    ], (
        "hooks.json PostToolUse must register EXACTLY the secret-redaction guard "
        "(OMN-16277 carve-out) and the bus-mirror hook (OMN-16162 S1 carve-out) "
        f"and nothing else. Found: {post_tool_use_commands!r}"
    )
    post_tool_use_matchers = [
        group.get("matcher", "") for group in hooks["PostToolUse"]
    ]
    assert post_tool_use_matchers == ["Bash", ".*"], (
        "PostToolUse secret-redaction guard must match Bash only and the "
        f"bus-mirror hook must match every tool (.*). Found: {post_tool_use_matchers!r}"
    )

    # Exactly three SubagentStop commands are wired: the secret-leak guard,
    # the report-contract guard, then the lane-termination guard.
    subagent_stop_commands = [
        hook.get("command", "")
        for group in hooks["SubagentStop"]
        for hook in group.get("hooks", [])
    ]
    assert subagent_stop_commands == [
        _SUBAGENT_STOP_SECRET_LEAK_GUARD_COMMAND,
        _SUBAGENT_STOP_REPORT_CONTRACT_GUARD_COMMAND,
        _SUBAGENT_STOP_LANE_TERMINATION_GUARD_COMMAND,
    ], (
        "hooks.json SubagentStop must register EXACTLY the secret-leak guard "
        "(OMN-15062 carve-out), the report-contract guard (OMN-15213 carve-out), "
        "and the lane-termination guard (OMN-16471 carve-out). Found: "
        f"{subagent_stop_commands!r}"
    )

    # Exactly one SessionStart command: the bus-mirror hook (OMN-16162).
    session_start_commands = [
        hook.get("command", "")
        for group in hooks["SessionStart"]
        for hook in group.get("hooks", [])
    ]
    assert session_start_commands == [_SESSION_START_BUS_MIRROR_COMMAND], (
        "hooks.json SessionStart must register EXACTLY the bus-mirror hook "
        f"(OMN-16162 carve-out). Found: {session_start_commands!r}"
    )

    # Exactly one SessionEnd command: the bus-mirror hook (OMN-16162).
    session_end_commands = [
        hook.get("command", "")
        for group in hooks["SessionEnd"]
        for hook in group.get("hooks", [])
    ]
    assert session_end_commands == [_SESSION_END_BUS_MIRROR_COMMAND], (
        "hooks.json SessionEnd must register EXACTLY the bus-mirror hook "
        f"(OMN-16162 carve-out). Found: {session_end_commands!r}"
    )

    # Exactly one UserPromptSubmit command: the bus-mirror hook (OMN-16162 S1).
    user_prompt_submit_commands = [
        hook.get("command", "")
        for group in hooks["UserPromptSubmit"]
        for hook in group.get("hooks", [])
    ]
    assert user_prompt_submit_commands == [_USER_PROMPT_SUBMIT_BUS_MIRROR_COMMAND], (
        "hooks.json UserPromptSubmit must register EXACTLY the bus-mirror hook "
        f"(OMN-16162 S1 carve-out). Found: {user_prompt_submit_commands!r}"
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
