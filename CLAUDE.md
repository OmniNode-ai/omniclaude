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
>
> **Tuning `api_timeout_ms`**: The context injection step has a 1s wall-clock budget. The
> internal HTTP request timeout (`api_timeout_ms`, default 900ms) must stay well below that
> limit — the ~100ms gap covers executor scheduling overhead and result processing. Do not raise
> `api_timeout_ms` to 1000ms or higher; doing so will cause the injection step to regularly
> breach its budget even when the API responds exactly at the timeout boundary.

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

### CI/Tooling Safety

- CI uv version: read from `.github/workflows/ci.yml` pinned version before making
  lock file changes. Do not hardcode the version. Ruff behavior may differ between
  local and CI.
- Prefer auto-merge over immediate merge when multiple PRs target the same branch.
- When modifying branch protection rules, never remove them after adding them.
  If temporary rules were needed, flag them to the user rather than auto-removing.

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

### Headless Mode

The plugin is designed to run without an interactive Claude Code session using `claude -p`
(print mode). This is the primary trigger surface for CLI automation, Slack bots, and webhooks.

#### Basic invocation

```bash
claude -p "Run ticket-pipeline for OMN-1234" \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep,mcp__linear-server__*,mcp__slack__*"
```

#### Required environment variables

| Variable | Purpose | Notes |
|----------|---------|-------|
| `ONEX_RUN_ID` | Unique run identifier for correlation | **Mandatory** — pipeline will not start without this |
| `ONEX_UNSAFE_ALLOW_EDITS` | Permit file edits in headless mode | Set to `1` to allow Write/Edit tools |
| `ANTHROPIC_API_KEY` | Claude API key | Required for `claude -p` |
| `GITHUB_TOKEN` | GitHub CLI auth | Required for PR creation and CI polling |
| `SLACK_BOT_TOKEN` | Slack API token | Required for gate notifications |
| `LINEAR_API_KEY` | Linear API key | Required for ticket updates |

```bash
export ONEX_RUN_ID="pipeline-$(date +%s)-OMN-1234"
export ONEX_UNSAFE_ALLOW_EDITS=1
export ANTHROPIC_API_KEY="..."
export GITHUB_TOKEN="..."
export SLACK_BOT_TOKEN="..."
export LINEAR_API_KEY="..."

claude -p "Run ticket-pipeline for OMN-1234" \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep,mcp__linear-server__*,mcp__slack__*"
```

#### How auth works in headless mode

`ONEX_RUN_ID` is mandatory. It is the correlation key written to:
- `~/.claude/pipelines/ledger.json` (run tracking / duplicate prevention)
- `~/.claude/pipelines/{ticket_id}/state.yaml` (phase state machine)
- `~/.claude/rrh-artifacts/{ticket_id}/` (RRH audit artifacts, if RRH is enabled)

Without `ONEX_RUN_ID` the pipeline cannot distinguish runs and will refuse to start.

MCP server credentials are sourced from the environment at startup:
- **Linear**: `LINEAR_API_KEY` (or `~/.claude/claude_desktop_config.json`)
- **Slack**: `SLACK_BOT_TOKEN`
- **GitHub**: `GITHUB_TOKEN` (used by the `gh` CLI)

Hook scripts (`plugins/onex/hooks/scripts/`) run in the same subprocess environment.
If `KAFKA_BOOTSTRAP_SERVERS` is set, the emit daemon will attempt to connect; if not set,
events are silently dropped (hooks still exit 0).

#### Resume after rate limits

Checkpoints are written to `~/.claude/pipelines/{ticket_id}/state.yaml` after every phase
transition. If the `claude -p` process is interrupted (rate limit, network drop, process
kill), resume from the last completed phase:

```bash
# Resume from where the pipeline stopped
claude -p "Run ticket-pipeline for OMN-1234 --skip-to ci_watch" \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep,mcp__linear-server__*,mcp__slack__*"
```

Auto-detection (OMN-2614) will also pick up the correct phase automatically when no
`--skip-to` flag is provided and a state file already exists.

#### Trigger surfaces

