# Security Remediation Checklist

**Date**: 2025-10-16
**Priority**: CRITICAL
**Estimated Time**: 2-4 hours

---

## ⚠️ CRITICAL - Do This First (30 minutes)

### 1. Revoke Exposed API Keys

- [ ] **Google Gemini API Key**: `***GEMINI_KEY_REMOVED***`
  - Go to: https://console.cloud.google.com/apis/credentials
  - Locate and DELETE this key
  - Generate new key and save securely
  - Time: ~5 minutes

- [ ] **Z.ai API Key**: `***ZAI_KEY_REMOVED***`
  - Go to Z.ai dashboard
  - Revoke this key
  - Generate new key and save securely
  - Time: ~5 minutes

### 2. Set Environment Variables

```bash
# Add to ~/.bashrc or ~/.zshrc
export GEMINI_API_KEY="your_new_gemini_key_here"
export ZAI_API_KEY="your_new_zai_key_here"

# Source the file
source ~/.bashrc  # or ~/.zshrc
```

- [ ] Set `GEMINI_API_KEY` environment variable
- [ ] Set `ZAI_API_KEY` environment variable
- [ ] Verify: `echo $GEMINI_API_KEY` (should show your key)
- [ ] Time: ~5 minutes

---

## 🔧 HIGH PRIORITY - Fix Hardcoded Secrets (1 hour)

### 3. Update claude-providers.json

```bash
cd /Volumes/PRO-G40/Code/omniclaude

# Backup original
cp claude-providers.json claude-providers.json.backup

# Replace hardcoded keys with environment variable placeholders
sed -i '' 's/"api_key": "***GEMINI_KEY_REMOVED***"/"api_key": "${GEMINI_API_KEY}"/g' claude-providers.json
sed -i '' 's/"api_key": "***ZAI_KEY_REMOVED***"/"api_key": "${ZAI_API_KEY}"/g' claude-providers.json

# Verify changes
grep -n "api_key" claude-providers.json
```

- [ ] Backup `claude-providers.json`
- [ ] Replace Google API key with `${GEMINI_API_KEY}`
- [ ] Replace Z.ai API key with `${ZAI_API_KEY}`
- [ ] Verify no hardcoded keys remain
- [ ] Time: ~10 minutes

### 4. Update toggle-claude-provider.sh

```bash
# Replace hardcoded Google API key in shell script
sed -i '' 's/***GEMINI_KEY_REMOVED***/${GEMINI_API_KEY}/g' toggle-claude-provider.sh

# Verify changes
grep -n "AIza" toggle-claude-provider.sh  # Should return no results
```

- [ ] Replace hardcoded API key in `toggle-claude-provider.sh`
- [ ] Verify script still works: `./toggle-claude-provider.sh status`
- [ ] Time: ~10 minutes

### 5. Update Documentation Files

```bash
# Update HANDOFF.md with placeholder
sed -i '' 's/GEMINI_API_KEY=***GEMINI_KEY_REMOVED***/GEMINI_API_KEY=your_gemini_api_key_here/g' agents/parallel_execution/HANDOFF.md

# Verify
grep -n "AIza" agents/parallel_execution/HANDOFF.md  # Should return no results
```

- [ ] Update `agents/parallel_execution/HANDOFF.md`
- [ ] Verify documentation shows placeholder values only
- [ ] Time: ~5 minutes

### 6. Commit Security Fixes

```bash
git add claude-providers.json toggle-claude-provider.sh agents/parallel_execution/HANDOFF.md
git commit -m "security: Remove hardcoded API keys and replace with environment variables

- Replaced Google Gemini API key with ${GEMINI_API_KEY}
- Replaced Z.ai API key with ${ZAI_API_KEY}
- Updated documentation to use placeholders
- Revoked exposed keys and generated new ones

BREAKING CHANGE: Users must now set GEMINI_API_KEY and ZAI_API_KEY
environment variables before using the provider toggle script."

git push origin feature/phase-7-refinement-optimization
```

- [ ] Stage security fix changes
- [ ] Commit with descriptive message
- [ ] Push to remote
- [ ] Time: ~5 minutes

---

## 📝 MEDIUM PRIORITY - Clean Up Sensitive Data (1 hour)

### 7. Add .gitignore Entries

Create or update `.gitignore`:

