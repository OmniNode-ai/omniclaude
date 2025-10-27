# OmniClaude Quick Start Guide

Get up and running with OmniClaude in under 30 minutes. This guide covers installation, configuration, and your first provider switch.

## What You'll Set Up

- **Multi-provider AI switching** - Use 7 different AI providers with Claude Code
- **Polymorphic agent framework** - 52 specialized agents for development workflows
- **Claude Code hooks** - Automatic quality gates and pattern tracking
- **Optional production infrastructure** - PostgreSQL, Docker, and monitoring (can skip for basic usage)

## Prerequisites

### Required

- **Claude Code CLI** - Must be installed and working
  ```bash
  # Verify installation
  claude --version
  # Expected: claude-code version x.x.x
  ```

- **jq** - JSON processor for configuration management
  ```bash
  # macOS
  brew install jq

  # Ubuntu/Debian
  sudo apt-get install jq

  # Verify
  jq --version
  # Expected: jq-1.6 or higher
  ```

- **Python 3.12+** - Required for agent framework
  ```bash
  python3 --version
  # Expected: Python 3.12.0 or higher
  ```

- **Poetry** (recommended) - Python dependency management
  ```bash
  curl -sSL https://install.python-poetry.org | python3 -

  # Verify
  poetry --version
  # Expected: Poetry (version x.x.x)
  ```

### Optional (for production features)

- **Docker Desktop** - For containerized services
- **PostgreSQL 15+** - For pattern tracking and observability
- **Git** - Already required by Claude Code

---

## Installation

### Step 1: Clone and Navigate

```bash
# Clone the repository
git clone https://github.com/yourusername/omniclaude.git
cd omniclaude

# Verify structure
ls -la
# Expected: README.md, CLAUDE.md, toggle-claude-provider.sh, .env.example, etc.
```

### Step 2: Configure Environment Variables

```bash
# Copy environment template
cp .env.example .env

# Edit with your API keys
nano .env  # or use your preferred editor

# Minimal configuration (for basic provider switching):
# - GEMINI_API_KEY=your_actual_gemini_key_here
# - GOOGLE_API_KEY=your_actual_gemini_key_here (same as GEMINI_API_KEY)
# - ZAI_API_KEY=your_actual_zai_key_here (if using Z.ai)

# Load environment
source .env

# Verify configuration
echo $GEMINI_API_KEY
# Expected: Your actual API key (not "your_gemini_api_key_here")
```

**Getting API Keys:**
- **Gemini**: https://console.cloud.google.com/apis/credentials (Enable "Generative Language API")
- **Z.ai**: https://z.ai/dashboard (or appropriate Z.ai portal)
- **Others**: See `.env.example` for provider details and API key sources

**Security Note:** Never commit your `.env` file to version control. It's already in `.gitignore`.

### Step 3: Install Python Dependencies

```bash
# Using Poetry (recommended)
poetry install

# Expected output:
# Installing dependencies from lock file
# ...
# Installing the current project: omniclaude-agents (0.1.0)

# Activate virtual environment
poetry shell

# Verify installation
python -c "import pydantic; print('Dependencies OK')"
# Expected: Dependencies OK
```

**Alternative (without Poetry):**
```bash
# Using pip
pip install -e .
```

### Step 4: Test Provider Switching

```bash
# Make script executable
chmod +x toggle-claude-provider.sh

# Check current status
./toggle-claude-provider.sh status

# Expected output:
# ══════════════════════════════════════════════════════════
#   Claude Code Provider Status
# ══════════════════════════════════════════════════════════
#   Current Provider: claude (Anthropic)
#   ...

# List all available providers
./toggle-claude-provider.sh list

# Expected output:
# Available providers:
# - claude (Anthropic Claude - official models)
# - zai (Z.ai GLM models - high concurrency)
# - together (Together AI - open source models)
# - openrouter (OpenRouter - model marketplace)
# - gemini-pro (Google Gemini Pro - quality focus)
# - gemini-flash (Google Gemini Flash - speed optimized)
# - gemini-2.5-flash (Google Gemini 2.5 - latest)
```

