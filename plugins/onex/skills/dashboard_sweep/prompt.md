<!-- persona: plugins/onex/skills/_lib/assistant-profile/persona.md -->
<!-- persona-scope: this-skill-only -- do not re-apply if polymorphic agent wraps this skill -->
Apply the persona profile above when generating outputs.

# Dashboard Sweep Orchestration

You are executing the dashboard-sweep skill. This prompt defines the complete orchestration
logic for all six phases.

---

## Argument Parsing

Parse from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| `--target <local\|cloud>` | `local` | Deployment target |
| `--url <url>` | _(from target)_ | Explicit base URL; overrides `--target` |
| `--skip-reaudit` | false | Skip Phase 5 re-audit |
| `--triage-only` | false | Run Phases 1+2 only |
| `--fix-only` | false | Skip to Phase 3, load triage from `latest/` |
| `--max-iterations <n>` | 3 | Hard cap on fix→reaudit cycles |
| `--dry-run` | false | Preview plan; no agents, PRs, tickets, or deploys |
| `--deploy` | false | Auto-deploy after fixes merge |
| `--release` | false | Run /release before /redeploy (cloud only) |
| `--skip-deploy` | true | Explicit no-deploy (default) |

### URL and Target Resolution

Resolve `{url}` and `{target}` in this precedence order:

1. `--url <explicit>` → use verbatim; set `{target}` to `custom`
2. `--target cloud` → `{url}` = `https://dash.dev.omninode.ai`; `{target}` = `cloud`
3. `--target local` (default) → `{url}` = `http://localhost:3000`; `{target}` = `local`

Store both as `{url}` and `{target}` for all subsequent phases.

### Target-Aware Context

| Concern | `local` | `cloud` |
|---------|---------|---------|
| Playwright base URL | `http://localhost:3000` | `https://dash.dev.omninode.ai` |
| Auth | none (open) | none currently (Keycloak not deployed) |
| Fix deployment | `docker compose up --build` | `/redeploy` skill |
| Log access | `docker logs <container>` | `kubectl logs` via SSM tunnel |
| DB inspection | `psql -h localhost -p 5436` | port-forward via `cloud-dev-connect.sh` |
| Kafka inspection | `docker exec omnibase-infra-redpanda rpk` | port-forward `:9092` |

**Cloud DB reference** (for triage inspection in Phase 2):
```
Port-forward: ./tools/cloud-dev-connect.sh (from omni_home/)
Postgres:     localhost:5436 → dev/dev-postgres:5432
DB:           omnidash_analytics
Role:         role_omnidash
Password:     in k8s secret omninode-service-roles (namespace: dev)
```

Generate `run_id` = first 12 chars of a UUID4 (e.g. `3f8a1c9b0d42`).
Create directory: `~/.claude/dashboard-sweep/{run_id}/`
Create symlink: `~/.claude/dashboard-sweep/latest -> {run_id}/`

If `--fix-only`:
- Load triage from `~/.claude/dashboard-sweep/latest/triage.json`
- Skip to Phase 3

If `--dry-run`:
- Set `DRY_RUN=true`; all write operations below are annotated `[DRY_RUN — skipped]`
- No `Task()` dispatches
- No `mcp__linear-server__*` calls
- No `gh pr create` or `gh pr merge` calls
- No deploy actions (Phase 4b fully skipped)
- Screenshots and JSON artifacts ARE written (read-only observation is always safe)

---

## Phase 0.5 — Freshness Check (OMN-5145)

Before auditing pages, verify that the running omnidash instance is up-to-date.
This prevents wasting a full Playwright sweep on stale code that has already been
fixed in a newer deploy.

### 0.5.1 Build Info Probe

```bash
build_info=$(curl -sf "{url}/api/build-info" 2>/dev/null)
```

If the endpoint is unreachable or returns non-200:
```
[dashboard-sweep] WARNING: /api/build-info not available — cannot verify freshness
[dashboard-sweep] Proceeding with audit (omnidash may be running stale code)
```
Continue to Phase 1 (non-blocking).

