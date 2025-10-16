# Security Scan Report

**Generated**: 2025-10-16
**Scan Type**: Comprehensive Secrets and Sensitive Data Scan
**Severity Levels**: HIGH (immediate action) | MEDIUM (review required) | LOW (informational)

---

## Executive Summary

**Total Findings**: 14 unique security issues
**Critical (HIGH)**: 3
**Medium**: 6
**Low/Informational**: 5

**Immediate Actions Required**:
1. Rotate Google Gemini API keys (exposed in 7 files)
2. Rotate Z.ai API key (exposed in 1 file)
3. Remove or redact absolute file paths containing usernames

---

## HIGH Severity Findings

### 1. Google Gemini API Key Exposed (CRITICAL)

**API Key**: `***GEMINI_KEY_REMOVED***`

**Locations** (7 files):
1. `./toggle-claude-provider.sh:230` - Hardcoded in function `switch_to_gemini_pro()`
2. `./toggle-claude-provider.sh:260` - Hardcoded in function `switch_to_gemini_flash()`
3. `./toggle-claude-provider.sh:290` - Hardcoded in function `switch_to_gemini_25_flash()`
4. `./claude-providers.json:99` - Provider configuration for "gemini-pro"
5. `./claude-providers.json:121` - Provider configuration for "gemini-flash"
6. `./claude-providers.json:143` - Provider configuration for "gemini-2.5-flash"
7. `./agents/parallel_execution/HANDOFF.md:71` - Documentation example

**Impact**: Complete compromise of Google Gemini API access, potential unauthorized usage and billing charges.

**Recommendation**:
1. **IMMEDIATELY** revoke this API key in Google Cloud Console
2. Generate a new API key
3. Store in environment variable: `export GEMINI_API_KEY="your_new_key_here"`
4. Update all references to use `${GEMINI_API_KEY}` environment variable
5. Add `.env` files to `.gitignore` if not already present

**Fix**:
```bash
# Replace hardcoded key with environment variable reference
sed -i '' 's/***GEMINI_KEY_REMOVED***/${GEMINI_API_KEY}/g' toggle-claude-provider.sh
sed -i '' 's/"api_key": "***GEMINI_KEY_REMOVED***"/"api_key": "${GEMINI_API_KEY}"/g' claude-providers.json
sed -i '' 's/***GEMINI_KEY_REMOVED***/your_gemini_api_key_here/g' agents/parallel_execution/HANDOFF.md
```

---

### 2. Z.ai API Key Exposed (CRITICAL)

**API Key**: `***ZAI_KEY_REMOVED***`

**Location**: `./claude-providers.json:30`

**Impact**: Unauthorized access to Z.ai GLM models, potential billing fraud.

**Recommendation**:
1. **IMMEDIATELY** revoke this API key through Z.ai dashboard
2. Generate a new API key
3. Store in environment variable: `export ZAI_API_KEY="your_new_key_here"`
4. Update reference to use `${ZAI_API_KEY}` environment variable

**Fix**:
```bash
sed -i '' 's/"api_key": "***ZAI_KEY_REMOVED***"/"api_key": "${ZAI_API_KEY}"/g' claude-providers.json
```

---

### 3. Personal Email Address in Git History

**Email**: `jonah.gabriel@gmail.com`

**Locations**: Multiple trace files in `./traces/` directory
- `./traces/coord_1759771770525_4407106320.json` (author_email in commit metadata)

**Impact**: MEDIUM-HIGH - Personal email exposure in version control

**Recommendation**:
1. This is in trace/log files - consider if these should be committed to version control
2. Add `traces/` directory to `.gitignore` if logs shouldn't be tracked
3. Use a generic email for public commits (e.g., `github-noreply` email)

**Note**: Email in git commit history cannot be removed without rewriting history. For public repos, consider this permanent.

---

## MEDIUM Severity Findings

### 4. Private IP Addresses Exposed

**Internal Network IPs Found**:
- `192.168.86.200` - Multiple files (Ollama server)
- `192.168.86.201` - Multiple files (vLLM/RTX 5090 server)
- `192.168.86.101` - Multiple files (Mac Mini server)
- `192.168.86.230`, `192.168.86.240`, `192.168.86.250` - Model endpoints
- `10.0.1.100` - Documentation examples

**Key Files**:
1. `./QUORUM_VALIDATION_QUICKSTART.md` - Contains 5 internal IPs
2. `./claude_hooks/config.yaml` - Lines 107, 115, 123, 148-149
3. `./agents/parallel_execution/VALIDATION_CONFIG_DESIGN.md` - Multiple occurrences
4. `./claude_hooks/lib/ai_agent_selector.py:210, 233, 241` - Hardcoded endpoints

**Impact**: Network topology disclosure, potential targeting for attacks.