### Step 5: Switch to Your First Provider

```bash
# Switch to Gemini 2.5 Flash (fast, latest features)
./toggle-claude-provider.sh gemini-2.5-flash

# Expected output:
# ══════════════════════════════════════════════════════════
#   Switching to gemini-2.5-flash Provider
# ══════════════════════════════════════════════════════════
# ✓ Settings backup created: /Users/you/.claude/settings.json.backup
# ✓ Provider configuration applied
# ✓ Switch completed successfully
#
# ⚠️  RESTART REQUIRED: Please restart Claude Code to apply changes
```

### Step 6: Restart Claude Code

```bash
# Quit Claude Code completely
# Then restart from Applications or command line

# Verify the switch worked
./toggle-claude-provider.sh status

# Expected: Shows your new provider (gemini-2.5-flash)
```

---

## Verify Your Setup

### Test Provider Functionality

Open Claude Code and run a simple test:

```bash
# In Claude Code terminal or chat
echo "Hello from OmniClaude with $(./toggle-claude-provider.sh status | grep 'Current Provider')"
```

Expected behavior:
- Claude Code responds normally
- Uses the provider you selected
- No errors about API keys

### Check Agent Framework

```bash
# View available agents
ls agents/configs/ | wc -l
# Expected: 52 (or close to it)

# View agent definitions
ls ~/.claude/agent-definitions/
# Expected: agent-registry.yaml and various agent-*.yaml files
```

### Verify Hooks Are Active

Claude Code hooks activate automatically. Test by using Claude Code:

1. Start a new Claude Code session
2. Hooks automatically process your requests
3. Check for hook logs (if configured)

**Note:** Hooks work transparently - no additional setup needed.

---

## Optional: Production Infrastructure Setup

Skip this section if you only want basic provider switching and agent framework. These steps are for advanced features like pattern tracking, observability, and monitoring.

### Prerequisites for Production Setup

- Docker Desktop installed and running
- PostgreSQL client tools (optional, for direct DB access)

### Step 1: Initialize Database

```bash
# Option A: Using Docker Compose (recommended)
docker-compose -f deployment/docker-compose.yml up -d postgres

# Wait for database to be ready (~10 seconds)
sleep 10

# Run initialization script
./scripts/init-db.sh

# Expected output:
# Initializing OmniClaude database...
# CREATE EXTENSION
# CREATE SCHEMA
# ...
# Database initialization completed successfully!
```

### Step 2: Start All Services

```bash
# Start full stack (database, observability, monitoring)
docker-compose -f deployment/docker-compose.yml up -d

# Expected output:
# Creating network "omniclaude_default" ...
# Creating omniclaude_postgres_1 ...
# Creating omniclaude_agent-observability-consumer_1 ...
# ...

# Verify services are running
docker-compose -f deployment/docker-compose.yml ps

# Expected: All services show "Up" status
```

### Step 3: Verify Health Checks

```bash
# Check database connectivity
docker exec $(docker ps -qf "name=postgres") psql -U postgres -d omninode_bridge -c "SELECT 1;"
# Expected: 1 row returned

# Check observability consumer
docker logs $(docker ps -qf "name=agent-observability-consumer") --tail 20
# Expected: No error messages, "Consumer started" message

# View service health dashboard (if running)
open http://localhost:8080  # Or appropriate port for your setup
```

---

## Configuration

### Environment Variables Explained

Key variables from `.env`:

