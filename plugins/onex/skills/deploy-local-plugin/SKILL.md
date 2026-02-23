---
name: deploy-local-plugin
description: Deploy local plugin files from repository source to Claude Code plugin cache for immediate testing
version: 1.0.0
category: tooling
tags:
  - deployment
  - plugin
  - development
  - tooling
author: OmniClaude Team
---

# Deploy Local Plugin Skill

Automate deployment of local plugin development to the Claude Code plugin cache.

## Problem Solved

During plugin development, changes in the repository are not automatically reflected in Claude Code because:
1. Plugins are loaded from `~/.claude/plugins/cache/` not the repository
2. Manual file copying is error-prone and tedious
3. Version management requires updating multiple locations

This skill solves the deployment gap between development and testing.

## Quick Start

```
# Preview what would change
/deploy-local-plugin

# Actually deploy (syncs files + builds lib/.venv)
/deploy-local-plugin --execute

# Deploy without bumping version
/deploy-local-plugin --execute --no-version-bump

# Repair: build lib/.venv in the active deployed version (no file sync, no version bump)
# Use when hooks fail with "No valid Python found" after a deploy
/deploy-local-plugin --repair-venv
```

## How It Works

### Source → Target Mapping

| Source (Repository) | Target (Cache) |
|---------------------|----------------|
| `plugins/onex/commands/` | `~/.claude/plugins/cache/omninode-tools/onex/{version}/commands/` |
| `plugins/onex/skills/` | `~/.claude/plugins/cache/omninode-tools/onex/{version}/skills/` |
| `plugins/onex/agents/` | `~/.claude/plugins/cache/omninode-tools/onex/{version}/agents/` |
| `plugins/onex/hooks/` | `~/.claude/plugins/cache/omninode-tools/onex/{version}/hooks/` |
| `plugins/onex/.claude-plugin/` | `~/.claude/plugins/cache/omninode-tools/onex/{version}/.claude-plugin/` |

### Version Management

By default, each deployment:
1. Reads current version from `plugin.json` (e.g., `2.1.2`)
2. Bumps patch version (e.g., `2.1.3`)
3. Creates new directory for the new version
4. Syncs all files to the new version directory
5. Updates `installed_plugins.json` registry

Use `--no-version-bump` to overwrite the current version in-place.

### Registry Update

The `installed_plugins.json` registry is updated with:
- New `version` field
- New `installPath` pointing to the new version directory
- Updated `lastUpdated` timestamp

## Safety Features

### Dry Run by Default

The command shows what would change without making modifications:

```
[DRY RUN] Would deploy local plugin to cache

Current version: 2.1.2
New version: 2.1.3

Files to sync:
  commands/:      16 files
  skills/:        31 directories
  agents/configs: 53 files
  hooks/:         7 items
  .claude-plugin: plugin.json + metadata

Target: ~/.claude/plugins/cache/omninode-tools/onex/2.1.3/

Use --execute to apply changes.
```

### Versioned Directories

Each deployment creates a new version directory and removes all prior versions.
Only the current version is kept in cache.

### Atomic Updates

The registry is updated atomically using temp file + move pattern to prevent corruption.

## After Deployment

After running `/deploy-local-plugin --execute`:

1. **Restart Claude Code** to pick up changes (plugins load at session start)
2. Verify with `/help` to see new commands
3. Old version directories are removed automatically

## Troubleshooting

### "command not found: jq"

Install jq: `brew install jq` (macOS) or `apt install jq` (Linux)

### Permissions Error

Ensure write access to `~/.claude/plugins/`:
```bash
ls -la ~/.claude/plugins/
```

### Changes Not Appearing

1. Restart Claude Code session
2. Check the correct version is in registry:
   ```bash
   cat ~/.claude/plugins/installed_plugins.json | jq '.plugins["onex@omninode-tools"]'
   ```

### "No valid Python found" / hooks fail with exit 1

This means `lib/.venv` is missing from the active plugin cache directory. This can happen if:
- The cache directory was populated by a source other than `deploy.sh --execute`
- The deploy was interrupted between the file sync and venv build steps
- A manual rsync was used to copy plugin files without building the venv

**Fix**:
```bash
${CLAUDE_PLUGIN_ROOT}/skills/deploy-local-plugin/deploy.sh --repair-venv
```

This builds `lib/.venv` in the currently-active deployed version (from `installed_plugins.json`)
without syncing files or bumping the version. A smoke test confirms the venv is healthy before
the command returns. Restart Claude Code after the repair completes.

## Skills Location

**Executable**: `${CLAUDE_PLUGIN_ROOT}/skills/deploy-local-plugin/deploy.sh`

## See Also

- Plugin development: `plugins/onex/.claude-plugin/plugin.json`
- Installed plugins registry: `~/.claude/plugins/installed_plugins.json`
