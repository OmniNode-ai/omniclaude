# Overnight Merge and Verify Runbook — 2026-04-08

**Session type:** Autonomous overnight execution
**Operator:** Claude Code agent team
**Goal:** Merge all 41 open PRs across 6 repos, self-test after each tool/skill/hook merge

---

## Standing Orders

These rules apply unconditionally throughout the session. No exceptions.

**After ANY omniclaude PR merges:**
```bash
cd $OMNI_HOME/omniclaude && git pull --ff-only
claude plugin marketplace update omninode-tools
claude plugin uninstall onex@omninode-tools
claude plugin install onex@omninode-tools
```

**After ANY omnimarket PR merges that touches nodes:**
```bash
onex run <affected-node>/contract.yaml --dry-run
# Verify exit code 0 and no import errors
```

**After ANY omnidash PR merges:**
```bash
kill $(lsof -ti :3000) 2>/dev/null || true
cd $OMNI_HOME/omnidash && KAFKA_BROKERS=192.168.86.201:19092 PORT=3000 npm run dev &
sleep 5 && curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 | grep -q 200
```

**After ANY omnibase_infra PR merges that touches Docker/runtime:**
```bash
onex emit onex.cmd.deploy.rebuild-requested.v1 --payload '{"target": ".201"}'
```

**Never merge a PR with CI failures.** Fix first or skip and document the skip.

**Use merge sweep with parallel polish:**
```bash
onex run node_merge_sweep --max-parallel-polish 20
```

---

## Merge Completion Semantics

These states are distinct and must not be conflated:

| State | Meaning |
|-------|---------|
| `merge_requested` | `gh pr merge --auto` was called; GitHub has queued the merge |
| `merged` | GitHub reports `mergedAt` is non-null; the commit landed on `main` |
| `pulled` | `git pull --ff-only` completed; local clone reflects the merge |
| `verified` | Smoke test / import check / CI check passed after pull |

**Standing rule: never pull a repo until the merge is confirmed. Never write a checkpoint as `complete` until verification passes.**

### Shell helper: wait_for_merge()

Add this to your session environment before starting Phase 1:

```bash
wait_for_merge() {
  local REPO=$1  # e.g. OmniNode-ai/omnimarket
  local PR=$2    # e.g. 74
  local MAX_WAIT=${3:-120}  # seconds, default 2 min
  local ELAPSED=0
  echo "Waiting for $REPO#$PR to merge..."
  while true; do
    MERGED_AT=$(gh pr view $PR --repo $REPO --json mergedAt -q '.mergedAt')
    if [[ -n "$MERGED_AT" && "$MERGED_AT" != "null" ]]; then
      echo "$REPO#$PR merged at $MERGED_AT"
      return 0
    fi
    if [[ $ELAPSED -ge $MAX_WAIT ]]; then
      echo "ERROR: $REPO#$PR not merged after ${MAX_WAIT}s — aborting wait"
      return 1
    fi
    sleep 10
    ELAPSED=$((ELAPSED + 10))
  done
}
```

### Correct merge pattern (use everywhere in this runbook)

```bash
# 1. Request merge
gh pr merge <PR> --repo <REPO> --squash --auto
# 2. Wait for confirmed merge
wait_for_merge <REPO> <PR>
# 3. Pull only after confirmed
git -C $OMNI_HOME/<local_dir> pull --ff-only
# 4. Verify
<smoke test command>
# 5. Write checkpoint with state=verified
```

---

## Phase 1: CI Fix Sprint (first 30 min)

These 5 PRs have CI failures that must be resolved before their phases can proceed. The `ci-fixes-batch` agent is handling these now; document retry steps here in case they need re-execution.

### omnimarket#75 — test_contract_handler_reference failure
```bash
# In worktree for omnimarket#75:
# Find the test and update the handler reference to match refactored contract shape
grep -rn "test_contract_handler_reference" tests/
# Fix: update expected handler class path or mock target to post-#74 contract
uv run pytest tests/ -k test_contract_handler_reference -v
git add -A && git commit -m "fix: update test_contract_handler_reference for contract shape"
git push
```

