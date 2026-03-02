---
name: runner-deploy
description: Deploy or update self-hosted GitHub Actions runners on the OmniNode CI host <!-- onex-allow-internal-ip -->
version: 1.0.0
category: tooling
tags:
  - ci
  - runners
  - deployment
  - github-actions
args:
  - name: rebuild
    description: Force Docker image rebuild (use after Dockerfile changes)
    required: false
  - name: dry-run
    description: Show compose diff + which containers will be recreated, without deploying
    required: false
---

# Runner Deploy Skill

Deploy or update self-hosted GitHub Actions runners on the OmniNode CI host (`192.168.86.201`) <!-- onex-allow-internal-ip -->
with a single command from Claude Code.

## Quick Start

```
# Preview what would change (no deploy)
/runner-deploy --dry-run

# Deploy or update runners (uses cached Docker image)
/runner-deploy

# Force Docker image rebuild (use after Dockerfile changes)
/runner-deploy --rebuild
```

## Prerequisites

Before deploying, verify:

1. **GitHub org-level token scope** — check with:
   ```bash
   gh auth status
   # Must show: Token scopes: ...admin:org (or manage_runners:org)
   ```

2. **SSH key for the CI host in agent** (`192.168.86.201`) — check with: <!-- onex-allow-internal-ip -->
   ```bash
   ssh-add -l
   # Must show a key fingerprint; if empty run: ssh-add ~/.ssh/id_ed25519 (or your key)
   ```

   > Note: SSH key path is not configured via env var — it must be loaded into the running
   > ssh-agent. No local Docker client is required; all operations run remotely via SSH.

If either check fails, resolve before running `/runner-deploy`.

## Dry-Run Mode (`--dry-run`)

When `--dry-run` is specified, no changes are made. The skill will:

1. SSH to the CI host (`192.168.86.201`) and run `docker compose config` to display the current runner <!-- onex-allow-internal-ip -->
   compose configuration
2. Compare the Dockerfile `ARG` versions (Node, GitHub Actions runner) against the running
   container image labels to detect whether a rebuild would be triggered
3. Print which containers would be recreated by the deploy

Example dry-run output:

```
[DRY RUN] Runner deploy — 192.168.86.201 <!-- onex-allow-internal-ip -->

Current compose config:
  Services: omnibase-runner-1, omnibase-runner-2, omnibase-runner-3
  Image: omnibase-ci-runner:latest (built 2026-02-28)

Version check:
  Dockerfile ARG RUNNER_VERSION=2.314.1
  Running image label: runner_version=2.314.1  ✓ up to date
  Dockerfile ARG NODE_VERSION=20
  Running image label: node_version=20          ✓ up to date

Containers that would be recreated: none (image up to date)

Use /runner-deploy to apply, or /runner-deploy --rebuild to force image rebuild.
```

## Normal Deploy Behavior

When invoked without `--dry-run`:

1. **Prerequisite check** — verifies `gh auth status` shows org-level token scope and
   SSH key is available in agent
2. **Deploy** — SSH to the CI host (`192.168.86.201`) and invoke `deploy-runners.sh` <!-- onex-allow-internal-ip -->
   (with `--rebuild` flag forwarded if specified)
3. **Status check** — surfaces the final runner status table via the `runner-status` skill
   so you can confirm all runners registered successfully

### With `--rebuild`

Forces the Docker image to rebuild on the remote host before bringing containers up.
Use this when:
- Runner version (`RUNNER_VERSION` ARG) has been bumped in the Dockerfile
- Node/tool versions have changed
- The base image (`ubuntu:22.04`) needs refreshing
- Any other Dockerfile change has been made

Without `--rebuild`, the deploy uses the cached image (faster, safe for config-only changes).

## Script Location

The underlying deploy script lives in the `omnibase_infra` repository:

```
omnibase_infra/scripts/deploy-runners.sh
```

This skill wraps that script to make runner deployment accessible as a one-command operation
from any Claude Code session without needing to navigate to the `omnibase_infra` worktree
or remember the SSH invocation syntax.

## Implementation Steps

When this skill is invoked, execute the following:

### Step 1: Check prerequisites <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

```bash
# Verify GitHub token has org scope
gh auth status 2>&1 | grep -E "(Token scopes|admin:org|manage_runners)"

# Verify SSH key is loaded
ssh-add -l
```

If prerequisites fail, report clearly which check failed and how to fix it. Do not proceed.

### Step 2 (dry-run only): Show compose diff <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

```bash
# SSH to host and show compose config (CI_HOST=192.168.86.201) # onex-allow-internal-ip
ssh 192.168.86.201 "cd ~/omnibase_infra/docker && docker compose -f docker-compose.runners.yml config" # onex-allow-internal-ip

# Compare Dockerfile ARG versions to running image labels
ssh 192.168.86.201 "docker inspect omnibase-runner-1 --format '{{.Config.Labels}}' 2>/dev/null || echo 'container not running'" # onex-allow-internal-ip
ssh 192.168.86.201 "grep -E '^ARG (RUNNER|NODE)_VERSION' ~/omnibase_infra/docker/runners/Dockerfile" # onex-allow-internal-ip
```

Print a clear summary of: current state, what would change, and which containers would be
recreated. Exit without making changes.

### Step 3 (deploy only): Run deploy-runners.sh <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

```bash
REBUILD_FLAG=""
# If --rebuild was specified:
REBUILD_FLAG="--rebuild"

ssh 192.168.86.201 "cd ~/omnibase_infra && bash scripts/deploy-runners.sh ${REBUILD_FLAG}" # onex-allow-internal-ip
```

Capture and display the full output. If the script exits non-zero, report the error and stop.

### Step 4 (deploy only): Surface status <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

Invoke `runner-status` to confirm all runners registered successfully:

```
/runner-status
```

## Error Handling

| Error | Action |
|-------|--------|
| `gh auth status` shows no org scope | Stop; print: "GitHub token missing org scope. Run: `gh auth refresh -s admin:org`" |
| `ssh-add -l` returns "The agent has no identities" | Stop; print: "No SSH key in agent. Run: `ssh-add ~/.ssh/<your_key>`" |
| SSH connection refused/timeout | Stop; print: "Cannot reach CI host. Check VPN/network." |
| `deploy-runners.sh` exits non-zero | Stop; print full script output; suggest `--rebuild` if image issue suspected |
| Runner fails to register (seen in `runner-status`) | Print warning; link to GitHub Actions runner registration docs |

## See Also

- `runner-status` — Display current runner registration status
- `omnibase_infra/scripts/deploy-runners.sh` — Underlying deploy script
- `omnibase_infra/docker/runners/Dockerfile` — Runner image definition
- `omnibase_infra/docker/docker-compose.runners.yml` — Runner compose config
