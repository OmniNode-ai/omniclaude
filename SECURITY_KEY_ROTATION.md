# Security: API Key Rotation Guide

## ⚠️ URGENT: Exposed API Keys Requiring Immediate Rotation

The following API keys have been exposed in version control and **MUST** be rotated immediately:

### Exposed Keys (ROTATE NOW)

| Provider | Key Type | Exposed Value | Location |
|----------|----------|---------------|----------|
| Google Gemini | `GEMINI_API_KEY` / `GOOGLE_API_KEY` | `***GEMINI_KEY_REMOVED***` | `toggle-claude-provider.sh` |
| Z.ai | `ZAI_API_KEY` | `***ZAI_KEY_REMOVED***` | `toggle-claude-provider.sh` |

**Impact**: These keys provide full API access and should be considered compromised.

---

## Step-by-Step Rotation Procedures

### 1. Google Gemini API Key Rotation

#### A. Delete/Restrict Exposed Key

1. **Access Google Cloud Console**
   - Navigate to: https://console.cloud.google.com/apis/credentials
   - Sign in with your Google account

2. **Locate and Disable the Exposed Key**
   - Find API key ending in `...vrz8LzU`
   - Click on the key name to open details
   - Click **"Delete"** or **"Restrict"** button
   - If restricting, set to "None" for Application restrictions temporarily

3. **Confirm Deletion/Restriction**
   - The key should be immediately invalidated
   - This will break any active services using this key

#### B. Generate New Google Gemini API Key

1. **Create New API Key**
   - Click **"Create Credentials"** → **"API Key"**
   - Copy the new API key immediately (shown only once)
   - Example format: `AIzaSy...` (96 characters)

2. **Restrict the New Key (IMPORTANT)**
   - Click on the newly created key
   - Under **"API restrictions"**:
     - Select **"Restrict key"**
     - Enable only: **"Generative Language API"**
   - Under **"Application restrictions"**:
     - Select **"IP addresses"** (if applicable)
     - Add your development/production IPs
   - Click **"Save"**

3. **Set Key Name for Easy Management**
   - Rename key to: `omniclaude-gemini-{date}`
   - Example: `omniclaude-gemini-2025-10`

#### C. Test New Gemini Key

```bash
# Test the new key with a simple API call
curl -X POST "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=YOUR_NEW_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{
      "parts": [{
        "text": "Test connection"
      }]
    }]
  }'

# Expected: JSON response with model output
# Error response means key is invalid or not activated
```

---

### 2. Z.ai API Key Rotation

#### A. Delete/Revoke Exposed Key

1. **Access Z.ai Dashboard**
   - Navigate to: https://z.ai/dashboard (or appropriate Z.ai portal)
   - Sign in with your Z.ai account credentials

2. **Navigate to API Keys Section**
   - Click on **"API Keys"** or **"Settings"** → **"API Keys"**
   - Locate key starting with `0160cf7a...`

3. **Revoke the Exposed Key**
   - Click **"Revoke"** or **"Delete"** button
   - Confirm revocation
   - The key should be immediately invalidated

#### B. Generate New Z.ai API Key

1. **Create New API Key**
   - Click **"Generate New Key"** or **"Create API Key"**
   - Add description: `OmniClaude GLM Models - {date}`
   - Copy the new API key immediately

2. **Configure Key Permissions (if available)**
   - Set to minimum required permissions
   - Enable only GLM model access
   - Set rate limits if available

#### C. Test New Z.ai Key

```bash
# Test the new key with Z.ai API
curl -X POST "https://api.z.ai/api/anthropic/v1/messages" \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_NEW_ZAI_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "glm-4.5-air",
    "max_tokens": 100,
    "messages": [{
      "role": "user",
      "content": "Test connection"
    }]
  }'

# Expected: JSON response with GLM model output
# Error response means key is invalid or not activated
```

---

## Where to Update Keys After Rotation

### Required Updates

After rotating keys, you **MUST** update them in the following locations:

#### 1. Environment Variables (Recommended Approach)

**Create `.env` file in project root:**

```bash
# Copy the example file
cp .env.example .env

# Edit with your new keys
nano .env  # or your preferred editor
```

**Update `.env` with new keys:**

```bash
# Google Gemini API Key (for Quorum Validation)
GEMINI_API_KEY=your_new_gemini_api_key_here
GOOGLE_API_KEY=your_new_gemini_api_key_here  # Same as GEMINI_API_KEY

# Z.ai API Key (for GLM Models)
ZAI_API_KEY=your_new_zai_api_key_here
```

**Load environment variables:**

```bash
# Option A: Source the .env file
source .env

# Option B: Use direnv (auto-loads .env)
direnv allow

# Option C: Export manually
export GEMINI_API_KEY="your_new_key"
export GOOGLE_API_KEY="your_new_key"
export ZAI_API_KEY="your_new_key"
```

#### 2. Update `toggle-claude-provider.sh` Script

**CRITICAL**: The script currently has hardcoded keys. After adding environment variable support:

**Option A: Modify script to read from environment** (Recommended)

Update lines in `toggle-claude-provider.sh`:

