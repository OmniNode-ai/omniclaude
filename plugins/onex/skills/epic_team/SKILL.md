---
description: Orchestrate a Claude Code agent team to autonomously work a Linear epic across multiple repos
mode: full
version: 2.1.0
level: advanced
debug: false
category: workflow
tags: [epic, team, multi-repo, autonomous, linear, slack]
args:
  - epic_id (required): Linear epic ID (e.g., OMN-2000)
  - --mode (required): Workflow mode — must be "build". Epic-team is exclusively a BUILD-mode skill. Omitting --mode emits a usage error.
  - --dry-run: Print decomposition plan (includes unmatched reason), no spawning
  - --force: Pause if active tasks remain; archive state and restart
  - --force-kill: Combine with --force to destroy active run even with live workers
  - --resume: Re-enter monitoring; finalize if all tasks terminal; no-op if already done
  - --force-unmatched: Route unmatched tickets to omniplan as TRIAGE tasks
---

# Epic Team Orchestration

## Mode Declaration

**This skill operates in BUILD mode only.**

Valid `--mode` values: `build`

**If `--mode` is omitted or set to any value other than `build`**, emit the following usage
error and stop — do NOT proceed to dispatch:

```
ERROR: /epic-team requires --mode build

Usage: /epic-team <epic_id> --mode build [options]

Valid modes:
  build    Orchestrate autonomous implementation of a Linear epic across repos

This skill is BUILD mode only. For close-out or reporting tasks:
  Close-out: /merge-sweep --mode close-out
  Reporting: /linear-insights --mode deep-dive
```

**First output line** when mode is valid must be:
```
[epic-team] MODE: build | epic: <epic_id>
```

No tool calls, file reads, or bash commands may precede this output.

## Headless Mode (Overnight Pipelines)

Use `plugins/onex/skills/epic_team/run.sh` for overnight/unattended runs:

```bash
# Full headless run
plugins/onex/skills/epic_team/run.sh OMN-2000 --mode build

# Dry run (no spawning)
plugins/onex/skills/epic_team/run.sh OMN-2000 --mode build --dry-run

# Resume after context limit or crash
plugins/onex/skills/epic_team/run.sh OMN-2000 --mode build --resume
```

**Minimum tool allowlist for headless epic-team:**
```
mcp__linear-server__get_issue, mcp__linear-server__list_issues,
mcp__linear-server__save_issue, mcp__linear-server__save_comment,
mcp__linear-server__list_projects, mcp__linear-server__get_project,
mcp__linear-server__list_teams, Bash, Read, Write, Edit, Glob, Grep,
TeamCreate, TeamDelete, Agent, TaskCreate, TaskUpdate, TaskGet, TaskList, SendMessage
```

**Failure doctrine in headless mode:**
- **Missing epic_id**: exit 1, structured JSON error — no partial run ever started
- **Missing credentials** (`LINEAR_API_KEY`): exit 2 immediately, no retries
- **Ambiguity** (cannot determine epic state, conflicting lock files): write
  `$ONEX_STATE_DIR/epics/<id>/ambiguity_<ts>.json`, exit 3 — never guess
- **Blocked tool** (not in allowlist): log denial, exit 4 — never silently substitute
- **Context limit**: checkpoint to `$ONEX_STATE_DIR/epics/<id>/state.yaml` before stopping;
  re-run with `--resume` to continue from last completed wave

**Checkpointable state:**
All in-progress state is written to `$ONEX_STATE_DIR/epics/<epic_id>/state.yaml` before
each wave and updated after each ticket completion. A coordinator killed at any point can be
resumed by re-running with `--resume` against the same `state.yaml`.

## Dispatch Surface: Agent Teams

epic-team uses Claude Code Agent Teams for all worker dispatch. The team lead (this session)
creates a named team, generates task contracts, dispatches workers, monitors for stalls, and
shuts down the team on completion.

### Lifecycle

