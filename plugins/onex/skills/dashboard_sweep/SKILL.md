---
description: Full autonomous audit-debug-fix loop for all dashboard pages — Playwright recon, parallel systematic-debug, fix, PR, Linear ticket, re-audit, iterate until clean. Supports local and cloud targets with optional post-fix redeployment.
mode: full
version: 1.1.0
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
inputs:
  - name: url
    type: str
    description: "Dashboard base URL override (overrides --target)"
    required: false
  - name: target
    type: str
    description: "Deployment target: local (default) or cloud"
    required: false
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
    description: "Skip recon, use existing triage report from ~/.claude/dashboard-sweep/latest/"
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
  - name: --release
    description: "Run /release skill before /redeploy (cloud only; required when version was bumped)"
    required: false
  - name: --skip-deploy
    description: "Skip deployment phase after fixes (default behavior)"
    required: false
---

# Dashboard Sweep

## Dispatch Requirement

When invoked, your FIRST and ONLY action is to dispatch to a polymorphic-agent. Do NOT
read files, run bash, or take any other action before dispatching.

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Run dashboard-sweep",
  prompt="Run the dashboard-sweep skill. <full context and args>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

## Overview

Full autonomous loop: Playwright audit → parallel systematic-debug → fix → PR → Linear ticket
→ re-audit → iterate until clean.

Replaces ad-hoc dashboard investigation. Every page is classified. Every fixable defect
gets a root-cause investigation and a PR. Every feature gap gets a Linear ticket.
Stops when all pages are `HEALTHY` or `MOCK` / `FLAG_GATED` (known gaps with tickets).

**Announce at start:** "I'm using the dashboard-sweep skill to audit and fix all dashboard issues."

## CLI

```
/dashboard-sweep                           # full sweep of localhost:3000 (local, default)
/dashboard-sweep --target local            # explicit local: http://localhost:3000
/dashboard-sweep --target cloud            # cloud: https://dash.dev.omninode.ai
/dashboard-sweep --url http://localhost:3000  # explicit URL override
/dashboard-sweep --skip-reaudit            # skip Phase 5 re-audit
/dashboard-sweep --triage-only             # Phase 1+2 only, no fixes
/dashboard-sweep --fix-only                # skip recon, use existing triage
/dashboard-sweep --max-iterations 5
/dashboard-sweep --dry-run
/dashboard-sweep --deploy                  # auto-deploy after fixes merge
/dashboard-sweep --deploy --release        # run /release then /redeploy (cloud version bump)
/dashboard-sweep --skip-deploy             # explicit no-deploy (default)
```

| Flag | Default | Description |
|------|---------|-------------|
| `--target` | `local` | Deployment target: `local` or `cloud` |
| `--url` | _(from target)_ | Explicit base URL override; takes precedence over `--target` |
| `--skip-reaudit` | false | Skip Phase 5 after fixes land |
| `--triage-only` | false | Phases 1+2 only |
| `--fix-only` | false | Skip to Phase 3, load triage from `latest/` |
| `--max-iterations` | 3 | Hard cap on fix→reaudit cycles |
| `--dry-run` | false | No fix agents, no PRs, no tickets; report only |
| `--deploy` | false | Deploy after fixes: restart local or redeploy cloud |
| `--release` | false | Run `/release` before `/redeploy` (cloud only) |
| `--skip-deploy` | true | Skip deployment phase (default) |

## Phase Sequence

```
Phase 1  — Recon       Playwright audit of all routes → per-page classification
Phase 2  — Triage      Group by problem domain; assign fix tier
Phase 3  — Parallel    Dispatch one debug agent per CODE_BUG/DATA_PIPELINE/SCHEMA_MISMATCH domain
Phase 4  — PR+Ticket   Each fix agent: branch → fix → PR → Linear ticket
Phase 4b — Deploy      (if --deploy) Wait for PRs to merge → restart local or redeploy cloud
Phase 5  — Re-audit    Re-run Playwright audit; compare before vs after
Phase 6  — Iterate     If new issues, loop back to Phase 3 (up to --max-iterations)
```

## Target Resolution

### URL Selection (in precedence order)

