---
description: Full autonomous audit-debug-fix loop for all dashboard pages — node dispatch with built-in HTTP recon, parallel systematic-debug, fix, PR, Linear ticket, iterate until clean. Supports local and cloud targets with optional post-fix redeployment.
mode: full
version: 2.0.0
level: advanced
debug: false
category: quality
tags:
  - dashboard
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
    description: "Skip re-audit after fixes land"
    required: false
  - name: --triage-only
    description: "Run node dispatch + triage only, no fixes"
    required: false
  - name: --fix-only
    description: "Skip node dispatch, use existing triage report from $ONEX_STATE_DIR/dashboard-sweep/latest/"
    required: false
  - name: --max-iterations
    description: "Maximum fix iterations before stopping (default: 3)"
    required: false
  - name: --dry-run
    description: "Preview plan without dispatching fix agents, creating PRs, or Linear tickets"
    required: false
  - name: --deploy
    description: "Auto-deploy after fixes: restart local containers or trigger cloud redeploy"
    required: false
  - name: --pages
    description: "JSON array of pre-classified page objects (ModelPageInput shape) to pass directly to the node, skipping HTTP recon"
    required: false
---

# Dashboard Sweep

**Announce at start:** "I'm using the dashboard-sweep skill to audit and fix all dashboard issues."

## Usage

```
/dashboard-sweep                           # Full sweep of localhost:3000
/dashboard-sweep --target cloud            # cloud: https://dash.dev.omninode.ai
/dashboard-sweep --url http://localhost:3000
/dashboard-sweep --triage-only             # Node dispatch + triage only, no fixes
/dashboard-sweep --fix-only                # Skip dispatch, use existing triage
/dashboard-sweep --dry-run
/dashboard-sweep --max-iterations 5
/dashboard-sweep --deploy
```

## Execution

### Step 1 — Parse arguments

- `--target` → `local` (default) or `cloud`
- `--url` → explicit URL override (wins over `--target`)
- `--pages` → pre-classified ModelPageInput objects; passed to node directly (skips HTTP recon)
- Other flags pass through to the orchestration phases

### Step 2 — Dispatch to node

Pass the resolved URL to the node. The node handles all HTTP recon internally:

```bash
onex run-node node_dashboard_sweep \
  --input '{"base_url": "{url}", "max_iterations": 3, "dry_run": false}' \
  --timeout 300
```

When `--pages` is supplied instead:

```bash
onex run-node node_dashboard_sweep \
  --input '{"pages": [...], "max_iterations": 3, "dry_run": false}' \
  --timeout 300
```

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose. Exit 0 = clean, exit 1 = issues found.

### Step 3 — Fix loop (unless `--triage-only` or `--dry-run`)

Dispatch one `systematic-debugging` agent per `CODE_BUG`/`DATA_PIPELINE`/`SCHEMA_MISMATCH` domain.
All dispatches happen in a single message for parallelism. Wait for all agents, then:
- Create PRs + Linear tickets
- Deploy if `--deploy`
- Iterate up to `--max-iterations`

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
SKILL.md   -> thin dispatcher: resolve URL -> node dispatch -> render results
node       -> omnimarket/src/omnimarket/nodes/node_dashboard_sweep/
contract   -> node_dashboard_sweep/contract.yaml
```

All HTTP recon, classification, and triage logic lives in the node handler.
The skill resolves the target URL and dispatches; it does not perform any
inline curl, HTTP checks, or endpoint probing.
