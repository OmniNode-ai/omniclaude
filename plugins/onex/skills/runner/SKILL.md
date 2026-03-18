---
description: GitHub Actions runner management — deploy, update, and monitor self-hosted runners
version: 1.0.0
level: advanced
debug: false
category: infrastructure
tags:
  - runner
  - github-actions
  - ci
  - deploy
  - status
author: OmniClaude Team
composable: true
args:
  - name: subcommand
    description: "Mode: status (check health/metrics) or deploy (deploy/update runners)"
    required: true
  - name: --host
    description: "Target host for deploy operations"
    required: false
  - name: --version
    description: "Runner version for deploy operations"
    required: false
  - name: --rebuild
    description: "Force Docker image rebuild (use after Dockerfile changes)"
    required: false
  - name: --dry-run
    description: "Show compose diff + which containers will be recreated, without deploying"
    required: false
mode: full
---

# Runner

## Overview

GitHub Actions self-hosted runner management. Two modes:
- **status**: Display health, version, and host metrics for all runners
- **deploy**: Deploy or update runners on the CI host

## status

Surfaces per-runner health (GitHub API + Docker inspect) and host-level disk metrics for all
OmniNode self-hosted GitHub Actions runners. Alerts for degraded conditions are shown at the
top of the output when triggered.

### Quick Start

```
/runner status
```

No arguments required. The skill queries the GitHub API and SSH-inspects the CI host
(`192.168.86.201`) automatically. <!-- onex-allow-internal-ip -->

### Output Format

When all runners are healthy:

```
Runner Status — 2026-03-01 14:23:07 UTC

+--------------------------+--------+--------------+-------------+----------+------------+---------+--------+
| Runner                   | Status | Runner Group | Runner Ver  | gh Ver   | kubectl    | uv      | Uptime |
+--------------------------+--------+--------------+-------------+----------+------------+---------+--------+
| omnibase-runner-1        | idle   | omnibase-ci  | 2.314.1     | 2.44.1   | v1.29.2    | 0.5.4   | 3d 2h  |
| omnibase-runner-2        | busy   | omnibase-ci  | 2.314.1     | 2.44.1   | v1.29.2    | 0.5.4   | 3d 2h  |
| omnibase-runner-3        | idle   | omnibase-ci  | 2.314.1     | 2.44.1   | v1.29.2    | 0.5.4   | 3d 2h  |
+--------------------------+--------+--------------+-------------+----------+------------+---------+--------+

Host metrics (192.168.86.201): <!-- onex-allow-internal-ip -->
  /var/lib/docker disk: 42% used (126 GB / 300 GB)
  Docker build cache: 8.3 GB
```

When alerts are triggered:

```
ALERTS
  [OFFLINE] omnibase-runner-2 has been offline for 12 minutes (threshold: 5m)
  [DISK] /var/lib/docker at 74% (threshold: 70%)

Runner Status — 2026-03-01 14:23:07 UTC
  ...
```

### Per-Runner Data

The following fields are shown for each runner:

| Field | Source | Notes |
|-------|--------|-------|
| Runner name | GitHub API | Container hostname / runner display name |
| Status | GitHub API | `idle`, `busy`, or `offline` |
| Runner group | GitHub API | Must be `omnibase-ci`; flagged if different |
| Runner binary version | Docker image label `org.omninode.runner.version` | Set in Dockerfile ARG |
| gh CLI version | Docker image label `org.omninode.gh.version` | Set in Dockerfile ARG |
| kubectl version | Docker image label `org.omninode.kubectl.version` | Set in Dockerfile ARG |
| uv version | Docker image label `org.omninode.uv.version` | Set in Dockerfile ARG |
| Container uptime | `docker ps --format "{{.Status}}"` on host | Via SSH |

#### Label Keys

The Docker image labels are defined in the runner Dockerfile (OMN-3275). The skill reads them
deterministically using these exact keys:

```
org.omninode.runner.version
org.omninode.gh.version
org.omninode.kubectl.version
org.omninode.uv.version
```

Read via:

```bash
# SSH to CI host, inspect each container # onex-allow-internal-ip
ssh 192.168.86.201 "docker inspect omnibase-runner-1 --format '{{json .Config.Labels}}'" # onex-allow-internal-ip
```

### Host-Level Metrics

In addition to per-runner data, the skill collects host-level metrics from the CI host:

#### Disk Usage (`/var/lib/docker`)

```bash
ssh 192.168.86.201 "df -h /var/lib/docker" # onex-allow-internal-ip
```

