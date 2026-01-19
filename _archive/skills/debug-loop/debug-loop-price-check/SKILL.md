---
name: debug-loop-price-check
description: Query AI model pricing from model_price_catalog table with cost calculations and comparisons
---

# Debug Loop Price Check

Comprehensive AI model pricing tool that queries the `model_price_catalog` table for pricing information, calculates estimated costs, and provides rich formatted comparison tables.

## Overview

This skill provides instant access to AI model pricing across multiple providers (Anthropic, OpenAI, Google, Together, etc.) with:

- **Price Comparison**: Side-by-side pricing for all active models
- **Cost Calculation**: Estimate costs based on input/output token counts
- **Filtering**: Filter by provider, model name, or capabilities
- **Rich Formatting**: Beautiful tables with color-coded costs
- **Active Models**: Automatically filters to active (non-deprecated) models

## When to Use

- Before selecting a model for a task
- When estimating costs for bulk operations
- When comparing provider pricing
- When debugging cost overruns
- When planning budget allocation
- When validating model availability

## Usage

Use the Bash tool to execute:

```bash
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing [OPTIONS]
```

### Options

| Option | Description | Example |
|--------|-------------|---------|
| `--provider` | Filter by provider name | `--provider anthropic` |
| `--model` | Filter by model name (partial match) | `--model claude-3` |
| `--input-tokens` | Calculate cost for N input tokens | `--input-tokens 10000` |
| `--output-tokens` | Calculate cost for N output tokens | `--output-tokens 5000` |
| `--all` | Show all models (including inactive) | `--all` |
| `--json` | Output as JSON instead of table | `--json` |

### Examples

**1. List all active models with pricing:**
```bash
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing
```

**2. Filter by provider:**
```bash
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing --provider anthropic
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing --provider google
```

**3. Filter by model name:**
```bash
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing --model claude-3
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing --model gpt-4
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing --model gemini
```

**4. Calculate estimated cost:**
```bash
# Estimate cost for 10K input tokens + 5K output tokens
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing --input-tokens 10000 --output-tokens 5000

# Just input tokens
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing --input-tokens 100000

# Filter + calculate
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing --provider anthropic --input-tokens 10000 --output-tokens 5000
```

**5. JSON output for scripting:**
```bash
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing --provider google --json | jq '.[] | select(.model_name | contains("flash"))'
```

## Output Format

### Table Format (Default)

```
╭─────────────────────────────────────────────────────────────────────────────────╮
│                         AI Model Pricing Comparison                              │
├──────────────┬────────────────────────────┬──────────────┬──────────────┬────────┤
│ Provider     │ Model                      │ Input/1M     │ Output/1M    │ Total  │
├──────────────┼────────────────────────────┼──────────────┼──────────────┼────────┤
│ anthropic    │ claude-3-5-sonnet-20241022 │ $3.0000      │ $15.0000     │ $18.00 │
│ anthropic    │ claude-3-haiku-20240307    │ $0.2500      │ $1.2500      │ $1.50  │
│ google       │ gemini-1.5-flash           │ $0.0750      │ $0.3000      │ $0.38  │
│ google       │ gemini-2.5-flash           │ $0.1000      │ $0.4000      │ $0.50  │
╰──────────────┴────────────────────────────┴──────────────┴──────────────┴────────╯

Most Cost-Effective Models:
  🥇 gemini-1.5-flash: $0.38 per 1M tokens
  🥈 gemini-2.5-flash: $0.50 per 1M tokens
  🥉 claude-3-haiku-20240307: $1.50 per 1M tokens
```

### With Cost Calculation

```
╭─────────────────────────────────────────────────────────────────────────────────╮
│                    Cost Estimate (10,000 input + 5,000 output)                  │
├──────────────┬────────────────────────────┬──────────────┬──────────────┬────────┤
│ Provider     │ Model                      │ Input Cost   │ Output Cost  │ Total  │
├──────────────┼────────────────────────────┼──────────────┼──────────────┼────────┤
│ anthropic    │ claude-3-5-sonnet-20241022 │ $0.0300      │ $0.0750      │ $0.105 │
│ anthropic    │ claude-3-haiku-20240307    │ $0.0025      │ $0.0063      │ $0.009 │
│ google       │ gemini-1.5-flash           │ $0.0008      │ $0.0015      │ $0.002 │
│ google       │ gemini-2.5-flash           │ $0.0010      │ $0.0020      │ $0.003 │
╰──────────────┴────────────────────────────┴──────────────┴──────────────┴────────╯

Cheapest Option: gemini-1.5-flash ($0.002)
Most Expensive: claude-3-5-sonnet-20241022 ($0.105)
Savings: $0.103 (98.1%)
```

