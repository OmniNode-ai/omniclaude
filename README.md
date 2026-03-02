# OmniClaude

> Claude Code integration layer for the ONEX platform — hooks, routing, intelligence, and agent coordination.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Mypy](https://img.shields.io/badge/mypy-strict-blue)](https://mypy.readthedocs.io/)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://pre-commit.com/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Integration Tiers

Tiers are **auto-detected at every SessionStart** — no configuration required.
A banner appears in every prompt's context showing the current tier and probe age.

| Tier | Config needed | What you get |
|------|--------------|--------------|
| **Standalone** | None | 90+ skills, 54 agents, hooks fire (events silently dropped) |
| **Event Bus** | `KAFKA_BOOTSTRAP_SERVERS` | + routing telemetry, Kafka event emission |
| **Full ONEX** | Full stack running | + context enrichment, semantic memory, pattern compliance |

See [QUICKSTART.md](QUICKSTART.md) for step-by-step setup instructions for each tier.

## What is OmniClaude?

OmniClaude is a Claude Code plugin that instruments every Claude Code session with typed ONEX events. On each prompt it routes the request to a specialized agent (from a library of 54), enriches the context with learned patterns retrieved from the ONEX intelligence layer, enforces architectural compliance via pattern advisory, and — when local LLMs are available — optionally delegates tasks to them through a quality-gated orchestrator. All hook activity is emitted asynchronously to Kafka via a Unix socket daemon so the Claude Code UI is never blocked.

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
- **54 agent YAML definitions** for specialized routing (API design, debugging, PR review, testing, devops, and more)
- **90+ skills** — reusable methodologies and user-invocable workflows (see [Skills](#skills) below)
- **Unix socket emit daemon** — non-blocking Kafka emission across hook invocations via a persistent background process
- **LLM-based agent routing** — prompt-to-agent matching with fuzzy fallback to `polymorphic-agent`
- **Multi-channel context enrichment** — learned patterns from Qdrant injected into the system prompt
- **Pattern compliance enforcement** — post-tool architectural advisories from the ONEX intelligence layer
- **Local LLM delegation orchestrator** — quality-gated task delegation to on-premises models
- **Typed ONEX event schemas** — frozen Pydantic models for all hook events with automatic secret redaction

## Quick Start

For the fastest path (zero config, Standalone tier):

```bash
git clone https://github.com/OmniNode-ai/omniclaude.git
cd omniclaude
uv sync
# In Claude Code: /deploy-local-plugin
```

For Event Bus or Full ONEX tier setup, see [QUICKSTART.md](QUICKSTART.md).

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
│   │   └── lib/                 # Python handler modules
│   │       ├── emit_client_wrapper.py       # Public: event emission via daemon
│   │       ├── context_injection_wrapper.py # Public: inject learned patterns
│   │       ├── route_via_events_wrapper.py  # Public: agent routing
│   │       ├── correlation_manager.py       # Public: correlation ID persistence
│   │       ├── delegation_orchestrator.py   # Local LLM delegation
│   │       ├── pattern_enforcement.py       # Compliance enforcement
│   │       └── …                            # Internal implementation modules
│   ├── agents/configs/          # 54 agent YAML definitions
│   └── skills/                  # 90+ skill definitions
├── docs/                        # Architecture decision records and proposals
├── tests/                       # Test suite (unit, integration)
├── pyproject.toml               # Package config
└── CLAUDE.md                    # Development guide and reference
```

## Skills

Skills are invoked in Claude Code as `onex:<skill-name>`. All skills live under `plugins/onex/skills/`.

### Pipeline & Workflow

| Skill | Description |
|-------|-------------|
| `onex:ticket-work` | Contract-driven ticket execution — intake, research, spec, implement, review, done phases with human gates |
| `onex:ticket-pipeline` | Autonomous per-ticket pipeline — chains ticket-work → local-review → PR → CI → auto-merge unattended |
| `onex:local-review` | Local code review loop — iterates review/fix/commit cycles without pushing |
| `onex:pr-watch` | Poll GitHub PR for review feedback, auto-fix issues, and report terminal state |
| `onex:ci-watch` | Poll GitHub Actions CI for a PR, auto-fix failures, and report terminal state |
| `onex:ci-failures` | Fetch and analyze GitHub Actions CI failures for debugging |
| `onex:ci-fix-pipeline` | Self-healing CI pipeline — 3-attempt retry budget with strategy rotation and autonomous fix loop |
| `onex:pr-polish` | Full PR readiness loop — resolve conflicts, address review comments and CI failures |
| `onex:pr-release-ready` | Fix ALL issues including nitpicks before release |
| `onex:pr-review-dev` | Fix critical/major/minor issues (review + CI failures) |
| `onex:auto-merge` | Merge a GitHub PR when all gates pass; uses Slack HIGH_RISK gate by default |
| `onex:finishing-a-development-branch` | Guide completing development work — presents structured options for merge, PR, or cleanup |

### Code Review

| Skill | Description |
|-------|-------------|
| `onex:pr-review` | Comprehensive PR review with strict priority-based organization and merge readiness assessment |
| `onex:requesting-code-review` | Dispatch code-reviewer subagent to verify implementation before proceeding |
| `onex:receiving-code-review` | Handle incoming review feedback with technical rigor, not blind implementation |
| `onex:review-cycle` | Guided local code review with human checkpoints and learning mode |

### Linear & Project Management

| Skill | Description |
|-------|-------------|
| `onex:linear` | Create, update, list, and manage Linear tickets with requirements and definition of done |
| `onex:linear-triage` | Scan all non-completed tickets, verify status against actual PR state, auto-mark done |
| `onex:linear-housekeeping` | Full triage + organize orphans into epics + sync MASTER_TICKET_PLAN.md |
| `onex:linear-epic-org` | Organize orphaned tickets into epics — auto-creates obvious groupings, gates on ambiguous cases |
| `onex:linear-insights` | Daily deep dive reports and velocity-based project completion estimates |
| `onex:create-followup-tickets` | Create Linear tickets from code review issues found in the current session |
| `onex:create-ticket` | Create a single Linear ticket from args, contract file, or plan milestone |
| `onex:ticket-plan` | Generate a prioritized master ticket plan from Linear with dependency ordering |
| `onex:ticket-plan-sync` | Sync MASTER_TICKET_PLAN.md with current Linear state |
| `onex:plan-to-tickets` | Batch create Linear tickets from a plan markdown file |
| `onex:project-status` | Linear insights dashboard — velocity, status, and project completion estimates |
| `onex:decompose-epic` | Analyze a Linear epic description and create sub-tickets as Linear children |

### Architecture & Design

| Skill | Description |
|-------|-------------|
| `onex:brainstorming` | Refine rough ideas into fully-formed designs through collaborative questioning |
| `onex:writing-plans` | Create comprehensive implementation plans with file paths, code examples, and verification steps |
| `onex:decision-store` | Record, query, and conflict-check architectural decisions across the platform |
| `onex:executing-plans` | Execute a complete implementation plan — creates tickets then routes to epic-team or ticket-pipeline |
| `onex:plan-ticket` | Generate a copyable ticket contract template |
| `onex:generate-ticket-contract` | Auto-draft a ModelTicketContract YAML from ticket context |
| `onex:contract-compliance-check` | Pre-merge seam validation — returns PASS/WARN/BLOCK with emergency bypass support |

### Testing & Debugging

| Skill | Description |
|-------|-------------|
| `onex:systematic-debugging` | Four-phase debugging framework (root cause → pattern analysis → hypothesis → implement) |
| `onex:test-driven-development` | Write the test first, watch it fail, write minimal code to pass |
| `onex:testing-anti-patterns` | Prevent testing mock behavior, production pollution, and mocking without understanding |
| `onex:condition-based-waiting` | Replace arbitrary timeouts with condition polling to eliminate flaky tests |
| `onex:defense-in-depth` | Multi-layer validation — makes invalid data structurally impossible deep in execution |
| `onex:root-cause-tracing` | Trace bugs backward through call stack to find the original trigger |
| `onex:verification-before-completion` | Require running verification commands before claiming work is complete |

### Integration Health

| Skill | Description |
|-------|-------------|
| `onex:gap-analysis` | Cross-repo integration audit — finds Kafka drift, type mismatches, FK drift, API drift |
| `onex:gap-cycle` | Full detect → fix → verify cycle (gap-analysis → gap-fix → golden-path-validate) |
| `onex:gap-fix` | Auto-fix loop for gap-analysis findings — dispatches ticket-pipeline for eligible findings |
| `onex:pipeline-audit` | Systematic multi-repo pipeline audit with parallel agents and severity-ordered gap register |
| `onex:golden-path-validate` | Execute a golden path event chain test using real Kafka/Redpanda |

### Observability & Status

| Skill | Description |
|-------|-------------|
| `onex:system-status` | Comprehensive system health monitoring across agent performance, DB, Kafka, and services |
| `onex:onex-status` | Show current OmniClaude integration tier, probe age, and per-service reachability |
| `onex:agent-observability` | Real-time monitoring and diagnostics for the OmniClaude agent execution system |
| `onex:agent-tracking` | PostgreSQL-backed observability for routing decisions, detection failures, and metrics |
| `onex:action-logging` | Easy action logging for agents with automatic timing and Kafka integration |
| `onex:log-execution` | Track agent execution in PostgreSQL for observability and intelligence gathering |
| `onex:trace-correlation-id` | Full observability trace for agent executions by correlation ID |
| `onex:pipeline-metrics` | Report pipeline health metrics — rework ratio, cycle time, CI stability, velocity |

### Release & Deployment

| Skill | Description |
|-------|-------------|
| `onex:release` | Org-wide coordinated release — bumps versions, pins deps, creates PRs, tags, triggers PyPI publish |
| `onex:deploy-local-plugin` | Deploy local plugin files to Claude Code plugin cache for immediate testing |
| `onex:setup-statusline` | Configure Claude Code status line to show folder name, git branch, and PR number |
| `onex:ultimate-validate` | Generate comprehensive validation command for this codebase |
| `onex:rrh` | Release Readiness Handshake — runs A1 (collect) → A2 (validate) → A3 (store) preflight |
| `onex:integration-gate` | Cross-repo merge gate with topological ordering and Slack gate approval |

### Multi-Agent Orchestration

| Skill | Description |
|-------|-------------|
| `onex:parallel-solve` | Execute any task in parallel using polymorphic agents with requirements gathering |
| `onex:dispatching-parallel-agents` | Dispatch multiple agents for 3+ independent failures that can be investigated concurrently |
| `onex:subagent-driven-development` | Dispatch fresh subagent per task with code review between tasks |
| `onex:epic-team` | Orchestrate a Claude Code agent team to autonomously work a Linear epic across multiple repos |
| `onex:resume-epic` | Resume a mid-epic interruption by re-dispatching incomplete tickets to ticket-pipeline |

### Daily Workflow

| Skill | Description |
|-------|-------------|
| `onex:deep-dive` | Daily work analysis report from git commit history |
| `onex:close-day` | Auto-generate a ModelDayClose YAML from today's GitHub PRs, git activity, and invariant probes |
| `onex:velocity-estimate` | Project velocity and ETA analysis |
| `onex:suggest-work` | Priority backlog recommendations |
| `onex:crash-recovery` | Show recent pipeline state to orient after an unexpected session end or crash |
| `onex:checkpoint` | Pipeline checkpoint management for resume, replay, and phase validation |

### Utilities

| Skill | Description |
|-------|-------------|
| `onex:using-superpowers` | Establish mandatory workflows at conversation start — find and use skills proactively |
| `onex:using-git-worktrees` | Create isolated git worktrees with smart directory selection and safety verification |
| `onex:writing-skills` | TDD for skill documentation — test with subagents before writing, iterate until bulletproof |
| `onex:testing-skills-with-subagents` | Verify skills before deployment using RED-GREEN-REFACTOR cycle |
| `onex:sharing-skills` | Contribute a skill upstream via pull request |
| `onex:merge-sweep` | Org-wide PR sweep — enable auto-merge on ready PRs, run pr-polish on blocked PRs |
| `onex:fix-prs` | Org-wide PR repair — fix merge conflicts, failing CI, and unaddressed review comments |
| `onex:review-all-prs` | Org-wide PR review — scan all open PRs and run local-review until N consecutive clean passes |
| `onex:list-prs` | Dashboard view of all open (non-draft) PRs across OmniNode-ai repos |
| `onex:pr-queue-pipeline` | Daily org-wide PR queue drain — review, fix broken PRs, merge all ready PRs |
| `onex:routing` | Request agent routing decisions via Kafka event bus |
| `onex:intelligence` | Request intelligence from OmniIntelligence for pattern discovery and context enrichment |
| `onex:generate-node` | Generate ONEX nodes via automated code generation with ContractInferencer |
| `onex:curate-legacy` | Canonicalize legacy docs and feature ideas into a handler-first Ideas Registry |
| `onex:slack-gate` | Post a risk-tiered Slack gate and poll for human reply |
| `onex:gather-github-stats` | Gather GitHub repository statistics — PR counts, commit velocity, contributor activity |

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
- [docs/TOPICS.md](docs/TOPICS.md) — Kafka topic catalog, naming convention, and access control
- [docs/](docs/) — Architecture decision records and design proposals

Open an issue or email contact@omninode.ai.
