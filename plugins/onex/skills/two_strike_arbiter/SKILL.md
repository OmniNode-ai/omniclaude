---
description: Two-strike diagnosis arbiter — after 2 consecutive fix failures, writes diagnosis doc and moves ticket to Blocked. Dispatches to node_two_strike_arbiter (omnimarket).
mode: full
version: 1.0.0
level: intermediate
debug: false
category: governance
tags:
  - two-strike
  - diagnosis
  - governance
  - pipeline-recovery
author: OmniClaude Team
composable: true
args:
  - name: --ticket-id
    description: "Linear ticket identifier (e.g. OMN-1234)"
    required: true
  - name: --repo
    description: "Repository slug (optional)"
    required: false
  - name: --pr
    description: "PR number (optional)"
    required: false
  - name: --branch
    description: "Branch name (optional)"
    required: false
  - name: --dry-run
    description: "Skip side effects when true"
    required: false
---

# Two-Strike Arbiter

**Skill ID**: `onex:two_strike_arbiter`
**Version**: 1.0.0
**Owner**: omniclaude
**Backing node**: `omnimarket/src/omnimarket/nodes/node_two_strike_arbiter/`
**Ticket**: OMN-9403

---

## Purpose

Thin shim that dispatches to `node_two_strike_arbiter` in omnimarket. After
2 consecutive fix failures on a ticket/PR, the node: (1) writes
`docs/diagnosis-{issue-slug}.md`, (2) moves the Linear ticket to Blocked,
and (3) files a friction event. Implements the Two-Strike Diagnosis Protocol
(per `~/.claude/CLAUDE.md`).

---

## Usage

```
/two-strike-arbiter --ticket-id OMN-1234
/two-strike-arbiter --ticket-id OMN-1234 --repo OmniNode-ai/omniclaude --pr 567
/two-strike-arbiter --ticket-id OMN-1234 --dry-run
```

---

## Dispatch

```bash
uv run onex run-node node_two_strike_arbiter -- \
  --ticket-id <ticket_id> \
  ${REPO:+--repo "$REPO"} \
  ${PR:+--pr-number "$PR"} \
  ${BRANCH:+--branch "$BRANCH"} \
  ${DRY_RUN:+--dry-run}
```

Do not invoke diagnosis logic inline. All state tracking and side effects are in the node handler.

---

## Output

The node returns `ModelTwoStrikeResult`:
- `ticket_id: str`
- `total_attempts: int`
- `action: str` — `no_action | first_strike | second_strike | diagnosis_written | ticket_blocked | friction_filed`
- `diagnosis_path: str | None` — path to written diagnosis doc (non-null when `action == diagnosis_written`)
- `friction_filed: bool`

**Backing node contract:** `omnimarket/src/omnimarket/nodes/node_two_strike_arbiter/contract.yaml`
