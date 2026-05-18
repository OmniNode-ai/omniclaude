---
description: Paired worker/verifier dispatch — verifier runs independently alongside each worker and produces typed verification_bundle.json evidence; bounded escalation with max 3 attempts
mode: full
level: intermediate
debug: false
category: verification
tags:
  - dispatch
  - verification
  - worker
  - verifier
  - evidence
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
version: 1.0.0
args:
  - name: ticket_id
    description: Linear ticket ID (e.g., OMN-1234)
    required: true
  - name: worker_prompt
    description: Prompt or task description passed to the worker subagent
    required: true
  - name: --max-attempts
    description: Maximum retry attempts before escalation (default 3)
    required: false
  - name: --cooldown-seconds
    description: Cooldown between retry attempts in seconds (default 60)
    required: false
  - name: --escalation-action
    description: Action on third failure — linear_ticket or human_review (default linear_ticket)
    required: false
---

# /onex:verified_dispatch — Verification-First Parallel Worker Dispatch

**Skill ID**: `onex:verified_dispatch`
**Version**: 1.0.0
**Backing node**: `node_verified_dispatch_orchestrator`

## Changelog

- **1.0.0** — Initial skill (OMN-11220). Thin dispatch-only shim. All logic in `node_verified_dispatch_orchestrator` (omnimarket PR #695).

## What this skill does

Dispatches through `onex run-node node_verified_dispatch_orchestrator`. The node launches a worker subagent and an independent verifier subagent in parallel. The verifier queries authoritative surfaces (GitHub PR state, CI checks, Linear, projection APIs, topology manifests, deployment receipts, artifact hashes) and produces a typed `verification_bundle.json`. Verifier rejection blocks merge and triggers bounded escalation: max 3 attempts with 60s cooldown; third failure creates a Linear escalation ticket.

**Announce at start:** "I'm using the verified-dispatch skill."

## Dispatch

```bash
uv run onex run-node node_verified_dispatch_orchestrator --input '{
  "ticket_id": "<ticket_id>",
  "worker_prompt": "<worker_prompt>",
  "max_attempts": 3,
  "cooldown_seconds": 60,
  "escalation_action": "linear_ticket"
}'
```

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

Contract target: `node_verified_dispatch_orchestrator`

Command topic: `onex.cmd.omnimarket.verified-dispatch-start.v1`

Terminal event: `onex.evt.omnimarket.verified-dispatch-completed.v1`

## Escalation Policy

- Attempt 1: Dispatch worker + verifier. On verifier rejection, log and wait `cooldown_seconds`.
- Attempt 2: Re-dispatch. On second rejection, log and wait `cooldown_seconds`.
- Attempt 3: Re-dispatch. On third rejection, create a Linear escalation ticket and halt.
- Merge is blocked until verifier produces `decision: accept`.
