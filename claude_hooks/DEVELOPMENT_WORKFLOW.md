# Development Workflow for Claude Hooks

This directory serves as a **git-tracked development environment** for the AI-Enhanced Quality Enforcement System hooks.

## Overview

Instead of editing files directly in `~/.claude/hooks/`, we:
1. ✅ **Work in this repository** (version controlled)
2. ✅ **Test changes safely**
3. ✅ **Sync to live directory** when ready
4. ✅ **Commit to git** for backup

## Directory Structure

```
claude-hooks-backup/          # Git-tracked development directory
├── lib/                      # Core libraries
├── tests/                    # Test suite
├── bin/                      # Utilities
├── logs/                     # Sample logs (not synced)
├── sync-to-live.sh          # Sync repo → live
├── sync-from-live.sh        # Sync live → repo
└── DEVELOPMENT_WORKFLOW.md  # This file
```

```
~/.claude/hooks/             # Live directory (active hooks)
├── lib/                     # Actual running code
├── tests/                   # Working tests
├── logs/                    # Active logs
└── quality_enforcer.py      # Running orchestrator
```

## Workflow: Repository → Live (Recommended)

### 1. Make Changes in Repository

Edit files in `claude-hooks-backup/`:

```bash
cd ${ARCHON_ROOT}/claude-hooks-backup

# Edit files
vim lib/validators/naming_validator.py

# Run tests locally
python3 -m pytest tests/ -v
```

### 2. Preview Changes

See what will be synced:

```bash
./sync-to-live.sh --dry-run
```

Output:
```
╔══════════════════════════════════════════════════════════════╗
║         Sync Repository to Live Hooks Directory             ║
╚══════════════════════════════════════════════════════════════╝

Source: ${ARCHON_ROOT}/claude-hooks-backup
Target: ${HOME}/.claude/hooks

Files to sync:
----------------------------------------
lib/validators/naming_validator.py
lib/consensus/quorum.py
quality_enforcer.py
----------------------------------------

Total files to sync: 3
```

### 3. Sync to Live

Apply changes to live directory:

```bash
./sync-to-live.sh
```

Confirm when prompted:
```
Proceed with sync? (y/N) y
```

### 4. Test in Claude Code

The changes are now live. Test them:

```bash
# Watch logs
tail -f ~/.claude/hooks/logs/quality_enforcer.log

# Create a test file with violations in Claude Code
# The hook should intercept and validate
```

### 5. Commit to Git

If everything works:

```bash
git add .
git commit -m "feat: improve naming validator performance"
git push
```

## Workflow: Live → Repository (Quick Fixes)

If you made a quick fix directly in `~/.claude/hooks/`, sync it back:

### 1. Preview Reverse Sync

```bash
./sync-from-live.sh --dry-run
```

### 2. Sync from Live

```bash
./sync-from-live.sh
```

### 3. Review and Commit

```bash
git diff  # Review changes
git add .
git commit -m "sync: update from live hooks"
```

## What Gets Synced

### ✅ Synced Files
- All Python files (`.py`)
- Shell scripts (`.sh`)
- Configuration files (`.yaml`, `.json`)
- Documentation (`.md`)
- Test files

### ❌ Not Synced (Excluded)
- `.cache/` - Cache files
- `__pycache__/` - Python bytecode
- `logs/*.log` - Active logs
- `logs/*.jsonl` - Decision logs
- `.DS_Store` - macOS metadata

## Example: Adding Phase 2 (RAG Integration)

Let's walk through enabling Phase 2:

### 1. Edit Configuration in Repo

```bash
cd claude-hooks-backup
vim config.yaml
```

Change:
```yaml
rag:
  enabled: false  # Phase 1
```

To:
```yaml
rag:
  enabled: true   # Phase 2
  base_url: "http://localhost:8051"
```

### 2. Test Configuration

```bash
# Validate YAML syntax
python3 -c "import yaml; yaml.safe_load(open('config.yaml'))"
```

### 3. Preview Sync

```bash
./sync-to-live.sh --dry-run
```

Should show:
```
Files to sync:
----------------------------------------
config.yaml
----------------------------------------
Total files to sync: 1
```

### 4. Sync to Live

```bash
./sync-to-live.sh
# Confirm with 'y'
```

### 5. Test Phase 2

Watch logs while creating files:
```bash
tail -f ~/.claude/hooks/logs/quality_enforcer.log
```

