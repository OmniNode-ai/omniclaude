---
description: Poll work backlog and dispatch builders for gaps via node_skill_dispatch_engine_orchestrator (scaffold)
mode: full
version: "1.0.0"
debug: false
category: dispatch
level: advanced
tags:
  - dispatch
  - orchestration
  - scaffold
author: omninode
args:
  - name: --dry-run
    description: "Return a dry_run placeholder without dispatching"
    required: false
  - name: --repo
    description: "Restrict dispatch scan to a single repository"
    required: false
---

> **SCAFFOLD ONLY.** Live dispatch returns a `"dispatched"` placeholder. Real
> dispatch wiring (backlog poll, gap detection, builder fan-out) is follow-up
> work; this surface exists so downstream callers can bind to a stable skill
> name and contract today.

# Dispatch Engine

**Announce at start:** "I'm using the dispatch_engine skill to poll the work backlog and dispatch builders for gaps."

## Overview

Thin skill wrapper around `node_skill_dispatch_engine_orchestrator` in omnimarket. The orchestrator node is the scheduled dispatch-engine tick's execution surface: pull backlog, detect gaps, dispatch builders. All dispatch logic will live in `HandlerSkillRequested`; in this scaffold the handler returns a `"dispatched"` placeholder for live runs and `"dry_run"` when `--dry-run` is supplied.

The SKILL.md is the SkillSurface (platform-specific invocation wrapper); the omnimarket node is the NodeUnit (contract-backed execution). Wrappers own no business logic.

## Quick Start

```bash
# Dry-run: inspect what would be dispatched
/onex:dispatch_engine --dry-run

# Live dispatch (scaffold: returns "dispatched" placeholder)
/onex:dispatch_engine
```

## Execution Steps

### 1. Build the skill request

Construct the handler input with:

- `skill_name`: `dispatch_engine`
- `skill_path`: absolute path to this `SKILL.md`
- `args`: `{}` or any caller-supplied flags as `dict[str, str]`
- `dry_run`: `true` if `--dry-run` was supplied, else `false`

### 2. Publish to the command topic

Topics are declared in `node_skill_dispatch_engine_orchestrator/contract.yaml`:

- Subscribe topic: `onex.cmd.omnimarket.dispatch_engine.v1`
- Consumer group: `omnimarket.skill.dispatch_engine`

### 3. Await the outcome event

- Success: `onex.evt.omnimarket.dispatch_engine-completed.v1`
- Failure: `onex.evt.omnimarket.dispatch_engine-failed.v1`

Parse the result dict. Scaffold returns `{"status": "dispatched" | "dry_run", ...}`.

### 4. Display the verdict

Render `status` back to the caller. On future live-dispatch wiring, also surface the count of builders dispatched and the ticket IDs they were assigned.

## Acceptance Criteria

- Request validated: `skill_path` ends with `SKILL.md`; `skill_name` is non-blank.
- Publication lands on `onex.cmd.omnimarket.dispatch_engine.v1` with the declared consumer group.
- Handler returns a dict whose `status` ∈ `{"dispatched", "dry_run"}`.
- `--dry-run` always short-circuits to `"dry_run"` with no side effects.

## See Also

- `node_skill_dispatch_engine_orchestrator/contract.yaml` — topic wiring and I/O schema
- `node_skill_overseer_verify_orchestrator` — canonical skill orchestrator pattern
- `dispatch_worker` skill — downstream builder dispatch target (future wiring)
