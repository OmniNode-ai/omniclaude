# Contributing to omniclaude

## Development Setup

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/), [Claude Code](https://claude.ai/code)

```bash
git clone https://github.com/OmniNode-ai/omniclaude.git
cd omniclaude
uv sync
uv run pre-commit install
```

## Running Tests

```bash
uv run pytest tests/ -m unit          # unit tests only (fast)
uv run pytest tests/ -m "not slow"    # skip slow tests
```

## Code Quality

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run mypy src/ --strict
uv run pre-commit run --all-files
```

## Pull Request Process

1. Branch from `main`
2. Write tests first
3. Ensure `pre-commit run --all-files` passes
4. Open a PR against `main`

## Commit Messages

[Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`

## Security

Report vulnerabilities to contact@omninode.ai (not in GitHub issues).
