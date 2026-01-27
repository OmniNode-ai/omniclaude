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

Event schemas use semantic versioning with strict backwards compatibility rules:

| Version Change | Impact | Example | Consumer Action |
|----------------|--------|---------|-----------------|
| **Patch** (1.0.x) | Bug fixes only | Field description updates | None required |
| **Minor** (1.x.0) | New optional fields | Adding `metadata` field with default | None (backwards compatible) |
| **Major** (x.0.0) | Breaking changes | Renaming/removing fields | Must update consumer |

**Guidelines**:
- Always add new fields as optional with sensible defaults
- Never remove or rename fields in minor versions
- Topic names include version (`.v1`) for parallel running during migrations

**Adding Fields (Minor Version)**:
1. New fields MUST be optional with sensible defaults
2. Use `Field(default=None)` or `Field(default_factory=...)` in Pydantic
3. Producers upgrade first, then consumers
4. No topic version change required

**Breaking Changes (Major Version)**:
1. Create new topic version (e.g., `onex.evt.omniclaude.session-started.v2`)
2. Run old and new topics in parallel during migration
3. Producers emit to both topics temporarily
4. Consumers migrate to new topic at their pace
5. Deprecate old topic after migration window (typically 30-90 days)

**Consumer Guidelines**:
- Use `extra="ignore"` in Pydantic models to ignore unknown fields
- Always check `schema_version` in envelope before processing
- Implement graceful degradation for missing optional fields

### Schema Design Principles

1. **Frozen models** - All events are immutable (`frozen=True`)
2. **Strict validation** - Extra fields forbidden (`extra="forbid"`)
3. **Discriminated union** - `event_name` as discriminator for polymorphic deserialization
4. **UUID handling** - `default_factory=uuid4` for correlation IDs
5. **Minimal payloads** - Only stable fields, avoid large blobs

### Event Ordering Guarantees

Events are designed to support strict ordering within a session:

| Concept | Description |
|---------|-------------|
| **Partition Key** | `entity_id` (session UUID) is used as Kafka partition key |
| **Ordering Scope** | Events with the same `entity_id` are published to the same partition |
| **Within-Session Order** | Total ordering is guaranteed for all events in a single session |
| **Cross-Session Order** | No ordering guarantee between different sessions |

**Disambiguation for Concurrent Events**:
- Events with identical `emitted_at` timestamps can be disambiguated using:
  - `tool_execution_id` for tool events (unique per execution)
  - `prompt_id` for prompt events (unique per prompt)
  - `causation_id` chain for causal ordering

**Example Partition Assignment**:
```python
# All events for session abc-123 go to the same partition
session_id = UUID("abc12345-...")
event1 = ModelSessionStarted(entity_id=session_id, ...)  # partition X
event2 = ModelPromptSubmitted(entity_id=session_id, ...)  # partition X (same)
event3 = ModelToolExecuted(entity_id=session_id, ...)     # partition X (same)
```

### Dual-Emission Architecture

The `UserPromptSubmit` hook emits to **two Kafka topics in parallel** to support both internal observability and external intelligence processing:

| Topic | Purpose | Prompt Content | Consumer |
|-------|---------|----------------|----------|
| `onex.evt.omniclaude.prompt-submitted.v1` | Internal observability | 100-char preview (truncated, sanitized) | OmniClaude analytics |
| `onex.cmd.omniintelligence.claude-hook-event.v1` | Intelligence processing | **Full prompt** (unsanitized) | OmniIntelligence |

**Architecture Diagram**:
```
UserPromptSubmit Hook
        │
        ├──► Background Process 1 ──► onex.evt.omniclaude.prompt-submitted.v1
        │         (prompt_preview: 100 chars, sanitized)
        │
        └──► Background Process 2 ──► onex.cmd.omniintelligence.claude-hook-event.v1
                  (full prompt for intelligence analysis)
```

**Design Rationale**:
- **Non-blocking**: Both emissions run as background processes (`&` in shell)
- **Decoupled consumers**: Intelligence system evolves independently from observability
- **Privacy separation**: Internal topic minimizes data; intelligence topic gets full context
- **Trade-off**: Doubled Kafka connections per prompt submission

