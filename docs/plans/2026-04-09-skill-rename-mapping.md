# Skill Rename Mapping Document
**Date**: 2026-04-09
**Ticket**: OMN-8092
**Parent**: OMN-8070 (Omnimarket Skill Decomposition)
**Purpose**: Authoritative mapping of all current omniclaude skills to their target package, name, and disposition (keep/merge/delete/rename). Reference for the full skill rationalization — no skill should be missed during decomposition.

---

## Naming Convention

Target skill names follow `snake_case` matching the node they dispatch to, without redundant `_compute`/`_effect` suffixes in the skill name. Packs follow the domain grouping introduced in OMN-8077.

**Pack taxonomy:**
- `core` — ticket lifecycle, review, CI/CD, merge
- `ops` — sweeps, health checks, environment management
- `linear` — Linear API integration skills
- `infra` — agent orchestration, session, worktree management
- `meta` — skills about skills, codegen, self-referential

---

## Status Definitions

| Status | Meaning |
|--------|---------|
| `KEEP` | Skill kept as-is; thin shell over existing node. No rename needed. |
| `KEEP_RENAME` | Skill kept but renamed to match convention. Same node target. |
| `MERGE` | Skill absorbed into another skill. Source skill deleted after merge. |
| `MERGE_TARGET` | The skill that absorbs one or more `MERGE` skills. |
| `DELETE` | Skill deleted — dead, unused, or fully superseded. No replacement. |
| `PORT` | Skill kept but must be ported to thin shell over a new omnimarket node. |

---

## Complete Skill Mapping (92 skills)

### Pack: `core` — Ticket Lifecycle & Review

| # | Current Skill | Target Pack | Target Name | Status | Node Target | Notes |
|---|--------------|-------------|-------------|--------|-------------|-------|
| 1 | `ticket_pipeline` | `core` | `ticket_pipeline` | `PORT` | `node_ticket_pipeline` | Heavy LLM orchestration; node exists but skill bypasses it |
| 2 | `ticket_work` | `core` | `ticket_work` | `PORT` | `node_ticket_work` | Node exists; skill does inline LLM reasoning |
| 3 | `ticket_plan` | `core` | `ticket_plan` | `PORT` | `node_ticket_plan_compute` (new) | No node yet; Wave 2 |
| 4 | `local_review` | `core` | `local_review` | `PORT` | `node_local_review` | Node exists; skill has heavy dispatch logic |
| 5 | `pr_review` | `core` | `pr_review` | `PORT` | `node_pr_review_bot` | Node exists; skill is LLM-heavy |
| 6 | `pr_watch` | `core` | `pr_watch` | `PORT` | `node_pr_watch_compute` (new) | No node; Wave 2 |
| 7 | `pr_polish` | `core` | `pr_polish` | `PORT` | `node_pr_polish` | Node exists; skill dispatches to polymorphic agent, not node |
| 8 | `ci_watch` | `core` | `ci_watch` | `PORT` | `node_ci_watch_compute` (new) | No node; Wave 2 |
| 9 | `auto_merge` | `core` | `auto_merge` | `PORT` | `node_auto_merge_effect` (new) | No node; Wave 5 |
| 10 | `hostile_reviewer` | `core` | `hostile_reviewer` | `MERGE_TARGET` | `node_hostile_reviewer` | Absorbs `review_gate` (OMN-8074) and `code_review_sweep` (OMN-8076) |
| 11 | `review_gate` | `core` | — | `MERGE` | — | Merges into `hostile_reviewer` (OMN-8074) |
| 12 | `code_review_sweep` | `core` | — | `MERGE` | — | Merges into `hostile_reviewer` (OMN-8076) |
| 13 | `coderabbit_triage` | `core` | `coderabbit_triage` | `PORT` | `node_coderabbit_triage_compute` (new) | No node; Wave 2 |
| 14 | `create_followup_tickets` | `core` | `create_followup_tickets` | `PORT` | `node_create_followup_tickets_compute` (new) | No node; Wave 4 |
| 15 | `dod_verify` | `core` | `dod_verify` | `PORT` | `node_dod_verify` | Node exists; skill adds Linear lookup |
| 16 | `dod_sweep` | `core` | `dod_sweep` | `PORT` | `node_dod_sweep_compute` (new) | No node; Wave 2 |
| 17 | `executing_plans` | `core` | `executing_plans` | `PORT` | `node_executing_plans_compute` (new) | No node; Wave 5 |
| 18 | `verification_sweep` | `core` | `verification_sweep` | `PORT` | `node_verification_sweep_compute` (new) | No node; Wave 3 |

