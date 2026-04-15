---
description: Run the deterministic overseer verification gate against a ticket or PR via node_skill_overseer_verify_orchestrator
mode: full
version: "1.0.0"
debug: false
category: verification
level: advanced
tags:
  - verification
  - overseer
  - gate
author: omninode
args:
  - name: --ticket
    description: "Linear ticket identifier (e.g. OMN-1234) to verify"
    required: false
  - name: --pr
    description: "GitHub PR number to verify"
    required: false
---

# Overseer Verify

**Announce at start:** "I'm using the overseer_verify skill to run the deterministic verification gate."

## Overview

Thin skill wrapper around `node_skill_overseer_verify_orchestrator` in omnimarket. Dispatches a skill request to the polymorphic agent (Polly) via the shared `handle_skill_requested` handler; Polly executes the five-check overseer gate and returns a structured RESULT block.

The node is an orchestrator shell — all dispatch logic lives in the shared handler. This skill is the SkillSurface wrapper callable from Claude Code; the NodeUnit is the contract-backed execution layer.

## Quick Start

```bash
# Verify a ticket by identifier
/onex:overseer_verify --ticket OMN-1234

# Verify a specific PR
/onex:overseer_verify --pr 1287
```

## Execution Steps

### 1. Build the skill request envelope

Construct a `ModelSkillRequest` with:

- `skill_name`: `overseer_verify`
- `skill_path`: absolute path to this `SKILL.md`
- `args`: whichever of `--ticket` / `--pr` the caller supplied, as `dict[str, str]`
- `correlation_id`: fresh UUID

### 2. Publish to the command topic

Publish the envelope to the contract-declared command topic (see node `contract.yaml`):

- Subscribe topic: `onex.cmd.omnimarket.overseer_verify.v1`
- Consumer group: `omnimarket.skill.overseer_verify`

The orchestrator subscribes, dispatches to Polly via `handle_skill_requested`, and emits an outcome event.

### 3. Await the outcome event

Await one of the publish topics:

- Success: `onex.evt.omnimarket.overseer_verify-completed.v1`
- Failure: `onex.evt.omnimarket.overseer_verify-failed.v1`

Parse the `ModelSkillResult` payload. Render `status` and `error` to the caller.

### 4. Display the verdict

Surface the RESULT block status (`success` / `failed` / `partial`) and any `error` text. On `failed`, present the handler's diagnostic output so the caller can act.

## Acceptance Criteria

- Request envelope conforms to `ModelSkillRequest` (`skill_path` ends with `SKILL.md`, `skill_name` non-blank, `correlation_id` present).
- Publication lands on `onex.cmd.omnimarket.overseer_verify.v1` with the declared consumer group.
- Caller observes exactly one outcome event on either the `-completed.v1` or `-failed.v1` topic for the emitted `correlation_id`.
- RESULT block parsing yields a `SkillResultStatus` that is faithfully rendered back to the caller.

## See Also

- `node_skill_overseer_verify_orchestrator/contract.yaml` — topic wiring and I/O schema
- `handle_skill_requested` handler — shared dispatch logic
- `overseer` — underlying verification gate skill
