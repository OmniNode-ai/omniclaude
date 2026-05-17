---
description: Full PR readiness loop — resolve merge conflicts, address all review comments and CI failures, then iterate local-review until N consecutive clean passes
mode: full
version: 3.0.0
level: intermediate
debug: false
category: workflow
tags:
  - pr
  - review
  - conflicts
  - code-quality
  - iteration
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
args:
  - name: pr_number
    description: PR number or URL (auto-detects from current branch if omitted)
    required: false
  - name: --required-clean-runs
    description: "Consecutive clean local-review passes required before done (default: 4)"
    required: false
  - name: --max-iterations
    description: "Maximum local-review cycles (default: 10)"
    required: false
  - name: --skip-conflicts
    description: Skip merge conflict resolution phase
    required: false
  - name: --skip-pr-review
    description: Skip PR review comments and CI failures phase
    required: false
  - name: --skip-local-review
    description: Skip local-review clean-pass loop phase
    required: false
  - name: --no-ci
    description: Skip CI failure fetch in PR review phase
    required: false
  - name: --no-push
    description: Apply all fixes locally without pushing to remote
    required: false
  - name: --dry-run
    description: Log phase decisions without making changes
    required: false
  - name: --no-automerge
    description: Skip enabling GitHub automerge after all phases complete
    required: false
---

# /onex:pr_polish — PR Polish Orchestrator

**Skill ID**: `onex:pr_polish`
**Version**: 3.0.0
**Backing node**: `node_pr_polish`

## Changelog

- **3.0.0** — Thinned to dispatch-only shim (OMN-8768). All phase logic in `node_pr_polish`.
- **2.0.0** — Added node_pr_polish dispatch path.

## What this skill does

Dispatches through `onex run-node node_pr_polish`. The node owns worktree resolution,
branch verification, conflict resolution, review comment addressing, local-review loop,
CodeRabbit triage, pre-commit gate, push, and auto-merge arming. This shim contains
no inline phase logic.

**Announce at start:** "I'm using the pr-polish skill."

## Dispatch

```bash
uv run onex run-node node_pr_polish --input '{
  "pr_number": <pr_number or null>,
  "required_clean_runs": 4,
  "max_iterations": 10,
  "skip_conflicts": false,
  "skip_pr_review": false,
  "skip_local_review": false,
  "no_ci": false,
  "no_push": false,
  "dry_run": false,
  "no_automerge": false
}'
```

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

Contract target: `node_pr_polish`

Command topic: `onex.cmd.omnimarket.pr-polish-start.v1`

Terminal events:
- `onex.evt.omnimarket.pr-polish-phase-transition.v1`
- `onex.evt.omnimarket.pr-polish-completed.v1`
