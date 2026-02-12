---
name: deauthorize
description: Revoke work authorization for Edit/Write operations in this session
tags: [security, authorization, workflow]
---

# Deauthorize

**Usage:** `/deauthorize`

Revoke authorization for Edit/Write operations in the current session.

## Implementation

When invoked:

1. Get the current session ID
2. Delete the authorization file:

```bash
SESSION_ID="${CLAUDE_SESSION_ID:-$(uuidgen | tr '[:upper:]' '[:lower:]')}"
rm -f "/tmp/omniclaude-auth/${SESSION_ID}.json"
```

3. Confirm: "Authorization revoked. Edit/Write operations will require re-authorization."

## Notes

- Only affects the current session
- Other sessions' authorizations are unaffected
- Run `/authorize [reason]` to re-grant