### JSON Format

```json
[
  {
    "provider": "anthropic",
    "model_name": "claude-3-5-sonnet-20241022",
    "model_version": "20241022",
    "input_price_per_million": 3.0,
    "output_price_per_million": 15.0,
    "currency": "USD",
    "avg_latency_ms": 2000,
    "context_window": 200000,
    "supports_streaming": true,
    "supports_function_calling": true,
    "is_active": true,
    "estimated_cost": {
      "input_cost": 0.03,
      "output_cost": 0.075,
      "total_cost": 0.105
    }
  }
]
```

## Integration with Debug Loop

This skill is designed to support the debug loop workflow:

1. **Pre-Execution**: Check model costs before running expensive operations
2. **Cost Tracking**: Calculate costs for completed debug loops
3. **Budget Planning**: Estimate costs for batch operations
4. **Provider Selection**: Compare providers for cost optimization

## Database Schema

Queries the `model_price_catalog` table:

| Column | Type | Description |
|--------|------|-------------|
| provider | varchar | Provider name (anthropic, openai, google, together) |
| model_name | varchar | Model identifier |
| model_version | varchar | Model version string |
| input_price_per_million | numeric | Cost per 1M input tokens (USD) |
| output_price_per_million | numeric | Cost per 1M output tokens (USD) |
| currency | varchar | Currency code (USD) |
| avg_latency_ms | integer | Average response latency |
| context_window | integer | Maximum context window size |
| supports_streaming | boolean | Streaming support flag |
| supports_function_calling | boolean | Function calling support flag |
| supports_vision | boolean | Vision/image input support flag |
| is_active | boolean | Active/deprecated status |

## Performance

- **Query Time**: <100ms typical
- **Caching**: Results cached per execution
- **Rate Limits**: None (direct database access)

## Dependencies

**Python Packages** (already installed in omniclaude):
- `psycopg2` - PostgreSQL adapter
- `rich` - Terminal formatting
- `config` - Type-safe configuration (omniclaude config module)

**Database**:
- PostgreSQL at `192.168.86.200:5436`
- Database: `omninode_bridge`
- Table: `model_price_catalog`

## Error Handling

- **Database unavailable**: Returns error with connection details
- **No results**: Shows "No models found matching criteria"
- **Invalid tokens**: Validates token counts are positive integers
- **Missing credentials**: Reports missing POSTGRES_PASSWORD in .env

## Common Use Cases

### Budget Planning
```bash
# Estimate cost for 1M token workflow
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing \
  --input-tokens 500000 \
  --output-tokens 500000
```

### Provider Comparison
```bash
# Compare Anthropic vs Google for same workload
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing --provider anthropic --input-tokens 10000 --output-tokens 5000
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing --provider google --input-tokens 10000 --output-tokens 5000
```

### Cost Tracking
```bash
# Check if model pricing changed
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing --model claude-3-5-sonnet
```

### Model Discovery
```bash
# Find all flash models (fast/cheap)
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing --model flash

# Find all haiku models (cheap)
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing --model haiku
```

## Skills Location

**Claude Code Access**: `~/.claude/skills/debug-loop/debug-loop-price-check/`
**Executable**: `~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing`

## Notes

- Prices are per **1 million tokens** (not 1K tokens like some APIs report)
- Only shows **active models** by default (use `--all` to include deprecated)
- **Cost calculations** assume input/output prices are independent
- **Streaming** and **function calling** support indicated in full table view
- Database connection uses shared infrastructure (192.168.86.200)

## Debugging

If the script fails:

```bash
# Check database connectivity
source .env && python3 -c "from config import settings; print(settings.get_postgres_dsn())"

# Verify table exists
source .env && psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "\d model_price_catalog"

# Run with error details
~/.claude/skills/debug-loop/debug-loop-price-check/check-pricing --provider test 2>&1
```

## See Also

- Debug Loop CLI: `scripts/debug_loop_cli.py`
- Model Price Catalog Effect: `omniclaude/debug_loop/node_model_price_catalog_effect.py`
- ONEX Debug Loop Documentation: `scripts/README_DEBUG_LOOP_CLI.md`
