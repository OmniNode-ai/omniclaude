---
name: slack-gate
description: Risk-classified Slack gate — posts approval request to Slack and waits for response with idempotent state, audit logging, and silence=consent for low-risk gates
version: 1.0.0
category: workflow
tags:
  - slack
  - gate
  - approval
  - human-in-the-loop
  - idempotent
author: OmniClaude Team
composable: true
args:
  - name: gate_id
    type: str
    description: Unique identifier for this gate (hash of ticket_id + phase + attempt)
    required: true
  - name: message
    type: str
    description: Message to post to Slack asking for approval
    required: true
  - name: risk
    type: enum
    description: "Risk level: LOW_RISK | MEDIUM_RISK | HIGH_RISK"
    required: true
  - name: timeout_seconds
    type: int
    description: How long to wait for a response before applying silence behavior (default 600)
    required: false
  - name: channel
    type: str
    description: Slack channel to post in (default from env SLACK_GATE_CHANNEL)
    required: false
outputs:
  - name: decision
    type: enum
    description: "silence_consent | explicit_approve | explicit_reject | timeout_escalated"
  - name: response_text
    type: str
    description: Slack response text, or null if silence
---

# Slack Gate

## Overview

Composable sub-skill that posts a Slack message and waits for a human response. Replaces
hard keyboard gates across all pipeline skills. Risk classification determines silence behavior —
LOW_RISK gates auto-advance on timeout; HIGH_RISK gates hold until explicit approval.

**Announce at start:** "I'm using the slack-gate skill for gate {gate_id}."

## Risk Classification

| Risk Level | Examples | Silence Behavior |
|------------|----------|------------------|
| **LOW_RISK** | "no questions" timeout, small-scope spec approval, nit review | Silence = `silence_consent` after timeout |
| **MEDIUM_RISK** | Review override, "scope unclear" CI fix, architectural classification | Silence = escalate + create Linear ticket |
| **HIGH_RISK** | Merge (branch delete), mass refactor >10 files, infra/secrets changes | Silence = hold indefinitely; requires explicit "approve" |

## Idempotency Model

Every gate invocation is idempotent — safe to call on retry or restart:

```
gate_id = hash(ticket_id + phase + attempt)
state_path = ~/.claude/gates/{gate_id}.json
```

**Before posting to Slack**:
1. Check if `~/.claude/gates/{gate_id}.json` exists
2. If status is `open`: resume polling existing thread (no re-post)
3. If status is `resolved`: return cached decision immediately
4. If not found: create gate, post to Slack, start polling

**State file is written atomically** (tmp file → rename) to prevent corruption on crash.

## Gate State Schema

```json
{
  "gate_id": "abc123def456",
  "ticket_id": "OMN-2356",
  "phase": "spec_approval",
  "risk": "LOW_RISK",
  "timeout_seconds": 600,
  "channel": "#pipeline-gates",
  "slack_thread_ts": "1234567890.123456",
  "status": "open | resolved",
  "decision": "silence_consent | explicit_approve | explicit_reject | timeout_escalated | null",
  "response_text": null,
  "posted_at": "2026-02-21T14:30:00Z",
  "resolved_at": null
}
```

## Polling Behavior

After posting the Slack message, the gate polls for a reply:

```
poll_interval = 30s
timeout = gate.timeout_seconds (default 600s)

loop:
  → Check gate state file for external resolution (another process may have resolved it)
  → Check Slack thread for reply containing "approve", "yes", "lgtm", "go", "ok",
      "reject", "no", "stop", "hold", "cancel"
  → If reply found: resolve with explicit_approve or explicit_reject
  → Wait poll_interval
  → If timeout reached: apply silence behavior based on risk level
```

**Keyword matching** (case-insensitive): `approve`, `yes`, `lgtm`, `go`, `ok` → `explicit_approve`;
`reject`, `no`, `stop`, `hold`, `cancel` → `explicit_reject`.

## Silence Behavior by Risk Level

### LOW_RISK — Silence = Consent

After timeout: resolve with `decision: silence_consent`, continue pipeline.

### MEDIUM_RISK — Silence = Escalate

After timeout: create a Linear sub-ticket for human review, resolve with `decision: timeout_escalated`,
log warning, continue pipeline (with reduced confidence).

### HIGH_RISK — Silence = Hold

After timeout: post a reminder to Slack, reset poll timer, continue waiting.
Never auto-advance. Only explicit `approve` unblocks.

> **Note**: Reminder messages must not contain the words `hold`, `cancel`, `stop`, `no`, or `reject`
> (any keyword that maps to `explicit_reject`), as the gate polls all replies including its own reminders
> if they appear in the thread.

## Audit Event

Every gate decision (silence or explicit) logs an audit record:

```json
{
  "gate_id": "abc123def456",
  "ticket_id": "OMN-2356",
  "phase": "spec_approval",
  "risk": "LOW_RISK",
  "timeout_seconds": 600,
  "decision": "silence_consent",
  "response_text": null,
  "timestamp": "2026-02-21T14:32:00Z"
}
```

Audit records are appended to `~/.claude/gates/audit.jsonl` (append-only log).

## Slack Message Format

```
[{risk}] Gate: {gate_id} — {ticket_id} {phase}

{message}

Reply with:
  • approve / yes / lgtm / go / ok — to approve
  • reject / no / stop / hold / cancel — to reject

Risk: {risk}
Timeout: {timeout_seconds}s
{LOW_RISK: "Silence = auto-approve after {timeout}s" | MEDIUM_RISK: "Silence = escalate + Linear ticket after {timeout}s" | HIGH_RISK: "Silence = hold (will not auto-advance)"}
```

## Composable Usage

From other skills (e.g., ticket-pipeline, ci-fix-pipeline):

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Slack gate for {phase}",
  prompt="Invoke: Skill(skill=\"onex:slack-gate\", args={
    gate_id: sha256(\"{ticket_id}:{phase}:{attempt}\")[:12],
    message: \"{approval_request}\",
    risk: \"LOW_RISK\",
    timeout_seconds: 600,
    channel: \"#pipeline-gates\"
  })

  Return the gate decision when complete."
)
```

Or inline (for orchestrators that manage their own loop):

```python
# Check gate state before posting
gate_path = os.path.expanduser(f"~/.claude/gates/{gate_id}.json")
if gate_exists(gate_path):
    gate = load_gate_state(gate_path)
    if gate["status"] == "resolved":
        return gate["decision"]  # cached — no Slack post
    # else: resume polling existing thread

# Post to Slack and poll
post_slack_gate(gate_id, message, risk, timeout, channel)
decision = poll_until_resolved(gate_id)
return decision
```

## Failure Handling

| Error | Behavior |
|-------|----------|
| Slack unavailable | Degrade to `silence_consent` for LOW_RISK; `timeout_escalated` for MEDIUM_RISK; hard hold for HIGH_RISK |
| Gate state file unwritable | Log error, continue in-memory (no idempotency this invocation) |
| Linear ticket creation fails (MEDIUM_RISK timeout) | Log warning, continue |
| Poll timeout exceeded | Apply silence behavior for risk level |

## See Also

- `ticket-pipeline` skill — invokes slack-gate at spec approval and review override gates
- `ci-fix-pipeline` skill (planned) — invokes slack-gate for MEDIUM_RISK architectural classification
- `auto-merge` skill (planned) — invokes slack-gate at HIGH_RISK for merge approval
