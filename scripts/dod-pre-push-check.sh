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
  # Evidence exists — verify ModelDodReceipt schema (OMN-9792, OMN-10540).
  # Fail-closed semantics: only `status == "PASS"` permits success in hard mode.
  if command -v jq &>/dev/null; then
    STATUS=$(jq -r '.status // ""' "$RECEIPT_PATH" 2>/dev/null || echo "")
    if [[ -z "$STATUS" ]]; then
      # Detect legacy pre-OMN-9792 receipts and fail loudly so they get
      # regenerated rather than silently bypassing the gate.
      LEGACY_FAILED=$(jq -r '.result.failed // empty' "$RECEIPT_PATH" 2>/dev/null || echo "")
      if [[ -n "$LEGACY_FAILED" ]]; then
        echo "WARNING: DoD evidence for ${TICKET_ID} uses pre-OMN-9792 schema (legacy 'result.failed')"
        echo "  Receipt: ${RECEIPT_PATH}"
        echo "  Run /dod-verify ${TICKET_ID} to regenerate as ModelDodReceipt"
      else
        echo "WARNING: DoD evidence for ${TICKET_ID} is missing required 'status' field"
        echo "  Receipt: ${RECEIPT_PATH}"
        echo "  Run /dod-verify ${TICKET_ID} to re-check"
      fi
      if [[ "$ENFORCEMENT" == "hard" ]]; then
        exit 1
      fi
    elif [[ "$STATUS" == "PASS" ]]; then
      echo "DoD evidence verified for ${TICKET_ID} (status=PASS)"
    else
      echo "WARNING: DoD evidence for ${TICKET_ID} has status=${STATUS}, only 'PASS' permits push"
      echo "  Receipt: ${RECEIPT_PATH}"
      echo "  Run /dod-verify ${TICKET_ID} to re-check"
      if [[ "$ENFORCEMENT" == "hard" ]]; then
        exit 1
      fi
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
