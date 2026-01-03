# Claude Artifacts

Unified directory containing all Claude Code customizations for OmniClaude.

## Quick Start

```bash
# Deploy to ~/.claude/
./scripts/deploy-claude.sh
```

This creates symlinks from `~/.claude/` to this repository, enabling all customizations.

## Directory Structure

```
claude/
├── agents/       # Agent YAML definitions (polymorphic agents)
├── commands/     # Slash commands (/parallel-solve, /pr-review-dev, etc.)
├── hooks/        # Pre/post tool hooks, session hooks
├── skills/       # Reusable skills (pr-review, ci-failures, linear, etc.)
├── lib/          # Shared Python libraries
└── plugins/      # Claude Code plugins
```

## Installation

### Prerequisites

1. **Poetry environment**: Required for Python imports in hooks/skills
   ```bash
   cd /path/to/omniclaude
   poetry install
   ```

2. **Environment variables**: Copy and configure `.env`
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

### Deploy

Run the deployment script:

```bash
./scripts/deploy-claude.sh
```

This creates the following symlinks:

```
~/.claude/
├── hooks/              → claude/hooks/
├── skills/             → claude/skills/
├── commands/           → claude/commands/
├── agents/omniclaude/        → claude/agents/
├── .env                → .env
└── onex/               # Namespace directory with all symlinks
    ├── hooks/
    ├── skills/
    ├── commands/
    ├── agents/
    ├── lib/
    ├── plugins/
    ├── config/
    └── .venv/          → Poetry virtualenv
```

### Verify Installation

After deployment, verify the symlinks:

```bash
ls -la ~/.claude/hooks/
ls -la ~/.claude/skills/
ls -la ~/.claude/commands/
ls -la ~/.claude/agent-definitions/
```

## Components

### Agents (`agents/`)

YAML-defined polymorphic agents with capabilities, triggers, and workflows.

**Key agents**:
- `polymorphic-agent.yaml` - Base agent for all polymorphic workflows
- `pr-review.yaml` - Pull request review agent
- `debug.yaml` - Debugging and troubleshooting agent
- `testing.yaml` - Test execution and analysis agent

**Usage**: Agents are loaded by the manifest injector and routed via the agent router.

### Commands (`commands/`)

Slash commands available in Claude Code sessions.

| Command | Description |
|---------|-------------|
| `/parallel-solve` | Execute tasks in parallel using polymorphic agents |
| `/pr-review-dev` | Development-focused PR review |
| `/pr-release-ready` | Release readiness PR review |
| `/ci-failures` | Analyze CI/CD failures |

### Hooks (`hooks/`)

Event-driven hooks that execute during Claude Code sessions.

| Hook | Event | Purpose |
|------|-------|---------|
| `session-start.sh` | SessionStart | Initialize session, load intelligence |
| `session-end.sh` | SessionEnd | Cleanup, log metrics |
| `pre-tool-use-quality.sh` | PreToolUse | Quality gates before tool execution |
| `post-tool-use-quality.sh` | PostToolUse | Quality validation after tools |
| `user-prompt-submit.sh` | UserPromptSubmit | Agent routing, prompt enrichment |
| `stop.sh` | Stop | Final cleanup on session stop |

### Skills (`skills/`)

Reusable skill modules for specific capabilities.

| Skill | Purpose |
|-------|---------|
| `pr-review/` | PR analysis, fetching, review |
| `ci-failures/` | CI failure analysis and research |
| `linear/` | Linear ticket management |
| `system-status/` | Infrastructure health checks |
| `agent-observability/` | Agent monitoring and diagnostics |
| `action-logging/` | Structured action logging |
| `generate-node/` | ONEX node generation |

### Shared Library (`lib/`)

Common Python modules used across hooks and skills.

## Development

### Adding a New Command

1. Create `claude/commands/my-command.md`
2. Add YAML frontmatter with description
3. Write the command prompt in markdown
4. Re-run `./scripts/deploy-claude.sh` (or symlinks are already active)

### Adding a New Skill

1. Create directory `claude/skills/my-skill/`
2. Add `SKILL.md` with skill documentation
3. Add executable scripts or Python modules
4. Skills are automatically available via symlinks

### Adding a New Agent

1. Create `claude/agents/my-agent.yaml`
2. Define: `agent_name`, `agent_domain`, `capabilities`, `triggers`
3. Agent is automatically loaded by the manifest injector

### Adding a New Hook

1. Create hook script in `claude/hooks/`
2. Follow naming convention: `{event-type}.sh` or `{event-type}.py`
3. Make executable: `chmod +x claude/hooks/my-hook.sh`
4. Register in `.claude/settings.json` if not using convention

## Troubleshooting

### Hooks not executing

1. Check symlinks exist: `ls -la ~/.claude/hooks/`
2. Verify scripts are executable: `chmod +x claude/hooks/*.sh`
3. Check `.claude/settings.json` for hook registration

### Skills not found

1. Verify symlinks: `ls -la ~/.claude/skills/`
2. Check Python path includes the skill directory
3. Ensure Poetry venv is linked: `ls -la ~/.claude/lib/onex/.venv`

### Agent not routing

1. Check agent YAML is valid: `python3 -c "import yaml; yaml.safe_load(open('claude/agents/my-agent.yaml'))"`
2. Verify agent is in registry
3. Check manifest injector logs

## Related Documentation

- [CLAUDE.md](../CLAUDE.md) - Main project documentation
- [Deployment README](../deployment/README.md) - Docker deployment
- [Config README](../config/README.md) - Configuration framework