### omnimarket#67 — same test (if also failing)
```bash
# Same fix as #75 — check if #67 shares the test file
```

### onex_change_control#141 — ruff format
```bash
# In worktree for onex_change_control#141:
uv run ruff format .
uv run ruff check . --fix
git add -A && git commit -m "fix: ruff format"
git push
```

### omnibase_infra#1208 — ruff format
```bash
# In worktree for omnibase_infra#1208:
uv run ruff format .
uv run ruff check . --fix
git add -A && git commit -m "fix: ruff format"
git push
```

### omnidash#557 — rename title (remove em-dash)
```bash
gh pr edit 557 --repo OmniNode-ai/omnidash --title "fix: latency page prompt_id field"
# Title must not contain em-dash (—) — CI title lint rejects it
```

**Phase 1 checkpoint:** Write to `.onex_state/overnight/2026-04-08-checkpoint.yaml` (see Checkpoint Format section).

---

## Phase 2: Foundation Merges

Merge in strict order. Each merge must complete CI verification before proceeding to the next.

### Step 1 — omnibase_core#792 (db_tables schema)
```bash
# Verify CI green
gh pr checks 792 --repo OmniNode-ai/omnibase_core
# Merge + wait
gh pr merge 792 --repo OmniNode-ai/omnibase_core --squash --auto
wait_for_merge OmniNode-ai/omnibase_core 792
# Pull only after confirmed merge
git -C $OMNI_HOME/omnibase_core pull --ff-only
git -C $OMNI_HOME/omnimarket pull --ff-only
# Spot check
cd $OMNI_HOME/omnimarket && uv run python -c "from omnibase_core.models.db_tables import *; print('schema ok')"
```

### Step 2 — omniclaude#1161 (parallel polish dispatch)
```bash
gh pr checks 1161 --repo OmniNode-ai/omniclaude
gh pr merge 1161 --repo OmniNode-ai/omniclaude --squash --auto
wait_for_merge OmniNode-ai/omniclaude 1161
# Mandatory redeploy
cd $OMNI_HOME/omniclaude && git pull --ff-only
claude plugin marketplace update omninode-tools
claude plugin uninstall onex@omninode-tools
claude plugin install onex@omninode-tools
# Verify parallel polish is wired
onex run node_merge_sweep --max-parallel-polish 20 --dry-run
```

### Step 3 — omnimarket#74 (projection contracts)
```bash
gh pr checks 74 --repo OmniNode-ai/omnimarket
gh pr merge 74 --repo OmniNode-ai/omnimarket --squash --auto
wait_for_merge OmniNode-ai/omnimarket 74
git -C $OMNI_HOME/omnimarket pull --ff-only
# Verify contract validation
cd $OMNI_HOME/omnimarket && uv run python -c "from omnimarket.contracts import ProjectionContract; print('contracts ok')"
```

### Step 4 — omnimarket#75 (legacy contract fix)
```bash
# Only proceed if CI is green (Phase 1 fix must have landed)
gh pr checks 75 --repo OmniNode-ai/omnimarket
gh pr merge 75 --repo OmniNode-ai/omnimarket --squash --auto
wait_for_merge OmniNode-ai/omnimarket 75
git -C $OMNI_HOME/omnimarket pull --ff-only
# Verify legacy migration
cd $OMNI_HOME/omnimarket && uv run pytest tests/ -k legacy_contract -v
```

**Phase 2 checkpoint.**

---

## Phase 3: Handler + Infra Merges

