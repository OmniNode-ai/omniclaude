#!/bin/bash
# Quick pattern statistics check

docker exec -i archon-intelligence-1 psql -U postgres -d omninode_bridge << 'EOF'
-- Last 24 hours summary
SELECT
    DATE_TRUNC('hour', created_at) as hour,
    COUNT(*) as patterns_created,
    COUNT(DISTINCT session_id) as sessions
FROM pattern_lineage_nodes
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour DESC;

-- Top languages tracked
SELECT
    language,
    COUNT(*) as count
FROM pattern_lineage_nodes
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY language
ORDER BY count DESC;
EOF
