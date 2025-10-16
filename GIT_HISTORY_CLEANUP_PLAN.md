# Git History Cleanup Plan
**Status**: ⚠️ REQUIRES USER CONFIRMATION BEFORE EXECUTION
**Risk Level**: HIGH - This operation rewrites git history
**Last Updated**: 2025-10-16

---

## Executive Summary

This document outlines procedures for removing exposed secrets from git history in the omniclaude repository. The exposed secrets have been committed across multiple commits and must be removed from all branches and tags.

## Exposed Secrets Inventory

### 1. GEMINI_API_KEY
- **Value**: `***GEMINI_KEY_REMOVED***`
- **Status**: ❌ EXPOSED IN COMMITS
- **Action Required**: Revoke key, remove from history
- **Commits Affected**: Minimum 4 commits (see analysis below)

### 2. ZAI_API_KEY
- **Value**: `***ZAI_KEY_REMOVED***`
- **Status**: ❌ EXPOSED IN COMMITS
- **Action Required**: Revoke key, remove from history
- **Commits Affected**: Minimum 4 commits (see analysis below)

### 3. Environment File
- **Path**: `agents/parallel_execution/.env`
- **Status**: ❌ COMMITTED TO HISTORY
- **Action Required**: Remove entire file from all commits
- **Commits Affected**: Minimum 5 commits

### Affected Commits (Identified)
```
a8c5388b236af72c21bf3df4c8fe0fb213c4c8c6 - Merge pull request #10
848d5be49c669890fbd06ed5a212dcf447940741 - polish: Address remaining CodeRabbit review feedback
33f079567c64a9871f7fdea31470f14bcc770779 - refactor: modularize dispatch_runner
740732f0484026c9fa21469bcbb8a6a0f6153da6 - docs(agents): add comprehensive documentation
7872e371e22ee80ffc10cbfe9bf955f39ad81ff5 - feat(framework): add omniclaude core framework
```

---

## Risk Assessment

### High Risk Factors
- ✅ **History Rewrite**: All commit hashes will change after cleanup
- ✅ **Force Push Required**: Remote repository must be force-pushed
- ✅ **Collaborator Impact**: All collaborators must re-clone or rebase
- ✅ **Branch Invalidation**: All local branches and forks become incompatible
- ✅ **PR Disruption**: Open pull requests may require recreation
- ✅ **CI/CD Impact**: Pipeline references to commit hashes will break

### Mitigation Strategies
1. **Backup**: Create complete repository backup before starting
2. **Communication**: Notify all collaborators of timeline
3. **Documentation**: Maintain record of old → new commit hash mapping
4. **Coordination**: Schedule cleanup during low-activity period
5. **Validation**: Verify cleanup success before announcing completion

---

## Prerequisites

### Required Tools

#### Option 1: git-filter-repo (Recommended)
```bash
# Install git-filter-repo
# macOS:
brew install git-filter-repo

# Ubuntu/Debian:
apt-get install git-filter-repo

# Python pip:
pip install git-filter-repo
```

**Advantages**:
- Fast and efficient
- Official Git recommendation
- Handles edge cases well
- Preserves repository integrity

#### Option 2: BFG Repo-Cleaner (Alternative)
```bash
# Install BFG
# macOS:
brew install bfg

# Download manually:
wget https://repo1.maven.org/maven2/com/madgag/bfg/1.14.0/bfg-1.14.0.jar
```

**Advantages**:
- Very fast for large repositories
- Simple command syntax
- Good for file removal

### API Key Revocation (MUST DO FIRST)

**⚠️ CRITICAL**: Revoke exposed keys BEFORE cleaning history:

1. **GEMINI_API_KEY**:
   ```bash
   # Go to Google AI Studio
   # URL: https://makersuite.google.com/app/apikey
   # Revoke key: ***GEMINI_KEY_REMOVED***
   # Generate new key
   # Update local .env files (NOT committed)
   ```

2. **ZAI_API_KEY**:
   ```bash
   # Access Z.ai dashboard
   # Revoke key: ***ZAI_KEY_REMOVED***
   # Generate new key
   # Update local .env files (NOT committed)
   ```

---

## Backup Procedures

