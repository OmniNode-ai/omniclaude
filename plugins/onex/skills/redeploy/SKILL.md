---
description: Full post-release runtime redeploy — syncs bare clones, updates Dockerfile plugin pins, rebuilds Docker runtime, seeds Infisical, and verifies health
mode: full
version: 2.0.0
level: advanced
debug: false
category: workflow
tags: [deploy, runtime, docker, infisical, post-release]
author: OmniClaude Team
composable: false
inputs:
  - name: versions
    type: str
    description: "Comma-separated plugin version pins: pkg=version,pkg2=version2. Auto-detected if omitted."
    required: false
  - name: dry_run
    type: bool
    description: Print step commands without execution
    required: false
  - name: resume
    type: str
    description: Resume from first non-completed phase by run_id
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to $ONEX_STATE_DIR/skill-results/{context_id}/redeploy.json"
    fields:
      - status: success | failed | dry_run
      - run_id: str
args:
  - name: --versions
    description: "Comma-separated plugin pins: pkg=version,pkg2=version2. Auto-detected if omitted."
    required: false
  - name: --skip-sync
    description: Skip SYNC phase (bare clones already current)
    required: false
  - name: --skip-dockerfile-update
    description: Skip PIN_UPDATE phase
    required: false
  - name: --skip-infisical
    description: Skip INFISICAL phase
    required: false
  - name: --verify-only
    description: Skip to VERIFY phase only (runtime already running)
    required: false
  - name: --dry-run
    description: Print step commands without execution
    required: false
  - name: --resume
    description: Resume from first non-completed phase by run_id
    required: false
---

# Redeploy

**Announce at start:** "I'm using the redeploy skill."

## Usage

```
/redeploy
/redeploy --versions omniintelligence=0.8.0,omninode-claude=0.4.0
/redeploy --skip-sync
/redeploy --verify-only
/redeploy --dry-run
/redeploy --resume <run_id>
```

## Execution

### Step 1 — Parse arguments

- `--versions` → explicit plugin pins (auto-detected from latest git tags if omitted)
- `--skip-sync` → skip bare clone sync (already current)
- `--skip-dockerfile-update` → skip Dockerfile pin update
- `--skip-infisical` → skip Infisical secret seeding
- `--verify-only` → skip deploy phases, only run health checks
- `--dry-run` → print all commands without executing
- `--resume <run_id>` → resume from first non-completed phase in state file

### Step 2 — Initialize node (contract verification)

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok
uv run python -m omnimarket.nodes.node_redeploy \
  [--versions <pins>] \
  [--dry-run] \
  [--resume <run_id>]
```

Outputs `ModelRedeployStartCommand` JSON. Note: handler is a structural placeholder;
full migration tracked in OMN-8004.

### Step 3 — Execute redeploy phases

1. **SYNC**: `git -C ~/.omnibase/bare/<repo> fetch --all && git reset --hard origin/main` for each repo
2. **PIN_UPDATE**: Update Dockerfile `ARG <pkg>_VERSION=<version>` pins from `--versions` or auto-detected tags
3. **BUILD**: `docker compose build` in the deployed snapshot path
4. **INFISICAL**: Seed updated env vars into Infisical (unless `--skip-infisical`)
5. **RESTART**: `docker compose up -d` to roll out new images
6. **VERIFY**: Health-check all runtime services; confirm endpoints respond

### Step 4 — Report

Write result to `$ONEX_STATE_DIR/skill-results/{context_id}/redeploy.json`.
Display: phases completed, pins applied, health check results.

## Architecture

```
SKILL.md   -> thin shell (this file)
node       -> omnimarket/src/omnimarket/nodes/node_redeploy/ (structural placeholder)
contract   -> node_redeploy/contract.yaml
migration  -> OMN-8004 (full handler implementation)
```