1. `--url <explicit>` — always wins; used verbatim
2. `--target cloud` → `https://dash.dev.omninode.ai`
3. `--target local` (default) → `http://localhost:3000`

Store the resolved URL as `{url}` throughout all phases.

### Target-Aware Behaviour

| Concern | `local` | `cloud` |
|---------|---------|---------|
| Playwright base URL | `http://localhost:3000` | `https://dash.dev.omninode.ai` |
| Auth | none (open) | none currently (Keycloak not deployed) |
| Fix deployment | `docker compose up --build` | trigger `/redeploy` skill |
| Log access | `docker logs <container>` | `kubectl logs` via SSM tunnel |
| DB inspection | `psql -h localhost -p 5436` | port-forward via `./tools/cloud-dev-connect.sh` |
| Kafka inspection | `docker exec omnibase-infra-redpanda rpk` | port-forward `:9092` |

### Cloud DB Reference

```
Port-forward:  ./tools/cloud-dev-connect.sh  (from omni_home/)
Postgres:      localhost:5436 → dev/dev-postgres:5432
DB:            omnidash_analytics
Role:          role_omnidash
Password:      in k8s secret omninode-service-roles (namespace: dev)
```

---

## Phase 4b — Deploy

Runs only when `--deploy` flag is set. Executes after PRs are merged (Phase 4 complete)
and before Phase 5 re-audit so the re-audit hits the updated deployment.

### Gate Condition

Skip Phase 4b entirely when:
- `--deploy` is not set (default)
- Zero PRs were merged in this iteration

### Local Deployment (`--target local`)

No confirmation required. Execute automatically.

```bash
# 1. Identify which repos had PRs merged this iteration
# 2. Rebuild affected services
docker compose up --build --force-recreate <affected-services>

# 3. If omnidash was affected (UI code changed), rebuild it explicitly
docker restart omnidash   # or rebuild if Dockerfile changed

# 4. Wait for health checks
until curl -sf http://localhost:3000/ > /dev/null; do sleep 2; done
echo "omnidash healthy"
```

Affected services are determined from `fixes/{domain_id}.json` → `repos_affected` field.

### Cloud Deployment (`--target cloud`)

Requires user confirmation before triggering (destructive operation).

```
Confirm cloud redeploy? The following repos had PRs merged: {repo_list}
This will run /redeploy which syncs bare clones, updates pins, and rebuilds the runtime.
Type YES to proceed, anything else to skip:
```

If confirmed:

```
1. IF --release flag set:
   - Run /release skill (version bump + tag) for each affected repo
   - Wait for release PRs to merge before continuing

2. Run /redeploy skill:
   - Syncs bare clones in omni_home to latest main
   - Updates image pins in k8s manifests
   - Rebuilds runtime containers
   - Rolls out via kubectl apply

3. Wait for pod readiness:
   kubectl rollout status deployment/omnidash -n dev --timeout=120s
```

If user declines: emit warning, skip Phase 4b, continue to Phase 5 re-audit against
the pre-deploy state (re-audit may show fixes only when containers restart manually).

### Emit Deploy Record

Emit to `~/.claude/dashboard-sweep/{run_id}/deploy.json`:

```json
{
  "run_id": "<run_id>",
  "target": "local | cloud",
  "iteration": 1,
  "triggered_at": "<ISO timestamp>",
  "repos_redeployed": ["omnidash", "omniintelligence"],
  "release_ran": false,
  "redeploy_confirmed": true,
  "health_check_passed": true,
  "error": null
}
```

---

## Phase 1 — Recon

### Route Discovery

Navigate `{url}` (default `http://localhost:3000`). Collect every link and nav item that
points to a route within the same origin. Include routes discovered via sidebar nav,
top nav, breadcrumbs, and route-level errors (404 pages that reveal route names).

**Minimum routes to check** (omnidash known routes):

| Route | Expected Data Signal |
|-------|----------------------|
| `/` | Summary cards, recent activity |
| `/agents` | Agent list with status |
| `/agents/[id]` | Agent detail (click first item) |
| `/events` | Event stream or event list |
| `/intelligence` | Intelligence metrics or chart |
| `/drift` | Drift detection results |
| `/pipeline` | Pipeline health tiles |
| `/metrics` | System metrics charts |
| `/settings` | Config / env info |

