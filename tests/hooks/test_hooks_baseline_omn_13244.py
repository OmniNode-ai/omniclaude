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
direct-dispatch hand-off.

OMN-17006 carves the final exception, and it is a *re-enable* rather than a new
build: the OMN-8376 overseer foreground-block guard, which the OMN-13244
baseline unregistered and which then sat on disk for months while the rule it
enforces was corrected by hand ~61 times over 16 of 18 days
(``docs/tracking/2026-08-29-beta-off-the-rails-analysis.md``, mechanism A1).
It blocks foreground Bash/Edit/Write/NotebookEdit/MultiEdit against repo paths
only while ``$ONEX_STATE_DIR/overseer-active.flag`` marks an overseer contract
as driving, and passes everything through when the flag is absent.

Its sibling from the same audit -- the OMN-8928/8929 dispatch-claim pre/post
pair -- is deliberately NOT re-registered. Live probing on 2026-08-29 showed
its ``exit 2`` is swallowed by the ``error-guard.sh`` EXIT trap (it never calls
``trap - EXIT``, unlike every registered guard), its deny payload uses a
``{"type": "permissionDenied"}`` shape this harness does not honour, and its
claimant falls back to the shared constant ``session`` so two anonymous lanes
can never collide. OMN-17005 carries the re-registration ACs and the expiry
condition. Both scripts stay on disk, unregistered.

OMN-17168 carves an eleventh exception, and it is the first that exists to make
an artifact *visible* rather than to refuse an action: a SessionStart
goal-surface hook that prints the ``state_as_of`` of
``$KNOWLEDGE_BASE_INTERNAL_PATH/beta/GOAL.md``, its age, and the goal rows, and
that prints the exact re-baseline command when the goal is missing or older than
12h. It is print-only -- pure bash, no interpreter, no network, no writes -- and
exits 0 on every user-visible outcome, so it can neither refuse nor delay a
session. It is not a re-enable of the disabled context-injection hooks: it
surfaces one artifact the session is already required to open from (memory
``feedback_session_goal_from_ground_state_reconciled_to_plan``), not
model-generated context. ``KNOWLEDGE_BASE_INTERNAL_PATH`` has no default,
because a guessed clone would surface another checkout's goal as if it were this
one (CLAUDE.md rule 8).

OMN-17207 carves a twelfth exception, and it is the second pure *re-enable*: the
local-capture pair ``post_tool_use_auto_checkpoint.sh`` and
``post_tool_use_changeset_guard.sh``, revived from the OMN-13244 unregister as
DURABLE LOCAL CAPTURE ONLY. The 2026-08-30 archaeology of that unregister found
the surface had produced almost nothing durable -- ~160k trajectory invocations
wrote zero entries, and the only machine-readable series that survived was
changeset-guard's 2,703-line JSONL. These two are revived because they are the
only ones whose captured fields overlap the C11 git-delta set (commit sha,
branch, message, files-changed, PR number+state).

Three defects the archaeology found are fixed as a condition of re-registering:
the ``printf '%s' "$TOOL_INFO"`` passthrough echo is removed from every branch
(it re-emitted the raw ``tool_response`` that the OMN-16277 guard masks on this
same Bash matcher); changeset-guard's advisory ``additionalContext`` injection is
NOT revived, only its JSONL side-write (per-turn injection is the token cost
OMN-13244 removed); and auto-checkpoint's ``gh pr view`` is bounded by
``timeout 5`` with its retention cap raised from 5 to 200 (the 5-file cap is why
only one 8-hour window of checkpoints survived to be examined). Neither hook
publishes to the bus -- that half stays gated behind OMN-17209 -- so this is not
an OMN-16162-class transport re-enable.

