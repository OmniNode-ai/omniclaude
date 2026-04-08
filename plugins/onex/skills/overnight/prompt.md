# overnight — Authoritative Behavior Specification

> **OMN-7810**: Bootstrap the entire overnight autonomous operation.
> **Authoritative**: When `SKILL.md` and `prompt.md` conflict, `prompt.md` wins.

---

## Invocation

```
/overnight [--max-cycles N] [--dry-run] [--skip-build-loop] [--skip-merge-sweep]
```

- `--max-cycles`: Maximum build loop cycles (default: unlimited)
- `--dry-run`: Print bootstrap plan without dispatching workers
- `--skip-build-loop`: Skip build loop startup
- `--skip-merge-sweep`: Skip merge-sweep cron

---

## Phase 0 — Context Load and Session Binding

### Generate session ID

```python
import uuid, datetime
SESSION_ID = f"overnight-{datetime.date.today().isoformat()}-{uuid.uuid4().hex[:8]}"
```

This session ID is the correlation key for all workers, crons, and artifacts.

### Announce

First output line must be:

```
[overnight] SESSION: {SESSION_ID} | bootstrapping night shift
```

### Read standing orders

Read the file at `$ONEX_STATE_DIR/nightly-loop-decisions.md`:

```bash
cat "$ONEX_STATE_DIR/nightly-loop-decisions.md"
```

If the file does not exist:
- Print WARNING: `Standing orders file not found at $ONEX_STATE_DIR/nightly-loop-decisions.md`
- Proceed with default priorities: build loop + merge sweep + monitoring
- Do NOT prompt the user — this is an overnight skill, it must be self-sufficient

Parse the standing orders to extract:
- `STANDING_PRIORITIES`: ordered list of focus areas
- `STANDING_RULES`: non-negotiable constraints
- `DELEGATION_ROUTING`: task-type to model routing table
- `ACTIVE_GAPS`: known issues (checked items are resolved, unchecked are active)

### Create artifact directory

```bash
mkdir -p "$ONEX_STATE_DIR/overnight/$SESSION_ID"
```

### Snapshot standing orders

Copy the standing orders to the session artifact directory for auditability:

```bash
cp "$ONEX_STATE_DIR/nightly-loop-decisions.md" "$ONEX_STATE_DIR/overnight/$SESSION_ID/standing-orders.md"
```

### Parse arguments

Parse `--max-cycles` (default: 0 = unlimited), `--dry-run` (default: false),
`--skip-build-loop` (default: false), `--skip-merge-sweep` (default: false).

---

## Phase 1 — Dry Run Check

If `--dry-run` is set, print the bootstrap plan and exit:

```
[overnight] DRY RUN — would bootstrap:
  Session ID:        {SESSION_ID}
  Team name:         overnight-ops-{SESSION_ID}
  Workers:
    - merge-sweep-worker (30min cron) {SKIP if --skip-merge-sweep}
    - monitoring-worker (15min cron)
    - build-loop-worker (continuous, max_cycles={MAX_CYCLES or "unlimited"}) {SKIP if --skip-build-loop}
  Crons:
    - priority-check (60min)
  Standing priorities: {count} items
  Active gaps: {unchecked_count} unresolved
```

Exit after printing. No workers dispatched, no team created.

---

## Phase 2 — Create Agent Team

Create the overnight operations team:

```
TeamCreate(team_name="overnight-ops-{SESSION_ID}")
```

If TeamCreate fails: **STOP immediately.** Report the exact error and wait for user direction.
Do NOT fall back to inline execution.

---

## Phase 3 — Dispatch Workers

Dispatch all workers in parallel. Each worker receives the full standing orders as context.

### Worker A: Merge Sweep (unless --skip-merge-sweep)

```
Agent(
  name="merge-sweep-worker",
  team_name="overnight-ops-{SESSION_ID}",
  prompt="""You are the merge-sweep worker for overnight session {SESSION_ID}.

Your job: keep PRs flowing. Run merge-sweep every 30 minutes.

## Standing Orders
{FULL_STANDING_ORDERS_CONTENT}

## Execution Loop

1. Run the merge-sweep skill:
   Skill(skill="onex:merge_sweep")

2. After each sweep completes, report results to the team lead:
   SendMessage(to="team-lead", content="[merge-sweep-worker] Sweep complete: {summary}")

3. Create a cron to re-run in 30 minutes:
   CronCreate(schedule="*/30 * * * *", command="Skill(skill='onex:merge_sweep')")

4. Between sweeps, monitor for merge queue issues:
   - Check if any PRs are stuck in merge queue > 30 minutes
   - Report stuck PRs to team-lead via SendMessage

## Rules
- Use --skip-polish on the first sweep to quickly enable auto-merge on ready PRs
- Use full sweep (with polish) on subsequent runs
- Always use --authors jonahgabriel to scope to our PRs
- Respect rate limits — merge-sweep has built-in exponential backoff
- If auth fails, report immediately to team-lead and stop
"""
)
```