### Step 5 — omnimarket#76 (handler refactor)
```bash
gh pr checks 76 --repo OmniNode-ai/omnimarket
gh pr merge 76 --repo OmniNode-ai/omnimarket --squash --auto
wait_for_merge OmniNode-ai/omnimarket 76
git -C $OMNI_HOME/omnimarket pull --ff-only
# Verify: no hardcoded topic strings remain (all must use TOPIC_ constants)
result=$(grep -rn "\"onex\." $OMNI_HOME/omnimarket/omnimarket/handlers/ | grep -v "TOPIC_" | wc -l)
echo "Hardcoded topic strings: $result"
# Expected: 0
```

### Step 6 — omnimarket#77 (orchestrator DI fix)
```bash
gh pr checks 77 --repo OmniNode-ai/omnimarket
gh pr merge 77 --repo OmniNode-ai/omnimarket --squash --auto
wait_for_merge OmniNode-ai/omnimarket 77
git -C $OMNI_HOME/omnimarket pull --ff-only
# Verify orchestrator starts — see Phase 7 Step 6 for full timeout logic
cd $OMNI_HOME/omnimarket
timeout 15 onex run node_build_loop_orchestrator/contract.yaml
EXIT_CODE=$?
STDERR_OUT=$(timeout 15 onex run node_build_loop_orchestrator/contract.yaml 2>&1 >/dev/null)
if echo "$STDERR_OUT" | grep -qiE "ImportError|ModuleNotFoundError|Traceback"; then
  echo "ERROR: import/crash failure — do not proceed to Phase 7"
  exit 1
elif [[ $EXIT_CODE -eq 124 ]]; then
  echo "OK: timeout (orchestrator ran, no crash)"
else
  echo "Exit code: $EXIT_CODE — review output before continuing"
fi
```

### Step 7 — omnimarket#78 (CI topic lint)
```bash
# Only after #75 is merged
gh pr checks 78 --repo OmniNode-ai/omnimarket
gh pr merge 78 --repo OmniNode-ai/omnimarket --squash --auto
wait_for_merge OmniNode-ai/omnimarket 78
git -C $OMNI_HOME/omnimarket pull --ff-only
```

### Step 8 — omnibase_infra#1208 (preflight validator)
```bash
# Only after ruff fix from Phase 1 lands
gh pr checks 1208 --repo OmniNode-ai/omnibase_infra
gh pr merge 1208 --repo OmniNode-ai/omnibase_infra --squash --auto
wait_for_merge OmniNode-ai/omnibase_infra 1208
git -C $OMNI_HOME/omnibase_infra pull --ff-only
# Verify preflight logs warnings (not errors)
cd $OMNI_HOME/omnibase_infra && uv run python -c "from omnibase_infra.validators.preflight import run_preflight; run_preflight()" 2>&1 | grep -E "WARN|OK|ERROR"
```

### Step 9 — omnibase_infra#1205 (model registry)
```bash
gh pr checks 1205 --repo OmniNode-ai/omnibase_infra
gh pr merge 1205 --repo OmniNode-ai/omnibase_infra --squash --auto
wait_for_merge OmniNode-ai/omnibase_infra 1205
git -C $OMNI_HOME/omnibase_infra pull --ff-only
cd $OMNI_HOME/omnibase_infra && uv run python -c "from omnibase_infra.registry.model_registry import ModelRegistry; print('model registry ok')"
```

### Step 10 — omnibase_infra#1206 (3 scripts)
```bash
gh pr checks 1206 --repo OmniNode-ai/omnibase_infra
gh pr merge 1206 --repo OmniNode-ai/omnibase_infra --squash --auto
wait_for_merge OmniNode-ai/omnibase_infra 1206
git -C $OMNI_HOME/omnibase_infra pull --ff-only
# Quick smoke test: each new script importable
cd $OMNI_HOME/omnibase_infra && python -c "import omnibase_infra.scripts; print('scripts ok')"
```

**Phase 3 checkpoint.**

---

## Phase 4: Dashboard Merges

### Dashboard restart helper

Use this function for every dashboard restart in Phase 4:

