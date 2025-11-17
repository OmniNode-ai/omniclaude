# Claude Artifacts Directory

**Purpose**: Centralized storage for Claude commands, skills, and agent definitions to eliminate duplicate display issues in Claude IDE.

**Last Updated**: 2025-11-17

---

## Problem Statement

The Claude IDE scans both:
- `~/.claude/` (global/user directory)
- `.claude/` (project directory)

When the same artifact exists in both locations, it appears **twice** in the IDE, causing confusion and clutter.

## Solution: Symlink Architecture

Store actual files in this normal directory (`claude-artifacts/`) and create symlinks from both Claude directories.

```
claude-artifacts/           # ← Actual files live here (ONE copy)
├── commands/              # ← Command definitions
├── skills/                # ← Skill implementations
└── agents/                # ← Agent definitions (future)

~/.claude/                 # ← Global symlinks point here
├── commands -> /path/to/project/claude-artifacts/commands/
├── skills -> /path/to/project/claude-artifacts/skills/
└── agents -> /path/to/project/claude-artifacts/agents/

.claude/                   # ← Project symlinks point here
├── commands -> ../claude-artifacts/commands/
├── skills -> ../claude-artifacts/skills/
└── agents -> ../claude-artifacts/agents/
```

**Benefits**:
- ✅ Single source of truth for all artifacts
- ✅ No duplication in Claude IDE
- ✅ Version controlled in repository (via `claude-artifacts/`)
- ✅ Accessible from both global and project contexts
- ✅ Easy to update (edit once, available everywhere)

---

## Directory Structure

### `commands/`

Slash commands for Claude Code.

**File Pattern**: `<command-name>.md`

**Example**:
```markdown
commands/
├── review-pr.md         # /review-pr command
├── parallel-solve.md    # /parallel-solve command
└── debug-workflow.md    # /debug-workflow command
```

**Symlink Setup**:
```bash
# Global symlink
ln -s /Volumes/PRO-G40/Code/omniclaude/claude-artifacts/commands ~/.claude/commands

# Project symlink (relative path)
ln -s ../claude-artifacts/commands .claude/commands
```

### `skills/`

Skill implementations with subdirectories per skill.

**Directory Pattern**: `<skill-name>/` with multiple files

**Example**:
```markdown
skills/
├── linear/
│   ├── create-ticket       # Skill entry point
│   ├── list-tickets        # Skill entry point
│   ├── update-ticket       # Skill entry point
│   └── README.md           # Skill documentation
├── pr-review/
│   ├── review-pr           # Skill entry point
│   ├── fetch-pr-data       # Helper script
│   └── README.md           # Skill documentation
└── action-logging/
    ├── action-logging      # Skill entry point
    └── README.md           # Skill documentation
```

**Symlink Setup**:
```bash
# Global symlink
ln -s /Volumes/PRO-G40/Code/omniclaude/claude-artifacts/skills ~/.claude/skills

# Project symlink (relative path)
ln -s ../claude-artifacts/skills .claude/skills
```

### `agents/`

Agent definitions (future use - `agents/definitions/` already exists for polymorphic agents).

**File Pattern**: `<agent-name>.yaml`

**Example**:
```markdown
agents/
├── agent-api.yaml
├── agent-frontend.yaml
├── agent-database.yaml
└── agent-onex.yaml
```

**Note**: This directory is reserved for future migration of agent definitions. The current `agents/definitions/` directory contains the polymorphic agent framework.

**Symlink Setup**:
```bash
# Global symlink (when ready)
ln -s /Volumes/PRO-G40/Code/omniclaude/claude-artifacts/agents ~/.claude/agents

# Project symlink (relative path, when ready)
ln -s ../claude-artifacts/agents .claude/agents
```

---

## Migration Guide

### Step 1: Identify Duplicates

Find artifacts that exist in both `~/.claude/` and `.claude/`:

```bash
# List global artifacts
ls -la ~/.claude/commands/
ls -la ~/.claude/skills/

# List project artifacts
ls -la .claude/commands/
ls -la .claude/skills/

# Identify duplicates (same filename in both locations)
```

### Step 2: Move to `claude-artifacts/`

Move actual files from both locations to `claude-artifacts/`:

```bash
# Example: Move command
mv ~/.claude/commands/review-pr.md claude-artifacts/commands/

# Example: Move skill directory
mv ~/.claude/skills/linear claude-artifacts/skills/
```

**Best Practice**: Keep the most recent/complete version when consolidating duplicates.

### Step 3: Create Symlinks

Create symlinks from both Claude directories to `claude-artifacts/`:

```bash
# Remove old directories (if they exist)
rm -rf ~/.claude/commands
rm -rf .claude/commands

# Create global symlink (absolute path)
ln -s /Volumes/PRO-G40/Code/omniclaude/claude-artifacts/commands ~/.claude/commands

# Create project symlink (relative path)
ln -s ../claude-artifacts/commands .claude/commands

# Verify symlinks
ls -la ~/.claude/commands
ls -la .claude/commands
```

