# Hook Bitmask Bit-Governance Freeze Inventory

> **OMN-9610 — Append-only governance freeze. 2026-04-24.**
>
> This document is the source of truth for the initial ordinal assignment of every
> `EnumHookBit` member. Once published, the rules below are permanent policy.
> **Do not edit rows already committed here** — tombstone and append instead.

---

## Governance Rules

These rules apply to every future change to `EnumHookBit` and to this document.
They become effective the moment this document is merged.

1. **Append-only ordinals.** New hooks append to the end of `EnumHookBit` — never
   insert mid-enum. Bit ordinals (the `1 << N` value) are stable forever.

2. **Tombstones for removals.** Removed hooks keep a tombstone entry. The ordinal is
   reserved; the name becomes `_RESERVED_<FORMER_NAME>`. Ordinals are never reused.

3. **Renames append.** A renamed hook appends a new bit with the new name. The old bit
   becomes tombstoned per rule 2. There is no in-place rename.

4. **Inventory and enum move together (post-bootstrap).** After this initial bootstrap
   PR, every subsequent PR that edits either the `EnumHookBit` class or this inventory
   doc must edit both in the same PR. A PR that edits one without the other is rejected.
   This rule does not apply to this PR — it *is* the bootstrap.

5. **Generator enforces declaration order.** The generator (`gen_hook_bits.py`, Task 3)
   asserts that ordinal order in `hook_bits.sh` matches declaration order in `EnumHookBit`.
   Mid-enum insertions fail the drift check.

6. **GATE/LIBRARY/INFRA classification is authoritative.** Later tasks (Task 5, 6)
   consume this classification rather than re-derive it.

7. **Headroom reservation.** The initial freeze uses ordinals 0–57 (58 bits). Ordinals
   58–62 are intentionally unassigned. Ordinal 63 (`1 << 63`) is the sign bit in a 64-bit
   signed integer and must never be used. Any reclassification that would push the enum
   past ordinal 62 requires an architecture review before proceeding.

---

## Classification Key

| Class | Meaning |
|---|---|
| **GATE** | Registered in `hooks.json`; actively blocks or enforces (can exit non-zero or inject content); receives a bit in `EnumHookBit`. |
| **LIBRARY** | Sourced or invoked by other hooks as a shared helper; no bit assigned. |
| **INFRA** | Registered in `hooks.json` but observe-only (never block, never inject, always exit 0); or hook-runtime plumbing; no bit assigned. |
| **NOT_REGISTERED** | Exists on disk but not in `hooks.json`; no bit assigned. |

> **GATE vs INFRA decision rule for registered hooks:** If the script can exit with a
> non-zero code that surfaces to the user, OR injects content into the Claude context
> stream, it is a GATE. If it only writes to disk/logs and always exits 0, it is INFRA.

---

## Pre/Post Pair Rules

When a hook has both a `pre_tool_use_` and a `post_tool_use_` variant sharing the same
semantic name root:

- Both receive individual bits (separate ordinals).
- The `_PRE` variant is assigned the **lower** ordinal; the `_POST` variant the **next** ordinal.
- The pair is documented together in the table below with linked ordinals.
- Removing or renaming one half of a pair does not affect the other half's ordinal.

Session and subagent lifecycle hooks follow the same rule: Start < End in ordinal order.

---

## Bash Hook GATE Inventory (ordered by assigned ordinal)

These are the hooks registered in `hooks.json` that function as enforcement gates
(can block or inject). Each row fixes the `EnumHookBit` member name and ordinal.
Ordinal column is `N` where `value = 1 << N`.

