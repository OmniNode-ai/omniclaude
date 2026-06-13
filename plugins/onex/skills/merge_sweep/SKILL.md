---
description: Thin dispatch-only shim for the org-wide PR merge sweep pipeline. Builds the contract-canonical pr_lifecycle_orchestrator start envelope and invokes the manifest-canonical onex run-node path. No inline GH script fallback, no direct Kafka publish, no orchestration logic.
mode: full
version: 7.0.0
level: advanced
debug: false
category: workflow
tags:
  - pr
  - github
  - merge
  - autonomous
  - pipeline
  - org-wide
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: "Comma-separated org/repo names to scan; empty means all OmniNode repos"
    required: false
  - name: --dry-run
    description: "Run without side effects"
    required: false
  - name: --inventory-only
    description: "Stop after inventory"
    required: false
  - name: --fix-only
    description: "Only run the fix phase; skip merge"
    required: false
  - name: --merge-only
    description: "Only run the merge phase; skip fix"
    required: false
  - name: --max-parallel-polish
    description: "Maximum concurrent pr-polish agents during the fix phase"
    required: false
  - name: --enable-auto-rebase
    description: "Auto-rebase stale PR branches before merge"
    required: false
  - name: --use-dag-ordering
    description: "Order merge candidates by dependency DAG"
    required: false
  - name: --enable-trivial-comment-resolution
    description: "Resolve trivial bot review threads before merge"
    required: false
  - name: --enable-admin-merge-fallback
    description: "Admin-merge PRs stuck in queue past threshold"
    required: false
  - name: --admin-fallback-threshold-minutes
    description: "Minutes before a queued PR is considered stuck"
    required: false
  - name: --verify
    description: "Run verification_sweep per PR before merge"
    required: false
  - name: --verify-timeout-seconds
    description: "Hard per-PR verification timeout in seconds"
    required: false
  - name: --run-id
    description: "Identifier for this run; generated when omitted"
    required: false
inputs:
  - name: envelope
    description: "ModelEventEnvelope[ModelPrLifecycleStartCommand]"
outputs:
  - name: orchestrator_result
    description: "ModelPrLifecycleResult JSON"
skill_kind: dispatch
---

# /onex:merge_sweep — one command, one typed result

**Skill ID**: `onex:merge_sweep` · **Command**: `uv run onex skill merge_sweep` (omnibase_infra) · **Backing node**: `node_pr_lifecycle_orchestrator` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelPrLifecycleResult]` JSON to
stdout carrying the FULL handler result; RuntimeLocal logs and intermediate
context go to a capture file + the artifact store, never to you.

See `prompt.md` for the one command and how to present the typed result.

## What this skill does NOT do

- Construct a payload file, `cd` anywhere, or `cat` a workflow_result.json (all internal to `onex skill`)
- Run any inline scan, probe, or orchestration — the backing node owns all logic
- Contain executable logic in this directory — markdown only

## Related

- **CLI entrypoint**: `omnibase_infra/src/omnibase_infra/cli/cli_skill.py`
- **Skill→node mapping**: `omnibase_infra/src/omnibase_infra/cli/skill_mapping.yaml`
- **Result model**: `omnimarket.nodes.node_pr_lifecycle_orchestrator.handlers.handler_pr_lifecycle_orchestrator.ModelPrLifecycleResult`