```
1. TeamCreate(team_name="epic-{epic_id}")
2. For each ticket in wave:
   a. Generate a ModelTaskContract from the ticket's Linear DoD and inject into the worker prompt
   b. TaskCreate(subject="{ticket_id}: {title}", description=ticket_requirements)
   c. Agent(name="worker-{ticket_id}", team_name="epic-{epic_id}",
            prompt="Execute ticket-pipeline for {ticket_id}. Task contract: {contract_json}")
3. Workers execute in background, report progress via SendMessage(to="team-lead")
4. Team lead monitors progress, handles stalls (OMN-6937 pattern: 5-min inactivity timeout)
5. On each worker completion: verification chain runs (see below)
6. TeamDelete(team_name="epic-{epic_id}") after all tasks complete or are terminal
```

### Task Contract Generation

Before dispatching each worker, the team lead generates a task contract:

1. Fetch ticket DoD from Linear (description, acceptance criteria)
2. Build `ModelTaskContract` with mechanical checks (test pass, lint clean, type-check clean)
3. Inject the serialized contract into the worker's dispatch prompt
4. The contract travels with the worker — it is the single source of truth for what "done" means

### Verification Chain (Part 2 Reference)

Each worker task must produce evidence through the full Part 2 verification chain:

1. **Task contract** — `ModelTaskContract` persisted before dispatch
2. **Self-check** — worker runs `SelfCheckResult` against its own contract checks
3. **Verifier** — independent verifier agent validates self-check evidence
4. **Quorum gate** — `ModelQuorumResult` evaluates self-check + verifier verdicts
5. **Completion event** — `ModelTaskCompletedEvent` emitted with evidence to unified event stream

A worker is not considered complete until all five artifacts are present. Missing evidence
triggers a re-verification pass before the task is marked done.

### Stall Detection (OMN-6937 Pattern)

After dispatching workers in a wave, the team lead monitors for stalls:

- **Inactivity timeout**: 5 minutes with no tool calls from a worker → stall detected
- **On stall**: Log friction event to `.onex_state/friction/`, cancel stalled worker, mark task
  for retry in next wave
- **Retry policy**: Each ticket gets 1 retry. If stalled twice → mark `blocked`, add Linear
  comment, skip
- **Wave timeout**: 30 minutes total per wave. Remaining in-progress tasks are timed out and
  retried once

### Failure on Dispatch

If Agent Teams dispatch fails (TeamCreate error, Agent tool unavailable, auth error):
**STOP immediately.** Report the exact error to the user and wait for direction. Do NOT fall
back to direct Bash, Read, Edit, Write, or Glob calls — falling back bypasses observability,
context management, and the orchestration layer.

> **Session lifetime**: The monitoring phase is alive only while this session runs. Use `/epic-team {epic_id} --resume` to re-enter after a disconnection.

> **Architecture note (v3.0.0)**: epic-team is a thin orchestrator. All business logic lives in
> independently-invocable composable sub-skills. epic-team's job is coordination, state, and routing
> — not implementation. Workers are Agent Teams members, not poly-agent subagents.

## Overview

Decompose a Linear epic into per-repo workstreams and autonomously drive them to completion.
The team lead (this session) owns planning, dispatch, state persistence, and lifecycle
notifications. Tickets are executed by dispatching workers via Agent Teams (`TeamCreate` +
`Agent(team_name=...)`) in dependency-respecting waves.

**If the epic has zero child tickets**, epic-team invokes `decompose-epic` to create sub-tickets,
then posts a Slack LOW_RISK gate. Silence for 30 minutes = proceed.

## Execution Rules

Execute end-to-end without stopping between tasks. If blocked on one task, record a skip note
and continue to the next. Only pause for: (a) credentials not available in the session,
(b) a destructive action not explicitly covered by the plan, or (c) an explicit user gate in
the plan. Do not exit plan mode or stop to "await direction" in any other circumstance.

---

## Wave Cap

Dispatch tickets in waves of **5 tickets maximum** to prevent usage-limit interruptions.
Start the next wave only after all Agent() workers in the current wave have reported back.
Never dispatch more than 5 tickets in a single wave, even if more are independent.

---

## Sequential PR Chaining (OMN-6458)

When creating PRs for sequential tasks that modify the same files:
1. PR N+1 should target PR N's branch (not main) if they share modified files
2. Maximum chain depth: 3 PRs
3. If chain would exceed 3, wait for earlier PRs to merge before creating more