```bash
# OLD (line 11):
ZAI_API_KEY="***ZAI_KEY_REMOVED***"

# NEW (line 11):
ZAI_API_KEY="${ZAI_API_KEY:-}"  # Read from environment
if [ -z "$ZAI_API_KEY" ]; then
    echo -e "${RED}Error: ZAI_API_KEY not set${NC}"
    echo "Set it with: export ZAI_API_KEY='your-key-here'"
    exit 1
fi
```

```bash
# OLD (lines 230, 260, 290):
--arg api_key "***GEMINI_KEY_REMOVED***" \

# NEW (lines 230, 260, 290):
--arg api_key "${GEMINI_API_KEY:-}" \
```

**Option B: Use a separate config file** (Alternative)

Create `claude-keys.env` (add to .gitignore):

```bash
# claude-keys.env
export ZAI_API_KEY="your_new_zai_key"
export GEMINI_API_KEY="your_new_gemini_key"
```

Source it before running:
```bash
source claude-keys.env
./toggle-claude-provider.sh gemini-flash
```

#### 3. CI/CD and Production Environments

**For GitHub Actions:**

1. Go to repository **Settings** → **Secrets and variables** → **Actions**
2. Add repository secrets:
   - `GEMINI_API_KEY`
   - `ZAI_API_KEY`
3. Reference in workflow files:

```yaml
env:
  GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
  ZAI_API_KEY: ${{ secrets.ZAI_API_KEY }}
```

**For Docker Deployments:**

```bash
# Use --env-file flag
docker run --env-file .env omniclaude

# Or pass individually
docker run \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  -e ZAI_API_KEY="$ZAI_API_KEY" \
  omniclaude
```

---

## Environment Variable Setup Instructions

### Quick Setup (First Time)

```bash
# 1. Navigate to project directory
cd /path/to/omniclaude

# 2. Copy example environment file
cp .env.example .env

# 3. Edit with your actual keys
nano .env  # Replace placeholder values

# 4. Verify file is not committed
git status  # Should NOT show .env file

# 5. Load environment variables
source .env

# 6. Test configuration
./toggle-claude-provider.sh status
```

### Persistent Environment Variables

**Option A: Shell Profile (Permanent)**

Add to `~/.zshrc` or `~/.bashrc`:

```bash
# OmniClaude API Keys
export GEMINI_API_KEY="your_new_gemini_key"
export GOOGLE_API_KEY="your_new_gemini_key"
export ZAI_API_KEY="your_new_zai_key"
```

Reload shell:
```bash
source ~/.zshrc  # or ~/.bashrc
```

**Option B: direnv (Per-Project)**

Install direnv:
```bash
brew install direnv  # macOS
# or
sudo apt install direnv  # Linux
```

Setup:
```bash
# Add to ~/.zshrc
eval "$(direnv hook zsh)"

# Create .envrc in project root
cd /path/to/omniclaude
echo 'dotenv' > .envrc

# Allow direnv to load .env
direnv allow
```

---

## Using .env.example Files

### Purpose

- **Template**: Provides structure for required environment variables
- **Documentation**: Comments explain each variable's purpose
- **Version Control Safe**: Contains no actual secrets
- **Team Coordination**: Shows teammates what variables they need

### Workflow

1. **Developer clones repository**
2. **Copies `.env.example` to `.env`**
3. **Fills in their own API keys**
4. **Never commits `.env` file** (blocked by .gitignore)

### Example Files

**Root `.env.example`:**
```bash
# Google Gemini API Key
# Get from: https://console.cloud.google.com/apis/credentials
GEMINI_API_KEY=your_gemini_api_key_here
GOOGLE_API_KEY=your_gemini_api_key_here

# Z.ai API Key
# Get from: https://z.ai/dashboard
ZAI_API_KEY=your_zai_api_key_here
```

**`agents/parallel_execution/.env.example`:**
```bash
# Gemini API Key for Quorum Validation
# Used by: quorum_validator.py, demo_quorum_integration.py
# Get from: https://console.cloud.google.com/apis/credentials
GEMINI_API_KEY=your_gemini_api_key_here

# Google API Key for Pydantic AI (same as GEMINI_API_KEY)
# Used by: Pydantic AI integrations
GOOGLE_API_KEY=your_google_api_key_here

# Z.ai API Key for GLM Models
# Used by: quorum_validator.py for multi-model consensus
# Get from: https://z.ai/dashboard
ZAI_API_KEY=your_zai_api_key_here
```

---

## Security Best Practices

### 1. Never Commit Secrets

**Verify before committing:**

```bash
# Check what will be committed
git status
git diff --cached

# If .env is staged, remove it
git reset .env

# Verify .gitignore is working
git check-ignore .env  # Should output: .env
```

### 2. Rotate Keys Regularly

- **Development keys**: Rotate every 90 days
- **Production keys**: Rotate every 30-60 days
- **Compromised keys**: Rotate immediately

### 3. Restrict Key Permissions

- Enable only required APIs
- Set IP restrictions when possible
- Use separate keys for dev/staging/production
- Set usage quotas to limit damage from leaks

