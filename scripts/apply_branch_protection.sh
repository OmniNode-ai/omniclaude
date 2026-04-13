#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# apply_branch_protection.sh
#
# Adds `review-bot/all-findings-resolved` as a required status check on main
# for all active OmniNode-ai repositories.
#
# Required: GitHub token with `repo` scope (set GH_TOKEN or use `gh auth login`)
#
# The script reads current branch protection settings first to avoid clobbering
# existing required_status_checks.strict or other fields, then PUTs the merged
# check list back.
#
# Usage:
#   bash scripts/apply_branch_protection.sh
#   bash scripts/apply_branch_protection.sh --dry-run   # print payload without applying

set -euo pipefail

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
  echo "[DRY RUN] No changes will be applied."
fi

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
NEW_CHECK="review-bot/all-findings-resolved"
NEW_CHECK_APP_ID=15368  # GitHub Actions app_id

FAILED_REPOS=()

# Python helper: reads current protection JSON from stdin, merges new check,
# and emits the full PUT payload as JSON to stdout.
MERGE_SCRIPT='
import json, sys

new_check_ctx = sys.argv[1]
new_check_app_id = int(sys.argv[2])

data = json.load(sys.stdin)

rsc = data.get("required_status_checks") or {}
checks = list(rsc.get("checks") or [])
strict = rsc.get("strict", False)

seen = {c["context"] for c in checks}
if new_check_ctx not in seen:
    checks.append({"context": new_check_ctx, "app_id": new_check_app_id})
    print(f"  ADDING: {new_check_ctx}", file=sys.stderr)
else:
    print(f"  ALREADY PRESENT: {new_check_ctx} (no-op)", file=sys.stderr)

def bool_field(d, *keys):
    """Safely extract nested bool field."""
    val = d
    for k in keys:
        if not isinstance(val, dict):
            return False
        val = val.get(k, False)
    return bool(val)

payload = {
    "required_status_checks": {
        "strict": strict,
        "checks": checks,
    },
    "enforce_admins": bool_field(data, "enforce_admins", "enabled"),
    "required_linear_history": bool_field(data, "required_linear_history", "enabled"),
    "allow_force_pushes": bool_field(data, "allow_force_pushes", "enabled"),
    "allow_deletions": bool_field(data, "allow_deletions", "enabled"),
    "required_conversation_resolution": bool_field(data, "required_conversation_resolution", "enabled"),
    "restrictions": None,
}

print(json.dumps(payload))
'

for repo in "${REPOS[@]}"; do
  echo ""
  echo "=== Processing $ORG/$repo ==="

  # Fetch current protection settings
  protection=$(gh api "/repos/$ORG/$repo/branches/main/protection" 2>&1) || {
    echo "  ERROR: Could not fetch branch protection for $repo"
    echo "  $protection"
    FAILED_REPOS+=("$repo")
    continue
  }

  # Build merged payload using the Python helper
  payload=$(echo "$protection" | python3 -c "$MERGE_SCRIPT" "$NEW_CHECK" "$NEW_CHECK_APP_ID") || {
    echo "  ERROR: Failed to build payload for $repo"
    FAILED_REPOS+=("$repo")
    continue
  }

  echo "  Payload: $payload"

  if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY RUN] Would PUT /repos/$ORG/$repo/branches/main/protection"
    continue
  fi

  result=$(echo "$payload" | gh api --method PUT \
    "/repos/$ORG/$repo/branches/main/protection" \
    --input - 2>&1) || {
    echo "  ERROR: PUT failed for $repo"
    echo "  $result"
    FAILED_REPOS+=("$repo")
    continue
  }

  echo "  SUCCESS: branch protection updated for $repo"
done

echo ""
echo "=== Summary ==="
if [[ ${#FAILED_REPOS[@]} -eq 0 ]]; then
  echo "All ${#REPOS[@]} repos updated successfully."
else
  echo "FAILED repos (${#FAILED_REPOS[@]}):"
  for r in "${FAILED_REPOS[@]}"; do
    echo "  - $r"
  done
  exit 1
fi