| Ordinal | Enum Member Name | Script Path (relative to `plugins/onex/hooks/`) | Event Type | Matcher | Has Existing Env Flag | Pre/Post Pair |
|---------|-----------------|------------------------------------------------|------------|---------|----------------------|---------------|
| 0 | `CI_REMINDER` | `post-tool-use-ci-reminder.sh` | PostToolUse | `Bash` | `OMNICLAUDE_HOOK_CI_REMINDER` | — |
| 1 | `RUFF_FIX` | `post-tool-use-ruff.sh` | PostToolUse | `^(Edit\|Write)$` | `OMNICLAUDE_HOOK_RUFF_FIX` | — |
| 2 | `CONVENTION_INJECTOR` | `pre_tool_use_convention_injector.sh` | PreToolUse | `^(Edit\|Write)$` | (none) | — |
| 3 | `FILE_PATH_CONVENTION` | `scripts/file-path-convention-inject.sh` | PreToolUse | `^(Edit\|Write)$` | (none) | — |
| 4 | `DISPATCH_CLAIM_PRE` | `scripts/hook_dispatch_claim_pretool.sh` | PreToolUse | `^(Agent\|Bash)$` | (none) | ↔ ordinal 5 |
| 5 | `DISPATCH_CLAIM_POST` | `scripts/hook_dispatch_claim_posttool.sh` | PostToolUse | `^(Agent\|Bash)$` | (none) | ↔ ordinal 4 |
| 6 | `IDLE_RATELIMIT` | `scripts/hook_idle_notification_ratelimit.sh` | PreToolUse | `^SendMessage$` | (none) | — |
| 7 | `VERIFIER_ROLE_GUARD` | `scripts/hook_verifier_role_guard.sh` | PreToolUse | `^Agent$` | (none) | — |
| 8 | `SKILL_DELEGATION_ENFORCER` | `scripts/post-skill-delegation-enforcer.sh` | PostToolUse | `Skill` | (none) | — |
| 9 | `DELEGATION_COUNTER` | `scripts/post-tool-delegation-counter.sh` | PostToolUse | `^(Read\|Write\|Edit\|Bash\|...)$` | (none) | — |
| 10 | `QUALITY_POST` | `scripts/post-tool-use-quality.sh` | PostToolUse | `^(Read\|Write\|Edit\|Bash\|...)$` | (none) | — |
| 11 | `TEST_REMINDER` | `scripts/post-tool-use-test-reminder.sh` | PostToolUse | `^(Edit\|Write)$` | `OMNICLAUDE_HOOK_TEST_REMINDER` | — |
| 12 | `AGENT_RESULT_VERIFIER` | `scripts/post_tool_use_agent_result_verifier.sh` | PostToolUse | `Agent` | (none) | — |
| 13 | `AUTO_CHECKPOINT` | `scripts/post_tool_use_auto_checkpoint.sh` | PostToolUse | `Bash` | `OMNICLAUDE_HOOK_AUTO_CHECKPOINT` | — |
| 14 | `AUTO_HOSTILE_REVIEW` | `scripts/post_tool_use_auto_hostile_review.sh` | PostToolUse | `Bash` | `OMNICLAUDE_HOOK_AUTO_HOSTILE_REVIEW` | — |
| 15 | `CHANGESET_GUARD_PRE` | `scripts/pre_tool_use_changeset_guard.sh` | PreToolUse | `Bash` | `OMNICLAUDE_HOOK_CHANGESET_GUARD` | ↔ ordinal 16 |
| 16 | `CHANGESET_GUARD_POST` | `scripts/post_tool_use_changeset_guard.sh` | PostToolUse | `Bash` | `OMNICLAUDE_HOOK_CHANGESET_GUARD` | ↔ ordinal 15 |
| 17 | `COMMIT_VERIFY` | `scripts/post_tool_use_commit_verify.sh` | PostToolUse | `Bash` | (none) | — |
| 18 | `CRON_ACTION_GUARD` | `scripts/post_tool_use_cron_action_guard.sh` | PostToolUse | `CronCreate` | (none) | — |
| 19 | `ENV_SYNC` | `scripts/post_tool_use_env_var_sync.sh` | PostToolUse | `^(Edit\|Write)$` | `OMNICLAUDE_HOOK_ENV_SYNC` | — |
| 20 | `KAFKA_POISON_GUARD` | `scripts/post_tool_use_kafka_poison_message_guard.sh` | PostToolUse | `Bash` | (none) | — |
| 21 | `OUTPUT_SUPPRESSOR` | `scripts/post_tool_use_output_suppressor.sh` | PostToolUse | `Bash` | (none) | — |
| 22 | `RETURN_PATH_AUDITOR` | `scripts/post_tool_use_return_path_auditor.sh` | PostToolUse | `^(Task\|Agent)$` | (none) | — |
| 23 | `STATE_VERIFY` | `scripts/post_tool_use_state_verify.sh` | PostToolUse | `Bash` | (none) | — |
| 24 | `TEAM_OBSERVABILITY` | `scripts/post_tool_use_team_observability.sh` | PostToolUse | `^(TeamCreate\|Agent\|...)$` | `OMNICLAUDE_HOOK_TEAM_OBSERVABILITY` | — |
| 25 | `TSC_CHECK` | `scripts/post_tool_use_tsc_check.sh` | PostToolUse | `^(Edit\|Write)$` | (none) | — |
| 26 | `PRE_COMPACT` | `scripts/pre-compact.sh` | PreCompact | (any) | (none) | — |
| 27 | `AGENT_DISPATCH_GATE` | `scripts/pre_tool_use_agent_dispatch_gate.sh` | PreToolUse | `^Agent$` | (none) | — |
| 28 | `AGENT_TOOL_GATE` | `scripts/pre_tool_use_agent_tool_gate.sh` | PreToolUse | `.*` | (none) | — |
| 29 | `AUTHORIZATION_SHIM` | `scripts/pre_tool_use_authorization_shim.sh` | PreToolUse | `^(Edit\|Write)$` | (none) | — |
| 30 | `BASH_GUARD` | `scripts/pre_tool_use_bash_guard.sh` | PreToolUse | `Bash` | (none) | — |
| 31 | `BRANCH_PROTECTION_GUARD` | `scripts/pre_tool_use_branch_protection_guard.sh` | PreToolUse | `Bash` | (none) | — |
| 32 | `CONTEXT_SCOPE_AUDITOR` | `scripts/pre_tool_use_context_scope_auditor.sh` | PreToolUse | (any) | (none) | — |
| 33 | `DISPATCH_GUARD` | `scripts/pre_tool_use_dispatch_guard.sh` | PreToolUse | `^(Edit\|Write\|Bash)$` | (none) | — |
| 34 | `DISPATCH_GUARD_TICKET_EVIDENCE` | `scripts/pre_tool_use_dispatch_guard_ticket_evidence.sh` | PreToolUse | `^(Agent\|Task)$` | (none) | — |
| 35 | `DISPATCH_MODE_GUARDRAIL` | `scripts/pre_tool_use_dispatch_mode_guardrail.sh` | PreToolUse | `^Agent$` | (none) | — |
| 36 | `DOD_COMPLETION_GUARD` | `scripts/pre_tool_use_dod_completion_guard.sh` | PreToolUse | `^mcp__linear-server__...` | (none) | — |
| 37 | `HOSTILE_REVIEW_GATE` | `scripts/pre_tool_use_hostile_review_gate.sh` | PreToolUse | `Bash` | (none) | — |
| 38 | `LINEAR_DONE_VERIFY` | `scripts/pre_tool_use_linear_done_verify.sh` | PreToolUse | `^mcp__linear-server__...` | (none) | — |
| 39 | `MODEL_ROUTER` | `scripts/pre_tool_use_model_router.sh` | PreToolUse | `^(Bash\|Read\|Edit\|Write\|...)$` | (none) | — |
| 40 | `OVERSEER_FOREGROUND_BLOCK` | `scripts/pre_tool_use_overseer_foreground_block.sh` | PreToolUse | `^(Edit\|Write\|MultiEdit\|...)$` | (none) | — |
| 41 | `PIPELINE_GATE` | `scripts/pre_tool_use_pipeline_gate.sh` | PreToolUse | `^(Edit\|Write\|Bash)$` | (none) | — |
| 42 | `PLAN_EXISTENCE_GATE` | `scripts/pre_tool_use_plan_existence_gate.sh` | PreToolUse | `^(Edit\|Write)$` | `OMNICLAUDE_HOOK_PLAN_EXISTENCE_GATE` | — |
| 43 | `PREPUSH_VALIDATOR` | `scripts/pre_tool_use_prepush_validator.sh` | PreToolUse | `Bash` | (none) | — |
| 44 | `SCOPE_GATE` | `scripts/pre_tool_use_scope_gate.sh` | PreToolUse | `^(Edit\|Write)$` | `OMNICLAUDE_HOOK_SCOPE_GATE` | — |
| 45 | `SWEEP_PREFLIGHT` | `scripts/pre_tool_use_sweep_preflight.sh` | PreToolUse | `Bash` | (none) | — |
| 46 | `TDD_DISPATCH_GATE` | `scripts/pre_tool_use_tdd_dispatch_gate.sh` | PreToolUse | `^(Agent\|Task)$` | (none) | — |
| 47 | `TEAM_LEAD_GUARD` | `scripts/pre_tool_use_team_lead_guard.sh` | PreToolUse | `^(Read\|Edit\|Write\|Bash\|...)$` | (none) | — |
| 48 | `WORKFLOW_GUARD` | `scripts/pre_tool_use_workflow_guard.sh` | PreToolUse | `^(mcp__linear-server__save_issue\|...)$` | (none) | — |
| 49 | `SESSION_START` | `scripts/session-start.sh` | SessionStart | (any) | (none) | ↔ ordinal 50 |
| 50 | `SESSION_END` | `scripts/session-end.sh` | SessionEnd | (any) | (none) | ↔ ordinal 49 |
| 51 | `SUBAGENT_START` | `scripts/subagent-start.sh` | SubagentStart | (any) | (none) | ↔ ordinal 52 |
| 52 | `SUBAGENT_STOP_CLAIM_VERIFIER` | `scripts/subagent_stop_claim_verifier.sh` | SubagentStop | (any) | (none) | ↔ ordinal 51 |
| 53 | `USER_PROMPT_DELEGATION_RULE` | `scripts/user-prompt-delegation-rule.sh` | UserPromptSubmit | (any) | (none) | — |
| 54 | `USER_PROMPT_SUBMIT` | `scripts/user-prompt-submit.sh` | UserPromptSubmit | (any) | (none) | — |
| 55 | `BOOTSTRAP_INJECTOR` | `scripts/user_prompt_bootstrap_injector.sh` | UserPromptSubmit | (any) | (none) | — |
| 56 | `HANDOFF_NUDGE` | `scripts/user_prompt_structured_handoff_nudge.sh` | UserPromptSubmit | (any) | `OMNICLAUDE_HOOK_HANDOFF_NUDGE` | — |
| 57 | `STOP_SESSION_BOOTSTRAP_GUARD` | `scripts/stop_session_bootstrap_guard.sh` | Stop | (any) | (none) | — |

