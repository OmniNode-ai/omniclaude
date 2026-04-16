---
description: "Functional verification audit of all registered onex skills — classifies by risk tier, invokes read-only skills, greps write skills for stub markers, produces structured per-skill verdicts, and FAILs if any facade/stub is found without a tracked Linear ticket."
version: 1.0.0
mode: full
level: advanced
debug: false
category: workflow
tags:
  - skill-audit
  - quality
  - verification
  - catalog
  - facade-detection
author: OmniClaude Team
composable: false
args:
  - name: --output
    description: "Output path for the audit YAML (default: ${ONEX_STATE_DIR}/skill-audits/<timestamp>.yaml)"
    required: false
  - name: --fail-on-facade
    description: "Exit nonzero if any FACADE/STUB verdict found without a tracked Linear ticket (default: true)"
    required: false
  - name: --skip-invocation
    description: "Skip live invocation of read-only skills — check backing only (default: false)"
    required: false
inputs:
  - name: output
    description: "Override output path for audit YAML"
  - name: fail_on_facade
    description: "Whether to fail if untracked facades are found"
outputs:
  - name: audit_path
    description: "Absolute path to the written audit YAML"
  - name: facade_count
    description: "Number of FACADE/STUB verdicts found"
  - name: exit_code
    description: "0=clean, 1=facade/stub found without Linear ticket"
---

# /onex:skill_functional_audit — Functional Verification Audit

**Skill ID**: `onex:skill_functional_audit`
**Version**: 1.0.0
**Owner**: omniclaude
**Created**: 2026-04-14
**Rationale**: Addresses gap found in skill-catalog-2026-04-14.md — existence checks reported "0 broken" while 3 facades were live.

---

## Why This Skill Exists

The prior `skill-catalog-gap-sweep` checked two things:
1. `SKILL.md` file exists in `plugins/onex/skills/<name>/`
2. Skill is registered in the plugin catalog

It did NOT verify:
- Whether backing `handle()` methods contain `STUB` / `NotImplementedError` markers
- Whether `SKILL.md §Implementation Status` declares phases as in-progress stubs
- Whether pure-instruction skills that describe complex orchestration have any executable backing
- Whether skills claiming node-backed dispatch actually have those nodes at the expected path

**File existence ≠ functional.** This skill closes that gap.

---

## Announce at Start

> "I'm using the skill_functional_audit skill to functionally verify all registered onex skills — checking backing nodes, stub markers, and invocability."

---

## Phase 1: Enumerate Skills

Walk `plugins/onex/skills/` and collect all skill directories (exclude `_shared`, `_lib`, `_bin`, `_golden_path_validate`):

```bash
ls "${ONEX_REGISTRY_ROOT}/omniclaude/plugins/onex/skills/" | \
  grep -v "^_\|__pycache__\|__init__\|progression.yaml\|slack-gate" | sort
```

For each skill directory, verify `SKILL.md` exists. Any missing `SKILL.md` = **BROKEN** verdict immediately.

---

## Phase 2: Classify by Risk Tier

For each skill, classify into one of three tiers based on the skill name and SKILL.md `category`/`tags` fields:

### WRITE/DISPATCH (skip live invocation, check backing)

Skills that create PRs, dispatch agent teams, trigger releases, or write to external systems:

```
epic_team, autopilot, build_loop, release, redeploy, merge_sweep, overnight,
ticket_pipeline, ticket_work, create_ticket, create_followup_tickets,
plan_to_tickets, wave_scheduler, dispatch_worker, coderabbit_triage,
pr_polish, pr_review, pr_review_bot, auto_merge, dep_cascade_dedup,
dashboard_sweep, local_review, refill_sprint, generate_node,
adversarial_pipeline, multi_agent, integration_sweep, linear_epic_org,
linear_housekeeping, start_environment, record_friction, dod_sweep,
friction_triage, pipeline_fill, delegate, design_to_plan, checkpoint,
close-day, runner
```

### INTERACTIVE (skip live invocation, check backing)

Skills requiring interactive session context or that modify session state:

```
session, onboarding, handoff, crash_recovery, begin_day, executing_plans,
resume_session, set_session, login, using_git_worktrees, demo,
systematic_debugging, writing_skills, insights_to_plan, authorize,
worktree, decompose_epic, ticket_plan, rrh
```

