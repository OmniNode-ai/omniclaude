# CLAUDE.md

This file provides operational guidance for working with code in this repository.

---

## Repository Invariants

These rules are non-negotiable. Violations will cause production issues.

**No backwards compatibility**: This repository has no external consumers. Schemas, APIs, and interfaces may change without deprecation periods. If something needs to change, change it.

| Invariant | Rationale |
|-----------|-----------|
| Hook scripts must **never block** on Kafka | Blocking hooks freeze Claude Code UI |
| Only preview-safe data goes to `onex.evt.*` topics | Observability topics have broad access |
| Full prompts go **only** to `onex.cmd.omniintelligence.*` | Intelligence topics are access-restricted |
| All event schemas are **frozen** (`frozen=True`) | Events are immutable after emission |
| `emitted_at` timestamps must be **explicitly injected** | No `datetime.now()` defaults for deterministic testing |
| SessionStart must be **idempotent** | May be called multiple times on reconnect |
| Hooks must exit 0 unless blocking is intentional | Non-zero exit blocks the tool/prompt |

---

## Failure Modes

What happens when infrastructure is unavailable:

| Failure | Behavior | Exit Code | Data Loss |
|---------|----------|-----------|-----------|
| **Emit daemon down** | Events dropped, hook continues | 0 | Yes (events) |
| **Kafka unavailable** | Daemon buffers briefly, then drops | 0 | Yes (events) |
| **PostgreSQL down** | Logging skipped if `ENABLE_POSTGRES=true` | 0 | Yes (logs) |
| **Routing timeout (5s)** | Fallback to `polymorphic-agent` | 0 | No |
| **Malformed stdin JSON** | Hook logs error, passes through empty | 0 | No |
| **Agent YAML not found** | Uses default agent, logs warning | 0 | No |
| **Context injection fails** | Proceeds without patterns | 0 | No |
| **No valid Python found** | Hook exits with actionable error | 1 | No |

**Design principle**: Hooks never block Claude Code. Data loss is acceptable; UI freeze is not.

**Exception**: `find_python()` hard-fails (exit 1) if no valid Python interpreter is found. This is intentional — running hooks against the wrong Python produces non-reproducible bugs. The error message tells the user exactly how to fix it (deploy the plugin or set `OMNICLAUDE_PROJECT_ROOT`). See OMN-2051.

**Logging**: Failures are logged to `~/.claude/hooks.log` when `LOG_FILE` is set.

---

## Performance Budgets

Targets for **synchronous path only** (excludes backgrounded processes):

| Hook | Budget | What Blocks | What's Backgrounded |
|------|--------|-------------|---------------------|
| SessionStart | <50ms | Daemon check, stdin read | Kafka emit, Postgres log |
| SessionEnd | <50ms | stdin read | Kafka emit, Postgres log |
| UserPromptSubmit | <500ms | Routing, agent load, context injection | Kafka emit, intelligence requests |
| PostToolUse | <100ms | stdin read, quality check | Kafka emit, content capture |

If hooks exceed budget, check:
1. Network latency to routing service
2. Agent YAML file I/O
3. Context injection database queries

---

## Where to Change Things

| Change | Location | Notes |
|--------|----------|-------|
| Event schemas | `src/omniclaude/hooks/schemas.py` | Frozen Pydantic models |
| Kafka topics | `src/omniclaude/hooks/topics.py` | TopicBase enum |
| Hook configuration | `plugins/onex/hooks/hooks.json` | Tool matchers, script paths |
| Hook scripts | `plugins/onex/hooks/scripts/*.sh` | Shell handlers |
| Handler modules | `plugins/onex/hooks/lib/*.py` | Python business logic |
| Agent definitions | `plugins/onex/agents/configs/*.yaml` | Agent capabilities, triggers |
| Commands | `plugins/onex/commands/*.md` | User-invocable workflows |
| Skills | `plugins/onex/skills/*/SKILL.md` | Reusable methodologies |

### Public Entrypoints (stable API)

These modules are intended for external use:

| Module | Purpose |
|--------|---------|
| `emit_client_wrapper.py` | Event emission via daemon |
| `context_injection_wrapper.py` | Inject learned patterns |
| `route_via_events_wrapper.py` | Agent routing |
| `simple_agent_loader.py` | Load agent YAML |
| `correlation_manager.py` | Correlation ID persistence |

