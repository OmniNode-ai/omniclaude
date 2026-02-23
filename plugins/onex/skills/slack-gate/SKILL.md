---
name: slack-gate
description: Post a risk-tiered Slack gate via chat.postMessage and poll for human reply using Bot Token
version: 2.0.0
category: workflow
tags: [slack, gate, human-in-loop, notification, polling]
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
  - name: poll_interval_seconds
    type: int
    description: Seconds between reply polls (default 30 for LOW_RISK, 60 otherwise)
    required: false
  - name: accept_keywords
    type: list[str]
    description: "Replies that mean 'proceed' (default: ['yes', 'proceed', 'merge', 'approve'])"
    required: false
  - name: reject_keywords
    type: list[str]
    description: "Replies that mean 'reject' (default: ['no', 'reject', 'cancel', 'hold', 'deny'])"
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to ~/.claude/skill-results/{context_id}/slack-gate.json"
    fields:
      - status: accepted | rejected | timeout
      - risk_level: str
      - reply: str | null
      - thread_ts: str | null
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
  - name: --poll-interval-seconds
    description: Override default poll interval
    required: false
---

# Slack Gate

## Overview

Post a risk-tiered gate message to Slack via `chat.postMessage` (captures `thread_ts` for reply
threading), then poll the thread for human reply using the `conversations.replies` API. The gate
outcome determines whether the calling orchestrator proceeds, escalates, or holds.

**Announce at start:** "I'm using the slack-gate skill to post a [{risk_level}] gate."

**Implements**: OMN-2521, OMN-2627

## Quick Start

```
/slack-gate LOW_RISK "Epic has no tickets — auto-decomposed into 3 sub-tickets. Reply 'reject' to cancel."
/slack-gate MEDIUM_RISK "CI failed 3 times on PR #123. Reply 'skip-ci' to proceed or 'abort' to cancel."
/slack-gate HIGH_RISK "Ready to merge PR #123 to main. Reply 'merge' to proceed."
```

## Risk Tiers

| Tier | Default Timeout | Poll Interval | Silence Behavior | Use Case |
|------|----------------|---------------|------------------|----------|
| `LOW_RISK` | 30 minutes | Skip polling | Proceed (auto-approve) | Auto-decomposition, minor decisions |
| `MEDIUM_RISK` | 60 minutes | 60 seconds | Escalate (notify again, hold) | CI failures, cross-repo splits |
| `HIGH_RISK` | 24 hours | 60 seconds | Hold (explicit approval required) | Merges to main, destructive ops |

**LOW_RISK gates skip reply polling entirely** — they auto-approve after posting the message.
This matches the intent: LOW_RISK gates are informational notifications with opt-out only.

## Gate Flow

```
1. Resolve credentials (see Credential Resolution section)
2. Build formatted Slack message with [RISK_LEVEL] prefix
3. Post via chat.postMessage API → capture thread_ts
4. LOW_RISK: sleep for timeout_minutes, then exit with status: accepted (no polling)
5. MEDIUM_RISK / HIGH_RISK: poll conversations.replies every poll_interval_seconds:
   a. Fetch replies newer than gate post timestamp
   b. For each reply text (lowercased):
      - Match accept_keywords → exit with status: accepted
      - Match reject_keywords → exit with status: rejected
   c. If timeout reached:
      - MEDIUM_RISK: post follow-up notification + exit with status: timeout
      - HIGH_RISK: exit with status: timeout (caller must hold)
6. Write skill result JSON
```

## Slack Message Format

Messages are posted with prefix `[{risk_level}]` in bold:

```
*[LOW_RISK]* slack-gate: {short_summary}

{message_body}

Reply "{accept_keywords[0]}" to proceed. {silence_note}
Gate expires in {timeout_minutes} minutes.
```

**Silence notes by tier:**
- LOW_RISK: "No reply needed — silence = consent."
- MEDIUM_RISK: "Silence escalates after {timeout_minutes} minutes."
- HIGH_RISK: "Explicit approval required — silence holds."

## Implementation

### Step 1: Credential Resolution

```bash
# Load from ~/.omnibase/.env (source of truth)
if [[ -f ~/.omnibase/.env ]]; then
  source ~/.omnibase/.env
fi

# Verify required credentials
if [[ -z "$SLACK_BOT_TOKEN" || -z "$SLACK_CHANNEL_ID" ]]; then
  echo "ERROR: SLACK_BOT_TOKEN and SLACK_CHANNEL_ID required in ~/.omnibase/.env" >&2
  exit 1
fi
```

If credentials are missing from `~/.omnibase/.env`, fall back to Infisical:

