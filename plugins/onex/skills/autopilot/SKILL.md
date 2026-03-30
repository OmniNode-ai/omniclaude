---
description: Autonomous close-out orchestrator — 4-phase pipeline with worktree health sweep, full merge-sweep with DIRTY PR triage and queue stall detection, infra health gate, quality sweeps (dod-sweep with per-ticket verification, aislop-sweep, bus-audit, gap detect), integration-sweep hard gate, Playwright regression gate, release, redeploy, and post-release verification (verify-plugin, dashboard-sweep, container health). Compounds — each cycle's merged infrastructure makes the next cycle's gate stricter.
version: 3.0.0
mode: full
level: advanced
debug: false
category: workflow
tags:
  - autonomous
  - close-out
  - pipeline
  - integration
  - release
  - deploy
  - org-wide
author: OmniClaude Team
composable: true
args:
  - name: --mode
    description: "Execution mode: build | close-out (default: build)"
    required: false
  - name: --autonomous
    description: "Run without human gates (default: true)"
    required: false
  - name: --require-gate
    description: "Opt into a Slack HIGH_RISK gate before the release step (default: false)"
    required: false
inputs:
  - name: mode
    description: "build | close-out"
outputs:
  - name: status
    description: "complete | halted | error"
  - name: halt_reason
    description: "Integration surface(s) that caused halt, or empty string on complete"
---

# autopilot

**Skill ID**: `onex:autopilot`
**Version**: 3.0.0
**Owner**: omniclaude
**Ticket**: OMN-6872
**Epic**: OMN-5431

---

## Dispatch Surface

**Target**: Headless claude -p

---

## Purpose

Top-level autonomous close-out orchestrator.

In `--mode close-out`, autopilot executes the full pipeline in 4 phases:

**Phase A — Prepare (sequential):**
- A0: worktree-health — sweep worktrees for lost uncommitted work, auto-clean merged worktrees, create recovery tickets for dirty worktrees [OMN-6867]
- A1: merge-sweep — drain open PRs (full merge-sweep skill: Track A auto-merge, Track A-update branch refresh, Track A-resolve thread resolution, Track B pr-polish for fixable blockers)
- A1b: dirty-pr-triage — explicit DIRTY/CONFLICTING PR detection, auto-close stale PRs (>24h), queue stall detection, missing auto-merge detection [OMN-6872]
- A2: deploy-local-plugin — activate newly merged skills/hooks for this session
- A3: start-environment — audit-first infra startup: verify core infra (postgres, redpanda, valkey) running, migration-gate healthy (proves DB migrations current), all runtime containers healthy. Auto-fixes by running infra-up + infra-up-runtime if containers missing.

**Phase B — Quality Gate (B1-B4 parallel, B4b data verification parallel advisory, B5-B6 sequential hard gates):**
- B1: dod-sweep — query tickets completed since last cycle, run dod-verify against each, flag incomplete DoD evidence
- B2: aislop-sweep — AI anti-patterns in recent merges
- B3: bus-audit — Kafka topic health / schema drift
- B4: gap detect --no-fix — cross-repo integration health
- B4b: data-verification (advisory, parallel with B1-B4) — runs all three data sweeps in dry-run:
  - `/database-sweep --dry-run` — projection table health
  - `/data-flow-sweep --dry-run --skip-playwright` — end-to-end pipeline check
  - `/runtime-sweep --dry-run` — node registration and wiring integrity
  Findings appended to close-day report. Non-blocking — does NOT halt pipeline.
- B5: integration-sweep — **HARD GATE** (unchanged halt policy)
- B6: playwright-gate — **HARD GATE** for smoke failures; consumes B5 Playwright result (reruns only if stale >10 min or missing)

B1-B4 are read-only audits, safe to parallelize. Failures in B1-B4 are logged and increment
the circuit breaker but do NOT halt the pipeline. B5 and B6 have halt authority.

**Phase C — Ship (sequential):**
- C1: release — version bump + publish (gated by integration-sweep)
- C2: redeploy — runtime refresh