**Detection**: Before creating a PR, check if another open PR from the same epic modifies any of the same files:
```bash
# Get files in current change
CHANGED_FILES=$(git diff --name-only main...)

# Check open PRs from same epic for overlapping files
for PR_NUM in $(gh pr list --label "epic:OMN-XXXX" --json number -q '.[].number'); do
  PR_FILES=$(gh pr view $PR_NUM --json files -q '.files[].path')
  OVERLAP=$(comm -12 <(echo "$CHANGED_FILES" | sort) <(echo "$PR_FILES" | sort))
  if [[ -n "$OVERLAP" ]]; then
    echo "Overlapping files with PR #$PR_NUM: $OVERLAP"
    echo "Target PR #$PR_NUM's branch instead of main"
  fi
done
```

---

## Composable Sub-Skills

epic-team orchestrates these independently-invocable primitives:

| Sub-Skill | Purpose | Ticket |
|-----------|---------|--------|
| `decompose-epic` | Analyze epic → create Linear child tickets | OMN-2522 |
| `slack-gate` | LOW_RISK / MEDIUM_RISK / HIGH_RISK human gates | OMN-2521 |
| `ticket-pipeline` | Per-ticket pipeline (implement → review → PR → CI → merge) | — |

`ticket-pipeline` in turn composes:

| Sub-Skill | Purpose | Ticket |
|-----------|---------|--------|
| `ticket-work` | Implement ticket (autonomous mode) | OMN-2526 |
| `local-review` | Review + fix loop | — |
| `ci-watch` | Poll CI, auto-fix failures | OMN-2523 |
| `pr-watch` | Poll PR reviews, auto-fix comments | OMN-2524 |
| `auto-merge` | Merge PR with HIGH_RISK Slack gate | OMN-2525 |

Each layer is independently invocable:
- `ticket-pipeline` runs standalone without `epic-team`
- `ticket-work` runs standalone without `ticket-pipeline`
- `ci-watch` runs standalone on any PR

**If the epic has zero child tickets**, epic-team automatically invokes the `decompose-epic` sub-skill to analyze the epic description and create sub-tickets, then posts a Slack LOW_RISK gate. Silence for 30 minutes means proceed with newly created tickets.

## Usage Examples

```bash
# Dry run — see decomposition without spawning agents
/epic-team OMN-2000 --dry-run

# Full run
/epic-team OMN-2000

# Resume after session disconnect
/epic-team OMN-2000 --resume

# Force restart (archive existing state; pauses if workers active)
/epic-team OMN-2000 --force

# Force restart even with active workers (dangerous)
/epic-team OMN-2000 --force --force-kill

# Route unmatched tickets to omniplan triage
/epic-team OMN-2000 --force-unmatched
```

## Orchestration Flow

```
epic-team OMN-XXXX
  → Fetch child tickets from Linear
  → If 0 child tickets:
      → Dispatch decompose-epic (composable, returns skill_result)
      → Read $ONEX_STATE_DIR/skill-results/{context_id}/decompose-epic.json
      → Dispatch slack-gate (LOW_RISK, 30 min, silence=proceed)
      → Read $ONEX_STATE_DIR/skill-results/{context_id}/slack-gate.json
      → If rejected: stop
      → Re-fetch newly created tickets
  → Assign tickets to repos via repo_manifest
  → Build dependency waves:
      Wave 0: independent tickets + cross-repo Part 1 splits (run in parallel)
      Wave 1: cross-repo Part 2 splits (run after Wave 0 completes)
  → For each wave: dispatch ticket-pipeline per ticket as Agent() workers in parallel
  → Start stall-detection watchdog for the wave [OMN-6987]
  → Await all Agent() workers in wave to report via SendMessage before starting next wave
  → If watchdog detects stall: cancel stalled worker, log to state, retry in next wave
  → Collect results (status, pr_url, branch) from SendMessage reports
  → Post-wave integration check (OMN-3345): run gap cycle --no-fix per repo touched
      → GREEN/YELLOW/RED per repo → post to Slack epic thread
      → Write integration_check section to state.yaml (non-blocking — always advances)
  → DoD compliance gate (OMN-5833): invoke /dod-sweep {epic_id} (targeted mode)
      → If FAIL: do NOT mark epic Done; follow-ups auto-created; post Slack block
      → If PASS: proceed to mark epic Done; post Slack clean notification
      → If UNKNOWN (all exempt): proceed (rollout accommodation); post review warning
  → Send Slack lifecycle notifications (started, ticket done, epic done)
  → Persist state to $ONEX_STATE_DIR/epics/{epic_id}/state.yaml
```

