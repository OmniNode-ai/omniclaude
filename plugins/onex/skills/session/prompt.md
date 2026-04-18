<!-- persona: plugins/onex/skills/_lib/assistant-profile/persona.md -->
<!-- persona-scope: this-skill-only -- do not re-apply if polymorphic agent wraps this skill -->
Apply the persona profile above when generating outputs.

# Session Orchestrator Skill

You are executing the unified session orchestrator skill. This prompt defines the complete
three-phase control loop for session management.

---

## Step 0: Announce <!-- ai-slop-ok: skill-step-heading -->

Say: "I'm using the session orchestrator skill."

---

## Step 1: Parse Arguments <!-- ai-slop-ok: skill-step-heading -->

Parse from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| `--mode <mode>` | `interactive` | `interactive` or `autonomous` |
| `--dry-run` | `false` | Print plan without dispatching |
| `--skip-health` | `false` | Skip Phase 1 health gate (emergency only) |
| `--standing-orders <path>` | `.onex_state/session/standing_orders.json` | Override standing orders path |

---

## Step 2: Generate Session ID <!-- ai-slop-ok: skill-step-heading -->

Generate a session ID in the format `sess-{YYYYMMDD}-{HHMM}` (e.g., `sess-20260412-0300`).

Write to `.onex_state/session/current_session_id`.

If `.onex_state/session/in_flight.yaml` exists and `resumable: true`, read it and announce:
"Found resumable session from {last_checkpoint}. Running mandatory Phase 1 health gate before resuming."
Then proceed to Step 3 (Phase 1 health gate). Do NOT skip Phase 1 — the environment may have
degraded since the session was interrupted. Only after Phase 1 returns PROCEED or FIX_ONLY
should execution continue from `{current_phase}`. If Phase 1 returns HALT, stop and report
the blocking health dimensions before resuming any dispatch work.

---

## Step 2.5: Diagnosis-Flag Escalation <!-- ai-slop-ok: skill-step-heading -->

**This step is NOT skipped by `--skip-health`.** Stale diagnosis flags are escalation-class
issues that must surface at every session start regardless of gate mode.

### Step 2.5a: Scan diagnosis docs

Run:
```bash
find docs/ -name "diagnosis-*.md" -type f 2>/dev/null
```

For each file found, check its last-modified time:
```bash
stat -f "%m %N" docs/diagnosis-*.md   # macOS
# or: stat --format="%Y %n" docs/diagnosis-*.md   # Linux
```

If `(now - mtime) > 86400` seconds (24 hours):
1. Read the file and scan for a `Resolved:` marker anywhere in the content.
2. If no `Resolved:` marker is present, add this file to the **stale escalation list**.

### Step 2.5b: Check `.onex_state/diagnosis-required.flag`

If `.onex_state/diagnosis-required.flag` exists:
1. Read its contents (fields: `ticket`, `attempt_count`, `diagnosis_doc`).
2. Check mtime of the flag file. If `(now - mtime) > 86400` seconds:
   - Add to the stale escalation list.
3. Verify whether the referenced `diagnosis_doc` contains a `Resolved:` marker.
   If it does, the flag is stale-resolved — delete the flag file and skip escalation for it.

### Step 2.5c: Emit escalation

If the stale escalation list is non-empty:

**Announce (non-silent — this MUST be shown to the user):**

```
ESCALATION: Unresolved diagnosis flags older than 24h detected.

{for each stale entry:}
  - {filename} (ticket: {ticket}, age: {age_hours}h)
    Doc: {diagnosis_doc path}

These flags indicate Two-Strike Protocol violations that were never reviewed.
Session start is blocked until you acknowledge:
  → Type "acknowledged" to proceed (diagnosis docs remain open)
  → Type "resolved <ticket>" to mark a specific entry as resolved
  → Type "skip" to bypass this check (logged as friction)
```

Wait for user response before proceeding to Step 3.

- **"acknowledged"**: Log acknowledgement to `.onex_state/session/diagnosis_escalations.jsonl`
  and continue to Step 3.
- **"resolved \<ticket\>"**: Append `Resolved: {timestamp} — marked resolved at session start`
  to the relevant `docs/diagnosis-{slug}.md`. Delete `.onex_state/diagnosis-required.flag`
  if its `ticket` field matches. Continue to Step 3.
- **"skip"**: Log friction event to `.onex_state/friction/` with category
  `diagnosis_escalation_bypassed`. Continue to Step 3.

If the stale escalation list is empty, proceed silently to Step 3.

---

