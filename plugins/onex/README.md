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
- `route_via_events_wrapper.py` - Kafka-based agent routing with candidate list generation
- `hook_event_logger.py` - PostgreSQL event logging
- `correlation_manager.py` - Correlation ID management
- `publish_intelligence_request.py` - Publishes to event bus
- `session_intelligence.py` - Session tracking
- `metadata_extractor.py` - Extracts prompt metadata

**Performance Targets**:
- UserPromptSubmit: <500ms typical (~15s worst-case with delegation)
- PostToolUse: <100ms
- SessionStart/SessionEnd: <50ms

### Agents

Polymorphic agent framework with ONEX compliance:

- Dynamic agent transformation based on task domain
- YAML-based agent definitions in `plugins/onex/agents/configs/`
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

Hooks are configured in `plugins/onex/hooks/hooks.json`. Claude Code reads
this file from the plugin directory automatically — no changes to
`~/.claude/settings.json` are needed.

The configuration uses `${CLAUDE_PLUGIN_ROOT}` (injected by Claude Code) to
reference hook scripts:

```json
{
  "$schema": "https://claude.ai/schemas/hooks.json",
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session-start.sh"}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/user-prompt-submit.sh"}]}],
    "PostToolUse": [
      {
        "matcher": "^(Read|Write|Edit|Bash|Glob|Grep|Task|Skill|WebFetch|WebSearch|NotebookEdit|NotebookRead)$",
        "hooks": [{"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post-tool-use-quality.sh"}]
      }
    ]
  }
}
```

See `plugins/onex/hooks/hooks.json` for the full configuration including
`PreToolUse` and `SessionEnd` hooks.

### Dependencies

Hooks require a Python virtual environment with dependencies managed via
`uv`. The project uses Python 3.12+.

**Setup**:
```bash
# Install all dependencies (including dev tools)
uv sync --group dev
```

All required packages (`aiokafka`, `psycopg2-binary`, `pydantic`, etc.) are
declared in `pyproject.toml` and installed automatically by `uv sync`.

**Never use `pip install` directly** — always use `uv sync` or `uv run`.

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

#### 3. Remove Legacy Hook Entries from settings.json

If you previously had hook entries in `~/.claude/settings.json` pointing to
`plugins/cache/omninode-tools/onex/`, remove them. Hooks are declared
authoritatively in `hooks/hooks.json` (the plugin manifest). Claude Code
loads `hooks.json` automatically via the plugin — duplicate entries in
`settings.json` cause each event to fire twice.

Running `deploy.sh --execute` (version 1.3.0+) automatically removes any
legacy onex hook entries from `settings.json`.

To remove them manually:

```bash
# Remove all onex hook entries from settings.json
python3 - <<'EOF'
import json, re
from pathlib import Path

settings_path = Path.home() / ".claude/settings.json"
settings = json.loads(settings_path.read_text())
hooks = settings.get("hooks", {})

def rm_onex(entries):
    if not entries:
        return entries
    return [
        e for e in entries
        if not any(
            re.search(r"plugins/cache/omninode-tools/onex/", h.get("command", ""))
            for h in e.get("hooks", [])
        )
    ]

for event in list(hooks.keys()):
    hooks[event] = rm_onex(hooks[event])

settings_path.write_text(json.dumps(settings, indent=2))
print("Done. Restart Claude Code.")
EOF
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
| Hooks not firing | Ensure `hooks/hooks.json` is present in the plugin directory; remove any duplicate onex entries from `~/.claude/settings.json` |
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
POSTGRES_HOST=<postgres-host>           # Or your PostgreSQL host
POSTGRES_PORT=5436                     # Or your PostgreSQL port
POSTGRES_DATABASE=omniclaude           # Or your database name
POSTGRES_PASSWORD=<set_in_env>         # Required - never commit

# Kafka/Redpanda
KAFKA_BOOTSTRAP_SERVERS=omninode-bridge-redpanda:9092  # Docker services
# KAFKA_BOOTSTRAP_SERVERS=<kafka-bootstrap-servers>:9092         # Host scripts

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
PROJECT_ROOT=/path/to/omniclaude  # local-path-ok
OMNICLAUDE_PATH=/path/to/omniclaude  # local-path-ok
POSTGRES_HOST=<postgres-host>
KAFKA_BOOTSTRAP_SERVERS=<kafka-bootstrap-servers>:9092
```

