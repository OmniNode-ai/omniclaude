# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

OmniClaude is a toolkit for enhancing Claude Code capabilities with multi-provider AI model support and development utilities. The primary focus is on enabling dynamic switching between different AI providers while maintaining optimal rate limits and concurrency.

## Development Commands

### Provider Management
```bash
# Switch between AI providers
./toggle-claude-provider.sh claude        # Use Anthropic Claude models
./toggle-claude-provider.sh zai           # Use Z.ai GLM models
./toggle-claude-provider.sh together      # Use Together AI models
./toggle-claude-provider.sh openrouter    # Use OpenRouter models
./toggle-claude-provider.sh gemini-pro      # Use Google Gemini Pro models
./toggle-claude-provider.sh gemini-flash    # Use Google Gemini Flash models
./toggle-claude-provider.sh gemini-2.5-flash # Use Google Gemini 2.5 Flash models

# Check current provider status
./toggle-claude-provider.sh status

# List all available providers
./toggle-claude-provider.sh list

# Get help
./toggle-claude-provider.sh help
```

### Script Testing
```bash
# Test script functionality
./toggle-claude-provider.sh --help    # Show usage
./toggle-claude-provider.sh status    # Check current state
```

### Environment Setup

Before using provider commands, set up environment variables:

```bash
# Copy environment template
cp .env.example .env

# Edit with your API keys
nano .env

# Load environment variables
source .env

# Verify setup
echo $GEMINI_API_KEY
echo $ZAI_API_KEY
```

See [SECURITY_KEY_ROTATION.md](SECURITY_KEY_ROTATION.md) for:
- Obtaining API keys from provider dashboards
- Security best practices and key rotation
- Testing and troubleshooting

## Architecture

### Core Components

**Provider Configuration System** (`claude-providers.json`):
- Configuration-driven provider management
- Model mapping and rate limit definitions
- Environment variable templates for each provider
- Validation and cleanup procedures

**Provider Toggle Script** (`toggle-claude-provider.sh`):
- Dynamic provider switching using jq for JSON manipulation
- Backup/restore mechanism for Claude settings
- Colored output and status reporting
- Error handling and validation

**Provider Support**:
- **Anthropic**: Native Claude models with standard rate limits
- **Z.ai**: GLM-4.5-Air, GLM-4.5, GLM-4.6 with high concurrency (35 total)
- **Together AI**: Llama-3.1 variants with variable limits
- **OpenRouter**: Model marketplace with OpenRouter-specific limits
- **Google Gemini Pro**: Gemini 1.5 Flash/Pro with quality focus
- **Google Gemini Flash**: Gemini 1.5 Flash optimized for speed
- **Google Gemini 2.5 Flash**: Gemini 2.5 Flash/Pro with latest capabilities

### Configuration Structure

The `claude-providers.json` file defines:
- Provider metadata and API endpoints
- Model mappings (haiku/sonnet/opus equivalents)
- Rate limits and concurrency settings
- Environment variable templates
- Cleanup procedures for switching providers

### Settings Management

The system modifies `~/.claude/settings.json` to:
- Set provider-specific base URLs and API keys
- Map Claude model names to provider equivalents
- Configure rate limits and concurrent requests
- Backup/restore previous configurations

## Development Patterns

### Adding New Providers
1. Add provider configuration to `claude-providers.json`
2. Define model mappings and rate limits
3. Specify environment variables needed
4. Test with `./toggle-claude-provider.sh <provider>`

### Provider Validation
- JSON structure validation
- API key format checking
- Model mapping verification
- Settings file backup before changes

### Error Handling
- Graceful degradation for missing configurations
- Clear error messages with colored output
- Automatic backup restoration on failure
- Provider discovery and validation

## Key Files

- `toggle-claude-provider.sh` - Main provider management script
- `claude-providers.json` - Provider configuration file
- `SECURITY_KEY_ROTATION.md` - API key security and rotation guide
- `.env.example` - Environment variable template
- `CLAUDETOGGLE.md` - Planning and architecture documentation
- `README.md` - Project overview and usage instructions

## Polymorphic Agent Framework

The `agents/` directory contains a comprehensive polymorphic agent framework for Claude Code, built on ONEX architecture principles.

### Agent Architecture

