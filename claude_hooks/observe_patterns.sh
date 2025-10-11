#!/bin/bash
# Passive pattern observation - run in background

INTERVAL=300  # 5 minutes
LOG_FILE="/Users/jonah/.claude/hooks/logs/pattern-observation.log"

# Create log directory if it doesn't exist
mkdir -p "$(dirname "$LOG_FILE")"

while true; do
    echo "===== Pattern Observation: $(date) =====" >> "$LOG_FILE"

    # Count patterns in last 5 minutes
    docker exec -i archon-intelligence-1 psql -U postgres -d omninode_bridge << 'EOF' >> "$LOG_FILE" 2>&1
SELECT
    COUNT(*) as total_patterns,
    COUNT(DISTINCT session_id) as unique_sessions,
    tool_name,
    language
FROM pattern_lineage_nodes
WHERE created_at > NOW() - INTERVAL '5 minutes'
GROUP BY tool_name, language;
EOF

    sleep $INTERVAL
done