| Surface | How |
|---------|-----|
| **CLI (direct)** | `claude -p "Run ticket-pipeline for OMN-1234" --allowedTools "..."` |
| **Slack bot** | Webhook handler constructs the `claude -p` call and spawns it as a subprocess |
| **Webhook** | HTTP handler receives ticket ID, sets env vars, invokes `claude -p` |
| **Cron / CI** | Shell script iterates tickets and calls `claude -p` per ticket |

### Common Anti-Patterns (DO NOT DO THESE)

Recurring wrong-approach mistakes surfaced from session analysis (875 sessions, 75 `wrong_approach` instances):

| Anti-Pattern | Correct Approach |
|---|---|
| Treating skills as separate from the node system | Skills are orchestration instructions that drive node execution and event emission. They are not an alternative architecture. |
| Reimplementing CI merge branches | Use GitHub Merge Queue (`gh pr merge --auto`). Never re-implement CI merge coordination. |
| plan-to-tickets: stalling on formatting | Attempt ticketization immediately; if it fails due to formatting, fix the minimum formatting and retry. |
| Making `consumer.run()` block the Kafka event loop | Kafka consumers must not block the event loop. Use async patterns or background threads. |
| Removing branch protection rules after adding them | Never remove branch protection rules. If temporary rules were added, flag them to the user. |
| Routing a ticket to a repo based on title alone | Always verify the target repo from the Linear ticket metadata (`repo` field in TicketContract) before starting work. |
| Iterating plans more than 2 self-review passes | After 2 review cycles, present the plan to the user. Do not continue internally iterating. |
| Inventing raw Kafka topic strings outside contract.yaml | All topic names must come from a `ContractConfig` or event contract YAML. Never hardcode topic strings. |
| Writing "call helper X()" in a skill without a real implementation | If logic is needed, it must be a tool, node, or handler — not a phantom callable referenced in markdown. |

### Fail-Fast Design

Hooks exit 0 on infrastructure failure. Data loss is acceptable; UI freeze is not. See **Failure Modes** for the complete table of degraded behaviors.

### Epic Orchestration

- When orchestrating epics with subagents, if a subagent hits a context or rate limit,
  log the failure clearly and continue with remaining tasks. After all other tasks
  complete, report failed tasks with enough context for the user to resume them.
- Ticket routing policy lives in the Decision Store. Query before dispatching.

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
| `INTELLIGENCE_SERVICE_URL` | Overrides default context injection API URL (http://localhost:8053); ignored if `OMNICLAUDE_CONTEXT_API_URL` is explicitly set | No |
| `OMNICLAUDE_CONTEXT_API_URL` | Overrides the omniintelligence HTTP API base URL used for context injection (default: `INTELLIGENCE_SERVICE_URL` or http://localhost:8053) | No |
| `OMNICLAUDE_CONTEXT_API_ENABLED` | Enable (`true`) or disable (`false`) the omniintelligence HTTP API as a context injection pattern source (default: true) | No |
| `OMNICLAUDE_CONTEXT_API_TIMEOUT_MS` | Timeout in milliseconds for omniintelligence API calls during context injection (default: 900, range: 100–10000) | No |
| `DUAL_PUBLISH_LEGACY_TOPICS` | Enable dual-publish to legacy topics during migration window (OMN-2368); set to `1` to enable | No (default: false) |
| `OMNICLAUDE_INTENT_API_URL` | Explicit override for the intent classification endpoint URL (default: `INTELLIGENCE_SERVICE_URL/api/v1/intent/classify` or `http://localhost:8053/api/v1/intent/classify`) | No |
| `OMNICLAUDE_STATE_DIR` | Override the correlation state directory used by intent_classifier CLI (default: `~/.claude/hooks/.state`) | No (dev/test only) |
| `OMNICLAUDE_INTENT_<CLASS>_MODEL` | Override recommended model for a given intent class (e.g. `OMNICLAUDE_INTENT_SECURITY_MODEL=claude-opus-4-6`) | No |
| `OMNICLAUDE_INTENT_<CLASS>_TEMPERATURE` | Override temperature hint for a given intent class | No |
| `OMNICLAUDE_INTENT_<CLASS>_VALIDATORS` | Override validator list for a given intent class (comma-separated) | No |
| `OMNICLAUDE_INTENT_<CLASS>_SANDBOX` | Override sandbox setting for a given intent class (`none`, `standard`, `enforced`) | No |

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
