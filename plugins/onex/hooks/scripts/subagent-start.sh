#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# SubagentStart Hook — inject compact ONEX conventions into every spawned agent
# OMN-7020 / OMN-5130: Platform-agnostic context injection for team workers
# Performance target: <50ms execution time
#
# =============================================================================
# Claude Code SubagentStart JSON Schema
# =============================================================================
# Input (stdin):
# {
#   "session_id": "abc123",
#   "agent_name": "worker-1",
#   "team_name": "test-team",
#   "parent_session_id": "parent-session"
# }
#
# Output (stdout):
# {
#   "hookSpecificOutput": {
#     "additionalContext": "## ONEX Conventions ..."
#   }
# }
# =============================================================================
set -euo pipefail

TOOL_INFO=$(cat)

# Build compact conventions bundle (~50 lines, high-signal)
# Phase 1: hardcoded in hook script. Future: move to versioned artifact
# (plugins/onex/conventions/onex-conventions.md) so SubagentStart does not
# drift from platform policy as conventions evolve.
CONVENTIONS="## ONEX Conventions (injected by SubagentStart)

### Architecture
- Node types: Effect/Compute/Reducer/Orchestrator
- Naming: Node<Name><Type>, Model prefix, Enum prefix, always Pydantic BaseModel
- Contracts: YAML source of truth; handlers read from contract; never hardcode topics
- Topics: onex.{cmd|evt}.{service}.{event}.v{N}
- All config from Infisical or env vars — never hardcode connection strings

### Code Standards
- Python 3.12+, uv for all commands (uv run pytest, uv run mypy, uv run ruff)
- PEP 604 unions: X | Y (not Optional[X] or Union[X, Y])
- No datetime.now() defaults, no @dataclass, no backwards compat shims
- No one-off scripts — write permanent tests instead

### Testing & Quality
- Tests: every change ships with a unit test — no exceptions
- Pre-commit hooks must pass; never use --no-verify
- mypy --strict target; ruff for linting/formatting

### Workflow
- All output written to disk (never chat-only)
- Worktrees only in /Volumes/PRO-G40/Code/omni_worktrees/ # local-path-ok
- Evidence written to .onex_state/evidence/ for verification
- Always create Linear tickets before starting work
- Always push and create PRs — never leave work uncommitted

### Safety
- Never disable safety guardrails (pre-commit, CI gates, review requirements)
- Never write to ~/.claude/ — state goes in omni_home/.onex_state/
- Two-strike diagnosis: after 2 failed fixes, write diagnosis doc before continuing"

# Emit JSON with additionalContext
echo "$TOOL_INFO" | jq --arg ctx "$CONVENTIONS" \
  '{hookSpecificOutput: {additionalContext: $ctx}}'
exit 0
