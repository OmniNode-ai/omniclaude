---
name: slack-gate
description: Post a risk-tiered Slack gate and wait for human reply or timeout
version: 1.0.0
category: workflow
tags: [slack, gate, human-in-loop, notification]
author: OmniClaude Team
composable: true
inputs:
  - name: risk_level
    type: str
    description: "Gate risk tier: LOW_RISK | MEDIUM_RISK | HIGH_RISK"
    required: true
  - name: message
    type: str
    description: Gate message body (Markdown)
    required: true
  - name: timeout_minutes
    type: int
    description: Minutes before gate times out (default varies by tier)
    required: false
  - name: accept_keywords
    type: list[str]
    description: "Replies that mean 'proceed' (default: ['yes', 'proceed', 'merge', 'approve'])"
    required: false
  - name: reject_keywords
    type: list[str]
    description: "Replies that mean 'reject' (default: ['no', 'reject', 'cancel', 'hold'])"
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to ~/.claude/skill-results/{context_id}/slack-gate.json"
    fields:
      - status: accepted | rejected | timeout
      - risk_level: str
      - reply: str | null
      - elapsed_minutes: int
args:
  - name: risk_level
    description: "Gate tier: LOW_RISK|MEDIUM_RISK|HIGH_RISK"
    required: true
  - name: message
    description: Gate message body
    required: true
  - name: --timeout-minutes
    description: Override default timeout for this tier
    required: false
---

# Slack Gate

## Overview

Post a risk-tiered gate message to Slack and wait for human reply. The gate outcome determines
whether the calling orchestrator proceeds, escalates, or holds.

**Announce at start:** "I'm using the slack-gate skill to post a [{risk_level}] gate."

**Implements**: OMN-2521

## Quick Start

```
/slack-gate LOW_RISK "Epic has no tickets — auto-decomposed into 3 sub-tickets. Reply 'reject' to cancel."
/slack-gate MEDIUM_RISK "CI failed 3 times on PR #123. Reply 'skip-ci' to proceed or 'abort' to cancel."
/slack-gate HIGH_RISK "Ready to merge PR #123 to main. Reply 'merge' to proceed."
```

## Risk Tiers

| Tier | Default Timeout | Silence Behavior | Use Case |
|------|----------------|------------------|----------|
| `LOW_RISK` | 30 minutes | Proceed (silence = consent) | Auto-decomposition, minor decisions |
| `MEDIUM_RISK` | 60 minutes | Escalate (notify again, hold) | CI failures, cross-repo splits |
| `HIGH_RISK` | 24 hours | Hold (explicit approval required) | Merges to main, destructive ops |

## Gate Flow

1. Post message to Slack with `[{risk_level}]` prefix
2. Poll for reply every 60 seconds (LOW_RISK: 30s):
   - If reply matches `accept_keywords`: exit with `status: accepted`
   - If reply matches `reject_keywords`: exit with `status: rejected`
   - If timeout reached: apply silence behavior
3. LOW_RISK timeout → exit with `status: accepted` (silence = consent)
4. MEDIUM_RISK timeout → re-notify + exit with `status: timeout`
5. HIGH_RISK timeout → exit with `status: timeout` (caller must hold)

## Slack Message Format

Messages are posted with prefix `[{risk_level}]` in bold:

```
*[LOW_RISK]* slack-gate: {short_summary}

{message_body}

Reply "{accept_keywords[0]}" to proceed. {silence_note}
Gate expires in {timeout_minutes} minutes.
```

## Skill Result Output

Write `ModelSkillResult` to `~/.claude/skill-results/{context_id}/slack-gate.json` on exit.

```json
{
  "skill": "slack-gate",
  "status": "accepted",
  "risk_level": "LOW_RISK",
  "reply": null,
  "elapsed_minutes": 0,
  "context_id": "{context_id}"
}
```

**Status values**: `accepted` | `rejected` | `timeout`

- `accepted`: Reply matched accept_keywords, or LOW_RISK timed out (silence = consent)
- `rejected`: Reply matched reject_keywords
- `timeout`: MEDIUM_RISK or HIGH_RISK gate timed out without reply

## See Also

- `auto-merge` skill (uses HIGH_RISK gate before merging)
- `epic-team` skill (uses LOW_RISK gate for empty epic auto-decompose)
- `ticket-pipeline` skill (uses MEDIUM_RISK gate for CI/PR escalation)
- OMN-2521 — implementation ticket
