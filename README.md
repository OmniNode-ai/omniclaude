# OmniClaude

> Claude Code integration layer for the ONEX platform — hooks, routing, intelligence, and agent coordination.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Mypy](https://img.shields.io/badge/mypy-strict-blue)](https://mypy.readthedocs.io/)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://pre-commit.com/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## What is OmniClaude?

OmniClaude is a Claude Code plugin that instruments every Claude Code session with typed ONEX events. On each prompt it routes the request to a specialized agent (from a library of 53), enriches the context with learned patterns retrieved from the ONEX intelligence layer, enforces architectural compliance via pattern advisory, and — when local LLMs are available — optionally delegates tasks to them through a quality-gated orchestrator. All hook activity is emitted asynchronously to Kafka via a Unix socket daemon so the Claude Code UI is never blocked.

## Hook Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Claude Code Session                                                    │
│                                                                         │
│  SessionStart ──────────────────────────────────────────────────────►  │
│    SYNC:  start emit daemon if not running                              │
│    ASYNC: emit session-started.v1                                       │
│                                                                         │
│  UserPromptSubmit ──────────────────────────────────────────────────►  │
│    SYNC:  detect automated workflow → route → enrich → pattern advisory │
│           → (optional) local delegation                                 │
│    ASYNC: emit prompt-submitted.v1 (100-char preview)                   │
│           emit claude-hook-event.v1 (full prompt, intelligence topic)   │
│                                                                         │
│  PreToolUse (Edit | Write) ─────────────────────────────────────────►  │
│    SYNC:  authorization check                                           │
│                                                                         │
│  PostToolUse (Read|Write|Edit|Bash|Glob|Grep|Task|Skill|...) ───────►  │
│    SYNC:  pattern compliance enforcement                                │
│    ASYNC: emit tool-executed.v1, capture tool content                   │
│                                                                         │
│  SessionEnd ────────────────────────────────────────────────────────►  │
│    ASYNC: emit session-ended.v1, session outcome                        │
└─────────────────────────────────────────────────────────────────────────┘
                              │ Unix socket
                              ▼
                    Emit Daemon (/tmp/omniclaude-emit.sock)
                              │
                              ▼
                    Kafka / Redpanda (ONEX event bus)
```

**Design principle**: Hooks never block the Claude Code UI. Infrastructure failures degrade gracefully — events are dropped, not retried, and hooks always exit 0 (except for a missing Python interpreter, which exits 1 with a clear fix message).

## What This Repo Provides

- **5 Claude Code hooks** — SessionStart, UserPromptSubmit, PreToolUse (Edit/Write), PostToolUse, SessionEnd — each implemented as a shell script delegating to Python handler modules
- **53 agent YAML definitions** for specialized routing (API design, debugging, PR review, testing, devops, and more)
- **55+ skills and 4 slash commands** — reusable methodologies and user-invocable workflows
- **Unix socket emit daemon** — non-blocking Kafka emission across hook invocations via a persistent background process
- **LLM-based agent routing** — prompt-to-agent matching with fuzzy fallback to `polymorphic-agent`
- **Multi-channel context enrichment** — learned patterns from Qdrant injected into the system prompt
- **Pattern compliance enforcement** — post-tool architectural advisories from the ONEX intelligence layer
- **Local LLM delegation orchestrator** — quality-gated task delegation to on-premises models
- **Typed ONEX event schemas** — frozen Pydantic models for all hook events with automatic secret redaction

## Quick Start

```bash
git clone https://github.com/OmniNode-ai/omniclaude.git
cd omniclaude
uv sync
uv run pytest tests/ -m unit
```

Copy and configure environment:

```bash
cp .env.example .env
# Edit .env — set KAFKA_BOOTSTRAP_SERVERS, POSTGRES_* as needed
```

Deploy the plugin to Claude Code:

```bash
uv run deploy-local-plugin
# or use the /deploy-local-plugin skill from within a Claude Code session
```

Verify the emit daemon is reachable:

```bash
python plugins/onex/hooks/lib/emit_client_wrapper.py status --json
```

Validate the hook configuration:

```bash
jq . plugins/onex/hooks/hooks.json
```

## Project Structure

```
omniclaude/
├── src/omniclaude/              # Main Python package
│   ├── hooks/                   # Core hook module
│   │   ├── schemas.py           # Frozen Pydantic event models
│   │   ├── topics.py            # Kafka topic definitions (TopicBase enum)
│   │   ├── handler_context_injection.py
│   │   ├── handler_event_emitter.py
│   │   └── contracts/           # YAML contracts + Python models
│   ├── aggregators/             # Session aggregation
│   ├── cli/                     # CLI entry points
│   ├── config/                  # Pydantic Settings
│   ├── contracts/               # Cross-cutting contract models
│   ├── handlers/                # Business logic handlers
│   ├── lib/                     # Shared utilities
│   ├── nodes/                   # ONEX node implementations
│   ├── publisher/               # Event publisher
│   └── runtime/                 # Runtime support
├── plugins/onex/                # Claude Code plugin root
│   ├── hooks/
│   │   ├── hooks.json           # Hook configuration (tool matchers, script paths)
│   │   ├── scripts/             # Shell handlers (session-start.sh, user-prompt-submit.sh, …)
│   │   └── lib/                 # 55+ Python handler modules
│   │       ├── emit_client_wrapper.py       # Public: event emission via daemon
│   │       ├── context_injection_wrapper.py # Public: inject learned patterns
│   │       ├── route_via_events_wrapper.py  # Public: agent routing
│   │       ├── correlation_manager.py       # Public: correlation ID persistence
│   │       ├── delegation_orchestrator.py   # Local LLM delegation
│   │       ├── pattern_enforcement.py       # Compliance enforcement
│   │       └── …                            # Internal implementation modules
│   ├── agents/configs/          # 53 agent YAML definitions
│   ├── commands/                # 4 slash command definitions
│   └── skills/                  # 55+ skill definitions
├── docs/                        # Architecture decision records and proposals
├── tests/                       # Test suite (unit, integration)
├── pyproject.toml               # Package config
└── CLAUDE.md                    # Development guide and reference
```

## Kafka Topics

Topics follow the ONEX canonical format: `onex.{kind}.{producer}.{event-name}.v{n}`

| Topic | Kind | Purpose |
|-------|------|---------|
| `onex.evt.omniclaude.session-started.v1` | evt | Session initialization |
| `onex.evt.omniclaude.session-ended.v1` | evt | Session close |
| `onex.evt.omniclaude.prompt-submitted.v1` | evt | 100-char prompt preview (broad access) |
| `onex.evt.omniclaude.tool-executed.v1` | evt | Tool completion metrics |
| `onex.cmd.omniintelligence.claude-hook-event.v1` | cmd | Full prompt — intelligence only (restricted) |
| `onex.cmd.omniintelligence.tool-content.v1` | cmd | Tool content for pattern learning (restricted) |
| `onex.cmd.omninode.routing-requested.v1` | cmd | Agent routing requests |
| `onex.evt.omniclaude.routing-decision.v1` | evt | Routing outcomes and confidence scores |
| `onex.evt.omniclaude.manifest-injected.v1` | evt | Agent manifest injection tracking |
| `onex.evt.omniclaude.context-injected.v1` | evt | Context enrichment tracking |
| `onex.evt.omniclaude.task-delegated.v1` | evt | Local LLM delegation events |
| `onex.cmd.omniintelligence.compliance-evaluate.v1` | cmd | Compliance evaluation requests |

Full topic list: `src/omniclaude/hooks/topics.py`

## Privacy Design

`prompt_preview` captures the **first 100 characters** of each user prompt only — full prompt content is never stored in observability topics. The field also automatically redacts secrets: OpenAI keys (`sk-*`), AWS keys (`AKIA*`), GitHub tokens (`ghp_*`), Slack tokens (`xox*`), PEM keys, Bearer tokens, and passwords in URLs. Full prompt content is sent exclusively to the access-restricted `onex.cmd.omniintelligence.*` topics consumed only by the OmniIntelligence service.

## Development

```bash
uv sync --group dev              # Install with dev tools

uv run pytest tests/ -m unit -v  # Unit tests (no services required)
uv run pytest tests/ -v          # All tests

uv run ruff check src/ tests/    # Lint
uv run ruff format src/ tests/   # Format
uv run mypy src/omniclaude/      # Type check (strict)
uv run bandit -r src/omniclaude/ # Security scan
```

Integration tests require Kafka:

```bash
KAFKA_INTEGRATION_TESTS=1 uv run pytest -m integration
```

## Documentation

- [CLAUDE.md](CLAUDE.md) — Architecture, invariants, failure modes, performance budgets, and where to change things
- [docs/](docs/) — Architecture decision records and design proposals

Open an issue or email contact@omninode.ai.
