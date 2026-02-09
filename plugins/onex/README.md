# ONEX Plugin for Claude Code

Unified plugin for ONEX architecture providing hooks, agents, skills, and commands for enhanced Claude Code functionality.

## Overview

The ONEX plugin consolidates the previously fragmented plugin ecosystem into a single, coherent namespace aligned with ONEX architecture principles. This plugin provides:

- **Hooks**: Event-driven lifecycle integration with Claude Code
- **Agents**: Polymorphic agent framework with ONEX compliance
- **Skills**: Reusable capabilities and domain expertise
- **Commands**: User-facing slash commands for workflows

## Architecture

The plugin follows ONEX architecture with clear separation of concerns:

```
plugins/onex/
├── .claude-plugin/         # Plugin metadata and configuration
├── hooks/                  # Claude Code lifecycle hooks
│   ├── scripts/           # Hook shell scripts (executable)
│   ├── lib/               # Hook Python libraries
│   ├── logs/              # Hook execution logs
│   └── hooks.json         # Hook configuration
├── agents/                 # Agent definitions and framework
├── skills/                 # Reusable capabilities
└── commands/               # Slash commands
```

## Components

### Hooks

Event-driven integration with Claude Code lifecycle events:

- **UserPromptSubmit**: Agent routing, manifest injection, intelligence requests
- **PostToolUse**: Quality enforcement, pattern tracking
- **SessionStart**: Session lifecycle logging, project context
- **SessionEnd**: Session cleanup and finalization
- **Stop**: Graceful shutdown and state persistence

**Location**: `hooks/scripts/`

**Key Libraries** (`hooks/lib/`):
- `agent_detector.py` - Detects automated workflows
- `route_via_events_wrapper.py` - Kafka-based agent routing
- `simple_agent_loader.py` - Loads agent YAML definitions
- `hook_event_logger.py` - PostgreSQL event logging
- `correlation_manager.py` - Correlation ID management
- `publish_intelligence_request.py` - Publishes to event bus
- `session_intelligence.py` - Session tracking
- `metadata_extractor.py` - Extracts prompt metadata

**Performance Targets**:
- UserPromptSubmit: <500ms (critical: >2000ms)
- PostToolUse: <100ms (critical: >500ms)
- SessionStart: <50ms (critical: >200ms)

### Agents

Polymorphic agent framework with ONEX compliance:

- Dynamic agent transformation based on task domain
- YAML-based agent definitions in `~/.claude/agent-definitions/`
- Manifest injection with intelligence context
- Correlation tracking for end-to-end traceability
- Multi-agent coordination with parallel execution

**Node Types** (ONEX):
- **Effect**: External I/O, APIs (`Node<Name>Effect`)
- **Compute**: Pure transforms (`Node<Name>Compute`)
- **Reducer**: State/persistence (`Node<Name>Reducer`)
- **Orchestrator**: Workflow coordination (`Node<Name>Orchestrator`)

### Skills

Reusable capabilities and domain expertise:

- Pattern discovery from 15,689+ vectors
- Intelligence infrastructure integration
- Linear ticket management
- PR review and CI/CD workflows
- System monitoring and diagnostics

### Commands

User-facing slash commands for common workflows:

- `/velocity-estimate` - Project velocity & ETA analysis
- `/suggest-work` - Priority backlog recommendations
- `/pr-release-ready` - Fix all PR issues
- `/parallel-solve` - Execute tasks in parallel
- `/project-status` - Linear insights dashboard
- `/deep-dive` - Daily work analysis report
- `/ci-failures` - CI/CD quick review
- `/pr-review-dev` - PR review + CI failures

## Installation

The ONEX plugin is automatically discovered by Claude Code when placed in the `~/.claude/plugins/` directory or when the repository containing it is opened.

### Plugin Registration

1. **Manual Installation** (copy to Claude Code plugins directory):
   ```bash
   ln -s /path/to/omniclaude/plugins/onex ~/.claude/plugins/onex
   ```

2. **Repository-Based** (automatic when repo is opened):
   Claude Code automatically discovers plugins in `<repo>/plugins/` directories.

### Hook Configuration

