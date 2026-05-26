<!-- persona: plugins/onex/skills/_lib/assistant-profile/persona.md -->
<!-- persona-scope: this-skill-only -- do not re-apply if general-purpose agent wraps this skill -->
Apply the persona profile above when generating outputs.

# Dashboard Sweep Orchestration

You are executing the dashboard-sweep skill. This prompt defines the complete orchestration
logic across three phases: arguments + setup, node dispatch + fix loop, and render.

HTTP recon (route discovery and per-page probing) is handled by the node internally —
this skill does not perform any inline curl commands or HTTP checks.

---

## Phase 1 — Arguments & Setup

Parse from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| `--target <local\|cloud>` | `local` | Deployment target |
| `--url <url>` | _(from target)_ | Explicit base URL; overrides `--target` |
| `--skip-reaudit` | false | Skip re-audit after fix loop |
| `--triage-only` | false | Run Phase 1+2 only |
| `--fix-only` | false | Skip to Phase 2, load triage from `latest/` |
| `--max-iterations <n>` | 3 | Hard cap on fix cycles |
| `--dry-run` | false | Preview plan; no agents, PRs, tickets, or deploys |
| `--deploy` | false | Auto-deploy after fixes merge |
| `--release` | false | Run /release before /redeploy (cloud only) |
| `--skip-deploy` | true | Explicit no-deploy (default) |
| `--pages <json>` | null | Pre-classified ModelPageInput objects; bypasses node HTTP recon |

### URL and Target Resolution

Resolve `{url}` and `{target}` in this precedence order:

1. `--url <explicit>` → use verbatim; set `{target}` to `custom`
2. `--target cloud` → `{url}` = `https://dash.dev.omninode.ai`; `{target}` = `cloud`
3. `--target local` (default) → `{url}` = `http://localhost:3000`; `{target}` = `local`

Store both as `{url}` and `{target}` for all subsequent phases.

### Target-Aware Context

| Concern | `local` | `cloud` |
|---------|---------|---------|
| Dashboard base URL | `http://localhost:3000` | `https://dash.dev.omninode.ai` |
| Auth | none (open) | none currently (Keycloak not deployed) |
| Fix deployment | `docker compose up --build` | `/redeploy` skill |
| Log access | `docker logs <container>` | `kubectl logs` via SSM tunnel |
| DB inspection | `psql -h localhost -p 5436` | port-forward via `cloud-dev-connect.sh` |
| Kafka inspection | `docker exec omnibase-infra-redpanda rpk` | port-forward `:9092` |

**Cloud DB reference** (for triage inspection):
```
Port-forward: ./tools/cloud-dev-connect.sh (from omni_home/)
Postgres:     localhost:5436 → dev/dev-postgres:5432
DB:           omnidash_analytics
Role:         role_omnidash
Password:     in k8s secret omninode-service-roles (namespace: dev)
```

### Freshness Check

Before dispatching, verify the running omnidash instance is up-to-date:

```bash
build_info=$(curl -sf "{url}/api/build-info" 2>/dev/null)
```

If the endpoint is unreachable or returns non-200:
```
[dashboard-sweep] WARNING: /api/build-info not available — cannot verify freshness
[dashboard-sweep] Proceeding with audit (omnidash may be running stale code)
```
Continue (non-blocking).

If build info is available, check:
1. Is the build recent? (within 24h)
2. Does the git SHA match the latest omnidash main?

If stale AND `--deploy` flag is set, auto-restart before audit.

Write freshness result to `$ONEX_STATE_DIR/dashboard-sweep/{run_id}/freshness.json`.

### Run Setup

Generate `run_id` = first 12 chars of a UUID4 (e.g. `3f8a1c9b0d42`).
Create directory: `$ONEX_STATE_DIR/dashboard-sweep/{run_id}/`
Create symlink: `$ONEX_STATE_DIR/dashboard-sweep/latest -> {run_id}/`

If `--fix-only`:
- Load triage from `$ONEX_STATE_DIR/dashboard-sweep/latest/triage.json`
- Skip to Phase 2

If `--dry-run`:
- Set `DRY_RUN=true`; all write operations below are annotated `[DRY_RUN — skipped]`
- No `Task()` dispatches
- No `tracker.*` calls
- No `gh pr create` or `gh pr merge` calls
- No deploy actions
- JSON artifacts ARE written (read-only observation is always safe)

