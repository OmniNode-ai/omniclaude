# OmniClaude Core Plugin

Core infrastructure plugin for Claude Code providing intelligent agent routing, manifest injection, quality enforcement, and observability.

## Overview

The `omniclaude-core` plugin enhances Claude Code with:

- **Intelligent Agent Routing** - Kafka-based routing to specialized agents with confidence scoring
- **Manifest Injection** - Dynamic context injection for enhanced agent capabilities
- **Quality Enforcement** - Pre/post tool use validation with auto-correction
- **Session Tracking** - Complete session lifecycle management with correlation IDs
- **Observability** - Event logging to PostgreSQL and Kafka for debugging and analytics

## Installation

### Prerequisites

- Python 3.10+
- Required Python packages:
  - `kafka-python`
  - `aiokafka`
  - `psycopg2-binary`
  - `pydantic`

### Setup

1. **Install the plugin** (when Claude Code plugin system is available):
   ```bash
   claude plugins install ./plugins/omniclaude-core
   ```

2. **Configure environment variables** in your project's `.env`:
   ```bash
   # Required
   KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092
   POSTGRES_HOST=192.168.86.200
   POSTGRES_PORT=5436
   POSTGRES_DATABASE=omninode_bridge
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=your_password

   # Optional
   ARCHON_INTELLIGENCE_URL=http://localhost:8053
   ENABLE_HOOK_DATABASE_LOGGING=false
   ```

3. **Install Python dependencies**:
   ```bash
   cd plugins/omniclaude-core
   python3 -m venv lib/.venv
   source lib/.venv/bin/activate
   pip install kafka-python aiokafka psycopg2-binary pydantic
   ```

## Plugin Structure

```
omniclaude-core/
├── .claude-plugin/
│   └── plugin.json          # Plugin manifest
├── hooks/
│   ├── hooks.json            # Hook registration
│   ├── lib/                  # Hook utility modules
│   │   ├── agent_detector.py
│   │   ├── correlation_manager.py
│   │   ├── hook_event_logger.py
│   │   ├── route_via_events_wrapper.py
│   │   ├── simple_agent_loader.py
│   │   └── ... (16 modules)
│   ├── logs/                 # Hook execution logs
│   └── scripts/              # Hook implementations
│       ├── user-prompt-submit.sh
│       ├── session-start.sh
│       ├── session-end.sh
│       ├── pre-tool-use-quality.sh
│       ├── post-tool-use-quality.sh
│       └── stop.sh
├── lib/                      # Shared Python libraries
│   ├── core/                 # Core functionality
│   │   ├── action_logger.py
│   │   ├── agent_router.py
│   │   ├── manifest_injector.py
│   │   ├── routing_event_client.py
│   │   └── ... (12 modules)
│   ├── utils/                # Utilities
│   │   ├── error_handling.py
│   │   ├── health_checks.py
│   │   ├── quality_enforcer.py
│   │   └── ... (11 modules)
│   ├── models/               # Data models
│   └── clients/              # API clients
└── README.md
```

## Hooks

### UserPromptSubmit

**Triggers on**: Every user prompt submission

**Functionality**:
- Detects automated workflow triggers
- Routes prompts to optimal agents via Kafka event bus
- Loads agent YAML definitions for polymorphic transformation
- Injects agent context into the prompt
- Publishes intelligence requests for RAG-enhanced responses

**Performance**: Target <2000ms, typical <500ms

### SessionStart

**Triggers on**: Session initialization

**Functionality**:
- Captures session metadata (ID, project path, git branch)
- Logs session start to database
- Initializes correlation tracking

**Performance**: Target <50ms

### SessionEnd

**Triggers on**: Session completion

**Functionality**:
- Aggregates session statistics
- Logs session completion with duration
- Cleans up correlation state

**Performance**: Target <50ms

### PreToolUse (Quality)

**Triggers on**: Write, Edit, MultiEdit operations

**Functionality**:
- Validates code quality before file writes
- Checks naming conventions (ONEX/PEP 8)
- Can block operations with violations
- Logs tool call start events

**Performance**: Target <500ms

### PostToolUse (Quality)

**Triggers on**: Write, Edit, MultiEdit, Bash, Read, Glob, Grep operations

