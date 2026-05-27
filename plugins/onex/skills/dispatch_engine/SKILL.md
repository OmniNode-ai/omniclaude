---
description: Thin dispatch-only shim for the dispatch_engine pipeline. Builds the contract-canonical node_skill_dispatch_engine_orchestrator start envelope and invokes the manifest-canonical onex run-node path. No inline orchestration logic.
mode: full
version: "2.0.0"
debug: false
category: dispatch
level: advanced
foreground_orchestrator: true
tags:
  - dispatch
  - orchestration
  - dispatch-only
  - routing-enforced
author: omninode
args:
  - name: --dry-run
    description: "Return a dry_run placeholder without dispatching"
    required: false
  - name: --repo
    description: "Restrict dispatch scan to a single repository"
    required: false
inputs:
  - name: envelope
    description: "ModelEventEnvelope[ModelSkillRequest]"
outputs:
  - name: orchestrator_result
    description: "ModelSkillResult JSON"
---

# /onex:dispatch_engine — Dispatch Engine Shim

**Skill ID**: `onex:dispatch_engine`
**Version**: 2.0.0
**Owner**: omniclaude
**Ticket**: OMN-12236
**Backing node**: `node_skill_dispatch_engine_orchestrator`

**Announce at start:** "I'm using the dispatch_engine skill to poll the work backlog and dispatch builders for gaps."

## Changelog

- **2.0.0** — Breaking dispatch contract change. The shim now builds a
  `ModelSkillRequest` payload and invokes the manifest-canonical
  `uv run onex run-node node_skill_dispatch_engine_orchestrator` path.
  No inline placeholder logic remains in the skill surface.
- **1.0.0** — Scaffold only. Returned a `"dispatched"` placeholder.

## What this skill does

Dispatches through `onex run-node node_skill_dispatch_engine_orchestrator`. The node owns
backlog polling, gap detection, and builder fan-out. This shim contains no orchestration
logic, no inline placeholder returns, and no direct Kafka publish.

## Wire Schema

Contract target:
`node_skill_dispatch_engine_orchestrator`

Command topic:
`onex.cmd.omnimarket.dispatch_engine.v1`

Dispatch declaration for deterministic routing gates:
`plugins/onex/skills/dispatch_engine/run.sh` invokes
`uv run onex run-node node_skill_dispatch_engine_orchestrator --input <envelope>`
through the manifest-canonical runtime path.

Event type alias:
`omnimarket.dispatch_engine`

Terminal events:
- Success: `onex.evt.omnimarket.dispatch_engine-completed.v1`
- Failure: `onex.evt.omnimarket.dispatch_engine-failed.v1`

Envelope shape:

```json
{
  "event_type": "omnimarket.dispatch_engine",
  "correlation_id": "<uuid>",
  "payload": {
    "skill_name": "dispatch_engine",
    "skill_path": "<absolute-path-to-SKILL.md>",
    "args": {},
    "dry_run": false
  }
}
```

## Dispatch

```bash
plugins/onex/skills/dispatch_engine/run.sh \
  [--dry-run] \
  [--repo <repo>]
```

The launcher dispatches through `onex run-node node_skill_dispatch_engine_orchestrator`
and prints the `ModelSkillResult` JSON returned by the backing node.
Surface non-zero exits directly. On routing failure raise `SkillRoutingError`;
do not produce prose.

**Fallback path (local/offline):**

```bash
onex node node_skill_dispatch_engine_orchestrator --input <envelope_json_file>
```

Where `<envelope_json_file>` contains a `ModelEventEnvelope[ModelSkillRequest]` JSON blob.

## Quick Start

```bash
# Dry-run: inspect what would be dispatched
/onex:dispatch_engine --dry-run

# Live dispatch
/onex:dispatch_engine

# Restrict to a single repo
/onex:dispatch_engine --repo OmniNode-ai/omnimarket
```

## See Also

- `node_skill_dispatch_engine_orchestrator/contract.yaml` — topic wiring and I/O schema
- `node_skill_overseer_verify_orchestrator` — canonical skill orchestrator pattern
- `dispatch_worker` skill — downstream builder dispatch target
