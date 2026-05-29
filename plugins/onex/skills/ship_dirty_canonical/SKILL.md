---
description: Detect uncommitted files in canonical omni_home repo clones and auto-ship each dirty repo to a worktree + PR. Dispatches to node_dirty_canonical_sweep (omnimarket, OMN-7466).
mode: full
version: 1.0.0
level: advanced
debug: false
category: operations
tags:
  - canonical
  - worktree
  - auto-ship
  - build-loop
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: true
args:
  - name: --dry-run
    description: "Detect and report dirty repos without moving files or creating PRs (default: false)"
    required: false
  - name: --repos
    description: "Comma-separated repo names to check (default: repos discovered by the backing node)"
    required: false
  - name: --omni-home
    description: "Override the workspace root used by the backing node"
    required: false
  - name: --worktrees-root
    description: "Override worktrees root path (default: $ONEX_WORKTREES_ROOT)"
    required: false
  - name: --pr-label
    description: "GitHub label to attach to auto-shipped PRs (default: auto-ship)"
    required: false
---

<!-- routing-enforced: dispatches to node_dirty_canonical_sweep. Fully implemented (OMN-7466). -->

# /onex:ship_dirty_canonical — Auto-ship dirty canonical repos

**Skill ID**: `onex:ship_dirty_canonical`
**Version**: 1.0.0
**Owner**: omniclaude
**Backing node**: `omnimarket/src/omnimarket/nodes/node_dirty_canonical_sweep/`
**Ticket**: OMN-7466

---

## Problem it solves

Agents can edit files in canonical workspace repo clones but cannot commit there.
Those edits sit uncommitted, are invisible to CI, and are at risk during routine
sync workflows.

This skill detects dirty canonicals and rescues the edits by:
1. Running status detection on every configured repo
2. Creating a worktree from `dev` at `$ONEX_WORKTREES_ROOT/auto-ship-<ts>/<repo>`
3. Copying the dirty files there and committing
4. Pushing and opening a PR with `--label auto-ship`
5. Restoring the canonical clone to clean state only after publishing succeeds

---

## Usage

```
/ship-dirty-canonical
/ship-dirty-canonical --dry-run
/ship-dirty-canonical --repos omniclaude,omnimarket
/ship-dirty-canonical --dry-run --repos omnibase_core
```

---

## Dispatch

```bash
INPUT_JSON='{"dry_run":false,"repos":null,"omni_home":null,"worktrees_root":null,"pr_label":"auto-ship"}'
uv run onex run-node node_dirty_canonical_sweep --input "${INPUT_JSON}"
```

The node returns `ModelDirtyCanonicalSweepResult`:
- `repos_checked`: total repos inspected
- `repos_dirty`: repos that had uncommitted changes
- `repos_shipped`: repos successfully shipped to PRs
- `repos_failed`: repos where ship failed
- `results`: per-repo `ModelDirtyRepoShipResult` entries (only dirty repos)

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

---

## Safety invariants (enforced by node handler, not this skill)

- `never_commits_to_canonical_repo` — the canonical clone is restored by the backing node only after successful shipping
- `restores_canonical_to_clean_state_on_success` — canonical changes remain in place if publishing the rescue branch fails
- `one_worktree_per_dirty_repo` — creates at most one worktree per dirty repo per invocation

---

## Build-loop integration

This skill is designed to be invoked by the 15-minute build-loop cron (OMN-7466).
Wire it as a CronCreate job to run every 15 minutes:

```
CronCreate(interval="15m", prompt="/ship-dirty-canonical")
```

The build loop can also invoke it explicitly during the VERIFYING phase as a
pre-condition before dispatching new tickets.

---

## Backing node contract

`omnimarket/src/omnimarket/nodes/node_dirty_canonical_sweep/contract.yaml`