OMN-17020 carves a further exception and, unlike every one before it, also moves
where this file's guarantee lives. The exception is a SessionStart hook-inventory
parity check (``session_start_hook_parity.sh``): warn-only by construction, every
path exits 0, because a hook-manifest mismatch must never make the machine
unusable. The relocation is the more important half. The lists below are
hand-maintained -- every carve-out since OMN-13856 has added another literal to
them, and the ordinal chain in ``hooks.json``'s description has already collided
at "thirteenth" -- and a hand-maintained list is exactly what OMN-13244 did not
have when it switched the surface off. As of OMN-17020 the typed inventory at
``plugins/onex/hooks/contracts/hook_inventory.yaml`` is the general record, with
its own gate (``hook-inventory-gate``), its own end-to-end canary for every
enforcement hook, and its own tests (``tests/hooks/test_hook_inventory.py``).
This file keeps its narrower job: it locks the OMN-13244 *baseline* specifically
-- that the measurement hooks stay disabled and that these named carve-outs, and
no others, exist.

Everything else stays disabled. These tests therefore lock in a *narrowed*
baseline:

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
import os
import subprocess
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
# OMN-15213 + OMN-16277 + OMN-16162 + OMN-16471 + OMN-16478 + OMN-16485
# carve-outs, in hooks.json registration order.
_DONE_FLIP_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_done_flip_guard.sh"
)
_WORKTREE_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_worktree_guard.sh"
)
_LANE_LIVENESS_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_lane_liveness_guard.sh"
)
_PR_OWNERSHIP_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_pr_ownership_guard.sh"
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
_AGENT_MODEL_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_agent_model_guard.sh"
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
_OVERSEER_FOREGROUND_BLOCK_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_overseer_foreground_block.sh"
)
_SESSION_START_GOAL_SURFACE_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session_start_goal_surface.sh"
)
_SESSION_START_WORKSPACE_SYNC_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session_start_workspace_sync.sh"
)
_WORKSPACE_RECONCILE_TICK_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/workspace_reconcile_tick.sh"
)
_SESSION_START_HOOK_PARITY_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session_start_hook_parity.sh"
)

# OMN-17207 carve-out: the two LOCAL-ONLY capture hooks revived from
# the OMN-13244 unregister. Neither publishes to the bus (that stays gated
# behind OMN-17209) and neither emits anything on stdout.
_POST_TOOL_USE_AUTO_CHECKPOINT_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post_tool_use_auto_checkpoint.sh"
)
_POST_TOOL_USE_CHANGESET_GUARD_COMMAND = (
    "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post_tool_use_changeset_guard.sh"
)

