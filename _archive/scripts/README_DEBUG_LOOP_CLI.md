# Debug Loop Intelligence CLI

User-friendly command-line interface for managing Solution Template Fragments (STFs) and model pricing catalog.

## Installation

### Prerequisites

```bash
pip install click rich asyncpg
```

### Environment Setup

The CLI requires PostgreSQL connection details. Ensure your `.env` file is configured:

```bash
# Copy from example
cp .env.example .env

# Edit with your values
nano .env

# Load environment
source .env
```

Required environment variables:
- `POSTGRES_HOST` (default: 192.168.86.200)
- `POSTGRES_PORT` (default: 5436)
- `POSTGRES_USER` (default: postgres)
- `POSTGRES_PASSWORD` (required - no default)
- `POSTGRES_DATABASE` (default: omninode_bridge)

## Usage

### STF Commands

#### List all STFs

```bash
# List all STFs (default: 20 results)
python3 scripts/debug_loop_cli.py stf list

# Filter by category
python3 scripts/debug_loop_cli.py stf list --category "data_validation"

# Adjust quality threshold
python3 scripts/debug_loop_cli.py stf list --min-quality 0.8 --limit 50
```

**Output includes:**
- STF name and category
- Quality score (color-coded: green ≥0.9, yellow ≥0.7, red <0.7)
- Usage count and success rate
- Approval status
- Summary statistics

#### Show detailed STF

```bash
python3 scripts/debug_loop_cli.py stf show <stf_id>
```

**Displays:**
- Full metadata (category, quality, usage, success rate)
- Complete description
- Full code with syntax highlighting
- Hash and timestamps

#### Search STFs

```bash
# Search by category
python3 scripts/debug_loop_cli.py stf search --category "error_handling"

# Adjust quality threshold
python3 scripts/debug_loop_cli.py stf search --min-quality 0.9 --limit 5
```

**Returns:**
- Filtered results matching criteria
- Only approved STFs (by default)
- Sorted by quality and usage

#### Store new STF

```bash
python3 scripts/debug_loop_cli.py stf store \
  --code path/to/code.py \
  --name "My STF" \
  --description "Does something useful" \
  --category "data_validation" \
  --quality 0.85
```

**Features:**
- Automatic hash computation (detects duplicates)
- Validates code file exists
- Stores with initial quality score
- Returns STF ID and hash

### Model Pricing Commands

#### List all models

```bash
# List all active models
python3 scripts/debug_loop_cli.py model list

# Filter by provider
python3 scripts/debug_loop_cli.py model list --provider anthropic

# Include inactive models
python3 scripts/debug_loop_cli.py model list --all
```

**Output includes:**
- Provider and model name
- Input/output pricing per million tokens
- Feature support badges:
  - 🔄 Streaming
  - 🔧 Function calling
- Active/inactive status
- Summary statistics

#### Show model details

```bash
python3 scripts/debug_loop_cli.py model show anthropic claude-3-5-sonnet
```

**Displays:**
- Complete pricing information
- Feature support matrix
- Rate limits (if configured)
- Version and metadata

#### Add new model

```bash
# Interactive mode
python3 scripts/debug_loop_cli.py model add
```

**Prompts for:**
- Provider (anthropic, openai, google, zai, together)
- Model name and version
- Input/output pricing
- Max tokens and context window
- Feature support flags
- Rate limits

## Examples

### Common Workflows

**Find high-quality STFs for error handling:**
```bash
python3 scripts/debug_loop_cli.py stf search \
  --category "error_handling" \
  --min-quality 0.9 \
  --limit 10
```

**Store a new validation STF:**
```bash
python3 scripts/debug_loop_cli.py stf store \
  --code examples/validate_input.py \
  --name "Input Validation Pattern" \
  --description "Validates user input with type checking" \
  --category "data_validation" \
  --quality 0.85
```

**Compare model pricing by provider:**
```bash
# Anthropic models
python3 scripts/debug_loop_cli.py model list --provider anthropic

# OpenAI models
python3 scripts/debug_loop_cli.py model list --provider openai

# Google models
python3 scripts/debug_loop_cli.py model list --provider google
```

**Add a new model:**
```bash
python3 scripts/debug_loop_cli.py model add
# Follow interactive prompts...
```

### Inspection and Debugging

**Inspect specific STF:**
```bash
# Get STF ID from list command first
python3 scripts/debug_loop_cli.py stf list | grep "pattern name"

# Then show details
python3 scripts/debug_loop_cli.py stf show <stf_id>
```

**Check model pricing before API calls:**
```bash
python3 scripts/debug_loop_cli.py model show anthropic claude-3-5-sonnet
```

## Output Features

### Beautiful Terminal UI

- **Rich tables** with color-coded values
- **Syntax highlighting** for code display
- **Progress spinners** during database queries
- **Panels and borders** for structured output
- **Icons and badges** for status indicators

### Color Coding

**Quality Scores:**
- 🟢 Green: ≥ 0.9 (excellent)
- 🟡 Yellow: 0.7-0.89 (good)
- 🔴 Red: < 0.7 (needs improvement)