### 4. Monitor Key Usage

**Google Cloud Console:**
- View API usage at: https://console.cloud.google.com/apis/dashboard
- Set up billing alerts
- Monitor for unusual activity

**Z.ai Dashboard:**
- Check usage statistics regularly
- Set up alerts for rate limit breaches
- Review access logs

### 5. Use Secret Management Tools

For production deployments:

- **HashiCorp Vault**: Enterprise secret management
- **AWS Secrets Manager**: Cloud-based secrets
- **1Password CLI**: Team password management
- **Doppler**: Environment variable management

### 6. Audit Access Regularly

```bash
# Find all files mentioning API keys
grep -r "GEMINI_API_KEY\|ZAI_API_KEY" . \
  --exclude-dir=.git \
  --exclude-dir=node_modules \
  --exclude="*.md"

# Review which scripts load environment variables
grep -r "getenv\|os.environ" agents/ --include="*.py"
```

---

## Verification Checklist

After rotating keys, verify:

- [ ] Old keys deleted/revoked in provider dashboards
- [ ] New keys generated and copied securely
- [ ] `.env` file created and populated with new keys
- [ ] `.env` file NOT committed to git (`git status` check)
- [ ] Environment variables loaded (`echo $GEMINI_API_KEY`)
- [ ] `toggle-claude-provider.sh` updated to read from environment
- [ ] Provider toggle script tested (`./toggle-claude-provider.sh status`)
- [ ] API connections tested with new keys
- [ ] CI/CD secrets updated (if applicable)
- [ ] Team members notified of key rotation
- [ ] Key usage monitoring enabled
- [ ] Documentation updated with rotation date

---

## Troubleshooting

### Problem: "API Key Invalid" Error

**Solution:**
1. Verify key was copied correctly (no extra spaces)
2. Check if key is activated (may take a few minutes)
3. Verify API restrictions allow your IP address
4. Test key with curl command (see testing sections above)

### Problem: Environment Variables Not Loading

**Solution:**
```bash
# Check if .env exists
ls -la .env

# Manually source
source .env

# Verify variables are set
env | grep -E "GEMINI|ZAI"

# Check for syntax errors in .env
cat .env  # Look for quotes, spaces, special characters
```

### Problem: Script Still Using Old Keys

**Solution:**
1. Verify script was updated to read from environment
2. Restart terminal/shell session
3. Check for hardcoded values: `grep -n "AIzaSy\|0160cf7a" toggle-claude-provider.sh`
4. Clear any cached environment: `unset GEMINI_API_KEY ZAI_API_KEY`
5. Re-source: `source .env`

### Problem: git showing .env file

**Solution:**
```bash
# Verify .gitignore has .env
cat .gitignore | grep "^\.env$"

# If missing, add it
echo ".env" >> .gitignore

# If already committed, remove from git but keep locally
git rm --cached .env
git commit -m "Remove .env from version control"

# Verify
git status  # Should not show .env
```

---

## Emergency Response Plan

If API keys are leaked publicly (GitHub, logs, etc.):

### Immediate Actions (Within 5 minutes)

1. **Revoke keys immediately** in provider dashboards
2. **Generate new keys** following procedures above
3. **Update all environments** with new keys
4. **Notify team members** of the breach

### Short-term Actions (Within 1 hour)

5. **Review access logs** for unauthorized usage
6. **Assess impact**: Check for unusual API calls
7. **Update CI/CD secrets** in all pipelines
8. **Test all services** with new keys

### Long-term Actions (Within 24 hours)

9. **Conduct post-mortem**: How did the leak occur?
10. **Implement preventive measures**: Pre-commit hooks, secret scanning
11. **Update security procedures**: Document lessons learned
12. **Review billing**: Check for unexpected charges

### Prevention Tools

Install git pre-commit hooks to catch secrets:

```bash
# Install gitleaks
brew install gitleaks  # macOS
# or
curl -sSfL https://raw.githubusercontent.com/gitleaks/gitleaks/master/scripts/install.sh | sh -s -- -b /usr/local/bin

# Add to .git/hooks/pre-commit
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/sh
gitleaks protect --staged --verbose
EOF

chmod +x .git/hooks/pre-commit
```

---

## Additional Resources

### Provider Documentation

- **Google Cloud API Keys**: https://cloud.google.com/docs/authentication/api-keys
- **Google Gemini API**: https://ai.google.dev/docs
- **Z.ai Documentation**: https://z.ai/docs (check for official docs)

### Security Tools

- **git-secrets**: https://github.com/awslabs/git-secrets
- **gitleaks**: https://github.com/gitleaks/gitleaks
- **truffleHog**: https://github.com/trufflesecurity/truffleHog

### Support Contacts

- **Google Cloud Support**: https://cloud.google.com/support
- **Z.ai Support**: Check Z.ai dashboard for support options

---

## Document History

- **2025-10-16**: Initial security documentation created
- **Action Required**: Rotate exposed keys immediately
- **Next Review**: After key rotation completion

**Status**: 🔴 URGENT - Keys exposed, immediate rotation required
