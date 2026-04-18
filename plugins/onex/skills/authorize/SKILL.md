---
description: Grant work authorization for Edit/Write operations in this session
mode: full
version: "2.0.0"
level: basic
debug: false
category: security
tags:
  - security
  - authorization
  - workflow
author: omninode
args:
  - name: scope
    description: "Comma-separated glob patterns the grant covers (e.g. 'src/**,tests/**'). Defaults to 'src/**,tests/**,docs/**'."
    required: false
  - name: tools
    description: "Comma-separated tool names (e.g. 'Edit,Write'). Defaults to 'Edit,Write'."
    required: false
  - name: ttl_seconds
    description: "Grant lifetime in seconds. Omit for the default 4 hour TTL; pass '0' for a non-expiring grant."
    required: false
---

# Authorize

**Usage:** `/authorize [scope] [tools] [ttl_seconds]`

Grant authorization for Edit/Write operations in the current session. Backed
by `node_authorize` in omnimarket per `feedback_skills_are_wrappers.md` —
logic lives in the node handler, this skill is a thin UX wrapper.

## What This Does

Invokes `node_authorize`, which writes a `ModelAgentAuthorizationGrant` to
`$ONEX_STATE_DIR/session/authorization.json` via a tempfile + `os.replace`
atomic swap. The PermissionRequest authorization gate hook (OMN-9087) reads
this file to auto-approve in-scope Edit/Write requests.

**Grant schema (on-disk contract):**

```json
{
  "scope": ["src/**", "tests/**"],
  "granted_at": "2026-04-17T16:00:00+00:00",
  "expires_at": "2026-04-17T20:00:00+00:00",
  "tools": ["Edit", "Write"]
}
```

- `expires_at: null` — non-expiring grant (explicit opt-in via `ttl_seconds=0`).
- Missing file OR `expires_at < now()` both collapse to "no grant"; the hook
  falls through to the default PermissionRequest flow.

## Invocation

Run the node directly via the ONEX node runner:

```bash
uv run onex run node_authorize -- \
  --scope 'src/**' --scope 'tests/**' \
  --tools Edit --tools Write \
  --ttl-seconds 14400
```

Under a full Kafka runtime, the skill wrapper publishes a command envelope to
`onex.cmd.omnimarket.authorize-start.v1`; the node consumes it, writes the
file, and emits `onex.evt.omnimarket.authorize-completed.v1`. Under
`RuntimeLocal` (no infra), the handler runs in-process via
`EventBusInmemory` — the file is written either way.

## File Location

`$ONEX_STATE_DIR/session/authorization.json`. The canonical relative path
constant is exported as `AUTHORIZATION_FILE_RELATIVE_PATH` from
`omnimarket.nodes.node_authorize.models.model_agent_authorization_grant`.

## Reader Contract

Downstream consumers (Task 3 PermissionRequest hook, audit tooling) should
import `load_grant_if_valid(path)` from the same module. It returns `None`
for missing, malformed, or expired grants — callers make exactly one
decision.

## Failure Modes

- `ONEX_STATE_DIR` unset — handler raises `RuntimeError`. Caller must export
  the env var before invocation (set at plugin install time).
- Disk write failure — handler removes the tempfile and re-raises; no
  partial `authorization.json` is ever observable.
- Second invocation — atomically replaces the prior grant.

## Migration Note

The prior `/tmp/omniclaude-auth/{session_id}.json` scheme read by
`plugins/onex/hooks/lib/auth_gate_adapter.py` remains in place for the
PreToolUse gate until the Task 3 PermissionRequest hook (OMN-9087) ships.
This skill writes the OMN-9087-shaped file; the PreToolUse adapter migration
is tracked under the OMN-9083 unused-hooks epic.

## Related

- Ticket: [OMN-9104](https://linear.app/omninode/issue/OMN-9104)
- Reader ticket: [OMN-9087](https://linear.app/omninode/issue/OMN-9087) (PermissionRequest authorization gate)
- Epic: [OMN-9083](https://linear.app/omninode/issue/OMN-9083) (unused-hooks)
- Node: `omnimarket/src/omnimarket/nodes/node_authorize/`
- Reference: `feedback_skills_are_wrappers.md`, `feedback_no_informational_gates.md`
