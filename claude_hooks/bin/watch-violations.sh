#!/bin/bash
# Watch violations in real-time
#
# Usage: ./bin/watch-violations.sh
#
# This script monitors the violations.log file and displays new violations
# as they occur. Useful for tracking naming convention issues during development.

VIOLATIONS_LOG="$HOME/.claude/hooks/logs/violations.log"

# Ensure log file exists
if [ ! -f "$VIOLATIONS_LOG" ]; then
    echo "Violations log not found at: $VIOLATIONS_LOG"
    echo "No violations have been logged yet, or enforcement is not enabled."
    exit 1
fi

echo "======================================================================"
echo "Watching Violations Log"
echo "======================================================================"
echo "File: $VIOLATIONS_LOG"
echo ""
echo "Press Ctrl+C to stop watching"
echo "======================================================================"
echo ""

# Tail the violations log
tail -f "$VIOLATIONS_LOG"