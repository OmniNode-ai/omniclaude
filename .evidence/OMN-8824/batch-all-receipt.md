# OMN-8824 Migration Receipt — All Batches

**Date**: 2026-04-15
**Branch**: jonah/omn-8824-task-10b-skill-port-fan-out-port-remaining-42-skills-to
**Ticket**: OMN-8824

## Summary

All 45 skill files with `mcp__linear-server__` or `mcp__linear_server__` references were
ported to `tracker.*` DI pattern in a single atomic commit.

## Files Patched (45)

- plugins/onex/skills/_shared/linear-availability-check.md
- plugins/onex/skills/agent_healthcheck/SKILL.md
- plugins/onex/skills/aislop_sweep/SKILL.md
- plugins/onex/skills/auto_merge/SKILL.md
- plugins/onex/skills/compliance_sweep/SKILL.md
- plugins/onex/skills/compliance_sweep/prompt.md
- plugins/onex/skills/coverage_sweep/SKILL.md
- plugins/onex/skills/create_ticket/SKILL.md
- plugins/onex/skills/dashboard_sweep/prompt.md
- plugins/onex/skills/decompose_epic/SKILL.md
- plugins/onex/skills/decompose_epic/prompt.md
- plugins/onex/skills/dod_sweep/SKILL.md
- plugins/onex/skills/dod_sweep/prompt.md
- plugins/onex/skills/env_parity/prompt.md
- plugins/onex/skills/epic_team/SKILL.md
- plugins/onex/skills/epic_team/run.sh
- plugins/onex/skills/executing_plans/SKILL.md
- plugins/onex/skills/feature_dashboard/SKILL.md
- plugins/onex/skills/friction_triage/SKILL.md
- plugins/onex/skills/gap/prompt.md
- plugins/onex/skills/integration_sweep/prompt.md
- plugins/onex/skills/linear_epic_org/SKILL.md
- plugins/onex/skills/linear_insights/SKILL.md
- plugins/onex/skills/linear_insights/deep-dive
- plugins/onex/skills/linear_insights/estimation-accuracy
- plugins/onex/skills/linear_insights/project-status
- plugins/onex/skills/linear_insights/setup
- plugins/onex/skills/linear_insights/suggest-work
- plugins/onex/skills/linear_insights/velocity-estimate
- plugins/onex/skills/linear_triage/SKILL.md
- plugins/onex/skills/local_review/prompt.md
- plugins/onex/skills/merge_sweep/run.sh
- plugins/onex/skills/pipeline_fill/SKILL.md
- plugins/onex/skills/plan_audit/SKILL.md
- plugins/onex/skills/plan_audit/prompt.md
- plugins/onex/skills/plan_to_tickets/SKILL.md
- plugins/onex/skills/pr_watch/prompt.md
- plugins/onex/skills/rrh/SKILL.md
- plugins/onex/skills/runtime_sweep/SKILL.md
- plugins/onex/skills/session/prompt.md
- plugins/onex/skills/tech_debt_sweep/SKILL.md
- plugins/onex/skills/ticket_pipeline/prompt.md
- plugins/onex/skills/ticket_plan/SKILL.md
- plugins/onex/skills/ticket_plan/prompt.md
- plugins/onex/skills/worktree/SKILL.md

## Enforcement Test

```text
tests/skills/test_no_mcp_linear_calls_in_skill_prompts.py::test_no_hardcoded_mcp_linear_in_skill_prompts PASSED
```

## Pre-existing Failure (not introduced by this PR)

`tests/hooks/test_context_injection_api_source.py::TestContextInjectionConfigAPIUrl::test_api_enabled_inferred_false_without_url`
— fails on main before this branch, unrelated to skill prompts.