## Dispatch: decompose-epic

When epic has 0 child tickets:

```
Agent(
  name="decompose-{epic_id}",
  team_name="epic-{epic_id}",
  prompt="The epic {epic_id} has no child tickets.

    Invoke: Skill(skill=\"onex:decompose_epic\", args=\"{epic_id}\")

    Read result from $ONEX_STATE_DIR/skill-results/{context_id}/decompose-epic.json
    Report back via SendMessage: created_tickets (list of IDs and titles), count."
)
```

## Pre-Dispatch Verification Preamble [OMN-6990]

**Before dispatching any ticket in a wave**, the team lead performs a lightweight verification
pass to catch misaligned tickets early -- before they consume a full pipeline run.

### Verification Steps (per ticket, before Agent() dispatch)

1. **Ticket readiness check**: Fetch ticket via `mcp__linear-server__get_issue` and verify:
   - Description is non-empty and contains actionable content
   - Repo target is identifiable (from title, description, or labels)
   - No blocking dependencies are in non-Done state

2. **Approach sanity check**: For each ticket, state in the dispatch prompt:
   - What the ticket requires (1-sentence summary)
   - Which repo and approximate files will be modified
   - Any known constraints or patterns to follow

3. **Skip unready tickets**: If a ticket fails verification:
   - Mark as `skipped` in `state.yaml` with reason: `"verification_failed: {detail}"`
   - Add a Linear comment: "Skipped by epic-team: {reason}"
   - Do NOT dispatch -- move to next ticket in wave
   - Unready tickets are re-evaluated in the next wave (dependency may have resolved)

### Verification in the Dispatch Prompt

The verification context is injected directly into each Agent() dispatch prompt so the
ticket-pipeline agent starts with pre-validated understanding rather than re-deriving it.

## Dispatch: Ticket-Pipeline per Ticket (Agent Teams Pattern)

For each ticket in a wave, generate a task contract and dispatch a worker via Agent Teams:

```
# 1. Generate task contract from Linear DoD
contract = generate_task_contract(ticket_id, ticket_description, ticket_acceptance_criteria)
# Persist contract to $ONEX_STATE_DIR/epics/{epic_id}/contracts/{ticket_id}.json

# 2. Create a task for tracking
TaskCreate(subject="{ticket_id}: {title}", description=ticket_requirements)

# 3. Dispatch worker as Agent Teams member
Agent(
  name="worker-{ticket_id}",
  team_name="epic-{epic_id}",
  prompt="You are executing ticket {ticket_id} for epic {epic_id}.

    Ticket: {ticket_id} - {title}
    URL: {url}
    Repo: {repo} at {repo_path}
    Epic: {epic_id}  Run: {run_id}

    TASK CONTRACT (source of truth for done):
    {contract_json}

    VERIFIED CONTEXT (from epic-team pre-dispatch check):
    - Summary: {verified_summary}
    - Target files: {verified_file_targets}
    - Pattern to follow: {verified_pattern_reference}
    - Dependencies met: {dependency_status}

    VERIFICATION CHAIN — you must produce ALL of these before reporting done:
    1. Run self-check against the task contract (SelfCheckResult)
    2. Evidence is verified by an independent verifier agent
    3. Quorum gate evaluates self-check + verifier verdicts (ModelQuorumResult)
    4. Emit ModelTaskCompletedEvent with all evidence

    Invoke: Skill(skill=\"onex:ticket_pipeline\", args=\"{ticket_id}\")

    After ticket-pipeline completes, report back via SendMessage(to=\"team-lead\"):
    - ticket_id: {ticket_id}
    - status: (merged/failed/blocked)
    - pr_url: (if available)
    - branch: (branch name used)
    - verification_verdict: (PASS/FAIL/INCOMPLETE)"
)
```

**Wave parallelism**: Agent Teams workers run as independent concurrent Claude sessions.
Dispatch all Agent() calls for a wave before monitoring. Do NOT dispatch tickets sequentially
within a wave.

**Wave serialization**: Wave N+1 starts only after all workers from Wave N have reported back
via SendMessage or been timed out by stall detection.