## Step 3: Phase 1 — System Health Gate <!-- ai-slop-ok: skill-step-heading -->

Skip if `--skip-health` is set (warn: "Skipping health gate — emergency mode").

### Step 3a: Read cross-session context

Before running live probes:
1. Read `.onex_state/session/last_health.yaml` if it exists — note any regressions
2. Invoke the `recall` skill (sub-skill invocation, not Bash) with query "recent health issues infrastructure runtime" — incorporate findings into Phase 1 context

### Step 3b: Run 8 health dimensions

Run these checks. Mark each GREEN / YELLOW / RED:

1. **PR Inventory**: `gh pr list --json number,title,statusCheckRollup --limit 50` across all repos.
   RED if any PR has failing CI with no activity in >6h. YELLOW if >3 PRs pending review >24h.

2. **Golden Chain**: Run `/onex:golden_chain_sweep --dry-run`.
   RED if any chain failure. GREEN otherwise.

3. **Linear Sync**: Check if recently completed PRs have merged tickets in Linear.
   RED if >0 merged PRs with tickets still In Progress. YELLOW if >2 stale In Review tickets.

4. **Runtime Health**: Check containers on .201 via SSH or `ssh 192.168.86.201 docker ps`. # onex-allow-internal-ip
   Verify ports 8000/8001/8100 responding. RED if critical container (runtime, deploy-agent) down.
   YELLOW if non-critical container down.

5. **Plugin Currency**: Run `claude plugin list` and check omniclaude version.
   YELLOW if version is behind latest tag. GREEN otherwise.

6. **Deploy Agent**: Check `systemd deploy-agent.service` status on .201.
   RED if service inactive. YELLOW if service active but not producing Kafka heartbeats.

7. **Observability**: Check Kafka consumer lag on .201.
   YELLOW if no events emitted from any consumer in >10 minutes.
   GREEN if Phoenix (`http://192.168.86.201:4000`) responds. # onex-allow-internal-ip

8. **Repo Sync**: Run `bash omnibase_infra/scripts/pull-all.sh --dry-run` or equivalent check.
   YELLOW if any canonical repo is behind origin/main.

### Step 3c: Evaluate gate decision

```
overall_status = RED    if ANY dimension is RED
               = YELLOW if ANY dimension is YELLOW (no RED)
               = GREEN  if ALL dimensions GREEN

gate_decision = HALT     if overall_status = RED AND no fix-dispatch possible
              = FIX_ONLY if overall_status = RED (dispatch only fix work)
              = PROCEED  if overall_status = GREEN or YELLOW (with blocks_dispatch: false)
```

