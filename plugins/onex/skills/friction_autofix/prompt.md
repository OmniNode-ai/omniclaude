<!-- persona: plugins/onex/skills/_lib/assistant-profile/persona.md -->
<!-- persona-scope: this-skill-only -->
Apply the persona profile above when generating outputs.

# Friction Autofix Skill Orchestration

You are executing the friction_autofix skill. This prompt defines the complete
pipeline for automatically fixing structurally-resolvable friction points.

---

## Step 0: Announce <!-- ai-slop-ok: skill-step-heading -->

Say: "I'm using the friction_autofix skill."

---

## Step 1: Parse Arguments <!-- ai-slop-ok: skill-step-heading -->

Parse from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| `--dry-run` | `false` | Classify and plan only, do not execute |
| `--max-fixes` | `5` | Maximum friction fixes per run |
| `--window-days` | `30` | Rolling window for friction aggregation |

---

## Step 2: Collect — Read Friction Registry <!-- ai-slop-ok: skill-step-heading -->

Load and aggregate friction events:

```python
import sys
import os
from pathlib import Path

plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
shared_path = f"{plugin_root}/skills/_shared"
lib_path = f"{plugin_root}/skills/_lib"
for p in [shared_path, lib_path]:
    if p not in sys.path:
        sys.path.insert(0, p)

from friction_aggregator import aggregate_friction

window_days = int("{{window_days}}" or "30")
aggregates = aggregate_friction(window_days=window_days)
crossed = [a for a in aggregates if a.threshold_crossed]
```

Report: "{len(aggregates)} surfaces tracked, {len(crossed)} crossed threshold in {window_days}-day window"

If `len(crossed) == 0`: report "No friction surfaces crossed threshold. Nothing to fix." and STOP.

---

## Step 3: Classify — FIXABLE vs ESCALATE <!-- ai-slop-ok: skill-step-heading -->

For each threshold-crossing aggregate, classify using the rubric in `classify.md`:

```python
from friction_autofix.classifier import classify_friction_batch
from friction_autofix.models import EnumFrictionDisposition

classifications = classify_friction_batch(crossed)
fixable = [c for c in classifications if c.disposition == EnumFrictionDisposition.FIXABLE]
escalate = [c for c in classifications if c.disposition == EnumFrictionDisposition.ESCALATE]
```

Apply the max-fixes cap:
```python
max_fixes = int("{{max_fixes}}" or "5")
fixable = fixable[:max_fixes]
```

Report classification summary:
```
Classification:
  FIXABLE: {len(fixable)} (capped at {max_fixes})
  ESCALATE: {len(escalate)}
```

---

## Step 4: Escalate — Create Tickets for ESCALATE Items <!-- ai-slop-ok: skill-step-heading -->

For each ESCALATE classification, create a Linear ticket (same as friction_triage but
with an explicit "autofix-escalated" tag):

Use `mcp__linear-server__save_issue` with:
- title: `[Friction-Escalate] {surface_key} — {count} occurrences / score {severity_score}`
- team: "Omninode"
- project: "Active Sprint"
- priority: 2
- description: Include `friction_surface_key: {surface_key}` dedup marker, escalation reason,
  sample descriptions

**Dedup**: Before creating, search for existing open ticket with `friction_surface_key: {surface_key}`
in description. Skip if found.

If `--dry-run`: report what would be created but do not create.

---

## Step 5: Plan — Generate Micro-Plans for FIXABLE Items <!-- ai-slop-ok: skill-step-heading -->

For each FIXABLE classification, generate a micro-plan:

```python
from friction_autofix.plan_generator import generate_micro_plan

plans = []
for clf in fixable:
    plan = generate_micro_plan(clf)
    plans.append(plan)
```

The generated micro-plan provides the structure. The LLM executing the ticket-pipeline
will use the friction description, surface, and fix category to determine the exact
code changes needed.

If `--dry-run`: report generated plans and STOP.

---

## Step 6: Execute — Route Each Fix Through Ticket-Pipeline <!-- ai-slop-ok: skill-step-heading -->

For each micro-plan, create a Linear ticket and dispatch ticket-pipeline:

**6a: Check two-strike rule**

```python
from friction_autofix.attempt_tracker import AttemptTracker

tracker = AttemptTracker()
```

For each plan, check `tracker.is_blocked(plan.surface_key)`. If blocked, skip with
outcome SKIPPED and report: "Surface {surface_key} blocked by two-strike rule."

**6b: Create the Linear ticket**

```
mcp__linear-server__save_issue(
    title="[Friction-Fix] {plan.title}",
    team="Omninode",
    project="Active Sprint",
    priority=3,
    description="""## Friction Autofix

friction_surface_key: {plan.surface_key}

**Skill**: {classification.skill}
**Surface**: {classification.surface}
**Fix Category**: {classification.fix_category}
**Occurrences**: {classification.count} (score: {classification.severity_score})

## Description

{classification.description}

## Micro-Plan

{formatted task list from plan.tasks}

## Context

This ticket was auto-created by `/friction_autofix`. The fix should be
scoped to the micro-plan above (1-3 tasks, single repo: {plan.target_repo}).
""",
)
```

**6c: Dispatch ticket-pipeline**

```
/ticket-pipeline {ticket_id}
```

Wait for ticket-pipeline to complete. Track outcome per fix.

**6d: Record attempt**

```python
tracker.record_attempt(plan.surface_key)
```

If the fix succeeds, mark resolved:
```python
tracker.mark_resolved(plan.surface_key)
```

---

## Step 7: Verify — Confirm Fixes Work <!-- ai-slop-ok: skill-step-heading -->

After each fix merges, verify it resolved the friction:

1. Check if the PR merged successfully (via `gh pr view`)
2. If the friction was from a specific operation (e.g., build, import check), re-run
   that operation and confirm it succeeds
3. Mark the fix result:
   - `RESOLVED`: PR merged AND verification passed
   - `FAILED`: PR merged but verification failed (or PR failed CI)
   - `SKIPPED`: Fix attempt was skipped (two-strike, cap reached)

---

## Step 8: Report — Emit Events and Summary <!-- ai-slop-ok: skill-step-heading -->

For each resolved fix, emit a Kafka event:

```python
from emit_client_wrapper import emit_event

emit_event("friction.autofix.resolved", {
    "surface_key": result.surface_key,
    "outcome": result.outcome,
    "ticket_id": result.ticket_id,
    "pr_number": result.pr_number,
    "verification_passed": result.verification_passed,
})
```

Print final summary:

```
FRICTION AUTOFIX COMPLETE

Friction surfaces processed: {total}
  FIXABLE:   {len(fixable)}
  ESCALATE:  {len(escalate)}

Fix Results:
  Resolved:  {resolved_count}
  Failed:    {failed_count}
  Skipped:   {skipped_count}

Escalation Tickets Created: {escalation_tickets_created}

FRICTION_AUTOFIX_RESULT: {status} fixes_attempted={attempted} fixes_resolved={resolved} escalations={escalated}
```
