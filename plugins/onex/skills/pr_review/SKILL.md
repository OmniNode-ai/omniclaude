---
description: Comprehensive PR review with strict priority-based organization and merge readiness assessment
mode: full
version: 6.0.0
level: basic
debug: false
category: review
tags:
  - review
  - pr
  - multi-model
  - judge-verification
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
args:
  - name: pr_number
    description: PR number to review
    required: true
  - name: repo
    description: GitHub repo (owner/repo)
    required: true
  - name: --dry-run
    description: Run without posting to GitHub
    required: false
---

# /onex:pr_review — PR Review Bot

**Skill ID**: `onex:pr_review`
**Version**: 6.0.0
**Backing node**: `node_pr_review_bot`

## Changelog

- **6.0.0** — Thinned to dispatch-only shim (OMN-8768). All logic in `node_pr_review_bot`.
- **5.0.0** — Added node_pr_review_bot node-dispatch path.

## What this skill does

Dispatches through `onex run-node node_pr_review_bot`. The node owns diff fetching,
multi-agent review, finding aggregation, verdict posting, and thread watching.
This shim contains no inline review logic.

**Announce at start:** "I'm using the pr-review skill."

## Dispatch

```bash
uv run onex run-node node_pr_review_bot --input '{
  "pr_number": <pr_number>,
  "repo": "<owner/repo>",
  "dry_run": false
}'
```

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

Contract target: `node_pr_review_bot`

Command topic: `onex.cmd.omnimarket.pr-review-bot-start.v1`

Terminal events:
- `onex.evt.omnimarket.pr-review-bot-phase-transition.v1`
- `onex.evt.omnimarket.pr-review-bot-thread-posted.v1`
- `onex.evt.omnimarket.pr-review-bot-thread-verified.v1`
