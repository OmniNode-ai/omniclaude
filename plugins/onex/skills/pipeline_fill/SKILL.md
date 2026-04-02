---
description: RSD-driven continuous pipeline fill — queries Linear for unstarted tickets, scores by acceleration, and dispatches to the appropriate execution path
mode: full
version: 1.0.0
level: advanced
debug: false
category: workflow
tags:
  - pipeline
  - rsd
  - automation
  - linear
  - delegation
  - continuous
author: OmniClaude Team
args:
  - name: --dry-run
    description: Score and rank tickets, print the dispatch plan, but do not execute
    required: false
  - name: --wave-cap
    description: "Maximum concurrent dispatches (default: 5)"
    required: false
  - name: --once
    description: Run a single fill cycle then exit (do not loop)
    required: false
  - name: --min-score
    description: "Minimum RSD acceleration score to dispatch (default: 0.1)"
    required: false
  - name: --skip-delegation
    description: Route all tickets to ticket-pipeline (never delegate to local LLM)
    required: false
---

# Pipeline Fill

## Dispatch Surface

**Target**: Interactive, Agent Teams, Headless, or CronCreate loop

```bash
# Interactive
/pipeline-fill

# One-shot
/pipeline-fill --once

# Dry run (score + rank, no dispatch)
/pipeline-fill --dry-run

# Scheduled via /loop
/loop 15m /pipeline-fill

# Scheduled via CronCreate
CronCreate("*/15 * * * *", "/pipeline-fill", recurring=true)

# Headless
claude -p "/pipeline-fill" \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep,Agent,mcp__linear-server__*"
```

**Announce at start:** "I'm using the pipeline-fill skill to select and dispatch the highest-acceleration ticket."

## Overview

Pipeline Fill continuously pulls the next highest-acceleration ticket from the backlog
and dispatches it to the appropriate execution path. It is the demand-side complement
to ticket-pipeline (which executes a single ticket end-to-end). Together they form a
closed loop: pipeline-fill selects WHAT to work on, ticket-pipeline handles HOW.

**Core loop:**

```
1. Query Linear → unstarted tickets in Active Sprint
2. Filter → exclude blocked, in-progress, or already-dispatched tickets
3. Score → RSD acceleration_value for each candidate
4. Rank → sort descending by acceleration_value
5. Select → pick top ticket (respecting wave cap)
6. Classify → delegatable to local LLM or requires Opus?
7. Dispatch → send to appropriate worker
8. Loop → wait for completion or next cycle interval
```

## Execution Rules

Execute end-to-end without stopping between cycles. If a cycle fails to find dispatchable
tickets, log the reason and wait for the next cycle interval. Only pause for:
(a) credentials not available, (b) Linear API completely unreachable after 3 retries,
(c) explicit user stop signal.

---

## Phase 1: Query Linear

Query for unstarted tickets in the Active Sprint using `mcp__linear-server__list_issues`.

**Filters:**
- State: `Backlog` or `Todo` (not `In Progress`, `In Review`, `Done`, `Canceled`)
- Cycle: Active Sprint (current cycle)
- Exclude: tickets with `blocked` label or unresolved blocking issues

```
mcp__linear-server__list_issues with filter:
  - state: { name: { in: ["Backlog", "Todo"] } }
  - cycle: { isActive: { eq: true } }
```

**Graceful degradation:** If Linear is unreachable, wait 60 seconds and retry up to
3 times. After 3 failures, log a friction event to `.onex_state/friction/` and exit
the current cycle (the next scheduled cycle will retry).

---

## Phase 2: Filter Candidates

Remove tickets that should not be dispatched:

1. **Already dispatched**: Check `.onex_state/pipeline-fill/dispatched.yaml` for ticket IDs
   that are currently in-flight (dispatched but not yet completed)
2. **Blocked**: Tickets with `blocked` label or where `blockedBy` relations exist with
   non-completed tickets
3. **Missing repo**: Tickets without a clear target repo (no `repo:` label or description match)
4. **No push access**: Exclude repos where the current agent identity cannot push — verify
   via `gh api repos/{owner}/{repo} --jq '.permissions.push'` before scheduling any workers.
   If the permission check errors, times out, returns null/undefined, or yields any non-true
   value, treat the repo as non-pushable, log the error and repo identifier, and skip dispatch
   for that repo (fail-closed).
5. **Wave cap**: If current in-flight count >= wave cap, skip this cycle entirely