**omniarchon**:
```bash
PROJECT_ROOT=/path/to/omniarchon  # local-path-ok
OMNICLAUDE_PATH=/path/to/omniclaude  # For shared config  # local-path-ok
POSTGRES_HOST=<postgres-host>
KAFKA_BOOTSTRAP_SERVERS=<kafka-bootstrap-servers>:9092
```

**omnibase_core**:
```bash
PROJECT_ROOT=/path/to/omnibase_core  # local-path-ok
OMNICLAUDE_PATH=/path/to/omniclaude  # For shared config  # local-path-ok
POSTGRES_HOST=<postgres-host>
KAFKA_BOOTSTRAP_SERVERS=<kafka-bootstrap-servers>:9092
```

**Critical**: Always `source .env` before running database or Kafka operations.

### Agent Registry

Agent definitions are stored in YAML format:

**Location**: `plugins/onex/agents/configs/`

**Example**:
```yaml
schema_version: "1.0.0"
agent_type: "api_architect"

agent_identity:
  name: "agent-api-architect"
  description: "Designs RESTful APIs and OpenAPI schemas"
  color: "blue"

activation_patterns:
  explicit_triggers:
    - "api design"
    - "openapi"
  context_triggers:
    - "designing HTTP endpoints"
```

See `docs/guides/ADDING_AN_AGENT.md` for the full guide.

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
4. Deploy with `/deploy-local-plugin`

See `docs/guides/ADDING_A_HOOK_HANDLER.md` for the step-by-step guide.

### Adding New Agents

1. Create YAML definition in `agents/configs/`
2. Define activation patterns (explicit and context triggers)
3. Test with routing framework: `python hooks/lib/route_via_events_wrapper.py "test prompt"`
4. Deploy with `/deploy-local-plugin`

See `docs/guides/ADDING_AN_AGENT.md` for the step-by-step guide.

### Adding New Skills

1. Create skill directory in `skills/my-skill/`
2. Add `SKILL.md` with Overview, Quick Start, and Methodology sections
3. Optionally add `prompt.md` for orchestration logic and scripts
4. Deploy with `/deploy-local-plugin`; invoke with `/my-skill`

See `docs/guides/ADDING_A_SKILL.md` for the step-by-step guide.

### Adding New Commands

1. Create command file in `commands/`
2. Add frontmatter with metadata
3. Implement command logic
4. Test via Claude Code

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Hooks not firing | Verify `plugins/onex/hooks/hooks.json` is valid JSON (`jq . hooks/hooks.json`) |
| Import errors | Run `uv sync` to install dependencies; check `OMNICLAUDE_PROJECT_ROOT` |
| Hook exits 1 | Wrong Python interpreter — set `OMNICLAUDE_PROJECT_ROOT` or `PLUGIN_PYTHON_BIN` |
| Kafka errors | Check `KAFKA_BOOTSTRAP_SERVERS` in `.env` |
| Database errors | Verify `POSTGRES_*` variables and `source .env` |
| Permission denied | Make hook scripts executable: `chmod +x hooks/scripts/*.sh` |
| Path errors | Set `PROJECT_ROOT` and `OMNICLAUDE_PATH` environment variables |

### Debug Commands

```bash
# Check hook logs
tail -f ~/.claude/hooks.log

# Daemon status
uv run python plugins/onex/hooks/lib/emit_client_wrapper.py status --json

# Validate hooks.json
jq . plugins/onex/hooks/hooks.json

# Test routing
uv run python ${CLAUDE_PLUGIN_ROOT}/hooks/lib/route_via_events_wrapper.py "test prompt" "test-correlation-id"

# Verify environment variables
echo "PROJECT_ROOT: ${PROJECT_ROOT}"
echo "OMNICLAUDE_PATH: ${OMNICLAUDE_PATH}"
echo "CLAUDE_PLUGIN_ROOT: ${CLAUDE_PLUGIN_ROOT}"
```