### 0.5.2 Freshness Checks

If build info is available, extract and validate:

```python
import json
from datetime import datetime, timezone

info = json.loads(build_info)
git_sha = info.get("gitSha", "unknown")
build_time = info.get("buildTime", "")
uptime_seconds = info.get("uptimeSeconds", 0)

# Check 1: Is the build recent? (within 24h)
if build_time:
    build_dt = datetime.fromisoformat(build_time.replace("Z", "+00:00"))
    age_hours = (datetime.now(timezone.utc) - build_dt).total_seconds() / 3600
    if age_hours > 24:
        print(f"[dashboard-sweep] WARNING: omnidash build is {age_hours:.0f}h old (gitSha={git_sha})")
        print(f"[dashboard-sweep] Consider running omnidash-restart before sweeping")

# Check 2: Does the git SHA match the latest omnidash main?
latest_sha = run(f"git -C {OMNI_HOME}/omnidash rev-parse --short HEAD", capture=True).stdout.strip()
if latest_sha and git_sha != "unknown" and git_sha != latest_sha:
    print(f"[dashboard-sweep] WARNING: omnidash running {git_sha}, latest main is {latest_sha}")
    print(f"[dashboard-sweep] Fixes merged since last restart may not be reflected")
```

### 0.5.3 Auto-Restart Option

If freshness check detects stale code AND the `--deploy` flag is set:

```python
if stale_detected and deploy_flag:
    print("[dashboard-sweep] Stale omnidash detected — auto-restarting before audit")
    lifecycle_script = f"{OMNI_HOME}/omnibase_infra/scripts/omnidash-lifecycle.sh"
    if os.path.isfile(lifecycle_script):
        run(f"bash {lifecycle_script} restart")
        # Re-check build info after restart
        build_info = run(f"curl -sf {url}/api/build-info", capture=True).stdout
```

Write freshness result to `~/.claude/dashboard-sweep/{run_id}/freshness.json`:
```json
{
  "checked_at": "{ISO timestamp}",
  "build_info": { "version": "1.1.0", "gitSha": "abc1234", "buildTime": "...", "uptimeSeconds": 3600 },
  "latest_main_sha": "def5678",
  "is_stale": true,
  "auto_restarted": false,
  "warnings": ["omnidash running abc1234, latest main is def5678"]
}
```

---

## Phase 1 — Recon (Playwright Audit)

### 1.1 Browser Initialization

```
mcp__playwright__browser_navigate(url="{url}")
mcp__playwright__browser_wait_for(event="networkidle", timeout=10000)
mcp__playwright__browser_snapshot()
```

Collect all navigation links from the DOM snapshot. Extract `href` attributes from
`<a>`, `<nav>`, sidebar items, and breadcrumbs. Filter to same-origin only.

Deduplicate routes. Add any routes in the known-route list (SKILL.md § Phase 1 table)
that were not discovered via nav links.

### 1.2 Per-Page Audit Loop

For each route (process sequentially — Playwright is single-browser):

```
mcp__playwright__browser_navigate(url="{url}{route}")
mcp__playwright__browser_wait_for(event="networkidle", timeout=10000)
# fallback: wait DOMContentLoaded + 2 s if networkidle times out
mcp__playwright__browser_evaluate(script="window.scrollTo(0, document.body.scrollHeight)")
mcp__playwright__browser_take_screenshot(full_page=true, save_as="~/.claude/dashboard-sweep/{run_id}/screenshots/{slug}.png")
console_errors = mcp__playwright__browser_console_messages()
network_reqs   = mcp__playwright__browser_network_requests()
snapshot       = mcp__playwright__browser_snapshot()
```

**Route slug**: replace `/` with `-`; strip leading `-`. E.g. `/agents` → `agents`,
`/agents/123` → `agents-123`.

Save console errors:
```
save to: ~/.claude/dashboard-sweep/{run_id}/console/{slug}.json
format:  { "route": "/...", "errors": [...], "warnings": [...] }
```

### 1.3 Classification Logic

Apply in order — first match wins:

