# OmniClaude

A comprehensive toolkit for Claude Code enhancements, including multi-provider support, agent workflows, and development utilities.

## Overview

OmniClaude provides tools and configurations to extend Claude Code capabilities beyond the default setup, focusing on multi-provider AI model support and enhanced development workflows.

## Features

### Multi-Provider Support
- **Dynamic provider switching** between Anthropic Claude, Z.ai, Together AI, and more
- **Rate limit optimization** with concurrent request management
- **Configuration-driven approach** for easy provider addition
- **Model mapping** to optimize cost and performance

### Planned Features
- Enhanced agent workflows
- Custom Claude Code hooks
- Development utilities and tools
- Configuration templates and examples

## Quick Start

### Provider Toggle Script

```bash
# Switch between providers
./toggle-claude-provider.sh zai       # Use Z.ai GLM models
./toggle-claude-provider.sh anthropic # Use native Claude models
./toggle-claude-provider.sh together  # Use Together AI models

# Check current status
./toggle-claude-provider.sh status

# List available providers
./toggle-claude-provider.sh list
```

### Configuration

Edit `claude-providers.json` to customize provider settings, add new providers, or adjust model mappings.

### Environment Variables

Before using the provider toggle script, you must set the required API keys as environment variables:

```bash
# Option 1: Copy and edit the example file (recommended)
cp .env.example .env
# Edit .env with your actual API keys, then:
source .env

# Option 2: Add to your shell profile
# Add to your ~/.bashrc, ~/.zshrc, or ~/.profile
export GEMINI_API_KEY="your_gemini_api_key_here"
export ZAI_API_KEY="your_zai_api_key_here"
```

**Security Note**: Never commit API keys directly to the repository. Always use environment variables or secure credential management systems.

**Important**: See [SECURITY_KEY_ROTATION.md](SECURITY_KEY_ROTATION.md) for:
- How to obtain API keys from provider dashboards
- Step-by-step key rotation procedures
- Testing and troubleshooting guides
- Security best practices

## Repository Structure

```
omniclaude/
├── README.md                         # This file
├── SECURITY_KEY_ROTATION.md          # API key security guide
├── .env.example                      # Environment template
├── toggle-claude-provider.sh         # Main provider toggle script
├── claude-providers.json             # Provider configuration file
├── ClaudeToggle.md                  # Planning and documentation
├── agents/                           # Agent framework
│   └── parallel_execution/           # Parallel execution agents
│       └── .env.example              # Agent-specific env template
└── docs/                            # Additional documentation (planned)
```

## Supported Providers

| Provider | Models | Concurrent Requests | Description |
|----------|--------|-------------------|-------------|
| Anthropic | Claude 3.5 | Standard limits | Official Anthropic models |
| Z.ai | GLM-4.5-Air, GLM-4.5, GLM-4.6 | 35 total | High-concurrency GLM models |
| Together AI | Llama 3.1 variants | Variable | Open-source models |
| OpenRouter | Multiple models | Variable | Model marketplace |

## Contributing

This is part of the OmniNode ecosystem. Contributions and feedback are welcome as we build out comprehensive Claude Code enhancements.

## License

Part of the OmniNode project. See main project for licensing details.