---
description: Opt-in session continuity — save context before /clear for injection on next session start
version: 1.0.0
level: basic
debug: false
category: workflow
tags:
  - session
  - continuity
  - handoff
  - context
  - clear
author: OmniClaude Team
args:
  - name: --message
    description: "Optional message for the next session (free text context)"
    required: false
mode: full
---

# /handoff — Opt-in Session Continuity

## Overview

Save session context and clear. The next session starts with continuity.
`/clear` alone stays clean — no surprise injection.

## Usage

```
/handoff
/handoff --message "Continue implementing the auth middleware"
```

## How It Works

1. `/handoff` captures current session context (active ticket, branch, recent commits, working files)
2. Writes a manifest to `~/.claude/handoff/{cwd_hash}-{repo_slug}.json`
3. Clears the session (equivalent to `/clear`)
4. On next session start (if `OMNICLAUDE_SESSION_HANDOFF=1`), session-start.sh:
   - Reads the manifest for the current CWD
   - Injects the context as `additionalContext`
   - Deletes the manifest after successful injection (one-shot)

## Atomicity Rules

- **Scoping**: Manifest path includes both CWD hash AND repo identity
- **Atomic write**: Write to `.tmp` suffix first, then `mv` (atomic on POSIX)
- **Staleness**: Manifests older than 24h are ignored and cleaned up by session-start.sh
- **Injection failure**: If manifest read fails, log warning and continue without injection. Do not delete on failure — allow retry on next session start
- **One-shot**: Manifest consumed (deleted) after successful injection

## Toggle

Requires `OMNICLAUDE_SESSION_HANDOFF=1` in `~/.omnibase/.env` or shell environment.
Default is OFF (`0`). Without the toggle, session-start.sh skips handoff injection entirely.

## Manifest Format

```json
{
  "version": 1,
  "created_at": "2026-03-15T12:00:00Z",
  "cwd": "/path/to/project",
  "cwd_hash": "a1b2c3d4",
  "repo_slug": "omniclaude",
  "message": "Continue implementing the auth middleware",
  "context": {
    "active_ticket": "OMN-1234",
    "branch": "jonahgabriel/omn-1234-auth-middleware",
    "recent_commits": ["abc1234 fix: auth header parsing", "def5678 feat: add middleware skeleton"],
    "working_files": ["src/auth/middleware.py", "tests/test_middleware.py"]
  }
}
```
