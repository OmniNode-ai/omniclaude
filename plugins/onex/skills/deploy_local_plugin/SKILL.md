---
description: Deploy local plugin files from repository source to Claude Code plugin cache for immediate testing
mode: full
version: 1.0.0
level: advanced
debug: true
category: tooling
tags:
  - deployment
  - plugin
  - development
  - tooling
author: OmniClaude Team
args:
  - name: --list-skills
    description: "Show all skills with level/debug/status (no deploy)"
    required: false
  - name: --select
    description: "Interactive checklist for skill selection"
    required: false
  - name: --skill
    description: "Explicit skill inclusion (comma-separated names)"
    required: false
  - name: --exclude
    description: "Explicit skill exclusion (comma-separated names)"
    required: false
mode: full
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
# Preview what would change (deploys from canonical bare clone, ref: main)
/deploy-local-plugin

# Actually deploy (syncs files + builds lib/.venv)
/deploy-local-plugin --execute

# Deploy from a specific branch, tag, or commit SHA
/deploy-local-plugin --execute --ref release/v0.10.1
/deploy-local-plugin --execute --ref abc1234

# Deploy from an explicit worktree/checkout (opt-in override)
/deploy-local-plugin --execute --source-path /path/to/omniclaude

# New user install — daily driver skills only (excludes debug: true skills)
/deploy-local-plugin --execute --level basic

# Intermediate user install
/deploy-local-plugin --execute --level intermediate

# Full install including debug/diagnostic skills
/deploy-local-plugin --execute --include-debug

# Repair: build lib/.venv in the active deployed version (no file sync, no version bump)
# Use when hooks fail with "No valid Python found" after a deploy
/deploy-local-plugin --repair-venv
```

## Source Resolution

The deploy script resolves its source files deterministically. No silent worktree fallback.

| Priority | Source | Trigger |
|----------|--------|---------|
| 1 | `--source-path <path>` | Explicit flag (deliberate override) |
| 2 | `DEPLOY_SOURCE_PATH` env var | Same as above, env form |
| 3 | Canonical bare clone (`$OMNI_HOME/omniclaude`) | Default — `git archive` into ephemeral staging dir |
| 4 | `CLAUDE_PLUGIN_ROOT` | Legacy fallback (warns), only if outside cache |

**Archive-based deploys** (tier 3) extract plugin files via `git archive` from the canonical
bare clone. This means:
- Exact ref, exact tree, no stale checkout
- Provenance is logged: repo path, ref, concrete commit SHA, staging path
- Staging dir is cleaned up automatically on exit (success or failure)
- Use `--ref` to deploy from a specific branch/tag/SHA (default: `main`)

## Skill Tier Filtering

`--level basic|intermediate|advanced` controls which skills are copied into the plugin cache.
Filtering is **inclusive downward** — lower tiers are always included when a higher tier is requested:

| Flag | Skills included |
|------|----------------|
| `--level basic` | Only `level: basic` skills |
| `--level intermediate` | `level: basic` + `level: intermediate` skills |
| `--level advanced` | All non-debug skills (all levels); `debug: true` skills excluded unless `--include-debug` is passed |

Skills marked `debug: true` are **excluded** from all filtered deploys (any explicit `--level`)
unless `--include-debug` is also passed. When no `--level` flag is used, debug skills are
included as before (backwards-compatible default).

Internal support library dirs (prefixed with `_`) are always included regardless of filter.

## Skill Selection

By default, all skills are deployed. Use these flags to control which skills are included:

### `--list-skills`
Display a table of all skills showing name, level, debug status, and deployment status. Does not deploy.

### `--select`
Interactive checklist mode. Presents all skills grouped by category with checkboxes. Selected skills are deployed; unselected are skipped.

### `--skill <names>`
Deploy only the named skills (comma-separated). Example: `--skill local-review,pr-review,ticket-pipeline`

### `--exclude <names>`
Deploy all skills EXCEPT the named ones (comma-separated). Example: `--exclude debug-only-skill,experimental-feature`

### Selection Persistence
Selections are persisted to `$ONEX_STATE_DIR/plugin-skill-selection.json`. Format:
```json
{
  "included": ["skill-a", "skill-b"],
  "excluded": ["skill-c"],
  "last_updated": "2026-03-04T12:00:00Z"
}
```

Subsequent `--select` runs pre-check previously selected skills. Use `--skill` or `--exclude` to override persisted selections for a single deploy.

## How It Works

### Source → Target Mapping

By default, files are extracted from the canonical bare clone via `git archive`:

| Source (Canonical Repo @ ref) | Target (Cache) |
|-------------------------------|----------------|
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

### Hook Smoke Test Gate (OMN-4383)

Every `--execute` deploy runs `smoke-test-hooks.sh` as a mandatory gate after files are copied
and the venv is built. If any hook fails, the deploy exits non-zero and reports which hook(s)
failed — the deployment is not considered successful until all hooks pass.

To run the smoke tests manually:
```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/deploy_local_plugin/smoke-test-hooks.sh
```

### Version-Agnostic `current/` Symlink

Every `--execute` deploy creates or updates a stable symlink:

```
~/.claude/plugins/cache/omninode-tools/onex/current/  ->  <version>/
```

If `PLUGIN_PYTHON_BIN` is set in `~/.omnibase/.env` with a version-pinned path (e.g.
`/onex/2.2.5/lib/.venv/bin/python3`), the deploy script automatically rewrites it to
the version-agnostic form:

```bash
PLUGIN_PYTHON_BIN=~/.claude/plugins/cache/omninode-tools/onex/current/lib/.venv/bin/python3
```

This means `PLUGIN_PYTHON_BIN` survives future version upgrades without manual changes.
The `current/` symlink is updated atomically on every deploy so the path always resolves
to the live venv.

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
${CLAUDE_PLUGIN_ROOT}/skills/deploy_local_plugin/deploy.sh --repair-venv
```

This builds `lib/.venv` in the currently-active deployed version (from `installed_plugins.json`)
without syncing files or bumping the version. A smoke test confirms the venv is healthy before
the command returns. Restart Claude Code after the repair completes.

### `PLUGIN_PYTHON_BIN` points to wrong version after upgrade

If `PLUGIN_PYTHON_BIN` was set with a version-pinned path (e.g. `.../onex/2.2.5/lib/.venv/...`)
and a new version was deployed, the path silently resolves to an old or missing venv.

**Fix — run a deploy**: The next `--execute` deploy auto-rewrites `PLUGIN_PYTHON_BIN` in
`~/.omnibase/.env` to the version-agnostic form using the `current/` symlink.

**Fix — manual one-liner**:
```bash
# Set PLUGIN_PYTHON_BIN to the version-agnostic current symlink path
AGNOSTIC="$HOME/.claude/plugins/cache/omninode-tools/onex/current/lib/.venv/bin/python3"
sed -i.bak -E \
  "s|^(PLUGIN_PYTHON_BIN=).*/onex/[0-9]+\.[0-9]+\.[0-9]+/lib/\.venv/bin/python3|\1${AGNOSTIC}|" \
  ~/.omnibase/.env
```

After this change, `PLUGIN_PYTHON_BIN` will always resolve to the live venv regardless of
which version is deployed. No further manual updates needed.

## Skills Location

**Executable**: `${CLAUDE_PLUGIN_ROOT}/skills/deploy_local_plugin/deploy.sh`

## See Also

- Plugin development: `plugins/onex/.claude-plugin/plugin.json`
- Installed plugins registry: `~/.claude/plugins/installed_plugins.json`
