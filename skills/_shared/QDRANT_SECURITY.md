# Qdrant Helper - SSRF Security Improvements

## Overview

Added comprehensive SSRF (Server-Side Request Forgery) protection to `qdrant_helper.py` to prevent malicious URLs from being used to access internal services if environment variables are compromised.

## Security Enhancements

### 1. URL Validation (`validate_qdrant_url()`)

**Purpose**: Validate all Qdrant URLs before use to prevent SSRF attacks.

**Security Checks**:
- ✅ **HTTPS enforcement** in production environments
- ✅ **Hostname whitelist** validation
- ✅ **Dangerous port blocking** (SSH, databases, etc.)
- ✅ **Port range validation** (1-65535)
- ✅ **Custom allowed hosts** support

### 2. HTTPS Enforcement

**Development**:
- HTTP allowed for localhost testing
- No certificate validation required

**Production** (ENVIRONMENT=production):
- HTTPS required for all Qdrant connections
- HTTP connections rejected with clear error message
- Ensures encrypted communication in production

**Example**:
```bash
# Production .env
ENVIRONMENT=production
QDRANT_URL=https://qdrant.internal:6333
```

### 3. Hostname Whitelist

**Default Allowed Hosts**:
- `localhost` - Local development
- `127.0.0.1` - IPv4 loopback
- `::1` - IPv6 loopback
- `qdrant.internal` - Internal DNS name
- `192.168.86.101` - Archon server IP
- `192.168.86.200` - OmniNode bridge IP (fallback)

**Blocked by Default**:
- Cloud metadata endpoints (AWS: 169.254.169.254, GCP: metadata.google.internal)
- External domains not in whitelist
- Internal admin panels
- Private IPs not explicitly whitelisted

**Custom Hosts**:
```bash
# .env file
QDRANT_ALLOWED_HOSTS=custom-qdrant.example.com,10.0.0.50
```

### 4. Dangerous Port Blocking

**Automatically Blocked Ports**:
- `22` - SSH (prevent shell access)
- `23` - Telnet (prevent shell access)
- `25` - SMTP (prevent email relay)
- `3389` - RDP (prevent remote desktop)
- `5432` - PostgreSQL (prevent database access)
- `6379` - Redis (prevent cache access)
- `27017` - MongoDB (prevent database access)
- `3306` - MySQL (prevent database access)
- `1521` - Oracle (prevent database access)
- `9092` - Kafka (prevent message bus access)

**Rationale**: These ports commonly expose sensitive services that should never be accessed via Qdrant client.

### 5. Connection Timeout

**Default**: 5 seconds (via `get_timeout_seconds()`)

**Configuration**:
```bash
# .env file
REQUEST_TIMEOUT_MS=5000  # 5 seconds
```

**Purpose**: Prevents hanging connections on SSRF attempts to unresponsive services.

## Attack Vectors Prevented

### 1. Cloud Metadata Exploitation
```python
# ❌ BLOCKED
validate_qdrant_url("http://169.254.169.254/latest/meta-data/")
# ValueError: Qdrant host not in whitelist: 169.254.169.254
```

### 2. Internal Service Access
```python
# ❌ BLOCKED
validate_qdrant_url("http://internal-admin:80/admin")
# ValueError: Qdrant host not in whitelist: internal-admin
```

### 3. Database Access
```python
# ❌ BLOCKED
validate_qdrant_url("http://localhost:5432")
# ValueError: Dangerous port blocked: 5432
```

### 4. SSH/RDP Access
```python
# ❌ BLOCKED
validate_qdrant_url("http://localhost:22")
# ValueError: Dangerous port blocked: 22
```

### 5. Production HTTP Downgrade
```python
# ❌ BLOCKED (in production)
os.environ["ENVIRONMENT"] = "production"
validate_qdrant_url("http://qdrant.internal:6333")
# ValueError: HTTPS required for production Qdrant
```

## Valid Usage Examples

### Development
```python
# ✅ ALLOWED (development)
os.environ["ENVIRONMENT"] = "development"
validate_qdrant_url("http://localhost:6333")
validate_qdrant_url("http://192.168.86.101:6333")
```

### Production
```python
# ✅ ALLOWED (production)
os.environ["ENVIRONMENT"] = "production"
validate_qdrant_url("https://qdrant.internal:6333")
validate_qdrant_url("https://192.168.86.101:6333")
```

### Custom Hosts
```python
# ✅ ALLOWED (with QDRANT_ALLOWED_HOSTS set)
os.environ["QDRANT_ALLOWED_HOSTS"] = "custom-qdrant.example.com"
validate_qdrant_url("http://custom-qdrant.example.com:6333")
```

