---
description: "Unified Session Orchestrator — single entry point replacing overnight/autopilot/begin_day/handoff/crash_recovery. Three-phase control loop: health gate → RSD scoring → dispatch. Supports interactive (daytime) and autonomous (overnight) modes. Interactive invocation executes prompt.md directly in Claude; omnimarket handler reachable only via CLI or Kafka (Wave 3: OMN-8367)."
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

## Tools Required (OMN-8708)

This skill spawns workers via `Agent()`. Workers run in fresh sessions where dispatch tools
are **deferred** (schema not pre-loaded). Any worker that needs to itself dispatch sub-agents
must fetch the schema at session start:

```
ToolSearch(query="select:Agent,SendMessage,TaskCreate,TaskUpdate,TaskGet", max_results=5)
```

Inject this call as the first step in every Phase 3 dispatch prompt that includes downstream
`Agent()` calls (e.g. `session` workers calling `merge_sweep` or `epic_team`).

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

Three-phase control loop with a mandatory escalation step between Steps 2 and 3.
Every phase is backed by `node_session_orchestrator` in `omnimarket/`.

```
Phase 1 (Step 2):   System Health Gate (8 dimensions)
    └─ ANY RED → fix-dispatch only, no new work
    └─ ALL GREEN or YELLOW → Step 2.5

Step 2.5:           Diagnosis-Flag Escalation  ← NOT skipped by --skip-health
    └─ scan docs/diagnosis-*.md + .onex_state/diagnosis-required.flag
    └─ any unresolved flag older than 24h blocks dispatch until the user
       types "acknowledged", "resolved <ticket>", or "skip"

Phase 2 (Step 3):   RSD Priority Scoring
    └─ interactive: present report, await user approval
    └─ autonomous: read standing orders, auto-proceed

Phase 3 (Step 4):   Dispatch
    └─ TeamCreate with correlation chain propagation
    └─ Graceful Kafka degradation to local execution
```

### Step 2.5 artifacts (diagnosis escalation)

The escalation step reads and writes the following paths (OMN-9123):

| Path | Purpose |
|---|---|
| `docs/diagnosis-*.md` | Diagnosis docs scanned for `Resolved:` marker + mtime |
| `.onex_state/diagnosis-required.flag` | Two-Strike flag with `ticket:` + `diagnosis_doc:` fields |
| `.onex_state/session/diagnosis_escalations.jsonl` | Append-only log of "acknowledged" responses |
| `.onex_state/friction/F<N>-diagnosis-bypass.yaml` | Friction entry when user types "skip" |

Step 2.5 is invoked unconditionally — the `--skip-health` flag only skips Phase 1
health probes; it does NOT bypass diagnosis-flag escalation, since stale flags
represent Two-Strike protocol violations that must be surfaced every session.

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
| Kafka + Runtime healthy | Full event-driven (pub/sub topics on `onex.cmd.omnimarket.session.v1`) |
| Kafka down, Runtime up | Direct CLI invocation (`uv run onex node node_session_orchestrator`) |
| Kafka down, Runtime down | Direct handler invocation (imports `HandlerSessionOrchestrator` in-process) |
| Everything down | Interactive-only: the session skill executes `prompt.md` directly in-process |

The deprecated `onex run <node>` form MUST NOT be used. The supported non-interactive routes are the Kafka topic above or the `uv run onex node node_session_orchestrator` CLI invocation, in keeping with the Routing Contract below.

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

## Execution Path

**Interactive invocation (`/onex:session`):** Claude loads `prompt.md` from this skill directory
and executes it directly in the Claude session context. No Kafka event is published, no omnimarket
handler is called. Claude IS the orchestrator — it follows the 6-step `prompt.md` spec.

**Omnimarket handler (`HandlerSessionOrchestrator`):** Fully implemented (1403 LOC, all three phases)
in `omnimarket/src/omnimarket/nodes/node_session_orchestrator/`. Reachable only via:
- `uv run onex node node_session_orchestrator` CLI
- Kafka topic `onex.cmd.omnimarket.session.v1`

The interactive skill path is **not wired** to the omnimarket handler. Wiring this connection
is Wave 3 work tracked in OMN-8367.

---

## Known Blockers (as of 2026-04-21)

### Step 2.5: Diagnosis-flag halt

Step 2.5 (OMN-9123) is **unconditional** — it runs even with `--skip-health`. If
`.onex_state/diagnosis-required.flag` exists and is older than 24h, every session invocation
blocks until the user types `acknowledged`, `resolved <ticket>`, or `skip`.

**To unblock:** Add a `Resolved:` line to the referenced diagnosis doc
(`docs/diagnosis-<slug>.md`) so Step 2.5b auto-clears the flag — or type `acknowledged`
at the prompt when it appears. Do NOT delete the flag file directly; Step 2.5 will recreate it
on the next unfixed incident.

### Dimension 6 (Deploy Agent) RED — OMN-9393

Phase 1 Dimension 6 (`blocks_dispatch: true`) has been RED since 2026-04-16 due to OMN-9393.
With Dimension 6 RED, Phase 1 always emits a FIX_ONLY gate decision, preventing Phase 2/3
dispatch in normal mode.

**Operational workaround until OMN-9393 is resolved:**

```
/onex:session --mode autonomous --skip-health
```

`--skip-health` bypasses Phase 1 probes (Dimension 6 RED is not evaluated). Step 2.5
still runs — acknowledge any stale flags first (see above).

---

## Implementation Status

**omnimarket handler:** Complete. `HandlerSessionOrchestrator` implements all three phases
(Phase 1: 8 health dimension probes via SSH + subprocess; Phase 2: Linear GraphQL RSD scoring
+ standing orders; Phase 3: `claude -p /onex:ticket_pipeline` subprocess dispatch). Confirmed
running standalone with `result=completed` in the 2026-04-18 skill functional audit.

**Interactive wiring:** Not yet connected. The skill executes `prompt.md` directly in Claude.
Connecting the interactive path through `HandlerSessionOrchestrator` is Wave 3 (OMN-8367).

**Skill files (OMN-8340):** Created. `prompt.md` is a 349-line 6-step spec that Claude
executes directly. It is the functional implementation for interactive use.

## Routing Contract

- **Classification**: Deterministic
- **Interactive path**: Claude is the orchestrator — executes `prompt.md` directly in session context. No Kafka event, no omnimarket handler. Prose is the correct output format for interactive mode.
- **Non-interactive path**: Dispatches to `node_session_orchestrator` (omnimarket) via Kafka topic `onex.cmd.omnimarket.session.v1` or `uv run onex node node_session_orchestrator` CLI.

On non-interactive routing failure, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose.
