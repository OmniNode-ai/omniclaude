#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# file-stall-tickets.sh — file Linear tickets for PR stall events [OMN-9406]
#
# Reads a JSON array of stall events from stdin (produced by run-stall-detector.py),
# and for each event files a Linear ticket tagged "auto-stall-detected" unless an
# open ticket for the same repo#pr already exists.
#
# Requires: LINEAR_API_KEY env var. If absent, logs and exits 0 (fail-open).
# Requires: LINEAR_TEAM_ID env var (or falls back to querying the API once).
#
# Input (stdin): JSON array of objects with keys:
#   pr_number, repo, stall_count, blocking_reason, head_sha,
#   first_seen_at, last_seen_at
#
# Usage (from cron-merge-sweep.sh):
#   uv run python scripts/lib/run-stall-detector.py | bash scripts/lib/file-stall-tickets.sh
#
# [OMN-9406]

set -euo pipefail

_stall_log() {
  echo "[stall-tickets] $1" >&2
}

log() {
  _stall_log "$1"
}

# ---------------------------------------------------------------------------
# Guard: require LINEAR_API_KEY
# ---------------------------------------------------------------------------

if [[ -z "${LINEAR_API_KEY:-}" ]]; then
  log "LINEAR_API_KEY not set — skipping stall ticket filing (fail-open)"
  # Drain stdin so the pipeline doesn't hang.
  cat > /dev/null
  exit 0
fi

# ---------------------------------------------------------------------------
# Read stall events from stdin
# ---------------------------------------------------------------------------

STALL_JSON="$(cat)"

# Empty or null array → nothing to do.
if [[ -z "${STALL_JSON}" ]] || [[ "${STALL_JSON}" == "[]" ]] || [[ "${STALL_JSON}" == "null" ]]; then
  log "no stall events — nothing to file"
  exit 0
fi

event_count="$(echo "${STALL_JSON}" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)"
if [[ "${event_count}" -eq 0 ]]; then
  log "no stall events — nothing to file"
  exit 0
fi

log "${event_count} stall event(s) detected"

# ---------------------------------------------------------------------------
# Resolve Linear team ID
# ---------------------------------------------------------------------------

_linear_api() {
  local query="$1"
  curl -fsS \
    -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: ${LINEAR_API_KEY}" \
    --data "{\"query\": $(echo "${query}" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))")}" \
    "https://api.linear.app/graphql"
}

# Accepts a pre-built JSON body (query + variables) — used where shell vars must not
# be interpolated directly into the GraphQL string.
_linear_api_json() {
  local body="$1"
  curl -fsS \
    -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: ${LINEAR_API_KEY}" \
    --data "${body}" \
    "https://api.linear.app/graphql"
}

TEAM_ID="${LINEAR_TEAM_ID:-}"
if [[ -z "${TEAM_ID}" ]]; then
  team_resp="$(_linear_api '{ teams { nodes { id name } } }' 2>/dev/null || true)"
  TEAM_ID="$(echo "${team_resp}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
teams = d.get('data', {}).get('teams', {}).get('nodes', [])
# Pick the first team that looks like Omninode
for t in teams:
    print(t['id'])
    break
" 2>/dev/null || true)"
fi

if [[ -z "${TEAM_ID}" ]]; then
  log "WARN: could not resolve Linear team ID — skipping ticket filing"
  exit 0
fi

# ---------------------------------------------------------------------------
# File one ticket per stall event (idempotent: skip if open ticket exists)
# ---------------------------------------------------------------------------

FILED=0
SKIPPED=0

