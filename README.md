# omniclaude

Claude Code integration layer for the ONEX platform -- hooks, routing, intelligence, and agent coordination.

[![CI](https://github.com/OmniNode-ai/omniclaude/actions/workflows/ci.yml/badge.svg)](https://github.com/OmniNode-ai/omniclaude/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Install

Install as a Claude Code plugin:

```bash
claude plugin add /path/to/omniclaude
```

## Example

```yaml
# skills/my-skill/skill.yaml
name: my-skill
description: Example skill
```

```python
# Hook that runs on every prompt
async def on_prompt(prompt: str) -> str:
    # Route, classify, or transform the prompt
    return prompt
```

## Key Features

- **Hook system**: UserPromptSubmit, PreToolUse, PostToolUse lifecycle hooks
- **Agent routing**: Polymorphic agent with 53 specialized agent configs
- **Skills**: PR review, Linear integration, commit automation, and more
- **Intelligence**: Event-based pattern discovery and quality assessment via Kafka
- **AI quorum**: Multi-model consensus for critical decisions

## Documentation

- [Architecture](docs/architecture/)
- [Skills catalog](plugins/onex/skills/)
- [CLAUDE.md](CLAUDE.md) -- developer context and conventions
- [AGENT.md](AGENT.md) -- LLM navigation guide

## License

[MIT](LICENSE)