**Core Components**:
- **Agent Workflow Coordinator**: Unified orchestration with routing, parallel execution, and dynamic transformation
- **Enhanced Router System**: Intelligent agent selection with fuzzy matching and confidence scoring
- **ONEX Compliance**: 4-node architecture (Effect, Compute, Reducer, Orchestrator) with strict naming conventions
- **Multi-Agent Coordination**: Parallel execution with shared state and dependency tracking

### Framework Requirements

**Mandatory Functions** (47 total across 11 categories):
- Intelligence Capture (4 functions): Pre-execution intelligence gathering
- Execution Lifecycle (5 functions): Agent lifecycle management
- Debug Intelligence (3 functions): Debug pattern capture and analysis
- Context Management (4 functions): Context inheritance and preservation
- Coordination Protocols (5 functions): Multi-agent communication
- Performance Monitoring (4 functions): Real-time performance tracking
- Quality Validation (5 functions): ONEX compliance and quality gates
- Parallel Coordination (4 functions): Synchronization and result aggregation
- Knowledge Capture (4 functions): UAKS framework implementation
- Error Handling (5 functions): Graceful degradation and retry logic
- Framework Integration (4 functions): Template system and @include references

### Quality Gates System

**23 Quality Gates** across 8 validation types:
- Sequential validation: Input/process/output validation
- Parallel validation: Distributed coordination validation
- Intelligence validation: RAG intelligence application
- Coordination validation: Multi-agent context inheritance
- Quality compliance: ONEX standards validation
- Performance validation: Threshold compliance
- Knowledge validation: Learning pattern validation
- Framework validation: Lifecycle integration

### Agent Discovery System

**Enhanced Routing Components**:
- **Trigger Matcher**: Fuzzy matching with multiple strategies
- **Confidence Scorer**: 4-component weighted scoring
- **Capability Index**: In-memory inverted index for fast lookups
- **Result Cache**: TTL-based caching with hit tracking

### AI Quorum Integration

**Available Models** (Total Weight: 7.5):
- Gemini Flash (1.0) - Cloud baseline
- Codestral @ Mac Studio (1.5) - Code specialist
- DeepSeek-Lite @ RTX 5090 (2.0) - Advanced codegen
- Llama 3.1 @ RTX 4090 (1.2) - General reasoning
- DeepSeek-Full @ Mac Mini (1.8) - Full code model

### ONEX Architecture Patterns

**Node Types**:
- **Effect**: External I/O, APIs, side effects (`Node<Name>Effect`)
- **Compute**: Pure transforms/algorithms (`Node<Name>Compute`)
- **Reducer**: Aggregation, persistence, state (`Node<Name>Reducer`)
- **Orchestrator**: Workflow coordination (`Node<Name>Orchestrator`)

**File Patterns**:
- Models: `model_<name>.py` → `Model<Name>`
- Contracts: `model_contract_<type>.py` → `ModelContract<Type>`
- Node files: `node_*_<type>.py` → `Node<Name><Type>`

### Configuration Structure

**Agent Registry**: Located in `~/.claude/agent-definitions/`
- Central registry for all agent definitions
- YAML-based configuration with metadata
- Dynamic agent loading and transformation

**Performance Targets**:
- Routing accuracy: >95%
- Average query time: <100ms
- Cache hit rate: >60%
- Quality gate execution: <200ms per gate

### Development Commands for Agents

```bash
# View agent configurations
ls agents/configs/                    # List all agent definitions
cat agents/configs/agent-*.yaml       # View specific agent configuration

# Check framework requirements
cat agents/core-requirements.yaml     # View 47 mandatory functions
cat agents/quality-gates-spec.yaml    # View 23 quality gates

# Test agent routing
python -m agents.lib.enhanced_router  # Test routing system (if implemented)
```

## Notes

- Requires `jq` for JSON manipulation in provider toggle
- Modifies `~/.claude/settings.json` (creates backups)
- Requires Claude Code restart after provider changes
- **API keys must be set via environment variables** (see `.env.example`)
- Never commit `.env` files with actual API keys to version control
- Supports concurrent request optimization across providers
- Agent framework requires ONEX compliance for all implementations
- Quality gates provide automated validation with <200ms execution target

## Security

**Important**: This repository uses environment variables for API key management:

1. **Never commit API keys** to version control
2. **Use `.env.example`** as a template for your local `.env` file
3. **Rotate keys regularly** (every 30-90 days recommended)
4. **See [SECURITY_KEY_ROTATION.md](SECURITY_KEY_ROTATION.md)** for complete security procedures
