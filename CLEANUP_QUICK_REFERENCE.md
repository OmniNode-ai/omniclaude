# Git History Cleanup - Quick Reference

⚠️ **CRITICAL**: Do NOT execute without reading full plan in `GIT_HISTORY_CLEANUP_PLAN.md`

---

## Pre-Flight Checklist

**MUST DO FIRST** (in order):

- [ ] Read `GIT_HISTORY_CLEANUP_PLAN.md` completely
- [ ] Revoke exposed API keys (GEMINI, ZAI)
- [ ] Generate new API keys
- [ ] Notify all team members of upcoming cleanup
- [ ] Install required tools
- [ ] Schedule low-activity window for cleanup

---

## Tool Installation

### Option 1: git-filter-repo (Recommended)
```bash
brew install git-filter-repo
```

### Option 2: BFG Repo-Cleaner
```bash
brew install bfg
```

### Validation Tools (Optional)
```bash
brew install git-secrets gitleaks
pip install truffleHog
```

---

## Quick Start: Complete Cleanup

### Method 1: Using git-filter-repo (Recommended)

```bash
# 1. Dry run first (safe, no changes)
./cleanup-secrets.sh --dry-run

# 2. Review the output, then run actual cleanup
./cleanup-secrets.sh

# 3. Validate results
./validate-cleanup.sh

# 4. Force push to remote (DANGER - point of no return)
git push origin --force --all
git push origin --force --tags
```

### Method 2: Using BFG Repo-Cleaner

```bash
# 1. Run BFG cleanup
./cleanup-secrets-bfg.sh

# 2. Validate results
./validate-cleanup.sh

# 3. Replace repository and force push
# (Follow instructions output by script)
```

---

## Scripts Overview

| Script | Purpose | Risk | Duration |
|--------|---------|------|----------|
| `cleanup-secrets.sh` | Main cleanup using git-filter-repo | HIGH | 10-15 min |
| `cleanup-secrets-bfg.sh` | Alternative using BFG | HIGH | 5-10 min |
| `validate-cleanup.sh` | Verify secrets removed | LOW | 2-5 min |

---

## Command Cheat Sheet

### Before Cleanup

```bash
# Check what will be removed
git log --all --full-history -S "***GEMINI_KEY_REMOVED***"
git log --all --full-history -- agents/parallel_execution/.env

# Create manual backup
BACKUP_DIR="$HOME/git-backups/omniclaude-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
git clone --mirror . "$BACKUP_DIR/backup.git"

# Check working directory is clean
git status
```

### During Cleanup

```bash
# Run dry run first
./cleanup-secrets.sh --dry-run

# Run actual cleanup
./cleanup-secrets.sh

# If using BFG
./cleanup-secrets-bfg.sh
```

### After Cleanup

```bash
# Validate thoroughly
./validate-cleanup.sh

# Deep validation (slow but thorough)
DEEP_SCAN=true ./validate-cleanup.sh

# Check specific secret manually
git log --all --full-history -S "***GEMINI_KEY_REMOVED***"
# Should return: no results

# Verify repository integrity
git fsck --full

# Force push (DANGER)
git push origin --force --all
git push origin --force --tags
```

---

## Exposed Secrets

**⚠️ REVOKE THESE KEYS FIRST**

| Type | Value | Action |
|------|-------|--------|
| GEMINI_API_KEY | `***GEMINI_KEY_REMOVED***` | Revoke at https://makersuite.google.com/app/apikey |
| ZAI_API_KEY | `***ZAI_KEY_REMOVED***` | Revoke at Z.ai dashboard |
| File | `agents/parallel_execution/.env` | Remove from all history |

---

## Timeline

| Step | Duration | Blocking |
|------|----------|----------|
| API Key Revocation | 15 min | YES |
| Backup Creation | 10 min | YES |
| Cleanup Execution | 15 min | YES |
| Validation | 20 min | YES |
| Force Push | 10 min | YES |
| Team Communication | 15 min | YES |
| **TOTAL** | **~2 hours** | |

---

## Team Communication

### Before Cleanup (Send 24h in advance)

```
SUBJECT: [ACTION REQUIRED] Git History Cleanup - Tomorrow [DATE] at [TIME]

We're removing exposed API keys from git history tomorrow.

WHAT: Git history rewrite to remove secrets
WHEN: [DATE] at [TIME]
DURATION: ~2 hours
IMPACT: All commit hashes will change

ACTION REQUIRED AFTER CLEANUP:
1. Delete your local repository
2. Re-clone from GitHub
3. DO NOT push old branches

OPEN PRs: May need recreation - will provide update

Questions? Reply to this email.
```

### After Cleanup

