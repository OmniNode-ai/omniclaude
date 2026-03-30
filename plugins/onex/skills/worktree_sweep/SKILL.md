---
description: Audit all worktrees under omni_worktrees, categorize health, auto-clean merged+clean, flag lost work and stale branches
mode: full
version: "1.0.0"
level: intermediate
debug: false
category: maintenance
tags: [worktree, cleanup, close-out, autopilot, sweep]
author: omninode
args:
  - name: dry_run
    description: "If true, report findings without removing worktrees or creating tickets (default: false)"
    required: false
  - name: worktrees_root
    description: "Override worktrees root path (default: /Volumes/PRO-G40/Code/omni_worktrees)" # local-path-ok
    required: false
  - name: stale_days
    description: "Number of days since last commit to consider a branch stale (default: 3)"
    required: false
---

# Worktree Health Sweep

Audits all git worktrees under `/Volumes/PRO-G40/Code/omni_worktrees/` and categorizes <!-- local-path-ok -->
them by health status. Auto-cleans merged+clean worktrees, flags lost work for recovery,
and identifies stale branches.

**Autopilot integration**: This skill runs as **Step 0** in close-out mode, before merge-sweep.
It ensures no work is silently lost and prevents worktree accumulation.

**Announce at start:** "I'm using the worktree-sweep skill to audit worktree health."

## Runtime Model

This skill is implemented as prompt-driven orchestration, not executable Python.
Python blocks in this document are pseudocode specifying logic and data shape, not
callable runtime helpers. The LLM executes the equivalent logic through Bash, Grep,
and Linear MCP tool calls, holding intermediate state in its working context.

The typed models live in `src/omniclaude/hooks/worktree_sweep.py` and define the
report schema: `EnumWorktreeStatus`, `ModelWorktreeEntry`, `ModelWorktreeSweepReport`.

## Usage

```
/worktree-sweep
/worktree-sweep --dry_run true
/worktree-sweep --stale_days 7
```
