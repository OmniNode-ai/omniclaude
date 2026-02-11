---
name: authorize
description: Grant work authorization for Edit/Write operations in this session
tags: [security, authorization, workflow]
---

# Authorize

**Usage:** `/authorize [reason]`

Grant authorization for Edit/Write operations in the current session. Authorization lasts 4 hours.

## What This Does

Creates an authorization file at `/tmp/omniclaude-auth/{session_id}.json` that the PreToolUse auth gate checks before allowing Edit/Write operations.

## Implementation

When invoked:

1. Get the current session ID from the environment or generate one
2. Create directory `/tmp/omniclaude-auth/` if it doesn't exist
3. Write the authorization file:

```bash
SESSION_ID="${CLAUDE_SESSION_ID:-$(uuidgen | tr '[:upper:]' '[:lower:]')}"
REASON="${1:-no reason provided}"
GRANTED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
EXPIRES_AT=$(date -u -v+4H +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u -d "+4 hours" +"%Y-%m-%dT%H:%M:%SZ")

mkdir -p /tmp/omniclaude-auth
cat > "/tmp/omniclaude-auth/${SESSION_ID}.json" << EOF
{
    "session_id": "${SESSION_ID}",
    "granted_at": "${GRANTED_AT}",
    "expires_at": "${EXPIRES_AT}",
    "reason": "${REASON}",
    "source": "explicit",
    "allowed_tools": ["Edit", "Write"]
}
EOF
```

4. Confirm: "Authorization granted for Edit/Write operations. Expires in 4 hours. Reason: {reason}"

## Notes

- Authorization is scoped to the current session
- Expires after 4 hours (non-renewable -- run /authorize again to refresh)
- Use `/deauthorize` to revoke early
