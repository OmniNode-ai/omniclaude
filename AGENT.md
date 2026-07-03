# AGENT.md -- omniclaude

> LLM navigation guide. Points to context sources -- does not duplicate them.

## Context

- **Plugin architecture**: `docs/architecture/`
- **Skills catalog**: `plugins/onex/skills/`
- **Hook system**: `plugins/onex/hooks/` (scripts in `scripts/`, Python lib in `lib/`, Pydantic schemas in `src/omniclaude/hooks/`)
- **Conventions**: `CLAUDE.md`

## Commands

- Tests: `uv run pytest`
- Lint: `uv run ruff check src/ tests/`
- Type check: `uv run mypy src/omniclaude/hooks/ src/omniclaude/config/`
- Pre-commit: `pre-commit run --all-files`

## Cross-Repo

- Shared platform standards: `~/.claude/CLAUDE.md`
- Core models: `omnibase_core/CLAUDE.md`

## Rules

- Uses `plugins/onex/skills/` directory, never a top-level `skills/` or `commands/`
- Hook shell scripts go in `plugins/onex/hooks/scripts/`; Python hook modules in `plugins/onex/hooks/lib/`; Pydantic hook schemas in `src/omniclaude/hooks/`
- Agent configs in `plugins/onex/agents/configs/`