## Testing

### Run Security Tests
```bash
python3 /Users/jonah/.claude/skills/_shared/test_qdrant_ssrf_protection.py
```

### Test Coverage
- **28 test cases** covering all security scenarios
- **100% pass rate** required for deployment

**Test Categories**:
1. Valid URLs (5 tests)
2. HTTPS enforcement (3 tests)
3. Malicious URLs / SSRF attacks (11 tests)
4. Port validation (6 tests)
5. Custom allowed hosts (3 tests)

## Configuration

### Environment Variables

```bash
# Required
QDRANT_HOST=localhost           # or 192.168.86.101
QDRANT_PORT=6333

# Optional
ENVIRONMENT=development         # or 'production'
QDRANT_ALLOWED_HOSTS=host1,host2  # comma-separated
REQUEST_TIMEOUT_MS=5000         # connection timeout

# Production (recommended)
ENVIRONMENT=production
QDRANT_URL=https://qdrant.internal:6333
```

### Type-Safe Configuration

Uses Pydantic Settings framework for validated configuration:

```python
from config import settings

# Automatically validated and type-safe
host = settings.qdrant_host        # str
port = settings.qdrant_port        # int
timeout = settings.request_timeout_ms  # int
```

## Migration Guide

### Existing Code

**No changes required** - existing code continues to work:

```python
from qdrant_helper import check_qdrant_connection, list_collections

# Still works - validation happens internally
result = check_qdrant_connection()
collections = list_collections()
```

### URL Construction

**Before** (insecure):
```python
import os
qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
# No validation - could be http://internal-admin:80
```

**After** (secure):
```python
from qdrant_helper import get_qdrant_url

qdrant_url = get_qdrant_url()
# Validated for SSRF protection
# HTTPS enforced in production
# Dangerous ports blocked
```

## Production Deployment Checklist

- [ ] Set `ENVIRONMENT=production` in .env
- [ ] Use HTTPS URL: `QDRANT_URL=https://your-host:6333`
- [ ] Verify Qdrant host is in whitelist (or add to `QDRANT_ALLOWED_HOSTS`)
- [ ] Ensure TLS certificate is valid
- [ ] Run security tests: `python3 test_qdrant_ssrf_protection.py`
- [ ] Verify production connectivity: `python3 qdrant_helper.py`
- [ ] Monitor logs for validation errors

## Error Messages

### HTTPS Required
```
ValueError: HTTPS required for production Qdrant (got: http).
Set QDRANT_URL to use https:// in production environment.
```

**Solution**: Use HTTPS URL in production .env file.

### Host Not in Whitelist
```
ValueError: Qdrant host not in whitelist: evil.com.
Allowed hosts: localhost, 127.0.0.1, ::1, qdrant.internal, 192.168.86.101, 192.168.86.200.
Add to QDRANT_ALLOWED_HOSTS environment variable if needed.
```

**Solution**: Add host to `QDRANT_ALLOWED_HOSTS` or verify you're using the correct URL.

### Dangerous Port Blocked
```
ValueError: Dangerous port blocked: 5432.
This port is commonly used for sensitive services and should not be accessed via Qdrant client.
```

**Solution**: Use Qdrant's default port (6333) or an appropriate non-dangerous port.

## Security Best Practices

1. **Never disable validation** - Always use `get_qdrant_url()` or `validate_qdrant_url()`
2. **Use HTTPS in production** - Set `ENVIRONMENT=production` to enforce
3. **Whitelist sparingly** - Only add trusted hosts to `QDRANT_ALLOWED_HOSTS`
4. **Monitor errors** - Log validation failures for security monitoring
5. **Regular audits** - Review allowed hosts and dangerous ports list periodically
6. **Test thoroughly** - Run `test_qdrant_ssrf_protection.py` before deployment

## References

- **OWASP SSRF**: https://owasp.org/www-community/attacks/Server_Side_Request_Forgery
- **CWE-918**: https://cwe.mitre.org/data/definitions/918.html
- **PR Review**: PR #33 security review findings

## Changelog

### 2025-11-20 - SSRF Protection Implementation
- Added `validate_qdrant_url()` function
- Implemented HTTPS enforcement for production
- Added hostname whitelist validation
- Added dangerous port blocking
- Added port range validation
- Created comprehensive test suite (28 tests)
- Updated `get_qdrant_url()` to use validation
- Added security documentation

## Support

For questions or issues:
1. Review this documentation
2. Run test suite to verify configuration
3. Check error messages for clear guidance
4. Review PR #33 for context and rationale
