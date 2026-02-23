# Slack Gate — Execution Detail (OMN-2627)

This file contains detailed execution logic for the slack-gate skill.
Load this only if `SKILL.md` doesn't contain enough detail for the current situation.

## Full Execution Procedure

### 0. Parse Arguments

```
risk_level = args[0]                    # LOW_RISK | MEDIUM_RISK | HIGH_RISK
message = args[1]                       # gate message body
timeout_minutes = args.get("--timeout-minutes", tier_default)
poll_interval = args.get("--poll-interval-seconds", tier_default)
accept_keywords = args.get("accept_keywords", ["merge", "approve", "yes", "proceed"])
reject_keywords = args.get("reject_keywords", ["no", "reject", "cancel", "hold", "deny"])
```

Tier defaults:
- LOW_RISK: timeout=30m, poll_interval=N/A (auto-approve, no polling)
- MEDIUM_RISK: timeout=60m, poll_interval=60s
- HIGH_RISK: timeout=1440m (24h), poll_interval=60s

### 1. Resolve Credentials

```bash
# Always load from ~/.omnibase/.env first
source ~/.omnibase/.env 2>/dev/null || true

# Check required vars
if [[ -z "${SLACK_BOT_TOKEN:-}" || -z "${SLACK_CHANNEL_ID:-}" ]]; then
  # Infisical fallback
  if [[ -n "${INFISICAL_CLIENT_ID:-}" && -n "${INFISICAL_CLIENT_SECRET:-}" ]]; then
    TOKEN=$(curl -s -X POST "${INFISICAL_ADDR:-http://localhost:8880}/api/v1/auth/universal-auth/login" \
      -H "Content-Type: application/json" \
      -d "{\"clientId\":\"$INFISICAL_CLIENT_ID\",\"clientSecret\":\"$INFISICAL_CLIENT_SECRET\"}" \
      | python3 -c "import sys,json; print(json.load(sys.stdin)['accessToken'])")

    for secret_name in SLACK_BOT_TOKEN SLACK_CHANNEL_ID; do
      val=$(curl -s \
        "${INFISICAL_ADDR:-http://localhost:8880}/api/v3/secrets/raw/${secret_name}?workspaceId=${INFISICAL_PROJECT_ID}&environment=prod&secretPath=/shared/env" \
        -H "Authorization: Bearer $TOKEN" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['secret']['secretValue'])")
      export "${secret_name}=${val}"
    done
  fi
fi
```

### 2. Build Formatted Message

```python
silence_notes = {
    "LOW_RISK":    "No reply needed — silence = consent.",
    "MEDIUM_RISK": f"Silence escalates after {timeout_minutes} minutes.",
    "HIGH_RISK":   "Explicit approval required — silence holds.",
}
formatted = (
    f"*[{risk_level}]* slack-gate\n\n"
    f"{message}\n\n"
    f"Reply \"{accept_keywords[0]}\" to proceed. {silence_notes[risk_level]}\n"
    f"Gate expires in {timeout_minutes} minutes."
)
```

### 3. Post via chat.postMessage

```python
import json, urllib.request

payload = json.dumps({
    "channel": SLACK_CHANNEL_ID,
    "text": formatted,
}).encode("utf-8")

req = urllib.request.Request(
    "https://slack.com/api/chat.postMessage",
    data=payload,
    headers={
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    },
)
with urllib.request.urlopen(req, timeout=30) as resp:
    data = json.loads(resp.read())

if not data["ok"]:
    raise RuntimeError(f"chat.postMessage failed: {data.get('error')}")

thread_ts = data["message"]["ts"]
```

**If `chat.postMessage` fails due to invalid token:**
- Log the error
- Fall back to webhook (`SLACK_WEBHOOK_URL`) for fire-and-forget
- Set `thread_ts = None`
- If risk_level is MEDIUM_RISK or HIGH_RISK and no thread_ts: exit with error
  (reply polling is required for these tiers)
- If LOW_RISK: continue to auto-approve flow

### 4. LOW_RISK: Auto-Approve (No Polling)