### Worker B: Monitoring

```
Agent(
  name="monitoring-worker",
  team_name="overnight-ops-{SESSION_ID}",
  prompt="""You are the monitoring worker for overnight session {SESSION_ID}.

Your job: watch runtime health and report issues.

## Standing Orders
{FULL_STANDING_ORDERS_CONTENT}

## Monitoring Targets

Check every 15 minutes:

### Runtime Health (.201)
```bash
curl -s --connect-timeout 5 http://192.168.86.201:8085/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'8085: {d.get(\"status\",\"unknown\")}')" 2>/dev/null || echo "8085: DOWN" # onex-allow-internal-ip
curl -s --connect-timeout 5 http://192.168.86.201:8086/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'8086: {d.get(\"status\",\"unknown\")}')" 2>/dev/null || echo "8086: DOWN" # onex-allow-internal-ip
curl -s --connect-timeout 5 http://192.168.86.201:8087/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'8087: {d.get(\"status\",\"unknown\")}')" 2>/dev/null || echo "8087: DOWN" # onex-allow-internal-ip
```

### PR Status
```bash
gh pr list --repo OmniNode-ai/omnimarket --state open --json number,title,statusCheckRollup --limit 20
gh pr list --repo OmniNode-ai/omniclaude --state open --json number,title,statusCheckRollup --limit 20
gh pr list --repo OmniNode-ai/omnidash --state open --json number,title,statusCheckRollup --limit 20
gh pr list --repo OmniNode-ai/omnibase_core --state open --json number,title,statusCheckRollup --limit 20
gh pr list --repo OmniNode-ai/omnibase_infra --state open --json number,title,statusCheckRollup --limit 20
```

### Kafka/Redpanda Health
```bash
docker exec omnibase-infra-redpanda rpk cluster health 2>/dev/null || echo "Redpanda: UNREACHABLE"
```

### Dashboard Responsiveness
```bash
curl -s --connect-timeout 5 -o /dev/null -w "%{http_code}" http://localhost:3000/ 2>/dev/null || echo "Dashboard: DOWN"
```

## Reporting

After each check cycle, report to team-lead:

```
SendMessage(to="team-lead", content="[monitoring-worker] Health check:
  Runtime: 8085={status} 8086={status} 8087={status}
  Redpanda: {status}
  Dashboard: {status}
  Open PRs: {count} across {repo_count} repos
  Failing PRs: {failing_count}")
```

If any service is DOWN that was previously UP, escalate immediately:
```
SendMessage(to="team-lead", content="ALERT: {service} went DOWN. Previous status: UP. Investigating...")
```

## Cron Setup

Set up a 15-minute check cron:
```
CronCreate(schedule="*/15 * * * *", command="Run health check cycle")
```

## Rules
- Never attempt to restart services without reporting to team-lead first
- Log all health check results to $ONEX_STATE_DIR/overnight/{SESSION_ID}/monitoring/
- Track state transitions (UP->DOWN, DOWN->UP) for alerting
"""
)
```

### Worker C: Build Loop (unless --skip-build-loop)

```
Agent(
  name="build-loop-worker",
  team_name="overnight-ops-{SESSION_ID}",
  prompt="""You are the build loop worker for overnight session {SESSION_ID}.

Your job: run the autonomous build loop continuously, pulling tickets and creating PRs.

## Standing Orders
{FULL_STANDING_ORDERS_CONTENT}

## Execution

Start the build loop skill:
```
Skill(skill="onex:build_loop", args="--max-cycles {MAX_CYCLES_OR_EMPTY}")
```

The build loop executes the 6-phase cycle:
  IDLE -> CLOSING_OUT -> VERIFYING -> FILLING -> CLASSIFYING -> BUILDING -> COMPLETE

## Model Routing

Follow the delegation routing from standing orders:
- Test fixes, imports, formatting -> Local LLM (Qwen3-Coder)
- Classification, routing -> Local fast (Qwen3-14B)
- Code review, reasoning -> Local reasoning (DeepSeek)
- Architecture, multi-file changes -> Frontier (OpenAI/Google)

Environment variables for local inference should already be set:
- ENABLE_LOCAL_DELEGATION=true
- ENABLE_LOCAL_INFERENCE_PIPELINE=true

## Reporting

After each cycle, report to team-lead:
```
SendMessage(to="team-lead", content="[build-loop-worker] Cycle {N} complete:
  Phase: {final_phase}
  Tickets dispatched: {count}
  PRs created: {count}
  Failures: {count}")
```

If the circuit breaker trips (3 consecutive failures), report immediately:
```
SendMessage(to="team-lead", content="ALERT: Build loop circuit breaker tripped after 3 consecutive failures. Halting. Last error: {error}")
```

## Rules
- All code changes in worktrees — never commit to omni_home repos directly
- Pre-commit hooks always run — never bypass with --no-verify
- Evidence for everything — PR links, test results, DB queries
- If build loop hangs for > 30 minutes on one phase, report to team-lead
"""
)
```

---

## Phase 4 — Set Up Priority Check Cron

Create a cron job that re-reads standing orders every 60 minutes:

```
CronCreate(
  schedule="0 * * * *",
  command="Read $ONEX_STATE_DIR/nightly-loop-decisions.md and check for priority changes. If Active Gaps have changed or new standing priorities added, notify team-lead via SendMessage."
)
```

This ensures the overnight session adapts to updated standing orders without restart.

---

## Phase 5 — Write Bootstrap Artifact

Write the bootstrap metadata to `$ONEX_STATE_DIR/overnight/{SESSION_ID}/bootstrap.yaml`:

```yaml
session_id: "{SESSION_ID}"
started_at: "{ISO_TIMESTAMP}"
team_name: "overnight-ops-{SESSION_ID}"
workers_dispatched:
  - name: merge-sweep-worker
    status: dispatched  # or skipped
    cron_interval: "30m"
  - name: monitoring-worker
    status: dispatched
    cron_interval: "15m"
  - name: build-loop-worker
    status: dispatched  # or skipped
    max_cycles: {MAX_CYCLES or "unlimited"}
crons:
  - name: priority-check
    schedule: "0 * * * *"
    status: created
standing_orders_snapshot: "standing-orders.md"
active_gaps_count: {UNCHECKED_GAP_COUNT}
standing_priorities_count: {PRIORITY_COUNT}
```

---

## Phase 6 — Team Lead Monitoring Loop

After all workers are dispatched, the team lead enters monitoring mode:

1. **Collect worker reports** via SendMessage — workers report after each cycle
2. **Log status updates** to `$ONEX_STATE_DIR/overnight/{SESSION_ID}/status.log`
3. **Aggregate results** periodically:
   - Total merge-sweep runs and PRs processed
   - Total build loop cycles and PRs created
   - Health check history and any downtime events
4. **React to alerts**:
   - If a service goes DOWN, log it and check if it recovers on next monitoring cycle
   - If build loop circuit breaker trips, log it and check standing orders for guidance
   - If merge-sweep auth fails, log it and stop the merge-sweep cron

### Status Update Format

Every 60 minutes (aligned with priority check), output a status summary:

```
[overnight] STATUS @ {TIMESTAMP}
  Session: {SESSION_ID} | uptime: {HOURS}h{MINUTES}m
  Build loop: {cycles_completed} cycles | {prs_created} PRs created | {failures} failures
  Merge sweep: {sweeps_completed} sweeps | {prs_merged} PRs merged | {prs_polished} polished
  Runtime: 8085={status} 8086={status} 8087={status}
  Active gaps: {resolved}/{total} resolved this session
```

---

## Completion

The overnight session runs until:
- All build loop cycles complete (if `--max-cycles` was set)
- The user invokes `/begin-day` (morning handoff)
- The user sends a stop signal ("done", "stop", "enough")
- All workers report completion with no remaining work

On completion, write final summary to `$ONEX_STATE_DIR/overnight/{SESSION_ID}/summary.yaml`:

```yaml
session_id: "{SESSION_ID}"
started_at: "{START_TIMESTAMP}"
completed_at: "{END_TIMESTAMP}"
duration_hours: {HOURS}
build_loop:
  cycles_completed: {N}
  cycles_failed: {N}
  prs_created: {N}
  tickets_dispatched: {N}
merge_sweep:
  sweeps_completed: {N}
  prs_merged: {N}
  prs_polished: {N}
  prs_blocked: {N}
monitoring:
  health_checks: {N}
  downtime_events: {N}
  services_recovered: {N}
gaps_resolved: {N}
```

Report the summary to the user and clean up the team:

```
TeamDelete(team_name="overnight-ops-{SESSION_ID}")
```