---

## Phase 2 — Node Dispatch & Fix Loop

### 2.1 Dispatch to Node

Pass `{url}` as `base_url` so the node performs HTTP recon, route discovery,
classification, and triage in a single call.

**Standard dispatch (HTTP recon mode):**
```bash
onex run-node node_dashboard_sweep \
  --input '{"base_url": "{url}", "max_iterations": {max_iterations}, "dry_run": {dry_run}}' \
  --timeout 300
```

**Pre-classified pages dispatch** (when `--pages` was supplied):
```bash
onex run-node node_dashboard_sweep \
  --input '{"pages": [...], "max_iterations": {max_iterations}, "dry_run": {dry_run}}' \
  --timeout 300
```

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly,
do not produce prose. Exit 0 = clean, exit 1 = issues found.

The node returns:
- `page_statuses`: per-page classification (HEALTHY, EMPTY, MOCK, BROKEN, FLAG_GATED)
- `domains`: grouped problem domains with fix tiers
- `recon_results`: raw HTTP recon results (populated when `base_url` was set)
- `summary`: aggregated counts by status and tier

Write node output to `$ONEX_STATE_DIR/dashboard-sweep/{run_id}/triage.json`.

Print human summary:
```
[dashboard-sweep] Node dispatch complete — {n} pages classified, {m} domains triaged
  CODE_BUG:       {n}
  DATA_PIPELINE:  {n}
  SCHEMA_MISMATCH:{n}
  FEATURE_GAP:    {n} (tickets only)
  FLAG_GATE:      {n} (document only)
```

If `--triage-only`: emit the triage report and stop.

### 2.2 Feature Gap Ticket Creation

For each domain with `fix_tier=FEATURE_GAP`, create a Linear ticket immediately:

```
tracker.save_issue(
  title="feat: {domain_id} — upstream data producer needed for {pages}",
  teamId="{omniclaude_team_id}",
  parentId="OMN-5057",
  priority=2,
  description="
## Pages Affected
{pages}

## Classification
Dashboard-sweep classified these pages as EMPTY/FEATURE_GAP.
No upstream service or Kafka producer emits data for this view.

## Acceptance Criteria
- Upstream producer emits events to appropriate Kafka topic
- DB projection is populated by consumer
- dashboard-sweep re-audit classifies these pages as HEALTHY

## Sweep Context
Run ID: {run_id}
Triage: $ONEX_STATE_DIR/dashboard-sweep/{run_id}/triage.json
"
)
```

Record ticket ID in `$ONEX_STATE_DIR/dashboard-sweep/{run_id}/feature_gap_tickets.json`.

### 2.3 Fix Agent Dispatch

For each domain with `fix_tier` in `[CODE_BUG, DATA_PIPELINE, SCHEMA_MISMATCH]`,
use this prompt template when dispatching the general-purpose agent:

```
You are a debug agent for the dashboard-sweep skill.

Your mission: find the root cause of why {pages} show {status} on the dashboard,
then implement a fix.

## Domain
Domain ID:   {domain_id}
Fix Tier:    {fix_tier}
Pages:       {pages}
Hypothesis:  {hypothesis}
Repos:       {repos_likely_affected}

## Context
Dashboard URL: {url}
Sweep Run ID:  {run_id}
Triage data:   $ONEX_STATE_DIR/dashboard-sweep/{run_id}/triage.json

## Required Process
You MUST follow the systematic-debugging skill (5 phases):
1. Backward Tracing — trace from symptom back to root trigger
2. Root Cause Investigation — reproduce, read errors, trace data flow
3. Pattern Analysis — find working examples, compare
4. Hypothesis Testing — form ONE hypothesis, test minimally
5. Implementation — create test first, fix root cause, verify

## Worktree Setup
Create worktrees for each affected repo:
  TICKET=OMN-5057
  BRANCH=jonah/omn-5057-fix-{domain_id}

  For each repo in {repos_likely_affected}:
    git -C $OMNI_HOME/{repo} worktree add \
      $OMNI_HOME/omni_worktrees/OMN-5057/{repo}-{domain_id} \
      -b {BRANCH}

## NEVER edit files in $OMNI_HOME/<repo>/ directly. Always use worktrees.

## Fix Requirements
- Fix the root cause (not just the symptom)
- Run: uv run pre-commit run --all-files (must pass before commit)
- For TypeScript repos: cd $OMNI_HOME/omni_worktrees/OMN-5057/{repo}-{domain_id} && npx tsc --noEmit

## Output Contract
Write fix summary to: $ONEX_STATE_DIR/dashboard-sweep/{run_id}/fixes/{domain_id}.json

Format:
{
  "domain_id": "{domain_id}",
  "fix_tier": "{fix_tier}",
  "root_cause": "<one-line description of actual root cause found>",
  "root_cause_detail": "<multi-line investigation summary>",
  "files_changed": ["<repo>/<path>", ...],
  "pre_commit_passed": true,
  "typecheck_passed": true,
  "pr_url": null,
  "linear_ticket": null,
  "branch": "{BRANCH}",
  "repos": {repos_likely_affected},
  "status": "fix_ready"
}

Set status to:
  "fix_ready"    — fix implemented, pre-commit passed, ready for PR
  "root_cause_found_no_fix" — found root cause but cannot implement fix (explain why)
  "blocked"      — cannot reach root cause; describe blocker
  "feature_gap"  — after investigation, this is a feature gap not a bug (reclassify)
```