**All other modules in `plugins/onex/hooks/lib/` are internal implementation details.**

---

## Environment Variables

### Canonical Variables

| Variable | Purpose | Required |
|----------|---------|----------|
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka connection string | Yes (for events) |
| `KAFKA_ENVIRONMENT` | Topic prefix (`dev`, `staging`, `prod`) | Yes |
| `POSTGRES_HOST/PORT/DATABASE/USER/PASSWORD` | Database connection | No |
| `ENABLE_POSTGRES` | Enable database logging | No (default: false) |
| `USE_EVENT_ROUTING` | Enable agent routing via Kafka | No (default: false) |
| `ENFORCEMENT_MODE` | Quality enforcement: `warn`, `block`, `silent` | No (default: warn) |
| `OMNICLAUDE_PROJECT_ROOT` | Explicit project root for dev-mode Python venv resolution | No (dev only) |
| `PLUGIN_PYTHON_BIN` | Override Python interpreter path for hooks (escape hatch) | No |

---

## Project Structure

```
omniclaude/
├── src/omniclaude/              # Main Python package
│   ├── hooks/                   # Core hooks module
│   │   ├── schemas.py           # ONEX event schemas
│   │   ├── topics.py            # Kafka topic definitions
│   │   ├── handler_context_injection.py
│   │   ├── handler_event_emitter.py
│   │   └── contracts/           # YAML contracts + Python models
│   ├── aggregators/             # Session aggregation
│   ├── config/                  # Pydantic Settings
│   ├── handlers/                # Business logic
│   └── nodes/                   # ONEX nodes
├── plugins/onex/                # Claude Code plugin
│   ├── hooks/                   # Hook scripts and library
│   │   ├── hooks.json           # Hook configuration
│   │   ├── scripts/             # Shell handlers
│   │   └── lib/                 # Python handler modules
│   ├── agents/configs/          # Agent YAML definitions
│   ├── commands/                # Slash command definitions
│   └── skills/                  # Skill definitions
├── tests/                       # Test suite
└── _archive/                    # Archived legacy code
```

---

## Hook Data Flow

### Input Format

All hooks receive JSON via stdin from Claude Code:

```json
// SessionStart
{"sessionId": "uuid", "projectPath": "/path", "cwd": "/path"}

// UserPromptSubmit
{"sessionId": "uuid", "prompt": "user text"}

// PostToolUse
{"sessionId": "uuid", "tool_name": "Read", "tool_input": {...}, "tool_response": {...}}
```

### UserPromptSubmit Flow (most complex)

```
stdin JSON
    │
    ├─► [ASYNC] Emit to Kafka (dual-emission)
    │       ├─► onex.evt.omniclaude.prompt-submitted.v1 (100-char preview)
    │       └─► onex.cmd.omniintelligence.claude-hook-event.v1 (full prompt)
    │
    ▼ [SYNC - counts toward 500ms budget]
agent_detector.py → detect automated workflow
    │
    ▼
route_via_events_wrapper.py → get agent selection
    │
    ▼
simple_agent_loader.py → load agent YAML
    │
    ▼
context_injection_wrapper.py → load learned patterns
    │
    ▼
Output: JSON with hookSpecificOutput.additionalContext
```

### Emit Daemon Architecture

```
Hook Script → emit_via_daemon() → Unix Socket → Emit Daemon → Kafka
                                  /tmp/omniclaude-emit.sock
```

The daemon:
- Started by SessionStart hook if not running
- Persists across hook invocations
- Buffers events briefly if Kafka slow
- Drops events (with log) if Kafka unavailable

---

## Kafka Topics

### Topic Naming Convention

```
onex.{kind}.{producer}.{event-name}.v{n}

kind: evt (observability, broad access) | cmd (commands, restricted access)
producer: omniclaude | omninode | omniintelligence
```

### Core Topics

