---
description: Detect stalled agent worktrees with uncommitted work and auto-ship (commit, push, create PR)
mode: full
version: "1.0.0"
level: advanced
debug: false
category: maintenance
tags: [agents, worktrees, shipping, automation, recovery]
author: omninode
composable: true
args:
  - name: --dry-run
    description: "Report stalled worktrees without taking action (default: false)"
    required: false
  - name: --worktrees-root
    description: "Override worktrees root path (default: /Volumes/PRO-G40/Code/omni_worktrees)" # local-path-ok
    required: false
---

# Ship Stalled Agents

**Skill ID**: `onex:ship_stalled_agents`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-6868

---

## Purpose

Detects worktrees with uncommitted work from stalled background agents and auto-ships
the work: stages, commits, pushes, and creates PRs. If pre-commit fails, creates a
recovery Linear ticket instead of forcing the commit.

**Announce at start:** "I'm using the ship-stalled-agents skill to check for uncommitted worktree work."

## Runtime Model

This skill is implemented as prompt-driven orchestration, not executable Python.
Python blocks in this document are pseudocode specifying logic and data shape, not
callable runtime helpers. The LLM executes the equivalent logic through Bash, Grep,
and GitHub CLI tool calls, holding intermediate state in its working context.

The models in `src/omniclaude/hooks/agent_shipper.py` define the data contracts:
- `EnumShipperAction`: NO_OP, COMMITTED, PUSHED, PR_CREATED, RECOVERY_TICKET
- `ModelStallDetection`: Git state of a single worktree
- `ModelShipperResult`: Outcome of shipping a single worktree
- `ModelShipperReport`: Aggregate report across all worktrees

## Usage

```
/ship-stalled-agents                     # scan and ship all stalled worktrees
/ship-stalled-agents --dry-run           # report only, no action
```
