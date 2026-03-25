<!-- persona: plugins/onex/skills/_lib/assistant-profile/persona.md -->
<!-- persona-scope: this-skill-only -- do not re-apply if polymorphic agent wraps this skill -->
Apply the persona profile above when generating outputs.

# Autopilot Skill Orchestration

You are executing the autopilot skill. This prompt defines the complete orchestration
logic for autonomous close-out and build-mode operation.

---

## Step 0: Announce <!-- ai-slop-ok: skill-step-heading -->

Say: "I'm using the autopilot skill."

---

## Step 1: Parse Arguments <!-- ai-slop-ok: skill-step-heading -->

Parse from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| `--mode <mode>` | `build` | `build` or `close-out` |
| `--autonomous` | `true` | No human gates |
| `--require-gate` | `false` | Opt-in Slack HIGH_RISK gate before release |
| `--reconcile-tags` | `false` | Auto-create git tags to align with pyproject.toml versions (F40) |

If `--mode` is not provided, default to `build`.

---

## Step 2: Mode Dispatch <!-- ai-slop-ok: skill-step-heading -->

**If `--mode build`**: execute Build Mode (see Build Mode section below). Stop after.

**If `--mode close-out`**: execute Close-Out Mode (Steps 2b–9b below). Stop after.

---

## Close-Out Mode

### Step 0: Initialize Cycle Record <!-- ai-slop-ok: skill-step-heading -->

Generate cycle_id: `autopilot-{mode}-{YYYYMMDD}-{6-char-random}`

Check for consecutive no-op cycles:
- Read the single most recent cycle record from `$ONEX_STATE_DIR/state/autopilot/` (by modification time)
- Read its `consecutive_noop_count` field directly (no need to reconstruct from multiple files)
- If `consecutive_noop_count >= 2`:
  Print: "WARNING: {count + 1} consecutive autopilot cycles found zero tickets.
  Unconditional surface probes still running but ticket-gated verification has not occurred."

Initialize step tracking: all 18 steps start as `not_run`, using canonical IDs:
```
A1_merge_sweep, A2_deploy_local_plugin, A3_start_environment,
B1_dod_sweep, B2_aislop_sweep, B3_bus_audit, B4_gap_detect, B5_integration_sweep,
B6_playwright_gate, B7_friction_triage, B8_duplication_sweep,
C1_release, C2_redeploy,
D1_verify_plugin, D2_container_health, D3_dashboard_sweep, D4_close_day, D5_insights_to_plan
```

**Step result vocabulary** (stable, for cycle records and completion summary):
- `pass` — step succeeded with no issues
- `pass_repaired` — step succeeded but required auto-repair first (A3 only)
- `warn` — step completed with non-blocking warnings
- `fail` — step failed (may or may not halt depending on halt authority)
- `halt` — step failed AND halted the pipeline (A3, B5, C1, C2 only)
- `skipped` — step was skipped (e.g., due to earlier halt)
- `not_run` — step has not been reached yet

---

### Cycle Mutex (F11) <!-- ai-slop-ok: skill-step-heading -->

At the START of every cycle:
1. Check `.onex_state/autopilot/cycle.lock`
2. If the lock exists and `started_at` is less than 45 minutes ago: **SKIP THIS CYCLE**. Log "Skipping — previous cycle still running (started {started_at})".
3. If the lock exists and `started_at` is >= 45 minutes ago: treat as stale, delete it.
4. Create `.onex_state/autopilot/cycle.lock` with contents:
   ```yaml
   started_at: <ISO timestamp>
   cycle_id: <unique id>
   ```
5. At the END of every cycle (success, failure, or no-op): delete the lock file.

**Ownership rule:** `cycle.lock` is owned only by the active autopilot cycle. No other process may remove a live lock opportunistically. Only stale recovery (>= 45 min) permits deletion by a new cycle.

---

### Cross-Cycle State <!-- ai-slop-ok: skill-step-heading -->

Before starting any cycle, read `.onex_state/autopilot/cycle-state.yaml`.

#### Strike Tracker (F13)

Before attempting to fix any BLOCKED PR:
1. Read `strike_tracker[<repo>/<pr_number>]` from cycle-state.yaml
2. If count >= 2: DO NOT attempt fixes. Write a diagnosis document per Two-Strike Protocol. Skip this PR.
3. If count < 2: proceed with fix attempt. After pushing, increment the counter and write back to cycle-state.yaml.