| Topic | Kind | Access | Purpose |
|-------|------|--------|---------|
| `onex.evt.omniclaude.session-started.v1` | evt | Broad | Session observability |
| `onex.evt.omniclaude.prompt-submitted.v1` | evt | Broad | 100-char preview only |
| `onex.evt.omniclaude.tool-executed.v1` | evt | Broad | Tool metrics |
| `onex.cmd.omniintelligence.claude-hook-event.v1` | cmd | Restricted | Full prompts |
| `onex.cmd.omniintelligence.tool-content.v1` | cmd | Restricted | File contents |

### Access Control

**Current state**: Honor system. No Kafka ACLs configured.

**Intended state**:
- `evt.*` topics: Any consumer may subscribe
- `cmd.omniintelligence.*` topics: Only OmniIntelligence service
- ACL policy: Managed via Redpanda Console (192.168.86.200:8080)

---

## Event Schemas

**Location**: `src/omniclaude/hooks/schemas.py`

| Schema | Purpose |
|--------|---------|
| `ModelHookSessionStartedPayload` | Session initialization |
| `ModelHookSessionEndedPayload` | Session termination |
| `ModelHookPromptSubmittedPayload` | User prompt (preview + length) |
| `ModelHookToolExecutedPayload` | Tool completion |
| `ModelHookContextInjectedPayload` | Context injection tracking |

### Privacy-Sensitive Fields

| Field | Risk | Mitigation |
|-------|------|------------|
| `prompt_preview` | User input | Auto-sanitized, 100 chars max |
| `working_directory` | Usernames | Anonymize in analytics |
| `git_branch` | Ticket IDs | Treat as PII |
| `summary` | Code snippets | 500 char limit |

### Automatic Secret Redaction

`prompt_preview` redacts: OpenAI keys (`sk-*`), AWS keys (`AKIA*`), GitHub tokens (`ghp_*`), Slack tokens (`xox*`), PEM keys, Bearer tokens, passwords in URLs.

---

## Declarative Node Types

### Agents (YAML)

**Location**: `plugins/onex/agents/configs/*.yaml`

```yaml
schema_version: "1.0.0"
agent_type: "api_architect"

agent_identity:
  name: "agent-api-architect"
  description: "Designs RESTful APIs"
  color: "blue"

activation_patterns:
  explicit_triggers: ["api design", "openapi"]
  context_triggers: ["designing HTTP endpoints"]
```

Agents are selected by matching `activation_patterns` against user prompts.

### Commands (Markdown)

**Location**: `plugins/onex/commands/*.md`

User-invocable via `/command-name`. Examples: `/parallel-solve`, `/ci-failures`, `/pr-review-dev`

### Skills (SKILL.md)

**Location**: `plugins/onex/skills/*/SKILL.md`

Reusable methodologies and executable scripts. Referenced by agents and commands.

---

## Workflow Guidance

### For Automated Workflows (`/parallel-solve`)

Prefer dispatching to `polymorphic-agent`:

```python
Task(
    subagent_type="polymorphic-agent",
    description="Review PR #30",
    prompt="..."
)
```

This ensures ONEX capabilities, intelligence integration, and observability.

### For Human Developers

Run tools directly. The polymorphic-agent pattern is for automated workflows, not a repository invariant.

```bash
# These are fine for humans
pytest tests/ -v
ruff check src/
mypy src/omniclaude/
```

---

## Dependencies

**File**: `pyproject.toml`


### Installation

```bash
uv sync              # Install dependencies
uv sync --group dev  # Include dev tools
```

---

## Testing

```bash
pytest tests/ -v                                    # All tests
pytest tests/ -m unit -v                            # Unit only (no services)
pytest tests/ --cov=src/omniclaude --cov-report=html  # Coverage
KAFKA_INTEGRATION_TESTS=1 pytest -m integration     # Integration (needs Kafka)
```

**Kafka is mocked** in unit tests via `conftest.py`.

---

## Quick Reference

### Validation Commands

```bash
jq . plugins/onex/hooks/hooks.json          # Validate hook config
ls -la plugins/onex/hooks/scripts/*.sh      # Check script permissions
python plugins/onex/hooks/lib/emit_client_wrapper.py status --json  # Daemon status
```

### Linting

```bash
ruff check src/ tests/
ruff format src/ tests/
mypy src/omniclaude/
bandit -r src/omniclaude/
```

---

**Last Updated**: 2026-02-01
**Version**: 0.2.1