**Dispatched state file** (`.onex_state/pipeline-fill/dispatched.yaml`):
```yaml
in_flight:
  - ticket_id: OMN-7300
    repo: OmniNode-ai/omniclaude
    dispatched_at: "2026-04-02T10:00:00Z"
    worker_type: ticket_pipeline
    status: running
  - ticket_id: OMN-7301
    repo: OmniNode-ai/omnibase_infra
    dispatched_at: "2026-04-02T10:05:00Z"
    worker_type: local_llm
    status: running
completed:
  - ticket_id: OMN-7299
    repo: OmniNode-ai/omniclaude
    dispatched_at: "2026-04-02T09:00:00Z"
    completed_at: "2026-04-02T09:45:00Z"
    worker_type: ticket_pipeline
    status: done
failed:
  - ticket_id: OMN-7298
    repo: OmniNode-ai/omniclaude
    dispatched_at: "2026-04-02T08:00:00Z"
    failed_at: "2026-04-02T08:01:00Z"
    worker_type: ticket_pipeline
    error: "Agent dispatch timed out"
```

On dispatch failure, the ticket must be moved out of `in_flight` immediately and into `failed`
(not left as `in_flight`). Failed entries do not count toward wave-cap enforcement.

---

## Phase 3: Score via RSD

For each candidate ticket, compute an RSD-style acceleration score. The scoring uses
five factors from the RSD score compute node (`omnibase_infra/src/omnibase_infra/nodes/node_rsd_score_compute/`):

### Scoring Algorithm

```
acceleration_value = (
    blocking_weight * blocking_score +
    priority_weight * priority_score +
    staleness_weight * staleness_score +
    repo_readiness_weight * repo_readiness_score +
    size_weight * size_score
)
```

**Factor weights** (default, tunable):

| Factor | Weight | Description |
|--------|--------|-------------|
| `blocking_score` | 0.30 | How many other tickets does this unblock? Normalized 0-1. A ticket that blocks 5 others scores 1.0; blocking 0 scores 0.0. |
| `priority_score` | 0.25 | Label-derived priority. Urgent=1.0, High=0.75, Medium=0.5, Low=0.25, None=0.1. |
| `staleness_score` | 0.20 | Days since ticket creation, normalized. Created >14 days ago = 1.0, <1 day = 0.1. Linear interpolation between. |
| `repo_readiness_score` | 0.15 | Inverse of open PR count for the target repo. 0 open PRs = 1.0, 5+ open PRs = 0.2. Repos with fewer open PRs are more ready for new work. |
| `size_score` | 0.10 | Estimated ticket size (from labels or estimate field). Smaller tickets score higher (faster acceleration). XS=1.0, S=0.8, M=0.5, L=0.3, XL=0.1. |

**Tiebreaker:** If two tickets have equal `acceleration_value`, prefer the one with higher
`priority_score`. If still tied, prefer the older ticket (higher `staleness_score`).

### Example Scoring

```
OMN-7300: blocks 3 tickets (0.6), High (0.75), 7 days old (0.5), repo has 1 PR (0.8), size S (0.8)
  = 0.30*0.6 + 0.25*0.75 + 0.20*0.5 + 0.15*0.8 + 0.10*0.8
  = 0.18 + 0.1875 + 0.10 + 0.12 + 0.08
  = 0.6675

OMN-7301: blocks 0 tickets (0.0), Medium (0.5), 2 days old (0.2), repo has 4 PRs (0.3), size M (0.5)
  = 0.30*0.0 + 0.25*0.5 + 0.20*0.2 + 0.15*0.3 + 0.10*0.5
  = 0.0 + 0.125 + 0.04 + 0.045 + 0.05
  = 0.26
```

Result: OMN-7300 dispatched first (0.6675 > 0.26).

---

## Phase 4: Classify Delegation

Determine whether the top-scoring ticket can be delegated to a local LLM or requires
Opus-level orchestration.

### Classification Heuristic

**Delegate to local LLM** when ALL of:
- Single repo target (one `repo:` label or clear description match)
- Estimated size XS or S (or labels suggest simple scope)
- Title/description matches known simple patterns:
  - "Add unit test for..."
  - "Fix typo in..."
  - "Update documentation..."
  - "Add type annotations..."
  - "Rename X to Y"
  - "Add model/enum for..."
  - "Fix linting..."
- No cross-repo dependencies
- No architecture/design decisions required

**Route to Opus (ticket-pipeline)** when ANY of:
- Multi-repo changes required
- Estimated size M, L, or XL
- Title/description suggests architectural work:
  - "Redesign...", "Refactor...", "Migrate..."
  - "Cross-repo...", "Multi-service..."
  - "Add new node type...", "New skill..."
- Blocking relationships suggest coordination needed
- Has `architecture` or `design` labels

**Default**: If classification is ambiguous, route to ticket-pipeline (safer).

---

## Phase 5: Dispatch

### Dispatch to ticket-pipeline (Opus)

Invoke `ticket-pipeline` via Agent Teams:

```
1. Create a task: "Run ticket-pipeline for {ticket_id}"
2. Spawn an Agent worker with the task
3. Record dispatch in dispatched.yaml
4. Continue to next cycle (do not wait for completion)
```