**BROKEN** (any of):
- `console_errors` contains an entry with `level=error` AND `text` contains stack trace keywords
  (`TypeError`, `ReferenceError`, `SyntaxError`, `Uncaught`, `Cannot read`)
- Any network request returned HTTP status 5xx
- Page body contains text matching: `Error:`, `500 Internal Server Error`,
  `Application error`, `ChunkLoadError`, `Failed to fetch`
- Blank page body (`document.body.innerText.trim().length < 10`)

**MOCK** (any of):
- Visible text matches any Mock Detection Pattern (see § Mock Detection Patterns below)
- Count values all equal known mock constants: 42, 99, 1337
- Timestamps are static and far in the past (> 180 days old)
- Text contains: `Lorem ipsum`, `Sample Agent`, `Test User`, `example@email.com`

**HEALTHY** (all of):
- No console errors
- No network failures (4xx/5xx)
- Page contains numeric values that differ from known mock constants
- At least one timestamp visible that is within 24 hours of now

**FLAG_GATED** (any of):
- Page displays text matching: `feature not enabled`, `coming soon`,
  `flag not set`, `enable {FEATURE_*}`, `contact admin`
- Source references `NEXT_PUBLIC_FEATURE_*` or `FEATURE_FLAG_*` env vars
  that resolve to false/undefined

**EMPTY** (fallback):
- Renders without any of the above errors
- Shows empty state component: `No data`, `No results`, `Nothing here`, `0 items`
- Or renders a skeleton/loading state that never resolves

### 1.4 Mock Detection Patterns

Strings that indicate hardcoded mock data:

```
"Sample Agent"
"Test Agent"
"Mock "
"Placeholder"
"Lorem ipsum"
"example.com"
"foo@bar"
"Agent Alpha"
"Agent Beta"
"count: 42"
"total: 99"
"active: 1337"
```

Also flag if all numeric values on the page are identical (e.g. every metric shows `42`).

### 1.5 Recon Output

Write `~/.claude/dashboard-sweep/{run_id}/recon.json`:

```json
{
  "run_id": "{run_id}",
  "url": "{url}",
  "audited_at": "{ISO timestamp}",
  "pages": [
    {
      "route": "/agents",
      "slug": "agents",
      "status": "EMPTY",
      "screenshot_path": "~/.claude/dashboard-sweep/{run_id}/screenshots/agents.png",
      "console_errors": [],
      "network_failures": [],
      "visible_text_sample": "No agents found. Connect your first agent to get started.",
      "classified_at": "{ISO timestamp}"
    }
  ],
  "summary": {
    "HEALTHY": 0,
    "EMPTY": 0,
    "MOCK": 0,
    "BROKEN": 0,
    "FLAG_GATED": 0,
    "total": 0
  }
}
```

Print human summary after writing:
```
[dashboard-sweep] Phase 1 complete — {total} pages audited
  HEALTHY:    {n}
  EMPTY:      {n}
  MOCK:       {n}
  BROKEN:     {n}
  FLAG_GATED: {n}
```

If `--triage-only` was NOT set, proceed to Phase 2.
If `--triage-only` IS set, emit the recon report and stop after Phase 2.

---

## Phase 2 — Triage

### 2.1 Domain Grouping

For each page with status `EMPTY` or `BROKEN`:

1. Identify the primary data source (API endpoint from network requests, or inferred from route name)
2. Group pages that share the same data source into one domain
3. Assign a `domain_id`: kebab-case name derived from the data source
   (e.g. `agent-pipeline`, `intelligence-metrics`, `drift-detection`)

### 2.2 Fix Tier Decision

For each domain, determine fix tier using this decision tree:

**Step 1 — Check for CODE_BUG**

```bash
# In the relevant repo's worktree, check if the API endpoint exists
gh api repos/OmniNode-ai/{repo}/contents/src --jq '.[] | .name' 2>/dev/null
# Check if omnidash API route is defined
ls ~/Code/omni_worktrees/OMN-5057/omnidash/src/app/api/{domain}/ 2>/dev/null
```