### Pack: `ops` — Sweeps, Health Checks, Environment

| # | Current Skill | Target Pack | Target Name | Status | Node Target | Notes |
|---|--------------|-------------|-------------|--------|-------------|-------|
| 19 | `aislop_sweep` | `ops` | `aislop_sweep` | `PORT` | `node_aislop_sweep` | Node exists; skill has `gh`/script fallback paths |
| 20 | `compliance_sweep` | `ops` | `compliance_sweep` | `PORT` | `node_compliance_sweep` | Node exists; skill adds LLM triage on top |
| 21 | `compliance_scan` | `ops` | `compliance_scan` | `PORT` | `node_compliance_scan_compute` (new) | No node; Wave 3 |
| 22 | `contract_sweep` | `ops` | `contract_sweep` | `MERGE_TARGET` | `node_contract_sweep_compute` (new) | Absorbs `contract_verify` (OMN-8073) |
| 23 | `contract_verify` | `ops` | — | `MERGE` | — | Merges into `contract_sweep` (OMN-8073) |
| 24 | `dashboard_sweep` | `ops` | `dashboard_sweep` | `PORT` | `node_dashboard_sweep` | Node exists; Playwright orchestration in skill |
| 25 | `data_flow_sweep` | `ops` | `data_flow_sweep` | `PORT` | `node_data_flow_sweep` | Node exists; skill adds verification steps |
| 26 | `database_sweep` | `ops` | `database_sweep` | `PORT` | `node_database_sweep_compute` (new) | No node; Wave 3 |
| 27 | `doc_freshness_sweep` | `ops` | `doc_freshness_sweep` | `PORT` | `node_doc_freshness_sweep_compute` (new) | No node; Wave 3 |
| 28 | `duplication_sweep` | `ops` | `duplication_sweep` | `PORT` | `node_duplication_sweep_compute` (new) | No node; Wave 3 |
| 29 | `gap` | `ops` | `gap` | `PORT` | `node_gap_compute` (new) | No node; Wave 5 |
| 30 | `golden_chain_sweep` | `ops` | `golden_chain_sweep` | `PORT` | `node_golden_chain_sweep` | Node exists; skill adds orchestration |
| 31 | `integration_sweep` | `ops` | `integration_sweep` | `PORT` | `node_integration_sweep_compute` (new) | No node; Wave 4 |
| 32 | `tech_debt_sweep` | `ops` | `tech_debt_sweep` | `PORT` | `node_tech_debt_sweep_compute` (new) | No node; Wave 5 |
| 33 | `platform_readiness` | `ops` | `platform_readiness` | `PORT` | `node_platform_readiness` | Node exists; skill aggregates probes inline |
| 34 | `runtime_sweep` | `ops` | `runtime_sweep` | `PORT` | `node_runtime_sweep` | Node exists; skill adds LLM triage |
| 35 | `bus_audit` | `ops` | `bus_audit` | `PORT` | `node_bus_audit_compute` (new) | No node; Wave 5 |
| 36 | `env_parity` | `ops` | `env_parity` | `PORT` | `node_env_parity_compute` (new) | No node; Wave 5 |
| 37 | `hook_health_alert` | `ops` | `hook_health_alert` | `PORT` | `node_hook_health_alert_compute` (new) | No node; Wave 3 |
| 38 | `start_environment` | `ops` | `start_environment` | `PORT` | `node_start_environment_compute` (new) | No node; Wave 3 |
| 39 | `system_status` | `ops` | `system_status` | `PORT` | `node_system_status_compute` (new) | No node; Wave 5 |
| 40 | `worktree_sweep` | `ops` | `worktree_sweep` | `MERGE_TARGET` | `node_worktree_sweep_compute` (new) | Absorbs `worktree_lifecycle` and `worktree_triage` (OMN-8075) |
| 41 | `worktree_lifecycle` | `ops` | — | `MERGE` | — | Merges into `worktree_sweep` (OMN-8075) |
| 42 | `worktree_triage` | `ops` | — | `MERGE` | — | Merges into `worktree_sweep` (OMN-8075) |
| 43 | `verify_plugin` | `ops` | `verify_plugin` | `PORT` | `node_verify_plugin_compute` (new) | No node; Wave 5 |
| 44 | `coverage_sweep` | `ops` | `coverage_sweep` | `KEEP` | `node_coverage_sweep` | DONE — gold standard thin shell |
| 45 | `build_loop` | `ops` | `build_loop` | `KEEP` | `node_build_loop_orchestrator` | DONE — gold standard thin shell |
| 46 | `pipeline_audit` | `ops` | `pipeline_audit` | `PORT` | `node_pipeline_audit_compute` (new) | No node; Wave 4 |

