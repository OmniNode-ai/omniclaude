---
description: Automatically fix structurally-resolvable friction points from autopilot runs
mode: full
version: "1.0.0"
level: advanced
debug: false
category: workflow
tags: [friction, autofix, self-healing, pipeline, autonomous]
author: OmniClaude Team
composable: true
args:
  - name: --dry-run
    description: "Classify and plan but do not execute fixes (default: false)"
    required: false
  - name: --max-fixes
    description: "Maximum number of friction fixes per run (default: 5)"
    required: false
  - name: --window-days
    description: "Rolling window in days for friction aggregation (default: 30)"
    required: false
inputs:
  - name: friction_registry
    description: "Path to friction NDJSON registry (default: ~/.claude/state/friction/friction.ndjson)"
outputs:
  - name: status
    description: "complete | partial | error"
  - name: fixes_attempted
    description: "Number of friction fixes attempted"
  - name: fixes_resolved
    description: "Number of friction fixes verified as resolved"
  - name: escalations_created
    description: "Number of escalation tickets created"
---

# Friction Autofix

**Skill ID**: `onex:friction_autofix`
**Version**: 1.0.0
**Owner**: omniclaude
**Epic**: OMN-5442

---

## Purpose

Self-healing pipeline skill. Reads friction events recorded during autopilot/close-out
runs, classifies them as structurally fixable or requiring escalation, generates micro-plans
for fixable items, executes fixes via ticket-pipeline, and verifies the fixes work.

## Dispatch Requirement

When invoked, dispatch to polymorphic-agent:

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Run friction_autofix pipeline",
  prompt="Run the friction_autofix skill. <full context and args>"
)
```

## Safety Constraints

- Maximum 5 friction fixes per run (configurable via `--max-fixes`)
- Each fix scoped to 1-3 tasks and single repo
- Anything larger gets escalated to a normal ticket
- Each fix must pass CI before merge (no --no-verify)
- Two-strike rule: if a fix fails twice, create diagnosis document and stop

## Integration Points

- **Reads from**: `~/.claude/state/friction/friction.ndjson` (via `aggregate_friction()`)
- **Writes to**: Linear (tickets), GitHub (PRs), Kafka (friction-resolved events)
- **Called by**: autopilot skill (tail step after close-out or build mode)
- **Calls**: `/ticket-pipeline` for each fixable friction, `/friction-triage` for escalations

## Relationship to Existing Skills

| Skill | Relationship |
|-------|-------------|
| `/record-friction` | Upstream — records individual friction events |
| `/friction-triage` | Parallel — triage creates tickets; autofix creates tickets AND fixes them |
| `/ticket-pipeline` | Downstream — autofix routes each fix through ticket-pipeline |
| `/autopilot` | Caller — autofix runs as a tail step |
