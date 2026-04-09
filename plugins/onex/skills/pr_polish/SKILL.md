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

Dispatch to the deterministic node — do NOT inline any logic:

```bash
onex run node_pr_polish -- --pr-number "${pr_number}" "${@}"
```
