# Hooks Infrastructure Handoff

## Current State - ALL HOOKS WORKING

### What's Working
- **UserPromptSubmit hook** - Successfully logging events to PostgreSQL, injecting 25k+ char polymorphic-agent manifest
- **PostToolUse hook** - Processing file changes, quality enforcement ready (currently disabled)
- **SessionStart hook** - Logging session initialization events
- **PostgreSQL connection** - Via socat port forwarder to local Docker container
- **Kafka connection** - Local Redpanda at localhost:29092
- **Agent definitions** - Located at `~/.claude/agents/omniclaude/`
- **Agent tracking skills** - Routing decisions and agent actions logged to database

### Verification
Every prompt now shows in system-reminder:
```
UserPromptSubmit hook success: Event logged: <uuid>
Routing decision logged: <uuid>
Agent action logged: <uuid>
```

## Changes Made This Session

### 1. Created Agent Tracking Skills
New skills at `skills/agent-tracking/`:
- `log-routing-decision/execute_unified.py` - Logs agent selection decisions
- `log-agent-action/execute_unified.py` - Logs agent actions (tool calls, decisions, errors)

### 2. Created Database Tables
```sql
-- Agent routing decisions
CREATE TABLE agent_routing_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    correlation_id UUID,
    session_id VARCHAR(255),
    project_name VARCHAR(255),
    project_path TEXT,
    user_request TEXT,
    selected_agent VARCHAR(255) NOT NULL,
    confidence_score DECIMAL(4,3),
    selection_strategy VARCHAR(100),
    latency_ms INTEGER,
    reasoning TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Agent actions
CREATE TABLE agent_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    correlation_id UUID,
    session_id VARCHAR(255),
    agent_name VARCHAR(255) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    action_name VARCHAR(255) NOT NULL,
    details JSONB DEFAULT '{}',
    project_name VARCHAR(255),
    project_path TEXT,
    working_directory TEXT,
    duration_ms INTEGER,
    success BOOLEAN,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### 3. Fixed Broken Imports in skills/_shared/
All relative imports fixed:
- `docker_helper.py` - `from .common_utils import`
- `kafka_helper.py` - `from .kafka_types import`, `from .common_utils import`
- `qdrant_helper.py` - `from .common_utils import`
- `test_qdrant_empty_collections.py` - `from .qdrant_helper import`
- `test_qdrant_https_support.py` - 6x `from .qdrant_helper import`
- `test_qdrant_ssrf_protection.py` - `from .qdrant_helper import`

### 4. Created PostToolUse Hook Config
Created `claude/hooks/config.yaml`:
```yaml
autofix:
  enabled: false
pattern_tracking:
  enabled: false
  fail_gracefully: true
naming_validation:
  enabled: false
quorum:
  enabled: false
```

### 5. Removed cc-notifier Hooks
Removed failing third-party hooks from `~/.claude/settings.json`:
- SessionStart: cc-notifier init
- Stop: cc-notifier notify
- Notification: cc-notifier notify
- SessionEnd: cc-notifier cleanup

### 6. Config Settings Cleanup
- Marked legacy archon URLs as deprecated (kept for backward compatibility)
- Removed hardcoded infrastructure IPs from defaults
- `kafka_bootstrap_servers` now requires explicit configuration

## Environment Configuration

### Required in `.env`
```bash
# PostgreSQL (via socat forwarder)
POSTGRES_HOST=localhost
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<your_password>

# Kafka (local Redpanda)
KAFKA_BOOTSTRAP_SERVERS=localhost:29092

# Agent definitions
AGENT_REGISTRY_PATH=/Users/jonah/Code/omniclaude/agents/definitions/agent-registry.yaml
AGENT_DEFINITIONS_PATH=/Users/jonah/Code/omniclaude/agents/definitions
```

### Hooks Configuration (`~/.claude/settings.json`)
```json
{
  "hooks": {
    "UserPromptSubmit": [{
      "hooks": [{
        "type": "command",
        "command": "/Users/jonah/Code/omniclaude/claude/hooks/user-prompt-submit.sh",
        "timeout": 10
      }]
    }],
    "PostToolUse": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "/Users/jonah/Code/omniclaude/claude/hooks/post-tool-use.sh",
        "timeout": 5
      }]
    }],
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "/Users/jonah/Code/omniclaude/claude/hooks/session-start.sh",
        "timeout": 5
      }]
    }]
  }
}
```

## Quick Test Commands

```bash
# Test skills
source .env && poetry run python3 skills/agent-tracking/log-routing-decision/execute_unified.py \
    --agent "test-agent" --confidence 0.85 --strategy "test" --latency-ms 42 \
    --user-request "Test" --project-name "test" --correlation-id "00000000-0000-0000-0000-000000000001"

# Check database
docker exec omninode-bridge-postgres psql -U postgres -d omninode_bridge \
    -c "SELECT COUNT(*) FROM agent_routing_decisions;"
docker exec omninode-bridge-postgres psql -U postgres -d omninode_bridge \
    -c "SELECT COUNT(*) FROM agent_actions;"

# Check hook logs
tail -20 claude/hooks/logs/hook-enhanced.log
tail -20 claude/hooks/logs/hook-session-start.log
tail -20 claude/hooks/logs/hook-post-tool-use.log

# Restart socat if needed
docker run -d --rm --name postgres-forward --network omninode-bridge-network \
    -p 5436:5432 alpine/socat tcp-listen:5432,fork,reuseaddr tcp-connect:postgres:5432
```

## Files Modified This Session

### New Files
- `skills/agent-tracking/log-routing-decision/execute_unified.py`
- `skills/agent-tracking/log-agent-action/execute_unified.py`
- `claude/hooks/config.yaml`

### Modified Files
- `config/settings.py` - Legacy URL fields marked deprecated, kafka default removed
- `skills/_shared/docker_helper.py` - Fixed relative import
- `skills/_shared/kafka_helper.py` - Fixed relative imports (2)
- `skills/_shared/qdrant_helper.py` - Fixed relative import
- `skills/_shared/test_qdrant_empty_collections.py` - Fixed relative import
- `skills/_shared/test_qdrant_https_support.py` - Fixed relative imports (6)
- `skills/_shared/test_qdrant_ssrf_protection.py` - Fixed relative import
- `~/.claude/settings.json` - Removed cc-notifier hooks

## Known Issues / Future Work

1. **Socat port forwarder** - Dies on restart. Consider adding to docker-compose or systemd
2. **Legacy archon URLs** - Still referenced by some code, kept for backward compatibility
3. **PostToolUse features** - Auto-fix, pattern tracking, quorum disabled (enable in config.yaml when ready)

## Architecture Overview

```
User Prompt
    │
    ▼
┌─────────────────────────────────────┐
│  user-prompt-submit.sh              │
│  - Routes via Kafka                 │
│  - Loads agent YAML (25k+ chars)    │
│  - Logs routing decision            │
│  - Logs agent action                │
│  - Logs to hook_events table        │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  Claude Code + Polymorphic Agent    │
│  - Manifest injected into context   │
│  - Full agent capabilities enabled  │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  post-tool-use.sh                   │
│  - Processes file changes           │
│  - Quality enforcement (disabled)   │
└─────────────────────────────────────┘
```

---
**Last Updated**: 2025-12-02
**Status**: All hooks operational