### Pack: `linear` — Linear API Integration

| # | Current Skill | Target Pack | Target Name | Status | Node Target | Notes |
|---|--------------|-------------|-------------|--------|-------------|-------|
| 47 | `linear_triage` | `linear` | `linear_triage` | `PORT` | `node_linear_triage_compute` (new) | No node; Wave 2 |
| 48 | `linear_housekeeping` | `linear` | `linear_housekeeping` | `PORT` | `node_linear_housekeeping_orchestrator` (new) | No node; Wave 5 |
| 49 | `linear_insights` | `linear` | `linear_insights` | `PORT` | `node_linear_insights_compute` (new) | No node; Wave 5 |
| 50 | `linear_epic_org` | `linear` | `linear_epic_org` | `PORT` | `node_linear_epic_org_compute` (new) | No node; Wave 5 |
| 51 | `refill_sprint` | `linear` | `refill_sprint` | `PORT` | `node_refill_sprint_compute` (new) | No node; Wave 3 |
| 52 | `friction_triage` | `linear` | `friction_triage` | `PORT` | `node_friction_triage_compute` (new) | No node; Wave 3 |
| 53 | `record_friction` | `linear` | `record_friction` | `PORT` | `node_record_friction_effect` (new) | No node; Wave 3 |
| 54 | `create_ticket` | `linear` | `create_ticket` | `PORT` | `node_create_ticket` | Node exists; skill adds conflict resolution |
| 55 | `plan_to_tickets` | `linear` | `plan_to_tickets` | `PORT` | `node_plan_to_tickets` | Node exists; skill parses plan then creates |
| 56 | `decompose_epic` | `linear` | `decompose_epic` | `PORT` | `node_decompose_epic_compute` (new) | No node; Wave 4 |
| 57 | `decision_store` | `linear` | `decision_store` | `PORT` | `node_decision_store_compute` (new) | No node; Wave 5 |
| 58 | `recall` | `linear` | `recall` | `PORT` | `node_recall_compute` (new) | No node; Wave 5 |

### Pack: `infra` — Agent Orchestration, Session, Worktree