```bash
cat >> .gitignore << 'EOF'

# Security - Environment variables
.env
.env.local
.env.*.local
*.env

# Logs and traces (may contain sensitive data)
traces/
logs/
*.log

# Build artifacts
htmlcov/
.coverage
.pytest_cache/
*.pyc
__pycache__/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
EOF
```

- [ ] Add `.env` files to `.gitignore`
- [ ] Add `traces/` directory to `.gitignore`
- [ ] Add `htmlcov/` to `.gitignore`
- [ ] Commit `.gitignore` changes
- [ ] Time: ~10 minutes

### 8. Remove Trace Files (Optional)

```bash
# Review trace files first
ls -lh traces/

# If they contain sensitive data, remove them
git rm -r traces/
git commit -m "chore: Remove trace files containing sensitive data

Trace files contained:
- Personal email addresses
- Absolute file paths with usernames
- Example credentials

These are now excluded via .gitignore."
```

- [ ] Review contents of `traces/` directory
- [ ] Decide if traces should be in version control
- [ ] Remove if they contain sensitive data
- [ ] Time: ~15 minutes

### 9. Fix Hardcoded File Paths

**File**: `agents/lib/enhanced_router.py`

```python
# Before (line 70)
registry_path: str = "/Users/jonah/.claude/agent-definitions/agent-registry.yaml"

# After
registry_path: str = os.path.expanduser("~/.claude/agent-definitions/agent-registry.yaml")
```

- [ ] Update `agents/lib/enhanced_router.py` (lines 70, 284)
- [ ] Update `agents/detect_archon_integration.py` (line 161)
- [ ] Update `claude_hooks/debug_utils.py` (lines 289, 429)
- [ ] Test that paths still work
- [ ] Time: ~15 minutes

### 10. Replace Hardcoded IP Addresses

**Files to update**:
- `claude_hooks/config.yaml`
- `claude_hooks/lib/ai_agent_selector.py`

```yaml
# Before
base_url: "http://192.168.86.201:8000/v1"

# After
base_url: "${VLLM_ENDPOINT:-http://localhost:8000/v1}"
```

```python
# Before
endpoint = "http://192.168.86.201:8001"

# After
endpoint = os.getenv("VLLM_ENDPOINT", "http://localhost:8001")
```

- [ ] Create environment variables for server endpoints
- [ ] Update `claude_hooks/config.yaml`
- [ ] Update `claude_hooks/lib/ai_agent_selector.py`
- [ ] Update documentation with new environment variables
- [ ] Time: ~20 minutes

---

## 🛡️ LOW PRIORITY - Prevention (1-2 hours)

### 11. Add Pre-commit Hook

Create `.git/hooks/pre-commit`:

```bash
#!/bin/bash
# Pre-commit hook to prevent committing secrets

echo "🔍 Scanning for secrets..."

# Check for AWS keys
if git diff --cached --diff-filter=ACM | grep -E "AKIA[0-9A-Z]{16}"; then
    echo "❌ Error: Possible AWS access key detected"
    exit 1
fi

# Check for Google API keys
if git diff --cached --diff-filter=ACM | grep -E "AIza[0-9A-Za-z_-]{35}"; then
    echo "❌ Error: Google API key detected"
    exit 1
fi

# Check for private keys
if git diff --cached --diff-filter=ACM | grep -E "BEGIN.*PRIVATE KEY"; then
    echo "❌ Error: Private key detected"
    exit 1
fi

# Check for generic secrets
if git diff --cached --diff-filter=ACM | grep -E "['\"][0-9a-f]{32,}['\"]"; then
    echo "⚠️  Warning: Possible secret detected (long hex string)"
    echo "Review changes carefully before committing"
    # Don't exit 1 here - just warn
fi

echo "✅ Secret scan passed"
exit 0
```

```bash
# Make executable
chmod +x .git/hooks/pre-commit

# Test it
git add SECURITY_SCAN_REPORT.md
git commit -m "test: pre-commit hook"  # Should pass
```

- [ ] Create pre-commit hook script
- [ ] Make script executable
- [ ] Test with a safe commit
- [ ] Test with a commit containing a fake secret
- [ ] Time: ~20 minutes

### 12. Create Environment Variable Template

Create `.env.template`:

