# CLAUDE.md

> **Python**: 3.12+ | **Plugin**: Claude Code hooks/agents | **Shared Standards**: See **`~/.claude/CLAUDE.md`** for shared development standards (Python, uv, Git, testing, architecture principles) and infrastructure configuration (PostgreSQL, Kafka/Redpanda, Docker networking, environment variables).

---

## Repo Boundaries

| This repo owns | Another repo owns |
|----------------|-------------------|
| Claude Code hooks (SessionStart, UserPromptSubmit, PostToolUse, SessionEnd) | **omniintelligence** -- intelligence processing, code analysis |
| Agent YAML definitions (`plugins/onex/agents/configs/`) | **omniarchon** -- search service, bridge services |
| Slash commands and skills (`plugins/onex/commands/`, `plugins/onex/skills/`) | **omnibase_core** -- ONEX runtime, node framework, contracts |
| Event emission via Unix socket daemon | **omnibase_infra** -- Kubernetes, deployment |
| Context injection (learned patterns into prompts) | |
| Agent routing (prompt-to-agent matching) | |

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
| **Migration freeze active** (`.migration_freeze`) | DB-SPLIT in progress (OMN-2055) — no new schema migrations |

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
| **Agent loader timeout (1s)** | Falls back to empty YAML, hook continues | 0 | No |
| **Context injection timeout (1s)** | Proceeds without patterns, hook continues | 0 | No |
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
| UserPromptSubmit | <500ms typical (~15s worst-case with delegation) | Routing, candidate formatting, context injection, pattern advisory, local delegation | Kafka emit, intelligence requests |
| PostToolUse | <100ms | stdin read, quality check | Kafka emit, content capture |

> **Note**: UserPromptSubmit's 500ms target is for typical runs. Worst-case with all timeout
> paths (routing 5s + injection 1s + advisory 1s + delegation 8s) is ~15s. Without delegation
> enabled, worst-case is ~7s. Agent YAML loading was removed from the sync path in OMN-1980 —
> Claude loads the selected agent's YAML on-demand. These timeouts are safety nets; normal
> execution stays well under 500ms.

If hooks exceed budget, check:
1. Network latency to routing service
2. Context injection database queries

---

## Git/CI Standards

### Branch Naming

Linear generates branch names: `jonahgabriel/omn-XXXX-description`

### Commit Format

```
type(scope): description [OMN-XXXX]
```

Types: `feat`, `fix`, `chore`, `refactor`, `docs`

### CI Pipeline

Single consolidated workflow in `.github/workflows/ci.yml` (OMN-2228):

| Job | What it does | Gate |
|-----|-------------|------|
| **quality** | ruff format + ruff lint + mypy | Quality Gate |
| **pyright** | Pyright type checking on `src/omniclaude/` | Quality Gate |
| **check-handshake** | Architecture handshake vs omnibase_core | Quality Gate |
| **enum-governance** | ONEX enum casing, literal-vs-enum, duplicates | Quality Gate |
| **exports-validation** | `__all__` exports match actual definitions | Quality Gate |
| **cross-repo-validation** | Kafka import guard (ARCH-002) | Quality Gate |
| **migration-freeze** | Blocks new migrations when `.migration_freeze` exists | Quality Gate |
| **onex-validation** | ONEX naming, contracts, method signatures | Quality Gate |
| **security-python** | Bandit security linter (Medium+ severity) | Security Gate |
| **detect-secrets** | Secret detection scan | Security Gate |
| **test** | pytest with 5-way parallel split (`pytest-split`) | Tests Gate |
| **hooks-tests** | Hook scripts and handler modules | Tests Gate |
| **agent-framework-tests** | Agent YAML loading and framework validation | Tests Gate |
| **database-validation** | DB schema consistency checks | Tests Gate |
| **merge-coverage** | Combines coverage from 5 test shards, uploads to Codecov | (none) |
| **build** | Docker image build + Trivy vulnerability scan | (downstream) |
| **deploy** | Staging (develop) / Production (main) | (downstream) |

### Branch Protection

Three gate aggregators per CI/CD Standards v2 (`required-checks.yaml`):
- **"Quality Gate"** -- aggregates all code quality checks
- **"Tests Gate"** -- aggregates all test suites
- **"Security Gate"** -- aggregates security scanning

Gate names are API-stable. Do not rename without following the Branch Protection Migration Safety procedure in `CI_CD_STANDARDS.md`.

---

## Code Quality

Principles specific to this repo (see **Repository Invariants** for the complete list):

