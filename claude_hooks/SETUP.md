# Claude Code Hooks - Setup Guide

## Overview

The Claude Code hooks system provides real-time intelligence capture and quality enforcement across your development workflow. This guide covers setting up hooks with version control via symlinks.

## Architecture

**Hook Types:**
- **UserPromptSubmit**: Agent detection, RAG intelligence gathering, context injection
- **PreToolUse**: Quality gates, ONEX compliance checks, security validation
- **PostToolUse**: Auto-fixes, naming conventions, performance tracking

**Database Logging:**
- PostgreSQL `hook_events` table
- Correlation ID tracking across all hooks
- Performance metrics and intelligence data

## Setup Methods

### Recommended: Symlink Setup (Version Control)

This approach keeps all hooks in the git repository and symlinks them to `~/.claude/hooks`.

**Benefits:**
- ✅ All hook changes automatically tracked in git
- ✅ No need to sync between directories
- ✅ Single source of truth in repository
- ✅ Easy rollback via git
- ✅ Team collaboration on hook improvements

**Setup:**

```bash
# 1. Navigate to repository
cd /path/to/omniclaude

# 2. Create .env from template (if not exists)
cp .env.example .env

# 3. Edit .env and add your DB_PASSWORD
nano .env  # or your preferred editor

# 4. Run symlink setup script
./claude_hooks/setup-symlinks.sh

# 5. Source .env to make DB_PASSWORD available
source .env

# 6. Verify setup
ls -la ~/.claude/hooks  # Should show symlink to repository
```

### Alternative: Rsync Sync (Legacy)

If symlinks don't work in your environment, use the sync scripts:

```bash
# Sync FROM repository TO live hooks
./claude_hooks/sync-to-live.sh

# Sync FROM live hooks TO repository (after making changes)
./claude_hooks/sync-from-live.sh
```

## Environment Configuration

### Required Environment Variables

Add these to your `.env` file:

```bash
# Hook Intelligence Database
DB_PASSWORD=omninode-bridge-postgres-dev-2024

# Archon MCP URLs (optional, defaults provided)
ARCHON_MCP_URL=http://localhost:8051
ARCHON_INTELLIGENCE_URL=http://localhost:8053

# AI Agent Selection (optional)
ENABLE_AI_AGENT_SELECTION=true
AI_MODEL_PREFERENCE=5090  # or mac-studio, gemini-flash
AI_AGENT_CONFIDENCE_THRESHOLD=0.8
AI_SELECTION_TIMEOUT_MS=3000
```

### Loading Environment Variables

**Option 1: Manual source (per session)**
```bash
source .env
```

**Option 2: direnv (automatic)**
```bash
# Install direnv (macOS)
brew install direnv

# Add to ~/.zshrc or ~/.bashrc
eval "$(direnv hook zsh)"  # or bash

# Allow .env loading
echo 'source .env' > .envrc
direnv allow
```

**Option 3: Shell profile (global)**
```bash
# Add to ~/.zshrc or ~/.bashrc
source /path/to/omniclaude/.env
```

## Database Setup

The hooks require a PostgreSQL database for event logging:

```bash
# Database should already be running from agents setup
# Verify connection:
PGPASSWORD=omninode-bridge-postgres-dev-2024 psql \
  -h localhost -p 5436 \
  -U postgres -d omninode_bridge \
  -c "SELECT COUNT(*) FROM hook_events;"
```

If the database isn't running, start it:

```bash
cd /path/to/omniclaude/agents
docker-compose up -d postgres
```

## Testing Hook Setup

### 1. Test Database Connection

```bash
cd /path/to/omniclaude/claude_hooks
python3 tools/test_hook_event_logger.py
```

Expected output:
```
Testing hook event logger...
✓ PreToolUse event logged: <uuid>
✓ PostToolUse event logged: <uuid>
✓ UserPromptSubmit event logged: <uuid>
```

### 2. Test Hook Intelligence Dashboard

```bash
cd /path/to/omniclaude/claude_hooks/tools
python3 hook_dashboard.py
```

Should display:
- Hook Performance (24 hours)
- Recent Agent Detections
- Tool Usage by Agent