### Screenshot Protocol

For each route:

1. Navigate to route; wait for `networkidle` (max 10 s) or `DOMContentLoaded` + 2 s
2. Scroll to bottom to trigger lazy renders
3. Capture full-page screenshot → save to `~/.claude/dashboard-sweep/{run_id}/screenshots/{route_slug}.png`
4. Capture browser console errors → save to `~/.claude/dashboard-sweep/{run_id}/console/{route_slug}.json`
5. Capture `document.title` and visible text summary (first 500 chars)

### Page Classification

Classify each page immediately after screenshot:

| Status | Criteria |
|--------|----------|
| `HEALTHY` | Real data present (non-zero counts, live timestamps within 24 h, API responses visible) |
| `EMPTY` | Renders without error but shows no data; pipeline exists upstream (fixable with data flow work) |
| `MOCK` | Hardcoded placeholder values (e.g. "Sample Agent", `count: 42`, lorem ipsum) |
| `BROKEN` | JS error in console, HTTP 5xx, fetch failure, blank white screen, schema validation error visible in UI |
| `FLAG_GATED` | Correct pipeline confirmed; page gated behind env var or feature flag that is unset |

**Classification decision tree** (in order):

1. Any JS error with stack trace visible OR HTTP 5xx response → `BROKEN`
2. `fetch` failed OR network request returning 4xx/5xx → `BROKEN`
3. Text matches known mock patterns (see prompt.md § Mock Detection Patterns) → `MOCK`
4. Data present with live timestamps → `HEALTHY`
5. Feature flag reference found in source → `FLAG_GATED`
6. Renders cleanly but no data rows / empty state component → `EMPTY`

### Recon Output

Emit recon report to `~/.claude/dashboard-sweep/{run_id}/recon.json`:

```json
{
  "run_id": "<12-char uuid prefix>",
  "url": "http://localhost:3000",
  "pages": [
    {
      "route": "/agents",
      "status": "EMPTY",
      "screenshot": "~/.claude/dashboard-sweep/{run_id}/screenshots/agents.png",
      "console_errors": [],
      "network_failures": [],
      "visible_text_sample": "No agents found",
      "classified_at": "<ISO timestamp>"
    }
  ],
  "summary": {
    "HEALTHY": 2,
    "EMPTY": 4,
    "MOCK": 1,
    "BROKEN": 2,
    "FLAG_GATED": 0
  }
}
```

## Phase 2 — Triage

### Grouping Into Problem Domains

For each `EMPTY` and `BROKEN` page, identify the independent problem domain.
Pages share a domain when they share the same broken data source (Kafka consumer,
DB projection, API endpoint, or service).

Example: `/agents` and `/agents/[id]` both empty → both belong to domain `agent-pipeline`.

### Fix Tier Assignment

For each domain, assign exactly one fix tier:

| Fix Tier | Definition | Action |
|----------|-----------|--------|
| `CODE_BUG` | Logic error in omnidash or backend service (wrong field name, broken query, bad import) | Dispatch debug agent |
| `DATA_PIPELINE` | Kafka topic, consumer, or projection gap — data never reaches the DB | Dispatch debug agent |
| `SCHEMA_MISMATCH` | Field name or type changed in producer but not reflected in consumer/UI | Dispatch debug agent |
| `FEATURE_GAP` | Upstream service or data producer does not exist yet | Create Linear ticket only |
| `FLAG_GATE` | Correct pipeline exists; env var or feature flag not set | Document, no code fix |

### Triage Decision Tree (per domain)

1. Any JS console error with `ReferenceError` / `TypeError` / `SyntaxError` → `CODE_BUG`
2. API endpoint returns data but UI renders nothing → `CODE_BUG` (display layer)
3. API endpoint returns 200 with empty array → check DB:
   - DB table exists and is empty → `DATA_PIPELINE`
   - DB table or column does not exist → `SCHEMA_MISMATCH`
   - DB table does not exist because service was never built → `FEATURE_GAP`
