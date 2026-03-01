---
name: redeploy
description: Full post-release runtime redeploy — syncs bare clones, updates Dockerfile plugin pins, rebuilds Docker runtime, seeds Infisical, and verifies health
version: 1.0.0
category: workflow
tags: [deploy, runtime, docker, infisical, post-release]
author: OmniClaude Team
composable: false
inputs:
  - name: versions
    type: str
    description: "Comma-separated plugin version pins: omniintelligence=0.8.0,omninode-claude=0.4.0,omninode-memory=0.6.1"
    required: true
  - name: skip_sync
    type: bool
    description: Skip SYNC phase (bare clones already current)
    required: false
  - name: skip_dockerfile_update
    type: bool
    description: Skip PIN_UPDATE phase
    required: false
  - name: skip_infisical
    type: bool
    description: Skip INFISICAL phase unconditionally
    required: false
  - name: worktree_ticket
    type: str
    description: "Worktree name prefix (default: redeploy-<run_id>)"
    required: false
  - name: verify_only
    type: bool
    description: Skip to VERIFY phase only (assumes runtime already running)
    required: false
  - name: dry_run
    type: bool
    description: Print step commands without execution
    required: false
  - name: resume
    type: str
    description: Resume from first non-completed phase in state file by run_id
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to ~/.claude/skill-results/{context_id}/redeploy.json"
    fields:
      - status: success | failed | dry_run
      - run_id: str
      - phases: "dict[str, phase_status]"
      - pins_applied: "dict[str, str] | null"
args:
  - name: --versions
    description: "Comma-separated plugin pins: pkg=version,pkg2=version2"
    required: true
  - name: --skip-sync
    description: Skip SYNC phase
    required: false
  - name: --skip-dockerfile-update
    description: Skip PIN_UPDATE phase
    required: false
  - name: --skip-infisical
    description: Skip INFISICAL phase unconditionally
    required: false
  - name: --worktree-ticket
    description: "Worktree name prefix (default: redeploy-<run_id>)"
    required: false
  - name: --verify-only
    description: Skip all phases except VERIFY
    required: false
  - name: --dry-run
    description: Print step commands, no execution
    required: false
  - name: --resume
    description: Resume from state file by run_id
    required: false
---

# Redeploy

## Overview

Full post-release runtime redeploy for the OmniNode platform. Runs after a coordinated
release to sync all bare clones, update `Dockerfile.runtime` plugin pins, rebuild and
restart Docker runtime services, optionally seed Infisical with new contract keys,
and verify that health endpoints and pinned package versions match expectations.

**Announce at start:** "I'm using the redeploy skill to redeploy the runtime."

## Quick Start

```
/redeploy --versions "omniintelligence=0.8.0,omninode-claude=0.4.0,omninode-memory=0.6.1"
/redeploy --versions "omniintelligence=0.8.0" --skip-sync --dry-run
/redeploy --verify-only --versions "omniintelligence=0.8.0,omninode-claude=0.4.0,omninode-memory=0.6.1"
/redeploy --resume redeploy-20260301-abc123 --versions "omniintelligence=0.8.0,omninode-claude=0.4.0,omninode-memory=0.6.1"
```

## Phase Sequence

| # | Phase | Core Action | Idempotency |
|---|-------|-------------|-------------|
| 1 | `SYNC` | `pull-all.sh` — fast-forward all bare clones on `main` | Safe: ff-only is a no-op if already current |
| 2 | `ENV_CHECK` | Per-phase env validation | Read-only, always safe |
| 3 | `WORKTREE` | Create `omni_worktrees/<ticket>/omnibase_infra` from main HEAD | Skip if path exists and branch matches |
| 4 | `PIN_UPDATE` | Run `update-plugin-pins.py` to rewrite `Dockerfile.runtime` version pins | Skip if already at target versions |
| 5 | `DEPLOY` | `deploy-runtime.sh --execute --restart` from worktree | Safe: rsync + rebuild + `--force-recreate` |
| 6 | `INFISICAL` | Seed new contract keys to Infisical | `seed-infisical.py` is idempotent |
| 7 | `VERIFY` | curl health endpoints + in-container version checks | Read-only, always safe |
| 8 | `NOTIFY` | Slack via `node_slack_alerter_effect` (FULL_ONEX only) | Idempotent (run_id in message) |

## ENV_CHECK: Required Variables per Phase

