#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Verifier Role Guard (OMN-8925)
#
# Blocks Agent() dispatch from agents that are designated as verifiers
# (is_verifier: true in their YAML config). Verifiers read and report;
# they must not spawn further implementation agents.
#
# Fail-safe: missing or unreadable YAML = BLOCK (not pass-through).
# This prevents a compromised or misconfigured agent from self-exempting.
#
# Pass conditions (exit 0):
#   - tool_name is not "Agent"
#   - CLAUDE_AGENT_ID is unset or empty (not an agent context)
#   - Agent YAML config not found for CLAUDE_AGENT_ID (fail-safe: BLOCK, not pass)
#   - is_verifier field is false or absent in YAML
#   - VERIFIER_ROLE_GUARD_DISABLED=1 kill switch
#
# Block condition (exit 2, permissionDenied):
#   - is_verifier: true in YAML config for this agent
#   - YAML not found for this agent_id (fail-safe)
#
# Hook registration: hooks.json PreToolUse, matcher "^Agent$"
# Ticket: OMN-8925

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

cd "$HOME" 2>/dev/null || cd /tmp || true

_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" || { echo "FATAL: ONEX_STATE_DIR not set" >&2; exit 1; }
LOG_FILE="${ONEX_HOOK_LOG}"

mkdir -p "$(dirname "$LOG_FILE")"

# Kill switch
if [[ "${VERIFIER_ROLE_GUARD_DISABLED:-0}" == "1" ]]; then
    cat
    exit 0
fi

TOOL_INFO=$(cat)

# Fast path: only care about Agent tool
TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null) || {
    echo "$TOOL_INFO"
    exit 0
}

if [[ "$TOOL_NAME" != "Agent" ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

# Not in an agent context — pass through
AGENT_ID="${CLAUDE_AGENT_ID:-}"
if [[ -z "$AGENT_ID" ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

# Locate Python
source "${HOOKS_DIR}/scripts/common.sh"

# Look up the agent's YAML config and check is_verifier
AGENTS_DIR="${PLUGIN_ROOT}/agents/configs"

set +e
VERDICT=$(echo "$AGENT_ID" | \
    $PYTHON_CMD -c "
import sys
import os
import yaml  # type: ignore[import-untyped]
from pathlib import Path

agent_id = sys.stdin.read().strip()
agents_dir = Path('${AGENTS_DIR}')

# Find the YAML file for this agent — match by agent_identity.name or filename
yaml_file = agents_dir / f'{agent_id}.yaml'
if not yaml_file.exists():
    # Try searching by agent_identity.name inside all YAMLs
    yaml_file = None
    for f in agents_dir.glob('*.yaml'):
        try:
            data = yaml.safe_load(f.read_text())
            if isinstance(data, dict):
                identity = data.get('agent_identity', {})
                if isinstance(identity, dict) and identity.get('name') == agent_id:
                    yaml_file = f
                    break
        except Exception:
            pass

if yaml_file is None:
    # Fail-safe: YAML not found = BLOCK
    print('BLOCK:yaml_not_found')
    sys.exit(0)

try:
    data = yaml.safe_load(yaml_file.read_text())
    if not isinstance(data, dict):
        print('BLOCK:invalid_yaml')
        sys.exit(0)
    is_verifier = data.get('is_verifier', False)
    if is_verifier:
        print('BLOCK:is_verifier')
    else:
        print('PASS')
except Exception as e:
    print(f'BLOCK:error:{e}')
" 2>>"$LOG_FILE")
EXIT_CODE=$?
set -e

if [[ $EXIT_CODE -ne 0 ]] || [[ -z "$VERDICT" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] guard check failed (exit=$EXIT_CODE); failing safe (BLOCK)" >> "$LOG_FILE"
    printf '{"type":"permissionDenied","message":"Verifier role guard: check failed (fail-safe block)"}'
    exit 2
fi

if [[ "$VERDICT" == "PASS" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] PASS for agent=${AGENT_ID}" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi

# BLOCK
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] BLOCKED agent=${AGENT_ID} reason=${VERDICT}" >> "$LOG_FILE"
printf '{"type":"permissionDenied","message":"Verifier role guard: %s may not dispatch Agent() — is_verifier=true agents are read-only (OMN-8925)"}' "$AGENT_ID"
exit 2
