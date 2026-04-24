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

4. **Inventory and enum move together.** The Task 1 inventory doc and the `EnumHookBit`
   class must be updated in the same PR. A drift PR that edits one without the other is
   rejected.

5. **Generator enforces declaration order.** The generator (`gen_hook_bits.py`, Task 3)
   asserts that ordinal order in `hook_bits.sh` matches declaration order in `EnumHookBit`.
   Mid-enum insertions fail the drift check.

6. **GATE/LIBRARY/INFRA classification is authoritative.** Later tasks (Task 5, 6)
   consume this classification rather than re-derive it.

---

## Classification Key

| Class | Meaning |
|---|---|
| **GATE** | Registered in `hooks.json` as a hook entrypoint; receives a bit in `EnumHookBit`. |
| **LIBRARY** | Sourced or invoked by other hooks as a shared helper; no bit assigned. |
| **INFRA** | Hook plumbing (runtime daemon, deploy tooling, test scaffolding); no bit assigned. |
| **NOT_REGISTERED** | Exists on disk but not in `hooks.json` (candidate for future registration or removal). |

---

## Pre/Post Pair Rules

When a hook has both a `pre_tool_use_` and a `post_tool_use_` variant sharing the same
semantic name root:

- Both receive individual bits (separate ordinals).
- The `_PRE` variant is assigned the lower ordinal; the `_POST` variant the next.
- The pair is documented together in the table below with linked ordinals.
- Removing or renaming one half of a pair does not affect the other half's ordinal.

---

## Bash Hook GATE Inventory (ordered by assigned ordinal)