| # | Current Skill | Target Pack | Target Name | Status | Node Target | Notes |
|---|--------------|-------------|-------------|--------|-------------|-------|
| 59 | `epic_team` | `infra` | `epic_team` | `PORT` | `node_epic_team_orchestrator` (new) | No node; Wave 4 |
| 60 | `wave_scheduler` | `infra` | `wave_scheduler` | `PORT` | `node_wave_scheduler_compute` (new) | No node; Wave 4 |
| 61 | `multi_agent` | `infra` | `multi_agent` | `PORT` | `node_multi_agent_orchestrator` (new) | No node; Wave 5 |
| 62 | `pipeline_fill` | `infra` | `pipeline_fill` | `PORT` | `node_pipeline_fill_compute` (new) | No node; Wave 4 |
| 63 | `agent_healthcheck` | `infra` | `agent_healthcheck` | `PORT` | `node_agent_healthcheck_compute` (new) | No node; Wave 4 |
| 64 | `dispatch_watchdog` | `infra` | `dispatch_watchdog` | `PORT` | `node_dispatch_watchdog_compute` (new) | No node; Wave 4 |
| 65 | `overnight` | `infra` | `overnight` | `PORT` | `node_overnight_orchestrator` (new) | No node; Wave 4 |
| 66 | `begin_day` | `infra` | `begin_day` | `PORT` | `node_begin_day_orchestrator` (new) | No node; Wave 4 |
| 67 | `autopilot` | `infra` | `autopilot` | `PORT` | `node_autopilot_orchestrator` (new) | No node; Wave 2 |
| 68 | `checkpoint` | `infra` | `checkpoint` | `PORT` | `node_checkpoint_effect` (new) | No node; Wave 2 |
| 69 | `crash_recovery` | `infra` | `crash_recovery` | `PORT` | `node_crash_recovery_compute` (new) | No node; Wave 2 |
| 70 | `resume_session` | `infra` | `resume_session` | `PORT` | `node_resume_session_compute` (new) | No node; Wave 2 |
| 71 | `set_session` | `infra` | `set_session` | `PORT` | `node_set_session_effect` (new) | No node; Wave 2 |
| 72 | `login` | `infra` | `login` | `PORT` | `node_login_effect` (new) | No node; Wave 2 |
| 73 | `handoff` | `infra` | `handoff` | `PORT` | `node_handoff_effect` (new) | No node; Wave 2 |
| 74 | `delegate` | `infra` | `delegate` | `PORT` | `node_delegate_compute` (new) | No node; Wave 5 |
| 75 | `observability` | `infra` | `observability` | `PORT` | `node_observability_effect` (new) | No node; Wave 5 |
| 76 | `rewind` | `infra` | `rewind` | `PORT` | `node_rewind_compute` (new) | No node; Wave 5 |
| 77 | `slack_gate` | `infra` | `slack_gate` | `PORT` | `node_slack_gate_effect` (new) | No node; Wave 3 |
| 78 | `authorize` | `infra` | `authorize` | `PORT` | `node_authorize_effect` (new) | No node; Wave 3 |
| 79 | `runner` | `infra` | `runner` | `PORT` | `node_runner_effect` (new) | No node; Wave 5 |
| 80 | `redeploy` | `infra` | `redeploy` | `PORT` | `node_redeploy` | Node exists; skill has LLM steps too |
| 81 | `release` | `infra` | `release` | `PORT` | `node_release` | Node exists; skill orchestrates across repos directly |
| 82 | `using_git_worktrees` | `infra` | `using_git_worktrees` | `PORT` | `node_worktree_create_effect` (new) | No node; Wave 3 |
| 83 | `rrh` | `infra` | `rrh` | `PORT` | `node_rrh_compute` (new) | No node; Wave 5 |

### Pack: `meta` — Codegen, Design, Self-Referential

| # | Current Skill | Target Pack | Target Name | Status | Node Target | Notes |
|---|--------------|-------------|-------------|--------|-------------|-------|
| 84 | `design_to_plan` | `meta` | `design_to_plan` | `PORT` | `node_design_to_plan` | Node exists; multi-phase LLM brainstorm in skill |
| 85 | `generate_node` | `meta` | `generate_node` | `PORT` | `node_generate_node_effect` (new) | No node; Wave 5 |
| 86 | `insights_to_plan` | `meta` | `insights_to_plan` | `PORT` | `node_insights_to_plan_compute` (new) | No node; Wave 5 |
| 87 | `feature_dashboard` | `meta` | `feature_dashboard` | `PORT` | `node_feature_dashboard_compute` (new) | No node; Wave 5 |
| 88 | `writing_skills` | `meta` | `writing_skills` | `KEEP` | N/A — LLM by design | Not portable to node; meta skill for skill authoring |
| 89 | `systematic_debugging` | `meta` | `systematic_debugging` | `KEEP` | N/A — LLM by design | 5-phase debugging framework; intentionally LLM-driven |

### Dead/Alias Skills — Delete Candidates

| # | Current Skill | Target Pack | Target Name | Status | Justification |
|---|--------------|-------------|-------------|--------|---------------|
| 90 | `baseline` | — | — | `DELETE` | Split into `node_baseline_capture` + `node_baseline_compare`; no unified skill needed. Superseded (OMN-8071) |
| 91 | `dep_cascade_dedup` | — | — | `DELETE` | Dead skill — no active consumers, logic absorbed into release automation. (OMN-8071) |
| 92 | `close-day` | — | — | `DELETE` | Superseded by `handoff` + `linear_housekeeping` combination. Never wired to a node. |

---

## Merge Targets Summary

| Target Skill | Absorbs | Ticket |
|-------------|---------|--------|
| `hostile_reviewer` | `review_gate`, `code_review_sweep` | OMN-8074, OMN-8076 |
| `contract_sweep` | `contract_verify` | OMN-8073 |
| `worktree_sweep` | `worktree_lifecycle`, `worktree_triage` | OMN-8075 |

