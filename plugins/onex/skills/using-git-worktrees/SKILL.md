---
name: using-git-worktrees
description: Use when starting feature work that needs isolation from current workspace or before executing implementation plans - creates isolated git worktrees with smart directory selection and safety verification
version: 1.0.0
category: git
tags:
  - git
  - worktrees
  - isolation
  - workspace-management
author: OmniClaude Team
---

# Using Git Worktrees

## Overview

Git worktrees create isolated workspaces sharing the same repository, allowing work on multiple branches simultaneously without switching.

**Core principle:** Systematic directory selection + safety verification = reliable isolation.

**Announce at start:** "I'm using the using-git-worktrees skill to set up an isolated workspace."

## Directory Selection Process

Follow this priority order:

### 1. Check Existing Directories

```bash
# Check in priority order
ls -d .worktrees 2>/dev/null     # Preferred (hidden)
ls -d worktrees 2>/dev/null      # Alternative
```

**If found:** Use that directory. If both exist, `.worktrees` wins.

### 2. Check CLAUDE.md

```bash
grep -i "worktree.*director" CLAUDE.md 2>/dev/null
```

**If preference specified:** Use it without asking.

### 3. Ask User

If no directory exists and no CLAUDE.md preference:

```
No worktree directory found. Where should I create worktrees?

1. .worktrees/ (project-local, hidden)
2. ~/.config/worktrees/<project-name>/ (global location)

Which would you prefer?
```

### 4. Agent-Created Worktrees

When agents (subagents, polymorphic agents, automated workflows) create worktrees, they MUST use the canonical location:

```
~/.claude/worktrees/{repo}/{branch}
```

This location:
- Is outside any project repo (no .gitignore needed)
- Has deterministic cleanup via SessionEnd hook
- Is scoped per-repo and per-branch for isolation

**Do NOT use project-local directories for agent worktrees.** Project-local `.worktrees/` is for human-driven workflows only.

## Safety Verification

### For Project-Local Directories (.worktrees or worktrees)

**MUST verify .gitignore before creating worktree:**

```bash
# Check if directory pattern in .gitignore
grep -q "^\.worktrees/$" .gitignore || grep -q "^worktrees/$" .gitignore
```

**If NOT in .gitignore:**

Per best practices "Fix broken things immediately":
1. Add appropriate line to .gitignore
2. Commit the change
3. Proceed with worktree creation

**Why critical:** Prevents accidentally committing worktree contents to repository.

### For Global Directory (~/.config/worktrees)

No .gitignore verification needed - outside project entirely.

## Creation Steps

### 1. Detect Project Name

```bash
project=$(basename "$(git rev-parse --show-toplevel)")
```

### 2. Create Worktree

```bash
# Determine full path
case $LOCATION in
  .worktrees|worktrees)
    path="$LOCATION/$BRANCH_NAME"
    ;;
  ~/.config/worktrees/*)
    path="~/.config/worktrees/$project/$BRANCH_NAME"
    ;;
esac

# Create worktree with new branch
git worktree add "$path" -b "$BRANCH_NAME"
cd "$path"
```

### 3. Run Project Setup

Auto-detect and run appropriate setup:

```bash
# Node.js
if [ -f package.json ]; then npm install; fi

# Rust
if [ -f Cargo.toml ]; then cargo build; fi

# Python
if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
if [ -f pyproject.toml ]; then poetry install; fi

# Go
if [ -f go.mod ]; then go mod download; fi
```

### 4. Verify Clean Baseline

Run tests to ensure worktree starts clean:

```bash
# Examples - use project-appropriate command
npm test
cargo test
pytest
go test ./...
```

**If tests fail:** Report failures, ask whether to proceed or investigate.

**If tests pass:** Report ready.

### 5. Report Location

```
Worktree ready at <full-path>
Tests passing (<N> tests, 0 failures)
Ready to implement <feature-name>
```

## Session Marker

When creating a worktree at `~/.claude/worktrees/`, write a `.claude-session.json` marker file in the worktree root immediately after creation:

```bash
# After git worktree add
cat > "${worktree_path}/.claude-session.json" <<MARKER
{
  "session_id": "${SESSION_ID}",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "repo": "${project}",
  "branch": "${BRANCH_NAME}",
  "worktree_path": "${worktree_path}",
  "parent_repo_path": "$(git rev-parse --show-toplevel)",
  "creator": "using-git-worktrees/1.0.0",
  "cleanup_policy": "session-end"
}
MARKER
```

### Marker Fields

