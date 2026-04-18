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

# --- Sub-agent session marker [OMN-9140] ---
# Task()-spawned sub-agents get a distinct session_id. Record it so the
# delegation counter (post-tool-delegation-counter.sh) can short-circuit pass —
# sub-agents cannot call Agent() to satisfy the delegation rule and would
# otherwise recursive-block after a handful of tool calls.
if command -v jq >/dev/null 2>&1; then
    _SA_SESSION_ID=$(printf '%s' "$TOOL_INFO" | jq -r '.session_id // .sessionId // ""' 2>/dev/null || echo "")
    _SA_PARENT_ID=$(printf '%s' "$TOOL_INFO" | jq -r '.parent_session_id // .parentSessionId // ""' 2>/dev/null || echo "")
    if [[ -n "$_SA_SESSION_ID" ]]; then
        _SA_MARKER_DIR="${ONEX_STATE_DIR:-${HOME}/.onex_state}/hooks/subagent-sessions"
        mkdir -p "$_SA_MARKER_DIR" 2>/dev/null || true
        printf '{"session_id":"%s","parent_session_id":"%s","timestamp":"%s"}\n' \
            "$_SA_SESSION_ID" "$_SA_PARENT_ID" "$(date -u +%FT%TZ)" \
            > "${_SA_MARKER_DIR}/${_SA_SESSION_ID}.marker" 2>/dev/null || true
        unset _SA_MARKER_DIR
    fi
    unset _SA_SESSION_ID _SA_PARENT_ID
fi

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
- Worktrees only in /Volumes/PRO-G40/Code/omni_worktrees/ # local-path-ok: worktree convention documentation
- Evidence written to .onex_state/evidence/ for verification
- Always create Linear tickets before starting work
- Always push and create PRs — never leave work uncommitted

### Safety
- Never disable safety guardrails (pre-commit, CI gates, review requirements)
- Never write to ~/.claude/ — state goes in omni_home/.onex_state/
- Two-strike diagnosis: after 2 failed fixes, write diagnosis doc before continuing"

# Emit JSON with additionalContext
echo "$TOOL_INFO" | jq --arg ctx "$CONVENTIONS" \
  '{hookSpecificOutput: {hookEventName: "SubagentStart", additionalContext: $ctx}}'
exit 0
