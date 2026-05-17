---
description: End-to-end design workflow — brainstorm ideas into structured implementation plans with optional launch
mode: full
version: 2.0.0
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
**Version**: 2.0.0
**Backing node**: `node_design_to_plan`

## Changelog

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
