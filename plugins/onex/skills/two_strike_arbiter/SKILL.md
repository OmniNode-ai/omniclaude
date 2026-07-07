---
description: Two-strike diagnosis arbiter — after 2 consecutive fix failures, writes diagnosis doc and moves ticket to Blocked. Dispatches to node_two_strike_arbiter (omnimarket).
mode: full
version: 1.1.0
level: intermediate
debug: false
category: governance
tags:
  - two-strike
  - diagnosis
  - governance
  - pipeline-recovery
  - dispatch-surface-trace
author: OmniClaude Team
composable: true
args:
  - name: --ticket-id
    description: "Linear ticket identifier (e.g. <TICKET>)"
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
**Version**: 1.1.0
**Owner**: omniclaude
**Backing node**: `omnimarket/src/omnimarket/nodes/node_two_strike_arbiter/`
**Ticket**: <TICKET>
**Retro**: D-2 (<TICKET>) — first-strike dispatch-surface trace protocol

---

## Purpose

Thin shim that dispatches to `node_two_strike_arbiter` in omnimarket. After
2 consecutive fix failures on a ticket/PR, the node: (1) writes
`docs/diagnosis-{issue-slug}.md`, (2) moves the Linear ticket to Blocked,
and (3) files a friction event. Implements the Two-Strike Diagnosis Protocol
(per `~/.claude/CLAUDE.md`).

---

## First-Strike Protocol: Dispatch-Surface Defects

When `action == first_strike` **and** the defect is on a dispatch surface,
this skill mandates a full end-to-end static trace **before fixing anything**.

### What counts as a dispatch-surface defect

A defect is on the dispatch surface when it involves any of:
- Contract declaration (inputs, outputs, event_bus topics)
- Dispatch callback (how the handler is invoked from the node)
- Handler dependencies (injected consumers, updaters, recorders)
- Injected consumers (what topics they subscribe to)
- Terminal correlation (event ID / correlation chain to the `terminal_event`)

### Required static trace on first strike

Walk the full chain **contract → dispatch callback → handler deps → injected consumers → terminal correlation** and enumerate every defect found before making any fix:

1. Open the node's `contract.yaml` — verify `handler.module`, `handler.class`, `input_model`, `terminal_event`, and all `event_bus.subscribe_topics` / `event_bus.publish_topics`.
2. Trace how the dispatch callback invokes the handler class; confirm the injected deps match what the handler's `__init__` expects.
3. For each injected consumer / updater / recorder protocol, verify the concrete implementation exists and subscribes to the correct topic.
4. Confirm the terminal event emitted by the handler matches `terminal_event` declared in the contract.
5. Record **every** mismatch, missing binding, or wrong topic found across all four steps.

Only after the full trace is complete, enumerate the defects and ship fixes as **ONE design-reviewed PR set per repo**.

### Rationale

Four-cycle defect ladders (<TICKET>→<TICKET>→<TICKET>→<TICKET>) doubled overnight
dispatch costs. The fix-then-rediscover pattern is structurally disallowed by this rule
(Retro D-2, <TICKET>). The mandate is: enumerate ALL defects on first strike, fix once.

---

## Anti-Patterns

| Forbidden | Required |
|-----------|---------|
| Fix first dispatch-surface defect found, then discover the next one | Run full static trace on first strike; enumerate ALL defects before fixing any |
| Issue separate PRs for each defect discovered during the fix cycle | Bundle all defects found in the trace into ONE design-reviewed PR set per repo |
| Start implementation before completing the static trace | Complete the trace → enumerate → then implement |

---

## Usage

```
/two-strike-arbiter --ticket-id <TICKET>
/two-strike-arbiter --ticket-id <TICKET> --repo OmniNode-ai/omniclaude --pr 567
/two-strike-arbiter --ticket-id <TICKET> --dry-run
```

---

## Dispatch

```bash
INPUT_JSON='{"ticket_id":"<ticket_id>","repo":"<repo>","pr_number":<pr_number_or_null>,"branch":"<branch>","fix_attempts":[],"dry_run":true}'
uv run onex run-node node_two_strike_arbiter --input "${INPUT_JSON}"
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

When `action == first_strike`, the caller **must** perform the dispatch-surface static trace
described in the "First-Strike Protocol" section above before issuing any fix.

**Backing node contract:** `omnimarket/src/omnimarket/nodes/node_two_strike_arbiter/contract.yaml`