```
SUBJECT: Git History Cleanup COMPLETE - Action Required NOW

Cleanup is complete. All secrets removed.

IMMEDIATE ACTION REQUIRED:
1. Delete local repo: rm -rf /path/to/omniclaude
2. Re-clone: git clone <repo-url>
3. DO NOT push old branches

Questions? Contact [admin]
```

---

## Validation Checklist

After cleanup, verify:

- [ ] `git log -S "***GEMINI_KEY_REMOVED***"` returns no results
- [ ] `git log -S "***ZAI_KEY_REMOVED***"` returns no results
- [ ] `git log -- agents/parallel_execution/.env` returns no results
- [ ] `git fsck --full` passes
- [ ] `./validate-cleanup.sh` passes all checks
- [ ] Commit count is reasonable (~68 expected)
- [ ] All branches present
- [ ] All tags present

---

## Rollback Procedure

If something goes wrong:

```bash
# 1. Locate backup
ls ~/git-backups/

# 2. Restore from backup
BACKUP_DIR="~/git-backups/omniclaude-YYYYMMDD-HHMMSS"
cd /Volumes/PRO-G40/Code
mv omniclaude omniclaude-failed
git clone --mirror "$BACKUP_DIR/backup.git" omniclaude-restore
cd omniclaude-restore
git config --bool core.bare false
git checkout main

# 3. Verify restoration
git log --oneline | head -20
git fsck --full
```

---

## Prevention (Post-Cleanup)

### Update .gitignore

```bash
cat >> .gitignore <<'EOF'

# Environment files
.env
.env.*
*.env

# API keys and secrets
*_api_key*
*_secret*
credentials*.json
secrets*.yaml
EOF

git add .gitignore
git commit -m "chore: enhance .gitignore to prevent secret exposure"
git push
```

### Install git-secrets

```bash
# Install
brew install git-secrets

# Configure for repository
cd /Volumes/PRO-G40/Code/omniclaude
git secrets --install
git secrets --register-aws

# Add custom patterns
git secrets --add 'AIzaSy[0-9A-Za-z_-]{33}'  # Google API keys
git secrets --add '[0-9a-f]{32}\.[0-9A-Za-z]{16}'  # Z.ai pattern

# Test
git secrets --scan-history
```

### Create env.template

```bash
cat > agents/parallel_execution/env.template <<'EOF'
# Copy this file to .env and fill in your API keys
# DO NOT commit .env files to git

GEMINI_API_KEY=your_gemini_api_key_here
ZAI_API_KEY=your_zai_api_key_here

# Instructions:
# 1. Copy: cp env.template .env
# 2. Fill in your keys
# 3. Verify .env is in .gitignore
EOF

git add agents/parallel_execution/env.template
git commit -m "chore: add environment template"
git push
```

---

## Troubleshooting

### "git-filter-repo not found"
```bash
brew install git-filter-repo
# or
pip3 install git-filter-repo
```

### "Working directory has changes"
```bash
git status
git stash save "pre-cleanup-$(date +%Y%m%d)"
```

### "Secrets still found after cleanup"
```bash
# Run validation to identify where
./validate-cleanup.sh

# Check specific commits
git log -S "secret" --all --oneline

# May need to re-run cleanup
./cleanup-secrets.sh
```

### "Force push rejected"
```bash
# Check remote protection rules
# May need to temporarily disable branch protection

# Verify you have force-push permissions
git push origin --force --dry-run
```

---

## Emergency Contacts

**Repository Admin**: [Contact Info]
**Backup Location**: `~/git-backups/`
**Full Documentation**: `GIT_HISTORY_CLEANUP_PLAN.md`

---

## Success Criteria

✅ All checks must pass:

1. No secrets in git history
2. .env file absent from all commits
3. Repository integrity check passes
4. Validation script passes
5. Force push successful
6. Team notified and updated
7. Prevention measures implemented

---

## Key Warnings

⚠️ **POINT OF NO RETURN**: Force push to remote cannot be undone
⚠️ **REVOKE KEYS FIRST**: Always revoke exposed keys before cleanup
⚠️ **BACKUP REQUIRED**: Never run without verified backup
⚠️ **TEAM COORDINATION**: All collaborators must re-clone
⚠️ **PR IMPACT**: Open pull requests will be affected

---

## One-Line Checks

```bash
# Check if secrets exist in history (should return nothing)
git log --all -S "***GEMINI_KEY_REMOVED***" --oneline
git log --all -S "***ZAI_KEY_REMOVED***" --oneline
git log --all -- agents/parallel_execution/.env --oneline

# Full validation
./validate-cleanup.sh

# Repository health
git fsck --full
```

---

**Last Updated**: 2025-10-16
**Status**: Ready for execution (requires user confirmation)
**Risk Level**: HIGH
**Review Required**: YES