Signs of `CODE_BUG`:
- API endpoint exists and returns a response (even empty 200)
- Console shows `TypeError` or `ReferenceError` in display code
- API returns data but UI renders nothing (mapping/parsing bug)

**Step 2 — Check for DATA_PIPELINE**

Signs of `DATA_PIPELINE`:
- API endpoint exists and returns 200 `[]` (empty array)
- DB table exists but has 0 rows
- No Kafka consumer registered for the relevant topic

**Step 3 — Check for SCHEMA_MISMATCH**

Signs of `SCHEMA_MISMATCH`:
- API returns data with field names that don't match UI expectations
- Console shows `undefined` on field access for data that came from API
- DB column names differ between producer migration and consumer query

**Step 4 — Check for FEATURE_GAP**

Signs of `FEATURE_GAP`:
- API endpoint does not exist (404 at `/api/{domain}`)
- DB table does not exist
- No Kafka topic registered for this data type
- No upstream service produces events of this type

**Step 5 — Check for FLAG_GATE**

Signs of `FLAG_GATE`:
- Page source references `NEXT_PUBLIC_FEATURE_*` that is `undefined`
- `.env.example` in omnidash shows the flag but it's not in `.env.local`

### 2.3 Triage Output

Write `~/.claude/dashboard-sweep/{run_id}/triage.json`:

```json
{
  "run_id": "{run_id}",
  "triaged_at": "{ISO timestamp}",
  "domains": [
    {
      "domain_id": "agent-pipeline",
      "pages": ["/agents", "/agents/123"],
      "fix_tier": "DATA_PIPELINE",
      "hypothesis": "No Kafka consumer subscribes to agent status events; agents table always empty",
      "repos_likely_affected": ["omniintelligence", "omnidash"],
      "api_endpoint": "/api/agents",
      "db_table": "agents",
      "kafka_topic_suspected": "onex.evt.omniintelligence.agent-status.v1",
      "estimated_complexity": "medium",
      "evidence": "GET /api/agents returns 200 []; agents table has 0 rows"
    }
  ],
  "feature_gaps": [
    {
      "domain_id": "billing-dashboard",
      "pages": ["/billing"],
      "reason": "No billing service or data producer exists in the OmniNode platform yet",
      "ticket_to_create": true
    }
  ],
  "flag_gates": [
    {
      "route": "/experimental",
      "flag": "NEXT_PUBLIC_FEATURE_EXPERIMENTAL",
      "current_value": "undefined",
      "action": "set env var to enable"
    }
  ],
  "skipped": [
    { "route": "/settings", "status": "MOCK", "reason": "Hardcoded mock — no fix needed" }
  ]
}
```

Print human summary:
```
[dashboard-sweep] Phase 2 complete — {n} domains triaged
  CODE_BUG:       {n}
  DATA_PIPELINE:  {n}
  SCHEMA_MISMATCH:{n}
  FEATURE_GAP:    {n} (tickets only)
  FLAG_GATE:      {n} (document only)
```

If `--triage-only`: stop here. Print triage.json path.

---

## Phase 3 — Parallel Debug

### 3.1 Feature Gap Ticket Creation (Before Agent Dispatch)

For each `feature_gaps` entry in triage.json, create a Linear ticket immediately:

```
mcp__linear-server__save_issue(
  title="feat: {domain_id} — upstream data producer needed for {pages}",
  teamId="{omniclaude_team_id}",
  parentId="OMN-5057",
  priority=2,
  description="
## Pages Affected
{pages}

## Classification
Phase 1 dashboard-sweep classified these pages as EMPTY/FEATURE_GAP.
No upstream service or Kafka producer emits data for this view.

## Root Cause
{reason}

## Acceptance Criteria
- Upstream producer emits events to appropriate Kafka topic
- DB projection is populated by consumer
- dashboard-sweep re-audit classifies these pages as HEALTHY

## Sweep Context
Run ID: {run_id}
Triage: ~/.claude/dashboard-sweep/{run_id}/triage.json
"
)
```