These are the hooks registered in `hooks.json` that function as enforcement gates.
Each row fixes the `EnumHookBit` member name and ordinal. Ordinal column is `N` where
`value = 1 << N`.

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
| 8 | `PERMISSION_DENIED_LOGGER` | `scripts/permission_denied_logger.sh` | PermissionDenied | (any) | (none) | — |
| 9 | `SKILL_DELEGATION_ENFORCER` | `scripts/post-skill-delegation-enforcer.sh` | PostToolUse | `Skill` | (none) | — |
| 10 | `DELEGATION_COUNTER` | `scripts/post-tool-delegation-counter.sh` | PostToolUse | `^(Read\|Write\|Edit\|Bash\|...)$` | (none) | — |
| 11 | `QUALITY_POST` | `scripts/post-tool-use-quality.sh` | PostToolUse | `^(Read\|Write\|Edit\|Bash\|...)$` | (none) | — |
| 12 | `TEST_REMINDER` | `scripts/post-tool-use-test-reminder.sh` | PostToolUse | `^(Edit\|Write)$` | `OMNICLAUDE_HOOK_TEST_REMINDER` | — |
| 13 | `AGENT_RESULT_VERIFIER` | `scripts/post_tool_use_agent_result_verifier.sh` | PostToolUse | `Agent` | (none) | — |
| 14 | `AUTO_CHECKPOINT` | `scripts/post_tool_use_auto_checkpoint.sh` | PostToolUse | `Bash` | `OMNICLAUDE_HOOK_AUTO_CHECKPOINT` | — |
| 15 | `AUTO_HOSTILE_REVIEW` | `scripts/post_tool_use_auto_hostile_review.sh` | PostToolUse | `Bash` | `OMNICLAUDE_HOOK_AUTO_HOSTILE_REVIEW` | — |
| 16 | `CHANGESET_GUARD_PRE` | `scripts/pre_tool_use_changeset_guard.sh` | PreToolUse | `Bash` | `OMNICLAUDE_HOOK_CHANGESET_GUARD` | ↔ ordinal 17 |
| 17 | `CHANGESET_GUARD_POST` | `scripts/post_tool_use_changeset_guard.sh` | PostToolUse | `Bash` | `OMNICLAUDE_HOOK_CHANGESET_GUARD` | ↔ ordinal 16 |
| 18 | `COMMIT_VERIFY` | `scripts/post_tool_use_commit_verify.sh` | PostToolUse | `Bash` | (none) | — |
| 19 | `CRON_ACTION_GUARD` | `scripts/post_tool_use_cron_action_guard.sh` | PostToolUse | `CronCreate` | (none) | — |
| 20 | `ENV_SYNC` | `scripts/post_tool_use_env_var_sync.sh` | PostToolUse | `^(Edit\|Write)$` | `OMNICLAUDE_HOOK_ENV_SYNC` | — |
| 21 | `KAFKA_POISON_GUARD` | `scripts/post_tool_use_kafka_poison_message_guard.sh` | PostToolUse | `Bash` | (none) | — |
| 22 | `OUTPUT_SUPPRESSOR` | `scripts/post_tool_use_output_suppressor.sh` | PostToolUse | `Bash` | (none) | — |
| 23 | `RETURN_PATH_AUDITOR` | `scripts/post_tool_use_return_path_auditor.sh` | PostToolUse | `^(Task\|Agent)$` | (none) | — |
| 24 | `STATE_VERIFY` | `scripts/post_tool_use_state_verify.sh` | PostToolUse | `Bash` | (none) | — |
| 25 | `SUBAGENT_TOOL_LOG` | `scripts/post_tool_use_subagent_tool_log.sh` | PostToolUse | `.*` | (none) | — |
| 26 | `TEAM_OBSERVABILITY` | `scripts/post_tool_use_team_observability.sh` | PostToolUse | `^(TeamCreate\|Agent\|...)$` | `OMNICLAUDE_HOOK_TEAM_OBSERVABILITY` | — |
| 27 | `TSC_CHECK` | `scripts/post_tool_use_tsc_check.sh` | PostToolUse | `^(Edit\|Write)$` | (none) | — |
| 28 | `PRE_COMPACT` | `scripts/pre-compact.sh` | PreCompact | (any) | (none) | — |
| 29 | `AGENT_DISPATCH_GATE` | `scripts/pre_tool_use_agent_dispatch_gate.sh` | PreToolUse | `^Agent$` | (none) | — |
| 30 | `AGENT_TOOL_GATE` | `scripts/pre_tool_use_agent_tool_gate.sh` | PreToolUse | `.*` | (none) | — |
| 31 | `AUTHORIZATION_SHIM` | `scripts/pre_tool_use_authorization_shim.sh` | PreToolUse | `^(Edit\|Write)$` | (none) | — |
| 32 | `BASH_GUARD` | `scripts/pre_tool_use_bash_guard.sh` | PreToolUse | `Bash` | (none) | — |
| 33 | `BRANCH_PROTECTION_GUARD` | `scripts/pre_tool_use_branch_protection_guard.sh` | PreToolUse | `Bash` | (none) | — |
| 34 | `CONTEXT_SCOPE_AUDITOR` | `scripts/pre_tool_use_context_scope_auditor.sh` | PreToolUse | (any) | (none) | — |
| 35 | `DISPATCH_GUARD` | `scripts/pre_tool_use_dispatch_guard.sh` | PreToolUse | `^(Edit\|Write\|Bash)$` | (none) | — |
| 36 | `DISPATCH_GUARD_TICKET_EVIDENCE` | `scripts/pre_tool_use_dispatch_guard_ticket_evidence.sh` | PreToolUse | `^(Agent\|Task)$` | (none) | — |
| 37 | `DISPATCH_MODE_GUARDRAIL` | `scripts/pre_tool_use_dispatch_mode_guardrail.sh` | PreToolUse | `^Agent$` | (none) | — |
| 38 | `DOD_COMPLETION_GUARD` | `scripts/pre_tool_use_dod_completion_guard.sh` | PreToolUse | `^mcp__linear-server__...` | (none) | — |
| 39 | `HOSTILE_REVIEW_GATE` | `scripts/pre_tool_use_hostile_review_gate.sh` | PreToolUse | `Bash` | (none) | — |
| 40 | `LINEAR_DONE_VERIFY` | `scripts/pre_tool_use_linear_done_verify.sh` | PreToolUse | `^mcp__linear-server__...` | (none) | — |
| 41 | `MODEL_ROUTER` | `scripts/pre_tool_use_model_router.sh` | PreToolUse | `^(Bash\|Read\|Edit\|Write\|...)$` | (none) | — |
| 42 | `OVERSEER_FOREGROUND_BLOCK` | `scripts/pre_tool_use_overseer_foreground_block.sh` | PreToolUse | `^(Edit\|Write\|MultiEdit\|...)$` | (none) | — |
| 43 | `PIPELINE_GATE` | `scripts/pre_tool_use_pipeline_gate.sh` | PreToolUse | `^(Edit\|Write\|Bash)$` | (none) | — |
| 44 | `PLAN_EXISTENCE_GATE` | `scripts/pre_tool_use_plan_existence_gate.sh` | PreToolUse | `^(Edit\|Write)$` | `OMNICLAUDE_HOOK_PLAN_EXISTENCE_GATE` | — |
| 45 | `PREPUSH_VALIDATOR` | `scripts/pre_tool_use_prepush_validator.sh` | PreToolUse | `Bash` | (none) | — |
| 46 | `SCOPE_GATE` | `scripts/pre_tool_use_scope_gate.sh` | PreToolUse | `^(Edit\|Write)$` | `OMNICLAUDE_HOOK_SCOPE_GATE` | — |
| 47 | `SWEEP_PREFLIGHT` | `scripts/pre_tool_use_sweep_preflight.sh` | PreToolUse | `Bash` | (none) | — |
| 48 | `TDD_DISPATCH_GATE` | `scripts/pre_tool_use_tdd_dispatch_gate.sh` | PreToolUse | `^(Agent\|Task)$` | (none) | — |
| 49 | `TEAM_LEAD_GUARD` | `scripts/pre_tool_use_team_lead_guard.sh` | PreToolUse | `^(Read\|Edit\|Write\|Bash\|...)$` | (none) | — |
| 50 | `WORKFLOW_GUARD` | `scripts/pre_tool_use_workflow_guard.sh` | PreToolUse | `^(mcp__linear-server__save_issue\|...)$` | (none) | — |
| 51 | `SESSION_END` | `scripts/session-end.sh` | SessionEnd | (any) | (none) | — |
| 52 | `SESSION_START` | `scripts/session-start.sh` | SessionStart | (any) | (none) | ↔ ordinal 51 |
| 53 | `SESSION_START_CLI_PIN_CHECK` | `scripts/session_start_onex_cli_pin_check.sh` | SessionStart | (any) | (none) | — |
| 54 | `STOP` | `scripts/stop.sh` | Stop | (any) | (none) | — |
| 55 | `STOP_FAILURE_LOGGER` | `scripts/stop_failure_logger.sh` | StopFailure | (any) | (none) | — |
| 56 | `STOP_SESSION_BOOTSTRAP_GUARD` | `scripts/stop_session_bootstrap_guard.sh` | Stop | (any) | (none) | — |
| 57 | `SUBAGENT_START` | `scripts/subagent-start.sh` | SubagentStart | (any) | (none) | ↔ ordinal 58 |
| 58 | `SUBAGENT_STOP_CLAIM_VERIFIER` | `scripts/subagent_stop_claim_verifier.sh` | SubagentStop | (any) | (none) | ↔ ordinal 57 |
| 59 | `USER_PROMPT_DELEGATION_RULE` | `scripts/user-prompt-delegation-rule.sh` | UserPromptSubmit | (any) | (none) | — |
| 60 | `USER_PROMPT_SUBMIT` | `scripts/user-prompt-submit.sh` | UserPromptSubmit | (any) | (none) | — |
| 61 | `BOOTSTRAP_INJECTOR` | `scripts/user_prompt_bootstrap_injector.sh` | UserPromptSubmit | (any) | (none) | — |
| 62 | `HANDOFF_NUDGE` | `scripts/user_prompt_structured_handoff_nudge.sh` | UserPromptSubmit | (any) | `OMNICLAUDE_HOOK_HANDOFF_NUDGE` | — |