### Step 4: Verify in Claude IDE

1. Restart Claude IDE (if running)
2. Check that artifacts appear only **once** in the IDE
3. Test that commands/skills work correctly

---

## Maintenance

### Adding New Artifacts

**Always add to `claude-artifacts/`** (not to `~/.claude/` or `.claude/`):

```bash
# Create new command
nano claude-artifacts/commands/new-command.md

# Create new skill
mkdir claude-artifacts/skills/new-skill
nano claude-artifacts/skills/new-skill/new-skill
```

Symlinks will automatically make them available in both contexts.

### Updating Existing Artifacts

**Edit files in `claude-artifacts/`** directly:

```bash
# Update command
nano claude-artifacts/commands/review-pr.md

# Update skill
nano claude-artifacts/skills/linear/create-ticket
```

Changes are immediately reflected in both `~/.claude/` and `.claude/` via symlinks.

### Removing Artifacts

**Delete from `claude-artifacts/`** only:

```bash
# Remove command
rm claude-artifacts/commands/old-command.md

# Remove skill
rm -rf claude-artifacts/skills/old-skill
```

---

## Troubleshooting

### Issue: Artifact appears twice in Claude IDE

**Cause**: Artifact exists in both `~/.claude/` and `.claude/` as actual files (not symlinks).

**Fix**:
```bash
# 1. Keep one copy in claude-artifacts/
mv .claude/commands/duplicate.md claude-artifacts/commands/

# 2. Verify symlinks exist
ls -la ~/.claude/commands  # Should show symlink
ls -la .claude/commands    # Should show symlink

# 3. Restart Claude IDE
```

### Issue: Symlink broken (red in `ls -la`)

**Cause**: Target file moved or deleted.

**Fix**:
```bash
# 1. Verify target exists
ls -la claude-artifacts/commands/missing.md

# 2. If missing, recreate file
nano claude-artifacts/commands/missing.md

# 3. If target path wrong, recreate symlink
rm .claude/commands
ln -s ../claude-artifacts/commands .claude/commands
```

### Issue: Changes not reflected in Claude IDE

**Cause**: Claude IDE cache.

**Fix**:
```bash
# 1. Verify file was edited in claude-artifacts/
cat claude-artifacts/commands/changed.md

# 2. Restart Claude IDE

# 3. If still not updated, check symlink:
ls -la .claude/commands/changed.md
# Should show: .claude/commands/changed.md -> ../claude-artifacts/commands/changed.md
```

---

## Version Control

**What to commit**:
- ✅ `claude-artifacts/` directory and all contents
- ✅ `.gitignore` entries for `.claude/` (if needed)

**What NOT to commit**:
- ❌ `~/.claude/` (global user directory)
- ❌ `.claude/` if it only contains symlinks (optional)

**Example `.gitignore`**:
```gitignore
# Claude IDE directories (symlinks only, not tracked)
.claude/*
!.claude/.gitkeep

# Exception: Track .claude/hooks if needed
!.claude/hooks/
```

---

## Architecture Benefits

1. **Single Source of Truth**: All artifacts in one location (`claude-artifacts/`)
2. **No Duplication**: Symlinks prevent duplicate display in Claude IDE
3. **Version Controlled**: Repository tracks actual files (not global user directory)
4. **Cross-Project Sharing**: Global symlinks (`~/.claude/`) make artifacts available to all projects
5. **Project Isolation**: Project symlinks (`.claude/`) keep project-specific artifacts
6. **Easy Updates**: Edit once in `claude-artifacts/`, available everywhere via symlinks
7. **Clear Organization**: Separate directories for commands, skills, and agents

---

## Future Enhancements

1. **Agent Migration**: Move agent definitions from `agents/definitions/` to `claude-artifacts/agents/`
2. **Shared Library**: Create `claude-artifacts/lib/` for shared Python utilities
3. **Documentation**: Create `claude-artifacts/docs/` for artifact-specific documentation
4. **Templates**: Create `claude-artifacts/templates/` for command/skill/agent templates
5. **CI/CD Integration**: Validate artifacts in CI pipeline before merge

---

## Related Documentation

- **OmniClaude CLAUDE.md**: `/Volumes/PRO-G40/Code/omniclaude/CLAUDE.md` - Repository architecture and services
- **Skills Documentation**: `~/.claude/skills/*/README.md` - Individual skill documentation
- **Agent Framework**: `agents/polymorphic-agent.md` - Polymorphic agent architecture
- **Configuration**: `config/README.md` - Type-safe configuration framework

---

**Status**: Directory structure created, ready for migration
**Next Steps**: Migrate existing commands and skills from `~/.claude/` and `.claude/` to `claude-artifacts/`