**Phase D — Verify (D1-D3 parallel, D4 sequential):**
- D1: verify-plugin — confirm new omniclaude plugin deployed correctly
- D2: container-health — verify all runtime containers healthy after redeploy
- D3: dashboard-sweep — verify omnidash pages work
- D4: close-day — audit artifact

D1-D3 are read-only verification. Failures are logged with warnings but do NOT halt —
the release and redeploy already completed successfully.

**Note:** This is a 20-step pipeline (A0-A3 including A1b, B1-B8, C1-C2, D1-D5). Internal step IDs use the
`{phase}{ordinal}` scheme for stable naming in cycle records, circuit breaker logs, and
downstream debugging.

**Compounding principle:** Step A2 (deploy-local-plugin) ensures that quality sweeps in Phase B
run with the latest enforcement tools. Each cycle's merged infrastructure makes the next
cycle's gate stricter.

In `--mode build` (default), autopilot queries Linear for unblocked Todo tickets and
dispatches `onex:ticket-pipeline` for each. Full build-mode spec is in OMN-5120.

---

## Usage

```
/autopilot
/autopilot --mode close-out
/autopilot --mode close-out --require-gate
/autopilot --mode build
```

---

## Invocation Patterns: CronCreate vs Headless Cron

There are two supported patterns for recurring autopilot execution. The headless cron
pattern is **preferred** for production use because it avoids context accumulation.

### Pattern 1: CronCreate (in-session, context-accumulating)

Uses Claude Code's built-in `CronCreate` to fire autopilot on a schedule within an
active interactive session. Each firing shares the session's context window.

```
/loop 30m /autopilot --mode close-out
```

**Pros**: Simple setup, immediate, no external dependencies.
**Cons**: Context accumulates across invocations. After 2-3 passes the session hits
`context_window_exceeded` errors (9 recorded friction events). Only viable for short
sessions with 1-2 passes.

**When to use**: Quick interactive close-out sessions where you will monitor and
`/clear` between passes.

### Pattern 2: Headless Cron (recommended for production)

Uses `claude -p` (print mode) via `scripts/cron-closeout.sh`. Each phase gets a
**fresh context window** via a separate `claude -p` invocation. State persists via
`.onex_state/autopilot/cycle-state.yaml` and per-run output files.

Architecture follows the headless decomposition pattern from
`omnibase_infra/docs/patterns/headless_decomposition.md`:
- **One task per invocation** (bounded context, <15 min timeout)
- **State handoff via files** (no shared session state)
- **Idempotent** (safe to re-run at any point)
- **Lock-file concurrency guard** (prevents overlapping runs)

```bash
# Direct invocation (one full close-out cycle)
./scripts/cron-closeout.sh

# Dry run — prints phases without executing claude -p
./scripts/cron-closeout.sh --dry-run

# Via crontab (every 30 minutes)
*/30 * * * * $OMNI_HOME/omniclaude/scripts/cron-closeout.sh >> /tmp/cron-closeout.log 2>&1  # local-path-ok: crontab example

# Via launchd (macOS)
# Create ~/Library/LaunchAgents/com.omninode.cron-closeout.plist
```

**State layout**:
```
.onex_state/autopilot/
  cycle-state.yaml                     # Cross-run state (deployed versions, strikes)
  cron-closeout.lock                   # Concurrency guard (auto-removed on exit)
  runs/
    closeout-2026-03-28T22-00-00Z/     # Per-run directory
      A1_merge_sweep.txt               # Phase output
      A2_deploy_plugin.txt
      A3_start_env.txt
      B5_integration.txt               # Hard gate output
      C1_release_check.txt
      C2_redeploy_check.txt
      D3_dashboard_sweep.txt
      pending_redeploys.txt            # F30 detection result
      summary.txt                      # Run summary
```

**Phases executed** (each a separate `claude -p` invocation):

