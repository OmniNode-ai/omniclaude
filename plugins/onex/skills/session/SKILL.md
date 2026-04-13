---
description: Unified Session Orchestrator — single entry point replacing overnight/autopilot/begin_day/handoff/crash_recovery. Three-phase control loop: health gate → RSD scoring → dispatch. Supports interactive (daytime) and autonomous (overnight) modes. Backed by node_session_orchestrator in omnimarket.
version: 1.0.0
mode: full
level: advanced
debug: false
category: workflow
tags:
  - session
  - orchestrator
  - health-gate
  - rsd
  - dispatch
  - autonomous
  - interactive
  - overnight
  - unified
author: OmniClaude Team
composable: false
args:
  - name: --mode
    description: "Execution mode: interactive | autonomous (default: interactive)"
    required: false
  - name: --dry-run
    description: "Print session plan without dispatching workers (default: false)"
    required: false
  - name: --skip-health
    description: "Skip Phase 1 health gate — use only in emergencies (default: false)"
    required: false
  - name: --standing-orders
    description: "Path to standing_orders.json override (default: .onex_state/session/standing_orders.json)"
    required: false
inputs:
  - name: mode
    description: "interactive | autonomous"
  - name: dry_run
    description: "Print plan without executing"
outputs:
  - name: status
    description: "complete | halted | error"
  - name: halt_reason
    description: "Phase and reason that caused halt, or empty string on complete"
  - name: session_id
    description: "sess-{date}-{time} identifier for correlation chain propagation"
---

# /onex:session — Unified Session Orchestrator

**Skill ID**: `onex:session`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-8340
**Design doc**: `docs/plans/2026-04-10-unified-session-orchestrator-design.md`

---

## Supersedes

This skill replaces 5 legacy skills. They are kept for backward compatibility but deprecated:

| Deprecated Skill | Absorbed Into |
|-----------------|---------------|
| `/onex:overnight` | Autonomous mode of `/onex:session` |
| `/onex:autopilot` | Phase 3 dispatch targets (release/redeploy become dispatch items) |
| `/onex:begin_day` | Phase 1 health check + Phase 2 RSD priority (interactive mode) |
| `/onex:handoff` | Session state persistence — writes `last_health.yaml` + standing orders |
| `/onex:crash_recovery` | Phase 1 dimension 8: reads `.onex_state/` pipeline state as health input |

---

## Architecture

Three-phase control loop. Every phase is backed by `node_session_orchestrator` in `omnimarket/`.

```
Phase 1: System Health Gate (8 dimensions)
    └─ ANY RED → fix-dispatch only, no new work
    └─ ALL GREEN or YELLOW → Phase 2

Phase 2: RSD Priority Scoring
    └─ interactive: present report, await user approval
    └─ autonomous: read standing orders, auto-proceed

Phase 3: Dispatch
    └─ TeamCreate with correlation chain propagation
    └─ Graceful Kafka degradation to local execution
```

### Health Gate Dimensions (Phase 1)

| # | Dimension | RED condition | Blocks dispatch? |
|---|-----------|---------------|-----------------|
| 1 | PR Inventory | Any PR blocked on RED CI with no owner | No |
| 2 | Golden Chain | Any chain failure | **Yes** |
| 3 | Linear Sync | Mismatch count > 0 | No |
| 4 | Runtime Health | Container down or port unreachable on .201 | **Yes (if critical)** |
| 5 | Plugin Currency | Version behind or skill count mismatch | No |
| 6 | Deploy Agent | Service inactive or not subscribed | **Yes** |
| 7 | Observability | No events from any consumer in >10 min | No |
| 8 | Repo Sync | Any canonical repo behind origin/main | No |

RED always blocks. YELLOW blocks only where `blocks_dispatch: true`.

### Phase 1 also checks in-flight session state

Before running live probes, Phase 1 reads:
- `.onex_state/session/in_flight.yaml` — resume interrupted sessions
- `.onex_state/session/last_health.yaml` — detect regressions (was GREEN, now RED = new failure)
- `/onex:recall` — cross-agent memory for recent discoveries

