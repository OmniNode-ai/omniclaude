# AGENT.md -- omniclaude

> LLM navigation guide. Points to context sources -- does not duplicate them.

## Context

- **Plugin architecture**: `docs/architecture/`
- **Skills catalog**: `skills/`
- **Hook system**: `src/omniclaude/hooks/`
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

- Uses `skills/` directory, never `commands/`
- Plugin hook files go in `src/omniclaude/hooks/`
- Agent configs in `onex/agents/configs/`
