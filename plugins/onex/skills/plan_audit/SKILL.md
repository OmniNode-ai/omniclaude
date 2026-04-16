---
description: Health check over plan files in docs/plans/ — verifies phase state, epic linkage, DoD completeness, ticket coverage, and staleness. Produces a PASS/WARN/FAIL report per plan.
mode: full
version: 1.0.0
level: intermediate
debug: false
category: quality
tags:
  - plans
  - audit
  - health-check
  - epic-linkage
  - dod
  - tickets
  - staleness
author: OmniClaude Team
composable: true
args:
  - name: --repo
    description: "Repo name to audit (default: resolved from git root)"
    required: false
  - name: --since-days
    description: "Staleness threshold in days (default: 14)"
    required: false
  - name: --fail-only
    description: "Only report plans with FAIL verdict (suppress WARN and PASS)"
    required: false
  - name: --dry-run
    description: "Report only, no ticket creation"
    required: false
---

# Plan Audit

Health check over plan files in `docs/plans/`. Verifies five properties per plan
and produces a structured PASS/WARN/FAIL report.

## Dispatch Surface

**Target**: Node dispatch via `handle_skill_requested`

```
/plan-audit [args]
        |
        v
onex.cmd.omniclaude.plan-audit.v1  (Kafka)
        |
        v
NodeSkillPlanAuditOrchestrator
  src/omniclaude/nodes/node_skill_plan_audit_orchestrator/
  → handle_skill_requested (omniclaude.shared)
  → claude -p (polymorphic agent executes skill)
        |
        v
onex.evt.omniclaude.plan-audit-completed.v1
```

All audit logic executes inside the polymorphic agent. This skill is a thin shell:
parse args, dispatch to node, render results.

## Announce at start

"I'm using the plan-audit skill to health-check all plan files."

## When to Use

- Before a sprint cycle to verify all active plans are actionable
- After a merge sweep to confirm plans have been updated
- As a gate before closing an epic (verify plans are resolved)
- During autopilot close-out to catch stale or incomplete plans

## The Five Checks

### Check 1: Phase State Verification

Each plan must declare its current phase and that phase must be in a valid state.

Valid states: `draft`, `in-review`, `approved`, `in-progress`, `completed`, `cancelled`

A plan with no phase declaration fails this check.
A plan with an unrecognized phase value fails this check.
A plan marked `completed` or `cancelled` is exempt from checks 2–5.

### Check 2: Epic Linkage

Each active plan must reference at least one Linear epic ID (`epic_id` field or
`OMN-XXXX` pattern in the header frontmatter or first 10 lines).

Plans without an epic linkage cannot be traced to project scope and fail this check.

### Check 3: DoD Completeness

Each active plan must have a `dod_evidence` section listing at least one verifiable
definition-of-done item. A DoD item is verifiable if it specifies a check type
(`file_exists`, `pr_merged`, `ci_green`, `command_output`, or `rendered_output`).

Plans with a `dod_evidence: []` or missing `dod_evidence` section fail this check.
Plans with DoD items that have no `type` field fail this check.

### Check 4: Ticket Coverage

Each milestone or phase in the plan must map to at least one existing Linear ticket.
Acceptable linkage patterns:
- `ticket: OMN-XXXX` in a milestone block
- `OMN-XXXX` reference anywhere in a milestone heading or body

Check via `tracker.get_issue` for each referenced ticket ID.
Milestones with no ticket reference are flagged as coverage gaps.
Referenced tickets that do not exist in Linear fail this check.

### Check 5: Staleness Check

A plan is stale if:
- Its last `git log` modification date is older than `--since-days` (default: 14)
- AND the plan's phase is not `completed` or `cancelled`

Use `git log -1 --format=%ai -- <plan-file>` for the authoritative modification date.

## Verdict Assignment

| Condition | Verdict |
|-----------|---------|
| All 5 checks pass | PASS |
| 1–2 checks fail with low severity (staleness, missing DoD items) | WARN |
| Phase invalid, epic missing, or ticket 404 | FAIL |
| Plan is `completed` or `cancelled` | PASS (exempt from checks 2–5) |

## Report Format

```
=== Plan Audit Report ===
Repo: <repo-name>
Plans scanned: N
  PASS:  X
  WARN:  Y
  FAIL:  Z

FAIL plans:
  [FAIL] docs/plans/2026-03-15-deploy-agent.md
    - Check 2 FAIL: No epic linkage found
    - Check 4 FAIL: Milestone "Phase 3" has no ticket reference

WARN plans:
  [WARN] docs/plans/2026-04-01-session-orchestrator.md
    - Check 5 WARN: Last modified 2026-03-28 (16 days ago, threshold: 14)

PASS plans:
  [PASS] docs/plans/2026-04-10-wave5-golden-chain.md
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--repo <name>` | current repo | Repo to audit (resolved from git root) |
| `--since-days N` | 14 | Staleness threshold in days |
| `--fail-only` | false | Only emit FAIL lines (quiet mode) |
| `--dry-run` | false | No ticket creation |

## Integration

- Used by close-out autopilot after merge-sweep and dod-sweep
- Referenced by `onex:platform_readiness` as a plan health gate
- FAIL verdict blocks epic close-out (same severity as DoD gap)

## See Also

- `onex:dod_sweep` — DoD evidence verification across tickets
- `onex:doc_freshness_sweep` — Broken references in docs
- `onex:contract_sweep` — Contract YAML health
