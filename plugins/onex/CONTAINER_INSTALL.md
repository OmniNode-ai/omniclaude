# OmniClaude Plugin — Container / Non-macOS Installation

## Quick Start

After installing the plugin (`claude plugin add /path/to/omniclaude`), hooks need
a Python interpreter. The plugin auto-detects one in this order:

1. `PLUGIN_PYTHON_BIN` env var (explicit path to python3)
2. Bundled venv at `<plugin-cache>/lib/.venv/bin/python3`
3. `OMNICLAUDE_PROJECT_ROOT/.venv/bin/python3` (dev mode)
4. System `python3` (lite mode only — auto-detected in containers)

In containers, option 4 is typically used automatically.

## Environment Variables

Set these via your shell environment, `~/.omnibase/.env`, or `~/.claude/settings.json` under `env`:

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `PLUGIN_PYTHON_BIN` | No | (auto-detect) | Override Python path if auto-detect fails |
| `OMNICLAUDE_MODE` | No | `lite` (in containers) | Force `full` or `lite` mode |
| `ENABLE_LOCAL_INFERENCE_PIPELINE` | No | `false` | Enable local LLM inference features |
| `ENABLE_LOCAL_ENRICHMENT` | No | `false` | Enable context enrichment |
| `ENABLE_LOCAL_DELEGATION` | No | `false` | Enable task delegation daemon |

## What Works Without Infrastructure

- **Skills** (SKILL.md files): Fully functional, no dependencies
- **Agent configs** (YAML): Fully functional, no dependencies
- **Commands** (markdown): Fully functional
- **Hooks**: Functional with graceful degradation when Kafka/Postgres unavailable

## Troubleshooting

### Hooks fail with "No valid Python found"

Auto-repair couldn't create a venv. Either:
- Install `python3-venv`: `apt-get install python3.12-venv`
- Or install `uv`: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Or set `PLUGIN_PYTHON_BIN` explicitly in settings.json

### Skills not discoverable after path changes

Restart Claude Code to re-read `installed_plugins.json`. The plugin path
in that file must match the actual filesystem path in the container.

### Bundled venv has wrong paths (macOS symlinks)

The venv was built on macOS. Delete it and let auto-repair rebuild:
```bash
rm -rf ~/.claude/plugins/cache/omninode-tools/onex/*/lib/.venv
```
The next hook invocation will auto-create a fresh venv.
