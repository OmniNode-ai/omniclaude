#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# dod-pre-push-check.sh — Advisory DoD evidence validation before push [OMN-6747]
#
# Checks whether DoD evidence receipts exist for tickets referenced in the
# branch name. This is advisory (exit 0 always) to avoid blocking pushes.
# Self-hosted runner only.
#
# Usage:
#   ./scripts/dod-pre-push-check.sh              # Check current branch
#   DOD_ENFORCEMENT=hard ./scripts/dod-pre-push-check.sh  # Hard fail mode
#
# Exit codes:
#   0 — always (advisory mode, default)
#   1 — only in DOD_ENFORCEMENT=hard mode when evidence is missing

set -euo pipefail

ENFORCEMENT="${DOD_ENFORCEMENT:-advisory}"
EVIDENCE_DIR="${ONEX_STATE_DIR:-.onex_state}/evidence"
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
# Fallback for CI detached HEAD state
if [[ "$BRANCH" == "HEAD" || -z "$BRANCH" ]]; then
  BRANCH="${GITHUB_HEAD_REF:-${GITHUB_REF_NAME:-}}"
fi

# Extract ticket ID from branch name (e.g., jonahgabriel/omn-1234-description -> OMN-1234)
TICKET_ID=""
if [[ "$BRANCH" =~ [Oo][Mm][Nn]-([0-9]+) ]]; then
  TICKET_ID="OMN-${BASH_REMATCH[1]}"
fi

if [[ -z "$TICKET_ID" ]]; then
  # No ticket ID in branch name — nothing to check
  exit 0
fi

# Check for DoD evidence receipt
RECEIPT_PATH="${EVIDENCE_DIR}/${TICKET_ID}/dod_report.json"

if [[ -f "$RECEIPT_PATH" ]]; then
  # Evidence exists — check if it passed
  if command -v jq &>/dev/null; then
    FAILED=$(jq -r '.result.failed // 0' "$RECEIPT_PATH" 2>/dev/null || echo "0")
    if [[ "$FAILED" != "0" ]]; then
      echo "WARNING: DoD evidence for ${TICKET_ID} has ${FAILED} failed check(s)"
      echo "  Receipt: ${RECEIPT_PATH}"
      echo "  Run /dod-verify ${TICKET_ID} to re-check"
      if [[ "$ENFORCEMENT" == "hard" ]]; then
        exit 1
      fi
    else
      echo "DoD evidence verified for ${TICKET_ID}"
    fi
  else
    echo "DoD evidence receipt found for ${TICKET_ID} (jq not available for detailed check)"
  fi
else
  echo "WARNING: No DoD evidence receipt found for ${TICKET_ID}"
  echo "  Expected: ${RECEIPT_PATH}"
  echo "  Run /dod-verify ${TICKET_ID} to generate evidence"
  if [[ "$ENFORCEMENT" == "hard" ]]; then
    exit 1
  fi
fi

exit 0