**Recommendation**:
1. Replace hardcoded IPs with configuration variables
2. Use hostnames or environment variables instead
3. For documentation, use example IPs like `10.0.0.1` or `192.168.1.100`

**Example Fix**:
```python
# Before
endpoint = "http://192.168.86.200:11434"

# After
endpoint = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
```

---

### 5. Absolute File Paths Containing Username "jonah"

**Sensitive Paths Found** (11 occurrences):
- `/Users/jonah/.claude/agents/configs`
- `/Users/jonah/.claude/hooks`
- `/Users/jonah/.claude/agent-definitions/`

**Key Files**:
1. `./traces/coord_1760122469303_4678411984.json` - Lines 163, 955
2. `./agents/lib/enhanced_router.py` - Lines 70, 284 (hardcoded default paths)
3. `./agents/detect_archon_integration.py:161` - Hardcoded path
4. `./claude_hooks/debug_utils.py:289, 429` - Hardcoded paths

**Impact**: Username disclosure, path traversal information.

**Recommendation**:
1. Use `os.path.expanduser("~/.claude/...")` instead of hardcoded paths
2. Use environment variables for configurable paths
3. Remove trace files from version control

**Example Fix**:
```python
# Before
registry_path = "/Users/jonah/.claude/agent-definitions/agent-registry.yaml"

# After
registry_path = os.path.expanduser("~/.claude/agent-definitions/agent-registry.yaml")
# Or
registry_path = os.getenv("CLAUDE_AGENT_REGISTRY", os.path.expanduser("~/.claude/agent-definitions/agent-registry.yaml"))
```

---

### 6. Database Connection Strings in Trace Files (Examples)

**Pattern Found**: `postgresql://test_user:test_password@localhost:5432/test_db`

**Locations**:
- `./traces/coord_1759771770525_4407106320.json`
- `./agents/parallel_execution/traces/coord_1759864928460_4945856848.json`

**Impact**: LOW-MEDIUM - These appear to be example/placeholder credentials, but could be misleading

**Recommendation**:
1. Verify these are not production credentials
2. Change examples to obviously fake values like `example_user:example_pass`
3. Add `.gitignore` entry for `traces/` directory

**Status**: FALSE POSITIVE if truly examples, but should be sanitized

---

### 7. Password Handling in User Registration Code

**File**: `./user_registration.py`

**Findings**:
- Line 70-105: Password validation logic
- Line 141-148: Password hashing function
- Line 278: Example password `SecureP@ssw0rd123!`

**Impact**: LOW - This is legitimate security code for password handling

**Recommendation**:
- Code is SECURE (uses Argon2id hashing)
- Example password on line 278 is acceptable for demonstration
- No action required

**Status**: FALSE POSITIVE - Legitimate security implementation

---

### 8. JWT Secret Pattern in Code Examples

**Pattern Found**: `process.env.JWT_SECRET`

**Locations**:
- `./claude_hooks/lib/pattern_tracker.py:870, 889`

**Impact**: LOW - This is example/template code, not actual secrets

**Recommendation**:
- These are code pattern examples for detection, not actual secrets
- No action required

**Status**: FALSE POSITIVE - Pattern detection examples

---

### 9. API Key Pattern Detection Examples

**File**: `./agents/lib/model_generator.py:553`

**Pattern**: `r'\b(api_key|token|secret)\b'`

**Impact**: NONE - This is a regex pattern for detection, not an actual secret

**Recommendation**: No action required

**Status**: FALSE POSITIVE - Detection pattern, not secret

---

## LOW Severity / Informational Findings

### 10. External Repository Path References

**Pattern**: `/Volumes/PRO-G40/Code/Archon/python`

**Location**: `./traces/coord_1759771770525_4407106320.json:1122`

**Impact**: LOW - Exposes local development environment structure

**Recommendation**:
- Remove trace files from version control
- Add `traces/` to `.gitignore`

---

### 11. Email Addresses in Generated Code Examples

**Locations**: Multiple trace files contain example emails like:
- `"user_email"` field names
- `"name@example.com"` style examples in generated code

**Impact**: NONE - These are field names and examples, not real addresses

**Status**: FALSE POSITIVE - Template/example code

---

### 12. Coverage Report Metadata

**File**: `./htmlcov/status.json`

**Finding**: Contains file hashes and coverage metadata

**Impact**: NONE - Build artifacts, no sensitive data

**Recommendation**: Add `htmlcov/` to `.gitignore`

---

### 13. Commit SHA in Logs

**Pattern**: Commit SHAs like `7e386fe348b991f063c646e307b27c69218f8d87`

**Locations**: `./claude_hooks/logs/violations_summary.json:4`

**Impact**: NONE - Public information

**Status**: Informational only

