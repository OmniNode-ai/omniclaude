# OmniClaude Plugin — Container / Non-macOS Installation

## Quick Start

After installing the plugin (`claude plugin add /path/to/omniclaude`), hooks need
a Python interpreter. The plugin auto-detects one in this order:

1. `PLUGIN_PYTHON_BIN` env var (explicit path to python3)
2. `CLAUDE_PLUGIN_DATA/.venv/bin/python3` (the plugin daemon venv)
3. `<repo root>/.venv/bin/python3` (the omniclaude repo venv, two levels above the plugin)
4. `ONEX_REGISTRY_ROOT/omniclaude/.venv/bin/python3`
5. `OMNICLAUDE_PROJECT_ROOT/.venv/bin/python3` (dev mode)
6. System `python3` (lite mode only — auto-detected in containers)

In containers, option 6 is typically used automatically. This list mirrors
`find_python()` in `hooks/scripts/common.sh`, which is the authority. There is no
bundled `lib/.venv`: that path left the chain in `035707dd2` (OMN-7310, 2026-04-02)
and was removed as an orphan in OMN-18746.

## Environment Variables

Set these via your shell environment, `~/.omnibase/.env`, or `~/.claude/settings.json` under `env`:

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `PLUGIN_PYTHON_BIN` | No | (auto-detect) | Override Python path if auto-detect fails |
| `OMNICLAUDE_MODE` | No | `lite` (in containers) | Force `full` or `lite` mode |
| `ENABLE_LOCAL_INFERENCE_PIPELINE` | No | `false` | Enable local LLM inference features |
| `ENABLE_LOCAL_ENRICHMENT` | No | `false` | Enable context enrichment |

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

> The path in that file is a *recorded* path, not necessarily the resolved one. On a
> workstation with a `directory`-source marketplace it records a cache path that is **not**
> the load path, and it can stay stale for weeks with no symptom (OMN-15274). If this
> container install has the omniclaude checkout available, resolve it rather than trusting
> the record: `python3 plugins/onex/hooks/lib/plugin_deploy_readback.py`. That tool is scoped
> to the `local_macos_claude_hooks` profile and is not part of the container install contract —
> a container that ships only the plugin payload will not have it, and it may resolve
> differently there. In that case, compare the recorded path against `known_marketplaces.json`
> by hand before concluding anything about which hooks run.

### Venv has wrong paths (macOS symlinks)

The venv was built on macOS. Delete the plugin daemon venv and let auto-repair
rebuild it:
```bash
rm -rf "${CLAUDE_PLUGIN_DATA:-$HOME/.claude/plugins/data/onex-omninode-tools}/.venv"
```
The next hook invocation will auto-create a fresh venv.
