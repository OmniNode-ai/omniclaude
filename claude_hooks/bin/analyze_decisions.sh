#!/bin/bash
# Generate analytics report from AI Quality Enforcer decision logs
# Provides insights into enforcement effectiveness and user acceptance

set -euo pipefail

# Configuration
LOG_FILE="${HOME}/.claude/hooks/logs/decisions.jsonl"
TEMP_DIR=$(mktemp -d)

# Cleanup on exit
trap 'rm -rf "$TEMP_DIR"' EXIT

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if log file exists
if [[ ! -f "$LOG_FILE" ]]; then
    echo -e "${RED}Error: Decision log file not found: $LOG_FILE${NC}"
    echo "No enforcement decisions have been logged yet."
    exit 1
fi

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo -e "${RED}Error: jq is required but not installed${NC}"
    echo "Install with: brew install jq"
    exit 1
fi

# Print header
echo "========================================"
echo "AI Quality Enforcer Analytics Dashboard"
echo "========================================"
echo ""
echo -e "${BLUE}Log file: $LOG_FILE${NC}"
echo "Generated: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Total decisions
TOTAL=$(wc -l < "$LOG_FILE" | xargs)
echo -e "${GREEN}Total Decisions: $TOTAL${NC}"
echo ""

# Check if we have any data
if [[ "$TOTAL" -eq 0 ]]; then
    echo "No decisions logged yet."
    exit 0
fi

# Actions breakdown
echo "----------------------------------------"
echo "Actions Taken:"
echo "----------------------------------------"
jq -r '.action' "$LOG_FILE" | sort | uniq -c | while read -r count action; do
    percentage=$(awk "BEGIN {printf \"%.1f\", ($count/$TOTAL)*100}")
    printf "  %-20s %5d (%5.1f%%)\n" "$action:" "$count" "$percentage"
done
echo ""

# Average consensus scores by action
echo "----------------------------------------"
echo "Average Consensus Scores by Action:"
echo "----------------------------------------"
for action in auto_applied suggested skipped; do
    avg=$(jq -r "select(.action==\"$action\") | .score.consensus" "$LOG_FILE" 2>/dev/null | \
          awk '{sum+=$1; count++} END {if (count>0) printf "%.3f", sum/count; else print "N/A"}')
    if [[ "$avg" != "N/A" ]]; then
        printf "  %-20s %.3f\n" "$action:" "$avg"
    fi
done
echo ""

# User response rates
echo "----------------------------------------"
echo "User Response Rates:"
echo "----------------------------------------"
RESPONSES=$(jq -r '.user_response' "$LOG_FILE" | grep -v null | wc -l | xargs)

if [[ "$RESPONSES" -gt 0 ]]; then
    jq -r '.user_response' "$LOG_FILE" | grep -v null | sort | uniq -c | while read -r count response; do
        percentage=$(awk "BEGIN {printf \"%.1f\", ($count/$RESPONSES)*100}")
        printf "  %-20s %5d (%5.1f%%)\n" "$response:" "$count" "$percentage"
    done

    # Calculate acceptance rate
    ACCEPTED=$(jq -r 'select(.user_response=="accepted") | .user_response' "$LOG_FILE" | wc -l | xargs)
    if [[ "$RESPONSES" -gt 0 ]]; then
        ACCEPTANCE_RATE=$(awk "BEGIN {printf \"%.1f\", ($ACCEPTED/$RESPONSES)*100}")
        echo ""
        echo -e "  ${GREEN}Acceptance Rate: ${ACCEPTANCE_RATE}%${NC}"
    fi
else
    echo "  No user responses recorded yet"
fi
echo ""

# Most common violation types
echo "----------------------------------------"
echo "Top Violation Types:"
echo "----------------------------------------"
jq -r '.violation.type' "$LOG_FILE" | sort | uniq -c | sort -rn | head -10 | while read -r count type; do
    printf "  %-30s %5d\n" "$type:" "$count"
done
echo ""

