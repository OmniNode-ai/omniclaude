---
description: Overnight session readiness check — verifies drive mount, machine identity, zombie agents, merge queue health, and required env vars, then emits a go/no-go verdict
version: 1.0.0
mode: full
level: intermediate
debug: false
category: operations
tags:
  - preflight
  - session-readiness
  - overnight
  - environment
  - health-check
author: OmniClaude Team
composable: true
args:
  - name: --skip-merge-queue
    description: "Skip merge queue health checks (faster, useful when GitHub API is rate-limited)"
    required: false
  - name: --skip-watchdog
    description: "Skip zombie agent detection via dispatch_watchdog"
    required: false
---

# Preflight

Run this skill before any overnight or long-running session. It performs 6 sequential checks
and emits a single go/no-go verdict. All checks are mandatory — a single FAIL blocks the verdict.

## CRITICAL RULES

- **DO NOT check `ANTHROPIC_API_KEY`** — Claude Code uses OAuth, not API keys (OMN-7467).
  Any check for `ANTHROPIC_API_KEY` is incorrect and must be removed.
- All 6 checks must complete before emitting the verdict.
- FAIL on any check means the verdict is NO-GO. Do not proceed with the overnight session.

---

## Check 1 — PRO-G40 Drive Mounted

Compose with `start_environment` for the drive check rather than reimplementing:

```bash
df /Volumes/PRO-G40 2>/dev/null && echo "PRO-G40: MOUNTED" || echo "PRO-G40: NOT MOUNTED — FAIL"
```

If NOT MOUNTED:
- Report: `PRO-G40 drive is not mounted. Overnight sessions that write to /Volumes/PRO-G40 will fail.`
- Mark check: FAIL
- Action: User must manually mount the drive before proceeding.

If MOUNTED:
- Verify `$OMNI_HOME` resolves correctly: `ls "$OMNI_HOME/omniclaude" 2>/dev/null && echo "OMNI_HOME resolves" || echo "OMNI_HOME broken"`
- Mark check: PASS

---

## Check 2 — Hostname / Machine Identity

```bash
hostname
uname -m
sw_vers -productVersion 2>/dev/null || lsb_release -d 2>/dev/null || echo "Linux"
echo "Shell: $SHELL"
echo "OMNI_HOME: ${OMNI_HOME:-UNSET}"
```

Report the full identity block:
```
Machine: <hostname>
Arch:    <architecture>
OS:      <version>
Shell:   <shell>
OMNI_HOME: <path or UNSET>
```

Mark FAIL if `OMNI_HOME` is UNSET — sessions cannot function without it.
Mark PASS otherwise (identity is informational).

---

## Check 3 — Zombie Agent Detection

Invoke `dispatch_watchdog` in inspect-only mode to list live agents and flag zombies.

Agents are considered zombies if they are idle (no tool call output) for >10 minutes.

```
/onex:dispatch_watchdog --action report
```

Interpret results:
- If no agents running: `No active agents — clean slate.` Mark PASS.
- If agents running with recent activity: list them. Mark PASS.
- If any agent is idle >10min: report it as zombie. Mark WARN (does not block go/no-go, but surface to user for manual review).

> Note: WARN does not flip the verdict to NO-GO. Only FAIL does.

---

## Check 4 — Merge Queue Health (11 repos)

Query GitHub merge queue and PR state across all 11 ONEX repos.

```bash
REPOS=(
  OmniNode-ai/omniclaude
  OmniNode-ai/omnibase_core
  OmniNode-ai/omnibase_infra
  OmniNode-ai/omnibase_spi
  OmniNode-ai/omnidash
  OmniNode-ai/omnigemini
  OmniNode-ai/omniintelligence
  OmniNode-ai/omnimemory
  OmniNode-ai/omninode_infra
  OmniNode-ai/omnimarket
  OmniNode-ai/omnibase_compat
)

for repo in "${REPOS[@]}"; do
  echo "=== $repo ==="
  gh pr list --repo "$repo" --state open --json number,title,mergeable,reviewDecision \
    --jq '.[] | "\(.number) \(.title[:60]) | mergeable=\(.mergeable) review=\(.reviewDecision)"' \
    2>/dev/null || echo "  (no open PRs or API error)"
done
```

