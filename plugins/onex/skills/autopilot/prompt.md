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

**If `--mode close-out`**: execute Close-Out Mode (Steps 3–9 below). Stop after.

---

## Close-Out Mode

### Step 3: merge-sweep <!-- ai-slop-ok: skill-step-heading -->

Run merge-sweep to drain open PRs before release:

```
/merge-sweep --autonomous
```

- On success: continue.
- On error (skill returns `error` status): **HALT**. Report the merge-sweep failure. Do NOT proceed.
- On `nothing_to_merge`: continue (no PRs to drain; this is expected).

Increment failure counter if merge-sweep returns `error`.
Check circuit breaker: if consecutive_failures >= 3 → HALT + Slack notify.

---

### Step 4: integration-sweep — THE GUARD <!-- ai-slop-ok: skill-step-heading -->

**This step is the hard gate. Read it carefully.**

Run integration-sweep in omniclaude-only mode:

```
/integration-sweep --mode=omniclaude-only
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

**HALT behaviour**: Stop all further steps. Print:

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

Increment failure counter if overall_status is FAIL or HALT-class UNKNOWN.
Check circuit breaker.

---

### Step 5: release <!-- ai-slop-ok: skill-step-heading -->

Integration-sweep passed. Proceed to release.

**If `--require-gate`**:
- Post a Slack HIGH_RISK gate message:
  ```
  [autopilot] Integration sweep PASSED. Ready to release. Reply APPROVE to proceed.
  ```
- Wait for explicit APPROVE reply before continuing.
- If not approved within timeout: HALT with message "Release gate timed out — no approval received."

**If not `--require-gate`** (default — `--autonomous`):
- Proceed automatically. No gate.

Run:
```
/release --bump patch
```

- On success: continue.
- On error: **HALT**. Report the release failure.

Increment failure counter if release fails.
Check circuit breaker.

---

### Step 6: redeploy <!-- ai-slop-ok: skill-step-heading -->

Run:
```
/redeploy
```

- On success: continue.
- On error: **HALT**. Report the redeploy failure.

Increment failure counter if redeploy fails.
Check circuit breaker.

---

### Step 7: close-day <!-- ai-slop-ok: skill-step-heading -->

Run:
```
/close-day
```

- On success: continue.
- On error: report the failure but do NOT halt. Close-day is audit-only; a failure here
  does not invalidate the release and redeploy that already completed successfully.

---

### Step 8: Circuit Breaker Check <!-- ai-slop-ok: skill-step-heading -->

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

### Step 9: Completion Summary <!-- ai-slop-ok: skill-step-heading -->

Print:

```
AUTOPILOT CLOSE-OUT COMPLETE

Steps:
  Step 1: merge-sweep     — {status}
  Step 2: integration-sweep — PASS  (guard cleared)
  Step 3: release         — {status}
  Step 4: redeploy        — {status}
  Step 5: close-day       — {status}

Status: complete
```

Emit result line:
```
AUTOPILOT_RESULT: complete mode=close-out
```

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
- Integration-sweep FAIL or HALT-class UNKNOWN (Step 4)
- merge-sweep returning `error` (Step 3)
- release failure (Step 5)
- redeploy failure (Step 6)
- Circuit breaker trigger (3 consecutive failures)
- `--require-gate` timeout (Step 5, if opted in)

Do not pause between steps to ask the user. `--require-gate` is the only opt-in pause mechanism.