## Stall Detection in Wave Dispatch [OMN-6987]

After dispatching all Agent() calls in a wave, the team lead monitors for stalled agents
using the `dispatch_watchdog` skill. This prevents a single stalled agent from blocking
the entire wave indefinitely.

### Monitoring Loop

```
# After dispatching wave N tasks:
wave_start_time = now()
stall_timeout = 300  # 5 minutes with no tool calls

while any_task_still_running(wave_tasks):
    # Check each running task
    for task in wave_tasks:
        if task.status == "in_progress":
            elapsed_since_last_activity = now() - task.last_tool_call_time

            if elapsed_since_last_activity > stall_timeout:
                # Stall detected
                log("[epic-team] STALL: {task.ticket_id} idle for {elapsed}s")
                write_stall_event(epic_id, task.ticket_id, elapsed)

                # Recovery: mark as failed, retry in next wave
                task.status = "stalled"
                task.retry_in_next_wave = true

    # Check wave-level timeout (30 minutes total)
    if now() - wave_start_time > 1800:
        log("[epic-team] WAVE TIMEOUT: cancelling remaining tasks")
        for task in wave_tasks:
            if task.status == "in_progress":
                task.status = "timeout"
                task.retry_in_next_wave = true
        break

    sleep(60)  # Check every minute
```

### Stall State in state.yaml

```yaml
waves:
  - wave_id: 0
    dispatched_at: "2026-03-29T10:00:00Z"
    completed_at: "2026-03-29T10:15:00Z"
    tasks:
      - ticket_id: OMN-2001
        status: merged
        pr_url: "https://github.com/..."
      - ticket_id: OMN-2002
        status: stalled
        stall_detected_at: "2026-03-29T10:08:00Z"
        idle_seconds: 480
        retry_wave: 1
```

### Retry Policy

- Stalled tasks are retried **once** in the next wave
- If a task stalls twice: mark as `blocked`, add Linear comment, skip
- Timeout tasks (wave-level) are always retried once
- Maximum retry count per ticket: 1 (prevents infinite retry loops)

### Integration with dispatch_watchdog Skill

The monitoring logic above is the inline version for the team-lead session.
For more sophisticated monitoring (e.g., headless overnight runs), invoke
the `dispatch_watchdog` skill as a composable sub-skill:

```
Skill(skill="onex:dispatch_watchdog", args="--epic-id {epic_id} --timeout 300 --action report")
```

## Skill Result Communication

All sub-skills write their output to `$ONEX_STATE_DIR/skill-results/{context_id}/`:

| Sub-Skill | Output File | Key Fields |
|-----------|------------|------------|
| `decompose-epic` | `decompose-epic.json` | status, created_tickets, count |
| `slack-gate` | `slack-gate.json` | status (accepted/rejected/timeout) |
| `ticket-pipeline` | `ticket-pipeline.json` | status, ticket_id, pr_url |
| `ticket-work` | `ticket-work.json` | status, pr_url, phase_reached |
| `local-review` | `local-review.json` | status, iterations_run |
| `ci-watch` | `ci-watch.json` | status, fix_cycles_used |
| `pr-watch` | `pr-watch.json` | status, fix_cycles_used |
| `auto-merge` | `auto-merge.json` | status, merge_commit |

## Skill Result Input Contract

**Input contract:** All sub-skill result files conform to `ModelSkillResult` from `omnibase_core.models.skill`.

> **Note: This contract reference is behavioral guidance for the LLM executing this skill. Runtime validation not yet implemented.**

Load result files and check outcomes as follows:

```python
result = ModelSkillResult.from_json(path.read_text())

# Check if the sub-skill completed successfully (success, partial, or dry_run)
if result.is_success_like:
    # Proceed with next wave or action
    pass

# Check for hard failure
elif result.status == EnumSkillResultStatus.FAILED:
    # Record failure, apply circuit breaker (max 2 retries per ticket)
    pass

# Check for blocking states
elif result.status == EnumSkillResultStatus.GATED:
    # Human approval is pending — do not advance wave
    pass

# Access skill-specific fields via extra dict (not direct attribute access).
# Use .get() with a default — extra may be empty on non-success paths.
created_tickets = result.extra.get("created_tickets", [])   # decompose-epic result
iterations_run = result.extra.get("iterations_run", 0)      # local-review result
```