Reports: total size, used, available, and usage percentage. Alerts if usage >= 70%.

#### Docker Build Cache Size

```bash
ssh 192.168.86.201 "docker builder du --verbose 2>/dev/null | tail -1" # onex-allow-internal-ip
```

Reports total build cache size. No alert threshold -- informational only.

### Alert Conditions

Alerts appear at the top of the output (before the status table) when any condition is met:

| Condition | Threshold | Alert Message |
|-----------|-----------|---------------|
| Runner offline | > 5 minutes | `[OFFLINE] {runner} has been offline for {N} minutes (threshold: 5m)` |
| Disk usage | >= 70% | `[DISK] /var/lib/docker at {N}% (threshold: 70%)` |
| Runner version lag | > 2 releases behind latest GitHub release | `[VERSION] {runner} running {current} -- latest is {latest} ({N} releases behind)` |

#### Runner Version Check

The skill compares the runner binary version (from Docker image label `org.omninode.runner.version`)
against the latest release from the GitHub Actions runner release feed:

```bash
gh api repos/actions/runner/releases/latest --jq '.tag_name'
```

If the running version is more than 2 releases behind the latest, an alert is emitted.
Version comparison uses semantic versioning (major.minor.patch).

#### Offline Detection

"Offline" status is reported by the GitHub API. Duration is estimated from the
`last_activity` timestamp on the runner object. Alert fires when `now - last_activity > 5 minutes`.

### Status Implementation Steps

When `status` is invoked, execute the following:

#### Step 1: Query GitHub API for runner list <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

```bash
gh api orgs/OmniNode-ai/actions/runners --jq '.runners[]'
```

This returns per-runner: `id`, `name`, `status` (`online`/`offline`), `busy`,
`runner_group_name`, `labels`, and timestamps.

#### Step 2: SSH to CI host -- collect Docker labels and uptime <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

```bash
# For each runner container (omnibase-runner-1, omnibase-runner-2, omnibase-runner-3):
ssh 192.168.86.201 "docker inspect omnibase-runner-1 --format '{{json .Config.Labels}}' && docker ps --filter name=omnibase-runner-1 --format '{{.Status}}'" # onex-allow-internal-ip
```

Parse `org.omninode.runner.version`, `org.omninode.gh.version`, `org.omninode.kubectl.version`,
`org.omninode.uv.version` from the labels JSON.

#### Step 3: Collect host metrics <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

```bash
ssh 192.168.86.201 "df -h /var/lib/docker && docker builder du 2>/dev/null | tail -1" # onex-allow-internal-ip
```

#### Step 4: Check latest runner version <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

```bash
gh api repos/actions/runner/releases/latest --jq '.tag_name'
```

Compare against the `org.omninode.runner.version` label from each container.

#### Step 5: Evaluate alerts <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

For each alert condition (see Alert Conditions above), check and collect triggered alerts.

#### Step 6: Render output <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

Print the output in the format shown in the Output Format section:
1. Alert block (if any alerts triggered) -- shown first, with `ALERTS` header
2. Timestamp line
3. Per-runner table (all 7 fields)
4. Host metrics block

## deploy

Deploy or update self-hosted GitHub Actions runners on the OmniNode CI host (`192.168.86.201`) <!-- onex-allow-internal-ip -->
with a single command from Claude Code.

### Quick Start

```
# Preview what would change (no deploy)
/runner deploy --dry-run

# Deploy or update runners (uses cached Docker image)
/runner deploy

# Force Docker image rebuild (use after Dockerfile changes)
/runner deploy --rebuild
```

### Prerequisites

Before deploying, verify:

1. **GitHub org-level token scope** -- check with:
   ```bash
   gh auth status
   # Must show: Token scopes: ...admin:org (or manage_runners:org)
   ```

2. **SSH key for the CI host in agent** (`192.168.86.201`) -- check with: <!-- onex-allow-internal-ip -->
   ```bash
   ssh-add -l
   # Must show a key fingerprint; if empty run: ssh-add ~/.ssh/id_ed25519 (or your key)
   ```

   > Note: SSH key path is not configured via env var -- it must be loaded into the running
   > ssh-agent. No local Docker client is required; all operations run remotely via SSH.

If either check fails, resolve before running `/runner deploy`.

### Dry-Run Mode (`--dry-run`)

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
  Running image label: runner_version=2.314.1  up to date
  Dockerfile ARG NODE_VERSION=20
  Running image label: node_version=20          up to date

Containers that would be recreated: none (image up to date)

