---
name: epic-team
description: Orchestrate a Claude Code agent team to autonomously work a Linear epic across multiple repos
version: 2.0.0
category: workflow
tags: [epic, team, multi-repo, autonomous, linear, slack]
args:
  - epic_id (required): Linear epic ID (e.g., OMN-2000)
  - --dry-run: Print decomposition plan (includes unmatched reason), no spawning
  - --force: Pause if active tasks remain; archive state and restart
  - --force-kill: Combine with --force to destroy active run even with live workers
  - --resume: Re-enter monitoring; finalize if all tasks terminal; no-op if already done
  - --force-unmatched: Route unmatched tickets to omniplan as TRIAGE tasks
---

# Epic Team Orchestration

> **Session lifetime**: The monitoring phase is alive only while this session runs. Use `/epic-team {epic_id} --resume` to re-enter after a disconnection.

> **Architecture note (v2.0.0)**: epic-team is a thin orchestrator. All business logic lives in
> independently-invocable composable sub-skills. epic-team's job is coordination, state, and routing
> — not implementation.

## Overview

Decompose a Linear epic into per-repo workstreams and autonomously drive them to completion.
The team lead (this session) owns planning, dispatch, state persistence, and lifecycle
notifications. Tickets are executed by dispatching `ticket-pipeline` as sequential `Task()`
subagents directly from the team-lead session, in dependency-respecting waves.

**Key constraint**: Workers spawned as team members (via `TeamCreate` + `Task(team_name=...)`)
go idle immediately and never process tasks. The proven working pattern is **direct dispatch
from the team-lead session** — see the Architecture section below.

**If the epic has zero child tickets**, epic-team invokes `decompose-epic` to create sub-tickets,
then posts a Slack LOW_RISK gate. Silence for 30 minutes = proceed.

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
      → Read ~/.claude/skill-results/{context_id}/decompose-epic.json
      → Dispatch slack-gate (LOW_RISK, 30 min, silence=proceed)
      → Read ~/.claude/skill-results/{context_id}/slack-gate.json
      → If rejected: stop
      → Re-fetch newly created tickets
  → Assign tickets to repos via repo_manifest
  → Build dependency waves:
      Wave 0: independent tickets + cross-repo Part 1 splits (run in parallel)
      Wave 1: cross-repo Part 2 splits (run after Wave 0 completes)
  → For each wave: dispatch ticket-pipeline per ticket as Task() from team-lead session
  → Await all Task() calls in wave before starting next wave
  → Collect results (status, pr_url, branch) from each Task()
  → Send Slack lifecycle notifications (started, ticket done, epic done)
  → Persist state to ~/.claude/epics/{epic_id}/state.yaml
```

## Dispatch: decompose-epic

When epic has 0 child tickets:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="epic-team: auto-decompose empty epic {epic_id}",
  prompt="The epic {epic_id} has no child tickets.

    Invoke: Skill(skill=\"onex:decompose-epic\", args=\"{epic_id}\")

    Read result from ~/.claude/skill-results/{context_id}/decompose-epic.json
    Report back: created_tickets (list of IDs and titles), count."
)
```

## Dispatch: Ticket-Pipeline per Ticket (Direct Dispatch Pattern)

For each ticket in a wave, dispatch ticket-pipeline as a Task() from the team-lead session:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="epic-team: ticket-pipeline for {ticket_id} [{repo}]",
  prompt="You are executing ticket {ticket_id} for epic {epic_id}.

    Ticket: {ticket_id} - {title}
    URL: {url}
    Repo: {repo} at {repo_path}
    Epic: {epic_id}  Run: {run_id}

    Invoke: Skill(skill=\"onex:ticket-pipeline\", args=\"{ticket_id}\")

    After ticket-pipeline completes, report back:
    - ticket_id: {ticket_id}
    - status: (merged/failed/blocked)
    - pr_url: (if available)
    - branch: (branch name used)"
)
```

**Wave parallelism**: All Task() calls within a wave MUST be dispatched in the same response
(same message) for true parallelism. Do NOT dispatch tickets sequentially within a wave.

**Wave serialization**: Wave N+1 starts only after all Task() calls from Wave N have returned.

**DEPRECATED**: Spawning per-repo workers via `TeamCreate` + `Task(team_name=...)` + a
`WORKER_TEMPLATE` is no longer used. See `prompt.md` for the deprecated WORKER_TEMPLATE
preserved for historical reference.

## Skill Result Communication

All sub-skills write their output to `~/.claude/skill-results/{context_id}/`:

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

## State Persistence

Runtime state is persisted to `~/.claude/epics/{epic_id}/state.yaml`:

```yaml
epic_id: OMN-XXXX
run_id: f084b6c3
status: monitoring  # queued | monitoring | done | failed
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

## Worktree Policy

Workers create isolated git worktrees at:

Workers create isolated git worktrees at:
```
~/.claude/worktrees/{epic_id}/{run_id}/{ticket_id}/
```

Stale worktrees are cleaned up automatically after merge when `auto_cleanup_merged_worktrees: true`
(default).

## Architecture

epic-team is a thin composition layer. It owns:
- Epic decomposition (via `decompose-epic`)
- Ticket-to-repo assignment (via repo_manifest)
- Wave construction (group tickets by dependency into parallel waves)
- Direct Task() dispatch of ticket-pipeline per ticket (from team-lead session)
- State persistence (`~/.claude/epics/{epic_id}/state.yaml`)
- Slack lifecycle notifications (started, ticket done, epic done)

It does NOT own:
- Ticket implementation (delegated to `ticket-pipeline` → `ticket-work`)
- Code review (delegated to `local-review`)
- CI polling (delegated to `ci-watch`)
- PR review polling (delegated to `pr-watch`)
- Merge execution (delegated to `auto-merge`)

### Execution Model

**Direct dispatch from team-lead session** is the authoritative execution pattern:

1. Team-lead constructs waves of tickets grouped by dependency
2. For each wave, team-lead dispatches one `Task()` per ticket in parallel
3. Team-lead awaits all Task() completions in a wave before starting the next wave
4. Results (status, pr_url, branch) are collected directly from Task() return values
5. No background workers, no TaskList polling loop, no SendMessage coordination

**Why not per-repo workers?** Workers spawned as team members via `TeamCreate` + `Task(team_name=...)`
go idle immediately (`idleReason: available`) and never process tasks from the task queue.
This is a confirmed behavior across multiple epic runs. The direct dispatch pattern is the
only execution model that reliably completes tickets.

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