```bash
# Google Gemini (required for Gemini providers)
GEMINI_API_KEY=your_key          # Gemini Pro, Flash, 2.5 Flash
GOOGLE_API_KEY=your_key          # Pydantic AI integration

# Z.ai (required for Z.ai provider)
ZAI_API_KEY=your_key             # GLM-4.5-Air, GLM-4.5, GLM-4.6

# Database (optional, for production features)
DB_PASSWORD=omninode-bridge-postgres-dev-2024
OMNINODE_BRIDGE_POSTGRES_PASSWORD=omninode-bridge-postgres-dev-2024

# Kafka (optional, for event-based intelligence)
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_ENABLE_INTELLIGENCE=true

# Development paths (optional, auto-detected)
# OMNIARCHON_PATH=../omniarchon
# OMNINODE_BRIDGE_PATH=../omninode_bridge
```

**What's Required?**
- Basic usage: Only API keys for providers you'll use
- Production features: Database passwords, Kafka configuration
- Code refinement: Development repository paths (auto-detected if in sibling directories)

### Provider Configuration

Edit `claude-providers.json` to:
- Add new AI providers
- Adjust rate limits and concurrency
- Customize model mappings
- Configure provider-specific settings

See [CLAUDE.md](CLAUDE.md) for detailed provider configuration documentation.

---

## Troubleshooting

### Issue: "jq: command not found"

```bash
# Solution: Install jq
# macOS
brew install jq

# Ubuntu/Debian
sudo apt-get install jq

# Verify
jq --version
```

### Issue: "Error: GEMINI_API_KEY environment variable not set"

```bash
# Solution: Ensure .env is sourced and contains your key
source .env
echo $GEMINI_API_KEY

# If empty, edit .env and add your actual key
nano .env
```

### Issue: Provider switch doesn't take effect

```bash
# Solution: Restart Claude Code completely
# 1. Quit Claude Code (Cmd+Q on macOS)
# 2. Relaunch Claude Code
# 3. Verify with: ./toggle-claude-provider.sh status
```

### Issue: "Permission denied" when running scripts

```bash
# Solution: Make scripts executable
chmod +x toggle-claude-provider.sh
chmod +x scripts/init-db.sh
```

### Issue: Python version too old

```bash
# Check version
python3 --version

# Solution: Install Python 3.12+
# macOS (using Homebrew)
brew install python@3.12

# Ubuntu/Debian
sudo apt-get install python3.12

# Verify
python3.12 --version
```

### Issue: Poetry not found after installation

```bash
# Solution: Add Poetry to your PATH
export PATH="$HOME/.local/bin:$PATH"

# Make permanent by adding to ~/.bashrc or ~/.zshrc
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### Issue: Docker services won't start

```bash
# Solution: Check Docker Desktop is running
docker ps
# If error, start Docker Desktop

# Check for port conflicts
lsof -i :5432  # PostgreSQL default port
lsof -i :9092  # Kafka default port

# If ports are in use, stop conflicting services or change ports in docker-compose.yml
```

### Issue: Agent framework not working

```bash
# Solution: Verify agent definitions are installed
ls ~/.claude/agent-definitions/

# If empty or missing, check installation
poetry install

