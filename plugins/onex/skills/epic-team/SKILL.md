---
name: epic-team
description: Orchestrate a Claude Code agent team to autonomously work a Linear epic across multiple repos
version: 1.2.0
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

## Overview

Decompose a Linear epic into per-repo workstreams and autonomously drive them to completion using a team-lead + worker topology. The team lead (this session) owns planning, monitoring, state persistence, and lifecycle notifications. Per-repo workers are spawned as Task() subagents and execute tickets independently using the ticket-work skill.

**If the epic has zero child tickets**, epic-team automatically invokes the `decompose-epic` sub-skill to analyze the epic description and create sub-tickets, then posts a Slack LOW_RISK gate. Silence for 30 minutes means proceed with newly created tickets.

## Usage Examples

```bash
# Dry run — see decomposition without spawning agents
/epic-team OMN-2000 --dry-run

# Full run
/epic-team OMN-2000

# Resume after session disconnect
/epic-team OMN-2000 --resume

# Force restart (archive existing state; pauses if workers active — use --force-kill to hard-stop)
/epic-team OMN-2000 --force

# Force restart even with active workers (dangerous)
/epic-team OMN-2000 --force --force-kill

# Route unmatched tickets to omniplan triage
/epic-team OMN-2000 --force-unmatched
```

## Empty Epic Auto-Decompose

When fetching child tickets from Linear returns 0 results, epic-team no longer hard-stops. Instead:

```
epic-team OMN-XXXX
  → Fetch child tickets from Linear
  → If 0 child tickets:
      → Invoke decompose-epic OMN-XXXX (OMN-2522)
        → decompose-epic analyzes epic description
        → Creates N sub-tickets as Linear children (uses repo_manifest for repo assignment)
        → Returns ModelSkillResult with created_tickets list
      → Post Slack LOW_RISK gate:
          "Epic OMN-XXXX has no child tickets — auto-decomposed into N sub-tickets.
           Reply 'reject' within 30 minutes to cancel. Silence = proceed."
      → On 'reject' reply: stop, post "decomposition rejected by human" to Slack
      → On silence (30 min): fetch newly created tickets, continue with existing behavior
  → If >0 child tickets: existing behavior (assign to repos, spawn workers)
```

### Slack Message Format (Empty Epic Gate)

```
[LOW_RISK] epic-team: Auto-decomposed OMN-XXXX

Epic had no child tickets. Created N sub-tickets:
  - OMN-YYYY: [title]
  - OMN-ZZZZ: [title]
  ...

Reply "reject" within 30 minutes to cancel. Silence = proceed with orchestration.
```

### decompose-epic Dispatch

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="epic-team: auto-decompose empty epic {epic_id}",
  prompt="The epic {epic_id} has no child tickets. Invoke decompose-epic to create them.
    Invoke: Skill(skill=\"onex:decompose-epic\", args=\"{epic_id}\")

    Read the ModelSkillResult from ~/.claude/skill-results/{context_id}/decompose-epic.json
    Report back with: created_tickets (list of ticket IDs and titles), count."
)
```

### --dry-run behavior

In dry-run mode, if the epic is empty: invoke decompose-epic with `--dry-run` flag (returns plan without creating tickets). Print the decomposition plan. Do not post Slack gate.

## Repo Manifest

Repo assignment for tickets uses the user-global manifest at `~/.claude/epic-team/repo_manifest.yaml`:

```yaml
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

Keyword matching is case-insensitive. Tickets matching no repo are UNMATCHED (routed to triage or omniplan with `--force-unmatched`).

## Worktree Policy

Workers create isolated git worktrees at:
```
~/.claude/worktrees/{epic_id}/{run_id}/{ticket_id}/
```

After merge, stale worktrees are cleaned up automatically when `auto_cleanup_merged_worktrees: true` (default).

## Architecture

The team lead runs in this session and is responsible for fetching the epic from Linear, decomposing its child tickets into per-repo groups, and spawning one worker agent per repo via `Task()`. Each worker runs the ticket-work skill sequentially for every ticket assigned to its repo, reporting results back to the team lead as each ticket reaches a terminal state. The team lead monitors all workers, aggregates their outcomes, and sends Slack notifications at key lifecycle events — epic started, individual ticket completed or failed, and epic done. All runtime state (worker assignments, ticket statuses, worker task handles) is persisted to `~/.claude/epics/{epic_id}/state.yaml` so that a disconnected session can be resumed with `--resume` without losing progress. For full orchestration behavior, state-machine logic, and edge-case handling, see `prompt.md` in this directory.

## See Also

- `prompt.md` — full orchestration logic, state machine, and error handling reference
- `/ticket-work` — per-ticket execution skill used by each worker
- `decompose-epic` skill (OMN-2522) — invoked when epic has zero child tickets
- `slack-gate` skill (OMN-2521) — LOW_RISK gate for decompose confirmation
- `~/.claude/epic-team/repo_manifest.yaml` — user-global repo assignment manifest
- Linear MCP tools (`mcp__linear-server__*`) — epic and ticket access