### RSD Scoring (Phase 2)

Two scoring contexts sharing the same input signals:

**Ticket dispatch:**
```
ticket_score = (acceleration_value / max(risk_score, 0.1))
             * (1 / (1 + dependency_count))
             * log(1 + staleness_days)
             + standing_order_boost * BOOST_WEIGHT
```

**PR merge ordering:**
```
merge_score = (unblocked_downstream_count / max(diff_size_normalized, 0.1))
            * review_confidence
            * (1 / (1 + unresolved_thread_count))
            * ci_pass_rate
            + standing_order_boost * BOOST_WEIGHT
```

DAG constraints are hard — RSD provides soft priority within the same dependency tier only.

### Dispatch Targets (Phase 3)

The following skills are dispatch targets — they remain standalone and are called from Phase 3:

`merge_sweep`, `dogfood`, `dod_verify`, `linear_triage`, `linear_housekeeping`,
`systematic_debugging`, `ticket_pipeline`, `epic_team`, `release`, `redeploy`,
`platform_readiness`, `system_status`, `hostile_reviewer`, `pr_review_bot`,
`golden_chain_sweep`, `data_flow_sweep`, `runtime_sweep`, `database_sweep`,
`aislop_sweep`, `gap`, `dashboard_sweep`

---

## Session State Files

| File | Purpose |
|------|---------|
| `.onex_state/session/current_session_id` | Active session ID (`sess-{date}-{time}`) |
| `.onex_state/session/in_flight.yaml` | Execution state for resume/recovery (written by orchestrator) |
| `.onex_state/session/last_health.yaml` | Health snapshot from previous session (written by orchestrator) |
| `.onex_state/session/ledger.jsonl` | One JSON line per completed session (written by orchestrator) |
| `.onex_state/session/standing_orders.json` | Persistent operator priority overrides (read by Phase 2, written by operator or agent) |

---

## Correlation Chain

Every event carries a four-segment chain: `{session_id}.{dispatch_id}.{ticket_id}.{pr_id}`

The session orchestrator generates `session_id` at Phase 1 start and injects it into every
Phase 3 TeamCreate dispatch. Background agents extend the chain with their own segments.

---

## Mode Comparison

| | Interactive | Autonomous |
|---|---|---|
| Entry | User invokes `/onex:session` | Cron or Kafka trigger |
| After Phase 1 | Presents health report, waits for approval | Reads standing orders, auto-proceeds |
| After Phase 2 | Shows priority queue, user can reorder/veto | Dispatches immediately |
| Phase 3 | Foreground silent unless user asks for status | Silent, writes to session artifact |
| Error handling | Surfaces RED interactively | Writes to artifact, retries once then escalates via Kafka |

---

## Graceful Degradation

| Infrastructure State | Dispatch Mode |
|---------------------|---------------|
| Kafka + Runtime healthy | Full event-driven (pub/sub topics) |
| Kafka down, Runtime up | RuntimeLocal in-memory bus (`onex run <node>`) |
| Kafka down, Runtime down | Direct handler invocation |
| Everything down | Skill-level fallback (raw skill execution) |

---

## Skill-First Enforcement

All background agents dispatched by Phase 3 must use platform skills exclusively.
If a deterministic skill exists for an action, the agent must invoke it — not raw CLI.
Agents that need an action with no existing skill must file a ticket via `/onex:create_ticket`
before executing the raw action.

---

## Usage

```
/onex:session
/onex:session --mode autonomous
/onex:session --dry-run
/onex:session --mode interactive --skip-health
```

---

## Implementation Status

**Phase 2 (in progress)**: Skill files created (OMN-8340). Backing node
`node_session_orchestrator` implementation tracked in the 2026-04-11 implementation plan
(`docs/plans/2026-04-11-unified-session-orchestrator-plan.md`).

Key dependencies before full functionality:
- `ModelSessionHealthContract` in `omnibase_compat/` (Wave 1: OMN-8368)
- `node_session_orchestrator` in `omnimarket/` (Wave 3: OMN-8367)
- Standing orders store + session artifact writer (Wave 4: OMN-8371)
