---
description: Opt-in session continuity — save context before /clear for injection on next session start
mode: full
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
2. Writes a manifest to `$ONEX_STATE_DIR/handoff/{cwd_hash}-{session_id}.json`
   - `cwd_hash`: first 8 chars of SHA-256 of the CWD path
   - `session_id`: from `CLAUDE_SESSION_ID` env var (falls back to `uuidgen | head -c 8`)
   - This ensures concurrent sessions in the same CWD do NOT overwrite each other
3. Clears the session (equivalent to `/clear`)
4. On next session start (if `OMNICLAUDE_SESSION_HANDOFF=1`), session-start.sh:
   - Reads ALL manifests matching `$ONEX_STATE_DIR/handoff/{cwd_hash}-*.json`
   - Sorts by `created_at` descending, injects the most recent as `additionalContext`
   - Deletes ALL consumed manifests for this CWD after successful injection (one-shot cleanup)

## Atomicity Rules

- **Scoping**: Manifest path includes CWD hash AND session ID (NOT repo slug — repo is always the same for a given CWD)
- **Concurrency safe**: Each session writes its own file. 6 concurrent sessions = 6 separate manifests. No overwrites.
- **Atomic write**: Write to `.tmp` suffix first, then `mv` (atomic on POSIX)
- **Staleness**: Manifests older than 24h are ignored and cleaned up by session-start.sh
- **Injection failure**: If manifest read fails, log warning and continue without injection. Do not delete on failure — allow retry on next session start
- **One-shot**: All consumed manifests for the CWD are deleted after successful injection
- **Multiple manifests**: When multiple manifests exist for the same CWD, session-start.sh reads the most recent by `created_at` timestamp. All others are cleaned up.

## Toggle

Requires `OMNICLAUDE_SESSION_HANDOFF=1` in `~/.omnibase/.env` or shell environment.
Default is OFF (`0`). Without the toggle, session-start.sh skips handoff injection entirely.

## Manifest Format

**Filename**: `{cwd_hash}-{session_id}.json` (e.g., `94b129c9-AFA23AA3.json`)

```json
{
  "version": 1,
  "created_at": "2026-03-15T12:00:00Z",
  "cwd": "/path/to/project",
  "cwd_hash": "a1b2c3d4",
  "session_id": "AFA23AA3",
  "message": "Continue implementing the auth middleware",
  "context": {
    "active_ticket": "OMN-1234",
    "branch": "jonahgabriel/omn-1234-auth-middleware",
    "recent_commits": ["abc1234 fix: auth header parsing", "def5678 feat: add middleware skeleton"],
    "working_files": ["src/auth/middleware.py", "tests/test_middleware.py"]
  }
}
```

## Auto-Checkpoint Fallback

When invoked, `/handoff` checks for auto-checkpoint files at `~/.claude/handoffs/checkpoint-*.md`
(produced by the auto-checkpoint hook, OMN-6528). These are used as **fallback enrichment only**
when the user did not provide explicit handoff context.

### Precedence Rules

1. **Explicit handoff** (user-provided `--message` or active session context) is always authoritative
2. **Auto-checkpoints** fill gaps only — they never override explicit handoff content
3. If a manual handoff is newer than the latest checkpoint, checkpoints are ignored entirely
4. If no explicit context exists but checkpoints are present, merge the latest checkpoint into the manifest

### Integration Behavior

When building the handoff manifest:

```python
# After gathering explicit session context...
if not context.get("recent_commits") and not context.get("message"):
    # No explicit context — check for auto-checkpoints
    checkpoint_dir = Path.home() / ".claude" / "handoffs"
    checkpoints = sorted(checkpoint_dir.glob("checkpoint-*.md"), reverse=True)
    if checkpoints:
        latest = checkpoints[0]
        # Parse frontmatter for commit_hash, branch
        # Merge into context as fallback
        context["_source"] = "auto-checkpoint"
        context["_checkpoint_file"] = str(latest)
```

### Recovery Path

After a session crash or `/clear` without explicit `/handoff`:
1. Next session's `/onex:crash_recovery` reads the latest auto-checkpoint
2. Provides: last commit, branch, files changed, PR status
3. This makes session resumption seamless even without explicit handoff