### 1. Complete Repository Backup
```bash
# Create timestamped backup
BACKUP_DIR="$HOME/git-backups/omniclaude-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Clone with full history
cd "$BACKUP_DIR"
git clone --mirror /Volumes/PRO-G40/Code/omniclaude omniclaude-backup.git

# Verify backup
cd omniclaude-backup.git
git log --oneline | head -20
git fsck --full

echo "Backup location: $BACKUP_DIR/omniclaude-backup.git"
```

### 2. Export Commit Mapping (Pre-Cleanup)
```bash
# Export all commit hashes before cleanup
cd /Volumes/PRO-G40/Code/omniclaude
git log --all --pretty=format:"%H %s" > ~/git-backups/pre-cleanup-commits.txt
git tag -l > ~/git-backups/pre-cleanup-tags.txt
git branch -a > ~/git-backups/pre-cleanup-branches.txt
```

### 3. Verify Working Directory State
```bash
# Ensure clean working directory
cd /Volumes/PRO-G40/Code/omniclaude
git status

# Stash any uncommitted changes
git stash save "pre-cleanup-stash-$(date +%Y%m%d-%H%M%S)"
```

---

## Cleanup Procedure: Method 1 (git-filter-repo)

### Step 1: Prepare Replacement File
```bash
cd /Volumes/PRO-G40/Code/omniclaude

# Create secrets replacement file
cat > /tmp/secrets-to-remove.txt <<'EOF'
***GEMINI_KEY_REMOVED***==>***GEMINI_KEY_REMOVED***
***ZAI_KEY_REMOVED***==>***ZAI_KEY_REMOVED***
***ZAI_KEY_REMOVED***==>***ZAI_KEY_REMOVED***
EOF
```

### Step 2: Run git-filter-repo
```bash
cd /Volumes/PRO-G40/Code/omniclaude

# IMPORTANT: This modifies history - no going back without backup
./cleanup-secrets.sh

# Or manually:
git filter-repo --force \
  --path agents/parallel_execution/.env --invert-paths \
  --replace-text /tmp/secrets-to-remove.txt
```

### Step 3: Verify Cleanup
```bash
# Verify secrets are removed
git log --all --full-history -S "***GEMINI_KEY_REMOVED***"
# Should return: no results

git log --all --full-history -S "***ZAI_KEY_REMOVED***"
# Should return: no results

git log --all --full-history -- agents/parallel_execution/.env
# Should return: no results

# Check file doesn't exist in any commit
git rev-list --all | xargs git ls-tree -r --name-only | grep "agents/parallel_execution/.env"
# Should return: no results
```

### Step 4: Force Push to Remote
```bash
# ⚠️ DANGER ZONE - This overwrites remote history

# Remove remote tracking
git remote remove origin

# Re-add remote
git remote add origin <your-remote-url>

# Force push all branches
git push origin --force --all

# Force push all tags
git push origin --force --tags
```

---

## Cleanup Procedure: Method 2 (BFG Repo-Cleaner)

### Alternative Approach Using BFG

```bash
cd /Volumes/PRO-G40/Code/omniclaude

# 1. Clone a fresh mirror
cd ..
git clone --mirror /Volumes/PRO-G40/Code/omniclaude omniclaude-bfg.git
cd omniclaude-bfg.git

# 2. Create secrets file
cat > ../secrets.txt <<'EOF'
***GEMINI_KEY_REMOVED***
***ZAI_KEY_REMOVED***
***ZAI_KEY_REMOVED***
EOF

# 3. Remove secrets with BFG
bfg --replace-text ../secrets.txt

# 4. Remove .env file
bfg --delete-files .env

# 5. Clean up
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# 6. Push changes
git push origin --force --all
git push origin --force --tags
```

---

## Validation Steps

### Post-Cleanup Verification Checklist

- [ ] **Secret Scan**: No secrets appear in git log
  ```bash
  git log --all --full-history -S "***GEMINI_KEY_REMOVED***"
  git log --all --full-history -S "***ZAI_KEY_REMOVED***"
  ```

- [ ] **File Removal**: `.env` file absent from history
  ```bash
  git log --all --full-history -- agents/parallel_execution/.env
  ```

- [ ] **Repository Integrity**: fsck passes
  ```bash
  git fsck --full
  ```

- [ ] **Commit Count**: Similar number of commits
  ```bash
  git rev-list --all --count
  # Should be close to 68 (original count)
  ```

- [ ] **Branch Verification**: All branches present
  ```bash
  git branch -a
  ```