# Severity distribution
echo "----------------------------------------"
echo "Violation Severity Distribution:"
echo "----------------------------------------"
jq -r '.violation.severity' "$LOG_FILE" | sort | uniq -c | while read -r count severity; do
    percentage=$(awk "BEGIN {printf \"%.1f\", ($count/$TOTAL)*100}")
    printf "  %-20s %5d (%5.1f%%)\n" "$severity:" "$count" "$percentage"
done
echo ""

# Performance metrics (if available)
echo "----------------------------------------"
echo "Performance Metrics:"
echo "----------------------------------------"
AVG_DURATION=$(jq -r 'select(.metadata.duration_ms != null) | .metadata.duration_ms' "$LOG_FILE" 2>/dev/null | \
               awk '{sum+=$1; count++} END {if (count>0) printf "%.0f", sum/count; else print "N/A"}')

CACHE_HITS=$(jq -r 'select(.metadata.cache_hit == true)' "$LOG_FILE" 2>/dev/null | wc -l | xargs)
CACHE_CHECKS=$(jq -r 'select(.metadata.cache_hit != null)' "$LOG_FILE" 2>/dev/null | wc -l | xargs)

if [[ "$AVG_DURATION" != "N/A" ]]; then
    echo "  Average Duration:    ${AVG_DURATION}ms"
fi

if [[ "$CACHE_CHECKS" -gt 0 ]]; then
    CACHE_RATE=$(awk "BEGIN {printf \"%.1f\", ($CACHE_HITS/$CACHE_CHECKS)*100}")
    echo "  Cache Hit Rate:      ${CACHE_RATE}%"
fi
echo ""

# Recent trends (last 24 hours)
echo "----------------------------------------"
echo "Recent Activity (Last 24 Hours):"
echo "----------------------------------------"
CUTOFF=$(date -u -v-24H '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%S')
RECENT=$(jq -r "select(.timestamp > \"$CUTOFF\")" "$LOG_FILE" 2>/dev/null | wc -l | xargs)

if [[ "$RECENT" -gt 0 ]]; then
    echo "  Recent decisions:    $RECENT"

    # Recent auto-applies
    RECENT_AUTO=$(jq -r "select(.timestamp > \"$CUTOFF\" and .action == \"auto_applied\")" "$LOG_FILE" 2>/dev/null | wc -l | xargs)
    echo "  Auto-applied:        $RECENT_AUTO"

    # Recent average score
    RECENT_AVG=$(jq -r "select(.timestamp > \"$CUTOFF\") | .score.consensus" "$LOG_FILE" 2>/dev/null | \
                 awk '{sum+=$1; count++} END {if (count>0) printf "%.3f", sum/count; else print "N/A"}')
    if [[ "$RECENT_AVG" != "N/A" ]]; then
        echo "  Average score:       $RECENT_AVG"
    fi
else
    echo "  No recent activity"
fi
echo ""

# Recommendations
echo "========================================"
echo "Recommendations:"
echo "========================================"

# Check if acceptance rate is low
if [[ "$RESPONSES" -gt 10 ]]; then
    if (( $(echo "$ACCEPTANCE_RATE < 70" | bc -l) )); then
        echo -e "${YELLOW}⚠ Low acceptance rate detected (<70%)${NC}"
        echo "  Consider reviewing quorum thresholds in config.yaml"
    fi
fi

# Check if many decisions are being skipped
SKIPPED=$(jq -r 'select(.action=="skipped")' "$LOG_FILE" | wc -l | xargs)
if [[ "$SKIPPED" -gt 0 ]]; then
    SKIP_RATE=$(awk "BEGIN {printf \"%.1f\", ($SKIPPED/$TOTAL)*100}")
    if (( $(echo "$SKIP_RATE > 30" | bc -l) )); then
        echo -e "${YELLOW}⚠ High skip rate (${SKIP_RATE}%)${NC}"
        echo "  Consider lowering suggest threshold in config.yaml"
    fi
fi

# Check average duration
if [[ "$AVG_DURATION" != "N/A" ]] && (( $(echo "$AVG_DURATION > 1000" | bc -l) )); then
    echo -e "${YELLOW}⚠ Average duration exceeds 1 second${NC}"
    echo "  Consider enabling caching or reducing model timeout"
fi

echo ""
echo "For detailed analysis, examine: $LOG_FILE"
echo "========================================"