## Performance

### Hook Performance

Targets for the **synchronous path only** (backgrounded work does not count
against these budgets):

| Hook | Budget | Notes |
|------|--------|-------|
| SessionStart | <50ms | Daemon check, stdin read |
| SessionEnd | <50ms | stdin read |
| UserPromptSubmit | <500ms typical | ~15s worst-case with all timeout paths (routing 5s + injection 1s + advisory 1s + delegation 8s). Without delegation, worst-case is ~7s. |
| PostToolUse | <100ms | stdin read, quality check |

Kafka emission, PostgreSQL logging, and intelligence requests are all
backgrounded and do not block.

### Agent Routing

- Routing accuracy: >95%
- Parallel speedup: 60-80% vs sequential
- Quality gate execution: <200ms each
- Agent transformation success: >85%

### Intelligence Infrastructure

- Pattern discovery: 15,689+ vectors from Qdrant
- Manifest query: <2000ms (critical: >5000ms)
- Intelligence availability: >95% (critical: <80%)

## Subsystems

### LLM-Based Routing

User prompts are matched against agent activation patterns using a fuzzy
scorer. The routing system returns a ranked candidate list; Claude selects
from the list and loads the winning agent's YAML on demand (agent YAML
loading is not on the synchronous hook path — see OMN-1980).

Routing falls back to `polymorphic-agent` on timeout (5s). With no-fallback
mode enabled (OMN-2340), prompts that match no agent below a confidence
threshold are rejected rather than silently downgraded.

See `docs/architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md` and
`docs/architecture/ROUTING_ARCHITECTURE_COMPARISON.md` for architecture
details.

### Context Enrichment

After routing, `context_injection_wrapper.py` queries the database for
learned patterns relevant to the session and appends them to
`hookSpecificOutput.additionalContext`. This gives Claude codebase-specific
context without requiring the user to repeat it.

Context injection has a 1s timeout. If the database is unreachable,
the hook proceeds without patterns (data loss acceptable; UI freeze is not).

See `docs/observability/AGENT_TRACEABILITY.md` for enrichment observability.

### Compliance Enforcement

`PostToolUse` hooks run a quality check on every tool call. The enforcement
mode is controlled by `ENFORCEMENT_MODE`:

| Mode | Behavior |
|------|----------|
| `warn` (default) | Log violations, do not block |
| `block` | Emit non-zero exit on violations (blocks the tool call) |
| `silent` | Suppress all compliance output |

Compliance results are published to Kafka for downstream consumers
(e.g., `compliance_result_subscriber.py` transforms violations into
`PatternAdvisory` events).

See `docs/architecture/SERVICE-BOUNDARIES.md` for service boundary details.

### Local LLM Delegation

When `USE_LOCAL_DELEGATION=true`, `UserPromptSubmit` can delegate prompts
to a local LLM endpoint (configured via `LLM_CODER_URL` or
`LLM_CODER_FAST_URL`) before returning a response to Claude. Delegation
adds up to 8s to the worst-case `UserPromptSubmit` path.

The delegation orchestrator (`delegation_orchestrator.py`) coordinates the
request, validates the response, and injects the result into
`additionalContext`.

See `docs/decisions/ADR-005-delegation-orchestrator.md` for the decision
record.

---

## Resources

- **Shared Infrastructure**: `~/.claude/CLAUDE.md`
- **Repository Documentation**: `${PROJECT_ROOT}/CLAUDE.md`
- **Hook Data Flow**: `docs/architecture/HOOK_DATA_FLOW.md`
- **Routing Architecture**: `docs/architecture/EVENT_DRIVEN_ROUTING_PROPOSAL.md`
- **Service Boundaries**: `docs/architecture/SERVICE-BOUNDARIES.md`
- **Guides**: `docs/guides/` (hook handlers, agents, skills, testing)
- **ADRs**: `docs/decisions/`

## License

Part of the OmniClaude project. See repository root for license information.

---

**Version**: 1.1.0
**Last Updated**: 2026-02-19
**Status**: Active Development