```bash
# Infisical fallback — fetch SLACK_BOT_TOKEN and SLACK_CHANNEL_ID
source ~/.omnibase/.env
TOKEN=$(curl -s -X POST "$INFISICAL_ADDR/api/v1/auth/universal-auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"clientId\":\"$INFISICAL_CLIENT_ID\",\"clientSecret\":\"$INFISICAL_CLIENT_SECRET\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['accessToken'])")

SLACK_BOT_TOKEN=$(curl -s \
  "$INFISICAL_ADDR/api/v3/secrets/raw/SLACK_BOT_TOKEN?workspaceId=$INFISICAL_PROJECT_ID&environment=prod&secretPath=/shared/env" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['secret']['secretValue'])")

SLACK_CHANNEL_ID=$(curl -s \
  "$INFISICAL_ADDR/api/v3/secrets/raw/SLACK_CHANNEL_ID?workspaceId=$INFISICAL_PROJECT_ID&environment=prod&secretPath=/shared/env" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['secret']['secretValue'])")
```

### Step 2: Post via chat.postMessage

Use `chat.postMessage` instead of the webhook to capture `thread_ts`:

```bash
POST_RESPONSE=$(curl -s -X POST "https://slack.com/api/chat.postMessage" \
  -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d "{
    \"channel\": \"$SLACK_CHANNEL_ID\",
    \"text\": \"$FORMATTED_MESSAGE\"
  }")

# Extract thread_ts from response
THREAD_TS=$(echo "$POST_RESPONSE" | python3 -c "
import json, sys
data = json.load(sys.stdin)
if not data.get('ok'):
    raise SystemExit(f'chat.postMessage failed: {data.get(\"error\")}')
print(data['message']['ts'])
")
```

If `chat.postMessage` fails (e.g., invalid token), fall back to webhook fire-and-forget:

```bash
# Webhook fallback (no thread_ts capture — LOW_RISK only acceptable)
curl -s -X POST "$SLACK_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"$FORMATTED_MESSAGE\"}"
THREAD_TS=""
```

### Step 3: Poll for Replies (MEDIUM_RISK / HIGH_RISK only)

LOW_RISK skips this step entirely.

```bash
# Use the slack_gate_poll.py helper for polling
python3 "$(dirname "$0")/slack_gate_poll.py" \
  --channel "$SLACK_CHANNEL_ID" \
  --thread-ts "$THREAD_TS" \
  --bot-token "$SLACK_BOT_TOKEN" \
  --timeout-minutes "$TIMEOUT_MINUTES" \
  --poll-interval "$POLL_INTERVAL_SECONDS" \
  --accept-keywords "$ACCEPT_KEYWORDS_JSON" \
  --reject-keywords "$REJECT_KEYWORDS_JSON"
```

The helper script exits with:
- `0` and prints `ACCEPTED:<reply_text>` → exit with `status: accepted`
- `1` and prints `REJECTED:<reply_text>` → exit with `status: rejected`
- `2` and prints `TIMEOUT` → exit with `status: timeout`

### Step 4: Write Skill Result

```json
{
  "skill": "slack-gate",
  "status": "accepted",
  "risk_level": "HIGH_RISK",
  "reply": "merge",
  "thread_ts": "1234567890.123456",
  "elapsed_minutes": 5,
  "context_id": "{context_id}"
}
```

Write to: `~/.claude/skill-results/{context_id}/slack-gate.json`

## Executable Scripts

### `slack_gate_poll.py`

Python helper that implements the `conversations.replies` polling loop. See the script at
`plugins/onex/skills/slack-gate/slack_gate_poll.py` for the full implementation.

```
Usage: slack_gate_poll.py [options]
  --channel         Slack channel ID
  --thread-ts       Thread timestamp from chat.postMessage response
  --bot-token       Slack Bot Token (xoxb-...)
  --timeout-minutes Gate timeout in minutes
  --poll-interval   Seconds between polls (default 60)
  --accept-keywords JSON array of accept keywords
  --reject-keywords JSON array of reject keywords

Exit codes:
  0  Accepted (reply matched accept keyword)
  1  Rejected (reply matched reject keyword)
  2  Timeout (no reply before deadline)
```

### `slack-gate.sh`

Bash wrapper for programmatic invocation of this skill.