**Behaviorally significant `extra_status` values by sub-skill:**

| Sub-Skill | `extra_status` | Orchestrator action |
|-----------|---------------|---------------------|
| `decompose-epic` | `null` | Normal — read `extra.get("created_tickets", [])` |
| `slack-gate` | `"accepted"` | Silence-proceed gate passed — continue |
| `slack-gate` | `"rejected"` | Gate rejected — stop (cancel orchestration) |
| `slack-gate` | `"timeout"` | Gate timed out — apply configured timeout policy |
| `ticket-pipeline` | `"merged"` | Ticket fully merged — record as done |
| `ticket-pipeline` | `"held"` | Merge gate open — non-terminal, do not retry yet |
| `auto-merge` | `"merged"` | PR merged — record wave ticket as complete |
| `auto-merge` | `"timeout"` | Merge gate expired — retryable with new pipeline run |

**Promotion rule for `extra` fields:** If any orchestrator consumer (epic-team, ticket-pipeline) branches on `extra["x"]`, that field MUST be promoted to a first-class field in `ModelSkillResult`. `extra` is a migration bridge, not a permanent schema extension mechanism.

## State Persistence

Runtime state is persisted to `$ONEX_STATE_DIR/epics/{epic_id}/state.yaml`:

```yaml
epic_id: OMN-XXXX
run_id: f084b6c3
status: monitoring  # queued | monitoring | done | failed
checkpoint:
  schema_version: 1
  last_completed_wave: 0
  waves:
    - wave_id: 0
      tickets: [OMN-2001, OMN-2002]
      status: completed  # pending | in_progress | completed | failed
      completed_at: "2026-03-06T..."
    - wave_id: 1
      tickets: [OMN-2003]
      status: pending
  open_prs:
    OMN-2001: {pr_number: 45, repo: "omniclaude", branch: "jonah/omn-2001-..."}
  failures:
    OMN-2003: {class: "ci_failure_ruff", attempts: 1, last_error: "..."}
  last_update_utc: "2026-03-06T..."
workers:
  - repo: omniclaude
    tickets: [OMN-2001, OMN-2002]
    status: running  # running | done | failed
ticket_status:
  OMN-2001: merged
  OMN-2002: running
```

Use `--resume` to re-enter monitoring from persisted state after session disconnect.

## Empty Epic Auto-Decompose

When epic has 0 child tickets:

```
[LOW_RISK] epic-team: Auto-decomposed OMN-XXXX

Epic had no child tickets. Created N sub-tickets:
  - OMN-YYYY: [title]
  - OMN-ZZZZ: [title]
  ...

Reply "reject" within 30 minutes to cancel. Silence = proceed with orchestration.
```

### --dry-run behavior for empty epic

Invoke `decompose-epic --dry-run` (returns plan, no tickets created). Print plan. Do not post
Slack gate.

## Repo Manifest

Ticket-to-repo assignment uses `plugins/onex/skills/epic-team/repo_manifest.yaml`:

```yaml
MIN_TOP_SCORE: 4

repos:
  - name: omniclaude
    path: ~/Code/omniclaude
    keywords: [hooks, skills, agents, claude, plugin, ticket-pipeline]
  - name: omnibase_core
    path: ~/Code/omnibase_core
    keywords: [nodes, contracts, runtime, onex]
  - name: omnibase_infra
    path: ~/Code/omnibase_infra
    keywords: [kubernetes, deploy, infra, helm]
```

Keyword matching is case-insensitive. Tickets with no keyword match are UNMATCHED.
Use `--force-unmatched` to route them to omniplan as TRIAGE tasks.

## Stacked Branch Execution (OMN-6270)

When Wave N+1 tickets depend on Wave N (via cross-repo Part 2 splits or file-overlap
chains), the downstream ticket branches from the Wave N branch tip instead of `main`.
This avoids merge conflicts and ensures later tickets see earlier changes without
waiting for merge.

**How it works:**

1. After Wave N completes, collect `{ticket_id: branch_name}` from worker results
2. When dispatching Wave N+1, check if any ticket has a dependency on a Wave N ticket
   (via `chain_targets` from `detect_file_overlap_chains` or cross-repo Part 2 mapping)
