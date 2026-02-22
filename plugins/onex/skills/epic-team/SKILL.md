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

Decompose a Linear epic into per-repo workstreams and autonomously drive them to completion using
a team-lead + worker topology. The team lead (this session) owns planning, monitoring, state
persistence, and lifecycle notifications. Per-repo workers are spawned as `Task()` subagents and
execute tickets independently using `ticket-pipeline`.

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
  → Spawn one worker per repo (Task() subagent)
  → Each worker dispatches ticket-pipeline per ticket
  → Monitor workers, aggregate results
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

## Dispatch: Worker per Repo

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="epic-team worker: {repo_name} ({n} tickets)",
  prompt="You are the worker agent for repo {repo_name} in epic {epic_id}.

    Working directory: {repo_path}
    Tickets assigned: {ticket_list}

    For each ticket, invoke:
    Skill(skill=\"onex:ticket-pipeline\", args=\"{ticket_id}\")

    Wait for each ticket-pipeline to complete before starting the next.
    Read result from ~/.claude/skill-results/{context_id}/ticket-pipeline.json after each ticket.

    Report after each ticket: ticket_id, status, pr_url.
    Report final summary when all tickets are done."
)
```

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
- Worker spawning (one Task() per repo)
- State persistence (`~/.claude/epics/{epic_id}/state.yaml`)
- Slack lifecycle notifications (started, ticket done, epic done)

It does NOT own:
- Ticket implementation (delegated to `ticket-pipeline` → `ticket-work`)
- Code review (delegated to `local-review`)
- CI polling (delegated to `ci-watch`)
- PR review polling (delegated to `pr-watch`)
- Merge execution (delegated to `auto-merge`)

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