| Phase | Name | Gate? | Description |
|-------|------|-------|-------------|
| A0 | worktree-health | No | `prune-worktrees.sh --execute` — clean merged worktrees, skip unpushed/dirty [OMN-7021] |
| A1 | merge-sweep | No | Drain open PRs with passing CI |
| A2 | deploy-plugin | No | Copy plugin to cache |
| A3 | infra-health | No | Verify postgres, redpanda, valkey |
| B1 | runtime-sweep | **Hard** | Containers healthy, node dispatch alive [OMN-7002] |
| B2 | data-flow-sweep | **Hard** | Kafka consumers active, projections populated [OMN-7002] |
| B3 | database-sweep | **Hard** | Projection tables have data [OMN-7002] |
| B5 | integration-gate | **Hard** | Postgres + Redpanda must be healthy |
| C1 | release-check | No | Report unreleased commits per repo |
| C2 | redeploy-check | Conditional | Only if F30 detects version drift |
| D3 | dashboard-sweep | No | Non-blocking health check |

**F30 pending redeploy detection**: Before Phase C, the script compares git tags
in each repo against `last_deploy_version` in `cycle-state.yaml`. If any tag has
advanced beyond the recorded version, the repo is flagged for redeploy.

**Circuit breaker**: 3 consecutive phase failures → pipeline halts with exit code 2.
Resets on any successful integration gate pass.

**Lock timeout**: 45 minutes. If a previous run's lock is older than this, it is
treated as stale and removed.

**Pros**: No context accumulation, survives session crashes, externally observable
state, can run unattended for days.
**Cons**: Requires `claude` CLI and environment variables configured externally.

**When to use**: Overnight close-out, unattended pipeline operation, any run
expected to exceed 2-3 passes.

---

## Integration-Sweep Halt Policy

| `overall_status` | `reason` | Action |
|-----------------|---------|--------|
| `FAIL` | any | **HALT** — report failed surface(s), do NOT proceed to release |
| `UNKNOWN` | `NO_CONTRACT` | **HALT** — contract missing; cannot verify integration |
| `UNKNOWN` | `INCONCLUSIVE` | **HALT** — ambiguous probe result; cannot verify integration |
| `UNKNOWN` | `PROBE_UNAVAILABLE` | CONTINUE with warning — tool not available |
| `UNKNOWN` | `NOT_APPLICABLE` | CONTINUE — surface not touched |
| `PASS` | — | CONTINUE |

**There is no soft-warning path for FAIL or contract UNKNOWN.** The pipeline stops.
`--require-gate` does NOT change this behaviour — it adds an opt-in Slack gate
*after* integration-sweep passes, before release begins.

---

## Circuit Breaker

3 consecutive step failures (across Steps A0–D5) → stop immediately + Slack notify.

**Halt authority vs circuit breaker:**
- **B5 (integration-sweep)** halts on FAIL or contract UNKNOWN — integration surfaces broken.
- **B6 (playwright-gate)** halts on smoke FAIL — UI is broken, cannot release. Data-flow
  failure is a soft gate (warn only).
- **A3 (start-environment)** halts on failure — cannot proceed with broken infrastructure.
- **B1-B4 (quality sweeps)** are advisory — failures are recorded individually but do not
  individually halt.
- **D1-D3 (post-release verification)** failures are logged as warnings but do NOT
  increment the circuit breaker — release and redeploy already completed successfully.
- **C1 (release) and C2 (redeploy)** halt individually on failure.

**Parallel failure counting:** B1-B4 run concurrently. For circuit-breaker purposes, the
entire parallel batch counts as **one evaluation window**, not four consecutive failures.
Individual sweep failures are recorded for metrics, but the breaker evaluates "did the
Phase B advisory batch fail" as a single event. This prevents one noisy parallel batch
from tripping the breaker in an absurd way.

**Advisory accumulation doctrine:** Advisory sweeps may contribute to the circuit breaker
only as evidence of broad workflow instability, not as substitutes for hard-gate authority.
Breaker behavior should not allow one noisy advisory class to dominate release control
unintentionally.

Failures are tracked per run. The circuit breaker does NOT persist across runs.