**Success Rates:**
- 🟢 Green: ≥ 80%
- 🟡 Yellow: 50-79%
- 🔴 Red: < 50%

**Status Badges:**
- ✓ Approved (green)
- ⧗ Pending (yellow)
- ✗ Rejected (red)

## Database Schema

### Tables Used

**debug_transform_functions:**
- STF storage with quality metrics
- Usage tracking (count, success rate)
- Approval workflow status

**model_price_catalog:**
- LLM model pricing
- Feature support flags
- Rate limit configuration

See `db/migrations/` for complete schema definitions.

## Troubleshooting

### Connection Errors

**Error: "POSTGRES_PASSWORD not set in environment"**
```bash
# Ensure .env is loaded
source .env

# Verify password is set
echo $POSTGRES_PASSWORD
```

**Error: "Database connection failed"**
```bash
# Check connection details
psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE

# Verify from CLI what's being used
python3 -c "from config import settings; print(f'{settings.postgres_host}:{settings.postgres_port}')"
```

### Import Errors

**Error: "Missing required dependencies"**
```bash
pip install click rich asyncpg
```

**Error: "No module named 'omniclaude'"**
```bash
# Ensure you're in the project root
cd /Volumes/PRO-G40/Code/omniclaude

# Run from project root
python3 scripts/debug_loop_cli.py --help
```

### Query Errors

**No results found:**
- Check if database tables exist: `psql ... -c "\dt debug_*"`
- Verify data is present: `psql ... -c "SELECT COUNT(*) FROM debug_transform_functions"`
- Lower quality threshold: `--min-quality 0.0`

**STF not found by ID:**
- List all STFs first: `stf list`
- Verify ID format is UUID
- Check approval status (search only returns approved by default)

## Architecture

### Components

**CLI Framework:** Click (command groups, options, arguments)
**Terminal UI:** Rich (tables, panels, syntax highlighting, progress)
**Database:** asyncpg (async PostgreSQL adapter)
**Nodes:** ONEX v2.0 compliant Effect nodes

### Data Flow

```
CLI Command
  ↓
AsyncPGProtocol (adapter)
  ↓
NodeDebugSTFStorageEffect / NodeModelPriceCatalogEffect
  ↓
PostgreSQL (omninode_bridge database)
  ↓
Rich formatted output
```

### Database Protocol

The CLI uses an adapter pattern to bridge asyncpg with the ONEX IDatabaseProtocol:

```python
class AsyncPGProtocol:
    """Adapter to make asyncpg compatible with IDatabaseProtocol"""

    async def fetch_one(query, params) -> Dict
    async def fetch_all(query, params) -> List[Dict]
    async def execute_query(query, params) -> Any
```

This allows reuse of existing ONEX nodes without modification.

## Integration

### With Debug Loop Nodes

The CLI directly uses ONEX nodes:
- `NodeDebugSTFStorageEffect` - STF operations
- `NodeModelPriceCatalogEffect` - Model pricing operations
- `NodeSTFHashCompute` - Hash computation

### With Database

Connects to shared `omninode_bridge` database:
- **Host:** 192.168.86.200 (remote server)
- **Port:** 5436 (external access)
- **Database:** omninode_bridge

### With Configuration

Uses type-safe Pydantic Settings:
```python
from config import settings

POSTGRES_HOST = settings.postgres_host
POSTGRES_PASSWORD = settings.get_effective_postgres_password()
```

Fallback to environment variables if config not available.

## Performance

**Connection Pooling:**
- Min connections: 2
- Max connections: 5
- Reuses connections across commands

**Query Optimization:**
- Indexed lookups (stf_id, catalog_id)
- Efficient filtering (WHERE clauses)
- Reasonable default limits (10-20 results)

**UI Responsiveness:**
- Progress spinners during queries
- Async operations (non-blocking)
- Fast table rendering with Rich

## Future Enhancements

### Planned Features

1. **Export commands:**
   - `stf export <stf_id> --format json/yaml`
   - `model export --provider anthropic --format csv`

2. **Batch operations:**
   - `stf import --file stfs.json`
   - `model bulk-update --file pricing.csv`

3. **Analytics:**
   - `stf stats` - Usage trends and quality distribution
   - `model compare` - Side-by-side pricing comparison

4. **Interactive TUI:**
   - Full-screen terminal UI with navigation
   - Real-time updates
   - Filtering and sorting

5. **Configuration:**
   - `--config` flag for custom connection settings
   - Profile support for multiple environments

### Contributing

When adding new commands:

1. Follow Click patterns (groups, commands, options)
2. Use Rich for output formatting
3. Include progress indicators for long operations
4. Add comprehensive help text
5. Update this README with examples

## References

- **ONEX Nodes:** `omniclaude/debug_loop/node_*.py`
- **Database Schema:** `db/migrations/debug_loop_schema.sql`
- **Configuration:** `config/settings.py`
- **Type-Safe Config:** `config/README.md`

## License

Part of OmniClaude project - See main repository LICENSE.
