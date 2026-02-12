# OmniClaude

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
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

The event schemas are designed with privacy in mind using a **data minimization** approach.

### Prompt Preview Field

The `prompt_preview` field captures a **truncated preview** of user prompts:

| Attribute | Value | Rationale |
|-----------|-------|-----------|
| Max Length | 200 characters | Limits exposure while preserving intent detection |
| Truncation | Hard cut at 200 chars | No smart truncation to avoid unintended data exposure |
| Full Content | **Never stored** | Only preview + length metadata |
| PII Handling | **User responsibility** | Prompts may contain sensitive data |

**What is captured**:
- First 200 characters of the prompt text
- Total character count (`prompt_length`)
- Optional classified intent (`detected_intent`)

**What is NOT captured**:
- Full prompt content beyond 200 chars
- File contents read/written by tools
- API keys, credentials, or secrets (unless in first 200 chars of prompt)

### Other Privacy Considerations

- **Working Directory**: Paths may reveal project names. Consider this when configuring consumers.
- **Tool Summaries**: The `summary` field (max 500 chars) on tool events may contain file paths.
- **Session IDs**: UUIDs are pseudonymous but can be correlated within a session.

### Recommendations

1. **Access Control**: Use Kafka topic-level ACLs to restrict access to event streams
2. **Data Retention**: Configure appropriate retention (e.g., 7-30 days for learning events)
3. **Audit Logging**: Track access to event consumers
4. **Encryption**: Enable TLS for Kafka connections
5. **User Consent**: Inform users that session metadata is collected for learning

## Schema Evolution

Event schemas follow **semantic versioning** for backwards compatibility.

### Version Change Rules

| Change Type | Version Bump | Example | Consumer Impact |
|-------------|--------------|---------|-----------------|
| **Patch** (1.0.x) | Bug fixes, docs | Field description update | None |
| **Minor** (1.x.0) | New optional fields | Adding `metadata` field with default | None (backwards compatible) |
| **Major** (x.0.0) | Breaking changes | Renaming/removing fields | Requires consumer update |

### Current Schema Version

**Version**: 1.0.0 (initial release)

### Evolution Strategy

**Adding Fields (Minor Version)**:
1. New fields MUST be optional with sensible defaults
2. Use `Field(default=None)` or `Field(default_factory=...)` in Pydantic
3. Producers upgrade first, then consumers
4. No topic version change required

**Breaking Changes (Major Version)**:
1. Create new topic version (e.g., `omniclaude.session.started.v2`)
2. Run old and new topics in parallel during migration
3. Producers emit to both topics temporarily
4. Consumers migrate to new topic at their pace
5. Deprecate old topic after migration window

**Consumer Guidelines**:
- Use `extra="ignore"` in Pydantic models to ignore unknown fields
- Always check schema version in envelope before processing
- Implement graceful degradation for missing optional fields

### Example: Adding a New Field

```python
# Version 1.0.0
class ModelHookSessionStartedPayload(BaseModel):
    session_id: str
    working_directory: str
    # ... existing fields

# Version 1.1.0 - Adding optional field (backwards compatible)
class ModelHookSessionStartedPayload(BaseModel):
    session_id: str
    working_directory: str
    # New optional field with default
    user_agent: str | None = Field(default=None, description="Client user agent")
```

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
- [RUNBOOK_VERTICAL_DEMO.md](plugins/onex/docs/RUNBOOK_VERTICAL_DEMO.md) - Pattern pipeline demo
- [_archive/README_ARCHIVE.md](_archive/README_ARCHIVE.md) - Archived code documentation

## Contributing

This project is part of the OmniNode ecosystem. See the main documentation for contribution guidelines.

## License

MIT License - See LICENSE file for details.