**CRITICAL**: Dispatch ALL agent Task() calls in a SINGLE message for true parallelism.
Do NOT dispatch sequentially. Do NOT await each before dispatching the next.

Wait for all agents to complete before proceeding.

### 2.4 PR + Ticket Creation

After all debug agents complete, for each domain with `status=fix_ready`:

**Create PR** (title MUST contain `OMN-XXXX` — CI blocks merge without it):
```bash
cd $OMNI_HOME/omni_worktrees/OMN-5057/{repo}-{domain_id}
git push -u origin jonah/omn-5057-fix-{domain_id}
gh pr create \
  --repo OmniNode-ai/{repo} \
  --title "fix(dashboard): {domain_id} — {root_cause} [OMN-5057]" \
  --body "$(cat <<'EOF'
## Summary
- Domain: {domain_id}
- Pages fixed: {pages}
- Fix tier: {fix_tier}
- Root cause: {root_cause}

## Root Cause Detail
{root_cause_detail}

## Files Changed
{files_changed}

## Test Plan
- [ ] Pre-commit passed
- [ ] Typecheck passed
- [ ] dashboard-sweep re-audit classifies affected pages as HEALTHY

## Sweep Context
Sweep run: OMN-5057 / {run_id}
Triage: {domain_id} | {fix_tier}
EOF
)"
```

**Create Linear ticket:**
```
tracker.save_issue(
  title="fix(dashboard): {domain_id} — {root_cause}",
  teamId="{omniclaude_team_id}",
  parentId="OMN-5057",
  priority=2,
  description="
## Root Cause
{root_cause_detail}

## Fix
PR: {pr_url}
Branch: jonah/omn-5057-fix-{domain_id}

## Files Changed
{files_changed}

## Acceptance Criteria
- PR merged
- dashboard-sweep re-audit classifies {pages} as HEALTHY
"
)
```

**Auto-merge:**
```bash
gh pr merge --auto --squash {pr_number} --repo OmniNode-ai/{repo}
```

**Update fix registry** at `$ONEX_STATE_DIR/dashboard-sweep/{run_id}/fixes/{domain_id}.json`:
- Set `pr_url`, `linear_ticket`, `status` = `pr_created`

**Domains that could not be fixed** (`root_cause_found_no_fix` or `blocked`):
- Create a Linear ticket with `priority=1` (urgent)
- Do NOT create a PR

### 2.5 Deploy (if `--deploy`)

Skip when ANY of: `--deploy` not set, `DRY_RUN=true`, no PRs merged.

**Local deployment:**
```bash
cd $OMNI_HOME
docker compose up --build --force-recreate <affected-services>
```

Health check:
```bash
max_wait=60; elapsed=0
until curl -sf http://localhost:3000/ > /dev/null; do
  sleep 2; elapsed=$((elapsed + 2))
  if [ $elapsed -ge $max_wait ]; then
    echo "[dashboard-sweep] Health check timeout — omnidash not responding after ${max_wait}s"
    exit 1
  fi
done
echo "[dashboard-sweep] Local deployment healthy"
```