# Reinstall if needed
poetry install --no-cache
```

### Issue: Hooks not activating

**Expected behavior:** Hooks activate automatically when Claude Code runs.

```bash
# Verify hooks exist
ls claude_hooks/*.sh

# Expected: session-start.sh, user-prompt-submit.sh, pre-tool-use-quality.sh, etc.

# Check hook permissions
ls -la claude_hooks/*.sh
# Expected: All hooks should be executable (rwxr-xr-x)

# If not executable:
chmod +x claude_hooks/*.sh
```

**Note:** If hooks aren't working, they may need to be registered with Claude Code. Check Claude Code documentation for hook registration.

---

## Next Steps

### Learn Provider Switching

```bash
# Try different providers for different use cases
./toggle-claude-provider.sh gemini-2.5-flash  # Fast, latest features
./toggle-claude-provider.sh gemini-pro         # Quality focus
./toggle-claude-provider.sh zai                # High concurrency (35 requests)
./toggle-claude-provider.sh anthropic          # Official Claude models

# Always restart Claude Code after switching
```

### Explore Agent Framework

Agents automatically route based on your requests:
- "Debug this error" → agent-debug-intelligence
- "Review this PR" → agent-pr-review
- "Optimize performance" → agent-performance
- "Generate tests" → agent-testing

View all agents:
```bash
ls agents/configs/
cat agents/configs/agent-debug-intelligence.yaml
```

### Read Full Documentation

- **[CLAUDE.md](CLAUDE.md)** - Complete project architecture and patterns
- **[README.md](README.md)** - Full feature overview and statistics
- **[.env.example](.env.example)** - API key setup and configuration guide
- **[agents/core-requirements.yaml](agents/core-requirements.yaml)** - Agent framework requirements

### Enable Advanced Features

Once basic setup works:

1. **Production Infrastructure** - Setup Docker services for observability
2. **Event-Based Intelligence** - Enable Kafka-based pattern discovery
3. **Quality Gates** - Configure automated validation checkpoints
4. **Performance Monitoring** - Setup real-time dashboards

See [CLAUDE.md](CLAUDE.md) for advanced configuration.

### Join the Community

- Report issues: GitHub Issues
- Contribute: See [README.md](README.md) Contributing section
- Share patterns: Help improve the agent framework

---

## Quick Reference

### Essential Commands

```bash
# Provider management
./toggle-claude-provider.sh status              # Check current provider
./toggle-claude-provider.sh list                # List all providers
./toggle-claude-provider.sh <provider-name>     # Switch provider
./toggle-claude-provider.sh help                # Show help

# Environment
source .env                                     # Load environment variables
echo $GEMINI_API_KEY                            # Verify API key loaded

# Dependencies
poetry install                                  # Install Python dependencies
poetry shell                                    # Activate virtual environment

# Docker (optional)
docker-compose -f deployment/docker-compose.yml up -d     # Start services
docker-compose -f deployment/docker-compose.yml ps        # Check status
docker-compose -f deployment/docker-compose.yml logs -f   # View logs
docker-compose -f deployment/docker-compose.yml down      # Stop services

# Agents
ls agents/configs/                              # List all agents
ls ~/.claude/agent-definitions/                 # List agent definitions
```

### Important Files

- `.env` - Your API keys and configuration (DO NOT commit)
- `claude-providers.json` - Provider definitions and settings
- `toggle-claude-provider.sh` - Main provider switching tool
- `~/.claude/settings.json` - Claude Code settings (modified by toggle script)
- `~/.claude/settings.json.backup` - Backup created before each switch

### Support

- **Documentation Issues**: Check [CLAUDE.md](CLAUDE.md) for detailed explanations
- **API Key Issues**: See [.env.example](.env.example) for configuration details
- **Agent Issues**: Review [agents/core-requirements.yaml](agents/core-requirements.yaml)
- **Bug Reports**: Open a GitHub issue with error details

---

## Success Checklist

- [ ] Prerequisites installed (Claude Code, jq, Python 3.12+, Poetry)
- [ ] Repository cloned and `.env` configured
- [ ] Python dependencies installed via Poetry
- [ ] Provider switch tested successfully
- [ ] Claude Code restarted and using new provider
- [ ] Basic functionality verified (test prompt in Claude Code)
- [ ] Agent framework accessible (52 agent configs found)
- [ ] Optional: Production infrastructure running (if needed)

**Setup time:** ~15-25 minutes for basic setup, ~30-40 minutes with production infrastructure

---

**Welcome to OmniClaude!** You're now ready to leverage multi-provider AI, intelligent agent orchestration, and production-grade development workflows. Start by experimenting with different providers and letting agents automatically handle your tasks.

For advanced usage, deep dive into [CLAUDE.md](CLAUDE.md) and explore the polymorphic agent framework. Happy coding!