```bash
cat > .env.template << 'EOF'
# ============================================
# OmniClaude Environment Variables Template
# ============================================
# Copy this file to .env and fill in your values
# DO NOT commit .env to version control

# API Keys
GEMINI_API_KEY=your_gemini_api_key_here
ZAI_API_KEY=your_zai_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Server Endpoints
OLLAMA_ENDPOINT=http://localhost:11434
VLLM_ENDPOINT=http://localhost:8001
MAC_MINI_ENDPOINT=http://localhost:11434

# Database (if needed)
POSTGRES_HOST=localhost
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_secure_password_here

# Agent Configuration
CLAUDE_AGENT_REGISTRY=~/.claude/agent-definitions/agent-registry.yaml
CLAUDE_HOOKS_PATH=~/.claude/hooks
EOF
```

- [ ] Create `.env.template` file
- [ ] Add documentation for each variable
- [ ] Update README.md to reference `.env.template`
- [ ] Time: ~15 minutes

### 13. Update README.md

Add security setup section to README.md:

```markdown
## 🔐 Security Setup

### Environment Variables

1. Copy the template:
   ```bash
   cp .env.template .env
   ```

2. Edit `.env` and add your API keys:
   ```bash
   # Get Google Gemini API key from:
   # https://console.cloud.google.com/apis/credentials

   # Get Z.ai API key from:
   # https://z.ai/dashboard
   ```

3. Source the environment:
   ```bash
   source .env
   ```

### Never Commit Secrets

- `.env` files are excluded via `.gitignore`
- Pre-commit hooks scan for accidental secret commits
- Use environment variables, never hardcode keys

### Security Audits

Run security scan:
```bash
grep -r "api_key.*=" . --include="*.py" --include="*.sh"
```
```

- [ ] Add security setup section to README.md
- [ ] Document environment variable setup
- [ ] Add security best practices
- [ ] Time: ~15 minutes

---

## ✅ Verification Checklist

### Test Everything Still Works

- [ ] Provider toggle script: `./toggle-claude-provider.sh status`
- [ ] Switch providers: `./toggle-claude-provider.sh zai`
- [ ] Verify API calls work with new keys
- [ ] Run tests: `pytest agents/tests/`
- [ ] Check no secrets in `git diff`

### Final Security Scan

```bash
# Scan for remaining secrets
grep -rn "AIza" . --include="*.py" --include="*.sh" --include="*.json"
grep -rn "api_key.*=" . --include="*.py" --include="*.sh" --include="*.json"
grep -rn "192.168" . --include="*.py" --include="*.yaml" --include="*.md"

# Should return minimal results (only documentation examples)
```

- [ ] No hardcoded Google API keys found
- [ ] No hardcoded Z.ai API keys found
- [ ] IP addresses replaced with env vars or documented as examples
- [ ] File paths use `~` or environment variables

---

## 📊 Progress Tracking

**Started**: ___________
**Completed**: ___________
**Total Time**: ___________

### Section Completion

- [ ] Critical Actions (30 min)
- [ ] High Priority Fixes (1 hour)
- [ ] Medium Priority Cleanup (1 hour)
- [ ] Low Priority Prevention (1-2 hours)
- [ ] Verification (30 min)

**Overall Progress**: _____ / 5 sections complete

---

## 🆘 Troubleshooting

### Issue: Script can't find environment variables

**Solution**:
```bash
# Add to ~/.bashrc or ~/.zshrc
export GEMINI_API_KEY="your_key"
export ZAI_API_KEY="your_key"

# Then reload
source ~/.bashrc
```

### Issue: Git pre-commit hook fails on valid code

**Solution**:
```bash
# Temporarily bypass hook (use sparingly!)
git commit --no-verify -m "your message"
```

### Issue: Provider toggle script fails after changes

**Solution**:
```bash
# Verify environment variables are set
echo $GEMINI_API_KEY
echo $ZAI_API_KEY

# Check script has correct variable substitution
grep "GEMINI_API_KEY" toggle-claude-provider.sh
```

---

## 📞 Need Help?

- Review: `SECURITY_SCAN_REPORT.md` for detailed findings
- Check: `.env.template` for required variables
- Test: Run `./toggle-claude-provider.sh status` to verify setup

---

**Report Version**: 1.0
**Last Updated**: 2025-10-16
