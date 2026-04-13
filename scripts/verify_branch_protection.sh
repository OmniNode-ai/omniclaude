#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# verify_branch_protection.sh
#
# Verifies that `review-bot/all-findings-resolved` is present as a required
# status check on main for all active OmniNode-ai repositories.
#
# Required: GitHub token with `repo` scope (set GH_TOKEN or use `gh auth login`)
#
# Exits 0 if all repos have the check present.
# Exits 1 if any repo is missing the check (lists failures).
#
# Usage:
#   bash scripts/verify_branch_protection.sh

set -euo pipefail

# Canonical set of active repos (matches omni_home registry)
REPOS=(
  omniclaude
  omnimarket
  omnibase_infra
  omnibase_core
  onex_change_control
  omnibase_spi
  omnibase_compat
  omnidash
  omnimemory
  omniintelligence
  omninode_infra
)

ORG="OmniNode-ai"
REQUIRED_CHECK="review-bot/all-findings-resolved"

MISSING_REPOS=()
ERROR_REPOS=()

for repo in "${REPOS[@]}"; do
  echo -n "Checking $ORG/$repo ... "

  checks=$(gh api "/repos/$ORG/$repo/branches/main/protection" \
    --jq '.required_status_checks.checks // [] | .[].context' 2>&1) || {
    echo "ERROR (could not fetch protection)"
    ERROR_REPOS+=("$repo")
    continue
  }

  if echo "$checks" | grep -qF "$REQUIRED_CHECK"; then
    echo "PRESENT"
  else
    echo "MISSING"
    MISSING_REPOS+=("$repo")
    echo "  Current checks:"
    echo "$checks" | sed 's/^/    - /'
  fi
done

echo ""
echo "=== Verification Summary ==="

if [[ ${#ERROR_REPOS[@]} -gt 0 ]]; then
  echo "ERROR repos (${#ERROR_REPOS[@]} — could not fetch protection):"
  for r in "${ERROR_REPOS[@]}"; do
    echo "  - $r"
  done
fi

if [[ ${#MISSING_REPOS[@]} -gt 0 ]]; then
  echo "MISSING '$REQUIRED_CHECK' on ${#MISSING_REPOS[@]} repo(s):"
  for r in "${MISSING_REPOS[@]}"; do
    echo "  - $r"
  done
  exit 1
fi

if [[ ${#ERROR_REPOS[@]} -eq 0 && ${#MISSING_REPOS[@]} -eq 0 ]]; then
  echo "PASS: '$REQUIRED_CHECK' is present on all ${#REPOS[@]} repos."
  exit 0
fi

exit 1
