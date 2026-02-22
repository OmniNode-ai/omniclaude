# Global CLAUDE.md — Autonomous Pipeline Behavioral Rules

This document describes the behavioral rules that should be added to `~/.claude/CLAUDE.md`
(the global Claude Code shared-standards file) to eliminate common agent mistakes that
cause pipeline failures and unnecessary manual interventions.

**Installation**: Append the sections below to `~/.claude/CLAUDE.md`.

---

## Pre-Commit / CI

When pre-commit hooks fail, fix ALL issues (ruff, mypy, lint) in a single pass before
re-committing. Run `pre-commit run --all-files` before staging any files. Never attempt
to commit until pre-commit passes locally.

## Code Review Guidelines

Do NOT flag the following as blocking issues unless they cause test failures or runtime errors:
- asyncio_mode configuration
- lambda variable capture in loops (unless demonstrably buggy)
- symlink behavior assumptions covered by passing tests
- Implementation details covered by passing tests

Prioritize: real bugs > missing error handling > type errors > style. Nits are never blocking.

## Git Workflow

When the user asks about local changes, ALWAYS check `git status` and `git diff` FIRST before
investigating branch history or commit logs.

## Pre-Existing Issues

Pre-existing linter/mypy/test failures are bugs. Fix them as part of any coding task UNLESS:
- The fix would touch >10 files
- The fix requires an architectural decision
- The fix is in a completely unrelated subsystem

If a pre-existing issue meets an exception criterion, create a follow-up Linear ticket and note
it in the PR description. Do not silently ignore it.

## Iterative Fixes

After applying each fix, run the relevant check (mypy, ruff, pytest) on the modified file before
moving to the next fix. Do not introduce new issues while fixing old ones.

## Worktree Preference

For any multi-ticket or multi-session workflow, use git worktrees by default. Create worktrees at
`../{repo}/.claude/worktrees/{context_id}/` unless the task is a single quick fix.
