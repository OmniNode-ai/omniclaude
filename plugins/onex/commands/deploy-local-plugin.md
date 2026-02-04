---
name: deploy-local-plugin
description: Deploy local plugin files to Claude Code plugin cache for testing
tags: [tooling, deployment, plugin]
args:
  - name: execute
    description: Actually perform deployment (default is dry-run)
    required: false
  - name: no-version-bump
    description: Skip auto-incrementing the patch version
    required: false
---

# Deploy Local Plugin

Deploy the local plugin source to the Claude Code plugin cache for testing.

**Announce at start:** "Deploying local plugin to cache..."

## Overview

This command syncs plugin files from the repository source to the installed plugin cache:
- **Source**: `${CLAUDE_PLUGIN_ROOT}` (plugins/onex/)
- **Target**: `~/.claude/plugins/cache/omninode-tools/onex/{version}/`

## Default Behavior: Dry Run

By default, the command shows what would change without making modifications:

```
/deploy-local-plugin
```

Output:
```
[DRY RUN] Would deploy local plugin to cache

Current version: 2.1.2
New version: 2.1.3

Files to sync:
  commands/: 16 files
  skills/: 31 directories
  agents/: 53 configs
  hooks/: scripts and config

Target: ~/.claude/plugins/cache/omninode-tools/onex/2.1.3/

Use --execute to apply changes.
```

## Execute Mode

To actually deploy, use the `--execute` flag:

```
/deploy-local-plugin --execute
```

## Skip Version Bump

To deploy without incrementing the version (overwrites current version):

```
/deploy-local-plugin --execute --no-version-bump
```

## Execution Flow

### Step 1: Read Current State

```bash
# Read plugin.json for current version
PLUGIN_JSON="${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json"
CURRENT_VERSION=$(jq -r '.version' "$PLUGIN_JSON")

# Determine target directory
CACHE_BASE="$HOME/.claude/plugins/cache/omninode-tools/onex"
```

### Step 2: Calculate New Version

```bash
# Parse version components (e.g., 2.1.2 -> 2 1 2)
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

# Bump patch unless --no-version-bump
if [[ "$NO_VERSION_BUMP" != "true" ]]; then
    NEW_PATCH=$((PATCH + 1))
    NEW_VERSION="${MAJOR}.${MINOR}.${NEW_PATCH}"
else
    NEW_VERSION="$CURRENT_VERSION"
fi
```

### Step 3: Preview Changes (Dry Run)

```bash
echo "=== Plugin Deployment Preview ==="
echo ""
echo "Version: $CURRENT_VERSION -> $NEW_VERSION"
echo "Source:  ${CLAUDE_PLUGIN_ROOT}"
echo "Target:  ${CACHE_BASE}/${NEW_VERSION}"
echo ""
echo "Components to sync:"

# Count files in each component
echo "  commands/:      $(ls -1 ${CLAUDE_PLUGIN_ROOT}/commands/*.md 2>/dev/null | wc -l | tr -d ' ') files"
echo "  skills/:        $(ls -1d ${CLAUDE_PLUGIN_ROOT}/skills/*/ 2>/dev/null | wc -l | tr -d ' ') directories"
echo "  agents/configs: $(ls -1 ${CLAUDE_PLUGIN_ROOT}/agents/configs/*.yaml 2>/dev/null | wc -l | tr -d ' ') files"
echo "  hooks/:         $(ls -1 ${CLAUDE_PLUGIN_ROOT}/hooks/ 2>/dev/null | wc -l | tr -d ' ') items"
echo "  .claude-plugin: plugin.json + metadata"
```

### Step 4: Execute Deployment

```bash
if [[ "$EXECUTE" == "true" ]]; then
    TARGET="${CACHE_BASE}/${NEW_VERSION}"

    # Update version in source plugin.json first (if bumping)
    if [[ "$NO_VERSION_BUMP" != "true" ]]; then
        jq --arg v "$NEW_VERSION" '.version = $v' "$PLUGIN_JSON" > "${PLUGIN_JSON}.tmp"
        mv "${PLUGIN_JSON}.tmp" "$PLUGIN_JSON"
        echo "Updated plugin.json version to $NEW_VERSION"
    fi

    # Create target directory
    mkdir -p "$TARGET"

    # Sync components
    rsync -av --delete "${CLAUDE_PLUGIN_ROOT}/commands/" "${TARGET}/commands/"
    rsync -av --delete "${CLAUDE_PLUGIN_ROOT}/skills/" "${TARGET}/skills/"
    rsync -av --delete "${CLAUDE_PLUGIN_ROOT}/agents/" "${TARGET}/agents/"
    rsync -av --delete "${CLAUDE_PLUGIN_ROOT}/hooks/" "${TARGET}/hooks/"
    rsync -av --delete "${CLAUDE_PLUGIN_ROOT}/.claude-plugin/" "${TARGET}/.claude-plugin/"

    # Copy additional files
    cp "${CLAUDE_PLUGIN_ROOT}/.env.example" "${TARGET}/" 2>/dev/null || true
    cp "${CLAUDE_PLUGIN_ROOT}/README.md" "${TARGET}/" 2>/dev/null || true
    cp "${CLAUDE_PLUGIN_ROOT}/ENVIRONMENT_VARIABLES.md" "${TARGET}/" 2>/dev/null || true

    echo ""
    echo "Deployment complete!"
fi
```

### Step 5: Update Registry

```bash
REGISTRY="$HOME/.claude/plugins/installed_plugins.json"

if [[ -f "$REGISTRY" && "$EXECUTE" == "true" ]]; then
    # Update lastUpdated timestamp
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")

    jq --arg ts "$TIMESTAMP" --arg v "$NEW_VERSION" --arg p "$TARGET" '
        .plugins["onex@omninode-tools"][0].lastUpdated = $ts |
        .plugins["onex@omninode-tools"][0].version = $v |
        .plugins["onex@omninode-tools"][0].installPath = $p
    ' "$REGISTRY" > "${REGISTRY}.tmp"

    mv "${REGISTRY}.tmp" "$REGISTRY"
    echo "Updated installed_plugins.json"
fi
```

## What Gets Synced

| Directory | Contents | Notes |
|-----------|----------|-------|
| `commands/` | Slash command definitions | 16 .md files |
| `skills/` | Skill directories with SKILL.md | 31+ skills |
| `agents/configs/` | YAML agent definitions | 53 configs |
| `hooks/` | Hook scripts and lib/ | Event handlers |
| `.claude-plugin/` | plugin.json | Plugin metadata |

## Error Handling

| Error | Behavior |
|-------|----------|
| Missing plugin.json | Report error, abort |
| Target exists (same version) | Warn, overwrite with rsync --delete |
| Registry update fails | Warn but continue (non-blocking) |
| Permission denied | Report error with suggested fix |

## Verification

After deployment, verify with:

```bash
# Check version in cache
cat ~/.claude/plugins/cache/omninode-tools/onex/*/plugin.json | jq -r '.version' | sort -V | tail -1

# Count synced commands
ls -1 ~/.claude/plugins/cache/omninode-tools/onex/*/commands/*.md | wc -l

# Restart Claude Code to pick up changes
# (plugins are loaded at session start)
```

## Examples

### Preview deployment (default)
```
/deploy-local-plugin
```

### Execute deployment
```
/deploy-local-plugin --execute
```

### Deploy without version bump
```
/deploy-local-plugin --execute --no-version-bump
```