For each repo, flag:
- PRs with `mergeable: CONFLICTING` — these block queue drain
- PRs with `reviewDecision: CHANGES_REQUESTED` — blocked by review
- PRs stuck in merge queue >2 hours (if detectable)

Summary table:
```
REPO                      OPEN  CONFLICTING  BLOCKED
omniclaude                   2            0        0
omnibase_core                1            1        1  ← WARN
...
```

If `--skip-merge-queue` flag is set, skip this check and mark as SKIPPED.

Mark FAIL only if the `gh` CLI is unavailable or unauthenticated. WARN on conflicts.

---

## Check 5 — Required Environment Variables

Check the three env vars required for overnight sessions.
**DO NOT check `ANTHROPIC_API_KEY`** — it is not required (OMN-7467).

```bash
REQUIRED_VARS=(
  KAFKA_BOOTSTRAP_SERVERS
  LINEAR_API_KEY
  GITHUB_TOKEN
)

for var in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var}" ]]; then
    echo "MISSING: $var"
  else
    # Mask value — show only first 4 chars
    masked="${!var:0:4}****"
    echo "SET:     $var = $masked"
  fi
done
```

Also check:
```bash
# Verify GITHUB_TOKEN is actually authenticated (not just set)
gh auth status 2>&1 | head -3

# Verify LINEAR_API_KEY reaches the API
# (check is lightweight — just verify the var is non-empty and plausibly formatted)
[[ "${LINEAR_API_KEY}" =~ ^lin_ ]] && echo "LINEAR_API_KEY: format OK" || echo "LINEAR_API_KEY: unexpected format (expected lin_...)"
```

Mark FAIL if any of the three vars is missing.
Mark WARN if `gh auth status` fails (token may be expired).

---

## Check 6 — Go / No-Go Verdict

After all 5 checks complete, emit a clear verdict.

### PASS (Go)

All checks are PASS (WARNs are acceptable):

```
╔══════════════════════════════════════╗
║         PREFLIGHT: GO                ║
╚══════════════════════════════════════╝

Check 1  PRO-G40 Drive      PASS
Check 2  Machine Identity   PASS
Check 3  Zombie Agents      PASS  (or WARN — list zombies)
Check 4  Merge Queue        PASS  (or WARN — list conflicts)
Check 5  Env Vars           PASS

Overnight session is clear to start.
```

### FAIL (No-Go)

One or more checks returned FAIL:

```
╔══════════════════════════════════════╗
║         PREFLIGHT: NO-GO             ║
╚══════════════════════════════════════╝

Check 1  PRO-G40 Drive      FAIL  ← drive not mounted
Check 2  Machine Identity   PASS
Check 3  Zombie Agents      WARN  (2 zombies — review before continuing)
Check 4  Merge Queue        PASS
Check 5  Env Vars           PASS

Issues to resolve before starting:
  1. Mount PRO-G40 drive (Check 1)

Do not start overnight session until all FAIL items are resolved.
Run /preflight again after fixing.
```

---

## Usage Examples

```bash
# Full preflight check
/preflight

# Fast check — skip merge queue (saves ~30s when rate-limited)
/preflight --skip-merge-queue

# Skip watchdog (no active agents to check)
/preflight --skip-watchdog
```

## See Also

- `/onex:start_environment` — bring up Docker services before running preflight
- `/onex:system_status` — comprehensive system health after session start
- `/onex:dispatch_watchdog` — detailed zombie agent recovery
- `/onex:merge_sweep` — fix conflicting PRs flagged by merge queue check