**Cloud deployment:** Prompt user for explicit confirmation before executing.
If confirmed: dispatch `/redeploy` skill, poll for pod readiness.

Write deploy record to `$ONEX_STATE_DIR/dashboard-sweep/{run_id}/deploy.json`.

### 2.6 Iteration

If open pages remain and `iteration < max_iterations`:
- Re-dispatch to node with `base_url` (node re-runs HTTP recon automatically)
- Continue fix loop (2.3 → 2.4 → 2.5)

Stop conditions:
- All pages HEALTHY → emit final report
- Max iterations reached → emit final report + Linear ticket for unresolved pages
- No new fixable domains → emit final report

---

## Phase 3 — Render Report

Write `$ONEX_STATE_DIR/dashboard-sweep/{run_id}/report.md`:

```markdown
# Dashboard Sweep Report

**Run ID**: {run_id}
**Dashboard**: {url}
**Target**: {local | cloud}
**Completed**: {ISO timestamp}
**Iterations**: {n} / {max_iterations}
**Deploy**: {skipped | local-restarted | cloud-redeployed | declined}

## Final Page Status

| Route | Classification | Fix Applied | PR | Ticket |
|-------|---------------|-------------|-----|--------|
| /agents | HEALTHY | agent-pipeline DATA_PIPELINE fix | #42 | OMN-5060 |
| ...    | ...    | ...         | ... | ...    |

## Summary

### Fixed This Sweep
- **{n} pages** moved to HEALTHY
- **{n} PRs** created / merged
- **{n} Linear tickets** created (fix tracking)

### Known Gaps (tickets created, no code fix)
{feature_gap_tickets}

### Flag-Gated (no fix needed)
{flag_gate_routes}

### Still Open (max iterations reached or blocked)
{unresolved_pages}

### Deploy Summary
- Target: {target}
- Repos redeployed: {repos_redeployed | none}
- Deploy status: {local-restarted | cloud-redeployed | declined | skipped}

## Artifacts
- Triage: $ONEX_STATE_DIR/dashboard-sweep/{run_id}/triage.json
- Fixes: $ONEX_STATE_DIR/dashboard-sweep/{run_id}/fixes/
- Deploy: $ONEX_STATE_DIR/dashboard-sweep/{run_id}/deploy.json (if --deploy set)
```

Print the report path and key metrics to stdout.

---

## Error Handling

| Error | Action |
|-------|--------|
| Node dispatch fails (non-zero exit) | Surface `SkillRoutingError` JSON envelope; do not produce prose |
| Dev server unreachable | Node will return network-error classifications; emit warning, proceed with triage |
| Agent dispatch fails | Log failure, mark domain as `blocked`, continue with other domains |
| Pre-commit fails in fix agent | Agent must fix pre-commit errors before marking `fix_ready` |
| PR creation fails | Log error with `gh` output, mark domain as `pr_failed`, continue |
| Linear API error | Log warning, continue; re-create tickets manually if needed |
| Regression detected | Halt immediately |
| Local docker restart fails | Log error with container name; emit warning; continue |
| Cloud health check timeout | Emit error; set `health_check_passed: false` in deploy.json; continue |
| kubectl rollout timeout | Emit error; advise manual check via `kubectl get pods -n dev`; continue |
| /release skill fails | Halt cloud deploy; create Linear ticket with `priority=1` |

---

## Dry Run Behavior

When `DRY_RUN=true`:

```
[dashboard-sweep] DRY RUN — no agents dispatched, no PRs created, no Linear tickets, no deploys
[dashboard-sweep] Target: {target} | URL: {url}
[dashboard-sweep] Would dispatch {n} debug agents for domains: {domain_ids}
[dashboard-sweep] Would create {n} feature-gap tickets
[dashboard-sweep] Would create {n} PRs across repos: {repos}
[dashboard-sweep] Deploy: would {restart local containers | trigger cloud redeploy} (skipped in dry run)
[dashboard-sweep] Triage written to: $ONEX_STATE_DIR/dashboard-sweep/{run_id}/triage.json
```

JSON artifacts are written even in dry run (observation is always safe).
No `Task()` dispatches, no `tracker.*` writes, no `gh pr` commands, no Docker/kubectl commands.
