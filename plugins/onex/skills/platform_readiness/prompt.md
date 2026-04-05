# Platform Readiness Gate

You are executing the platform readiness gate skill. This aggregates 7 verification dimensions into a tri-state (PASS/WARN/FAIL) readiness report.

## Argument Parsing

```
/platform_readiness [--json] [--dimension <dimension_name>]
```

```python
args = "$ARGUMENTS".split() if "$ARGUMENTS".strip() else []

json_output = "--json" in args
single_dimension = None

if "--dimension" in args:
    idx = args.index("--dimension")
    if idx + 1 < len(args):
        single_dimension = args[idx + 1]
```

## Announce

"I'm running the platform readiness gate to assess overall system health across 7 verification dimensions."

---

## Setup

Resolve paths for all repos:

```bash
OMNI_HOME="${OMNI_HOME:?OMNI_HOME must be set}"
OMNIDASH_PATH="$OMNI_HOME/omnidash"
OMNICLAUDE_PATH="$OMNI_HOME/omniclaude"
OMNIBASE_INFRA_PATH="$OMNI_HOME/omnibase_infra"
OMNIINTELLIGENCE_PATH="$OMNI_HOME/omniintelligence"

# Load DB credentials
if [ -f ~/.omnibase/.env ]; then
  source ~/.omnibase/.env
fi

DASHBOARD_URL="${DASHBOARD_URL:-http://localhost:3000}"
```

Define helper functions for freshness classification:

```
FRESHNESS_WARN_THRESHOLD_HOURS=24
FRESHNESS_FAIL_THRESHOLD_HOURS=72
```

For each dimension result, apply freshness override:
- If result timestamp is older than 24h: override status to at least WARN
- If result timestamp is older than 72h or missing: override status to FAIL

---

## Check 1: Contract Completeness (Critical)

Verify seam contracts exist across repos.

1. Scan for `contracts/*.yaml` files in each repo under `$OMNI_HOME`:
   - omniclaude, omnibase_core, omnibase_infra, omniintelligence, omnidash, omnimemory

2. For each contract file found, check for:
   - `golden_path` section present
   - `dod_evidence` section present

3. Scoring:
   - Count total contracts and contracts with both golden_path + dod_evidence
   - PASS: all contracts have both sections
   - WARN: >50% have both sections
   - FAIL: <50% or no contracts found

4. Record: `{status, total_contracts, complete_contracts, freshness: "current"}`

---

## Check 2: Golden Chain Health (Critical)

Look for the most recent golden chain sweep result.

1. Search for sweep results:
   ```bash
   # Check .onex_state for recent sweep results
   find "$OMNI_HOME/.onex_state" -name "*.json" -path "*golden*chain*" -mmin -4320 2>/dev/null | sort -r | head -1
   ```

2. If a result file is found:
   - Parse the JSON for pass/fail counts
   - Check file modification time for freshness

3. If no result file exists, check if the skill has ever been run:
   ```bash
   # Check git log for golden chain sweep evidence
   git -C "$OMNICLAUDE_PATH" log --oneline --since="7 days ago" --grep="golden.chain" 2>/dev/null | head -3
   ```

4. Scoring:
   - PASS: all chains passed, result < 24h old
   - WARN: all chains passed but result > 24h old
   - FAIL: any chain failed, or no result found

5. Record: `{status, chains_passed, chains_failed, freshness_hours}`

---

## Check 3: Data Flow Health

Look for the most recent data flow sweep result.

1. Search for sweep results:
   ```bash
   find "$OMNI_HOME/.onex_state" -name "*.json" -path "*data*flow*" -mmin -4320 2>/dev/null | sort -r | head -1
   ```

2. If found, parse for flow statuses (FLOWING, STALE, LAGGING, EMPTY_TABLE, MISSING_TABLE).

3. Scoring:
   - PASS: no FAIL flows, result < 24h old
   - WARN: <3 degraded flows, or result > 24h old
   - FAIL: >3 FAIL flows, or no result found

4. Record: `{status, flowing_count, degraded_count, failed_count, freshness_hours}`

---

## Check 4: Runtime Wiring

Look for the most recent runtime sweep result.

1. Search for sweep results:
   ```bash
   find "$OMNI_HOME/.onex_state" -name "*.json" -path "*runtime*" -mmin -4320 2>/dev/null | sort -r | head -1
   ```

2. If found, parse for unwired handler counts.

3. Scoring:
   - PASS: 0 unwired handlers, result < 24h old
   - WARN: <3 unwired, or result > 24h old
   - FAIL: >3 unwired, or no result found

4. Record: `{status, unwired_count, freshness_hours}`

---

## Check 5: Dashboard Data

Verify key omnidash API endpoints return real data (not mock/hardcoded).

1. Check each endpoint — expect HTTP 200 and valid JSON:
   ```bash
   # Core endpoints that should always respond
   curl -sf "$DASHBOARD_URL/api/costs/summary?window=7d" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d)"
   curl -sf "$DASHBOARD_URL/api/savings/summary?window=7d" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d)"
   curl -sf "$DASHBOARD_URL/api/llm-routing/summary?window=7d" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d)"
   curl -sf "$DASHBOARD_URL/api/infra-routing/summary?window=24h" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d)"
   curl -sf "$DASHBOARD_URL/api/baselines/summary" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d)"
   ```