- [ ] **Tag Verification**: All tags present
  ```bash
  git tag -l
  ```

- [ ] **Build Verification**: Project builds successfully
  ```bash
  poetry install
  poetry run pytest
  ```

### External Validation Tools

```bash
# Use git-secrets to scan for patterns
git secrets --scan --scan-history

# Use truffleHog for secret detection
trufflehog git file:///Volumes/PRO-G40/Code/omniclaude --json

# Use gitleaks for comprehensive scan
gitleaks detect --source /Volumes/PRO-G40/Code/omniclaude --verbose
```

---

## Collaborator Communication Plan

### Pre-Cleanup Announcement

**Subject**: [URGENT] Git History Rewrite - Action Required

**Message Template**:
```
Team,

We are performing a git history cleanup to remove exposed API keys from
our repository history. This will rewrite commit history and require
action from all collaborators.

TIMELINE:
- Cleanup Start: [DATE/TIME]
- Estimated Duration: 2-4 hours
- Repository Freeze: Yes

ACTION REQUIRED AFTER CLEANUP:
1. Delete your local repository
2. Re-clone from remote
3. Recreate any local branches
4. DO NOT push old branches

OPEN PULL REQUESTS:
- All open PRs may need to be recreated
- We will provide guidance after cleanup completes

AFFECTED COMMITS:
- All commit hashes will change
- References to old commits will be invalid

BACKUP:
- We have full backups of the repository pre-cleanup
- Contact [ADMIN] if you need access to old commits

Please confirm receipt of this message.
```

### Post-Cleanup Instructions

**Subject**: Git History Cleanup Complete - Action Required

**Message Template**:
```
Team,

Git history cleanup is complete. All API keys have been removed.

IMMEDIATE ACTIONS REQUIRED:
1. Delete your local repository:
   rm -rf /path/to/omniclaude

2. Re-clone from GitHub:
   git clone <repository-url>

3. Verify your checkout:
   cd omniclaude
   git log --oneline | head -10

4. DO NOT push old branches - they will be rejected

NEW COMMIT HASHES:
- Old commits are invalid
- See commit mapping file: [LINK]

OPEN PULL REQUESTS:
- Status: [UPDATE HERE]
- Action: [GUIDANCE HERE]

Questions? Contact: [ADMIN]
```

---

## Rollback Procedures

### If Cleanup Fails Mid-Process

```bash
# 1. Restore from backup
cd ~/git-backups/omniclaude-YYYYMMDD-HHMMSS
git clone --mirror omniclaude-backup.git /tmp/omniclaude-restore

# 2. Replace working directory
cd /Volumes/PRO-G40/Code
mv omniclaude omniclaude-failed-cleanup
git clone /tmp/omniclaude-restore omniclaude

# 3. Verify restoration
cd omniclaude
git log --oneline | head -20
git fsck --full
```

### If Remote Push Fails

```bash
# 1. Check remote status
git remote -v

# 2. Verify backup exists
ls -lh ~/git-backups/

# 3. Re-add remote without force push
git remote remove origin
git remote add origin <url>

# 4. Attempt resolution
git fetch origin
git log --oneline --graph --all | head -30

# 5. If needed, restore backup and retry
```

---

## Post-Cleanup Best Practices

### 1. Prevent Future Exposure

**Create .gitignore rules**:
```bash
# Add to .gitignore if not present
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
```

### 2. Implement git-secrets

```bash
# Install git-secrets
brew install git-secrets

# Configure for repository
cd /Volumes/PRO-G40/Code/omniclaude
git secrets --install
git secrets --register-aws

# Add custom patterns
git secrets --add 'AIzaSy[0-9A-Za-z_-]{33}'  # Google API keys
git secrets --add '[0-9a-f]{32}\.[0-9A-Za-z]{16}'  # Z.ai pattern
```

### 3. Pre-commit Hooks

**Create `.git/hooks/pre-commit`**:
```bash
#!/bin/bash
# Pre-commit hook to prevent secret commits

# Check for common secret patterns
if git diff --cached | grep -iE "(api_key|secret|password|token)" | grep -vE "^[-+]#"; then
    echo "❌ ERROR: Potential secret detected in commit"
    echo "Review your changes and remove secrets before committing"
    exit 1
fi

# Run git-secrets if installed
if command -v git-secrets &> /dev/null; then
    git secrets --pre_commit_hook -- "$@"
fi

exit 0
```