| Phase Gated | Required Vars | On Failure |
|-------------|--------------|------------|
| SYNC | `OMNI_HOME` (default: `/Volumes/PRO-G40/Code/omni_home`) | Fail with message | <!-- local-path-ok -->
| DEPLOY | `POSTGRES_PASSWORD`, `KAFKA_BOOTSTRAP_SERVERS` | Fail before deploy |
| INFISICAL | `INFISICAL_ADDR`, `INFISICAL_CLIENT_ID`, `INFISICAL_CLIENT_SECRET` | Skip if `INFISICAL_ADDR` unset; fail if set but creds missing |

## Tier-Aware Notifications

| Tier | Notification |
|------|-------------|
| `FULL_ONEX` | Slack via `node_slack_alerter_effect` (start + done) |
| `EVENT_BUS` | stdout only (no Kafka notification topic) |
| `STANDALONE` | stdout only |

Tier detection: see `@_lib/tier-routing/helpers.md`.

## State File

`~/.claude/state/redeploy/<run_id>.json` — written atomically after each phase completes.

```json
{
  "run_id": "redeploy-20260301-abc123",
  "worktree_path": "/Volumes/PRO-G40/Code/omni_worktrees/redeploy-20260301-abc123/omnibase_infra", // local-path-ok
  "worktree_ref": "main",
  "versions_requested": {"omniintelligence": "0.8.0", "omninode-claude": "0.4.0"},
  "phases": {
    "SYNC":       {"status": "completed", "ts": "2026-03-01T10:00:00Z"},
    "ENV_CHECK":  {"status": "completed", "ts": "2026-03-01T10:00:01Z"},
    "WORKTREE":   {"status": "completed", "ts": "2026-03-01T10:00:05Z", "path": "..."},
    "PIN_UPDATE": {"status": "completed", "ts": "2026-03-01T10:00:10Z", "pins_applied": {"omniintelligence": "0.8.0"}},
    "DEPLOY":     {"status": "pending"},
    "INFISICAL":  {"status": "pending"},
    "VERIFY":     {"status": "pending"},
    "NOTIFY":     {"status": "pending"}
  }
}
```

Resume: `--resume <run_id>` skips all phases with `status: completed`.
Cleanup: worktree is retained; pass `--cleanup` (v2) to remove after success.

## VERIFY Phase Details

Beyond `curl /health`, checks in-container package versions against `--versions` input:

```bash
docker exec omninode-runtime uv pip show omniintelligence | grep Version
docker exec omninode-runtime uv pip show omninode-claude   | grep Version
docker exec omninode-runtime uv pip show omninode-memory   | grep Version
```

Version mismatch causes VERIFY to fail explicitly (catches silent build failure or `--restart`-only runs).

## INFISICAL Phase Logic

```
IF INFISICAL_ADDR unset -> status: skipped_no_infisical (not an error)
IF INFISICAL_ADDR set AND creds missing -> fail before DEPLOY (validated in ENV_CHECK)
IF INFISICAL_ADDR set AND creds present:
  IF sync-omnibase-env.sh exists in worktree -> run it (dapper-soaring-falcon wrapper)
  ELSE -> uv run python seed-infisical.py --contracts-dir .../nodes --execute
```

## Skill Result Output

Written to `~/.claude/skill-results/{context_id}/redeploy.json`:

```json
{
  "skill": "redeploy",
  "status": "success",
  "run_id": "redeploy-20260301-abc123",
  "phases": {
    "SYNC": "completed",
    "ENV_CHECK": "completed",
    "WORKTREE": "completed",
    "PIN_UPDATE": "completed",
    "DEPLOY": "completed",
    "INFISICAL": "skipped_no_infisical",
    "VERIFY": "completed",
    "NOTIFY": "completed"
  },
  "pins_applied": {
    "omniintelligence": "0.8.0",
    "omninode-claude": "0.4.0",
    "omninode-memory": "0.6.1"
  }
}
```

**Status values**: `success` | `failed` | `dry_run`

## v1 Constraints

- `--versions` is required; no PyPI auto-detection of latest versions
- No `--no-deps` inference; existing Dockerfile install flags are preserved as-is
- `--cleanup` flag not implemented in v1 (worktree retained after success)

## See Also

- `prompt.md` — authoritative phase execution logic
- `release` skill — run before redeploy to coordinate version bumps across repos
- `_lib/tier-routing/helpers.md` — tier detection
- `_lib/slack-gate/helpers.md` — Slack credential resolution
- `omnibase_infra/scripts/deploy-runtime.sh` — DEPLOY phase core script
- `omnibase_infra/scripts/update-plugin-pins.py` — PIN_UPDATE phase helper
- `omnibase_infra/scripts/seed-infisical.py` — INFISICAL phase fallback
