---
description: Auto-triage CodeRabbit review threads — classify severity and auto-reply to Minor/Nitpick findings with acknowledgment, resolving the thread so it no longer blocks merge.
mode: full
version: 2.0.0
level: intermediate
debug: false
category: quality
tags:
  - coderabbit
  - pr-review
  - triage
  - auto-reply
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: true
args:
  - name: repo
    description: "GitHub repo in owner/name format (e.g., OmniNode-ai/omniclaude)"
    required: true
  - name: pr
    description: "PR number to triage"
    required: true
  - name: --dry-run
    description: "Classify threads but do not post replies or resolve"
    required: false
---

# /onex:coderabbit_triage — CodeRabbit Thread Auto-Triage

**Skill ID**: `onex:coderabbit_triage`
**Version**: 2.0.0
**Backing node**: `node_coderabbit_triage`

## Changelog

- **2.0.0** — Thinned to dispatch-only shim (OMN-8768). All logic in `node_coderabbit_triage`.

## What this skill does

Dispatches through `onex run-node node_coderabbit_triage`. The node owns thread
fetching, severity classification, reply generation, and thread resolution.
This shim contains no inline triage logic.

**Announce at start:** "I'm using the coderabbit-triage skill."

## Dispatch

```bash
uv run onex run-node node_coderabbit_triage --input '{
  "repo": "<owner/name>",
  "pr": <pr_number>,
  "dry_run": false
}'
```

On non-zero exit, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

Contract target: `node_coderabbit_triage`

Command topic: `onex.cmd.omnimarket.coderabbit-triage-start.v1`

Terminal event: `onex.evt.omnimarket.coderabbit-triage-completed.v1`