### 4. Environment Variable Management

**Create `env.template`**:
```bash
# Create template for developers
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
git commit -m "chore: add environment template for developers"
```

---

## Reference: Cleanup Script Usage

### cleanup-secrets.sh

**Location**: `/Volumes/PRO-G40/Code/omniclaude/cleanup-secrets.sh`

**Usage**:
```bash
# Make executable
chmod +x cleanup-secrets.sh

# Review the script first
cat cleanup-secrets.sh

# Run with confirmation
./cleanup-secrets.sh

# The script will:
# 1. Verify prerequisites
# 2. Create backup
# 3. Run git-filter-repo
# 4. Validate results
# 5. Provide next steps
```

**Dry Run** (recommended first):
```bash
# Test without making changes
./cleanup-secrets.sh --dry-run
```

---

## FAQ

### Q: Will this affect my local branches?
**A**: Yes. All local branches will become incompatible with the rewritten history. You must delete and re-clone.

### Q: What about pull requests?
**A**: Open PRs will likely need to be recreated. The base commits will have changed.

### Q: Can I keep my local changes?
**A**: Yes, but you'll need to:
1. Export your changes as patches: `git format-patch origin/main`
2. Re-clone the repository
3. Re-apply patches: `git am *.patch`

### Q: How long does cleanup take?
**A**: For a repository with 68 commits, expect 5-15 minutes for the cleanup itself, plus time for validation and force-push.

### Q: What if I push old commits by mistake?
**A**: The force-push will reject them if protection rules are set. Contact admin immediately if this happens.

### Q: Can we recover old commits?
**A**: Yes, from the backup. But the cleanup will need to be re-run if you restore old commits.

---

## Timeline Estimate

| Phase | Duration | Description |
|-------|----------|-------------|
| Preparation | 30 min | Install tools, verify backups, notify team |
| API Key Revocation | 15 min | Revoke exposed keys, generate new ones |
| Backup Creation | 10 min | Full repository backup with verification |
| History Cleanup | 15 min | Run git-filter-repo on all branches |
| Validation | 20 min | Comprehensive validation checks |
| Force Push | 10 min | Push rewritten history to remote |
| Team Communication | 15 min | Notify team, provide instructions |
| **TOTAL** | **2 hours** | Complete cleanup operation |

---

## Checklist: Execution Day

### Pre-Cleanup (30 minutes before)
- [ ] All team members notified
- [ ] API keys revoked and new ones generated
- [ ] Backup created and verified
- [ ] Tools installed (git-filter-repo or BFG)
- [ ] No critical work in progress
- [ ] Cleanup scripts reviewed

### During Cleanup
- [ ] Run backup creation script
- [ ] Run cleanup script
- [ ] Validate results (all checks pass)
- [ ] Force push to remote
- [ ] Verify remote state

### Post-Cleanup
- [ ] Send team notification with instructions
- [ ] Update documentation with new commit references
- [ ] Monitor for issues from team members
- [ ] Archive backup safely
- [ ] Update .gitignore and add pre-commit hooks
- [ ] Mark cleanup as complete

---

## Emergency Contacts

**If something goes wrong**:
1. **STOP** - Do not continue if uncertain
2. **Backup** - Ensure backup exists and is valid
3. **Contact** - Reach out to repository admin
4. **Rollback** - Use procedures above if needed

**Backup Location**: `~/git-backups/omniclaude-YYYYMMDD-HHMMSS/`

**Support Resources**:
- git-filter-repo docs: https://github.com/newren/git-filter-repo
- BFG Repo-Cleaner: https://rtyley.github.io/bfg-repo-cleaner/
- Git History Rewriting: https://git-scm.com/book/en/v2/Git-Tools-Rewriting-History

---

## Conclusion

This cleanup operation is critical for security but carries significant risks. Follow this plan carefully, ensure all backups are in place, and communicate clearly with all collaborators.

**Remember**: The goal is to remove exposed secrets permanently from git history while maintaining repository integrity and minimizing disruption to the team.

**Status After Cleanup**:
- ✅ Secrets removed from history
- ✅ Repository integrity maintained
- ✅ Team notified and updated
- ✅ Prevention measures in place

---

**Document Version**: 1.0
**Author**: Automated cleanup planning system
**Review Required**: YES - Human review before execution
**Approval Required**: YES - Repository admin approval before execution
