---
description: End-to-end post-PR-merge redeployment pipeline — verifies merge gate, confirms release state, releases packages via /release, rebuilds Docker runtime via /redeploy, and runs close-out verification
version: 1.0.0
level: advanced
debug: false
category: workflow
tags: [deploy, runtime, docker, release, post-merge, pipeline]
author: OmniClaude Team
composable: false
inputs:
  - name: batch_label
    type: str
    description: "GitHub label applied to batch PRs (e.g., omni-batch:2068). Required unless --skip-merge-gate is set."
    required: false
  - name: repos
    type: str
    description: "Comma-separated repo list (default: all repos in tier graph)"
    required: false
  - name: skip_merge_gate
    type: bool
    description: Skip Phase 0 merge gate verification
    required: false
  - name: skip_release
    type: bool
    description: Skip Phase 2 release (packages already released)
    required: false
  - name: skip_rebuild
    type: bool
    description: Skip Phase 3 Docker rebuild (containers already current)
    required: false
  - name: smoke_prompt
    type: str
    description: "Prompt text for Kafka smoke test (default: ROUTING_SMOKE_TEST nonce=<auto>)"
    required: false
  - name: dry_run
    type: bool
    description: Print pipeline plan without execution
    required: false
  - name: resume
    type: str
    description: Resume from state file by run_id
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to ~/.claude/skill-results/{context_id}/post-release-redeploy.json"
    fields:
      - status: success | failed | partial | dry_run
      - run_id: str
      - phases: "dict[str, phase_status]"
      - release_run_id: str | null
      - redeploy_run_id: str | null
      - released_versions: "dict[str, str] | null"
args:
  - name: --batch-label
    description: "GitHub label for batch PR gate (e.g., omni-batch:2068)"
    required: false
  - name: --repos
    description: "Comma-separated repo list (default: all)"
    required: false
  - name: --skip-merge-gate
    description: Skip merge gate verification
    required: false
  - name: --skip-release
    description: Skip /release phase (packages already on PyPI)
    required: false
  - name: --skip-rebuild
    description: Skip Docker rebuild phase
    required: false
  - name: --smoke-prompt
    description: "Custom Kafka smoke test prompt text"
    required: false
  - name: --dry-run
    description: Print plan, no execution
    required: false
  - name: --resume
    description: Resume from state file by run_id
    required: false
---

# Post-Release Redeploy

## Dispatch Requirement

When invoked, dispatch to a polymorphic-agent:

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Post-release redeploy pipeline",
  prompt="Run the post-release-redeploy skill. <full context>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

## Overview

End-to-end pipeline that codifies the full post-PR-merge redeployment runbook. Composes
the existing `/release` and `/redeploy` skills into a single orchestrated workflow with
pre-flight checks, merge gate verification, release state confirmation, package release,
Docker image rebuild, health verification, and close-out.

**Announce at start:** "I'm using the post-release-redeploy skill."

## Quick Start

```
/post-release-redeploy --batch-label "omni-batch:2068"
/post-release-redeploy --batch-label "omni-batch:2068" --dry-run
/post-release-redeploy --skip-merge-gate --skip-release --repos "omnibase_infra"
/post-release-redeploy --resume prd-20260307-abc123
```

## Phase Sequence

| # | Phase | Core Action | Idempotency |
|---|-------|-------------|-------------|
| 0 | `PRE_FLIGHT` | Verify tag discovery fix, repos on main, pull latest | Safe: read-only checks + ff-only pull |
| 1 | `MERGE_GATE` | Verify all batch-labeled PRs are merged | Read-only GitHub API check |
| 2 | `RELEASE_STATE` | Scan repos for unreleased commits, compute versions | Read-only git operations |
| 3 | `RELEASE` | Invoke `/release` for package publication | Delegates to release skill (idempotent) |
| 4 | `INSTALLABILITY` | Verify released packages installable from PyPI | Read-only pip check |
| 5 | `REBUILD` | Invoke `/redeploy` for Docker rebuild + restart | Delegates to redeploy skill (idempotent) |
| 6 | `HEALTH` | Infrastructure health checks + container version verification | Read-only curl + docker exec |
| 7 | `KAFKA_SMOKE` | Nonce-based Kafka emission test + consumer lag check | Emits one test event |
| 8 | `CLOSE_OUT` | Version gap verification, mixed tag check, Linear update | Read-only git checks + Linear API |

## Composition

This skill composes two existing skills:

| Phase | Delegates To | How |
|-------|-------------|-----|
| RELEASE | `/release` skill | Full release pipeline with Slack gate |
| REBUILD | `/redeploy` skill | Docker rebuild with version pins |

All other phases run inline.

## See Also

- `prompt.md` -- authoritative phase execution logic
- `release` skill -- Phase 3 delegate for package release
- `redeploy` skill -- Phase 5 delegate for Docker rebuild
- `~/.claude/plans/agile-purring-ullman.md` -- source runbook