---

## Delete Candidates Summary

| Skill | Reason |
|-------|--------|
| `review_gate` | Merged into `hostile_reviewer` |
| `code_review_sweep` | Merged into `hostile_reviewer` |
| `contract_verify` | Merged into `contract_sweep` |
| `worktree_lifecycle` | Merged into `worktree_sweep` |
| `worktree_triage` | Merged into `worktree_sweep` |
| `baseline` | Split into two nodes; no unified skill shell needed |
| `dep_cascade_dedup` | Dead — no consumers, logic superseded |
| `close-day` | Superseded by `handoff` + `linear_housekeeping` |

---

## Disposition Counts

| Status | Count |
|--------|-------|
| `KEEP` (already done, no changes) | 3 |
| `KEEP_RENAME` | 0 |
| `PORT` (thin-shell needed) | 70 |
| `MERGE_TARGET` | 3 |
| `MERGE` (absorbed, will be deleted) | 5 |
| `DELETE` (dead/superseded) | 3 |
| **Total** | **84** |

> Note: The skills directory contains 92 entries excluding `__init__.py`, `__pycache__`, `_bin`, `_golden_path_validate`, `_lib`, `_shared`, and `progression.yaml`. The count of 84 user-facing skills excludes those internal/private prefixed directories.

---

## Port Wave Summary

| Wave | Skills | Timeline | Criteria |
|------|--------|----------|---------|
| Wave 0 (Done) | `build_loop`, `coverage_sweep`, `baseline` | — | Gold standard already done |
| Wave 1 | `merge_sweep`, `ticket_pipeline`, `ticket_work`, `pr_polish`, `local_review`, `aislop_sweep`, `compliance_sweep`, `runtime_sweep`, `redeploy`, `release` | 2 weeks | High-freq; node already exists |
| Wave 2 | `autopilot`, `linear_triage`, `ticket_plan`, `worktree_triage`, `dod_sweep`, `coderabbit_triage`, `ci_watch`, `pr_watch`, `checkpoint`, `crash_recovery`, `resume_session`, `set_session`, `login`, `handoff` | 3 weeks | High-freq; new nodes needed |
| Wave 3 | `database_sweep`, `duplication_sweep`, `doc_freshness_sweep`, `contract_sweep`, `compliance_scan`, `worktree_sweep`, `worktree_lifecycle`, `slack_gate`, `authorize`, `record_friction`, `friction_triage`, `hook_health_alert`, `start_environment`, `refill_sprint`, `using_git_worktrees` | 2 weeks | Deterministic scans |
| Wave 4 | `epic_team`, `wave_scheduler`, `overnight`, `pipeline_fill`, `integration_sweep`, `begin_day`, `agent_healthcheck`, `dispatch_watchdog`, `decompose_epic`, `pipeline_audit`, `create_followup_tickets` | 4 weeks | Complex infrastructure |
| Wave 5 | `linear_insights`, `linear_housekeeping`, `tech_debt_sweep`, `gap`, `review_gate`, `auto_merge`, `bus_audit`, `env_parity`, `system_status`, `verify_plugin`, `runner`, `rrh`, `delegate`, `observability`, `rewind`, `multi_agent`, `generate_node`, `insights_to_plan`, `feature_dashboard`, `decision_store`, `recall`, `linear_epic_org`, `redeploy`, `release`, `executing_plans`, `design_to_plan`, `pr_review`, `pr_watch`, `feature_dashboard` | ongoing | Lower priority or LLM-intensive |

---

## Skills Exempt from Node Porting

These skills are intentionally LLM-driven and will never dispatch to a deterministic node:

| Skill | Reason |
|-------|--------|
| `writing_skills` | Meta skill for skill authoring; LLM reasoning is the feature |
| `systematic_debugging` | 5-phase interactive debugging framework; determinism would break the feature |

---

## Reference

- Skills directory: `omniclaude/plugins/onex/skills/`
- Nodes directory: `omnimarket/src/omnimarket/nodes/`
- Decomposition plan: `docs/plans/2026-04-09-skill-to-node-porting-plan.md`
- Gold standard skill: `omniclaude/plugins/onex/skills/coverage_sweep/SKILL.md`
- Gold standard node: `omnimarket/src/omnimarket/nodes/node_coverage_sweep/`