```bash
restart_and_verify_dashboard() {
  local ROUTE=${1:-""}  # optional specific route to verify, e.g. /latency
  kill $(lsof -ti :3000) 2>/dev/null || true
  cd $OMNI_HOME/omnidash
  KAFKA_BROKERS=192.168.86.201:19092 PORT=3000 npm run dev > /tmp/omnidash.log 2>&1 &
  # Poll /api/health up to 30s
  local ELAPSED=0
  until curl -sf http://localhost:3000/api/health | grep -q "ok"; do
    sleep 2; ELAPSED=$((ELAPSED + 2))
    if [[ $ELAPSED -ge 30 ]]; then
      echo "ERROR: dashboard /api/health did not return ok after 30s"
      echo "--- Last 20 lines of log ---"
      tail -20 /tmp/omnidash.log
      return 1
    fi
  done
  echo "Dashboard healthy"
  # Check specific routes if requested
  if [[ -n "$ROUTE" ]]; then
    curl -sf "http://localhost:3000${ROUTE}" | grep -q "." && echo "$ROUTE ok" || echo "WARNING: $ROUTE returned empty"
  fi
  # Always check core routes
  curl -sf http://localhost:3000/delegation | grep -q "." && echo "/delegation ok"
  curl -sf http://localhost:3000/events | grep -q "." && echo "/events ok"
  curl -sf http://localhost:3000/intelligence | grep -q "." && echo "/intelligence ok"
}
```

### Step 11 — omnidash#557 (latency prompt_id fix)
```bash
# Title must already be fixed (Phase 1)
gh pr checks 557 --repo OmniNode-ai/omnidash
gh pr merge 557 --repo OmniNode-ai/omnidash --squash --auto
wait_for_merge OmniNode-ai/omnidash 557
git -C $OMNI_HOME/omnidash pull --ff-only
restart_and_verify_dashboard /latency
curl -sf http://localhost:3000/latency | grep -q "prompt_id" && echo "latency prompt_id ok"
```

### Step 12 — omnidash#558 (omnimarket topic subscriptions)
```bash
gh pr checks 558 --repo OmniNode-ai/omnidash
gh pr merge 558 --repo OmniNode-ai/omnidash --squash --auto
wait_for_merge OmniNode-ai/omnidash 558
git -C $OMNI_HOME/omnidash pull --ff-only
restart_and_verify_dashboard /events
curl -sf http://localhost:3000/events | grep -q "omnimarket" && echo "omnimarket events page ok"
```

### Step 13 — omnidash#555, #556 (probes + routes)
```bash
for pr in 555 556; do
  gh pr checks $pr --repo OmniNode-ai/omnidash
  gh pr merge $pr --repo OmniNode-ai/omnidash --squash --auto
  wait_for_merge OmniNode-ai/omnidash $pr
done
git -C $OMNI_HOME/omnidash pull --ff-only
restart_and_verify_dashboard
```

### Step 14 — Remaining GREEN omnidash PRs (#554, #553, #552, #551, #541, #538, #537–#530)

Merge in batches of 2, restarting and verifying dashboard after each batch.

```bash
# Batch 1
for pr in 554 553; do
  gh pr checks $pr --repo OmniNode-ai/omnidash && \
  gh pr merge $pr --repo OmniNode-ai/omnidash --squash --auto && \
  wait_for_merge OmniNode-ai/omnidash $pr
done
git -C $OMNI_HOME/omnidash pull --ff-only
restart_and_verify_dashboard

# Batch 2
for pr in 552 551; do
  gh pr checks $pr --repo OmniNode-ai/omnidash && \
  gh pr merge $pr --repo OmniNode-ai/omnidash --squash --auto && \
  wait_for_merge OmniNode-ai/omnidash $pr
done
git -C $OMNI_HOME/omnidash pull --ff-only
restart_and_verify_dashboard

# Batch 3
for pr in 541 538; do
  gh pr checks $pr --repo OmniNode-ai/omnidash && \
  gh pr merge $pr --repo OmniNode-ai/omnidash --squash --auto && \
  wait_for_merge OmniNode-ai/omnidash $pr
done
git -C $OMNI_HOME/omnidash pull --ff-only
restart_and_verify_dashboard

# Batch 4
for pr in 537 536; do
  gh pr checks $pr --repo OmniNode-ai/omnidash && \
  gh pr merge $pr --repo OmniNode-ai/omnidash --squash --auto && \
  wait_for_merge OmniNode-ai/omnidash $pr
done
git -C $OMNI_HOME/omnidash pull --ff-only
restart_and_verify_dashboard

# Remaining (#535, #534, #533, #532, #531, #530)
for pr in 535 534 533 532 531 530; do
  gh pr checks $pr --repo OmniNode-ai/omnidash && \
  gh pr merge $pr --repo OmniNode-ai/omnidash --squash --auto && \
  wait_for_merge OmniNode-ai/omnidash $pr
done
git -C $OMNI_HOME/omnidash pull --ff-only
restart_and_verify_dashboard
```