4. API endpoint returns 404 → check if route is defined:
   - Route missing from API → `CODE_BUG` or `FEATURE_GAP` based on whether spec exists
5. Page renders mock values confirmed by text match → `MOCK` (no domain created; skip)
6. Feature flag env var found → `FLAG_GATE`

### Triage Output

Emit to `~/.claude/dashboard-sweep/{run_id}/triage.json`:

```json
{
  "run_id": "<run_id>",
  "domains": [
    {
      "domain_id": "agent-pipeline",
      "pages": ["/agents", "/agents/[id]"],
      "fix_tier": "DATA_PIPELINE",
      "hypothesis": "Agent events never consumed from Kafka; agents table empty",
      "repos_likely_affected": ["omnidash", "omniintelligence"],
      "estimated_complexity": "medium"
    }
  ],
  "skipped": [
    { "route": "/settings", "reason": "MOCK — hardcoded, FEATURE_GAP ticket required" }
  ]
}
```

## Phase 3 — Parallel Debug

### Dispatch Rules

- Dispatch one `systematic-debugging` polymorphic agent per domain with `fix_tier` in
  `[CODE_BUG, DATA_PIPELINE, SCHEMA_MISMATCH]`
- All dispatches happen in a **single message** for true parallelism
- `FEATURE_GAP` domains: create Linear ticket immediately, do NOT dispatch debug agent
- `FLAG_GATE` domains: document the env var in triage report, no agent dispatched
- `MOCK` pages: no action unless explicitly requested

### Agent Prompt Template (per domain)

See `prompt.md` § Phase 3 Agent Prompt Template for the full verbatim template injected
into each dispatch.

**Required fields in each dispatch:**

```
Domain ID:       {domain_id}
Fix Tier:        {fix_tier}
Pages Affected:  {pages}
Hypothesis:      {hypothesis}
Repos:           {repos_likely_affected}
Dashboard URL:   {url}
Run ID:          {run_id}
Triage Path:     ~/.claude/dashboard-sweep/{run_id}/triage.json
Recon Path:      ~/.claude/dashboard-sweep/{run_id}/recon.json
```

### Agent Constraints (Non-Negotiable)

Each dispatched debug agent MUST:

1. Follow the `systematic-debugging` skill (5 phases: backward trace → root cause →
   pattern → hypothesis → implementation)
2. Work in a git worktree (NEVER edit files in `omni_home/` directly)
3. Run `uv run pre-commit run --all-files` before committing
4. Write fix summary to `~/.claude/dashboard-sweep/{run_id}/fixes/{domain_id}.json`
5. Report actual root cause found (not just "fixed")

### Parallel Dispatch Contract

```
RULE: All debug agent Task() calls are dispatched simultaneously in ONE message.
RULE: Do NOT dispatch sequentially — this destroys the parallelism benefit.
RULE: Each agent creates its own branch (jonah/omn-5057-fix-{domain_id}).
RULE: Orchestrator waits for ALL agents before proceeding to Phase 4.
```

## Phase 4 — PR + Ticket

After each fix agent completes:

1. **Branch**: `jonah/omn-5057-fix-{domain_id}`
2. **Commit**: `fix(dashboard): {domain_id} — {root_cause_one_liner} [OMN-5057]`
3. **PR**: Create via `gh pr create --repo OmniNode-ai/{repo}`
4. **Linear ticket**: Create child ticket under OMN-5057 epic (title: `fix: {domain_id}`)
5. **Auto-merge**: `gh pr merge --auto --squash {pr_number} --repo OmniNode-ai/{repo}`

After all PRs are created and auto-merge is queued, wait for CI to complete and PRs to merge.
Then proceed to **Phase 4b (Deploy)** if `--deploy` is set.

### Feature Gap Ticket Template

For `FEATURE_GAP` domains (no fix agent dispatched):

