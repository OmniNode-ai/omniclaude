# Claude Code User-Level Configuration

This directory contains user-level configuration files for Claude Code that should be symlinked to `~/.claude/`.

## Directory Structure

```
~/.claude/
├── agent-definitions/  → symlink to omniclaude/agents/definitions/
├── agents/            → symlink to omniclaude/agents/
├── hooks/             → symlink to omniclaude/claude_hooks/
├── skills/            → symlink to omniclaude/skills/
├── commands/          → symlink to omniclaude/.claude/commands/
├── .env               → symlink to omniclaude/.env
└── CLAUDE.md          → (optional) symlink to omniclaude/CLAUDE.md
```

## Setup Instructions for New Machine

Run the setup script:

```bash
cd /path/to/omniclaude
./scripts/setup-claude-user-config.sh
```

Or manually:

```bash
# Remove any existing ~/.claude directories (backup first!)
mkdir -p ~/.claude

# Create symlinks
ln -sf "$(pwd)/agents/definitions" ~/.claude/agent-definitions
ln -sf "$(pwd)/agents" ~/.claude/agents
ln -sf "$(pwd)/claude_hooks" ~/.claude/hooks
ln -sf "$(pwd)/skills" ~/.claude/skills
ln -sf "$(pwd)/.claude/commands" ~/.claude/commands
ln -sf "$(pwd)/.env" ~/.claude/.env

# Optional: symlink CLAUDE.md for global instructions
ln -sf "$(pwd)/CLAUDE.md" ~/.claude/CLAUDE.md
```

## What's Included

### Agent Definitions (`agents/definitions/`)
- 40+ polymorphic agent YAML definitions
- Agent registry with capabilities and activation patterns
- Specialized agents for testing, debugging, API design, etc.

### Custom Commands (`.claude/commands/`)
- `/parallel-solve` - Auto-detect and solve issues in parallel
- `/pr-dev-review` - Development PR review workflow
- `/pr-release-ready` - Release-ready PR review workflow

### Hooks (`claude_hooks/`)
- User prompt submit hooks with agent routing
- Manifest injection for intelligence context
- Correlation ID tracking and observability

### Skills (`skills/`)
- Action logging skill
- Generate node skill
- PR review skill
- And many more...

### Environment Configuration (`.env`)
- API keys (Gemini, Z.ai, OpenAI)
- Database credentials (PostgreSQL)
- Kafka configuration
- Service endpoints

## Verification

After setup, verify symlinks:

```bash
ls -la ~/.claude/
```

All entries should show as symlinks (`lrwxr-xr-x`) pointing to this repository.

## Benefits of This Approach

1. **Single Source of Truth**: All configuration in version control
2. **Easy Sync**: Pull repo updates, get latest config automatically
3. **Portable**: Same setup across all machines
4. **Backup**: Configuration backed up with git
5. **Collaboration**: Share improvements with team

## Troubleshooting

**Symlink already exists**: Remove old symlink first
```bash
rm ~/.claude/agent-definitions
ln -sf "$(pwd)/agents/definitions" ~/.claude/agent-definitions
```

**Permission denied**: Check file permissions
```bash
chmod +x scripts/setup-claude-user-config.sh
```

**Commands not working**: Restart Claude Code after creating symlinks