| Field | Required | Purpose |
|-------|----------|---------|
| `session_id` | Yes | Links worktree to creating session for cleanup scoping |
| `created_at` | Yes | ISO-8601 timestamp of creation |
| `repo` | Yes | Repository name (basename of repo root) |
| `branch` | Yes | Branch name used for the worktree |
| `worktree_path` | Yes | Absolute path to the worktree directory |
| `parent_repo_path` | Yes | Absolute path to the main repository |
| `creator` | Yes | Skill name and version that created this worktree |
| `cleanup_policy` | Yes | Must be `"session-end"` -- signals automatic cleanup |

**Without this marker, the worktree will NOT be cleaned up automatically.**

## Lifecycle Management

### Automatic Cleanup (SessionEnd)

When a Claude Code session ends, the SessionEnd hook scans `~/.claude/worktrees/` for worktrees with `.claude-session.json` markers matching the current session ID.

**A worktree is removed if ALL conditions are met:**
1. Has a valid `.claude-session.json` marker
2. Marker `session_id` matches the ending session
3. No uncommitted changes (`git diff --quiet`)
4. No staged changes (`git diff --cached --quiet`)
5. No unpushed commits (local HEAD matches upstream)
6. Path is under `~/.claude/worktrees/` (traversal guard)

**If ANY condition fails, the worktree is logged as STALE but NOT deleted.**

### What Gets Cleaned Up

| Scenario | Action |
|----------|--------|
| Clean worktree, matching session | Removed via `git worktree remove` |
| Clean worktree, different session | Skipped (belongs to another session) |
| Dirty worktree, any session | Skipped + logged as STALE |
| No `.claude-session.json` | Skipped entirely |
| Malformed marker | Skipped + logged as STALE |

### Manual Cleanup

For stale worktrees that weren't auto-cleaned:

```bash
# List all worktrees under ~/.claude/worktrees
find ~/.claude/worktrees -name '.claude-session.json' -exec jq -r '.repo + "/" + .branch + " (session: " + .session_id + ")"' {} \;

# Remove a specific stale worktree (from parent repo)
cd /path/to/parent/repo
git worktree remove ~/.claude/worktrees/repo/branch
git worktree prune
```

## Quick Reference

| Situation | Action |
|-----------|--------|
| `.worktrees/` exists | Use it (verify .gitignore) |
| `worktrees/` exists | Use it (verify .gitignore) |
| Both exist | Use `.worktrees/` |
| Neither exists | Check CLAUDE.md -> Ask user |
| Directory not in .gitignore | Add it immediately + commit |
| Tests fail during baseline | Report failures + ask |
| No package.json/Cargo.toml | Skip dependency install |
| Agent creating worktree | Use `~/.claude/worktrees/{repo}/{branch}` |
| Worktree created at `~/.claude/worktrees/` | Write `.claude-session.json` marker |
| Session ending | Auto-cleanup matching clean worktrees |
| Stale worktree logged | Manual cleanup required |

## Common Mistakes

**Skipping .gitignore verification**
- **Problem:** Worktree contents get tracked, pollute git status
- **Fix:** Always grep .gitignore before creating project-local worktree

**Assuming directory location**
- **Problem:** Creates inconsistency, violates project conventions
- **Fix:** Follow priority: existing > CLAUDE.md > ask

**Proceeding with failing tests**
- **Problem:** Can't distinguish new bugs from pre-existing issues
- **Fix:** Report failures, get explicit permission to proceed

**Hardcoding setup commands**
- **Problem:** Breaks on projects using different tools
- **Fix:** Auto-detect from project files (package.json, etc.)

## Example Workflow

```
You: I'm using the using-git-worktrees skill to set up an isolated workspace.

[Check .worktrees/ - exists]
[Verify .gitignore - contains .worktrees/]
[Create worktree: git worktree add .worktrees/auth -b feature/auth]
[Run npm install]
[Run npm test - 47 passing]

Worktree ready at /Users/dev/myproject/.worktrees/auth
Tests passing (47 tests, 0 failures)
Ready to implement auth feature
```

## Red Flags

**Never:**
- Create worktree without .gitignore verification (project-local)
- Skip baseline test verification
- Proceed with failing tests without asking
- Assume directory location when ambiguous
- Skip CLAUDE.md check
- Use `rm -rf` to clean up worktrees (use `git worktree remove` instead)
- Create agent worktrees without `.claude-session.json` marker

**Always:**
- Follow directory priority: existing > CLAUDE.md > ask
- Verify .gitignore for project-local
- Auto-detect and run project setup
- Verify clean test baseline
- Write `.claude-session.json` when creating agent worktrees
- Use `git worktree remove` + `git worktree prune` for cleanup

## Integration

**Called by:**
- **brainstorming** (Phase 4) - REQUIRED when design is approved and implementation follows
- Any skill needing isolated workspace

**Pairs with:**
- **finishing-a-development-branch** - REQUIRED for cleanup after work complete
- **executing-plans** or **subagent-driven-development** - Work happens in this worktree
