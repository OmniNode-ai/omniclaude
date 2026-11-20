---
description: "Bootstrap skill for the awaiting-reply check: dispatch shim to the omnimarket nodes. Finds the Slack and Linear asks waiting on the operator, classifies each AUTO or ESCALATE, and (with --send) lets the effect node answer the AUTO ones"
version: 1.0.0
mode: full
level: advanced
debug: false
category: workflow
tags: [slack, linear, replies, awaiting-reply, schedule]
composable: true
args:
  - name: --bundle
    description: "Path to the JSON read bundle the session wrote (typed items, source reads, allowlist, ladder rows)"
    required: true
  - name: --window
    description: "Look-back window the bundle covers, e.g. 6h, 24h, 72h (default: 6h)"
    required: false
  - name: --send
    description: "Let node_awaiting_reply_effect send the AUTO replies. Without it the effect runs as a dry run and sends nothing."
    required: false
bootstrap: true
skill_kind: dispatch
---

# /onex:awaiting_reply -- one command, one typed result

**Skill ID**: `onex:awaiting_reply` · **Command**: `uv run onex skill awaiting_reply` · **Backing nodes**: `node_awaiting_reply_compute` and `node_awaiting_reply_effect` (omnimarket)

A dispatch skill IS one CLI call. The nodes own the AUTO and ESCALATE rules, the allowlist check,
the Slack footer, the Linear comment line and the ledger row. This file holds none of them.

## Reads

The session's Slack and Linear connectors read the newest message of each open conversation in the
window. Write what they returned, unfiltered, to the bundle file in the shape of
`ModelAwaitingReplyRequest` (omnimarket, `node_awaiting_reply_compute/models`). Do not filter,
classify or draft. A field the reads do not fill is left out, so the node refuses the bundle and
names the field.

## Command

```bash
uv run onex skill awaiting_reply --bundle <path> [--window <6h|24h|72h>] [--send]
```

| Argument | Type |
|----------|------|
| `--bundle` | path, required |
| `--window` | string |
| `--send` | boolean, flag |

Without `--send` the effect node runs as a dry run: it composes each reply and sends nothing.

## Present the result

Parse the single JSON object on stdout and present the typed `ModelSkillResult`:

- **Status**: `status`
- **Result**: `result`, the waiting items (AUTO and ESCALATE, with basis and escalation stage), the
  excluded items with reasons and the per-source read status. A refusal names the field that did not
  fit; surface it as it is.

On non-zero exit, surface the `SkillRoutingError` envelope directly; do not produce prose and do not
retry with a bundle you repaired by guessing.

## What this skill does NOT do

- Classify, draft or send anything itself
- Write any Slack message, Linear comment or ledger row; the effect node does, to allowlisted people only
- Hold executable logic in this directory (markdown only)