Blocking YELLOW dimensions (blocks_dispatch: true): Golden Chain (#2), Deploy Agent (#6),
Runtime Health (#4 if critical container).

### Step 3d: Write health artifact

Write `ModelSessionHealthReport` to `.onex_state/session/last_health.yaml`:
```yaml
session_id: sess-{id}
produced_at: {timestamp}
overall_status: GREEN|YELLOW|RED
gate_decision: PROCEED|FIX_ONLY|HALT
dimensions:
  - dimension: pr_inventory
    status: GREEN
    blocks_dispatch: false
    actionable_items: []
  # ... repeat for all 8 dimensions
```

### Step 3e: Act on gate decision

**If HALT**: Report blocking dimensions. Stop. Write `resumable: false` to in_flight.yaml.

**If FIX_ONLY**: Announce "Health gate RED. Dispatching fix work only."
Proceed to Phase 3 with dispatch queue limited to fix-dispatch targets:
`systematic_debugging`, `runtime_sweep`, `linear_triage`, `platform_readiness`.
Skip Phase 2 RSD scoring.

**If PROCEED**: Continue to Phase 2.

---

## Step 4: Phase 2 — RSD Priority Scoring <!-- ai-slop-ok: skill-step-heading -->

### Step 4a: Query work items

1. Run `/onex:linear_triage --output-only` or `tracker.list_issues` to get
   active tickets (Todo, In Progress) ordered by priority.
2. Run `gh pr list --json number,title,headRefName,mergeable,statusCheckRollup --limit 100`
   across all repos for PR merge ordering.

### Step 4b: Apply standing orders

Read `.onex_state/session/standing_orders.json`. For each order:
- Apply `priority_override` to the matching ticket/PR
- Skip expired orders (`expires_at` < now)
- Prune expired orders from the file (lazy expiry)

### Step 4c: Score tickets

For each ticket, compute:
```
score = (acceleration_value / max(risk_score, 0.1))
      * (1 / (1 + dependency_count))
      * log(1 + staleness_days)
      + standing_order_boost * 0.3
```

Approximate `acceleration_value` from Linear priority (Urgent=4, High=3, Medium=2, Low=1).
Approximate `risk_score` from label (breaking-change=3, infra=2, default=1).
`dependency_count` = count of blocking tickets not yet Done.
`staleness_days` = days since last state change.

### Step 4d: Score PRs for merge ordering

For each PR with passing CI:
```
merge_score = (unblocked_downstream / max(diff_lines/1000, 0.1))
            * review_confidence
            * (1 / (1 + unresolved_threads))
            * ci_pass_rate
```

Where `review_confidence` = 1.0 if approved, 0.7 if changes-requested-then-resolved,
0.5 if no review. `unresolved_threads` from CodeRabbit/GitHub review data.

### Step 4e: Produce dispatch queue

Output ordered list: merge-ready PRs first (highest merge_score), then tickets (highest ticket_score).
Respect DAG hard constraints — do not dispatch a ticket if any of its blocking tickets are not Done.

### Step 4f: Mode branch

**Interactive mode**:
1. Present health report summary and dispatch queue to user.
2. Say: "Phase 1 complete. Health: {overall_status}. Proposed dispatch queue ({N} items):
   {top 5 items with scores}. Approve to proceed, or reorder/veto items."
3. Wait for user response. Accept reordering or veto of items before continuing to Phase 3.

**Autonomous mode**:
1. Log dispatch queue to `.onex_state/session/in_flight.yaml`.
2. Proceed silently to Phase 3.

---

## Step 5: Phase 3 — Dispatch <!-- ai-slop-ok: skill-step-heading -->

### Step 5a: Write in-flight state

Write to `.onex_state/session/in_flight.yaml`:
```yaml
session_id: sess-{id}
current_phase: DISPATCH
dispatch_queue: [ticket-ids/pr-numbers in order]
in_progress: []
completed: []
waiting_for: {}
last_checkpoint: {timestamp}
resumable: true
```

### Step 5b: Dispatch work

For each item in dispatch queue (up to the concurrency limit, default 5 parallel):

**For PRs** (merge-ready): Invoke `/onex:merge_sweep` with the PR list.

**For tickets** (build work): Use `TeamCreate` to dispatch `/onex:ticket_pipeline` per ticket.
Inject the correlation prefix into each agent's environment:
```
ONEX_SESSION_ID=sess-{id}
ONEX_DISPATCH_ID=disp-{sequence}
ONEX_CORRELATION_PREFIX=sess-{id}.disp-{sequence}
```

**Skill-first enforcement**: Every background agent must use skills for any action that has one.
Do not run raw `gh`, `git`, `ssh`, or `curl` when a skill covers the operation. If no skill
exists for a needed action, the agent must file a ticket via `/onex:create_ticket` first.

### Step 5c: Monitor and update state

After dispatching all items, update `.onex_state/session/in_flight.yaml` with current status.

In **autonomous mode**: poll for completion periodically. Update `in_progress` and
`completed` lists. When all items complete, write `current_phase: COMPLETE`.

In **interactive mode**: report dispatch summary. User can query status with `/onex:system_status`.

### Step 5d: Session ledger

After Phase 3 completes (or on timeout), append to `.onex_state/session/ledger.jsonl`:
```json
{"session_id": "sess-{id}", "start_time": "...", "end_time": "...",
 "health_snapshot": "GREEN|YELLOW|RED", "dispatch_count": N,
 "gate_decision": "PROCEED|FIX_ONLY|HALT", "mode": "interactive|autonomous"}
```

---

## Step 6: Completion <!-- ai-slop-ok: skill-step-heading -->

Write `current_phase: COMPLETE` and `resumable: false` to in_flight.yaml.

Report summary:
- Session ID
- Health status (Phase 1 result)
- Items dispatched (Phase 3 count)
- Mode used

In autonomous mode, emit Kafka event `onex.evt.session.complete.v1` if Kafka is available.

---

## Halt Conditions

Stop and report immediately if:

1. Phase 1 overall_status is RED and no fix-dispatch targets apply.
2. Phase 3 circuit breaker trips: 3 consecutive dispatch failures.
3. `.onex_state/session/standing_orders.json` contains a `HALT` priority override matching
   the current session scope.
4. A dispatched agent reports a critical failure that invalidates the dispatch queue
   (e.g., Golden Chain goes RED mid-session).

On halt: write reason to in_flight.yaml, append to ledger.jsonl, report to user.