### READ-ONLY (invoke if --skip-invocation not set, assert output schema)

Skills that read and report state without writes:

```
aislop_sweep, agent_healthcheck, baseline, bus_audit, ci_watch,
compliance_sweep, contract_sweep, coverage_sweep, data_flow_sweep,
database_sweep, decision_store, dispatch_watchdog, doc_freshness_sweep,
dod_verify, duplication_sweep, env_parity, feature_dashboard, gap,
golden_chain_sweep, hook_health_alert, linear_insights, linear_triage,
observability, pipeline_audit, plan_audit, platform_readiness, pr_watch,
preflight, recall, rewind, runtime_sweep, tech_debt_sweep,
verification_sweep, verify_plugin
```

**Default classification:** If skill name doesn't match above lists, classify as INTERACTIVE (safer — skip invocation).

---

## Phase 3: Backing Node Check (all tiers)

For each skill, determine its backing type:

### 3a. Explicit node-backed skills

Check if a node named `node_<skill_name>` exists at:
- `omnimarket/src/omnimarket/nodes/node_<skill_name>/`
- `omnibase_infra/src/omnibase_infra/nodes/node_<skill_name>/`
- `omniclaude/src/omniclaude/nodes/node_<skill_name_orchestrator>/`

If SKILL.md mentions a specific node name (grep: `Backed by|backing node|node_`), verify that node exists at the stated path.

### 3b. Stub marker scan

For all node-backed skills, scan handler files for stub markers:

```bash
grep -rn "raise NotImplementedError\|pass  # TODO\|# STUB\|STUB:\|Phase.*STUB\|TODO.*Implement" \
  <node_path>/handlers/*.py 2>/dev/null | grep -v __pycache__
```

**Stub marker found = PARTIAL or STUB verdict** (PARTIAL if some phases work, STUB if entire handle() is stubbed).

### 3c. Pure instruction check

If no backing node exists AND SKILL.md describes complex multi-phase orchestration with state management (dispatched.yaml, phase tracking, wave caps), classify as **FACADE** unless the skill is explicitly documented as "pure instruction" / "instruction-only" in its description.

Heuristic for FACADE detection:
- SKILL.md has > 200 lines AND describes stateful orchestration (state files, wave caps, in-flight tracking)
- AND no backing node named `node_<skill_name>` exists
- AND no `run.py` or executable script exists in the skill directory

---

## Phase 4: Live Invocation (READ-ONLY skills only)

Unless `--skip-invocation` is set, invoke each READ-ONLY skill via the Skill tool with `--dry-run` if supported, or its lightest invocation mode:

```
Skill(skill="onex:<skill_name>", args="--dry-run")
```

**Assert output contains at least one of:**
- A status field (`status`, `verdict`, `health`, `result`)
- A count field (`count`, `total`, `found`, `checked`)
- A structured list or table

**Timeout:** 120 seconds per skill. If skill times out or throws an unhandled error: verdict = **BROKEN**.

**Note:** Skip invocation for skills known to require live infrastructure (Kafka, .201 runtime). Document these as `SKIP (infra-dep)` with the infrastructure dependency noted.

---

## Phase 5: Produce Per-Skill Records

For each skill, produce a record:

```yaml
- name: "onex:session"
  classification: INTERACTIVE
  backing_node: "node_session_orchestrator"
  backing_node_exists: true
  stub_detected: true
  stub_evidence: "handler_session_orchestrator.py:748 Phase 2 STUB, line 767 Phase 3 STUB"
  invocation_result: "SKIP (interactive)"
  linear_ticket: "OMN-8367"
  verdict: PARTIAL
  notes: "Phase 1 implemented. Phase 2 (RSD scoring) and Phase 3 (dispatch) are explicit stubs."
```

**Verdict values:**
- `WORKS` — backing exists, no stubs, invocation passed (or SKIP with reason)
- `PARTIAL` — some phases implemented, others explicitly stubbed; tracked in Linear
- `FACADE` — skill describes complex logic but has no backing implementation; untracked
- `STUB` — entire handle() is stubbed (`raise NotImplementedError` or `pass  # TODO`)
- `BROKEN` — SKILL.md missing, import error, invocation crashed

