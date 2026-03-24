---
description: Autonomous close-out orchestrator — 4-phase pipeline with infra health gate, quality sweeps (dod-sweep, aislop-sweep, bus-audit, gap detect), integration-sweep hard gate, release, redeploy, and post-release verification (verify-plugin, dashboard-sweep, container health). Compounds — each cycle's merged infrastructure makes the next cycle's gate stricter.
version: 2.0.0
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
**Version**: 2.0.0
**Owner**: omniclaude
**Ticket**: OMN-5438
**Epic**: OMN-5431

---

## Purpose

Top-level autonomous close-out orchestrator.

In `--mode close-out`, autopilot executes the full pipeline in 4 phases:

**Phase A — Prepare (sequential):**
- A1: merge-sweep — drain open PRs
- A2: deploy-local-plugin — activate newly merged skills/hooks for this session
- A3: start-environment — audit-first infra startup: verify core infra (postgres, redpanda, valkey) running, migration-gate healthy (proves DB migrations current), all runtime containers healthy. Auto-fixes by running infra-up + infra-up-runtime if containers missing.

**Phase B — Quality Gate (B1-B4 parallel, B5 sequential hard gate):**
- B1: dod-sweep — audit recently closed tickets for DoD compliance
- B2: aislop-sweep — AI anti-patterns in recent merges
- B3: bus-audit — Kafka topic health / schema drift
- B4: gap detect --no-fix — cross-repo integration health
- B5: integration-sweep — **HARD GATE** (unchanged halt policy)

B1-B4 are read-only audits, safe to parallelize. Failures in B1-B4 are logged and increment
the circuit breaker but do NOT halt the pipeline. Only B5 (integration-sweep) has halt authority.

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

**Note:** This is a 14-step pipeline (A1-A3, B1-B5, C1-C2, D1-D4). Internal step IDs use the
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

3 consecutive step failures (across Steps 1–13) → stop immediately + Slack notify.

**Halt authority vs circuit breaker:**
- **B5 (integration-sweep)** is the only step with individual halt authority — a single
  FAIL or contract UNKNOWN halts the pipeline immediately regardless of circuit breaker state.
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

## Integration Points

**Phase A — Prepare:**
- **merge-sweep**: A1 — drains open PRs before release
- **deploy-local-plugin**: A2 — activates newly merged skills/hooks
- **start-environment**: A3 — audit-first infra startup with auto-fix

**Phase B — Quality Gate:**
- **dod-sweep**: B1 — DoD compliance audit (parallel)
- **aislop-sweep**: B2 — AI anti-pattern detection (parallel)
- **bus-audit**: B3 — Kafka topic health (parallel)
- **gap**: B4 — cross-repo integration health (parallel)
- **integration-sweep**: B5 — hard gate; halt on FAIL or contract UNKNOWN

**Phase C — Ship:**
- **release**: C1 — version bump; gated by integration-sweep
- **redeploy**: C2 — runtime refresh after release

**Phase D — Verify:**
- **verify-plugin**: D1 — plugin deployment verification (parallel)
- **container-health**: D2 — verify all runtime containers healthy after redeploy (parallel)
- **dashboard-sweep**: D3 — verify omnidash pages work (parallel)
- **close-day**: D4 — day audit artifact
- **ModelIntegrationRecord**: written by integration-sweep; read by autopilot to determine halt
