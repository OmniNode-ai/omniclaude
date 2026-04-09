---
description: Full autonomous audit-debug-fix loop for all dashboard pages — Playwright recon, parallel systematic-debug, fix, PR, Linear ticket, re-audit, iterate until clean. Supports local and cloud targets with optional post-fix redeployment.
mode: full
version: 2.0.0
level: advanced
debug: false
category: quality
tags:
  - dashboard
  - playwright
  - debugging
  - parallel
  - audit
  - fix-loop
  - cloud
  - deploy
author: OmniClaude Team
composable: true
args:
  - name: --target
    description: "Deployment target: local (default: http://localhost:3000) or cloud (https://dash.dev.omninode.ai)"
    required: false
  - name: --url
    description: "Explicit dashboard base URL override (overrides --target)"
    required: false
  - name: --skip-reaudit
    description: "Skip Phase 5 re-audit after fixes land"
    required: false
  - name: --triage-only
    description: "Run Phase 1+2 only (recon + triage), no fixes"
    required: false
  - name: --fix-only
    description: "Skip recon, use existing triage report from $ONEX_STATE_DIR/dashboard-sweep/latest/"
    required: false
  - name: --max-iterations
    description: "Maximum fix-reaudit iterations before stopping (default: 3)"
    required: false
  - name: --dry-run
    description: "Preview plan without dispatching fix agents, creating PRs, or Linear tickets"
    required: false
  - name: --deploy
    description: "Auto-deploy after fixes: restart local containers or trigger cloud redeploy"
    required: false
  - name: --pages
    description: "JSON array of pre-collected page objects (route, status_code, visible_text, console_errors)"
    required: false
---

# Dashboard Sweep

**Announce at start:** "I'm using the dashboard-sweep skill to audit and fix all dashboard issues."

## Usage

```
/dashboard-sweep                           # Full sweep of localhost:3000
/dashboard-sweep --target cloud            # cloud: https://dash.dev.omninode.ai
/dashboard-sweep --url http://localhost:3000
/dashboard-sweep --triage-only             # Phase 1+2 only, no fixes
/dashboard-sweep --fix-only                # Skip recon, use existing triage
/dashboard-sweep --dry-run
/dashboard-sweep --max-iterations 5
/dashboard-sweep --deploy
```

## Execution

### Step 1 — Parse arguments

- `--target` → `local` (default) or `cloud`
- `--url` → explicit URL override (wins over `--target`)
- `--pages` → JSON array of pre-collected page data (skip Playwright recon)
- Other flags pass through to the orchestration phases

### Step 2 — Recon (Phase 1+2, unless `--fix-only`)

Run Playwright recon across all dashboard routes. For each page:
1. Navigate, wait for `networkidle`, capture screenshot + console errors
2. Classify: `HEALTHY` | `EMPTY` | `MOCK` | `BROKEN` | `FLAG_GATED`
3. Group broken pages into problem domains; assign fix tier per domain

When `--pages` is provided, skip live Playwright and pass pre-collected data directly to the node:

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok
uv run python -m omnimarket.nodes.node_dashboard_sweep \
  --pages '<json-array>' \
  [--max-iterations <n>] \
  [--dry-run]
```

Capture stdout (JSON: `DashboardSweepResult`). Exit 0 = clean, exit 1 = issues found.

### Step 3 — Fix loop (Phase 3-6, unless `--triage-only` or `--dry-run`)

Dispatch one `systematic-debugging` agent per `CODE_BUG`/`DATA_PIPELINE`/`SCHEMA_MISMATCH` domain.
All dispatches happen in a single message for parallelism. Wait for all agents, then:
- Create PRs + Linear tickets (Phase 4)
- Deploy if `--deploy` (Phase 4b)
- Re-audit with Playwright (Phase 5)
- Iterate up to `--max-iterations` (Phase 6)

### Step 4 — Render report

Display final page status table, fixes applied, PRs merged, tickets created, and any remaining open items.

## Page Classifications

| Status | Meaning |
|--------|---------|
| `HEALTHY` | Real data present, live timestamps |
| `EMPTY` | Renders cleanly, no data (fixable) |
| `MOCK` | Hardcoded placeholder values |
| `BROKEN` | JS error, HTTP 5xx, fetch failure |
| `FLAG_GATED` | Correct pipeline, env var unset |

## Fix Tiers

| Tier | Action |
|------|--------|
| `CODE_BUG` | Dispatch debug agent |
| `DATA_PIPELINE` | Dispatch debug agent |
| `SCHEMA_MISMATCH` | Dispatch debug agent |
| `FEATURE_GAP` | Create Linear ticket only |
| `FLAG_GATE` | Document, no code fix |

## Architecture

```
SKILL.md   -> thin shell (this file)
node       -> omnimarket/src/omnimarket/nodes/node_dashboard_sweep/ (classify + triage logic)
contract   -> node_dashboard_sweep/contract.yaml
```
