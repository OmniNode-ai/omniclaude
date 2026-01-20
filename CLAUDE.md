# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

OmniClaude provides Claude Code hooks and learning loop integration with the omnibase ecosystem:

- **ONEX-compatible event schemas** for Claude Code hook events
- **Claude Code plugin** with hooks for session, prompt, and tool lifecycle
- **Event-driven architecture** using Kafka for learning and intelligence
- **Integration with omnibase ecosystem** (omnibase-core, omnibase-spi, omnibase-infra)

---

## Project Structure

```
omniclaude/
├── src/omniclaude/           # Main Python package
│   ├── hooks/                # Hook schemas and topics
│   │   ├── schemas.py        # ONEX event envelope models
│   │   └── topics.py         # Kafka topic definitions
│   └── config/               # Pydantic Settings (future)
├── plugins/onex/             # Claude Code plugin
│   ├── hooks/                # Hook configuration and scripts
│   │   ├── hooks.json        # Hook event configuration
│   │   ├── scripts/          # Shell script handlers
│   │   └── lib/              # Python library modules
│   ├── agents/               # Agent YAML definitions
│   ├── commands/             # Command definitions
│   └── skills/               # Skill definitions
├── tests/                    # Test suite
│   └── hooks/                # Hook schema tests
├── _archive/                 # Archived legacy code (reference only)
├── pyproject.toml            # Package configuration
├── .env.example              # Environment template
└── CLAUDE.md                 # This file
```

---

## ONEX Event Schemas

**Location**: `src/omniclaude/hooks/schemas.py`

ONEX-compatible event schemas for Claude Code hooks. These schemas define the event envelope for all hook-emitted events.

### Event Types

| Schema | Event Name | Purpose |
|--------|------------|---------|
| `ModelSessionStarted` | `session.started` | Claude Code session starts |
| `ModelSessionEnded` | `session.ended` | Claude Code session ends |
| `ModelPromptSubmitted` | `prompt.submitted` | User submits a prompt |
| `ModelToolExecuted` | `tool.executed` | Tool completes execution |

### Schema Evolution Strategy

Event schemas use semantic versioning:

| Version Change | Impact | Example |
|----------------|--------|---------|
| Patch (1.0.x) | Bug fixes only | Field description updates |
| Minor (1.x.0) | New optional fields | Adding `metadata` field with default |
| Major (x.0.0) | Breaking changes | Renaming fields, removing fields |

**Guidelines**:
- Always add new fields as optional with sensible defaults
- Never remove or rename fields in minor versions
- Topic names include version (`.v1`) for parallel running

### Schema Design Principles

1. **Frozen models** - All events are immutable (`frozen=True`)
2. **Strict validation** - Extra fields forbidden (`extra="forbid"`)
3. **Discriminated union** - `event_name` as discriminator for polymorphic deserialization
4. **UUID handling** - `default_factory=uuid4` for correlation IDs
5. **Minimal payloads** - Only stable fields, avoid large blobs

### Example Usage

```python
from omniclaude.hooks import (
    ModelSessionStarted,
    ModelPromptSubmitted,
    TopicBase,
    build_topic,
)

# Create a session started event
event = ModelSessionStarted(
    session_id="abc123",
    working_directory="/workspace/project",
    git_branch="main",
    hook_source="startup",
)

# Serialize for Kafka
event_json = event.model_dump_json()

# Get topic name
topic = build_topic("dev", TopicBase.SESSION_STARTED)
# → "dev.omniclaude.session.started.v1"
```

---

## Kafka Topics

**Location**: `src/omniclaude/hooks/topics.py`

Topic base names (without environment prefix):

| Topic | Base Name |
|-------|-----------|
| Session Started | `omniclaude.session.started.v1` |
| Session Ended | `omniclaude.session.ended.v1` |
| Prompt Submitted | `omniclaude.prompt.submitted.v1` |
| Tool Executed | `omniclaude.tool.executed.v1` |
| Learning Pattern | `omniclaude.learning.pattern.v1` (future) |

Topic prefix (e.g., `dev`, `staging`, `prod`) comes from environment configuration.

---

## Claude Code Hooks

**Location**: `plugins/onex/hooks/`