### Step 15 — Dependabot bumps (#549, #548, #547, #546, #545, #543)
```bash
# Merge in batches of 2
for pr in 549 548; do
  gh pr checks $pr --repo OmniNode-ai/omnidash && \
  gh pr merge $pr --repo OmniNode-ai/omnidash --squash --auto && \
  wait_for_merge OmniNode-ai/omnidash $pr
done
git -C $OMNI_HOME/omnidash pull --ff-only
restart_and_verify_dashboard

for pr in 547 546; do
  gh pr checks $pr --repo OmniNode-ai/omnidash && \
  gh pr merge $pr --repo OmniNode-ai/omnidash --squash --auto && \
  wait_for_merge OmniNode-ai/omnidash $pr
done
git -C $OMNI_HOME/omnidash pull --ff-only
restart_and_verify_dashboard

for pr in 545 543; do
  gh pr checks $pr --repo OmniNode-ai/omnidash && \
  gh pr merge $pr --repo OmniNode-ai/omnidash --squash --auto && \
  wait_for_merge OmniNode-ai/omnidash $pr
done
git -C $OMNI_HOME/omnidash pull --ff-only
restart_and_verify_dashboard
echo "dashboard final ok"
```

**Phase 4 checkpoint.**

---

## Phase 5: onex_change_control Pipeline

### Step 16 — Fix #141 ruff (if not already done in Phase 1)
```bash
# Verify CI is green before proceeding
gh pr checks 141 --repo OmniNode-ai/onex_change_control
```

### Step 17 — Merge #141–#146 in order
```bash
for pr in 141 142 143 144 145 146; do
  echo "Merging onex_change_control#$pr..."
  gh pr checks $pr --repo OmniNode-ai/onex_change_control
  gh pr merge $pr --repo OmniNode-ai/onex_change_control --squash --auto
  wait_for_merge OmniNode-ai/onex_change_control $pr
  git -C $OMNI_HOME/onex_change_control pull --ff-only
done
```

### Step 18 — Verify dependency scanner
```bash
cd $OMNI_HOME/onex_change_control
uv run python -c "
from onex_change_control.scripts.scan_contract_dependencies import scan_all_repos
results = scan_all_repos()
print(f'Scanned repos: {len(results)}')
for repo, deps in results.items():
    print(f'  {repo}: {len(deps)} contracts')
"
```

**Phase 5 checkpoint.**

---

## Phase 6: Post-Merge Verification

Run all sweeps to confirm the merged state is coherent.

```bash
# Dashboard sweep
onex run node_dashboard_sweep

# Data flow sweep
onex run node_data_flow_sweep

# Golden chain sweep
onex run node_golden_chain_sweep

# Runtime sweep
onex run node_runtime_sweep

# Final dashboard health check
curl -sf http://localhost:3000/api/health
curl -sf http://localhost:3000/delegation
curl -sf http://localhost:3000/events
curl -sf http://localhost:3000/intelligence
```

**Write overnight report:**

Run the report generation script from the Checkpoint Format section. This reads the checkpoint YAML and generates the handoff markdown automatically.

