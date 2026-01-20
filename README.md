# OmniClaude

[![License](https://img.shields.io/badge/license-OmniNode-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/status-in%20development-yellow.svg)](#status)

Claude Code hooks and learning loop integration with the omnibase ecosystem.

## Overview

OmniClaude provides:

- **ONEX-compatible event schemas** for Claude Code hook events
- **Claude Code plugin** with hooks for session, prompt, and tool lifecycle
- **Event-driven architecture** using Kafka for learning and intelligence
- **Integration with omnibase ecosystem** (omnibase-core, omnibase-spi, omnibase-infra)

## Status

**Currently in development** - Reset in progress as part of OMN-1399.

- [x] Archive old code
- [x] Create new package structure
- [x] Define ONEX event schemas
- [x] Configure hook scripts (stubs)
- [ ] Implement event emission (OMN-1400)
- [ ] Session storage integration (OMN-1401)
- [ ] Learning compute node (OMN-1402)

## Quick Start

### Installation

```bash
# Clone repository
git clone https://github.com/OmniNode-ai/omniclaude.git
cd omniclaude

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

### Configuration

```bash
# Copy and configure environment
cp .env.example .env
nano .env
source .env
```

### Testing

```bash
# Run tests
pytest tests/ -v

# Validate hooks.json
jq . plugins/onex/hooks/hooks.json
```

## Project Structure

```
omniclaude/
├── src/omniclaude/           # Main Python package
│   ├── hooks/                # Event schemas and topics
│   │   ├── schemas.py        # ONEX event models
│   │   └── topics.py         # Kafka topic definitions
│   └── config/               # Configuration (future)
├── plugins/onex/             # Claude Code plugin
│   ├── hooks/                # Hook configuration
│   │   ├── hooks.json        # Hook definitions
│   │   └── scripts/          # Shell handlers
│   ├── agents/               # Agent YAML configs
│   ├── commands/             # Command definitions
│   └── skills/               # Skill definitions
├── tests/                    # Test suite
├── _archive/                 # Archived legacy code
├── pyproject.toml            # Package config
└── CLAUDE.md                 # Development guide
```

## Event Schemas

ONEX-compatible event schemas for Claude Code hooks:

| Event | Schema | Purpose |
|-------|--------|---------|
| Session Start | `ModelSessionStarted` | Session initialization |
| Session End | `ModelSessionEnded` | Session completion |
| Prompt Submit | `ModelPromptSubmitted` | User prompt submission |
| Tool Execute | `ModelToolExecuted` | Tool completion |

```python
from omniclaude.hooks import (
    ModelSessionStarted,
    TopicBase,
    build_topic,
)

# Create event
event = ModelSessionStarted(
    session_id="abc123",
    working_directory="/workspace/project",
    hook_source="startup",
)

# Get Kafka topic
topic = build_topic("dev", TopicBase.SESSION_STARTED)
# → "dev.omniclaude.session.started.v1"
```

## Privacy Considerations

The event schemas are designed with privacy in mind:

- **Prompt Preview**: The `prompt_preview` field (max 200 chars) may contain sensitive data.
  Configure appropriate access controls and data retention policies.
- **No Full Content**: Full prompt content is never stored in events - only metadata.
- **Session Data**: Working directory paths may reveal project names. Consider this
  when configuring event consumers.

**Recommendations**:
- Use Kafka topic-level ACLs to restrict access to event streams
- Configure appropriate data retention (e.g., 7-30 days for learning events)
- Audit access to event consumers

## Schema Evolution

Event schemas follow semantic versioning for backwards compatibility:

- **Minor versions** (1.x.0): New optional fields only, fully backwards compatible
- **Major versions** (2.0.0): Breaking changes, new topic versions created

**Current Schema Version**: 1.0.0

**Evolution Strategy**:
1. New optional fields are added with default values
2. Consumers should ignore unknown fields (`extra="ignore"` in Pydantic)
3. Breaking changes trigger new topic versions (e.g., `.v2` suffix)
4. Old and new topics run in parallel during migration

## Dependencies

```toml
dependencies = [
    "omnibase-core>=0.8.0,<0.9.0",
    "omnibase-spi>=0.5.0,<0.6.0",
    "omnibase-infra>=0.2.1,<0.3.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
]
```

## Documentation

- [CLAUDE.md](CLAUDE.md) - Development guide and reference
- [_archive/README_ARCHIVE.md](_archive/README_ARCHIVE.md) - Archived code documentation

## Contributing

This project is part of the OmniNode ecosystem. See the main documentation for contribution guidelines.

## License

OmniNode License - See LICENSE file for details.