---

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | `build` | `build` \| `close-out` |
| `--autonomous` | `true` | No human gates in close-out sequence |
| `--require-gate` | `false` | Opt into Slack HIGH_RISK gate before release |

---

## Authorization Passthrough (OMN-6469)

When dispatching subagents for release or other high-risk operations:

1. **Pass `--autonomous` flag through**: If the parent skill was invoked with `--autonomous`, all child dispatches must include it:
   ```
   Task(
     subagent_type="onex:polymorphic-agent",
     prompt="Run /release --autonomous for omnibase_core"
   )
   ```

2. **Include run ID for audit trail**: Always pass `ONEX_RUN_ID` to establish the authorization chain:
   ```
   The parent autopilot run ID is {run_id}. This run was authorized with --autonomous.
   Proceed with release execution without additional human gates.
   ```

3. **Subagent verification**: Subagents receiving `--autonomous` with a valid run ID should proceed without requesting additional approval. The authorization was granted at the parent level.

---

## Merge Queue Non-Interference (OMN-6468)

**NEVER** dequeue a PR from the merge queue. If a PR is in the merge queue (`mergeStateStatus: QUEUED`):
1. Do NOT run `gh pr merge --disable-auto-merge`
2. Do NOT dequeue and re-enqueue — this doubles CI time
3. Simply wait for the merge queue to process the PR
4. If the merge queue run fails, the PR will be dequeued automatically by GitHub

**Rationale**: Dequeuing and re-enqueuing creates a second CI run. The concurrency group has `cancel-in-progress: false`, so both runs execute sequentially, wasting ~10 min per unnecessary dequeue.

---

## Integration Points

**Phase A — Prepare:**
- **worktree-health**: A0 — `scripts/prune-worktrees.sh --execute`: auto-clean merged worktrees, skip worktrees with unpushed commits or dirty state, skip detached HEAD and missing upstream [OMN-6867, OMN-7021]
- **merge-sweep**: A1 — drains open PRs before release (full skill: Track A/B/A-update/A-resolve)
- **dirty-pr-triage**: A1b — DIRTY/CONFLICTING PR detection, auto-close stale >24h, queue stall detection, missing auto-merge [OMN-6872]
- **deploy-local-plugin**: A2 — activates newly merged skills/hooks
- **start-environment**: A3 — audit-first infra startup with auto-fix

**Phase B — Quality Gate:**
- **dod-sweep**: B1 — DoD compliance audit with per-ticket verification (parallel) [OMN-6728]
- **aislop-sweep**: B2 — AI anti-pattern detection (parallel)
- **bus-audit**: B3 — Kafka topic health (parallel)
- **gap**: B4 — cross-repo integration health (parallel)
- **data-flow-sweep**: B4b — end-to-end Kafka->DB->UI pipeline verification (parallel, advisory)
- **database-sweep**: B4b — projection table health check (parallel, advisory)
- **runtime-sweep**: B4b — node registration and wiring verification (parallel, advisory)
- **integration-sweep**: B5 — hard gate; halt on FAIL or contract UNKNOWN
- **playwright-gate**: B6 — Playwright regression gate; consumes B5 PLAYWRIGHT_BEHAVIORAL result (reruns if stale >10 min or missing); smoke FAIL halts, data-flow FAIL warns
- **friction-triage**: B7 — recurring friction pattern remediation (non-halting)
- **duplication-sweep**: B8 — structural collision detection; halt on FAIL

**Phase C — Ship:**
- **release**: C1 — version bump; gated by integration-sweep
- **redeploy**: C2 — runtime refresh after release

**Phase D — Verify:**
- **verify-plugin**: D1 — plugin deployment verification (parallel)
- **container-health**: D2 — verify all runtime containers healthy after redeploy (parallel)
- **dashboard-sweep**: D3 — verify omnidash pages work (parallel)
- **close-day**: D4 — day audit artifact
- **insights-to-plan**: D5 — opportunistic insights-to-plan auto-trigger (non-halting)
- **ModelIntegrationRecord**: written by integration-sweep; read by autopilot to determine halt