Then append the final system state:
```bash
cat >> $OMNI_HOME/.onex_state/handoff/session-2026-04-08-overnight.md << 'EOF'

## Final system state
- Dashboard: $(curl -sf http://localhost:3000/api/health | grep -q "ok" && echo "up" || echo "down")
- omnimarket handlers: $(cd $OMNI_HOME/omnimarket && uv run python -c "from omnimarket.handlers import *; print('ok')" 2>&1 | tail -1)
- onex_change_control scanner: $(cd $OMNI_HOME/onex_change_control && uv run python -c "from onex_change_control.scripts.scan_contract_dependencies import scan_all_repos; scan_all_repos(); print('ok')" 2>&1 | tail -1)
- omniclaude plugin: $(claude plugin list | grep omninode-tools | head -1)
EOF
```

**Phase 6 checkpoint.**

---

## Phase 7: Build Loop Test

### Gate — all of the following must be true before starting Phase 7:

```bash
# 1. Phase 2 complete: omnibase_core#792 + omnimarket#74 + #75 merged and verified
# 2. Phase 3 complete: omnimarket#76 + #77 + #78 merged and verified
# 3. Dashboard healthy
curl -sf http://localhost:3000/api/health | grep -q "ok" || { echo "GATE FAIL: dashboard not healthy"; exit 1; }
# 4. Event consumers healthy (Kafka consumer group lag check)
onex run node_consumer_health_check/contract.yaml || { echo "GATE FAIL: event consumers not healthy"; exit 1; }
echo "Phase 7 gate: PASS"
```

If any gate condition fails, do not proceed. Write the failure to checkpoint and stop.

### Step 6 — Run build loop test

```bash
cd $OMNI_HOME/omnimarket

# Capture stderr separately to distinguish failure modes
BUILD_STDERR=$(mktemp)
timeout 120 onex run node_build_loop_orchestrator/contract.yaml 2>"$BUILD_STDERR"
BUILD_EXIT=$?

if grep -qiE "ImportError|ModuleNotFoundError|Traceback" "$BUILD_STDERR"; then
  echo "FAIL: import/crash error — see $BUILD_STDERR"
  cat "$BUILD_STDERR"
  exit 1
elif [[ $BUILD_EXIT -eq 124 ]]; then
  echo "TIMEOUT: build loop ran for 120s without completing — check if expected"
elif [[ $BUILD_EXIT -ne 0 ]]; then
  echo "FAIL: build loop exited with code $BUILD_EXIT"
  cat "$BUILD_STDERR"
  exit 1
else
  echo "OK: build loop completed (exit 0)"
fi

# Verify Kafka events emitted
onex listen onex.event.build_loop.* --timeout 30 --count 1

# Check dashboard delegation page for new data
curl -sf http://localhost:3000/delegation | python3 -c "
import sys, json
data = json.load(sys.stdin)
assert len(data.get('delegations', [])) > 0, 'no delegation data'
print('delegation page: ok')
"
```

**Phase 7 checkpoint.**

---

## Checkpoint Format

### Write policy

- Write a checkpoint entry **after verification completes**, not after merge_requested.
- Use **append mode** only — never overwrite the checkpoint file.
- Use these distinct state values: `merge_requested` / `merged` / `verified` / `failed` / `skipped`.
- A phase is only `complete` when all its steps reach `verified`.

```bash
# Initialize on first write
mkdir -p $OMNI_HOME/.onex_state/overnight
touch $OMNI_HOME/.onex_state/overnight/2026-04-08-checkpoint.yaml

# Append a checkpoint entry (use >> not >)
cat >> $OMNI_HOME/.onex_state/overnight/2026-04-08-checkpoint.yaml << YAML
- phase: N
  status: verified   # merge_requested | merged | verified | failed | skipped
  timestamp: "$(date -u +%Y-%m-%dT%H:%MZ)"
  prs_merged:
    - repo/pr_number
  verifications:
    - check: "description"
      result: pass   # pass | fail
      detail: "optional note"
  next_action: "description of what comes next or why we stopped"
YAML
```

