---
description: Autonomous close-out orchestrator — runs integration-sweep as a hard gate, then executes merge-sweep, release, redeploy, and close-day in sequence. Halts immediately on any integration-sweep FAIL or UNKNOWN/contract failure.
version: 1.0.0
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
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-5438
**Epic**: OMN-5431

---

## Purpose

Top-level autonomous close-out orchestrator.

In `--mode close-out`, autopilot executes the full end-of-day pipeline:
1. merge-sweep (drain open PRs)
2. integration-sweep (hard gate — FAIL or contract UNKNOWN halts the run)
3. release (version bump + publish)
4. redeploy (runtime refresh)
5. close-day (audit artifact)

The integration-sweep guard at Step 2 is a **hard halt**: any FAIL result or any UNKNOWN
result with reason `NO_CONTRACT` or `INCONCLUSIVE` stops the entire pipeline. Autopilot
does NOT continue with warnings when the contract guard fails.

In `--mode build` (default), autopilot queries Linear for unblocked Todo tickets and
dispatches `/ticket-pipeline` for each. Full build-mode spec is in OMN-5120.

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

3 consecutive step failures (across Steps 1–5) → stop immediately + Slack notify.

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

- **integration-sweep**: invoked at Step 2 as the pre-release guard
- **merge-sweep**: Step 1 — drains open PRs before release
- **release**: Step 3 — version bump; gated by integration-sweep
- **redeploy**: Step 4 — runtime refresh after release
- **close-day**: Step 5 — day audit artifact; runs its own integration-sweep internally
- **ModelIntegrationRecord**: written by integration-sweep; read by autopilot to determine halt
