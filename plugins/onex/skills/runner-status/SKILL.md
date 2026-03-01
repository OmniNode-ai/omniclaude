---
name: runner-status
description: Display health, version, and host metrics for all self-hosted GitHub Actions runners
version: 1.0.0
category: tooling
tags:
  - ci
  - runners
  - monitoring
  - github-actions
args: []
---

# Runner Status Skill

Surfaces per-runner health (GitHub API + Docker inspect) and host-level disk metrics for all
OmniNode self-hosted GitHub Actions runners. Alerts for degraded conditions are shown at the
top of the output when triggered.

## Quick Start

```
/runner-status
```

No arguments required. The skill queries the GitHub API and SSH-inspects the CI host
(`192.168.86.201`) automatically. <!-- onex-allow-internal-ip -->

## Output Format

When all runners are healthy:

```
Runner Status — 2026-03-01 14:23:07 UTC

┌─────────────────────────┬────────┬──────────────┬─────────────┬──────────┬────────────┬─────────┬────────┐
│ Runner                  │ Status │ Runner Group │ Runner Ver  │ gh Ver   │ kubectl    │ uv      │ Uptime │
├─────────────────────────┼────────┼──────────────┼─────────────┼──────────┼────────────┼─────────┼────────┤
│ omnibase-runner-1       │ ✓ idle │ omnibase-ci  │ 2.314.1     │ 2.44.1   │ v1.29.2    │ 0.5.4   │ 3d 2h  │
│ omnibase-runner-2       │ ✓ busy │ omnibase-ci  │ 2.314.1     │ 2.44.1   │ v1.29.2    │ 0.5.4   │ 3d 2h  │
│ omnibase-runner-3       │ ✓ idle │ omnibase-ci  │ 2.314.1     │ 2.44.1   │ v1.29.2    │ 0.5.4   │ 3d 2h  │
└─────────────────────────┴────────┴──────────────┴─────────────┴──────────┴────────────┴─────────┴────────┘

Host metrics (192.168.86.201): <!-- onex-allow-internal-ip -->
  /var/lib/docker disk: 42% used (126 GB / 300 GB)
  Docker build cache: 8.3 GB
```

When alerts are triggered:

```
⚠ ALERTS
  [OFFLINE] omnibase-runner-2 has been offline for 12 minutes (threshold: 5m)
  [DISK] /var/lib/docker at 74% (threshold: 70%)

Runner Status — 2026-03-01 14:23:07 UTC
  ...
```

## Per-Runner Data

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

### Label Keys

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

## Host-Level Metrics

In addition to per-runner data, the skill collects host-level metrics from the CI host:

### Disk Usage (`/var/lib/docker`)

```bash
ssh 192.168.86.201 "df -h /var/lib/docker" # onex-allow-internal-ip
```

Reports: total size, used, available, and usage percentage. Alerts if usage ≥ 70%.

### Docker Build Cache Size

```bash
ssh 192.168.86.201 "docker builder du --verbose 2>/dev/null | tail -1" # onex-allow-internal-ip
```

Reports total build cache size. No alert threshold — informational only.

## Alert Conditions

Alerts appear at the top of the output (before the status table) when any condition is met:

| Condition | Threshold | Alert Message |
|-----------|-----------|---------------|
| Runner offline | > 5 minutes | `[OFFLINE] {runner} has been offline for {N} minutes (threshold: 5m)` |
| Disk usage | ≥ 70% | `[DISK] /var/lib/docker at {N}% (threshold: 70%)` |
| Runner version lag | > 2 releases behind latest GitHub release | `[VERSION] {runner} running {current} — latest is {latest} ({N} releases behind)` |

### Runner Version Check

The skill compares the runner binary version (from Docker image label `org.omninode.runner.version`)
against the latest release from the GitHub Actions runner release feed:

```bash
gh api repos/actions/runner/releases/latest --jq '.tag_name'
```

If the running version is more than 2 releases behind the latest, an alert is emitted.
Version comparison uses semantic versioning (major.minor.patch).

### Offline Detection

"Offline" status is reported by the GitHub API. Duration is estimated from the
`last_activity` timestamp on the runner object. Alert fires when `now - last_activity > 5 minutes`.

## Implementation Steps

When this skill is invoked, execute the following:

### Step 1: Query GitHub API for runner list <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

```bash
gh api orgs/OmniNode-ai/actions/runners --jq '.runners[]'
```

This returns per-runner: `id`, `name`, `status` (`online`/`offline`), `busy`,
`runner_group_name`, `labels`, and timestamps.

### Step 2: SSH to CI host — collect Docker labels and uptime <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

```bash
# For each runner container (omnibase-runner-1, omnibase-runner-2, omnibase-runner-3):
ssh 192.168.86.201 "docker inspect omnibase-runner-1 --format '{{json .Config.Labels}}' && docker ps --filter name=omnibase-runner-1 --format '{{.Status}}'" # onex-allow-internal-ip
```

Parse `org.omninode.runner.version`, `org.omninode.gh.version`, `org.omninode.kubectl.version`,
`org.omninode.uv.version` from the labels JSON.

### Step 3: Collect host metrics <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

```bash
ssh 192.168.86.201 "df -h /var/lib/docker && docker builder du 2>/dev/null | tail -1" # onex-allow-internal-ip
```

### Step 4: Check latest runner version <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

```bash
gh api repos/actions/runner/releases/latest --jq '.tag_name'
```

Compare against the `org.omninode.runner.version` label from each container.

### Step 5: Evaluate alerts <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

For each alert condition (see Alert Conditions above), check and collect triggered alerts.

### Step 6: Render output <!-- ai-slop-ok: genuine process step heading in skill documentation, not LLM boilerplate -->

Print the output in the format shown in the Output Format section:
1. Alert block (if any alerts triggered) — shown first, with `⚠ ALERTS` header
2. Timestamp line
3. Per-runner table (all 7 fields)
4. Host metrics block

## Error Handling

| Error | Action |
|-------|--------|
| `gh api` returns 401 / 403 | Stop; print: "GitHub API auth failed. Run: `gh auth status`" |
| SSH connection refused/timeout | Stop; print: "Cannot reach CI host. Check VPN/network." |
| Container not found (`docker inspect` error) | Show runner row with `N/A` for label fields; add `[MISSING]` note |
| `docker builder du` unsupported | Skip build cache line silently; show `—` in output |

## See Also

- `runner-deploy` — Deploy or update runners
- `omnibase_infra/docker/runners/Dockerfile` — Defines image labels read by this skill (OMN-3275)
- `omnibase_infra/docker/docker-compose.runners.yml` — Runner compose config
- GitHub Actions self-hosted runner docs: https://docs.github.com/en/actions/hosting-your-own-runners