```python
if risk_level == "LOW_RISK":
    # LOW_RISK gates are informational. Silence = consent.
    # Optionally sleep for a short grace period before auto-approving.
    # But do NOT poll — this keeps LOW_RISK gates fast and non-blocking.
    write_skill_result(status="accepted", reply=None, thread_ts=thread_ts, elapsed_minutes=0)
    exit(0)
```

### 5. MEDIUM_RISK / HIGH_RISK: Poll for Replies

```bash
POLL_RESULT=$(python3 "$(dirname "$0")/slack_gate_poll.py" \
  --channel "$SLACK_CHANNEL_ID" \
  --thread-ts "$THREAD_TS" \
  --bot-token "$SLACK_BOT_TOKEN" \
  --timeout-minutes "$TIMEOUT_MINUTES" \
  --poll-interval "$POLL_INTERVAL" \
  --accept-keywords "$(python3 -c "import json; print(json.dumps($ACCEPT_KEYWORDS))")" \
  --reject-keywords "$(python3 -c "import json; print(json.dumps($REJECT_KEYWORDS))")")
POLL_EXIT=$?

case "$POLL_EXIT" in
  0) STATUS="accepted"; REPLY="${POLL_RESULT#ACCEPTED:}" ;;
  1) STATUS="rejected"; REPLY="${POLL_RESULT#REJECTED:}" ;;
  2) STATUS="timeout";  REPLY="" ;;
  *) echo "ERROR: Polling failed: $POLL_RESULT" >&2; exit 1 ;;
esac
```

**MEDIUM_RISK timeout behavior:**
Post a follow-up re-notification before exiting:
```python
# Re-notify: post another message to the thread
followup = f"*[MEDIUM_RISK]* Gate expired with no response. Holding for manual review."
# post to thread (reply_broadcast=false)
```

**HIGH_RISK timeout behavior:**
Exit with `status: timeout` immediately. No re-notification needed.

### 6. Write Skill Result

```python
import json, os, pathlib

context_id = os.environ.get("CLAUDE_CONTEXT_ID", "default")
result_dir = pathlib.Path(f"~/.claude/skill-results/{context_id}").expanduser()
result_dir.mkdir(parents=True, exist_ok=True)

result = {
    "skill": "slack-gate",
    "status": status,           # accepted | rejected | timeout
    "risk_level": risk_level,
    "reply": reply or None,
    "thread_ts": thread_ts,
    "elapsed_minutes": elapsed_minutes,
    "context_id": context_id,
}
(result_dir / "slack-gate.json").write_text(json.dumps(result, indent=2))
```

## Agent Execution Notes

- The agent executing this skill should use `slack_gate_poll.py` as a subprocess for the
  polling loop. Do NOT implement the polling loop inline in the agent's main context.
- If the Bot Token is expired/invalid, log a clear error message directing the operator to
  regenerate the token in the Slack app settings and update `~/.omnibase/.env`.
- The `thread_ts` is critical for `conversations.replies`. Without it (webhook-only fallback),
  reply polling is impossible for MEDIUM_RISK and HIGH_RISK gates.

## Token Validity Check

Before posting, optionally verify the Bot Token:
```bash
AUTH_RESULT=$(curl -s -X POST "https://slack.com/api/auth.test" \
  -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
  -H "Content-Type: application/json")

if [[ "$(echo "$AUTH_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ok'))")" != "True" ]]; then
  echo "WARNING: SLACK_BOT_TOKEN appears invalid. Falling back to webhook (no reply polling)."
  # For MEDIUM_RISK / HIGH_RISK: exit with error, cannot proceed without polling
  # For LOW_RISK: continue with webhook fallback
fi
```

## Error Handling Summary

| Condition | LOW_RISK | MEDIUM_RISK | HIGH_RISK |
|-----------|----------|-------------|-----------|
| Token invalid, webhook works | Post via webhook, auto-approve | Exit with error | Exit with error |
| Token invalid, no webhook | Exit with error | Exit with error | Exit with error |
| Poll API error (transient) | N/A | Retry (log warning) | Retry (log warning) |
| Poll API error (persistent) | N/A | Exit with error | Exit with error |
| Timeout reached | Auto-approve | Re-notify + timeout | Timeout |