Record ticket ID in `~/.claude/dashboard-sweep/{run_id}/feature_gap_tickets.json`.

### 3.2 Agent Prompt Template

For each domain with `fix_tier` in `[CODE_BUG, DATA_PIPELINE, SCHEMA_MISMATCH]`,
use this prompt template when dispatching the polymorphic-agent:

---

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
Recon data:    ~/.claude/dashboard-sweep/{run_id}/recon.json
Triage data:   ~/.claude/dashboard-sweep/{run_id}/triage.json

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
    git -C ~/Code/omni_home/{repo} worktree add \
      ~/Code/omni_worktrees/OMN-5057/{repo}-{domain_id} \
      -b {BRANCH}

## NEVER edit files in ~/Code/omni_home/ directly. Always use worktrees.

## Fix Requirements
- Fix the root cause (not just the symptom)
- Run: uv run pre-commit run --all-files (must pass before commit)
- For TypeScript repos: cd ~/Code/omni_worktrees/OMN-5057/{repo}-{domain_id} && npx tsc --noEmit

## Output Contract
Write fix summary to: ~/.claude/dashboard-sweep/{run_id}/fixes/{domain_id}.json

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

---

### 3.3 Parallel Dispatch

Dispatch ALL agent Task() calls in a SINGLE message:

```python
# All dispatches in one message — TRUE PARALLELISM
for domain in fixable_domains:
    Task(
        subagent_type="onex:polymorphic-agent",
        description=f"Debug and fix dashboard domain: {domain.domain_id} ({domain.fix_tier})",
        prompt=render_agent_prompt(domain, run_id, url)
    )
```

**CRITICAL**: Do NOT dispatch sequentially. Do NOT await each before dispatching the next.

Wait for all agents to complete before proceeding to Phase 4.

---

## Phase 4 — PR + Ticket

After all debug agents complete, for each domain with `status=fix_ready` in its fix summary:

### 4.1 Create PR

