#!/bin/bash
# Show today's violation summary
#
# Usage: ./bin/violations-summary.sh
#
# This script displays the violations summary including:
# - Total violations today
# - Files with violations
# - Most common suggestions
#
# Requires jq for JSON formatting (install with: brew install jq)

VIOLATIONS_SUMMARY="$HOME/.claude/hooks/logs/violations_summary.json"

# Check if summary exists
if [ ! -f "$VIOLATIONS_SUMMARY" ]; then
    echo "Violations summary not found at: $VIOLATIONS_SUMMARY"
    echo "No violations have been logged yet, or enforcement is not enabled."
    exit 1
fi

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "jq is not installed. Install with: brew install jq"
    echo ""
    echo "Showing raw JSON instead:"
    echo "======================================================================"
    cat "$VIOLATIONS_SUMMARY"
    exit 0
fi

echo "======================================================================"
echo "Violations Summary"
echo "======================================================================"
echo ""

# Display formatted summary
jq -r '
  "Last Updated: \(.last_updated)",
  "Total Violations Today: \(.total_violations_today)",
  "",
  "Recent Files with Violations:",
  "------------------------------",
  (.files_with_violations[-10:] | reverse | .[] |
    "  • \(.path) - \(.violations) violations at \(.timestamp)"
  ),
  "",
  "Top Suggestions:",
  "-----------------",
  (
    [.files_with_violations[].suggestions[]] |
    group_by(.) |
    map({name: .[0], count: length}) |
    sort_by(.count) | reverse |
    .[:10] |
    .[] |
    "  • \(.name) (\(.count)x)"
  )
' "$VIOLATIONS_SUMMARY"

echo ""
echo "======================================================================"
echo "Full summary: $VIOLATIONS_SUMMARY"
echo "Watch live: ./bin/watch-violations.sh"
echo "======================================================================"