Strike counters reset when:
- The PR merges (remove the entry)
- The root cause changes (e.g., a dependency was updated — reset to 0 with a note)

#### Pending Redeploy Detection (F30)

At the START of every cycle (before merge-sweep), check:
1. For each repo with a release workflow, get the latest git tag
2. Compare against `last_deploy_version[<repo>]` in cycle-state.yaml
3. If tag > deployed version, add to `pending_redeploy[]`
4. If `pending_redeploy` is non-empty, run redeploy BEFORE merge-sweep

This ensures missed redeploys are caught on the next cycle, not lost.

---

### A1: merge-sweep <!-- ai-slop-ok: skill-step-heading -->

Run merge-sweep to drain open PRs before release:

```
/merge-sweep --autonomous
```

- On success: record `pass`, continue.
- On error (skill returns `error` status): record `fail`. Increment failure counter.
- On `nothing_to_merge`: record `warn`, continue (no PRs to drain; this is expected).

Check circuit breaker: if consecutive_failures >= 3 → HALT + Slack notify.

---

### A1a: Merge Queue Drain Wait (F39) <!-- ai-slop-ok: skill-step-heading -->

After merge-sweep completes, wait for all merge queues to drain before proceeding.
PRs that were enqueued (auto-merge armed) need time for CI to run and merge to complete.

**Skip condition**: If merge-sweep returned `nothing_to_merge` or `error`, skip this step
entirely. There are no queued PRs to wait for.

**Polling logic**:
```python
import time

MAX_DRAIN_WAIT_SECONDS = 15 * 60  # 15 minutes
POLL_INTERVAL_SECONDS = 60

elapsed = 0
while elapsed < MAX_DRAIN_WAIT_SECONDS:
    # Check all repos for PRs with active autoMergeRequest that haven't merged
    pending_prs = []
    for repo in repo_list:
        prs = gh_pr_list(repo, state="open", json_fields=["number", "autoMergeRequest"])
        for pr in prs:
            if pr.get("autoMergeRequest") is not None:
                pending_prs.append(f"{repo}#{pr['number']}")

    if not pending_prs:
        print(f"[autopilot] Merge queues drained in {elapsed}s. All enqueued PRs merged or dequeued.")
        break

    print(f"[autopilot] Waiting for {len(pending_prs)} PR(s) in merge queue: {pending_prs[:5]}{'...' if len(pending_prs) > 5 else ''} ({elapsed}s elapsed)")
    time.sleep(POLL_INTERVAL_SECONDS)
    elapsed += POLL_INTERVAL_SECONDS
else:
    print(f"WARNING: [autopilot] Merge queue drain timed out after {MAX_DRAIN_WAIT_SECONDS}s. "
          f"{len(pending_prs)} PR(s) still pending: {pending_prs}")
```

- On drain complete: record `pass`, continue.
- On timeout: record `warn` with message listing pending PRs. Do NOT halt. Continue to A2.
- On skip: record `pass` with note "No merge-sweep PRs to drain."

---

### A2: deploy-local-plugin <!-- ai-slop-ok: skill-step-heading -->

Activate newly merged omniclaude skills and hooks:

```
/deploy-local-plugin
```

- On success: record `pass`, continue. New skills/hooks are now available for Phase B quality sweeps.
- On error: record `warn`, continue. Plugin deploy failure is non-blocking — Phase B
  can still run with the previous plugin version.

---

### A3: start-environment — INFRA HEALTH GATE <!-- ai-slop-ok: skill-step-heading -->

Verify all infrastructure is running and healthy before proceeding:

```
/start-environment --mode auto
```

This skill audits actual container state (docker ps -a), starts missing core infra
(postgres, redpanda, valkey via infra-up), starts missing runtime services (via
infra-up-runtime), and verifies all containers are healthy.

Critical checks (specific pass criteria):
- postgres: running + healthy + responds to `SELECT 1` via `psql -h localhost -p 5436`
- migration-gate: running + healthy (proves `db_metadata.migrations_complete = TRUE` — all forward migrations applied)
- forward-migration: exited with code 0 (not stuck or crashed)
- intelligence-migration: exited with code 0
- redpanda: running + healthy + `rpk cluster health` returns clean
- valkey: running + healthy
- All runtime containers: show `(healthy)` in `docker ps -a` (not just "Up" — must pass healthcheck)