```
Title: feat: {domain_id} — upstream data producer needed for {pages}
Labels: feature-gap, dashboard-sweep
Parent: OMN-5057
Priority: 2 (Major)
Description:
  Phase 1 recon classified these pages as EMPTY/FEATURE_GAP:
  {pages}

  ## Root Cause
  No upstream service or Kafka producer emits data for this view.
  This is a greenfield feature gap, not a bug.

  ## Acceptance Criteria
  - Upstream producer emits events to {topic} topic
  - DB projection populated
  - Dashboard page classified as HEALTHY in dashboard-sweep re-audit
```

### Fix Registry

Emit to `~/.claude/dashboard-sweep/{run_id}/fixes/{domain_id}.json`:

```json
{
  "domain_id": "agent-pipeline",
  "fix_tier": "DATA_PIPELINE",
  "root_cause": "NodeAgentStatusEffect was not subscribed to onex.evt.omniintelligence.agent-status.v1",
  "files_changed": ["src/nodes/node_agent_status_effect.py"],
  "pr_url": "https://github.com/OmniNode-ai/omniintelligence/pull/42",
  "linear_ticket": "OMN-5060",
  "branch": "jonah/omn-5057-fix-agent-pipeline",
  "status": "pr_created | merged | failed",
  "pre_commit_passed": true
}
```

## Phase 5 — Re-audit

### When to Run

Run unless `--skip-reaudit` flag is set.

If `--skip-reaudit`: skip to Phase 6, emit summary with `reaudit: skipped`.

### Re-audit Protocol

Re-run Phase 1 Playwright audit against the same `{url}`. Use the same classification
logic. Compare `recon.json` (before) against `reaudit.json` (after):

```
Fixed:       pages that moved from EMPTY/BROKEN → HEALTHY
Regressed:   pages that moved from HEALTHY → BROKEN (alert immediately)
Unchanged:   still EMPTY or BROKEN after fixes (new domains for next iteration)
New issues:  routes now returning data but with new errors
```

Emit to `~/.claude/dashboard-sweep/{run_id}/reaudit.json` (same schema as recon.json).

### Comparison Report

Emit to `~/.claude/dashboard-sweep/{run_id}/comparison.md`:

```markdown
## Dashboard Sweep — Before vs After

| Route | Before | After | Delta |
|-------|--------|-------|-------|
| /agents | EMPTY | HEALTHY | FIXED |
| /events | BROKEN | HEALTHY | FIXED |
| /intelligence | BROKEN | BROKEN | OPEN |
| /drift | MOCK | MOCK | UNCHANGED |

## Summary
- Fixed: 2 pages
- Still open: 1 page (new domain created for next iteration)
- Regressions: 0
```

## Phase 6 — Iterate

### Stop Conditions

Stop iterating when ANY of the following are true:

1. All pages are `HEALTHY`, `MOCK`, or `FLAG_GATED`
2. Iteration count reaches `--max-iterations` (default: 3)
3. No new fix domains were created in the previous iteration
4. All remaining issues are `FEATURE_GAP` (tickets created, no code to write)

### Loop Logic

```
iteration = 1
WHILE iteration <= max_iterations:
  unchanged_broken = pages still EMPTY or BROKEN after reaudit
  IF unchanged_broken is empty: STOP — all clean
  new_domains = triage(unchanged_broken)
  IF new_domains is empty: STOP — no actionable work remaining
  dispatch_agents(new_domains)            # Phase 3
  wait_for_fixes()                       # Phase 4
  reaudit()                              # Phase 5
  iteration += 1

IF iteration > max_iterations:
  emit: "Max iterations reached. Remaining open pages: {list}"
  create Linear ticket summarizing unresolved items
```

## Final Report

After all iterations complete, emit to `~/.claude/dashboard-sweep/{run_id}/report.md`:

```markdown
# Dashboard Sweep Report — {run_id}

**URL**: {url}
**Target**: {local | cloud}
**Date**: {ISO timestamp}
**Iterations**: {n}
**Deploy**: {skipped | local-restarted | cloud-redeployed | declined}

## Final Page Status

| Route | Final Status | Fix Applied | PR | Ticket |
|-------|-------------|-------------|-----|--------|
| ...   | ...         | ...         | ... | ...    |

## Fixed This Sweep
- {n} pages moved to HEALTHY
- {n} PRs merged
- {n} Linear tickets created

## Known Gaps (tickets created, no code fix)
- {feature_gap_domains}

## Still Open (max iterations reached)
- {unresolved}
```