### Report generation from checkpoint

After Phase 6 (or at any point), generate the handoff markdown from the checkpoint:

```bash
python3 - << 'EOF'
import yaml, sys
from pathlib import Path

checkpoint_path = Path(f"{__import__('os').environ['OMNI_HOME']}/.onex_state/overnight/2026-04-08-checkpoint.yaml")
output_path = Path(f"{__import__('os').environ['OMNI_HOME']}/.onex_state/handoff/session-2026-04-08-overnight.md")

with open(checkpoint_path) as f:
    entries = yaml.safe_load(f) or []

lines = ["# Overnight Session Report — 2026-04-08", ""]
prs_merged = []
verifications_passed = []
failures = []

for entry in entries:
    prs_merged.extend(entry.get("prs_merged", []))
    for v in entry.get("verifications", []):
        if v.get("result") == "pass":
            verifications_passed.append(f"Phase {entry['phase']}: {v['check']}")
        else:
            failures.append(f"Phase {entry['phase']}: {v['check']} — {v.get('detail', '')}")

lines += ["## PRs merged", ""] + [f"- {p}" for p in prs_merged] + [""]
lines += ["## Verifications passed", ""] + [f"- {v}" for v in verifications_passed] + [""]
lines += ["## Failures / skipped", ""] + ([f"- {f}" for f in failures] if failures else ["- none"]) + [""]

# Final phase status summary
lines += ["## Phase status", ""]
for entry in entries:
    lines.append(f"- Phase {entry['phase']}: {entry['status']} ({entry.get('timestamp', '')})")

output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text("\n".join(lines))
print(f"Report written to {output_path}")
EOF
```

---

## Abort Conditions

| Condition | Action |
|-----------|--------|
| 3 consecutive merge failures on the same dependency chain | Stop that chain. Write diagnostic to checkpoint. Continue with independent PRs. |
| Runtime crash on .201 after rebuild trigger | Do NOT attempt recovery. Write checkpoint entry. Skip all further .201-touching infra work. |
| Dashboard unresponsive after restart (3 attempts) | Skip remaining dashboard merges. Mark dashboard PRs as "deferred". Continue with other repos. |
| CI still failing after Phase 1 fix was pushed and 10 min elapsed | Skip that PR. Mark as "blocked". Document which downstream PRs are also blocked. |

---

## PR Reference Table

| PR | Repo | Status | Phase | Depends on |
|----|------|--------|-------|------------|
| omnibase_core#792 | omnibase_core | CI nearly green | 2 | — |
| omniclaude#1161 | omniclaude | GREEN | 2 | — |
| omnimarket#74 | omnimarket | GREEN | 2 | omnibase_core#792 |
| omnimarket#75 | omnimarket | needs CI fix | 2 | #74 |
| omnimarket#76 | omnimarket | CI pending | 3 | #75 |
| omnimarket#77 | omnimarket | open | 3 | #76 |
| omnimarket#78 | omnimarket | blocked | 3 | #75 |
| omnidash#557 | omnidash | needs title fix | 4 | — |
| omnidash#558 | omnidash | CI pending | 4 | — |
| omnidash#555 | omnidash | GREEN | 4 | — |
| omnidash#556 | omnidash | GREEN | 4 | — |
| omnidash#554–#530 | omnidash | GREEN | 4 | — |
| omnidash#549,548,547,546,545,543 | omnidash | GREEN | 4 | — |
| omnibase_infra#1208 | omnibase_infra | needs ruff fix | 3 | — |
| omnibase_infra#1205 | omnibase_infra | CI pending | 3 | — |
| omnibase_infra#1206 | omnibase_infra | open | 3 | — |
| onex_change_control#141–#146 | onex_change_control | 5 GREEN, 1 ruff fix | 5 | #141 fixed first |