- On success (already healthy): record step result as `pass`. Continue.
- On success (after auto-repair): record step result as `pass_repaired`. Continue.
  A repaired pass is acceptable but must remain distinguishable from already-healthy
  infrastructure in the cycle record — it indicates the environment was degraded at
  pipeline start.
- On error: record `halt`. **HALT**. Report which containers are missing or unhealthy with exact
  `docker ps -a` status. Do NOT proceed to quality sweeps or release with broken infrastructure.

Increment failure counter on error. Check circuit breaker.

---

### B1-B4: Quality Sweeps (parallel) <!-- ai-slop-ok: skill-step-heading -->

Run B1 through B4 concurrently. Invoke all four skills simultaneously and collect
results before proceeding to B5.

**B1: dod-sweep**
```
/dod-sweep --since-days 7
```

**B2: aislop-sweep**
```
/aislop-sweep
```

**B3: bus-audit**
```
/bus-audit
```

**B4: gap detect**
```
/gap detect --no-fix
```

For each sweep:
- On success: record result as `pass`, continue.
- On warning: record result as `warn`, continue.
- On error: record result as `fail`, log the failure, increment failure counter.

**B1 DoD-sweep halt policy**: After all four sweeps complete, evaluate B1 separately.
If B1 (dod-sweep) returned `FAIL`, **HALT**. DoD failures indicate unresolved evidence
debt and block release. Print:
```
AUTOPILOT HALT: dod-sweep returned FAIL

Failing tickets:
  - {ticket_id}: {failed_checks}

Autopilot cannot proceed to release while DoD checks are failing.
Resolve the failures above, then re-run /autopilot --mode close-out.
```
Record B1 as `halt`. Mark remaining steps (B5-D4) as `skipped`. Check circuit breaker.

If B1 returned `UNKNOWN`: print summary as warning, continue. UNKNOWN is non-blocking
because exemptions are a legitimate source of UNKNOWN status.

B2, B3, B4 remain advisory — their failures do NOT halt.