3. If a dependency exists and the upstream ticket succeeded, pass `--base-branch <branch>`
   to the downstream ticket's `ticket-pipeline` invocation
4. `ticket-pipeline` creates its worktree from the specified base branch and opens its
   PR targeting that base branch

**Fallback:** If the upstream ticket failed or returned no branch, fall back to `main`.

**Chain depth limit:** Maximum 3 levels of stacking. Beyond that, tickets target `main`
independently to avoid deep rebase chains.

**State tracking:** The `ticket_results` dict in state.yaml records `branch` per ticket,
making stacked branch resolution available across waves and on `--resume`.

---

## Worktree Policy

Workers create isolated git worktrees at:
```
$ONEX_STATE_DIR/worktrees/{epic_id}/{run_id}/{ticket_id}/
```

Stale worktrees are cleaned up automatically after merge when `auto_cleanup_merged_worktrees: true`
(default).

## Architecture

epic-team is a thin composition layer. It owns:
- Epic decomposition (via `decompose-epic`)
- Ticket-to-repo assignment (via repo_manifest)
- Wave construction (group tickets by dependency into parallel waves)
- Agent Teams dispatch of ticket-pipeline per ticket (TeamCreate + Agent with team_name)
- State persistence (`$ONEX_STATE_DIR/epics/{epic_id}/state.yaml`)
- Slack lifecycle notifications (started, ticket done, epic done)

It does NOT own:
- Ticket implementation (delegated to `ticket-pipeline` → `ticket-work`)
- Code review (delegated to `local-review`)
- CI polling (delegated to `ci-watch`)
- PR review polling (delegated to `pr-watch`)
- Merge execution (delegated to `auto-merge`)

### Execution Model

**Agent Teams dispatch from team-lead session** is the authoritative execution pattern:

1. Team-lead creates the team via `TeamCreate(team_name="epic-{epic_id}")`
2. Team-lead constructs waves of tickets grouped by dependency
3. For each wave, team-lead dispatches `Agent()` workers in parallel with `team_name` parameter
4. Workers execute in background and report completion via `SendMessage(to="team-lead")`
5. Team-lead monitors SendMessage reports and stall detection before starting the next wave
6. After all waves complete, team-lead cleans up via `TeamDelete()`

### Circuit Breaker / Heartbeat Timeout

Every Agent() dispatch has a configurable timeout to prevent stalled agents from blocking the
entire wave indefinitely. If an agent produces no output for `DISPATCH_TIMEOUT_MINUTES`
(default: 30, configurable via `EPIC_TEAM_DISPATCH_TIMEOUT_MINUTES` env var), the circuit
breaker trips:

1. The Agent() dispatch returns a timeout error
2. The ticket is marked `AGENT_TIMEOUT` in state.yaml
3. A Kafka event `onex.evt.omniclaude.agent-circuit-breaker.v1` is emitted for observability
4. The wave continues with remaining tickets (timeout is non-blocking)

This prevents the first autopilot close-out failure mode where a release dispatch stalled
for 1+ hour with zero output.

### Agent Health-Check Integration (OMN-6889)

The `agent_healthcheck` skill provides more sophisticated stall detection beyond the simple
timeout circuit breaker. During wave monitoring, epic-team checks agent health using three
heuristics:

1. **Inactivity**: No tool calls for 10 minutes (configurable)
2. **Context overflow**: Context window usage > 80% (preemptive recovery before hard limit)
3. **Rate limits**: Agent encounters rate-limit errors

On stall detection, the health-check module:
- Snapshots progress to a checkpoint file (using the checkpoint protocol from OMN-6887)
- Summarizes completed vs remaining work
- Relaunches a fresh agent with the summary and remaining tasks only

See `@skills/agent_healthcheck/SKILL.md` for the full detection and recovery protocol.

## Failure Taxonomy and Recovery Strategies