Should now see:
```
[Phase 2] Querying RAG intelligence...
[Phase 2] Retrieved conventions - 0.250s
```

### 6. Commit

```bash
git add config.yaml
git commit -m "feat: enable Phase 2 RAG intelligence"
git push
```

## Troubleshooting

### Sync Shows No Changes

If `sync-to-live.sh` shows no files to sync:

```bash
# Check file differences
diff -r claude-hooks-backup ~/.claude/hooks --exclude=".cache" --exclude="logs"

# Force sync everything
rsync -av --delete claude-hooks-backup/ ~/.claude/hooks/
```

### Sync Direction Confusion

- **To Live** (`sync-to-live.sh`): Repository → `~/.claude/hooks/`
  - Use this 99% of the time (normal development)

- **From Live** (`sync-from-live.sh`): `~/.claude/hooks/` → Repository
  - Use this only for quick fixes you made directly in live directory

### Changes Not Taking Effect

After syncing, Claude Code caches may need refresh:

1. **Restart Claude Code** (hooks reload on restart)
2. **Check logs** for errors: `tail ~/.claude/hooks/logs/quality_enforcer.log`
3. **Verify file permissions**: `ls -la ~/.claude/hooks/quality_enforcer.py`

### Sync Conflicts

If you edited both repository and live directory:

```bash
# Back up live changes first
cp -r ~/.claude/hooks ~/claude-hooks-backup-$(date +%Y%m%d)

# Then decide which to keep:
# Option 1: Keep repository version
./sync-to-live.sh

# Option 2: Keep live version
./sync-from-live.sh
```

## Best Practices

### ✅ Do This

- **Always edit in repository first**
- **Test changes before syncing**
- **Use `--dry-run` to preview**
- **Commit working changes immediately**
- **Keep descriptive commit messages**
- **Run tests before syncing to live**

### ❌ Avoid This

- **Don't edit live directory unless emergency**
- **Don't skip testing**
- **Don't sync untested changes to live**
- **Don't forget to commit after syncing**
- **Don't sync logs or cache files**

## Quick Reference

| Task | Command |
|------|---------|
| Preview sync to live | `./sync-to-live.sh --dry-run` |
| Sync to live | `./sync-to-live.sh` |
| Sync from live | `./sync-from-live.sh` |
| Test changes | `python3 -m pytest tests/ -v` |
| Watch logs | `tail -f ~/.claude/hooks/logs/quality_enforcer.log` |
| Validate YAML | `python3 -c "import yaml; yaml.safe_load(open('config.yaml'))"` |
| Check differences | `diff -r . ~/.claude/hooks --exclude=logs` |

## Development Cycle

```
┌─────────────────────────────────────────────────────────┐
│                    Development Cycle                     │
└─────────────────────────────────────────────────────────┘

1. Edit in Repository
   └─→ vim claude-hooks-backup/lib/validators/naming_validator.py

2. Run Tests
   └─→ pytest tests/ -v

3. Preview Sync
   └─→ ./sync-to-live.sh --dry-run

4. Sync to Live
   └─→ ./sync-to-live.sh

5. Test in Claude Code
   └─→ tail -f ~/.claude/hooks/logs/quality_enforcer.log

6. Commit Changes
   └─→ git add . && git commit && git push

7. (Optional) Sync back for quick fixes
   └─→ ./sync-from-live.sh
```

## Phase Progression Workflow

As you advance through phases:

### Phase 1 → Phase 2 (Enable RAG)

```bash
# Edit config
vim config.yaml  # Set rag.enabled: true

# Sync and test
./sync-to-live.sh
tail -f ~/.claude/hooks/logs/quality_enforcer.log

# Commit
git add config.yaml
git commit -m "feat: enable Phase 2 RAG intelligence"
```

### Phase 2 → Phase 4 (Enable AI Quorum)

```bash
# Edit config
vim config.yaml  # Set quorum.enabled: true

# Update orchestrator environment
export ENABLE_PHASE_4_AI_QUORUM=true

# Sync and test
./sync-to-live.sh

# Commit
git add config.yaml
git commit -m "feat: enable Phase 4 AI quorum scoring"
```

## Recovery

If something goes wrong, you can always restore from git:

```bash
# Restore to last commit
git checkout .

# Sync clean version to live
./sync-to-live.sh

# Or restore from a specific commit
git checkout <commit-hash> .
./sync-to-live.sh
```

---

**Happy Coding!** 🚀

This workflow keeps your hooks safe, version-controlled, and easy to iterate on.