**Why Two Topics?**:
1. **Different retention policies**: Observability events can have short retention; intelligence may need longer
2. **Access control**: Intelligence topic requires stricter ACLs (contains full prompts)
3. **Schema evolution**: Topics can evolve independently without breaking consumers
4. **Replay capability**: Intelligence can replay full prompts for model training

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
# → "dev.onex.evt.omniclaude.session-started.v1"
```

---

## Kafka Topics

**Location**: `src/omniclaude/hooks/topics.py`

Topic base names (without environment prefix):

| Topic | Base Name | Purpose |
|-------|-----------|---------|
| Session Started | `onex.evt.omniclaude.session-started.v1` | Internal observability |
| Session Ended | `onex.evt.omniclaude.session-ended.v1` | Internal observability |
| Prompt Submitted | `onex.evt.omniclaude.prompt-submitted.v1` | Internal observability (100-char preview) |
| Tool Executed | `onex.evt.omniclaude.tool-executed.v1` | Internal observability |
| Learning Pattern | `onex.evt.omniclaude.learning-pattern.v1` | Future: pattern storage |
| **Claude Hook Event** | `onex.cmd.omniintelligence.claude-hook-event.v1` | Intelligence (full prompt) |

**Topic Naming Convention**:
- `evt.*` topics: Events (observability, analytics)
- `cmd.*` topics: Commands (triggers processing in another service)

Topic prefix (e.g., `onex`, `dev`, `staging`, `prod`) comes from environment configuration.

---

## Privacy Guidelines

The event schemas are designed with **data minimization** principles. Key privacy-sensitive fields:

### Prompt Preview Field

The `prompt_preview` field captures a truncated, sanitized preview of user prompts:

| Attribute | Value | Rationale |
|-----------|-------|-----------|
| **Max Length** | 100 characters | Limits exposure while preserving intent detection |
| **Truncation** | Hard cut with "..." suffix | No smart truncation to avoid unintended exposure |
| **Full Content** | Never stored | Only preview + `prompt_length` metadata |
| **Sanitization** | Automatic secret redaction | API keys, passwords, tokens pattern-matched |

**Automatic Sanitization** (via `_sanitize_prompt_preview()`):
- OpenAI API keys (`sk-...`)
- AWS access keys (`AKIA...`)
- GitHub tokens (`ghp_...`, `gho_...`)
- Slack tokens (`xox...`)
- Stripe keys (`sk_live_...`, `pk_test_...`)
- Google Cloud keys (`AIza...`)
- PEM private keys
- Bearer tokens
- Password/secret in URLs and key=value patterns

**Known False Positives**:
- Short strings matching patterns (e.g., "Skip-navigation" may match `sk-` prefix)
- Test fixtures with dummy values resembling secrets
- Documentation examples showing key formats

**What is NOT Captured**:
- Full prompt content beyond 100 chars
- File contents read/written by tools
- API keys beyond the first 100 chars of prompt (unless in preview window)

### Other Privacy-Sensitive Fields

| Field | Sensitivity | Mitigation |
|-------|-------------|------------|
| `working_directory` | May reveal usernames, project names | Anonymize in aggregated analytics |
| `git_branch` | May contain ticket IDs, developer identifiers | Treat as potentially identifying |
| `summary` (tool events) | May contain file paths, code snippets | Limited to 500 chars, not auto-sanitized |
| `session_id` / `entity_id` | Tracking identifiers | Apply data retention policies |

### Full Prompt Exposure for Intelligence

The `onex.cmd.omniintelligence.claude-hook-event.v1` topic intentionally receives **full, unsanitized prompts** for intelligence processing. This is a deliberate design decision with specific privacy implications:

| Attribute | Value | Rationale |
|-----------|-------|-----------|
| **Content** | Full prompt (no truncation) | Intelligence requires complete context for pattern analysis |
| **Sanitization** | None applied | Sanitization would remove potentially valuable patterns |
| **Consumer** | OmniIntelligence only | Restricted to intelligence processing pipeline |
| **Retention** | Configurable per deployment | Should align with data retention policies |

**Why Full Prompts?**:
- **Intent classification**: Requires full context to accurately classify user intent
- **Pattern learning**: Truncated prompts lose valuable workflow patterns
- **RAG optimization**: Full prompts needed to improve context injection quality
- **Workflow analysis**: Understanding multi-step workflows requires complete prompts

**Privacy Controls for Intelligence Topic**:
1. **Topic-level ACLs**: Restrict consumer access to OmniIntelligence service only
2. **Network isolation**: Intelligence consumers should run in isolated network segment
3. **Audit logging**: All reads from intelligence topic should be logged
4. **Data retention**: Configure aggressive retention (7-14 days recommended)
5. **Encryption at rest**: Enable Kafka log encryption for intelligence topics

**Contrast with Observability Topic**:

| Aspect | `prompt-submitted.v1` | `claude-hook-event.v1` |
|--------|----------------------|------------------------|
| Prompt content | 100-char preview | Full prompt |
| Sanitization | Automatic secret redaction | None |
| Access scope | Broad (dashboards, metrics) | Restricted (intelligence only) |
| Retention | 30 days | 7-14 days recommended |

### Recommendations

1. **Access Control**: Use Kafka topic-level ACLs to restrict access
2. **Data Retention**: Configure appropriate retention (7-30 days for learning events)
3. **Audit Logging**: Track access to event consumers
4. **Encryption**: Enable TLS for Kafka connections
5. **User Consent**: Inform users that session metadata is collected

---

## Duration Bounds

Duration fields have explicit upper bounds to prevent data quality issues:

| Field | Max Value | Constant | Rationale |
|-------|-----------|----------|-----------|
| `duration_seconds` (session) | 2,592,000 (30 days) | `86400 * 30` | Longest reasonable session with reconnects |
| `duration_ms` (tool) | 3,600,000 (1 hour) | `3600000` | No single tool should run longer than 1 hour |

**Why Upper Bounds?**:
1. **Data Quality**: Prevents corrupted timestamps from causing extreme values
2. **Storage Efficiency**: Enables efficient numeric encoding in analytics systems
3. **Anomaly Detection**: Values exceeding bounds indicate bugs or data corruption
4. **Business Logic**: Represents realistic operational constraints

**Handling Exceeded Bounds**:
- Pydantic validation will reject values exceeding `le` constraints
- Producers should log warnings and cap values if system clocks are skewed
- Monitoring should alert on values approaching 80% of bounds

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
    "omnibase-core>=0.9.5,<0.10.0",
    "omnibase-spi>=0.6.0,<0.7.0",
    "omnibase-infra>=0.2.4,<0.3.0",
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
| OMN-1402 | Intent capture workflow (dual-emission to intelligence) | In Progress |
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

**Last Updated**: 2026-01-26
**Version**: 0.1.0
**Status**: OMN-1402 (Intent capture workflow with dual-emission)
**Schemas**: ONEX-compatible event envelopes
**Hooks**: SessionStart, SessionEnd, UserPromptSubmit, PostToolUse
**Architecture**: Dual-emission (observability + intelligence)