**Total GATE count: 58** (ordinals 0–57 inclusive). Ordinals 58–62 are unassigned headroom. Ordinal 63 is permanently reserved (sign bit of 64-bit signed integer; must not be used).

---

## Pre/Post Pair Summary

| Pair | Start/Pre Ordinal | End/Post Ordinal |
|------|-------------------|-----------------|
| Changeset Guard | 15 `CHANGESET_GUARD_PRE` | 16 `CHANGESET_GUARD_POST` |
| Dispatch Claim | 4 `DISPATCH_CLAIM_PRE` | 5 `DISPATCH_CLAIM_POST` |
| Session lifecycle | 49 `SESSION_START` | 50 `SESSION_END` |
| Subagent lifecycle | 51 `SUBAGENT_START` | 52 `SUBAGENT_STOP_CLAIM_VERIFIER` |

---

## Reclassified as INFRA (registered in hooks.json, observe-only)

These scripts are registered in `hooks.json` but are observe-only: they never exit
non-zero and never inject content. Disabling them has no enforcement consequence —
only observability loss. They do not receive bits.

| Script Path | Event Type | Reason for INFRA classification |
|-------------|------------|--------------------------------|
| `scripts/permission_denied_logger.sh` | PermissionDenied | Explicitly "non-blocking" in header comment; writes friction YAML only |
| `scripts/post_tool_use_subagent_tool_log.sh` | PostToolUse | Appends JSONL record only; always exits 0; pure telemetry |
| `scripts/stop_failure_logger.sh` | StopFailure | Writes P1 friction YAML only; non-blocking by design (OMN-8873) |
| `scripts/stop.sh` | Stop | Session teardown telemetry; no blocking behavior |
| `scripts/session-end.sh` | SessionEnd | Explicitly "audit-only — NO context injection, NO contract mutation" |
| `scripts/session_start_onex_cli_pin_check.sh` | SessionStart | "Warns only — never blocks" per header comment |