---

### 14. Environment Variable Template in .env.example

**File**: `./agents/parallel_execution/.env.example`

**Contains**:
```
GEMINI_API_KEY=your_gemini_api_key_here
GOOGLE_API_KEY=your_google_api_key_here
ZAI_API_KEY=your_zai_api_key_here
```

**Impact**: NONE - This is a template file with placeholder values

**Status**: SAFE - Proper use of example file

---

## Summary of Actions Required

### Immediate (Within 24 hours)

1. ✅ **COMPLETED**: Rotate Google Gemini API key (exposed key revoked)
2. ✅ **COMPLETED**: Rotate Z.ai API key (exposed key revoked)
3. ⚠️ **PENDING**: Update all references to use environment variables
4. ⚠️ **PENDING**: Add security scanning to pre-commit hooks

### Short-term (Within 1 week)

1. Replace hardcoded IP addresses with environment variables
2. Fix absolute file paths to use `os.path.expanduser()`
3. Add `traces/` directory to `.gitignore`
4. Add `htmlcov/` directory to `.gitignore`
5. Review and remove any unnecessary trace files from git history

### Long-term (Within 1 month)

1. Implement automated secret scanning (e.g., `truffleHog`, `git-secrets`)
2. Add pre-commit hooks to prevent secret commits
3. Document security best practices for contributors
4. Conduct regular security audits

---

## Tools Used

- `grep` with regex patterns for API keys, tokens, passwords
- `grep` for email addresses and IP addresses
- `find` for private key files (none found)
- `grep` for database connection strings
- `grep` for absolute file paths with usernames

---

## False Positives

The following findings were investigated and determined to be safe:

1. **Password validation code** in `user_registration.py` - Legitimate security implementation
2. **JWT_SECRET patterns** in `pattern_tracker.py` - Example code for pattern detection
3. **API key detection regex** in `model_generator.py` - Detection pattern, not actual secret
4. **Database connection strings** in trace files - Example/placeholder credentials
5. **Email addresses** in generated code - Template field names and examples
6. **`.env.example` file** - Proper use of template with placeholders

---

## Recommendations for Prevention

### 1. Pre-commit Hook Configuration

Add to `.git/hooks/pre-commit`:

```bash
#!/bin/bash
# Check for potential secrets before commit

# Check for AWS keys
if git diff --cached | grep -E "AKIA[0-9A-Z]{16}"; then
    echo "❌ Error: Possible AWS access key detected"
    exit 1
fi

# Check for private keys
if git diff --cached | grep -E "BEGIN.*PRIVATE KEY"; then
    echo "❌ Error: Private key detected"
    exit 1
fi

# Check for high entropy strings (potential secrets)
if git diff --cached | grep -E "['\"][A-Za-z0-9+/]{32,}['\"]"; then
    echo "⚠️  Warning: High entropy string detected (possible secret)"
    echo "Review changes carefully before committing"
fi
```

### 2. .gitignore Additions

Add to `.gitignore`:

```
# Secrets and environment
.env
.env.local
*.env

# Build artifacts
htmlcov/
.coverage
*.pyc

# Logs and traces
traces/
*.log

# IDE
.vscode/
.idea/

# OS
.DS_Store
```

### 3. Environment Variable Template

Create `.env.template`:

```bash
# API Keys (replace with your actual keys)
GEMINI_API_KEY=your_gemini_api_key_here
ZAI_API_KEY=your_zai_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Ollama Endpoints (replace with your server IPs)
OLLAMA_ENDPOINT=http://localhost:11434
VLLM_ENDPOINT=http://localhost:8001
MAC_MINI_ENDPOINT=http://localhost:11434

# Paths (defaults to ~/.claude/...)
CLAUDE_AGENT_REGISTRY=~/.claude/agent-definitions/agent-registry.yaml
CLAUDE_HOOKS_PATH=~/.claude/hooks
```

---

## Compliance Notes

- **GDPR**: Personal email addresses found in trace files (review retention policy)
- **PCI-DSS**: No payment card data found ✅
- **SOC 2**: API key exposure violates access control requirements
- **OWASP Top 10**: A02:2021 – Cryptographic Failures (exposed secrets)

---

## Scan Metadata

**Scan Date**: 2025-10-16
**Scanned Files**: ~500 files
**File Types**: `.py`, `.js`, `.ts`, `.json`, `.yaml`, `.yml`, `.md`, `.sh`, `.env*`, `.toml`
**Scan Duration**: ~2 minutes
**Scanner**: Manual grep-based analysis
**False Positive Rate**: ~40% (6 of 14 findings)

---

## Contact

For questions about this security scan, contact the security team or create an issue in the repository.

**Report Version**: 1.0
**Last Updated**: 2025-10-16
