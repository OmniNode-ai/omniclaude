# Debug Loop CLI - Quick Start Guide

## Installation

```bash
# Install dependencies
pip install click rich asyncpg

# Make script executable (optional)
chmod +x scripts/debug_loop_cli.py
```

## Configuration

```bash
# Ensure .env is configured
source .env

# Verify connection
echo $POSTGRES_PASSWORD  # Should not be empty
```

## Quick Examples

### STF Management

```bash
# List all STFs
python3 scripts/debug_loop_cli.py stf list

# Search for high-quality error handling patterns
python3 scripts/debug_loop_cli.py stf search --category "error_handling" --min-quality 0.9

# Show detailed STF
python3 scripts/debug_loop_cli.py stf show <stf_id>

# Store a new STF
python3 scripts/debug_loop_cli.py stf store \
  --code my_pattern.py \
  --name "My Pattern" \
  --description "Does X, Y, Z" \
  --category "validation" \
  --quality 0.85
```

### Model Pricing

```bash
# List all models
python3 scripts/debug_loop_cli.py model list

# Filter by provider
python3 scripts/debug_loop_cli.py model list --provider anthropic

# Show model details
python3 scripts/debug_loop_cli.py model show anthropic claude-3-5-sonnet

# Add new model (interactive)
python3 scripts/debug_loop_cli.py model add
```

## Features

- Beautiful Rich terminal UI with tables, panels, and syntax highlighting
- Color-coded quality scores and success rates
- Progress spinners during database queries
- Direct PostgreSQL access (no ONEX dependencies)
- Interactive model adding
- Automatic STF hash computation

## Available Commands

**7 total commands:**

**STF (4):**
- `stf list` - List all STFs with filters
- `stf show` - Show detailed STF
- `stf search` - Search with criteria
- `stf store` - Store new STF

**Model (3):**
- `model list` - List price catalog
- `model show` - Show model details
- `model add` - Add new model

## Help

```bash
# Main help
python3 scripts/debug_loop_cli.py --help

# Command-specific help
python3 scripts/debug_loop_cli.py stf list --help
python3 scripts/debug_loop_cli.py model add --help
```

## Troubleshooting

**Connection errors:**
```bash
source .env
python3 scripts/debug_loop_cli.py stf list
```

**Import errors:**
```bash
pip install click rich asyncpg
```

**No results:**
- Check if tables exist: `psql ... -c "\dt debug_*"`
- Lower quality threshold: `--min-quality 0.0`
- Check approval status

## Full Documentation

See `scripts/README_DEBUG_LOOP_CLI.md` for complete documentation.
