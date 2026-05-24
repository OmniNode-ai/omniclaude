---
description: End-to-end design workflow — brainstorm ideas into structured implementation plans with optional launch
mode: full
version: 2.1.0
level: intermediate
debug: false
category: planning
tags:
  - design
  - brainstorming
  - planning
  - writing-plans
  - workflow
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: true
args:
  - name: --phase
    description: "Start at phase: brainstorm (Phase 1), plan (Phase 2), or launch (Phase 3). Default: brainstorm"
    required: false
  - name: --topic
    description: "Topic or problem to brainstorm (Phase 1)"
    required: false
  - name: --plan-path
    description: "Path to existing plan file (skip to Phase 2 or 3)"
    required: false
  - name: --no-launch
    description: "Stop after plan save — do not prompt for launch"
    required: false
---

# /onex:design_to_plan — Design to Plan Orchestrator

**Skill ID**: `onex:design_to_plan`
**Version**: 2.1.0
**Backing node**: `node_design_to_plan`

## Changelog

- **2.1.0** — Added Phase 0 knowledge preload via `node_design_plan_context_compute` (OMN-11940).
- **2.0.0** — Thinned to dispatch-only shim (OMN-8768). All logic in `node_design_to_plan`.
- **1.1.0** — Added Phase 3 launch path.

## What this skill does

Dispatches through `onex run-node node_design_to_plan`. The node owns the three-phase
workflow (brainstorm → plan → launch), adversarial review integration, and plan file
persistence. This shim contains no inline design or planning logic.

**Announce at start:** "I'm using the design-to-plan skill."

## Dispatch

```bash
uv run onex run-node node_design_to_plan --input '{
  "phase": "brainstorm",
  "topic": "<topic or null>",
  "plan_path": null,
  "no_launch": false
}'
```

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

Contract target: `node_design_to_plan`

Command topic: `onex.cmd.omnimarket.design-to-plan-start.v1`

Terminal event: `onex.evt.omnimarket.design-to-plan-completed.v1`


## Knowledge Preload (Phase 0)

Before dispatching to `node_design_to_plan`, invoke `node_design_plan_context_compute`
(omnimarket) to assemble an Architecture Context block. Inject the resulting
`architecture_context_block` field into the node input as `knowledge_preload`.

The node accepts pre-resolved results from three sources scoped to `repos_mentioned`:
- **Repowise** `get_why` — architectural decisions to honor
- **Antipattern registry** — patterns to avoid
- **Memgraph** dependency impact — downstream systems affected

Output fields: `systems_affected`, `decisions_to_honor`, `antipatterns_to_avoid`, `impact_summary`,
and the formatted `architecture_context_block` (four `###` sections ready for prompt injection).

## Phase 2b: Adversarial Review — R11 Doctrine Compliance (Advisory)

After the R1-R10 adversarial review loop completes, run an R11 doctrine
compliance check for plans that create or modify doctrine-governed surfaces.

### R11 -- Doctrine Compliance (Advisory)

For each task in the plan, check whether it touches a doctrine-governed surface:

- **Kafka topics**: Any task creating a Kafka topic must reference doctrine clause DT-001
- **Projections**: Any task creating a projection must declare freshness SLA (DT-003)
- **API endpoints**: Any task adding an API endpoint must declare contract binding (DT-004)
- **New data**: Any task creating new data must declare provenance (DT-005)

**Severity:** All R11 findings are ADVISORY — they do not block ticketization.
CI and runtime gates (Tasks 16-17) remain the authoritative enforcement layer.
R11 findings must not be treated as completion proof.

**Output format:**

Emit exactly one of the following forms, not both alternatives joined together.

If doctrine violations are found:

```
R11: checked -- [advisory: task 3 creates projection without DT-003 freshness declaration]
```

If no doctrine-governed surfaces are touched:

```
R11: checked -- [clean (no doctrine-governed surfaces touched)]
```