Hooks are configured in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "command": "/path/to/omniclaude/plugins/onex/hooks/scripts/user-prompt-submit.sh"
      }
    ],
    "PostToolUse": [
      {
        "command": "/path/to/omniclaude/plugins/onex/hooks/scripts/post-tool-use-quality.sh"
      }
    ],
    "SessionStart": [
      {
        "command": "/path/to/omniclaude/plugins/onex/hooks/scripts/session-start.sh"
      }
    ]
  }
}
```

### Dependencies

Hooks require a Python virtual environment with dependencies:

**Venv Location**: `${PROJECT_ROOT}/claude/lib/.venv` (where `PROJECT_ROOT` is the repository root)

**Required Packages**:
- `kafka-python`, `aiokafka` - Kafka integration
- `psycopg2-binary` - PostgreSQL connectivity
- `pydantic` - Data validation

**Setup**:
```bash
# Set PROJECT_ROOT to your repository location
cd ${PROJECT_ROOT}/claude/lib
python3 -m venv .venv
source .venv/bin/activate
pip install kafka-python aiokafka psycopg2-binary pydantic
```

## Migration from Legacy Plugin Structure

### Overview

Prior to version 1.0.0, OmniClaude used a fragmented plugin architecture with four separate plugins:
- `omniclaude-core` - Core functionality and hooks
- `omniclaude-agents` - Agent definitions and framework
- `omniclaude-skills` - Reusable capabilities
- `omniclaude-commands` - User-facing slash commands

These have been unified into a single **ONEX plugin** for better maintainability and ONEX architecture alignment.

### Migration Steps

If you have the old plugin structure installed, follow these steps to migrate:

#### 1. Remove Old Symlinks

```bash
# Remove old plugin symlinks from Claude Code directory
rm -f ~/.claude/plugins/omniclaude-core
rm -f ~/.claude/plugins/omniclaude-agents
rm -f ~/.claude/plugins/omniclaude-skills
rm -f ~/.claude/plugins/omniclaude-commands
```

#### 2. Create New ONEX Plugin Symlink

```bash
# Create symlink for unified ONEX plugin
ln -s /path/to/omniclaude/plugins/onex ~/.claude/plugins/onex
```

**Example** (adjust path to your repository location):
```bash
ln -s ~/Code/omniclaude/plugins/onex ~/.claude/plugins/onex
```

#### 3. Update Hook Paths in settings.json

Update your `~/.claude/settings.json` to reference the new plugin location:

**Old paths** (deprecated):
```json
{
  "hooks": {
    "UserPromptSubmit": [{
      "command": "/path/to/omniclaude/claude/hooks/user-prompt-submit.sh"
    }]
  }
}
```

**New paths** (recommended):
```json
{
  "hooks": {
    "UserPromptSubmit": [{
      "command": "/path/to/omniclaude/plugins/onex/hooks/scripts/user-prompt-submit.sh"
    }],
    "PostToolUse": [{
      "command": "/path/to/omniclaude/plugins/onex/hooks/scripts/post-tool-use-quality.sh"
    }],
    "SessionStart": [{
      "command": "/path/to/omniclaude/plugins/onex/hooks/scripts/session-start.sh"
    }]
  }
}
```

#### 4. Update Environment Variables

The ONEX plugin introduces clearer path management. Update your `.env`:

**Old approach**:
```bash
# No standardized path variables
```

**New approach**:
```bash
# Project root - Repository containing the plugin
PROJECT_ROOT="${HOME}/Code/omniclaude"

# Plugin root - Location of the ONEX plugin (auto-detected by Claude Code)
CLAUDE_PLUGIN_ROOT="${PROJECT_ROOT}/plugins/onex"

# OmniClaude path - For shared Python libraries
OMNICLAUDE_PATH="${HOME}/Code/omniclaude"
```

#### 5. Verify Migration

```bash
# Check symlink exists
ls -la ~/.claude/plugins/ | grep onex
# Expected: lrwxr-xr-x ... onex -> /path/to/omniclaude/plugins/onex

# Verify plugin structure
ls ~/.claude/plugins/onex/
# Expected: hooks/ agents/ skills/ commands/ .claude-plugin/

# Test hooks (should execute without errors)
source .env
~/.claude/plugins/onex/hooks/scripts/session-start.sh