> **Why these 6 are INFRA and not GATE:** A bit that can only be "disabled" is useless
> for an observability-only hook — disabling it reduces visibility without changing
> enforcement posture. The bitmask exists to turn off *enforcement*; telemetry hooks
> belong in a separate observability control plane (future work).

---

## LIBRARY Hooks (sourced-only, no bit)

These scripts are shared helpers sourced by GATE wrappers. They receive no bit in
`EnumHookBit`.

| Script Path | Role |
|-------------|------|
| `scripts/common.sh` | Shared emit/Kafka helpers, Python resolution, mode gate |
| `scripts/error-guard.sh` | Bash error trapping and hook error emission |
| `scripts/hook-runtime-client.sh` | Socket emit client (bash mirror of `emit_client_wrapper.py`) |
| `scripts/onex-paths.sh` | Path resolution helpers (`HOOKS_DIR`, `HOOKS_LIB`, `PYTHON_CMD`) |
| `scripts/delegation-config.sh` | Delegation mode configuration constants |
| `lib/repo_guard.sh` | Repo scope detection helpers |

---

## INFRA Hooks (plumbing/tooling, no bit)

These scripts are infrastructure tooling not registered as hook entrypoints.

| Script Path | Role |
|-------------|------|
| `scripts/deploy.sh` | Plugin deployment tooling |
| `scripts/register-tab.sh` | Shell tab-completion registration |
| `scripts/statusline.sh` | Terminal statusline rendering |
| `scripts/test-hooks.sh` | Local hook integration test scaffolding |
| `lib/test_repo_guard.sh` | Test helper for repo_guard.sh |
| `scripts/pre-compact-probe.sh` | Probe to confirm PreCompact event wiring (not itself a hook) |