**Functionality**:
- Auto-fixes naming convention violations
- Collects quality metrics
- Logs tool execution to agent_actions table
- Detects and reports tool errors

**Performance**: Target <500ms

### Stop

**Triggers on**: Response completion

**Functionality**:
- Logs response completion intelligence
- Displays agent execution summary banner
- Clears correlation state

**Performance**: Target <30ms

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | Yes | `192.168.86.200:29092` | Kafka broker addresses |
| `POSTGRES_HOST` | Yes | - | PostgreSQL host |
| `POSTGRES_PORT` | Yes | - | PostgreSQL port |
| `POSTGRES_DATABASE` | Yes | - | Database name |
| `POSTGRES_USER` | Yes | - | Database user |
| `POSTGRES_PASSWORD` | Yes | - | Database password |
| `ARCHON_INTELLIGENCE_URL` | No | `http://localhost:8053` | Intelligence service URL |
| `ENABLE_HOOK_DATABASE_LOGGING` | No | `false` | Enable detailed DB logging |

### Portable Paths

All hook scripts use the `${CLAUDE_PLUGIN_ROOT}` variable for portable paths:

```bash
# Instead of hardcoded paths:
# /Users/jonah/Code/omniclaude/claude/hooks/lib/

# Use portable paths:
${CLAUDE_PLUGIN_ROOT}/hooks/lib/
```

## Troubleshooting

### Log Files

Hook logs are stored in `hooks/logs/`:

| Log File | Contents |
|----------|----------|
| `hook-enhanced.log` | UserPromptSubmit activity |
| `hook-session-start.log` | SessionStart activity |
| `hook-session-end.log` | SessionEnd activity |
| `quality_enforcer.log` | PreToolUse quality checks |
| `post-tool-use.log` | PostToolUse activity |
| `stop.log` | Stop hook activity |

### Common Issues

| Issue | Solution |
|-------|----------|
| Hooks not firing | Verify plugin is installed and enabled |
| Import errors | Check Python venv has required packages |
| Kafka errors | Verify `KAFKA_BOOTSTRAP_SERVERS` is correct |
| Database errors | Check `POSTGRES_*` variables in `.env` |
| Permission denied | Run `chmod +x hooks/scripts/*.sh` |

### Debug Commands

```bash
# Check hook logs
tail -f hooks/logs/hook-enhanced.log

# Verify Python environment
lib/.venv/bin/python3 -c "import kafka; import psycopg2; print('OK')"

# Test routing
python3 hooks/lib/route_via_events_wrapper.py "test prompt" "test-id"
```

## Architecture

### Event Flow

```
User Prompt
    │
    ▼
UserPromptSubmit Hook
    │
    ├──► Kafka Routing Request
    │         │
    │         ▼
    │    Router Consumer
    │         │
    │         ▼
    │    Routing Response
    │
    ├──► Agent YAML Loading
    │
    ├──► Intelligence Requests (async)
    │
    ▼
Context Injection ──► Claude Response
    │
    ▼
PostToolUse Hooks ──► Quality Enforcement
    │
    ▼
Stop Hook ──► Summary & Cleanup
```

### Correlation Tracking

Every request is tracked with a correlation ID that propagates through:
- Agent routing decisions
- Manifest injections
- Tool executions
- Error events

Query correlation data:
```sql
SELECT * FROM agent_routing_decisions
WHERE correlation_id = 'your-correlation-id';
```

## Development

### Adding a New Hook

1. Create script in `hooks/scripts/`:
   ```bash
   #!/bin/bash
   PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
   # ... hook implementation
   ```

2. Register in `hooks/hooks.json`:
   ```json
   {
     "hooks": {
       "YourHookName": [
         {
           "type": "command",
           "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/your-hook.sh"
         }
       ]
     }
   }
   ```

3. Make executable:
   ```bash
   chmod +x hooks/scripts/your-hook.sh
   ```

### Adding Library Modules

Add Python modules to:
- `hooks/lib/` - Hook-specific utilities
- `lib/core/` - Core functionality
- `lib/utils/` - Shared utilities

Update `__init__.py` files to export new modules.

## License

MIT License - See LICENSE file for details.

## Related

- [OmniClaude Documentation](../../CLAUDE.md)
- [Agent Definitions](~/.claude/agent-definitions/)
- [Infrastructure Guide](~/.claude/CLAUDE.md)