## Dispatch Contracts (Non-Negotiable)

```
RULE: ALL Task() calls MUST use subagent_type="onex:polymorphic-agent".
RULE: NEVER modify files directly from the orchestrator context.
RULE: NEVER edit files inside omni_home/ — always use git worktrees.
RULE: Phase 3 agents are dispatched simultaneously (single message).
RULE: Each domain gets exactly one debug agent — no shared agents across domains.
RULE: --dry-run produces zero side effects: no agents, no PRs, no tickets, no deploys.
RULE: Phase 4b (Deploy) only runs when --deploy is set AND at least 1 PR was merged.
RULE: Cloud redeploy requires explicit user confirmation before execution.
RULE: Local restart is automatic (no confirmation required).
```

## Iteration Rules

| Condition | Action |
|-----------|--------|
| All pages HEALTHY/MOCK/FLAG_GATED | Stop — sweep complete |
| Max iterations reached | Stop — emit open items, create summary ticket |
| No new domains found in triage | Stop — remaining issues are structural/feature gaps |
| Regression detected (HEALTHY → BROKEN) | Halt, alert immediately, do NOT continue |

## Integration Test

Test suite: `tests/integration/skills/dashboard_sweep/test_dashboard_sweep_integration.py`

All tests use `@pytest.mark.unit` — static analysis of skill files, no live dashboard required.

| Test | What it verifies |
|------|-----------------|
| `TestPhase1Classification` | All 5 page statuses correctly classified |
| `TestTriageTiers` | Fix tier assigned for each page status |
| `TestParallelDispatch` | Phase 3 dispatches all agents simultaneously |
| `TestDryRunContract` | `--dry-run` produces zero side effects (including no deploy) |
| `TestIterationStopConditions` | All 4 stop conditions enforced |
| `TestFeatureGapTicketOnly` | FEATURE_GAP domains create ticket, skip agent dispatch |
| `TestRegressionHalt` | HEALTHY→BROKEN regression halts sweep immediately |
| `TestTargetResolution` | `--url` overrides `--target`; cloud resolves correct URL |
| `TestDeployGateNoPRs` | Phase 4b skipped when zero PRs merged |
| `TestLocalDeployNoConfirm` | Local restart executes without user confirmation |
| `TestCloudDeployRequiresConfirm` | Cloud redeploy prompts for confirmation |
| `TestCloudDeployDeclined` | Declined confirmation skips deploy, continues to Phase 5 |
| `TestReleaseBeforeRedeploy` | `--release` runs /release skill before /redeploy |

```bash
uv run pytest tests/integration/skills/dashboard_sweep/ -v
```

## Artifacts

```
~/.claude/dashboard-sweep/{run_id}/
  recon.json                  # Phase 1 output
  screenshots/*.png           # Per-page screenshots
  console/*.json              # Per-page console errors
  triage.json                 # Phase 2 output
  fixes/{domain_id}.json      # Per-domain fix output (Phase 3+4)
  deploy.json                 # Phase 4b deploy record (only when --deploy set)
  reaudit.json                # Phase 5 output
  comparison.md               # Before vs after comparison
  report.md                   # Final summary
~/.claude/dashboard-sweep/latest -> {run_id}  # symlink to most recent run
```

## See Also

- `systematic-debugging` skill — root-cause framework used inside each debug agent
- `gap` skill — cross-repo integration health audit (detect/fix/cycle for Kafka drift)
- `ticket-pipeline` skill — PR + ticket creation pattern
- `pr-queue-pipeline` skill — batched PR merge after fixes
- `redeploy` skill — syncs bare clones, updates pins, rebuilds runtime (cloud Phase 4b)
- `release` skill — version bump + tag before redeploy (when `--release` flag set)
- Playwright MCP — browser automation for Phase 1 and Phase 5 audits
- `omni_home/omnidash/` — dashboard repo (Next.js, React 18, TypeScript)
- `omni_home/tools/cloud-dev-connect.sh` — port-forwards for cloud DB/Kafka inspection