### 3. Test Hook Integration

```bash
cd /path/to/omniclaude/claude_hooks
./test_hook_integration.sh
```

### 4. Test with Claude Code

Start Claude Code and submit a prompt. Check logs:

```bash
# Hook execution logs
tail -f ~/.claude/hooks/hook-enhanced.log

# Quality enforcer logs
tail -f ~/.claude/hooks/logs/quality_enforcer.log

# Post-tool-use logs
tail -f ~/.claude/hooks/logs/post-tool-use.log
```

## Viewing Hook Intelligence

### Dashboard View

```bash
# Real-time dashboard
python3 tools/hook_dashboard.py

# Correlation trace for specific request
python3 tools/hook_dashboard.py trace <correlation-id>
```

### Direct Database Queries

```bash
# Recent agent detections
PGPASSWORD=omninode-bridge-postgres-dev-2024 psql \
  -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT created_at, payload->>'agent_detected', payload->>'prompt_preview'
      FROM hook_events
      WHERE source = 'UserPromptSubmit'
      ORDER BY created_at DESC
      LIMIT 10;"

# Tool usage by agent
PGPASSWORD=omninode-bridge-postgres-dev-2024 psql \
  -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT
        metadata->>'agent_name' as agent,
        resource_id as tool,
        COUNT(*) as usage_count
      FROM hook_events
      WHERE source = 'PreToolUse'
        AND created_at > NOW() - INTERVAL '24 hours'
      GROUP BY agent, tool
      ORDER BY usage_count DESC;"
```

## Development Workflow

### Making Hook Changes

With symlinks setup:

```bash
# 1. Edit hook files in repository
cd /path/to/omniclaude/claude_hooks
nano user-prompt-submit.sh

# 2. Changes are immediately active (symlinked)
# 3. Test with Claude Code

# 4. Commit changes
git add claude_hooks/
git commit -m "feat: improve agent detection logic"
git push
```

### Updating Hook Libraries

```bash
# Edit Python libraries
cd /path/to/omniclaude/claude_hooks/lib
nano hybrid_agent_selector.py

# Test
python3 -m pytest tests/

# Changes are immediately active
```

## Troubleshooting

### Hooks not logging to database

```bash
# Check DB_PASSWORD is set
echo $DB_PASSWORD

# If empty, source .env
source .env

# Verify database is running
docker ps | grep postgres

# Test database connection
python3 tools/test_hook_event_logger.py
```

### Agent detection not working

```bash
# Check logs
tail -f ~/.claude/hooks/hook-enhanced.log

# Verify pattern files exist
ls -la ~/.claude/hooks/config/

# Test agent selector directly
echo "create a new ONEX microservice" | \
  python3 lib/hybrid_agent_selector.py -
```

### Symlink issues

```bash
# Verify symlink exists
ls -la ~/.claude/hooks

# Should show: hooks -> /path/to/repository/claude_hooks

# If broken, re-run setup
./claude_hooks/setup-symlinks.sh
```

## Performance Targets

- **UserPromptSubmit**: <100ms (non-blocking RAG)
- **PreToolUse**: <50ms (synchronous checks)
- **PostToolUse**: <50ms (synchronous fixes)
- **Database Logging**: <10ms per event
- **AI Agent Selection**: <3000ms (with timeout)

## Security Notes

- **Never commit `.env`** to version control
- Use `.env.example` as template only
- Rotate `DB_PASSWORD` for production environments
- Consider using separate databases for dev/staging/prod
- Enable SSL for production PostgreSQL connections

## Additional Resources

- **Hook Intelligence Guide**: `HOOK_INTELLIGENCE_GUIDE.md`
- **Configuration Guide**: `CONFIG_AND_MONITORING.md`
- **Troubleshooting**: `TROUBLESHOOTING.md`
- **Hook Summary**: `/tmp/hook_intelligence_summary.md`

## Support

For issues or questions:
1. Check troubleshooting guide
2. Review logs in `~/.claude/hooks/logs/`
3. Test individual components with provided test scripts
4. Verify database connectivity
5. Check environment variables are loaded