---

## Phase 6: Write Audit Artifact

Write the full audit to disk:

```bash
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
if [[ -z "${ONEX_STATE_DIR:-}" ]]; then echo "ERROR: ONEX_STATE_DIR must be set" >&2; exit 1; fi
OUTPUT_PATH="${ONEX_STATE_DIR}/skill-audits/${TIMESTAMP}.yaml"
mkdir -p "${ONEX_STATE_DIR}/skill-audits/"
```

Artifact schema:

```yaml
generated_at: "2026-04-14T03:00:00Z"
skill_count: 91
verdicts:
  WORKS: 86
  PARTIAL: 2
  FACADE: 1
  STUB: 0
  BROKEN: 0
facade_skills:
  - "onex:pipeline_fill"
partial_skills:
  - "onex:session"
  - "onex:delegate"
skills:
  - name: "onex:aislop_sweep"
    classification: READ-ONLY
    backing_node: "node_aislop_sweep"
    backing_node_exists: true
    stub_detected: false
    invocation_result: "PASS"
    verdict: WORKS
  # ... all 91 entries
```

Also write a human-readable summary to `${ONEX_STATE_DIR}/skill-audits/latest-summary.md`.

---

## Phase 7: Fail Gate

If `--fail-on-facade` is true (default):

1. Collect all skills with verdict `FACADE`, `STUB`, or `PARTIAL`
2. For each, check if a Linear ticket is recorded in the skill record's `linear_ticket` field
3. If ANY facade/stub/partial has no `linear_ticket`: **FAIL** (exit nonzero)
4. If all facade/stub/partial skills have tracked Linear tickets: **PASS** (exit 0, log warning)

Failure message format:

```
SKILL AUDIT FAILED: 1 untracked facade(s) found

  FACADE: onex:pipeline_fill
    Evidence: No backing node node_pipeline_fill; SKILL.md describes stateful orchestration without implementation
    Action: File a Linear ticket and add its ID to the skill record

Run again after filing tickets to clear this gate.
```

---

## Phase 8: Report Summary

Output to chat:

```
Skill Functional Audit — 2026-04-14T03:00:00Z
==============================================
Skills audited: 91
  WORKS:   86
  PARTIAL:  2  [tracked in Linear]
  FACADE:   1  [ticket filed]
  STUB:     0
  BROKEN:   0

Audit artifact: ${ONEX_STATE_DIR}/skill-audits/20260414T030000Z.yaml

Gate: PASS (all facades have Linear tickets)
```

---

## Known Tracked Findings (do not re-flag)

The following skills have known PARTIAL/FACADE verdicts with Linear tickets. Do NOT re-flag these as new findings:

| Skill | Verdict | Linear Ticket | Since |
|-------|---------|--------------|-------|
| `onex:session` | PARTIAL | OMN-8699 (relates to OMN-8367) | 2026-04-14 |
| `onex:pipeline_fill` | FACADE | OMN-8700 | 2026-04-14 |
| `onex:delegate` | PARTIAL | OMN-8701 | 2026-04-14 |

Update this table when tickets are resolved or new findings are added.

---

## Nightly Scheduling

This skill is scheduled via CronCreate to run nightly:

```text
CronCreate("0 3 * * *", "/onex:skill_functional_audit", recurring=true)
```

If the audit FAILS (untracked facades found), it writes a friction event to `${ONEX_STATE_DIR}/friction/` and sends a message to the overnight overseer.

---

## Integration with skill-catalog-gap-sweep

The existing `skill-catalog-gap-sweep` (if it exists) should be updated to call this skill as its functional verification step. File existence alone is no longer sufficient. See `docs/process/skill-audit-methodology.md`.

---

## Related

- **Audit report**: `docs/briefs/skill-functional-audit-2026-04-14.md`
- **Process doc**: `docs/process/skill-audit-methodology.md`
- **Prior gap**: `docs/briefs/skill-catalog-2026-04-14.md` (false-clean sweep)
- **Tickets**: OMN-8367 (session Phase 2+3), filed 2026-04-14 (pipeline_fill, delegate)
