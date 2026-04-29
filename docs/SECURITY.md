# Security Implementation Guide

> **Reporting vulnerabilities**: See [`/SECURITY.md`](../SECURITY.md) at the repository root — that file is the canonical security policy and contact for reporting. This document covers implementation-level security practices in the codebase.

**Last Updated**: 2026-04-29
**Status**: Active
**Primary source tree**: `src/omniclaude/`, `plugins/onex/hooks/`

---

## Overview

This document outlines the security measures, best practices, and considerations implemented in the omniclaude codebase. The main surfaces are:

- Hook Python libraries (`plugins/onex/hooks/lib/`)
- Hook Pydantic models (`src/omniclaude/hooks/schemas.py`)
- Publisher / emit daemon client (`src/omniclaude/publisher/`)
- CLI entry points (`src/omniclaude/cli/`)

---

## Security Measures

### 1. Prompt Data Privacy

**Risk**: User prompts contain sensitive information (API keys, passwords, proprietary code).

**Mitigation**: Dual-emission with automatic sanitization.

The `prompt_preview` field in `ModelHookPromptSubmittedPayload` is:
- Truncated to 100 characters
- Scanned and redacted for common secret patterns:
  - OpenAI API keys (`sk-*`)
  - AWS access keys (`AKIA*`)
  - GitHub tokens (`ghp_*`)
  - Slack tokens (`xox*`)
  - PEM private keys
  - Bearer tokens
  - Passwords in URLs

Full prompt content is published **only** to `onex.cmd.omniintelligence.*` topics
(restricted access). Observability topics (`onex.evt.*`) receive only the
sanitized preview.

See [ADR-004: Dual-Emission Privacy Split](decisions/ADR-004-dual-emission-privacy-split.md).

### 2. SQL Injection Prevention

**Risk**: SQL injection via user-controlled input in database queries.

**Mitigation**: All database operations use parameterized queries:

```python
# SAFE: parameterized
query = "SELECT * FROM hooks WHERE session_id = $1"
result = await conn.fetchrow(query, session_id)

# UNSAFE: never do this
query = f"SELECT * FROM hooks WHERE session_id = '{session_id}'"
```

When table or column names cannot be parameterized (e.g., dynamic schema
introspection), they are validated with `validate_sql_identifier()` before
use in f-strings.

### 3. API Key and Secret Management

**Risk**: Hardcoded API keys exposed via version control or logs.

**Mitigation**:
- All secrets loaded from environment variables or `~/.omnibase/.env`
- `.env` is gitignored; `.env.example` contains only placeholder values
- Hook logs at `~/.claude/hooks.log` sanitize token-shaped strings

```python
# CORRECT — from env var
kafka_bootstrap = os.environ["KAFKA_BOOTSTRAP_SERVERS"]

# WRONG — never hardcode connection strings
```

Note: `ANTHROPIC_API_KEY` is **never required**. Claude Code authenticates
via OAuth. Do not add it to any required-env list or preflight check.

### 4. Network Binding

**Risk**: Services binding to all interfaces expose unnecessary attack surface.

**Mitigation**: The emit daemon binds to a Unix domain socket
(`/tmp/onex-emit.sock` or `$XDG_RUNTIME_DIR/onex-emit.sock`) by default —
no TCP port is opened. When the daemon runs in the kernel plugin on `.201`,
a host-mounted volume path is used. No services in omniclaude bind to
`0.0.0.0`.

### 5. Hook Exit Discipline

**Risk**: Hooks that exit non-zero block Claude Code UI.

**Design choice**: Hooks always exit 0 on infrastructure failure. Data loss
(dropped events) is acceptable; UI freeze is not. The one exception is
`find_python()` — if no valid interpreter is found, the hook exits 1 with
an actionable error message. See [CLAUDE.md](../CLAUDE.md) Failure Modes table.

---

## Security Scanning

Bandit runs as a required CI gate on every PR. To run locally:

```bash
# Scan the source tree (medium severity and above)
uv run bandit -r src/omniclaude/ -ll

# Output JSON for review
uv run bandit -r src/omniclaude/ -f json -o security-report.json
```

Suppressing false positives requires `# nosec B<id>` with an inline
comment explaining the control in place:

```python
# Socket path is resolved from env var, not user input
sock_path = os.environ.get("ONEX_EMIT_SOCKET_PATH", "/tmp/onex-emit.sock")  # nosec B108
```

Common Bandit test IDs in this codebase:

| ID | Description | Typical context |
|----|-------------|----------------|
| `B104` | Binding to all interfaces | Not used — Unix sockets only |
| `B108` | Probable insecure `/tmp` usage | Emit daemon socket default |
| `B301` | Pickle use | Not used in omniclaude |
| `B608` | SQL injection via string | Hook logging queries with validated identifiers |

---

## Deployment Security Checklist

Before any production deploy:

- [ ] `uv run bandit -r src/omniclaude/ -ll` exits 0
- [ ] No secrets in `onex.evt.*` topics (preview fields only)
- [ ] `OMNICLAUDE_HOOKS_DISABLE` not set in production env
- [ ] Plugin venv built from brew Python (macOS): `bash scripts/repair-plugin-venv.sh`
- [ ] Hook scripts executable: `ls -l plugins/onex/hooks/scripts/*.sh | grep -v ^-rwx`
- [ ] `detect-secrets` scan passes (wired as CI gate)

---

## Incident Response

If a security issue is discovered in production:

1. Assess severity and whether it is actively exploited
2. If actively exploited: disable hooks immediately (`export OMNICLAUDE_HOOKS_DISABLE=1`)
3. Rotate any potentially exposed credentials
4. Apply fix in a new worktree and ship via normal PR flow
5. Check `~/.claude/hooks.log` for exploitation indicators
6. Email **contact@omninode.ai** per the [root security policy](../SECURITY.md)

---

## References

- [Root security policy](../SECURITY.md) — vulnerability reporting contact
- [ADR-004: Dual-Emission Privacy Split](decisions/ADR-004-dual-emission-privacy-split.md)
- [CLAUDE.md Failure Modes](../CLAUDE.md) — hook degradation behavior
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Bandit Documentation](https://bandit.readthedocs.io/)