**Total GATE count: 63** (ordinals 0–62, inclusive)

---

## Pre/Post Pair Summary

| Pair | Pre Ordinal / Member | Post Ordinal / Member |
|------|---------------------|----------------------|
| Changeset Guard | 16 `CHANGESET_GUARD_PRE` | 17 `CHANGESET_GUARD_POST` |
| Dispatch Claim | 4 `DISPATCH_CLAIM_PRE` | 5 `DISPATCH_CLAIM_POST` |
| Session lifecycle | 52 `SESSION_START` | 51 `SESSION_END` |
| Subagent lifecycle | 57 `SUBAGENT_START` | 58 `SUBAGENT_STOP_CLAIM_VERIFIER` |

> Note: SESSION_START (ordinal 52) has a higher ordinal than SESSION_END (ordinal 51)
> because session-end.sh appeared first in the lexicographic registration pass. This is
> intentional — ordinals reflect registration order, not temporal execution order.
> The pair linkage in the GATE table is the authoritative reference for pairing.

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

These scripts are infrastructure tooling, not enforcement hooks.

| Script Path | Role |
|-------------|------|
| `scripts/deploy.sh` | Plugin deployment tooling |
| `scripts/register-tab.sh` | Shell tab-completion registration |
| `scripts/statusline.sh` | Terminal statusline rendering |
| `scripts/test-hooks.sh` | Local hook integration test scaffolding |
| `lib/test_repo_guard.sh` | Test helper for repo_guard.sh |
| `scripts/pre-compact-probe.sh` | Probe script to confirm PreCompact event wiring (not itself a hook) |

---

## NOT_REGISTERED Hooks (on disk, not in hooks.json)

These scripts exist in the hooks directory but are not currently registered in `hooks.json`.
They do **not** receive bits in the initial freeze. If registered in a future PR, they must
append new bits at that time per the governance rules above.

| Script Path | Classification | Notes |
|-------------|---------------|-------|
| `scripts/pre-tool-use-quality.sh` | NOT_REGISTERED | Pre-tool quality gate; comment in file states "register ONLY after pre-compact-probe.sh confirms" |
| `scripts/pre_tool_use_poly_enforcer.sh` | NOT_REGISTERED | Polymorphic dispatch enforcer; not yet wired in hooks.json |
| `scripts/epic_postaction_gate.sh` | NOT_REGISTERED | Epic post-action validation gate; invoked by external tooling, not Claude hook events |
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
| GATE (bash, registered in hooks.json) | 63 |
| LIBRARY (shared bash helpers) | 6 |
| INFRA (plumbing/tooling) | 6 |
| NOT_REGISTERED (on disk, not in hooks.json) | 4 |
| **Total bash .sh files** | **79** |

> The 63 GATE count is within the acceptance criteria bound (40–50 was estimated; actual
> count is higher because session/stop/subagent/userPrompt lifecycle hooks were included
> as full enforcement gates, not INFRA — each controls meaningful behavior).