### Hook Configuration

Hooks are defined in `plugins/onex/hooks/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "..." }] }],
    "SessionEnd": [{ "hooks": [{ "type": "command", "command": "..." }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "..." }] }],
    "PostToolUse": [{ "matcher": "^(Read|Write|Edit|Bash|...)$", "hooks": [...] }]
  }
}
```

### Hook Scripts

| Hook | Script | Performance Target |
|------|--------|-------------------|
| SessionStart | `session-start.sh` | <50ms |
| SessionEnd | `session-end.sh` | <50ms |
| UserPromptSubmit | `user-prompt-submit.sh` | <500ms |
| PostToolUse | `post-tool-use.sh` | <100ms |

### Current Status

**OMN-1399** (this ticket): Schema definition only - hooks are stubs
**OMN-1400** (next): Hook handlers emit events to Kafka

---

## Environment Configuration

**File**: `.env.example`

```bash
# Application Identity
OMNICLAUDE_APP_NAME=omniclaude
OMNICLAUDE_ENVIRONMENT=development

# Kafka / Redpanda
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092
KAFKA_TOPIC_PREFIX=dev

# PostgreSQL (optional - for event logging)
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<set_in_env>

# Logging
LOG_LEVEL=INFO
```

### Setup

```bash
cp .env.example .env
nano .env
source .env
```

---

## Dependencies

This package depends on the omnibase ecosystem:

```toml
dependencies = [
    "omnibase-core>=0.8.0,<0.9.0",
    "omnibase-spi>=0.5.0,<0.6.0",
    "omnibase-infra>=0.2.1,<0.3.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
]
```

### Installation

```bash
# Using uv (recommended)
uv sync

# Using pip
pip install -e .

# Development dependencies
uv sync --group dev
```

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run hook schema tests
pytest tests/hooks/test_schemas.py -v

# Verify hooks.json is valid
cat plugins/onex/hooks/hooks.json | jq .

# Verify scripts are executable
ls -la plugins/onex/hooks/scripts/*.sh
```

---

## Development Workflow

1. **Schema changes**: Edit `src/omniclaude/hooks/schemas.py`
2. **Topic changes**: Edit `src/omniclaude/hooks/topics.py`
3. **Hook config**: Edit `plugins/onex/hooks/hooks.json`
4. **Hook handlers**: Edit `plugins/onex/hooks/scripts/*.sh`
5. **Run tests**: `pytest tests/ -v`

---

## Archived Code

**Location**: `_archive/`

Contains the original OmniClaude implementation archived during the reset. Reference only - do not import or resurrect without explicit approval.

Key archived components:
- `agents/` - Old 52-agent polymorphic framework
- `claude/` - Old hooks implementation
- `config/` - Old Pydantic config
- `deployment/` - Old docker-compose

See `_archive/README_ARCHIVE.md` for details.

---

## Related Tickets

| Ticket | Description | Status |
|--------|-------------|--------|
| OMN-1399 | Define Claude Code hooks schema for ONEX event emission | In Progress |
| OMN-1400 | Hook handlers emit to Kafka | Pending |
| OMN-1401 | Session storage in OmniMemory | Pending |
| OMN-1402 | Learning compute node | Pending |
| OMN-1403 | Context injection | Pending |
| OMN-1404 | E2E integration test | Pending |

---

## Quick Reference

### Key Files

- **Schemas**: `src/omniclaude/hooks/schemas.py`
- **Topics**: `src/omniclaude/hooks/topics.py`
- **Hooks Config**: `plugins/onex/hooks/hooks.json`
- **Scripts**: `plugins/onex/hooks/scripts/`

### Commands

```bash
# Test schemas
pytest tests/hooks/test_schemas.py -v

# Validate hooks.json
jq . plugins/onex/hooks/hooks.json

# Check script permissions
ls -la plugins/onex/hooks/scripts/*.sh
```

---

**Last Updated**: 2026-01-20
**Version**: 0.1.0
**Status**: Reset in progress (OMN-1399)
**Schemas**: ONEX-compatible event envelopes
**Hooks**: SessionStart, SessionEnd, UserPromptSubmit, PostToolUse