---

## NOT_REGISTERED Hooks (on disk, not in hooks.json)

These scripts exist in the hooks directory but are not currently registered in `hooks.json`.
They do **not** receive bits in the initial freeze. If registered in a future PR, they must
append new bits at that time per the governance rules above.

| Script Path | Classification | Notes |
|-------------|---------------|-------|
| `scripts/pre-tool-use-quality.sh` | NOT_REGISTERED | Pre-tool quality gate; comment states "register ONLY after pre-compact-probe.sh confirms" |
| `scripts/pre_tool_use_poly_enforcer.sh` | NOT_REGISTERED | Polymorphic dispatch enforcer; not yet wired in hooks.json |
| `scripts/epic_postaction_gate.sh` | NOT_REGISTERED | Epic post-action gate; invoked by external tooling, not Claude hook events |
| `scripts/epic_preflight_gate.sh` | NOT_REGISTERED | Epic preflight scope check; same — external invocation only |

---

## Python Hook Sub-Inventory (for Task 6)

No Python files are registered as direct entrypoints in `hooks.json`. All hook entrypoints
are bash `.sh` wrappers. Python is used at two layers:

### Python files invoked by bash wrappers (shell-delegated)

These Python files are called from within bash hook wrappers. They are LIBRARY — no bit.

| Python File | Called From | Role |
|-------------|-------------|------|
| `lib/emit_client_wrapper.py` | `scripts/common.sh` | Socket-based Kafka event emit client |
| `lib/file_path_router.py` | `scripts/file-path-convention-inject.sh` | Derives file-path conventions from path pattern |
| `lib/skill_output_suppressor.py` | `scripts/post_tool_use_output_suppressor.sh` | Suppresses skill output in subagent contexts |
| `lib/skill_usage_logger.py` | `scripts/post-tool-use-quality.sh` | Logs skill invocation metadata |
| `lib/pattern_enforcement.py` | `scripts/post-tool-use-quality.sh` | Pattern-match enforcement for quality gate |
| `lib/pattern_advisory_formatter.py` | `scripts/post-tool-use-quality.sh` | Formats advisory messages for pattern violations |
| `lib/hook_error_emitter.py` | `scripts/error-guard.sh` | Emits hook error events to Kafka |
| `scripts/post_tool_use_enforcer.py` | `scripts/post-tool-use-quality.sh` | PostToolUse quality enforcement runner |

### Python files in `lib/` (pure library helpers, not invoked directly)

All remaining `.py` files in `lib/` are pure Python library modules imported by the
files above or by each other. They are LIBRARY — no bit.

Task 6's Python hook retrofit task should target the shell wrapper scripts listed in the
GATE Inventory above — each bash wrapper gains a 3-line gate near the top that calls
`hook_enabled()` against its assigned bit. The Python library files in `lib/` are not
hook entrypoints and are not retrofitted.

---

## Counts Summary

| Class | Count |
|-------|-------|
| GATE (bash, registered in hooks.json, enforcement-capable) | 58 |
| INFRA/observe-only (registered in hooks.json, telemetry only) | 6 |
| LIBRARY (shared bash helpers, not registered) | 6 |
| INFRA (plumbing/tooling, not registered) | 6 |
| NOT_REGISTERED (on disk, not in hooks.json) | 4 |
| **Total bash .sh files** | **80** |

Bit headroom: ordinals 58–62 (5 slots) are unassigned. Ordinal 63 is permanently reserved.
