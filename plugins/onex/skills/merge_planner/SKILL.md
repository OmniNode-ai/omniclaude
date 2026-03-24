---
description: Queue Priority Manager — classify PRs by type, score queue priority, and promote accelerator PRs in GitHub merge queues
mode: full
version: 1.0.0
level: advanced
debug: false
category: workflow
tags:
  - pr
  - github
  - merge
  - queue
  - priority
  - autonomous
author: OmniClaude Team
composable: true
args:
  - name: --mode
    description: "Operating mode: shadow (log only), label_gated (promote if labeled), auto (full auto)"
    required: false
  - name: --repos
    description: "Comma-separated repo names to scan (default: all queue-enabled repos)"
    required: false
  - name: --dry-run
    description: "Log decisions without executing promotions"
    required: false
  - name: --max-promotions
    description: "Safety cap on promotions per run (default: 3)"
    required: false
inputs:
  - GitHub merge queue state (via gh CLI)
  - PR file diffs for classification
  - CI check status
outputs:
  - QPM audit ledger entry (JSON)
  - Kafka events (qpm-classified, qpm-promotion-decided)
---

# merge-planner

Classify PRs as accelerator/normal/blocked, compute 5-dimension priority scores, and promote
standalone validator PRs ahead in GitHub merge queues using `enqueuePullRequest(jump: true)`.

See the plan for rollout phases: shadow -> label-gated -> auto.
