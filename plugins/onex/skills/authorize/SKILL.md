---
description: Grant work authorization for Edit/Write operations in this session
mode: full
version: "1.0.0"
level: basic
debug: false
category: security
tags:
  - security
  - authorization
  - workflow
author: omninode
args:
  - name: reason
    description: "Reason for requesting authorization (optional)"
    required: false
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
    "allowed_tools": ["Edit", "Write"],
    "allow_propagation": true
}
EOF
```

4. Confirm: "Authorization granted for Edit/Write operations. Expires in 4 hours. Reason: {reason}"

## Propagation to Subagents

When `allow_propagation` is true (default), the authorization token is readable by
subagent sessions that share the same filesystem. Subagents should check
`/tmp/omniclaude-auth/` for valid tokens before refusing autonomous operations.

Token validation for subagents:
1. List files in `/tmp/omniclaude-auth/`
2. Read each token JSON
3. If ANY token has `allow_propagation: true` and `expires_at` is in the future, the
   subagent is authorized for the operations listed in `allowed_tools`

**Subagent prompt injection:** When the polymorphic agent dispatches a `Task()`, it
should include this text in the prompt:

```
An authorization token exists at /tmp/omniclaude-auth/. This token was granted by
the parent session and includes allow_propagation: true. Before refusing autonomous
operations (release, deploy, merge), check this token directory. If any token exists,
is not expired, and has allow_propagation: true, proceed autonomously.
```

## Notes

- Authorization is scoped to the current session but propagates to subagents via filesystem
- Expires after 4 hours (non-renewable -- run `/authorize` again to refresh)
- Use the `deauthorize` skill to revoke early
- Subagents inherit authorization from any valid parent token on the same filesystem