- **Frozen event schemas**: All Pydantic event models use `frozen=True`, `extra="ignore"`, `from_attributes=True`
- **Explicit timestamp injection**: No `datetime.now()` defaults -- timestamps are injected by callers for deterministic testing
- **Automatic secret redaction**: `prompt_preview` redacts API keys (OpenAI, AWS, GitHub, Slack), PEM keys, Bearer tokens, passwords in URLs
- **Privacy-aware dual emission**: Preview-safe data (100 chars) goes to `onex.evt.*` topics; full prompts go only to `onex.cmd.omniintelligence.*`

---

## Workflow Principles

### Hook Development

Hook changes deploy via the plugin cache (`~/.claude/plugins/cache/`). Test locally before deploying:

1. Edit code in this repo
2. Run unit tests (`pytest tests/ -m unit -v`)
3. Deploy plugin to cache
4. Verify hooks work in a live Claude Code session

### Automated Workflows (`/parallel-solve`)

Prefer dispatching to `polymorphic-agent`:

```python
Task(
    subagent_type="onex:polymorphic-agent",
    description="Review PR #30",
    prompt="..."
)
```

This ensures ONEX capabilities, intelligence integration, and observability.

### Human Developers

Run tools directly. The polymorphic-agent pattern is for automated workflows, not a repository invariant.

```bash
# These are fine for humans
pytest tests/ -v
ruff check src/
mypy src/omniclaude/
```

### Fail-Fast Design

Hooks exit 0 on infrastructure failure. Data loss is acceptable; UI freeze is not. See **Failure Modes** for the complete table of degraded behaviors.

---

## Debugging

### Log Files

- **Hook logs**: `~/.claude/hooks.log` (when `LOG_FILE` is set)

### Diagnostic Commands

```bash
python plugins/onex/hooks/lib/emit_client_wrapper.py status --json  # Daemon status
jq . plugins/onex/hooks/hooks.json                                  # Validate hook config
ls -la plugins/onex/hooks/scripts/*.sh                              # Check script permissions
```

### Common Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Events not emitting | Daemon not started | SessionStart hook must run first to start the daemon |
| Hook fails with exit 1 | Wrong Python interpreter | Check `find_python()` logic; set `OMNICLAUDE_PROJECT_ROOT` or `PLUGIN_PYTHON_BIN` |
| Routing returns `polymorphic-agent` for everything | Routing service timeout | Check network connectivity to routing service (5s timeout) |
| Context injection empty | Database unreachable | Check `POSTGRES_HOST`/`POSTGRES_PORT` in `.env`; injection has 1s timeout |

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
| `correlation_manager.py` | Correlation ID persistence |

**All other modules in `plugins/onex/hooks/lib/` are internal implementation details.**

---

## Environment Variables

### Canonical Variables

| Variable | Purpose | Required |
|----------|---------|----------|
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka connection string | Yes (for events) |
| `KAFKA_ENVIRONMENT` | Environment label for logging/observability (not used for topic prefixing) | No |
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
│   ├── cli/                     # CLI entry points
│   ├── config/                  # Pydantic Settings
│   ├── contracts/               # Cross-cutting contract models
│   ├── handlers/                # Business logic
│   ├── lib/                     # Shared utilities
│   ├── nodes/                   # ONEX nodes
│   ├── publisher/               # Event publisher
│   └── runtime/                 # Runtime support
├── plugins/onex/                # Claude Code plugin
│   ├── hooks/                   # Hook scripts and library
│   │   ├── hooks.json           # Hook configuration
│   │   ├── scripts/             # Shell handlers
│   │   └── lib/                 # Python handler modules
│   ├── agents/configs/          # Agent YAML definitions
│   ├── commands/                # Slash command definitions
│   └── skills/                  # Skill definitions
└── tests/                       # Test suite
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
route_via_events_wrapper.py → get agent candidates + fuzzy best
    │
    ▼ (OMN-1980: agent YAML loading removed from sync path)
    │  Claude loads the selected agent's YAML on-demand after seeing candidates
    │
    ▼
context_injection_wrapper.py → load learned patterns
    │
    ▼
Output: JSON with hookSpecificOutput.additionalContext
        (includes candidate list for Claude to select from)
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

## Python/Linting

```bash
ruff check src/ tests/
ruff format src/ tests/
mypy src/omniclaude/
bandit -r src/omniclaude/
```

---

## Completion Criteria

What "done" means for changes to this repo:

- All unit tests pass (`pytest tests/ -m unit -v`)
- Hooks don't block Claude Code (respect performance budgets)
- CI pipeline passes (all 13 jobs green)
- Events emit correctly (if touching event schemas or emission)
- No secrets in `evt.*` topics
- Hook scripts exit 0 on infrastructure failure

---

**Last Updated**: 2026-02-13
**Version**: 0.3.0
