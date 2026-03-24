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

Initialize step tracking: all 14 steps start as `not_run`, using canonical IDs:
```
A1_merge_sweep, A2_deploy_local_plugin, A3_start_environment,
B1_dod_sweep, B2_aislop_sweep, B3_bus_audit, B4_gap_detect, B5_integration_sweep,
C1_release, C2_redeploy,
D1_verify_plugin, D2_container_health, D3_dashboard_sweep, D4_close_day
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
- On error: record result as `fail`, log the failure, increment failure counter. Do NOT halt — these are
  informational quality audits. Only B5 (integration-sweep) can halt.

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

**HALT behaviour**: Record `halt`. Stop all further steps (C1-D4 become `skipped`). Print:

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
  C1: release              — {status}  {version/tag if pass}
  C2: redeploy             — {status}
  D1: verify-plugin        — {status}
  D2: container-health     — {status}
  D3: dashboard-sweep      — {status}
  D4: close-day            — {status}

Ship provenance: {version/tag/commit from C1, or "N/A — no ship occurred"}

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
- Set each step's status from execution results using canonical IDs (A1-D4)
- Set `overall_status` (using `EnumAutopilotCycleStatus`):
  - `COMPLETE` if all steps are `pass`, `pass_repaired`, `warn`, or `skipped` (and every skipped step has a non-empty `reason` — the model validator enforces this)
  - `INCOMPLETE` if any step has status `not_run`, or if any step is `skipped` without a valid reason (should not happen if model validation is correct, but defense-in-depth)
  - `HALTED` if A3, B5, C1, or C2 triggered a halt
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

## Build Mode

**Reference only — full spec in OMN-5120.**

Build mode drives autonomous ticket execution:

```
1. Query Linear for unblocked Todo tickets (team=Omninode, state=Todo, no blockers)
2. For each ticket (in priority order):
   a. Claim the ticket (set state=In Progress)
   b. Dispatch /ticket-pipeline for the ticket ID
   c. Wait for ticket-pipeline to complete
   d. Clean up worktree
3. Repeat until no unblocked Todo tickets remain
```

Circuit breaker applies: 3 consecutive ticket-pipeline failures → stop.

Emit result line:
```
AUTOPILOT_RESULT: complete mode=build tickets_processed={N}
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
- C1 (release) failure
- C2 (redeploy) failure
- Circuit breaker trigger (3 consecutive failures)
- `--require-gate` timeout (C1, if opted in)

Do not pause between steps to ask the user. `--require-gate` is the only opt-in pause mechanism.
