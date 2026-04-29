# Contributing to omniclaude

omniclaude is the Claude Code agent plugin for the ONEX platform. It contains hooks, skills, agents, and the plugin runtime that runs alongside Claude Code sessions.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Plugin Architecture](#plugin-architecture)
- [Skill Development](#skill-development)
- [Hook Conventions](#hook-conventions)
- [Testing Requirements](#testing-requirements)
- [Code Standards](#code-standards)
- [Pull Request Process](#pull-request-process)

## Getting Started

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management
- [Claude Code](https://claude.ai/code) installed
- Access to the OmniNode GitHub org

### First Steps

1. Read [CLAUDE.md](CLAUDE.md) for operating rules and architectural constraints.
2. Read [AGENT.md](AGENT.md) for agent behavioral guidelines.
3. Browse [docs/](docs/) — especially [docs/INDEX.md](docs/INDEX.md) for the full doc map.
4. Review [QUICKSTART.md](QUICKSTART.md) for initial setup.

## Development Setup

```bash
git clone https://github.com/OmniNode-ai/omniclaude.git
cd omniclaude
uv sync --all-extras
uv run pre-commit install
uv run pre-commit install --hook-type pre-push
```

### Plugin Venv (for daemon processes)

The plugin daemon (`plugins/onex/lib/.venv`) must be built from the brew Python interpreter to obtain the macOS Local Network privacy grant required to reach LAN services (Kafka, Postgres on 192.168.86.201):

```bash
# Run from repo root
bash omniclaude/scripts/repair-plugin-venv.sh
```

Never use a uv-managed interpreter as the base for the plugin daemon venv. See `CLAUDE.md` Rule 11 for the full rationale.

### Deploying the Plugin Locally

```bash
# From omni_home/omniclaude/
deploy_local_plugin --execute
```

After deploy, verify with:

```bash
uv run python -m omniclaude.verify_plugin
```

## Plugin Architecture

The plugin runs as a daemon alongside Claude Code. Key directories:

```
plugins/onex/
├── agents/          # Agent YAML configs and prompts
├── hooks/           # PreToolUse / PostToolUse / Stop hook handlers
├── lib/             # Plugin runtime and daemon
│   └── .venv/       # Brew-Python venv (never modify manually)
├── skills/          # Slash-command skill definitions
└── scripts/         # Install/repair scripts
```

Hooks fire on Claude Code events (tool calls, session stop). Skills are slash commands invoked by the operator. All business logic belongs in `omnimarket` nodes — skills and hooks are thin shims.

## Skill Development

Skills live under `plugins/onex/skills/<skill_name>/`. Each skill requires:

- `SKILL.md` — metadata (name, description, trigger conditions)
- `prompt.md` — the skill prompt that Claude executes

### Skill Naming

Skills use kebab-case directories matching the slash command: `/onex:my_skill` → `plugins/onex/skills/my_skill/`.

### Authoring a Skill

1. Create `plugins/onex/skills/<name>/SKILL.md` and `prompt.md`.
2. Follow the authoring guide: [docs/reference/SKILL_AUTHORING_GUIDE.md](docs/reference/SKILL_AUTHORING_GUIDE.md).
3. Skills must be thin: extract node logic to `omnimarket`, not inline in `prompt.md`.
4. Add an entry to `plugins/onex/skills/README.md` (if it exists) and `docs/INDEX.md`.

See [docs/guides/ADDING_A_SKILL.md](docs/guides/ADDING_A_SKILL.md) for the step-by-step guide.

## Hook Conventions

Hooks implement `PreToolUse`, `PostToolUse`, or `Stop` interfaces. Key rules:

- Hook handlers live in `plugins/onex/hooks/`.
- Every hook must be registered in the hook manifest — no ad-hoc handler files.
- Hooks must be idempotent and must not block the tool call path for >500ms.
- Hook logic that spans >50 lines belongs in an `omnimarket` node, not inline.

See [docs/architecture/HOOK_DATA_FLOW.md](docs/architecture/HOOK_DATA_FLOW.md) for the data flow diagram.

### Adding a Hook Handler

Follow [docs/guides/ADDING_A_HOOK_HANDLER.md](docs/guides/ADDING_A_HOOK_HANDLER.md).

## Testing Requirements

Every change ships with a unit test — no exceptions.

```bash
uv run pytest tests/ -m unit          # fast unit suite
uv run pytest tests/ -m "not slow"    # skip integration tests
uv run pytest tests/ -v               # full suite (required before push)
```

### Test Markers

Markers are defined in `pyproject.toml`: `unit`, `integration`, `slow`.

### Pre-push Checklist

```bash
uv run ruff format src/ tests/
uv run ruff check --fix src/ tests/
uv run mypy src/ --strict
uv run pre-commit run --all-files
uv run pytest tests/ -v               # no -k filter
```

## Code Standards

- Python 3.12+; PEP 604 unions (`X | Y`, not `Optional[X]`)
- `uv run ...` for all commands — never bare `python` or `pip`
- No hardcoded connection strings or absolute paths starting with `/Users/` or `/Volumes/`
- No `datetime.now()` defaults; no `@dataclass`
- Pydantic `BaseModel` for all data models; ONEX naming: `ModelFoo`, `EnumBar`, `NodeBazCompute`

## Pull Request Process

1. Create a worktree (never branch inside `omni_home/omniclaude/` directly):
   ```bash
   git -C "$OMNI_HOME/omniclaude" worktree add "$OMNI_HOME/omni_worktrees/OMN-XXXX/omniclaude" -b jonah/omn-xxxx-description
   ```
2. Implement with tests.
3. Run the pre-push checklist above.
4. PR title must contain the Linear ticket: `feat(OMN-XXXX): description`.
5. PR body must cite the ticket with `## DoD evidence`.

See [CLAUDE.md](CLAUDE.md) for the full PR CI requirements.

## Commit Messages

[Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`

## Security

Report vulnerabilities to contact@omninode.ai — not in GitHub issues.