```bash
cd ~/Code/omni_worktrees/OMN-5057/{repo}-{domain_id}
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

### 4.2 Create Linear Ticket

```
mcp__linear-server__save_issue(
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

### 4.3 Auto-merge

```bash
gh pr merge --auto --squash {pr_number} --repo OmniNode-ai/{repo}
```

### 4.4 Update Fix Registry

Update `~/.claude/dashboard-sweep/{run_id}/fixes/{domain_id}.json`:
- Set `pr_url` to PR URL
- Set `linear_ticket` to created ticket ID
- Set `status` to `pr_created`

### 4.5 Domains That Could Not Be Fixed

For domains with `status=root_cause_found_no_fix` or `status=blocked`:
- Create a Linear ticket with `priority=1` (urgent)
- Document the blocker clearly
- Do NOT create a PR

---

## Phase 4b — Deploy

### 4b.0 Gate Check

Skip Phase 4b entirely when ANY of:
- `--deploy` flag is NOT set (default: skip)
- `DRY_RUN=true`
- `len({merged_repos}) == 0` (no PRs merged in this iteration)

When skipped: emit `[dashboard-sweep] Deploy skipped — no --deploy flag (or no PRs merged).`
Proceed directly to Phase 5.

Track `{merged_repos}` by checking each PR's merge status after Phase 4.3:

```bash
gh pr view {pr_number} --repo OmniNode-ai/{repo} --json state,mergedAt \
  --jq 'select(.state=="MERGED") | .mergedAt'
```

### 4b.1 Local Deployment (`{target} == "local"`)

Execute automatically — no confirmation required.

1. Derive affected Docker services from `{merged_repos}`:

   | Repo | Docker Compose Service |
   |------|------------------------|
   | `omnidash` | `omnidash` |
   | `omniintelligence` | `omniintelligence` |
   | `omnibase_infra` | `omnibase-infra` |
   | `omnibase_core` | _(library — no service to restart)_ |
   | `omnibase_spi` | _(library — no service to restart)_ |

2. Rebuild affected services:

   ```bash
   cd ~/Code/omni_home  # docker-compose.yml location
   docker compose up --build --force-recreate <affected-services>
   ```

3. Health check omnidash:

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

4. Emit `[dashboard-sweep] Local containers restarted: {affected-services}`

### 4b.2 Cloud Deployment (`{target} == "cloud"`)

Prompt user for explicit confirmation before executing (destructive):

```
[dashboard-sweep] PRs merged in repos: {merged_repos}
Cloud redeploy will sync bare clones, update image pins, and roll out new containers to k8s.
This cannot be undone without a rollback. Type YES to proceed, anything else to skip:
```

**If confirmed (`YES`):**

```
Step 1 (if --release flag set):
  - Dispatch polymorphic agent: run /release skill for each affected repo
  - Wait for release tags to publish and release PRs to merge
  - Emit "[dashboard-sweep] Release complete for: {repos}"

Step 2: Dispatch polymorphic agent to run /redeploy skill:
  - Syncs bare clones in omni_home/ to latest main
  - Updates image pins in k8s manifests (dev namespace)
  - Rebuilds runtime containers
  - Applies manifests via kubectl

Step 3: Poll for pod readiness (timeout 120 s):
  kubectl rollout status deployment/omnidash -n dev --timeout=120s

Step 4: Verify dashboard responds:
  curl -sf https://dash.dev.omninode.ai/ > /dev/null && \
    echo "[dashboard-sweep] Cloud deployment healthy"
```

**If not confirmed:**
```
[dashboard-sweep] Cloud redeploy declined by user. Phase 5 re-audit will reflect pre-deploy state.
```
Continue to Phase 5 (re-audit may not show fixes if containers still run old code).

### 4b.3 Emit Deploy Record

Write `~/.claude/dashboard-sweep/{run_id}/deploy.json`:

```json
{
  "run_id": "{run_id}",
  "target": "{local|cloud}",
  "iteration": {n},
  "triggered_at": "{ISO timestamp}",
  "repos_redeployed": ["{repo}"],
  "services_restarted": ["{service}"],
  "release_ran": false,
  "redeploy_confirmed": true,
  "health_check_passed": true,
  "error": null
}
```

If deploy was skipped or declined, set `"redeploy_confirmed": false` and `"repos_redeployed": []`.

---

## Phase 5 — Re-audit

### 5.1 Skip Check

If `--skip-reaudit`:
```
[dashboard-sweep] --skip-reaudit set — skipping Phase 5
```
Emit comparison report with `reaudit: "skipped"`. Proceed to Phase 6.

### 5.2 Wait for PRs to Land

Before re-auditing, check PR merge status:

```bash
for pr in {pr_numbers}:
    gh pr view {pr} --repo OmniNode-ai/{repo} --json state,mergedAt
```

If PRs are merged AND `--deploy` was set (Phase 4b ran):
- Containers were already rebuilt/redeployed in Phase 4b
- No additional wait needed — proceed directly to re-audit

If PRs are merged AND `--deploy` was NOT set:
- Code may not yet be running in the deployment
- Emit: `[dashboard-sweep] Note: --deploy not set; deployment not refreshed. Re-audit may not reflect fixes.`
- Proceed anyway

If PRs are NOT yet merged (still pending CI):
- Emit warning: `[dashboard-sweep] PRs not yet merged — re-audit may not reflect all fixes`
- Proceed anyway with a note in the comparison report

### 5.3 Re-audit Execution

Re-run Phase 1 Playwright audit. Save to `~/.claude/dashboard-sweep/{run_id}/reaudit.json`.

### 5.4 Comparison

Compare `recon.json` (before) vs `reaudit.json` (after):

```python
for page in all_routes:
    before = recon[page]["status"]
    after  = reaudit[page]["status"]

    if before in ("EMPTY", "BROKEN") and after == "HEALTHY":
        delta = "FIXED"
    elif before == "HEALTHY" and after == "BROKEN":
        delta = "REGRESSED"   # ALERT — halt
    elif before == after:
        delta = "UNCHANGED"
    else:
        delta = f"{before}→{after}"
```

**Regression halt**: If ANY page regressed from `HEALTHY` → `BROKEN`:
```
[dashboard-sweep] REGRESSION DETECTED: {route} was HEALTHY, now {status}
[dashboard-sweep] HALTING sweep immediately. Investigate before continuing.
```
Stop all further iteration. Create a LINEAR ticket with `priority=1` for the regression.

Write `~/.claude/dashboard-sweep/{run_id}/comparison.md`.

---

## Phase 6 — Iterate

### 6.1 Stop Condition Check

```python
open_pages = [p for p in reaudit if p["status"] in ("EMPTY", "BROKEN")]

if not open_pages:
    # All clean
    emit_final_report()
    stop()

if iteration >= max_iterations:
    emit_final_report()
    create_linear_ticket(title=f"dashboard-sweep: {len(open_pages)} pages unresolved after {max_iterations} iterations")
    stop()

new_domains = triage(open_pages)
if not new_domains:
    # Remaining issues are structural or feature gaps — no new code to write
    emit_final_report()
    stop()
```

### 6.2 Next Iteration

Increment `iteration`. Go to Phase 3 with `new_domains`.

Each iteration follows the full Phase 3 → Phase 4 → Phase 4b (if `--deploy`) → Phase 5 sequence.

---

## Final Report Generation

Write `~/.claude/dashboard-sweep/{run_id}/report.md`:

```markdown
# Dashboard Sweep Report

**Run ID**: {run_id}
**Dashboard**: {url}
**Target**: {local | cloud}
**Completed**: {ISO timestamp}
**Iterations**: {n} / {max_iterations}
**Deploy**: {skipped | local-restarted | cloud-redeployed | declined}

## Final Page Status

| Route | Before | After | Fix Applied | PR | Ticket |
|-------|--------|-------|-------------|-----|--------|
| /agents | EMPTY | HEALTHY | agent-pipeline DATA_PIPELINE fix | #42 | OMN-5060 |
| ...    | ...   | ...    | ...         | ... | ...    |

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
- Recon: ~/.claude/dashboard-sweep/{run_id}/recon.json
- Triage: ~/.claude/dashboard-sweep/{run_id}/triage.json
- Re-audit: ~/.claude/dashboard-sweep/{run_id}/reaudit.json
- Fixes: ~/.claude/dashboard-sweep/{run_id}/fixes/
- Deploy: ~/.claude/dashboard-sweep/{run_id}/deploy.json (if --deploy set)
- Screenshots: ~/.claude/dashboard-sweep/{run_id}/screenshots/
```

Print the report path and key metrics to stdout.

---

## Error Handling

| Error | Action |
|-------|--------|
| Playwright navigation timeout | Classify page as `BROKEN`; continue |
| Dev server unreachable | Emit error, stop sweep, suggest `npm run dev` or `docker compose up` |
| Agent dispatch fails | Log failure, mark domain as `blocked`, continue with other domains |
| Pre-commit fails in fix agent | Agent must fix pre-commit errors before marking `fix_ready` |
| PR creation fails | Log error with `gh` output, mark domain as `pr_failed`, continue |
| Linear API error | Log warning, continue; re-create tickets manually if needed |
| Regression detected | Halt immediately (see Phase 5.4) |
| Local docker restart fails | Log error with container name; emit warning; continue to Phase 5 |
| Cloud health check timeout | Emit error; set `health_check_passed: false` in deploy.json; continue to Phase 5 |
| kubectl rollout timeout | Emit error; advise manual check via `kubectl get pods -n dev`; continue |
| /release skill fails | Halt cloud deploy; create Linear ticket with `priority=1`; skip to Phase 5 |

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
[dashboard-sweep] Triage written to: ~/.claude/dashboard-sweep/{run_id}/triage.json
[dashboard-sweep] Screenshots written to: ~/.claude/dashboard-sweep/{run_id}/screenshots/
```

Screenshots and JSON artifacts are written even in dry run (observation is always safe).
No `Task()` dispatches, no `mcp__linear-server__*` writes, no `gh pr` commands, no Docker/kubectl commands.