2. For each endpoint:
   - If HTTP error or timeout (5s): mark as FAIL
   - If response contains data: mark as PASS
   - If 501 (deferred endpoint): mark as WARN

3. Check for mock/hardcoded values — look for suspicious patterns:
   - Exact values like `0.87` or `0.85` in quality scores (common mock defaults)
   - `demoMode: true` or `fallbackToMock: true` in responses

4. Scoring:
   - PASS: all endpoints return real data
   - WARN: some return 501 (deferred) or zero (valid-zero)
   - FAIL: any return mock data, or >2 endpoints down

5. Record: `{status, endpoints_up, endpoints_down, endpoints_deferred, mock_detected}`

Note: if omnidash is not running, all dashboard checks return FAIL with detail "Dashboard not reachable at $DASHBOARD_URL".

---

## Check 6: Cost Measurement

Verify cost pipeline specifically (subset of Check 5 with deeper analysis).

1. Fetch cost and savings data:
   ```bash
   COST_SUMMARY=$(curl -sf "$DASHBOARD_URL/api/costs/summary?window=7d" 2>/dev/null)
   SAVINGS_SUMMARY=$(curl -sf "$DASHBOARD_URL/api/savings/summary?window=7d" 2>/dev/null)
   ```

2. Determine valid-zero vs broken-zero:
   - Check if there are active sessions in the window:
     ```bash
     curl -sf "$DASHBOARD_URL/api/costs/summary?window=7d" | python3 -c "
     import sys, json
     d = json.load(sys.stdin)
     session_count = d.get('session_count', d.get('sessionCount', 0))
     total_cost = d.get('total_cost_usd', d.get('totalCostUsd', 0))
     print(f'sessions={session_count} cost={total_cost}')
     "
     ```
   - If session_count > 0 but total_cost == 0: **broken-zero** (FAIL)
   - If session_count == 0 and total_cost == 0: **valid-zero** (PASS)
   - If total_cost > 0: **real data** (PASS)

3. Scoring:
   - PASS: real data present, or valid-zero (no sessions = no cost)
   - WARN: endpoints exist but return errors intermittently
   - FAIL: endpoints missing, mock data, or broken-zero detected

4. Record: `{status, session_count, total_cost_usd, total_savings_usd, zero_type}`

---

## Check 7: CI Health (Critical)

Check GitHub Actions workflow status across repos.

1. For each repo, check recent workflow runs:
   ```bash
   REPOS=("omniclaude" "omnibase_core" "omnibase_infra" "omnidash" "omniintelligence" "omnimemory")
   ORGS=("OmniNode-ai" "OmniNode-ai" "OmniNode-ai" "OmniNode-ai" "OmniNode-ai" "OmniNode-ai")

   for i in "${!REPOS[@]}"; do
     REPO="${REPOS[$i]}"
     ORG="${ORGS[$i]}"
     # Get status of latest run on default branch
     gh run list --repo "$ORG/$REPO" --branch main --limit 3 --json status,conclusion,name 2>/dev/null
   done
   ```

2. Classify each repo:
   - GREEN: latest runs all succeeded
   - AMBER: some runs failed but not critical (e.g., optional checks)
   - RED: required workflow(s) failed

3. Scoring:
   - PASS: all repos GREEN
   - WARN: <2 repos AMBER
   - FAIL: any repo RED

4. Record: `{status, repos_green, repos_amber, repos_red, failing_repos[]}`

---

## Aggregation

After all checks complete:

1. Collect all dimension results into a list
2. Apply freshness overrides (stale data -> WARN, missing data -> FAIL)
3. Compute overall status:
   - If any dimension is FAIL: overall = FAIL
   - Else if any dimension is WARN: overall = WARN
   - Else: overall = PASS
4. Identify blockers (FAIL dimensions) and degraded (WARN dimensions)
5. Critical dimension check: if any critical dimension (1, 2, 7) is FAIL, note in blockers

---

## Output

If `--json` flag is set, output the raw JSON structure.

Otherwise, output a markdown report:

```markdown
# Platform Readiness Report -- {date}

## Overall: {PASS|WARN|FAIL}

| Dimension | Status | Freshness | Details |
|-----------|--------|-----------|---------|
| Contract completeness | {status} | {freshness} | {details} |
| Golden chain health | {status} | {freshness} | {details} |
| Data flow health | {status} | {freshness} | {details} |
| Runtime wiring | {status} | {freshness} | {details} |
| Dashboard data | {status} | {freshness} | {details} |
| Cost measurement | {status} | {freshness} | {details} |
| CI health | {status} | {freshness} | {details} |

## Blockers
{list of FAIL dimensions with details, or "None"}

## Degraded
{list of WARN dimensions with details, or "None"}

## Readiness Decision
{overall status with specific actionable items}
```

---

## Error Handling

- If a check cannot run (e.g., tool not available, service unreachable): mark that dimension as FAIL with reason
- Never return fake/optimistic results -- when in doubt, WARN or FAIL
- Log all check outputs for debugging even when the dimension passes