file_one_ticket() {
  local pr_number="$1"
  local repo="$2"
  local stall_count="$3"
  local blocking_reason="$4"
  local head_sha="$5"
  local last_seen_at="$6"

  local pr_key="${repo}#${pr_number}"
  local title="[auto-stall-detected] Stalled PR: ${pr_key} (${stall_count} consecutive identical snapshots)"

  # Check for existing open ticket with same title prefix.
  local search_resp
  search_resp="$(_linear_api "{ issueSearch(query: \"auto-stall-detected ${pr_key}\", filter: {state: {type: {nin: [\"completed\", \"cancelled\"]}}}) { nodes { id title } } }" 2>/dev/null || true)"

  local existing_count
  # shellcheck disable=SC2030
  existing_count="$(PR_KEY="${pr_key}" python3 -c "
import json, sys, os
pr_key = os.environ.get('PR_KEY', '')
try:
    d = json.load(sys.stdin)
    nodes = d.get('data', {}).get('issueSearch', {}).get('nodes', [])
    matches = [n for n in nodes if pr_key in n.get('title', '')]
    print(len(matches))
except Exception:
    print(0)
" <<< "${search_resp}" 2>/dev/null || echo 0)"

  if [[ "${existing_count}" -gt 0 ]]; then
    log "SKIP ${pr_key} — open auto-stall-detected ticket already exists"
    SKIPPED=$((SKIPPED + 1))
    return
  fi

  local description
  description="## Auto-detected PR stall [OMN-9406]

**PR:** https://github.com/${repo}/pull/${pr_number}
**Repo:** ${repo}
**PR number:** ${pr_number}
**Stall count:** ${stall_count} consecutive identical snapshots
**Blocking reason:** ${blocking_reason}
**HEAD SHA:** ${head_sha:-unknown}
**Last seen:** ${last_seen_at}

This ticket was automatically filed by the cron-merge-sweep stall detector.
The PR's shape (mergeable, merge_state_status, review_decision, required_checks_pass, head_sha)
was identical across ${stall_count} consecutive 5-minute snapshots while in a blocked state.

**Suggested actions:**
- Check CI: \`gh pr checks ${pr_number} --repo ${repo}\`
- Check for CodeRabbit unresolved threads
- Rebase if conflicted: \`gh pr view ${pr_number} --repo ${repo} --json mergeable\`"

  # Build request body via Python so title/description are properly JSON-escaped,
  # then pass the serialized body to _linear_api_json (curl-based) for dispatch.
  local create_body
  # shellcheck disable=SC2031
  create_body="$(TEAM_ID="${TEAM_ID}" ISSUE_TITLE="${title}" ISSUE_DESC="${description}" python3 -c "
import json, os, sys
team_id = os.environ.get('TEAM_ID', '')
issue_title = os.environ.get('ISSUE_TITLE', '')
desc    = os.environ.get('ISSUE_DESC', '')
body = {
    'query': 'mutation CreateIssue(\$input: IssueCreateInput!) { issueCreate(input: \$input) { issue { id identifier url } } }',
    'variables': {'input': {'teamId': team_id, 'title': issue_title, 'description': desc, 'labelNames': ['auto-stall-detected']}},
}
print(json.dumps(body))
" 2>/dev/null || echo "")"

  local create_resp
  create_resp="$(_linear_api_json "${create_body}" 2>/dev/null || true)"

  local issue_id
  issue_id="$(echo "${create_resp}" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    issue = d.get('data', {}).get('issueCreate', {}).get('issue', {})
    print(issue.get('identifier', ''))
except Exception:
    print('')
" 2>/dev/null || true)"

  if [[ -n "${issue_id}" ]]; then
    log "FILED ${issue_id}: ${title}"
    FILED=$((FILED + 1))
  else
    log "WARN: ticket creation failed for ${pr_key} — response: ${create_resp:0:200}"
  fi
}

# Iterate stall events via python3 (avoids bash JSON parsing complexity).
while IFS= read -r event_json; do
  pr_number="$(echo "${event_json}" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d['pr_number'])")"
  repo="$(echo "${event_json}" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d['repo'])")"
  stall_count="$(echo "${event_json}" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d['stall_count'])")"
  blocking_reason="$(echo "${event_json}" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d['blocking_reason'])")"
  head_sha="$(echo "${event_json}" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('head_sha') or '')")"
  last_seen_at="$(echo "${event_json}" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d['last_seen_at'])")"

  file_one_ticket "${pr_number}" "${repo}" "${stall_count}" "${blocking_reason}" "${head_sha}" "${last_seen_at}"
done < <(echo "${STALL_JSON}" | python3 -c "
import json, sys
events = json.load(sys.stdin)
for ev in events:
    print(json.dumps(ev))
")

log "stall ticket summary: filed=${FILED}, skipped=${SKIPPED}"
exit 0
