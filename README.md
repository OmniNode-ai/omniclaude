# omniclaude

Claude Code integration layer for the ONEX (OmniNode eXecution) platform — hooks, routing, and thin UX wrappers for ONEX workflows.

[![CI](https://github.com/OmniNode-ai/omniclaude/actions/workflows/ci.yml/badge.svg)](https://github.com/OmniNode-ai/omniclaude/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## What This Repo Is

omniclaude is the **Claude Code plugin layer** for the ONEX platform. It owns the
invocation surface, lifecycle hooks, routing, and prompt context that connect
Claude Code sessions to the rest of the ONEX runtime.

It is **not** a workflow execution engine. Business logic, long-running automation,
and portable workflow packages belong in [omnimarket](https://github.com/OmniNode-ai/omnimarket).

---

## Who Uses This

- **Claude Code sessions** — hooks fire on every session, prompt, and tool call
- **Automation operators** — headless `claude -p` pipelines that drive ticket work
- **Platform developers** — adding new skills, agents, or hook handlers

---

## What This Repo Owns

| Surface | Location | Description |
|---------|----------|-------------|
| Lifecycle hooks | `plugins/onex/hooks/` | SessionStart, UserPromptSubmit, PostToolUse, SessionEnd |
| Agent routing | `plugins/onex/hooks/lib/route_via_events_wrapper.py` | Fuzzy + LLM agent selection |
| Agent YAML definitions | `plugins/onex/agents/configs/` | Per-domain agent configs |
| Skill stubs | `plugins/onex/skills/*/SKILL.md` | Thin UX triggers dispatching to Market nodes |
| Slash commands | `plugins/onex/commands/` | User-facing command definitions |
| Hook Pydantic models | `src/omniclaude/hooks/schemas.py` | Hook payload schemas |
| Context injection | `plugins/onex/hooks/lib/context_injection_wrapper.py` | Pattern enrichment |
| Plugin daemon venv | `plugins/onex/lib/.venv` | Brew-interpreter venv for macOS LAN access |

## What This Repo Does NOT Own

| Concern | Canonical Owner |
|---------|----------------|
| Workflow business logic | [omnimarket](https://github.com/OmniNode-ai/omnimarket) |
| Emit daemon runtime | omnimarket `node_emit_daemon` (OMN-7628 complete) |
| Intelligence / routing logic | [omniintelligence](https://github.com/OmniNode-ai/omniintelligence) |
| `TopicBase` enum | omnibase_core (OMN-9335 complete) |
| ONEX runtime, node framework | [omnibase_core](https://github.com/OmniNode-ai/omnibase_core) |
| Infrastructure adapters | [omnibase_infra](https://github.com/OmniNode-ai/omnibase_infra) |

Skills that contain more than invocation routing belong in omnimarket.
See [Skill Lifecycle](docs/architecture/skill-lifecycle.md) for the decision rule.

---

## Quickstart

### Plugin Install

```bash
# Pull latest in the canonical clone
git -C "$OMNI_HOME/omniclaude" pull --ff-only

# Refresh marketplace and reinstall
claude plugin marketplace update omninode-tools
claude plugin uninstall onex@omninode-tools
claude plugin install onex@omninode-tools

# Restart the Claude Code session to pick up hooks and skills
```

For the daemon venv (required for LAN access on macOS), use:

```bash
bash omniclaude/scripts/repair-plugin-venv.sh
```

### Local Development

```bash
# Install all dependencies (including dev tools)
uv sync --group dev

# Run tests
uv run pytest tests/ -v

# Run unit tests only (no services needed)
uv run pytest tests/ -m unit -v

# Lint and format
uv run ruff format src/ tests/
uv run ruff check --fix src/ tests/

# Type check
uv run mypy src/omniclaude/
```

---

## Common Workflows

### Adding a skill

1. Create `plugins/onex/skills/<name>/SKILL.md`
2. If the skill needs multi-step logic: create a node in omnimarket instead; the skill is a one-line dispatch trigger
3. Deploy: reinstall plugin (see above)
4. Invoke: `/<name>` in Claude Code

See [Adding a Skill](docs/guides/ADDING_A_SKILL.md) and [Skill Lifecycle](docs/architecture/skill-lifecycle.md).

### Adding a hook handler

1. Create shell script in `plugins/onex/hooks/scripts/`
2. Add Python logic in `plugins/onex/hooks/lib/`
3. Register in `plugins/onex/hooks/hooks.json`
4. Run `uv run pytest tests/ -v` before deploying

See [Adding a Hook Handler](docs/guides/ADDING_A_HOOK_HANDLER.md).

### Disabling all hooks (emergency kill-switch)

```bash
export OMNICLAUDE_HOOKS_DISABLE=1
# or: touch ~/.claude/omniclaude-hooks-disabled
```

See [CLAUDE.md](CLAUDE.md) for the full kill-switch and per-hook bitmask documentation.

---

## Architecture Summary

```
Claude Code session
       |
  hooks (shell scripts)
       |
  Python hook lib  ──► event emission → omnimarket node_emit_daemon → Kafka
       |
  agent routing ──────────────────────────────► omniintelligence
       |
  context injection ──────────────────────────► omniintelligence HTTP API
       |
  skill dispatch ─────────────────────────────► omnimarket nodes
```

**Thin wrapper rule**: Every hook and skill exits as fast as possible.
Anything that blocks, stores state, or runs for more than a few seconds
belongs in an omnimarket node, not in this repo.

---

## Documentation Map

| I want to... | Go to |
|---|---|
| Install the plugin and configure hooks | [docs/getting-started/INSTALLATION.md](docs/getting-started/INSTALLATION.md) |
| Understand the hook data flow | [docs/architecture/HOOK_DATA_FLOW.md](docs/architecture/HOOK_DATA_FLOW.md) |
| Understand agent routing | [docs/architecture/AGENT_ROUTING_ARCHITECTURE.md](docs/architecture/AGENT_ROUTING_ARCHITECTURE.md) |
| Know when a skill moves to omnimarket | [docs/architecture/skill-lifecycle.md](docs/architecture/skill-lifecycle.md) |
| Add a hook handler | [docs/guides/ADDING_A_HOOK_HANDLER.md](docs/guides/ADDING_A_HOOK_HANDLER.md) |
| Add an agent | [docs/guides/ADDING_AN_AGENT.md](docs/guides/ADDING_AN_AGENT.md) |
| Add a skill | [docs/guides/ADDING_A_SKILL.md](docs/guides/ADDING_A_SKILL.md) |
| Write tests for hooks | [docs/guides/TESTING_GUIDE.md](docs/guides/TESTING_GUIDE.md) |
| Look up Kafka topics | [docs/reference/KAFKA_TOPICS_REFERENCE.md](docs/reference/KAFKA_TOPICS_REFERENCE.md) |
| Read the full docs index | [docs/INDEX.md](docs/INDEX.md) |
| Understand CI/CD pipeline | [docs/standards/CI_CD_STANDARDS.md](docs/standards/CI_CD_STANDARDS.md) |
| Report a security vulnerability | [SECURITY.md](SECURITY.md) |

---

## Development and Test Commands

```bash
# Full test suite (required before every PR)
uv run pytest tests/ -v

# Unit only
uv run pytest tests/ -m unit -v

# Integration (requires Kafka on 192.168.86.201:19092)
KAFKA_INTEGRATION_TESTS=1 uv run pytest -m integration

# Coverage
uv run pytest tests/ --cov=src/omniclaude --cov-report=html

# Pre-commit (run before staging)
pre-commit run --all-files

# Security scan
uv run bandit -r src/omniclaude/ -ll

# SPDX header check
uv run onex spdx fix --check src tests scripts
```

---

## Security, Contributing, and License

- [Security policy](SECURITY.md) — how to report vulnerabilities
- [CI/CD standards](docs/standards/CI_CD_STANDARDS.md) — pipeline gates and branch protection
- [License: MIT](LICENSE)