### Dispatch to local LLM

Build a delegation prompt using the delegation prompt builder
(`src/omniclaude/hooks/handlers/handler_delegation_prompt_builder.py`) and send it
to the delegation orchestrator:

```
1. Fetch ticket description from Linear
2. Identify target repo and relevant files
3. Build self-contained prompt via build_delegation_prompt()
4. Dispatch via NodeDelegationOrchestrator
5. Record dispatch in dispatched.yaml
6. Continue to next cycle
```

### Dispatch recording

After every dispatch, update `.onex_state/pipeline-fill/dispatched.yaml`:
- Add ticket to `in_flight` list
- Include `dispatched_at`, `worker_type`, `repo` (target GitHub repo), and initial `status: running`

---

## Phase 6: Completion Check

Before starting a new cycle, check for completed dispatches:

1. For ticket-pipeline dispatches: check if the ticket's PR has been merged in the recorded repo
   (`gh pr list --repo "{repo}" --state merged --search "{ticket_id}"`)
2. For local LLM dispatches: check if the delegation orchestrator reported completion
3. Move completed tickets from `in_flight` to `completed` in dispatched.yaml
4. Update the in-flight count for wave cap enforcement

---

## Wave Cap Enforcement

The wave cap (default: 5) limits how many tickets can be in-flight simultaneously.

- Before dispatch: count `in_flight` entries in dispatched.yaml
- If `len(in_flight) >= wave_cap`: skip this cycle, log "Wave cap reached ({n}/{cap})"
- After completion check: recalculate — if slots freed, proceed with dispatch

The wave cap prevents overloading the system with too many concurrent agents and
ensures each dispatch gets adequate resources.

---

## State Management

All state is written to `.onex_state/pipeline-fill/`:

| File | Purpose |
|------|---------|
| `dispatched.yaml` | In-flight, completed, and failed ticket tracking |
| `last-run.yaml` | Timestamp and result of last cycle |
| `scores.yaml` | Last scoring run (for debugging/auditing) |

### last-run.yaml

```yaml
timestamp: "2026-04-02T10:15:00Z"
candidates_found: 12
candidates_after_filter: 8
top_ticket: OMN-7300
top_score: 0.6675
action: dispatched_to_ticket_pipeline
wave_status: "3/5 in-flight"
```

---

## Dry Run Mode

When `--dry-run` is passed, execute Phases 1-4 (query, filter, score, classify) but
skip Phase 5 (dispatch). Output a formatted report:

```
Pipeline Fill — Dry Run
========================

Active Sprint Candidates: 12
After Filtering: 8
Wave Status: 3/5 in-flight (2 slots available)

Ranked Tickets:
  #1  OMN-7300  score=0.668  blocking=3  priority=High    repo=omniclaude     → ticket-pipeline
  #2  OMN-7305  score=0.542  blocking=1  priority=High    repo=omnibase_core  → local_llm
  #3  OMN-7301  score=0.260  blocking=0  priority=Medium  repo=omnidash       → ticket-pipeline
  ...

Would dispatch: OMN-7300 (ticket-pipeline), OMN-7305 (local_llm)
```

Also write this report to `.onex_state/pipeline-fill/scores.yaml` for external tools.

---

## Error Handling

| Failure | Behavior |
|---------|----------|
| Linear unreachable | Retry 3x with 60s backoff, then log friction event and skip cycle |
| No candidates found | Log "No unstarted tickets in Active Sprint", skip cycle |
| All candidates filtered | Log reason breakdown, skip cycle |
| All candidates below --min-score | Log "No tickets above minimum score threshold", skip cycle |
| Dispatch failure | Log friction event, move ticket out of `in_flight` into `failed` in dispatched.yaml (decrement wave-cap count), continue to next ticket |
| Wave cap reached | Log "Wave cap reached", skip cycle |
| GitHub API error (repo readiness check) | Use default repo_readiness_score of 0.5, continue scoring |

---

## Integration with /loop

The recommended scheduling pattern:

```bash
# Every 15 minutes, check for work and dispatch
/loop 15m /pipeline-fill

# Aggressive fill (every 5 minutes, useful during active sprints)
/loop 5m /pipeline-fill --wave-cap 8

# Conservative fill (every 30 minutes, lower concurrency)
/loop 30m /pipeline-fill --wave-cap 3
```

When invoked via `/loop`, each cycle runs `--once` implicitly (the loop handles repetition).

---

## Security and Safety

- **Never bypass pre-commit hooks** when dispatching to local LLMs
- **Never dispatch to repos the agent does not have push access to**
- **Wave cap is a hard limit** — cannot be overridden at runtime without `--wave-cap`
- **Dispatched state is append-only** — completed entries are never deleted, only archived
  (monthly rotation)
- **All dispatches are logged** to `.onex_state/pipeline-fill/` for audit trail