| Failure Class | Symptoms | Recovery Strategy |
|---|---|---|
| `rate_limit` | Sub-agent exits with rate limit error | Wait 60s, retry the ticket via `ticket-pipeline` sequentially |
| `context_limit` | Sub-agent hits max context length mid-ticket | Spawn fresh sub-agent; previous work is in the branch |
| `ci_failure_uv` | CI fails with lock file or uv version error | Verify CI uv version; regenerate lock with matching version |
| `ci_failure_ruff` | CI fails with lint/format error | Run `uv run ruff check --fix` + `uv run ruff format`, recommit |
| `stale_branch` | PR fails to merge — "main has moved" | `git rebase origin/main`, re-push, re-enable auto-merge |
| `wrong_repo` | Ticket worked in wrong repo | Look up target repo in Linear ticket `repo` field; re-dispatch |
| `blocker_unresolved` | Ticket blocked by another in-progress ticket | Move to end of queue; complete blocking ticket first |
| `pr_template_blocked` | Mergeability gate rejected — missing PR body sections | Update PR body with required sections (Summary/Risk/Test Evidence/Rollback), rerun gate |
| `agent_timeout` | Sub-agent produces no output for >30 min | Circuit breaker trips; ticket marked AGENT_TIMEOUT; retry in next run |
| `unknown` | Failure doesn't match above patterns | Escalate to user: ticket ID, last command output, branch state |

## Failure Attempt Definition

A failure attempt is counted when `ticket-pipeline` returns non-zero exit OR the summary contains an explicit failure class. Partial completions (branch exists, some steps done) count as one attempt.

## Self-Healing Rules

- Attempt retry up to 2 times *within the same run only*. On interruption + re-run, counts reset.
- After 2 failed attempts: produce failure report and stop dispatching new tickets.
- Escalation = log the failure report and continue with remaining unblocked tickets.

## DoD Compliance Gate

After all ticket-pipeline waves complete and before marking the epic as Done:

1. Invoke `/dod-sweep {epic_id}` (targeted mode)
2. If `overall_status == FAIL`:
   - Do NOT mark the epic Done
   - Follow-up tickets are auto-created by dod_sweep
   - Post Slack notification: "Epic {epic_id} blocked by DoD gaps: {failed} failed, {exempted} exempted, {passed} passed"
   - Leave epic in current state for manual resolution
3. If `overall_status == PASS`:
   - Proceed to mark epic Done
   - Post Slack notification: "Epic {epic_id} DoD gate cleared: {passed} passed, {exempted} exempted, {failed} failed"
4. If `overall_status == UNKNOWN` (e.g., all tickets exempted):
   - Post Slack notification: "Epic {epic_id} DoD gate: no evidence-backed passes -- {exempted} exempted, review recommended"
   - Proceed to mark epic Done (non-blocking) but flag for review
   - NOTE: Allowing all-exempted epics to proceed under UNKNOWN is a rollout
     accommodation, not the intended long-term steady state. This allow-through
     must sunset after the cutoff exemption review trigger fires (4 weeks or
     warning volume <10%, whichever first).

Notifications must always include passed/failed/exempted counts separately --
never imply all tickets passed when exemptions are present.

## See Also

- `prompt.md` — full orchestration logic, state machine, and error handling reference
- `ticket-pipeline` skill — per-ticket pipeline invoked by workers
- `ticket-work` skill — implementation phase (autonomous mode)
- `local-review` skill — review + fix loop
- `ci-watch` skill (OMN-2523) — CI polling and auto-fix
- `pr-watch` skill (OMN-2524) — PR review polling and auto-fix
- `auto-merge` skill (OMN-2525) — merge gate
- `decompose-epic` skill (OMN-2522) — empty epic auto-decompose
- `slack-gate` skill (OMN-2521) — LOW/MEDIUM/HIGH_RISK gates
- `plugins/onex/skills/epic-team/repo_manifest.yaml` — repo keyword mapping
- Linear MCP tools (`mcp__linear-server__*`) — epic and ticket access

## Container / Degraded Environment

When running without the full omniclaude plugin (e.g., container-based Claude Code sessions):

- **`onex:polymorphic-agent`** silently falls back to `general-purpose`. ONEX intelligence
  integration, action logging, and observability will be inactive. Skill instructions still
  execute correctly — only metadata and telemetry are affected.
- **Cross-skill dispatch** (`Skill(skill="onex:...")`) requires the plugin's skill registry.
  If skills are not registered, dispatch calls will fail. Verify: check if the skill
  appears in the system-reminder skills list.
- **Hook enforcement** (poly_enforcer, authorization_shim, bash_guard) will not be active.
- **Linear MCP** may not be available. See `--local` mode (if applicable) for offline
  ticket management.