```bash
#!/usr/bin/env bash
set -euo pipefail

# slack-gate.sh — wrapper for the slack-gate skill
# Usage: slack-gate.sh <RISK_LEVEL> <MESSAGE> [--timeout-minutes N]

RISK_LEVEL=""
MESSAGE=""
TIMEOUT_MINUTES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --timeout-minutes)  TIMEOUT_MINUTES="$2";  shift 2 ;;
    -*)  echo "Unknown flag: $1" >&2; exit 1 ;;
    *)
      if [[ -z "$RISK_LEVEL" ]]; then RISK_LEVEL="$1"; shift
      elif [[ -z "$MESSAGE" ]];   then MESSAGE="$1";    shift
      else echo "Unexpected argument: $1" >&2; exit 1
      fi
      ;;
  esac
done

if [[ -z "$RISK_LEVEL" || -z "$MESSAGE" ]]; then
  echo "Usage: slack-gate.sh <RISK_LEVEL> <MESSAGE> [--timeout-minutes N]" >&2
  echo "  RISK_LEVEL: LOW_RISK | MEDIUM_RISK | HIGH_RISK" >&2
  exit 1
fi

TIMEOUT_ARG=""
if [[ -n "$TIMEOUT_MINUTES" ]]; then
  TIMEOUT_ARG="--arg timeout_minutes=${TIMEOUT_MINUTES}"
fi

exec claude --skill onex:slack-gate \
  --arg "risk_level=${RISK_LEVEL}" \
  --arg "message=${MESSAGE}" \
  ${TIMEOUT_ARG}
```

| Invocation | Description |
|------------|-------------|
| `/slack-gate LOW_RISK "Decomposed epic into 3 sub-tickets. Reply reject to cancel."` | Post LOW_RISK gate, auto-approve (no polling) |
| `/slack-gate HIGH_RISK "Ready to merge PR #123. Reply merge to proceed."` | Post HIGH_RISK gate, poll for explicit approval |
| `Skill(skill="onex:slack-gate", args="MEDIUM_RISK CI failed 3 times. --timeout-minutes 60")` | Programmatic: composable invocation from orchestrator |
| `slack-gate.sh HIGH_RISK "Deploy to production?" --timeout-minutes 1440` | Shell: direct invocation with 24h timeout |

## Skill Result Output

Write `ModelSkillResult` to `~/.claude/skill-results/{context_id}/slack-gate.json` on exit.

```json
{
  "skill": "slack-gate",
  "status": "accepted",
  "risk_level": "LOW_RISK",
  "reply": null,
  "thread_ts": "1234567890.123456",
  "elapsed_minutes": 0,
  "context_id": "{context_id}"
}
```

**Status values**: `accepted` | `rejected` | `timeout`

- `accepted`: Reply matched accept_keywords, or LOW_RISK (auto-approve, no polling)
- `rejected`: Reply matched reject_keywords
- `timeout`: MEDIUM_RISK or HIGH_RISK gate timed out without qualifying reply

## Credential Resolution

The agent executing this skill resolves Slack credentials in this order:

1. **Check `~/.omnibase/.env`** — source of truth for shared credentials:
   ```
   SLACK_BOT_TOKEN=xoxb-...       # Required for chat.postMessage + conversations.replies
   SLACK_CHANNEL_ID=C0...          # Required for posting and polling
   SLACK_WEBHOOK_URL=https://...   # Fallback for fire-and-forget (no thread_ts)
   ```

2. **Fetch from Infisical** (if not in local .env):
   - Addr: `http://localhost:8880` (or `INFISICAL_ADDR` from `~/.omnibase/.env`)
   - Project: `1efd8d15-99f3-429b-b973-3b10491af449` (`INFISICAL_PROJECT_ID`)
   - Environment: `prod`
   - Path: `/shared/env`

3. **Webhook fallback** (LOW_RISK only, no thread_ts):
   If Bot Token is unavailable, fall back to `SLACK_WEBHOOK_URL` for fire-and-forget. Only
   acceptable for LOW_RISK because there is no reply thread to poll.

> **Note**: Slack link syntax for clickable URLs: `<https://example.com|Link text>`

## Changelog

- **v2.0.0** (OMN-2627): Switch from webhook to `chat.postMessage`; implement
  `conversations.replies` polling; add `slack_gate_poll.py` helper; LOW_RISK auto-approve.
- **v1.0.0** (OMN-2521): Initial webhook-based implementation.

## See Also

- `auto-merge` skill (uses HIGH_RISK gate before merging)
- `epic-team` skill (uses LOW_RISK gate for empty epic auto-decompose)
- `ticket-pipeline` skill (uses MEDIUM_RISK gate for CI/PR escalation)
- `merge-sweep` skill (uses HIGH_RISK gate for batch merge approval)
- OMN-2521 — original implementation ticket
- OMN-2627 — reply polling implementation
- OMN-2629 — merge-sweep integration
