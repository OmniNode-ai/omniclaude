---
description: Full PR readiness loop — resolve merge conflicts, address all review comments and CI failures, then iterate local-review until N consecutive clean passes
mode: full
version: 2.0.0
level: intermediate
debug: false
category: workflow
tags:
  - pr
  - review
  - conflicts
  - code-quality
  - iteration
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
    description: Skip CI failure fetch in PR review phase (review comments only)
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

# PR Polish

The current live branch-fixing path is the multi-phase workflow described in
`prompt.md`, but the live dispatch surface now runs through
`omnimarket.nodes.node_pr_polish`. That node owns repo/worktree resolution,
branch verification, pre-commit install, and `result.json` persistence before
invoking this skill inside the correct worktree.

Treat the authoritative execution path as:

1. `PrPolishDispatchAdapter` dispatches `python -m omnimarket.nodes.node_pr_polish`
2. `node_pr_polish` resolves the PR worktree and invokes `/onex:pr_polish <pr>`
3. this skill workflow performs the actual conflict/review/local-review loop

So the prompt workflow still owns the branch-fixing steps, but it is no longer
the only live execution surface; the node is now the repo-aware wrapper that
makes those steps real.
