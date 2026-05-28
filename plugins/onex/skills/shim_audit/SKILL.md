---
description: Scan all OmniNode repos for expired or expiring @shim decorator annotations and create Linear tickets for each expired shim. Dispatches to node_shim_scanner; creates no tickets in dry-run mode.
mode: full
version: 1.0.0
level: advanced
debug: false
category: verification
tags:
  - shim
  - tech-debt
  - sweep
  - close-out
  - dispatch-only
  - routing-enforced
author: omninode
composable: true
args:
  - name: --dry-run
    description: "Report findings without creating Linear tickets (default: false)"
    required: false
  - name: --repos
    description: "Comma-separated repo names to scan (default: all repos under OMNI_HOME)"
    required: false
  - name: --warn-days
    description: "Days before expiry to report as EXPIRING (default: 30)"
    required: false
---

# /onex:shim_audit — Shim Lifecycle Audit

**Skill ID**: `onex:shim-audit`
**Version**: 1.0.0
**Backing node**: `node_shim_scanner`

## Changelog

- **1.0.0** — Initial implementation (OMN-4420). Dispatch-only shim over node_shim_scanner.

## What this skill does

Scans Python source files across OmniNode repos for `@shim` decorator annotations,
classifies each as EXPIRED / EXPIRING / ACTIVE, and creates Linear tickets for
every expired shim. Logic lives entirely in `node_shim_scanner`.

**Announce at start:** "I'm using the shim-audit skill."

## Dispatch

```bash
uv run onex run-node node_shim_scanner --input '{
  "paths": ["<repo_path>"],
  "reference_date": null,
  "warn_days_before_expiry": <warn_days>
}'
```

Repeat for each repo. Aggregate results across all repos.

## Arguments

| Arg | Default | Effect |
|-----|---------|--------|
| `--dry-run` | false | Skip ticket creation; print findings only |
| `--repos` | all | Limit scan to named repos (comma-separated) |
| `--warn-days` | 30 | Days before expiry treated as EXPIRING |

## Post-scan actions

For each finding with `status == EXPIRED`:
1. Check if a Linear ticket already exists for `ticket_id` (skip if already open).
2. If `--dry-run` is false, create a Linear ticket:
   - Title: `Remove expired @shim: <function_name> in <file_path>`
   - Body: ticket_id, expires_on, reason, replacement, file_path, line_number
   - Priority: High

On non-zero exit from `onex run-node`, surface the error directly. Do not produce prose.

## Wire Schema

Contract target: `node_shim_scanner`

Command topic: `onex.cmd.omnimarket.shim-scan-start.v1`

Terminal event: `onex.evt.omnimarket.shim-scan-completed.v1`
