---
name: epic-team
description: Orchestrate a Claude Code agent team to autonomously work a Linear epic across multiple repos
version: 1.0.0
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

## Usage Examples

```bash
# Dry run — see decomposition without spawning agents
/epic-team OMN-2000 --dry-run

# Full run
/epic-team OMN-2000

# Resume after session disconnect
/epic-team OMN-2000 --resume

# Force restart (archive existing state; hard-stops if workers active)
/epic-team OMN-2000 --force

# Force restart even with active workers (dangerous)
/epic-team OMN-2000 --force --force-kill

# Route unmatched tickets to omniplan triage
/epic-team OMN-2000 --force-unmatched
```

## Architecture

The team lead runs in this session and is responsible for fetching the epic from Linear, decomposing its child tickets into per-repo groups, and spawning one worker agent per repo via `Task()`. Each worker runs the ticket-work skill sequentially for every ticket assigned to its repo, reporting results back to the team lead as each ticket reaches a terminal state. The team lead monitors all workers, aggregates their outcomes, and sends Slack notifications at key lifecycle events — epic started, individual ticket completed or failed, and epic done. All runtime state (worker assignments, ticket statuses, worker task handles) is persisted to `~/.claude/epics/{epic_id}/state.yaml` so that a disconnected session can be resumed with `--resume` without losing progress. For full orchestration behavior, state-machine logic, and edge-case handling, see `prompt.md` in this directory.

## See Also

- `prompt.md` — full orchestration logic, state machine, and error handling reference
- `/ticket-work` — per-ticket execution skill used by each worker
- Linear MCP tools (`mcp__linear-server__*`) — epic and ticket access