# The OMN-8928/8929 dispatch-claim pair: on disk, deliberately unregistered.
# See OMN-17005 for the three probed defects and the expiry condition.
_DISPATCH_CLAIM_FILES = (
    "plugins/onex/hooks/scripts/hook_dispatch_claim_pretool.sh",
    "plugins/onex/hooks/scripts/hook_dispatch_claim_posttool.sh",
    "plugins/onex/hooks/lib/dispatch_claim_gate.py",
    "plugins/onex/hooks/lib/dispatch_claim_release.py",
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
        "OMN-16478/OMN-16485 carve-outs "
        f"(measurement baseline otherwise intact). Found event classes: {sorted(hooks.keys())!r}"
    )

    # Exactly seven PreToolUse commands are wired: Done-flip guard, worktree
    # guard, PR lane-ownership guard (OMN-16485), background-agent model guard
    # (OMN-17499), lane-open recorder, lane-liveness guard, then the overseer
    # foreground-block guard.
    #
    # The model guard's position is behaviour, not taste: it is registered
    # AHEAD of the lane-open recorder so a refused dispatch does not first
    # write a phantom OPEN lane record that no terminal record will ever
    # close.
    commands = [
        hook.get("command", "")
        for group in hooks["PreToolUse"]
        for hook in group.get("hooks", [])
    ]
    assert commands == [
        _DONE_FLIP_GUARD_COMMAND,
        _WORKTREE_GUARD_COMMAND,
        _PR_OWNERSHIP_GUARD_COMMAND,
        _AGENT_MODEL_GUARD_COMMAND,
        _LANE_OPEN_COMMAND,
        _LANE_LIVENESS_GUARD_COMMAND,
        _OVERSEER_FOREGROUND_BLOCK_COMMAND,
    ], (
        "hooks.json PreToolUse must register EXACTLY the Done-flip durable-evidence "
        "guard, the worktree canonical-root guard, the PR lane-ownership guard, "
        "the background-agent model guard, the lane-dispatch recorder, the "
        "lane-liveness guard, and the overseer foreground-block guard, and "
        "nothing else (OMN-13856 + OMN-14330 + OMN-16485 + OMN-17499 + "
        "OMN-16471 + OMN-16478 + OMN-17006 carve-outs). "
        "A different or additional command means either the measurement baseline "
        "was re-enabled without an operator decision (OMN-13846) or one of the "
        f"guards regressed. Found: {commands!r}"
    )

    # The matchers must target the Linear write tools that flip Done, then Bash,
    # then the agent-lane dispatch tools (OMN-16471), then SendMessage.
    matchers = [group.get("matcher", "") for group in hooks["PreToolUse"]]
    assert matchers == [
        "^mcp__linear-server__(save_issue|update_issue)$",
        "Bash",
        "^(Workflow|Agent)$",
        "^(Task|Agent|Workflow)$",
        "^SendMessage$",
        "^(Bash|Edit|Write|NotebookEdit|MultiEdit)$",
    ], (
        f"Done-flip guard must match Linear save_issue/update_issue, the worktree "
        f"guard must match Bash, the background-agent model guard must match "
        f"exactly the two dispatch tools that choose a background model "
        f"(Workflow and Agent, never Task), the lane recorder must match the "
        f"dispatch tools, "
        f"the lane-liveness guard must match SendMessage, and the overseer "
        f"foreground-block guard must match exactly the BLOCK_TOOLS set in "
        f"overseer_foreground_block.py. Found: {matchers!r}"
    )

    # Exactly three PostToolUse commands are wired: the secret-redaction guard
    # (Bash only, OMN-16277), the catch-all bus-mirror hook (.*, OMN-16162 S1),
    # then the workspace-reconcile tick (.*, OMN-17190).
    post_tool_use_commands = [
        hook.get("command", "")
        for group in hooks["PostToolUse"]
        for hook in group.get("hooks", [])
    ]
    assert post_tool_use_commands == [
        _POST_TOOL_USE_SECRET_REDACT_GUARD_COMMAND,
        _POST_TOOL_USE_BUS_MIRROR_COMMAND,
        _WORKSPACE_RECONCILE_TICK_COMMAND,
        _POST_TOOL_USE_AUTO_CHECKPOINT_COMMAND,
        _POST_TOOL_USE_CHANGESET_GUARD_COMMAND,
    ], (
        "hooks.json PostToolUse must register EXACTLY the secret-redaction guard "
        "(OMN-16277 carve-out), the bus-mirror hook (OMN-16162 S1 carve-out), the "
        "workspace-reconcile tick (OMN-17190 carve-out), and the two OMN-17207 "
        "local-only capture hooks (auto-checkpoint, changeset-guard) and nothing "
        f"else. Found: {post_tool_use_commands!r}"
    )
    post_tool_use_matchers = [
        group.get("matcher", "") for group in hooks["PostToolUse"]
    ]
    assert post_tool_use_matchers == ["Bash", ".*", ".*", "Bash"], (
        "PostToolUse secret-redaction guard must match Bash only; the bus-mirror "
        "hook and the workspace-reconcile tick must each match every tool (.*) in "
        "their own entry; and the OMN-17207 local-capture group must match Bash "
        f"only. Found: {post_tool_use_matchers!r}"
    )

    # The OMN-17207 local-capture hooks MUST be registered AFTER the
    # secret-redaction guard. `updatedToolOutput` is last-writer-wins
    # (docs/research/2026-06-12-updated-tool-output-shape-probe.md, probe 3),
    # so the redaction guard may only be overwritten by a hook that emits the
    # field -- and these two emit nothing at all. Pinning the order here keeps
    # a future reorder from silently un-redacting Bash output.
    assert post_tool_use_commands.index(
        _POST_TOOL_USE_SECRET_REDACT_GUARD_COMMAND
    ) < post_tool_use_commands.index(_POST_TOOL_USE_AUTO_CHECKPOINT_COMMAND), (
        "the secret-redaction guard must stay ahead of the OMN-17207 capture hooks"
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

    # Exactly four SessionStart commands, in order: the bus-mirror hook
    # (OMN-16162), the goal-surface hook (OMN-17168), the workspace-sync line
    # (OMN-17190), then the hook-inventory parity warning (OMN-17020). Order
    # matters -- the bus mirror backgrounds its dispatch and returns
    # immediately, so what follows is what the session actually opens on: the
    # goal it is working toward, whether the workspace it will work in is
    # current, and whether any hook that is supposed to be enforcing has gone
    # dark.
    session_start_commands = [
        hook.get("command", "")
        for group in hooks["SessionStart"]
        for hook in group.get("hooks", [])
    ]
    assert session_start_commands == [
        _SESSION_START_BUS_MIRROR_COMMAND,
        _SESSION_START_GOAL_SURFACE_COMMAND,
        _SESSION_START_WORKSPACE_SYNC_COMMAND,
        _SESSION_START_HOOK_PARITY_COMMAND,
    ], (
        "hooks.json SessionStart must register EXACTLY the bus-mirror hook "
        "(OMN-16162 carve-out), the goal-surface hook (OMN-17168 carve-out), the "
        "workspace-sync line (OMN-17190 carve-out), and the hook-inventory parity "
        "check (OMN-17020 carve-out), and nothing else. "
        f"Found: {session_start_commands!r}"
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


def test_hooks_json_description_carries_baseline_disable_expiry_rule() -> None:
    """Any future baseline-style disable must carry an expiry + a re-enable ticket.

    OMN-13244 unregistered the whole hook surface with no expiry condition, no
    re-enable ticket, and no inventory of what went dark. The result
    (``docs/tracking/2026-08-29-beta-off-the-rails-analysis.md``, root cause
    RC-A(a)) was that ``pre_tool_use_overseer_foreground_block.sh`` lay on disk,
    switched off, while the foreground rule it enforces was corrected by hand
    ~61 times over 16 of 18 days. Nobody noticed, because a disable with no
    expiry is indistinguishable from a decision.

    This test pins the corrective rule into the artifact it governs: the rule
    lives in the ``description`` of the very file a future disable would edit,
    so it cannot be dropped without failing here.
    """
    data = json.loads(_HOOKS_JSON.read_text())
    description = data.get("description", "")

    for phrase in (
        "STANDING RULE",
        "expiry condition",
        "re-enable ticket",
    ):
        assert phrase in description, (
            f"hooks.json description must state the standing rule that any future "
            f"baseline-style disable lands with an expiry condition and a named "
            f"re-enable ticket in the same change (OMN-17006). Missing: {phrase!r}"
        )

    # The rule must name the incident it exists to prevent, so the next reader
    # gets the reason and not just the instruction.
    assert "OMN-13244" in description, (
        "hooks.json description must cite OMN-13244 as the disable the standing "
        "expiry rule exists to prevent recurring."
    )

    # A disable record that says only "this is off" reproduces OMN-13244: the
    # reader cannot tell who is accountable, why this specific hook is dark,
    # when the disable stops being valid, or what puts it back. The standing
    # rule therefore has to enumerate all four, or it is an instruction with
    # no shape and the next disable satisfies it by writing one sentence.
    for field in ("OWNER", "REASON", "EXPIRY", "RESTORATION"):
        assert field in description, (
            f"hooks.json description's STANDING RULE must require a baseline "
            f"disable to record all four of OWNER / REASON / EXPIRY / "
            f"RESTORATION (OMN-17006). Missing: {field!r}. Without {field!r} a "
            f"future disable can satisfy the rule while still being "
            f"indistinguishable from a decision — the OMN-13244 failure."
        )


@pytest.mark.parametrize("rel_path", _DISPATCH_CLAIM_FILES)
def test_dispatch_claim_machinery_remains_on_disk(rel_path: str) -> None:
    """The OMN-8928/8929 claim pair stays on disk while OMN-17005 is open."""
    path = _REPO_ROOT / rel_path
    assert path.is_file(), (
        f"Dispatch-claim file missing: {rel_path}. The OMN-13244 baseline leaves it "
        "unregistered, not deleted — OMN-17005 carries the re-registration ACs. "
        "Deleting it is the *expiry* branch of OMN-17005 and must close that ticket "
        "won't-fix in the same change, not happen silently."
    )


def test_dispatch_claim_pair_is_not_registered() -> None:
    """The claim pair must stay unregistered until OMN-17005's ACs are met.

    Re-registering it as-is would be worse than leaving it off. Probed
    2026-08-29: (1) its ``exit 2`` is converted to ``exit 0`` by the
    ``error-guard.sh`` EXIT trap because it never calls ``trap - EXIT``, so the
    deny is advisory text and the tool call proceeds; (2) the same run writes a
    false ``HOOK FAILURE ... exited with code 2`` into the error-guard log,
    which also spawns a background Kafka emitter on the OMN-16996-regressed
    interpreter; (3) ``AGENT_ID="${CLAUDE_AGENT_ID:-session}"`` collapses every
    anonymous session onto one claimant, and ``check_and_acquire`` passes when
    ``held_by == claimant`` — so two ordinary lanes never collide.
    """
    data = json.loads(_HOOKS_JSON.read_text())
    hooks = data.get("hooks", {})
    all_commands = [
        hook.get("command", "")
        for groups in hooks.values()
        for group in groups
        for hook in group.get("hooks", [])
    ]
    for script in (
        "hook_dispatch_claim_pretool.sh",
        "hook_dispatch_claim_posttool.sh",
    ):
        assert not any(cmd.endswith(script) for cmd in all_commands), (
            f"{script} must NOT be registered — see OMN-17005 for the three probed "
            "defects (swallowed exit 2, non-canonical deny payload, constant "
            "claimant identity) that must be fixed first."
        )


def test_goal_surface_carve_out_records_owner_reason_expiry_restoration() -> None:
    """The OMN-17168 carve-out carries its own four-field record, not just the rule.

    ``test_hooks_json_description_carries_baseline_disable_expiry_rule`` proves the
    STANDING RULE text is present. That is not the same as proving any *particular*
    carve-out obeys it: the four words appear once in the rule's own sentence, so a
    new registration with no record at all still passes that test. This one pins the
    record for the carve-out that is expected to expire soonest.

    OMN-17168 is a stopgap by construction — it reads a Markdown file that OMN-17169
    is scheduled to replace with a REDUCER projection. Without the RESTORATION line
    naming the repoint, the likeliest failure is not that the hook is deleted but that
    the projection lands and the hook keeps reading a file nobody re-baselines, which
    is a worse outcome than not having it: a stale goal renders as a goal.
    """
    description = json.loads(_HOOKS_JSON.read_text()).get("description", "")

    assert "OMN-17168" in description, (
        "hooks.json description must record the SessionStart goal-surface carve-out "
        "under its ticket (OMN-17168)."
    )

    marker = "its own carve-out record:"
    assert marker in description, (
        "The OMN-17168 carve-out must introduce its OWNER/REASON/EXPIRY/RESTORATION "
        f"record with {marker!r} so the record is locatable, not merely present."
    )
    record = description.split(marker, 1)[1]

    for field in ("OWNER", "REASON", "EXPIRY", "RESTORATION"):
        assert field in record, (
            f"The OMN-17168 carve-out record must name {field!r}. The STANDING RULE "
            "requires all four; a carve-out that inherits the rule's own wording "
            "without stating its own is the OMN-13244 shape (a registration nobody "
            f"can later evaluate). Record found: {record!r}"
        )

    assert "OMN-17169" in record, (
        "The OMN-17168 carve-out's EXPIRY/RESTORATION must name OMN-17169 — the node "
        "re-baseline that turns the session goal into a projection and repoints this "
        "hook off the Markdown file. An expiry with no ticket is not an expiry."
    )


def test_goal_surface_hook_never_hardcodes_a_kb_internal_path() -> None:
    """KNOWLEDGE_BASE_INTERNAL_PATH must have no default (CLAUDE.md rules 6 and 8).

    A default clone path is worse here than a hard failure: the hook would read some
    other checkout's GOAL.md and print it as *this* session's goal, with a plausible
    age and no signal that it came from the wrong tree. The unset branch must print
    the variable name instead.
    """
    script = (
        _REPO_ROOT
        / "plugins"
        / "onex"
        / "hooks"
        / "scripts"
        / "session_start_goal_surface.sh"
    )
    source = script.read_text()

    # No `${VAR:-default}` / `${VAR:=default}` on the config variable.
    for defaulting in (
        "KNOWLEDGE_BASE_INTERNAL_PATH:-/",
        "KNOWLEDGE_BASE_INTERNAL_PATH:=",
    ):
        assert defaulting not in source, (
            f"session_start_goal_surface.sh must not default "
            f"KNOWLEDGE_BASE_INTERNAL_PATH ({defaulting!r} found). Rule 8: a silent "
            "default surfaces another checkout's goal as if it were this one."
        )

    # The unset branch must name the variable so the fix is actionable.
    assert "Missing env var: KNOWLEDGE_BASE_INTERNAL_PATH" in source, (
        "The unset branch must print the exact missing variable name — 'cannot find "
        "the goal' is not an actionable message."
    )


# ---------------------------------------------------------------------------
# OMN-17207: the two LOCAL-ONLY capture hooks revived from the OMN-13244
# unregister. These tests are behavioural -- they drive the real scripts --
# because the whole point of the revival is that the previous iteration
# captured nothing across ~160k invocations while looking registered.
# ---------------------------------------------------------------------------

_REVIVED_LOCAL_CAPTURE_SCRIPTS = (
    "post_tool_use_auto_checkpoint.sh",
    "post_tool_use_changeset_guard.sh",
)


def _run_hook(
    script_name: str, payload: dict, home: Path
) -> subprocess.CompletedProcess:
    """Drive a hook script exactly as the harness does: JSON on stdin."""
    script = _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / script_name
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PLUGIN_ROOT"] = str(_REPO_ROOT / "plugins" / "onex")
    # Force the mask open so the gate is not what makes the test pass.
    env.pop("OMNICLAUDE_HOOKS_DISABLED", None)
    env.pop("ONEX_HOOKS_MASK", None)
    return subprocess.run(
        ["bash", str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,  # the hook's own exit code is the assertion
    )


@pytest.mark.parametrize("script_name", _REVIVED_LOCAL_CAPTURE_SCRIPTS)
def test_revived_capture_hook_emits_nothing_on_stdout(
    script_name: str, tmp_path: Path
) -> None:
    """Neither revived hook may write to stdout, on any path.

    This is the contract that lets them be registered at all. Plain PostToolUse
    stdout is debug-log-only, but a hook that echoes its whole input back is one
    schema change away from re-emitting raw ``tool_response`` -- the exact text
    the OMN-16277 secret-redaction guard exists to mask, on the same matcher.
    The pre-OMN-13244 versions of both scripts did precisely that
    (``printf '%s\\n' "$TOOL_INFO"`` on every branch). Silence is the fix.
    """
    payload = {
        "session_id": "test-session",
        "tool_name": "Bash",
        "tool_input": {"command": "echo hello"},
        "tool_response": {"stdout": "AKIAIOSFODNN7EXAMPLE", "stderr": ""},
    }
    result = _run_hook(script_name, payload, tmp_path)

    assert result.returncode == 0, (
        f"{script_name} must exit 0 (fail-open). stderr: {result.stderr!r}"
    )
    assert result.stdout == "", (
        f"{script_name} must emit NOTHING on stdout. A passthrough echo re-emits "
        "the raw tool_response the OMN-16277 guard masks on this same matcher. "
        f"Found: {result.stdout!r}"
    )


@pytest.mark.parametrize("script_name", _REVIVED_LOCAL_CAPTURE_SCRIPTS)
def test_revived_capture_hook_never_injects_context(script_name: str) -> None:
    """No ``additionalContext`` / ``updatedToolOutput`` in either revived script.

    OMN-13244 unregistered these hooks for token cost -- per-turn context
    injection at ~250-300 tokens/message. Reviving the durable-capture half
    while leaving the injection in would re-create the exact cost that caused
    the baseline. The JSONL side-write is kept; the warning injection is not.
    """
    script = _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / script_name
    # Comments are stripped deliberately: the scripts document *what was removed
    # and why*, and that prose necessarily names the fields. The invariant under
    # test is that no executable line emits them.
    code = "\n".join(
        line
        for line in script.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    for banned in ("additionalContext", "updatedToolOutput", "hookSpecificOutput"):
        assert banned not in code, (
            f"{script_name} must not emit {banned!r} — these hooks are revived as "
            "durable LOCAL capture only (OMN-17207), not as context injection. "
            "The injection half is what OMN-13244 killed."
        )


@pytest.mark.parametrize("script_name", _REVIVED_LOCAL_CAPTURE_SCRIPTS)
def test_revived_capture_hook_does_not_publish_to_the_bus(script_name: str) -> None:
    """Local capture only — the bus half stays gated behind OMN-17209.

    These hooks write to the local filesystem and nothing else. Any dispatch,
    publish, or HTTP call from this seam would put agent-attributable payloads
    on the bus ahead of the OMN-17209 egress/redaction decision.
    """
    script = _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / script_name
    code = "\n".join(
        line
        for line in script.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    for banned in (
        "node_event_emit_effect",
        "hook_emit_append",
        "rpk",
        "curl",
        "kafka",
    ):
        assert banned not in code, (
            f"{script_name} must not reference {banned!r} — OMN-17207 revives these "
            "as local-only capture; publishing stays gated behind OMN-17209."
        )


def test_auto_checkpoint_bounds_its_network_call(tmp_path: Path) -> None:
    """``gh pr view`` must be bounded by an explicit timeout.

    This is the one unbounded-latency call in either revived hook, and it sits
    on the PostToolUse path. OMN-17224 (the fast-append + singleton-drainer
    split) is NOT merged yet, so nothing upstream amortises a slow hook: on
    2026-08-30 the measured emitter load already reached 598 events / 10 s with
    895 windows at or above the 14-concurrent stacking threshold. An unbounded
    network call re-creates that failure mode one commit at a time.
    """
    script = (
        _REPO_ROOT
        / "plugins"
        / "onex"
        / "hooks"
        / "scripts"
        / "post_tool_use_auto_checkpoint.sh"
    )
    code_lines = [
        line
        for line in script.read_text().splitlines()
        if not line.lstrip().startswith("#")
    ]
    assert any("gh pr view" in line for line in code_lines), (
        "the PR-state capture is part of the OMN-17207 field set"
    )
    gh_line = next(line for line in code_lines if "gh pr view" in line)
    assert "timeout" in gh_line, (
        "the `gh pr view` call must be wrapped in `timeout` so a hung network call "
        f"cannot stall the PostToolUse path. Found: {gh_line!r}"
    )


def test_auto_checkpoint_writes_a_checkpoint_on_git_commit(tmp_path: Path) -> None:
    """Live synthetic invocation: the hook must actually write the file.

    The archaeology's central finding is that the previous hook iteration looked
    registered and produced zero durable data. A registration test alone would
    reproduce that mistake, so this drives the real script against a real git
    repo and asserts the artefact exists with the fields the archaeology named.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
    (repo / "a.txt").write_text("one\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "OMN-17207 first"],
        check=True,
        env=env,
    )
    (repo / "a.txt").write_text("two\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "OMN-17207 second"],
        check=True,
        env=env,
    )

    home = tmp_path / "home"
    home.mkdir()
    script = (
        _REPO_ROOT
        / "plugins"
        / "onex"
        / "hooks"
        / "scripts"
        / "post_tool_use_auto_checkpoint.sh"
    )
    hook_env = dict(os.environ)
    hook_env["HOME"] = str(home)
    hook_env["CLAUDE_PLUGIN_ROOT"] = str(_REPO_ROOT / "plugins" / "onex")
    hook_env.pop("ONEX_HOOKS_MASK", None)
    result = subprocess.run(
        ["bash", str(script)],
        input=json.dumps(
            {
                "session_id": "s",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'OMN-17207 second'"},
                "tool_response": {"stdout": "", "stderr": ""},
            }
        ),
        capture_output=True,
        text=True,
        env=hook_env,
        cwd=str(repo),
        timeout=90,
        check=False,  # the hook's own exit code is the assertion
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", f"must stay silent on stdout, found {result.stdout!r}"

    written = sorted((home / ".claude" / "handoffs").glob("checkpoint-*.md"))
    assert written, (
        "auto-checkpoint fired on a real `git commit` and wrote NO file — this is "
        "the exact zero-capture failure the archaeology documented."
    )
    body = written[-1].read_text()
    for field in (
        "commit_hash:",
        "branch:",
        "OMN-17207 second",
        "type: auto-checkpoint",
    ):
        assert field in body, f"checkpoint missing {field!r}. Got:\n{body}"


def test_changeset_guard_writes_jsonl_above_threshold(tmp_path: Path) -> None:
    """Live synthetic invocation of the retained JSONL side-write.

    The archaeology found this was the ONLY durable machine-readable output the
    whole pre-OMN-13244 hook surface ever produced (2,703 lines over 56 days).
    It is kept for continuity of that one series; the warning injection is not.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
    (repo / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "seed"], check=True, env=env
    )
    for i in range(20):  # 20 > the 15-file threshold
        (repo / f"f{i}.txt").write_text(f"{i}\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "big"], check=True, env=env
    )

    home = tmp_path / "home"
    home.mkdir()
    script = (
        _REPO_ROOT
        / "plugins"
        / "onex"
        / "hooks"
        / "scripts"
        / "post_tool_use_changeset_guard.sh"
    )
    hook_env = dict(os.environ)
    hook_env["HOME"] = str(home)
    hook_env["CLAUDE_PLUGIN_ROOT"] = str(_REPO_ROOT / "plugins" / "onex")
    hook_env.pop("ONEX_HOOKS_MASK", None)
    result = subprocess.run(
        ["bash", str(script)],
        input=json.dumps(
            {
                "session_id": "s",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m big"},
                "tool_response": {"stdout": "", "stderr": ""},
            }
        ),
        capture_output=True,
        text=True,
        env=hook_env,
        cwd=str(repo),
        timeout=90,
        check=False,  # the hook's own exit code is the assertion
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", f"must stay silent on stdout, found {result.stdout!r}"

    events = home / ".claude" / "changeset-guard-events" / "events.jsonl"
    assert events.exists(), "changeset guard wrote no events.jsonl above threshold"
    record = json.loads(events.read_text().strip().splitlines()[-1])
    assert record["event"] == "large_changeset"
    assert record["file_count"] == 20, record
    assert record["threshold"] == 15, record


def test_local_capture_carve_out_records_owner_reason_expiry_restoration() -> None:
    """The OMN-17207 carve-out carries its own four-field STANDING-RULE record."""
    description = json.loads(_HOOKS_JSON.read_text()).get("description", "")
    assert "OMN-17207" in description, (
        "hooks.json description must record the local-capture carve-out under "
        "its ticket (OMN-17207)."
    )
    marker = "OMN-17207 carve-out record:"
    assert marker in description, (
        f"The OMN-17207 carve-out must introduce its record with {marker!r}."
    )
    record = description.split(marker, 1)[1]
    for field in ("OWNER", "REASON", "EXPIRY", "RESTORATION"):
        assert field in record, (
            f"The OMN-17207 carve-out record must name {field!r}. Record: {record!r}"
        )
    assert "OMN-17209" in record, (
        "The OMN-17207 record must name OMN-17209 — the bus-egress gate that "
        "these hooks are deliberately kept local-only ahead of."
    )