Use /runner deploy to apply, or /runner deploy --rebuild to force image rebuild.
```

### Normal Deploy Behavior

When invoked without `--dry-run`:

1. **Prerequisite check** -- verifies `gh auth status` shows org-level token scope and
   SSH key is available in agent
2. **Deploy** -- SSH to the CI host (`192.168.86.201`) and invoke `deploy-runners.sh` <!-- onex-allow-internal-ip -->
   (with `--rebuild` flag forwarded if specified)
3. **Status check** -- surfaces the final runner status table via `runner status`
   so you can confirm all runners registered successfully

#### With `--rebuild`

Forces the Docker image to rebuild on the remote host before bringing containers up.
Use this when:
- Runner version (`RUNNER_VERSION` ARG) has been bumped in the Dockerfile
- Node/tool versions have changed
- The base image (`ubuntu:22.04`) needs refreshing
- Any other Dockerfile change has been made

Without `--rebuild`, the deploy uses the cached image (faster, safe for config-only changes).

### Script Location

The underlying deploy script lives in the `omnibase_infra` repository:

```
omnibase_infra/scripts/deploy-runners.sh
```

This skill wraps that script to make runner deployment accessible as a one-command operation
from any Claude Code session without needing to navigate to the `omnibase_infra` worktree
or remember the SSH invocation syntax.

### Deploy Implementation Steps

When `deploy` is invoked, execute the following:

#### Step 1: Check prerequisites <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

```bash
# Verify GitHub token has org scope
gh auth status 2>&1 | grep -E "(Token scopes|admin:org|manage_runners)"

# Verify SSH key is loaded
ssh-add -l
```

If prerequisites fail, report clearly which check failed and how to fix it. Do not proceed.

#### Step 2 (dry-run only): Show compose diff <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

```bash
# SSH to host and show compose config (CI_HOST=192.168.86.201) # onex-allow-internal-ip
ssh 192.168.86.201 "cd ~/omnibase_infra/docker && docker compose -f docker-compose.runners.yml config" # onex-allow-internal-ip

# Compare Dockerfile ARG versions to running image labels
ssh 192.168.86.201 "docker inspect omnibase-runner-1 --format '{{.Config.Labels}}' 2>/dev/null || echo 'container not running'" # onex-allow-internal-ip
ssh 192.168.86.201 "grep -E '^ARG (RUNNER|NODE)_VERSION' ~/omnibase_infra/docker/runners/Dockerfile" # onex-allow-internal-ip
```

Print a clear summary of: current state, what would change, and which containers would be
recreated. Exit without making changes.

#### Step 3 (deploy only): Run deploy-runners.sh <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

```bash
REBUILD_FLAG=""
# If --rebuild was specified:
REBUILD_FLAG="--rebuild"

ssh 192.168.86.201 "cd ~/omnibase_infra && bash scripts/deploy-runners.sh ${REBUILD_FLAG}" # onex-allow-internal-ip
```

Capture and display the full output. If the script exits non-zero, report the error and stop.

#### Step 4 (deploy only): Surface status <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

Invoke `runner status` to confirm all runners registered successfully:

```
/runner status
```

## Error Handling

| Error | Action |
|-------|--------|
| `gh auth status` shows no org scope | Stop; print: "GitHub token missing org scope. Run: `gh auth refresh -s admin:org`" |
| `ssh-add -l` returns "The agent has no identities" | Stop; print: "No SSH key in agent. Run: `ssh-add ~/.ssh/<your_key>`" |
| SSH connection refused/timeout | Stop; print: "Cannot reach CI host. Check VPN/network." |
| `deploy-runners.sh` exits non-zero | Stop; print full script output; suggest `--rebuild` if image issue suspected |
| Runner fails to register (seen in `runner status`) | Print warning; link to GitHub Actions runner registration docs |
| `gh api` returns 401 / 403 | Stop; print: "GitHub API auth failed. Run: `gh auth status`" |
| Container not found (`docker inspect` error) | Show runner row with `N/A` for label fields; add `[MISSING]` note |
| `docker builder du` unsupported | Skip build cache line silently; show `--` in output |

## See Also

- `omnibase_infra/scripts/deploy-runners.sh` -- Underlying deploy script
- `omnibase_infra/docker/runners/Dockerfile` -- Runner image definition (OMN-3275)
- `omnibase_infra/docker/docker-compose.runners.yml` -- Runner compose config
- GitHub Actions self-hosted runner docs: https://docs.github.com/en/actions/hosting-your-own-runners
