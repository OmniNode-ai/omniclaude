#!/bin/bash
# headless-merge-sweep.sh — Scan repos for mergeable PRs and auto-merge
#
# Usage:
#   ./scripts/headless-merge-sweep.sh              # auto-merge eligible PRs (default)
#   ./scripts/headless-merge-sweep.sh --report-only # just list eligible PRs, don't merge
#
# Requires: claude CLI, gh CLI (authenticated), ANTHROPIC_API_KEY
set -euo pipefail

export ONEX_RUN_ID="sweep-$(date +%s)"
export ONEX_UNSAFE_ALLOW_EDITS=1

REPORT_DIR="${HOME}/.claude/sweep-reports"
mkdir -p "$REPORT_DIR"

REPORT_FILE="${REPORT_DIR}/$(date +%Y-%m-%d)-sweep.md"

# Default: auto-merge. Pass --report-only to just list eligible PRs.
MODE="auto-merge"
[[ "${1:-}" == "--report-only" ]] && MODE="report-only"

echo "Running merge-sweep in ${MODE} mode..."
echo "Report will be saved to: ${REPORT_FILE}"

claude -p "Run merge-sweep in ${MODE} mode: scan all OmniNode-ai repos for open PRs with passing CI. If auto-merge, enable auto-merge on eligible ones (passing CI, approved, no conflicts). If report-only, list eligible PRs with their CI status, review status, and mergeable state. Report results as a markdown summary with counts." \
  --allowedTools "Bash,Read,Glob,Grep,mcp__linear-server__*" \
  > "${REPORT_FILE}" 2>&1

echo "Sweep complete. Report saved to: ${REPORT_FILE}"
