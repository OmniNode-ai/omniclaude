<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/brand/omninode-inline-white.png">
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/brand/omninode-inline-full-color.svg">
    <img alt="omninode" src="docs/assets/brand/omninode-inline-full-color.svg" width="420">
  </picture>
</p>

# omniclaude

Claude Code integration layer for the ONEX (OmniNode eXecution) platform — hooks, routing, and thin UX wrappers for ONEX workflows.

[![CI](https://github.com/OmniNode-ai/omniclaude/actions/workflows/ci.yml/badge.svg)](https://github.com/OmniNode-ai/omniclaude/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **`dev` is the live, default branch** — a plain `git clone` and the GitHub web UI both land
> here. `main` is the promotion target and lags behind by design (it is not kept current
> commit-for-commit); do not treat `main` as this repo's "stable" branch or clone it expecting
> parity with what's documented here.

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
| Skill-driven workflows | `plugins/onex/skills/` | User-facing workflow entrypoints |
| Hook Pydantic models | `src/omniclaude/hooks/schemas.py` | Hook payload schemas |
| Context injection | `plugins/onex/hooks/lib/context_injection_wrapper.py` | Pattern enrichment |
| Plugin daemon venv | `plugins/onex/lib/.venv` | Brew-interpreter venv for macOS LAN access |

## What This Repo Does NOT Own

| Concern | Canonical Owner |
|---------|----------------|
| Workflow business logic | [omnimarket](https://github.com/OmniNode-ai/omnimarket) |
| Emit daemon runtime | omnimarket `node_emit_daemon` (migration complete) |
| Intelligence / routing logic | [omniintelligence](https://github.com/OmniNode-ai/omniintelligence) |
| ONEX runtime, node framework | [omnibase_core](https://github.com/OmniNode-ai/omnibase_core) |
| Infrastructure adapters | [omnibase_infra](https://github.com/OmniNode-ai/omnibase_infra) |

> **Note (verified against code on this refresh):** omniclaude still defines and
> uses a **local** `TopicBase` enum in `src/omniclaude/hooks/topics.py` (a `StrEnum`,
> imported by 31 modules under `src/`). omnibase_core has its own `TopicBase`
> (`omnibase_core/src/omnibase_core/topics.py`), but the omniclaude-side migration to
> consume it is not complete — do not treat the local enum as removed.

Skills that contain more than invocation routing belong in omnimarket.
See [Skill Lifecycle](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/omniclaude-skill-lifecycle.md) for the decision rule.

---

## Quickstart

### Plugin Install

First-time install (registers the marketplace directly from GitHub — no local clone needed):

```bash
claude plugin marketplace add OmniNode-ai/omniclaude
claude plugin install onex@omninode-tools

# Restart the Claude Code session to pick up the skill
```

See [QUICKSTART.md](QUICKSTART.md) for the full walkthrough, including installing the `onex`
CLI the plugin depends on and known gaps.

To refresh an already-registered marketplace (e.g. after a plugin update):

```bash
claude plugin marketplace update omninode-tools
claude plugin uninstall onex@omninode-tools
claude plugin install onex@omninode-tools
```

> **OmniNode-internal canonical clone.** If you're on OmniNode's internal `$OMNI_HOME`
> canonical-clone registry, run `git -C "$OMNI_HOME/omniclaude" pull --ff-only` before the
> refresh above so the marketplace re-reads your latest local commits. External users
> installing from the public GitHub repo can ignore this — `marketplace add` above reads
> directly from GitHub and needs no local clone.

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

See [Adding a Skill](https://github.com/OmniNode-ai/knowledge-base/blob/main/guides/adding-a-skill.md) and [Skill Lifecycle](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/omniclaude-skill-lifecycle.md).

### Adding a hook handler

1. Create shell script in `plugins/onex/hooks/scripts/`
2. Add Python logic in `plugins/onex/hooks/lib/`
3. Register in `plugins/onex/hooks/hooks.json`
4. Run `uv run pytest tests/ -v` before deploying

See [Adding a Hook Handler](https://github.com/OmniNode-ai/knowledge-base/blob/main/guides/adding-a-hook-handler.md).

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

> **Current state (verified against code on this refresh):** every hook
> registration in `plugins/onex/hooks/hooks.json` is currently removed — the
> `hooks` block is `{}` — for a hooks-off measurement baseline. The hook
> shell scripts (`plugins/onex/hooks/scripts/`) and Python handler modules
> (`plugins/onex/hooks/lib/`) remain on disk; re-enabling is a pure config
> change. The flow above describes the wired behavior when
> hooks are registered.

---

## Documentation Map

| I want to... | Go to |
|---|---|
| Install the delegate-only plugin (`onex@omninode-tools`, what actually ships today) | [QUICKSTART.md](QUICKSTART.md) |
| Configure the legacy internal hooks/agents plugin (`plugins/onex`, not marketplace-distributed as of OMN-14688) | [docs/getting-started/INSTALLATION.md](docs/getting-started/INSTALLATION.md) |
| Understand the hook data flow | [knowledge-base: architecture/hook-data-flow.md](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/hook-data-flow.md) |
| Understand agent routing | [knowledge-base: architecture/agent-routing-architecture.md](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/agent-routing-architecture.md) |
| Know when a skill moves to omnimarket | [knowledge-base: architecture/omniclaude-skill-lifecycle.md](https://github.com/OmniNode-ai/knowledge-base/blob/main/architecture/omniclaude-skill-lifecycle.md) |
| Add a hook handler | [knowledge-base: guides/adding-a-hook-handler.md](https://github.com/OmniNode-ai/knowledge-base/blob/main/guides/adding-a-hook-handler.md) |
| Add an agent | [knowledge-base: guides/adding-an-agent.md](https://github.com/OmniNode-ai/knowledge-base/blob/main/guides/adding-an-agent.md) |
| Add a skill | [knowledge-base: guides/adding-a-skill.md](https://github.com/OmniNode-ai/knowledge-base/blob/main/guides/adding-a-skill.md) |
| Write tests for hooks | [knowledge-base: guides/omniclaude-testing-guide.md](https://github.com/OmniNode-ai/knowledge-base/blob/main/guides/omniclaude-testing-guide.md) |
| Look up Kafka topics | [docs/reference/KAFKA_TOPICS_REFERENCE.md](docs/reference/KAFKA_TOPICS_REFERENCE.md) |
| Read the knowledge base docs index | [knowledge-base README](https://github.com/OmniNode-ai/knowledge-base/blob/main/README.md) |
| Understand CI/CD pipeline | [knowledge-base: reference/omniclaude-ci-cd-standards.md](https://github.com/OmniNode-ai/knowledge-base/blob/main/reference/omniclaude-ci-cd-standards.md) |
| Report a security vulnerability | [SECURITY.md](SECURITY.md) |

---

## Development and Test Commands

```bash
# Full test suite (required before every PR)
uv run pytest tests/ -v

# Unit only
uv run pytest tests/ -m unit -v

# Integration (requires Kafka on <onex-host>:19092)
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
- [CI/CD standards](https://github.com/OmniNode-ai/knowledge-base/blob/main/reference/omniclaude-ci-cd-standards.md) — pipeline gates and branch protection
- [License: MIT](LICENSE)
