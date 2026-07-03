---
description: Dispatch-only shim for handler contract compliance sweep. All scanning (topic-compliance,
  transport-compliance, handler-routing, logic-in-node) executes in node_compliance_sweep (omnimarket).
  The skill parses --repos/--checks/--dry-run and dispatches; no inline scanning.
version: 3.0.0
mode: full
level: advanced
debug: false
category: verification
tags:
  - compliance
  - contracts
  - handlers
  - shim
  - dispatch-only
  - thin-shim
author: OmniClaude Team
composable: false
args:
  - name: --repos
    description: string list arg
    required: false
  - name: --checks
    description: string list arg
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
skill_kind: dispatch
---

# /onex:compliance_sweep — one command, one typed result

**Skill ID**: `onex:compliance_sweep` · **Command**: `uv run onex skill compliance_sweep` (omnibase_infra) · **Backing node**: `node_compliance_sweep` (omnimarket)

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ComplianceSweepResult]` JSON to
stdout carrying the FULL handler result; RuntimeLocal logs and intermediate
context go to a capture file + the artifact store, never to you.

See `prompt.md` for the one command and how to present the typed result.

## Routing Contract

The `uv run onex skill compliance_sweep` entrypoint publishes to `onex.cmd.omnimarket.compliance-sweep.v1`
through receipt-mode dispatch. If routing fails, surface `SkillRoutingError` directly; do not produce prose.

## What this skill does NOT do

- Construct a payload file, `cd` anywhere, or `cat` a workflow_result.json (all internal to `onex skill`)
- Run any inline scan, probe, or orchestration — the backing node owns all logic
- Contain executable logic in this directory — markdown only

## Related

- **CLI entrypoint**: `omnibase_infra/src/omnibase_infra/cli/cli_skill.py`
- **Skill→node mapping**: `omnibase_infra/src/omnibase_infra/cli/skill_mapping.yaml`
- **Result model**: `omnimarket.nodes.node_compliance_sweep.handlers.handler_compliance_sweep.ComplianceSweepResult`