# Check hook logs
tail ~/.claude/plugins/onex/hooks/logs/hook-session-start.log
```

#### 6. Restart Claude Code

Restart Claude Code to apply the new plugin configuration.

### Key Differences

| Aspect | Old Structure | New Structure |
|--------|---------------|---------------|
| **Plugins** | 4 separate plugins | 1 unified plugin |
| **Location** | `plugins/omniclaude-*` | `plugins/onex` |
| **Hooks** | `claude/hooks/*.sh` | `plugins/onex/hooks/scripts/*.sh` |
| **Agents** | `plugins/omniclaude-agents/agents/` | `plugins/onex/agents/` |
| **Skills** | `plugins/omniclaude-skills/skills/` | `plugins/onex/skills/` |
| **Commands** | `plugins/omniclaude-commands/commands/` | `plugins/onex/commands/` |
| **Hook Libs** | `claude/hooks/lib/` | `plugins/onex/hooks/lib/` |
| **Namespace** | Fragmented | ONEX-aligned |

### Backward Compatibility

The old directory structure (`claude/hooks/`, `agents/`, `skills/`, etc.) remains in place at the repository root for backward compatibility, but the **plugin structure has moved to `plugins/onex/`**.

**Recommendation**: Update all references to use the new `plugins/onex/` structure for future compatibility.

### Troubleshooting Migration

| Issue | Solution |
|-------|----------|
| Commands not found | Verify `~/.claude/plugins/onex` symlink exists |
| Hooks not firing | Update paths in `~/.claude/settings.json` to new location |
| Import errors | Set `PROJECT_ROOT` and `OMNICLAUDE_PATH` in `.env` |
| Old plugins still active | Remove old symlinks from `~/.claude/plugins/` |

## Configuration

### Environment Variables

The ONEX plugin is designed for cross-repository compatibility. Set these environment variables to adapt the plugin to your specific environment:

#### Required Path Variables

```bash
# Project root - Repository containing the plugin
# Used by: Hooks, skills, agents
# Default detection: Automatic from .env location or pwd
PROJECT_ROOT="${HOME}/Code/omniclaude"  # Example for omniclaude repo
# For other repos: PROJECT_ROOT="${HOME}/Code/omniarchon"

# Plugin root - Location of the ONEX plugin
# Set by Claude Code automatically when loading plugins
CLAUDE_PLUGIN_ROOT="${PROJECT_ROOT}/plugins/onex"  # Auto-detected

# OmniClaude path - For shared Python libraries
# Used by: Skills that import from config or agents
OMNICLAUDE_PATH="${HOME}/Code/omniclaude"  # If different from PROJECT_ROOT
```

#### Infrastructure Variables

```bash
# PostgreSQL (source .env before use)
POSTGRES_HOST=192.168.86.200           # Or your PostgreSQL host
POSTGRES_PORT=5436                     # Or your PostgreSQL port
POSTGRES_DATABASE=omninode_bridge      # Or your database name
POSTGRES_PASSWORD=<set_in_env>         # Required - never commit

# Kafka/Redpanda
KAFKA_BOOTSTRAP_SERVERS=omninode-bridge-redpanda:9092  # Docker services
# KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092         # Host scripts

# Qdrant Vector Database
QDRANT_URL=http://localhost:6333       # Or your Qdrant URL
QDRANT_HOST=localhost                  # Alternative format
QDRANT_PORT=6333
```

#### Optional Service Variables

```bash
# Linear Insights (for /deep-dive command)
LINEAR_INSIGHTS_OUTPUT_DIR="${HOME}/Code/omni_save"  # Deep dive output location

# Archon Intelligence Service
ARCHON_INTELLIGENCE_URL=http://localhost:8053  # Intelligence coordinator
```

#### Example .env Files by Repository

**omniclaude**:
```bash
PROJECT_ROOT=/Users/jonah/Code/omniclaude
OMNICLAUDE_PATH=/Users/jonah/Code/omniclaude
POSTGRES_HOST=192.168.86.200
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092
```

**omniarchon**:
```bash
PROJECT_ROOT=/Users/jonah/Code/omniarchon
OMNICLAUDE_PATH=/Users/jonah/Code/omniclaude  # For shared config
POSTGRES_HOST=192.168.86.200
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092
```

**omnibase_core**:
```bash
PROJECT_ROOT=/Users/jonah/Code/omnibase_core
OMNICLAUDE_PATH=/Users/jonah/Code/omniclaude  # For shared config
POSTGRES_HOST=192.168.86.200
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092
```

**Critical**: Always `source .env` before running database or Kafka operations.

### Agent Registry

Agent definitions are stored in YAML format:

**Location**: `~/.claude/agent-definitions/`

**Example**:
```yaml
name: agent-api
domain: api
description: FastAPI and REST API specialist
system_prompt: |
  You are an expert API developer...
```

## Usage

### Using Hooks

Hooks execute automatically on lifecycle events. View logs:

```bash
# Hook logs
tail -f hooks/logs/hook-enhanced.log
tail -f hooks/logs/hook-post-tool-use.log
tail -f hooks/logs/hook-session-start.log
```

### Using Commands

Execute slash commands in Claude Code:

```
/velocity-estimate
/suggest-work
/pr-release-ready
```

### Using Skills

Skills are invoked automatically by the agent framework when domain expertise is needed.

## Development

### Adding New Hooks

1. Create shell script in `hooks/scripts/`
2. Add Python libraries to `hooks/lib/` as needed
3. Update `hooks/hooks.json` configuration
4. Add to `~/.claude/settings.json`

### Adding New Agents

1. Create YAML definition in `~/.claude/agent-definitions/`
2. Define domain, system prompt, and capabilities
3. Test with routing framework

### Adding New Skills

1. Create skill directory in `skills/`
2. Add `SKILL.md` with documentation
3. Implement skill logic
4. Register in agent manifests

### Adding New Commands

1. Create command file in `commands/`
2. Add frontmatter with metadata
3. Implement command logic
4. Test via Claude Code

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Hooks not firing | Verify `~/.claude/settings.json` paths are absolute |
| Import errors | Ensure `${PROJECT_ROOT}/claude/lib/.venv` exists with dependencies |
| Kafka errors | Check `KAFKA_BOOTSTRAP_SERVERS` in `.env` |
| Database errors | Verify `POSTGRES_*` variables and `source .env` |
| Permission denied | Make hook scripts executable: `chmod +x hooks/scripts/*.sh` |
| Path errors | Set `PROJECT_ROOT` and `OMNICLAUDE_PATH` environment variables |

### Debug Commands

```bash
# Check hook logs (relative to plugin)
tail -f ${CLAUDE_PLUGIN_ROOT}/hooks/logs/hook-enhanced.log

# Verify venv
${PROJECT_ROOT}/claude/lib/.venv/bin/python3 -c "import kafka; import psycopg2; print('OK')"

# Test routing
python3 ${CLAUDE_PLUGIN_ROOT}/hooks/lib/route_via_events_wrapper.py "test prompt" "test-correlation-id"

# Verify environment variables
echo "PROJECT_ROOT: ${PROJECT_ROOT}"
echo "OMNICLAUDE_PATH: ${OMNICLAUDE_PATH}"
echo "CLAUDE_PLUGIN_ROOT: ${CLAUDE_PLUGIN_ROOT}"
```

## Performance

### Hook Performance

| Hook | Target | Critical |
|------|--------|----------|
| UserPromptSubmit | <500ms | >2000ms |
| PostToolUse | <100ms | >500ms |
| SessionStart | <50ms | >200ms |

### Agent Routing

- Routing accuracy: >95%
- Parallel speedup: 60-80% vs sequential
- Quality gate execution: <200ms each
- Agent transformation success: >85%

### Intelligence Infrastructure

- Pattern discovery: 15,689+ vectors from Qdrant
- Manifest query: <2000ms (critical: >5000ms)
- Intelligence availability: >95% (critical: <80%)

## Resources

- **Shared Infrastructure**: `~/.claude/CLAUDE.md`
- **Repository Documentation**: `${PROJECT_ROOT}/CLAUDE.md`
- **Agent Framework**: `${CLAUDE_PLUGIN_ROOT}/agents/polymorphic-agent.md`
- **Type-Safe Config**: `${PROJECT_ROOT}/config/README.md` (omniclaude)
- **Docker Deployment**: `${PROJECT_ROOT}/deployment/README.md` (omniclaude)

## License

Part of the OmniClaude project. See repository root for license information.

---

**Version**: 1.0.0
**Last Updated**: 2026-01-08
**Status**: Active Development