**Phase B batch summary:** Record both individual advisory step outcomes AND
a batch-level advisory summary reflecting the worst advisory outcome (e.g., "B-batch: fail
(B2 failed, B1/B3/B4 passed)") while preserving breaker evaluation as one window.

Check circuit breaker after all four complete. The parallel batch counts as one
evaluation window for breaker purposes (see circuit breaker doctrine in SKILL.md).

---

### B5: integration-sweep — THE GUARD <!-- ai-slop-ok: skill-step-heading -->

**This step is the hard gate. Read it carefully.**

Run integration-sweep in full-infra mode (includes Kafka and DB probes):

```
/integration-sweep --mode=full-infra
```

After the sweep completes, read the artifact at:
```
$ONEX_CC_REPO_PATH/drift/integration/{TODAY}.yaml
```

Resolve `TODAY` as `date +%Y-%m-%d`.

Apply the halt policy:

```
overall_status == FAIL                              → HALT (do NOT proceed to release)
overall_status == UNKNOWN AND any reason is:
  NO_CONTRACT                                       → HALT (contract missing)
  INCONCLUSIVE                                      → HALT (ambiguous probe result)
  PROBE_UNAVAILABLE                                 → CONTINUE with warning
  NOT_APPLICABLE                                    → CONTINUE
overall_status == PASS                              → CONTINUE
```

**HALT behaviour**: Record `halt`. Stop all further steps (B6-D4 become `skipped`). Print:

```
AUTOPILOT HALT: integration-sweep returned {overall_status}

Failed surfaces:
  - {ticket_id} / {surface}: {reason} — {evidence}
  (repeat for each failing result)

Autopilot cannot proceed to release while integration surfaces are failing.
Resolve the failures above, then re-run /autopilot --mode close-out.
```

Do NOT emit a Slack notification for a clean halt — the report above is sufficient.

**CONTINUE with warning**: print a single warning line per unavailable probe, then continue.
Record `pass`.

---

### B6: playwright-gate — REGRESSION GATE <!-- ai-slop-ok: skill-step-heading -->

**This step is a hard gate for smoke failures. Read it carefully.**

Verify that omnidash is not broken before proceeding to release. This step consumes
the `PLAYWRIGHT_BEHAVIORAL` probe result from B5 (integration-sweep) rather than
rerunning the full Playwright suite, avoiding duplicate test execution.

**Step 1: Read the integration-sweep artifact**

Read the integration-sweep artifact written by B5:
```
$ONEX_CC_REPO_PATH/drift/integration/{TODAY}.yaml
```

Resolve `TODAY` as `date +%Y-%m-%d`.

Look for the `PLAYWRIGHT_BEHAVIORAL` surface entry in the results list.

**Step 2: Determine if rerun is needed**

A rerun is required when ANY of these conditions is true:
- The `PLAYWRIGHT_BEHAVIORAL` entry is missing from the artifact (probe was not run)
- The entry's `probed_at` timestamp is older than 10 minutes from now (stale result)
- The entry's `status` is `UNKNOWN` with reason `PROBE_UNAVAILABLE` (Playwright was not installed during sweep)

If rerun is NOT needed: use the existing result from the artifact. Skip to Step 4.

**Step 3: Rerun Playwright (only when stale, missing, or unavailable)**

```bash
OMNIDASH_DIR="${OMNIDASH_DIR:-/Volumes/PRO-G40/Code/omni_home/omnidash}"  # local-path-ok
```

3a. Check Playwright is installed:
```bash
cd $OMNIDASH_DIR && npx playwright --version 2>&1
```
- If command fails: record `status=UNKNOWN`, `reason=PROBE_UNAVAILABLE`,
  `evidence="Playwright not installed"`. Record step as `warn`, continue to C1.

3b. Run smoke tests:
```bash
cd $OMNIDASH_DIR && npx playwright test --config playwright.smoke.config.ts 2>&1
```
- exit code 0: smoke_result = PASS
- exit code non-zero: smoke_result = FAIL (capture last 20 lines as evidence)

3c. Run data-flow tests (only if smoke passed):
```bash
cd $OMNIDASH_DIR && npx playwright test --config playwright.dataflow.config.ts 2>&1
```
- exit code 0: dataflow_result = PASS
- exit code non-zero: dataflow_result = FAIL (capture last 20 lines as evidence)

3d. Aggregate:
- smoke FAIL → surface_result = FAIL
- smoke PASS + dataflow FAIL → surface_result = PASS_WITH_WARNINGS
- smoke PASS + dataflow PASS → surface_result = PASS

**Step 4: Apply halt policy**

```
surface_result == FAIL                    → HALT (smoke tests failed — UI is broken)
surface_result == PASS_WITH_WARNINGS      → CONTINUE with warning (data-flow failure is soft gate)
surface_result == PASS                    → CONTINUE
surface_result == UNKNOWN/PROBE_UNAVAILABLE → CONTINUE with warning
```

**HALT behaviour**: Record `halt`. Stop all further steps (C1-D4 become `skipped`). Print:

```
AUTOPILOT HALT: Playwright regression gate FAILED — smoke tests failing

Evidence:
  {last 20 lines of smoke test output, from artifact or rerun}

Autopilot cannot proceed to release while Playwright smoke tests are failing.
Fix the failing tests, then re-run /autopilot --mode close-out.
```

**CONTINUE with warning** (PASS_WITH_WARNINGS): Print a single warning line:
```
WARNING: Playwright data-flow tests failed (soft gate) — smoke tests passed.
Data-flow evidence: {summary of failure}
```
Record step as `warn`.

**CONTINUE** (PASS): Record step as `pass`.

Increment failure counter if surface_result is FAIL.

Check circuit breaker.

---

### B7: friction-triage <!-- ai-slop-ok: skill-step-heading -->

Run friction-triage to surface recurring friction patterns as Linear tickets:

```
/friction-triage --window_days 7
```

**Halt policy:** NEVER halt. Friction triage generates remediation backlog (Linear tickets
for recurring friction patterns). It does not surface immediate release risk.
Log the number of tickets created.

**Skip condition:** If `~/.claude/state/friction/friction.ndjson` does not exist
or is empty, skip with message "No friction events recorded."

- On success: record `pass`, continue.
- On skip: record `pass` with note "No friction events recorded."
- On error: record `fail`. Log the failure, increment failure counter. Do NOT halt.

Check circuit breaker.

---

### B8: duplication-sweep <!-- ai-slop-ok: skill-step-heading -->

Run duplication-sweep to detect structural collisions across repos:

```
/duplication-sweep --omni-home $OMNI_HOME
```

**Halt policy:** HALT on any FAIL finding from checks D1-D4. WARN findings
are logged but do not halt. B8 halts because duplicate Drizzle tables, topic
registration conflicts, and migration collisions are immediate structural defects
that can cause silent data routing failures in the current release.

**Skip condition:** If $OMNI_HOME is not set or the directory does not exist,
skip with warning "OMNI_HOME not available for duplication sweep."

- On success (all PASS/WARN): record `pass`, continue.
- On FAIL: record `halt`. **HALT**. Report failing checks (D1-D4) and their findings.
- On skip: record `pass` with warning note.
- On error: record `fail`. Increment failure counter.

Check circuit breaker.

---

### C0: Tag Drift Detection (F40) <!-- ai-slop-ok: skill-step-heading -->

Before releasing, verify that git tags are aligned with `pyproject.toml` versions across
all repos. Tag drift indicates a prior release that was not tagged, or a version bump that
was not released.

**Detection logic**:
```python
import tomllib
from pathlib import Path

tag_drift_warnings = []

for repo in repo_list:
    repo_path = Path(omni_home) / repo.split("/")[-1]
    pyproject_path = repo_path / "pyproject.toml"

    if not pyproject_path.exists():
        continue  # not a Python repo (e.g., omnidash)

    # Get pyproject version
    with open(pyproject_path, "rb") as f:
        pyproject = tomllib.load(f)
    pyproject_version = pyproject.get("project", {}).get("version", "0.0.0")

    # Get latest git tag
    latest_tag = run(f"git -C {repo_path} describe --tags --abbrev=0 2>/dev/null || echo 'v0.0.0'").strip()
    tag_version = latest_tag.lstrip("v")

    # Compare minor versions
    pyproject_parts = [int(x) for x in pyproject_version.split(".")[:3]]
    tag_parts = [int(x) for x in tag_version.split(".")[:3]]

    minor_drift = abs(pyproject_parts[1] - tag_parts[1])
    if minor_drift > 1 or pyproject_parts[0] != tag_parts[0]:
        tag_drift_warnings.append({
            "repo": repo,
            "pyproject_version": pyproject_version,
            "latest_tag": latest_tag,
            "drift": f"{minor_drift} minor versions" if pyproject_parts[0] == tag_parts[0] else "major version mismatch",
        })

for w in tag_drift_warnings:
    print(f"WARNING: Tag drift in {w['repo']}: pyproject={w['pyproject_version']} tag={w['latest_tag']} ({w['drift']})")
```

**`--reconcile-tags` flag**: If passed, create missing tags to align with pyproject versions:
```bash
git -C {repo_path} tag -a "v{pyproject_version}" -m "chore: reconcile tag to pyproject version {pyproject_version}"
git -C {repo_path} push origin "v{pyproject_version}"
```

Add to the autopilot argument table:

| Argument | Default | Description |
|----------|---------|-------------|
| `--reconcile-tags` | `false` | Auto-create git tags to align with pyproject.toml versions |

**Halt policy**: NEVER halt. Tag drift is informational. Log warnings and continue to C1.

- On no drift: record `pass`, continue.
- On drift detected (no reconcile): record `warn`, log warnings, continue.
- On drift reconciled: record `pass` with note listing reconciled tags.
- On error: record `fail`, log error, continue (do NOT halt).

---

### C1: release <!-- ai-slop-ok: skill-step-heading -->

Integration-sweep passed. Proceed to release.

**If `--require-gate`**:
- Post a Slack HIGH_RISK gate message:
  ```
  [autopilot] Integration sweep PASSED. Ready to release. Reply APPROVE to proceed.
  ```
- Wait for explicit APPROVE reply before continuing.
- If not approved within timeout: record `halt` with message "Release gate timed out — no approval received."

**If not `--require-gate`** (default — `--autonomous`):
- Proceed automatically. No gate.

Run:
```
/release --bump patch
```

- On success: record `pass`. Record ship provenance: version/tag/commit produced by release.
- On error: record `halt`. **HALT**. Report the release failure.

Increment failure counter if release fails.
Check circuit breaker.

---

### C2: redeploy <!-- ai-slop-ok: skill-step-heading -->

Run:
```
/redeploy
```

- On success: record `pass`. Record redeployed target confirmation.
- On error: record `halt`. **HALT**. Report the redeploy failure.

Increment failure counter if redeploy fails.
Check circuit breaker.

---

### D1-D3: Post-Release Verification (parallel) <!-- ai-slop-ok: skill-step-heading -->

Run D1, D2, and D3 concurrently. Collect results before proceeding to D4.

**D1: verify-plugin**
```
/verify-plugin
```

**D2: container-health**
Verify all containers came back healthy after redeploy:
```bash
docker ps -a --format "table {{.Names}}\t{{.Status}}" | grep -i "unhealthy\|Exited"
```
Record: which containers are healthy, which are unhealthy, which exited.

**D2 pass-vs-warn thresholds:**
- `pass`: all core runtime containers healthy (omninode-runtime, intelligence-api, all consumers)
- `warn`: core runtime healthy but optional/non-critical containers degraded (phoenix, memgraph, autoheal)
- `fail`: any core runtime container unhealthy or missing

**D3: dashboard-sweep**
```
/dashboard-sweep --mode audit
```
Record: which omnidash pages pass, which fail.

**D3 pass-vs-warn thresholds:**
- `pass`: all core omnidash pages load and render data (/, /epic-pipeline, /live-events, /status)
- `warn`: core pages work but secondary pages degraded (patterns, llm-routing, graph)
- `fail`: any core demo-path page fails to load or render

D1, D2, and D3 report separately — runtime health (D2) and user-visible health (D3) must
not collapse into one status. A system can have all containers healthy but broken dashboard
pages, or vice versa.

Post-release verification (D1-D3) should reference the ship provenance from C1/C2 to tie
observations to the specific shipped artifact.

For each verification:
- On success: record step result as `pass`.
- On warning: record step result as `warn`.
- On error: record step result as `fail`. Log warning. Do NOT halt and do NOT increment circuit breaker — release and
  redeploy already completed. Failures here indicate the release may need a follow-up fix.

---

### D4: close-day <!-- ai-slop-ok: skill-step-heading -->

Run:
```
/close-day
```

- On success: record `pass`, continue.
- On error: record `fail`. Report the failure but do NOT halt. Close-day is audit-only; a failure here
  does not invalidate the release and redeploy that already completed successfully.

---

### D5: insights-to-plan (optional) <!-- ai-slop-ok: skill-step-heading -->

Check if today's insights report exists at `docs/registry/insights/YYYY-MM-DD.html`
(replace YYYY-MM-DD with today's date, e.g., 2026-03-24).

**If file exists:** Run `/insights-to-plan --file docs/registry/insights/YYYY-MM-DD.html --tickets`.

**If file does not exist:** Run `/linear-insights --mode deep-dive --save` to generate
today's deep dive report first. Then check if a Claude Code insights HTML was generated
during this session. If found, run `/insights-to-plan --file <path> --tickets`.
If no insights file is available, skip with message "No insights report for today."

**Halt policy:** NEVER halt. This step generates strategic follow-up tickets,
not release-risk findings.

**Caveat:** Step D5 is opportunistic automation based on report availability,
not proof that the generated insights are complete, fresh, or uniquely
authoritative for the session. It runs because a file exists, not because
the file has been validated as high-quality input.

- On success: record `pass`, continue.
- On skip: record `pass` with note "No insights report for today."
- On error: record `fail`. Log the failure but do NOT halt. Insights-to-plan is strategic;
  a failure here does not invalidate the release and redeploy.

---

### Step 8a: Friction Diary (F38) <!-- ai-slop-ok: skill-step-heading -->

After all steps complete (or halt), capture friction events from the current run before
the completion summary. This step NEVER halts the pipeline.

**Friction identification**: scan the current cycle's step results for:
- Steps that recorded `fail` (non-halting failures)
- Steps that recorded `pass_repaired` (recovered infrastructure)
- Steps that recorded `warn` (advisory warnings)
- Any errors logged during scan, classification, or agent dispatch
- Branch update failures or claim race conditions from merge-sweep

**Write friction diary**:
```bash
TODAY=$(date +%Y-%m-%d)
SESSION_ID="${cycle_id}"
FRICTION_DIR="docs/tracking/friction"
mkdir -p "$FRICTION_DIR"
```

Append to `docs/tracking/friction/{TODAY}-closeout-{session_id}.md`:
```markdown
# Friction Diary: {cycle_id}

Date: {TODAY}
Mode: close-out
Friction events: {count}

| Step | Status | Friction |
|------|--------|----------|
| {step_id} | {status} | {description of what went wrong or required recovery} |
...
```

Only include rows for steps that had friction (fail, warn, pass_repaired). Steps with
clean `pass` are omitted.

**Integration with completion summary**: include a friction count line:
```
Friction events captured: {count} (see docs/tracking/friction/{TODAY}-closeout-{session_id}.md)
```

If zero friction events occurred, skip the file write and print:
```
Friction events captured: 0 (clean run)
```

---

### Circuit Breaker Check <!-- ai-slop-ok: skill-step-heading -->

After all steps complete, if `consecutive_failures >= 3` was triggered at any point:

```
AUTOPILOT CIRCUIT BREAKER: 3 consecutive step failures detected.
Pipeline stopped.

Failed steps: {step_names}

Post a Slack notify and stop.
```

Post Slack notification:
```
[autopilot] Circuit breaker triggered — 3 consecutive failures.
Steps failed: {step_names}
Manual intervention required.
```

---

### Completion Summary <!-- ai-slop-ok: skill-step-heading -->

Print:

```
AUTOPILOT CLOSE-OUT COMPLETE

Steps:
  A1: merge-sweep          — {status}
  A2: deploy-local-plugin  — {status}
  A3: start-environment    — {status}
  B1: dod-sweep            — {status}
  B2: aislop-sweep         — {status}
  B3: bus-audit            — {status}
  B4: gap-detect           — {status}
  B5: integration-sweep    — {status}
  B6: playwright-gate      — {status}
  B7: friction-triage      — {status}
  B8: duplication-sweep    — {status}
  C1: release              — {status}  {version/tag if pass}
  C2: redeploy             — {status}
  D1: verify-plugin        — {status}
  D2: container-health     — {status}
  D3: dashboard-sweep      — {status}
  D4: close-day            — {status}
  D5: insights-to-plan     — {status}

Ship provenance: {version/tag/commit from C1, or "N/A — no ship occurred"}
Friction events captured: {friction_count} {friction_file_path or "(clean run)"}

Status: {complete|halted|circuit_breaker}
```

`pass_repaired` MUST be surfaced prominently in the completion summary and any Slack
close-out notification — not treated as visually equivalent to a clean `pass`. This signals
the run succeeded on recovered infrastructure, which is operationally significant even
though non-blocking.

Emit result line:
```
AUTOPILOT_RESULT: {status} mode=close-out
```

---

### Write Cycle Record <!-- ai-slop-ok: skill-step-heading -->

Populate `ModelAutopilotCycleRecord`:
- Set each step's status from execution results using canonical IDs (A1-D4, including B6)
- Set `overall_status` (using `EnumAutopilotCycleStatus`):
  - `COMPLETE` if all steps are `pass`, `pass_repaired`, `warn`, or `skipped` (and every skipped step has a non-empty `reason` — the model validator enforces this)
  - `INCOMPLETE` if any step has status `not_run`, or if any step is `skipped` without a valid reason (should not happen if model validation is correct, but defense-in-depth)
  - `HALTED` if A3, B5, B6, C1, or C2 triggered a halt
  - `CIRCUIT_BREAKER` if 3 consecutive failures occurred
- Set `consecutive_noop_count` from previous cycle + 1 if no tickets found, else reset to 0

Write YAML to: `$ONEX_STATE_DIR/state/autopilot/{cycle_id}/summary.yaml`

Ensure the parent directory exists:
```bash
mkdir -p "$ONEX_STATE_DIR/state/autopilot/{cycle_id}"
```

The 14-step completion summary must be persisted as a durable cycle artifact, not only
emitted in conversational output. This ensures repaired passes, warnings, halts, and
skipped downstream steps remain auditable across sessions.

If `overall_status == "incomplete"`:
  Print: "CYCLE INCOMPLETE: Steps {list of not_run steps} were never executed."

---

### Cycle Completion State Write <!-- ai-slop-ok: skill-step-heading -->

After every cycle (including no-ops), update `.onex_state/autopilot/cycle-state.yaml`:
- Set `last_cycle_id` to current ISO timestamp
- Set `last_cycle_status` to the cycle outcome
- Update `strike_tracker` (remove merged PRs, increment attempted PRs)
- Update `last_release_tag` if a release was published
- Update `last_deploy_version` if redeploy completed
- Clear `pending_redeploy` entries that were deployed
- Deduplicate `pending_redeploy` before writing

Then delete `.onex_state/autopilot/cycle.lock` to release the mutex.

If `cycle-state.yaml` has `last_cycle_id != null`, preserve existing data and merge
updates rather than overwriting. This is durable coordination state.

---

## Build Mode

**Reference only — full spec in OMN-5120.**

Build mode drives autonomous ticket execution:

```
1. Query Linear for unblocked Todo tickets (team=Omninode, state=Todo, no blockers)
2. For each ticket (in priority order):
   a. Claim the ticket (set state=In Progress)
   b. Dispatch /ticket-pipeline for the ticket ID
   c1. Wait for ticket-pipeline to complete
   c2. Run per-repo integration tests (see below)
   d. Clean up worktree
3. Repeat until no unblocked Todo tickets remain
```

### Step c2: Per-Repo Integration Tests [OMN-6294]

After each ticket-pipeline completes, run the repo's integration test suite in the
worktree to catch regressions immediately:

**Python repos** (omnibase_core, omnibase_infra, omnibase_spi, omniclaude, etc.):
```bash
uv run pytest tests/ -m integration --timeout=120
```

**TypeScript repos** (omnidash):
```bash
npx playwright test --config playwright.smoke.config.ts
```

**Result handling — non-halting:**
- On PASS: log "Integration tests passed for {repo}", continue to next ticket.
- On FAIL: do NOT halt build mode. Instead:
  1. Log the failure details (which tests failed, stderr output).
  2. Create a follow-up Linear ticket in Active Sprint with:
     - Title: `fix(integration): {repo} integration test failure after {ticket-id}`
     - Description must include: which ticket just completed, which tests failed,
       and the statement "This regression was observed immediately after {ticket-id}
       completion and may be causally related."
     - Priority: High
     - Label: the repo name
  3. Continue to the next ticket.

**Causality doctrine:** Non-halting integration failures in build mode are a throughput
policy choice, not a claim that the failure is benign. Follow-up tickets must explicitly
record that the regression was observed immediately after the ticket's completion and
may be causally related.

**Timeout:** 120 seconds. If the test suite exceeds this, treat as FAIL and create the
follow-up ticket with "timeout exceeded" as the failure reason.

Circuit breaker applies: 3 consecutive ticket-pipeline failures → stop.
Integration test failures do NOT count toward the circuit breaker (they are follow-up
tickets, not pipeline failures).

Emit result line:
```
AUTOPILOT_RESULT: complete mode=build tickets_processed={N} integration_failures={M}
```

---

## Error Handling <!-- ai-slop-ok: skill-step-heading -->

- If `ONEX_CC_REPO_PATH` is not set: HALT with
  `AUTOPILOT HALT: ONEX_CC_REPO_PATH not set — cannot read integration-sweep artifact`
- If integration-sweep artifact is missing after the sweep: treat as `overall_status=UNKNOWN/INCONCLUSIVE` → HALT
- If a step skill does not return a recognisable result: treat as error for circuit breaker purposes
- Never silently swallow errors — always surface the exception or error message

---

## Execution Rules

Execute end-to-end without stopping between steps unless explicitly halted by:
- A3 (start-environment) failure — cannot proceed with broken infrastructure
- B5 (integration-sweep) FAIL or HALT-class UNKNOWN
- B6 (playwright-gate) smoke FAIL — UI is broken, cannot release
- C1 (release) failure
- C2 (redeploy) failure
- Circuit breaker trigger (3 consecutive failures)
- `--require-gate` timeout (C1, if opted in)

Do not pause between steps to ask the user. `--require-gate` is the only opt-in pause mechanism.
