---
description: Generate a CI-verified evidence receipt for a task completion claim — dispatches to node_verification_receipt_generator (omnimarket)
mode: full
version: 1.0.0
level: intermediate
debug: false
category: verification
tags:
  - verification
  - receipts
  - ci
  - dod
author: OmniClaude Team
composable: true
args:
  - name: --task-id
    description: "Task identifier (e.g. OMN-9403)"
    required: true
  - name: --claim
    description: "What the task claims to have done (quoted string)"
    required: true
  - name: --repo
    description: "GitHub repo slug (e.g. OmniNode-ai/omniclaude)"
    required: false
  - name: --pr
    description: "PR number to verify CI checks for"
    required: false
  - name: --worktree-path
    description: "Path to worktree for pytest verification"
    required: false
  - name: --run-tests
    description: "Run pytest in worktree (default: true)"
    required: false
  - name: --dry-run
    description: "Return receipt without running verification"
    required: false
---

# Verification Receipt Generator

**Skill ID**: `onex:verification_receipt_generator`
**Version**: 1.0.0
**Owner**: omniclaude
**Backing node**: `omnimarket/src/omnimarket/nodes/node_verification_receipt_generator/`
**Ticket**: OMN-9403

---

## Purpose

Thin shim that dispatches to `node_verification_receipt_generator` in omnimarket.
Generates CI-verified evidence receipts for task completion claims. Kills
rubber-stamping: the node probes `gh pr checks` and/or runs `pytest` in the
worktree and returns a structured receipt with per-dimension evidence.

---

## Usage

```
/verification-receipt-generator --task-id OMN-1234 --claim "merged PR #567 with all CI green"
/verification-receipt-generator --task-id OMN-1234 --claim "..." --pr 567 --repo OmniNode-ai/omniclaude
/verification-receipt-generator --task-id OMN-1234 --claim "..." --worktree-path /path/to/wt --run-tests
```

---

## Dispatch

```bash
uv run onex run-node node_verification_receipt_generator -- \
  --task-id <task_id> \
  --claim "<claim>" \
  ${REPO:+--repo "$REPO"} \
  ${PR:+--pr-number "$PR"} \
  ${WORKTREE_PATH:+--worktree-path "$WORKTREE_PATH"} \
  ${RUN_TESTS:+--verify-tests} \
  ${DRY_RUN:+--dry-run}
```

Do not implement verification logic inline. All checking is in the node handler.

---

## Output

The node returns `ModelVerificationReceiptResponse`:
- `overall_pass: bool` — true only if ALL checks passed
- `checks: list` — per-dimension evidence (CI checks, pytest results)
- `verified_at: str` — ISO timestamp

Surface the JSON output. If `overall_pass == false`, render which checks failed.

**Backing node contract:** `omnimarket/src/omnimarket/nodes/node_verification_receipt_generator/contract.yaml`
