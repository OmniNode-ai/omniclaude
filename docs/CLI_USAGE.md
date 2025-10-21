# CLI Usage Guide - ONEX Node Generation

**Version**: 1.0.0
**Phase**: Phase 1 (POC)
**Last Updated**: 2025-10-21

---

## Overview

The ONEX Node Generation CLI (`generate_node.py`) provides a command-line interface for autonomous code generation from natural language prompts.

**Key Features**:
- Natural language → ONEX node code
- 6-stage generation pipeline with 14 validation gates
- Interactive and direct modes
- Real-time progress feedback
- Comprehensive error reporting
- ~40 second generation time

---

## Installation

### Prerequisites

- Python 3.11+
- Poetry package manager
- `omnibase_core` package installed

### Setup

```bash
# Clone repository
cd /path/to/omniclaude

# Install dependencies
poetry install

# Verify installation
poetry run python cli/generate_node.py --help
```

---

## Quick Start

### Basic Usage

```bash
# Generate node from prompt
poetry run python cli/generate_node.py "Create EFFECT node for database writes"
```

**Expected Output**:
```
╔════════════════════════════════════════════════════════════════╗
║                 ONEX Node Generation CLI                       ║
║                 Autonomous Code Generation POC                 ║
╚════════════════════════════════════════════════════════════════╝

🚀 Generating node from prompt...
📝 Prompt: Create EFFECT node for database writes
📁 Output: ./output

[Pipeline execution stages...]

════════════════════════════════════════════════════════════════
✅ SUCCESS - Node generation completed!
════════════════════════════════════════════════════════════════

Pipeline Result: SUCCESS
Duration: 38.45s
Stages: 6
Node Type: EFFECT
Service: database_writer
Files Generated: 11

📁 Output directory: /path/to/node_infrastructure_database_writer_effect
📄 Generated 11 files:
   - node.py
   - model_database_writer_input.py
   - model_database_writer_output.py
   - contract.yaml
   - node.manifest.yaml
   ... and 6 more
```

---

## Command-Line Options

### Positional Arguments

```bash
# Direct prompt (positional argument)
poetry run python cli/generate_node.py "Your prompt here"
```

### Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--interactive` | `-i` | Interactive mode with guided prompts | Off |
| `--prompt` | `-p` | Prompt (alternative to positional) | None |
| `--output` | `-o` | Output directory for generated files | `./output` |
| `--debug` | `-d` | Enable debug logging | Off |
| `--no-compile` | | Skip compilation testing (Stage 6) | Off |
| `--help` | `-h` | Show help message | - |

---

## Usage Modes

### 1. Direct Mode

Provide prompt directly via command line:

```bash
# Using positional argument
poetry run python cli/generate_node.py "Create EFFECT node for Redis cache operations"

# Using --prompt flag
poetry run python cli/generate_node.py --prompt "Create EFFECT node for Redis cache operations"

# With custom output directory
poetry run python cli/generate_node.py \
    --prompt "Create EFFECT node for API calls" \
    --output ./generated_nodes
```

---

### 2. Interactive Mode

Guided prompt entry with confirmation:

```bash
poetry run python cli/generate_node.py --interactive
```

**Interactive Session**:
```
╔════════════════════════════════════════════════════════════════╗
║                 ONEX Node Generation CLI                       ║
║                 Autonomous Code Generation POC                 ║
╚════════════════════════════════════════════════════════════════╝

📝 Interactive Node Generation
════════════════════════════════════════════════════════════════

Describe the node you want to generate:
(Example: Create EFFECT node for PostgreSQL database write operations)

Prompt: Create EFFECT node for sending emails via SMTP

Output directory (default: ./output):
Directory: ./nodes/email

────────────────────────────────────────────────────────────────
Configuration:
  Prompt: Create EFFECT node for sending emails via SMTP
  Output: ./nodes/email
────────────────────────────────────────────────────────────────

Proceed with generation? [Y/n]: y

🚀 Starting generation...
[Pipeline execution...]
```

---

## Examples

### Example 1: PostgreSQL Database Writer

```bash
poetry run python cli/generate_node.py \
    "Create EFFECT node for PostgreSQL database write operations" \
    --output ./nodes/postgres
```

**Generated Files**:
```
nodes/postgres/node_infrastructure_postgres_writer_effect/
├── v1_0_0/
│   ├── node.py                                    # Main node class
│   ├── models/
│   │   ├── model_postgres_writer_input.py         # Input model
│   │   └── model_postgres_writer_output.py        # Output model
│   ├── enums/
│   │   └── enum_postgres_operation.py             # Operation types
│   └── contract.yaml                              # Node contract
├── node.manifest.yaml                             # Manifest
└── README.md                                      # Documentation
```

---

### Example 2: Redis Cache Operations

```bash
poetry run python cli/generate_node.py \
    "Create EFFECT node for Redis cache operations including get, set, delete" \
    --output ./nodes/cache
```

**Generated Node**:
- **Node Type**: EFFECT
- **Service Name**: `redis_cache`
- **Domain**: `infrastructure`
- **Operations**: get, set, delete

---

### Example 3: HTTP API Client

```bash
poetry run python cli/generate_node.py \
    "Create EFFECT node for making HTTP API calls with retry logic" \
    --output ./nodes/api
```

**Generated Node**:
- **Node Type**: EFFECT
- **Service Name**: `http_client`
- **Domain**: `api`
- **Features**: Retry logic, timeout handling, error responses

---

### Example 4: Email Sender

```bash
poetry run python cli/generate_node.py \
    --prompt "Create EFFECT node for sending emails via SMTP with attachments" \
    --output ./nodes/email \
    --debug
```

**Debug Mode Output**:
- Detailed logging for each stage
- Validation gate execution details
- Template rendering debug info
- Import resolution diagnostics

---

## Understanding Pipeline Stages

The CLI executes a 6-stage pipeline:

### Stage 1: Prompt Parsing (5s)
- Parse natural language prompt
- Extract node type, service name, domain
- Analyze requirements
- **Validation Gates**: G7 (Prompt Completeness), G8 (Context Completeness)

### Stage 2: Pre-Generation Validation (2s)
- Validate node type
- Check service name format
- Verify critical imports exist
- Confirm templates available
- **Validation Gates**: G1-G6 (All blocking)

### Stage 3: Code Generation (10-15s)
- Render templates with context
- Generate node class
- Generate models (input/output)
- Generate enums
- Generate contract/manifest

### Stage 4: Post-Generation Validation (5s)
- Python syntax checking (AST parsing)
- ONEX naming convention verification
- Import resolution check
- Pydantic model structure validation
- **Validation Gates**: G9-G12 (All blocking)

### Stage 5: File Writing (3s)
- Write all generated files to disk
- Create directory structure
- Track written files for rollback

### Stage 6: Compilation Testing (10s) - Optional
- MyPy type checking
- Import testing
- **Validation Gates**: G13-G14 (Both warnings)

**Total**: ~40 seconds for successful generation

---

## Troubleshooting

### Common Errors

#### 1. Missing Dependencies

**Error**:
```
❌ FAILED - Node generation failed

Failed validation gates (1):
  ❌ G4 - Critical Imports Exist
     Critical imports failed: omnibase_core.nodes.node_effect.NodeEffect not found
```

**Solution**:
```bash
# Install omnibase_core
poetry install omnibase_core

# Or update dependencies
poetry update
```

---

#### 2. Invalid Prompt

**Error**:
```
❌ FAILED - Node generation failed

Failed validation gates (1):
  ❌ G1 - Prompt Completeness
     Missing required fields: node_type, service_name
```

**Solution**:
- Provide more detailed prompt
- Specify node type explicitly: "Create EFFECT node for..."
- Include service description

**Good Prompts**:
- ✅ "Create EFFECT node for PostgreSQL database write operations"
- ✅ "Create EFFECT node for Redis cache with get/set/delete operations"
- ✅ "Create EFFECT node for sending HTTP requests to external APIs"

**Bad Prompts**:
- ❌ "database" (too vague)
- ❌ "Create a node" (missing type and service)
- ❌ "EFFECT" (missing service description)

---

#### 3. Output Directory Not Writable

**Error**:
```
❌ Error: Output directory not writable: Permission denied
```

**Solution**:
```bash
# Check permissions
ls -la /path/to/output

# Create directory with correct permissions
mkdir -p ./output
chmod 755 ./output

# Or specify different directory
poetry run python cli/generate_node.py \
    --prompt "..." \
    --output ~/nodes
```

---

#### 4. Syntax Errors in Generated Code

**Error**:
```
❌ FAILED - Node generation failed

Failed validation gates (1):
  ❌ G9 - Python Syntax Valid
     Syntax error in node.py line 45: invalid syntax
```

**Solution**:
- Report bug with prompt and error details
- Try simpler prompt
- Check template engine logs in debug mode

---

### Debug Mode

Enable debug mode for detailed troubleshooting:

```bash
poetry run python cli/generate_node.py \
    --prompt "Your prompt" \
    --debug
```

**Debug Output Includes**:
- Detailed stage execution logs
- Validation gate execution times
- Template context data
- Import resolution details
- AST parsing diagnostics

---

## Output Structure

Generated nodes follow ONEX conventions:

```
node_<domain>_<service_name>_<type>/
├── v1_0_0/                           # Versioned implementation
│   ├── node.py                       # Main node class (Node<Name><Type>)
│   ├── models/                       # Pydantic models
│   │   ├── model_<service>_input.py
│   │   └── model_<service>_output.py
│   ├── enums/                        # Enumerations
│   │   └── enum_<name>.py
│   ├── subcontracts/                 # Subcontracts (if applicable)
│   └── contract.yaml                 # Node contract specification
├── node.manifest.yaml                # Node manifest
└── README.md                         # Auto-generated documentation
```

---

## Advanced Usage

### Skip Compilation Testing

Skip Stage 6 (compilation testing) for faster iteration:

```bash
poetry run python cli/generate_node.py \
    --prompt "Create EFFECT node for database writes" \
    --no-compile
```

**Use Case**: Rapid prototyping, testing prompt variations

---

### Custom Output Directory

Organize nodes by domain or project:

```bash
# Infrastructure nodes
poetry run python cli/generate_node.py \
    --prompt "Create EFFECT node for Postgres" \
    --output ./nodes/infrastructure

# API nodes
poetry run python cli/generate_node.py \
    --prompt "Create EFFECT node for HTTP client" \
    --output ./nodes/api

# Business logic nodes
poetry run python cli/generate_node.py \
    --prompt "Create COMPUTE node for pricing calculation" \
    --output ./nodes/business
```

---

### Batch Generation

Generate multiple nodes using a script:

```bash
#!/bin/bash
# generate_nodes.sh

PROMPTS=(
    "Create EFFECT node for PostgreSQL database writes"
    "Create EFFECT node for Redis cache operations"
    "Create EFFECT node for S3 file upload"
)

for prompt in "${PROMPTS[@]}"; do
    echo "Generating: $prompt"
    poetry run python cli/generate_node.py \
        --prompt "$prompt" \
        --output ./nodes/infrastructure
done
```

---

## Performance Tips

### 1. Disable Compilation Testing for Speed

```bash
# ~30 seconds (no compilation)
poetry run python cli/generate_node.py --prompt "..." --no-compile
```

### 2. Pre-warm Templates

Templates are cached after first use. Run multiple generations in succession for better performance.

### 3. Use Specific Prompts

More specific prompts = faster parsing and validation:
- ✅ "Create EFFECT node for PostgreSQL writes with connection pooling"
- ❌ "database node" (requires more inference)

---

## Best Practices

### 1. Prompt Writing

**Be Specific**:
```bash
# Good
"Create EFFECT node for PostgreSQL database write operations with transaction support"

# Better
"Create EFFECT node for PostgreSQL writes (INSERT, UPDATE, DELETE) with connection pooling and transaction rollback"
```

### 2. Output Organization

Organize nodes by domain:
```
nodes/
├── infrastructure/
│   ├── node_postgres_writer_effect/
│   ├── node_redis_cache_effect/
│   └── node_s3_uploader_effect/
├── api/
│   ├── node_http_client_effect/
│   └── node_graphql_client_effect/
└── business/
    ├── node_pricing_calculator_compute/
    └── node_order_validator_compute/
```

### 3. Validation

Always review generated code:
1. Check node class naming (suffix-based: `Node<Name>Effect`)
2. Verify imports use correct paths
3. Review Pydantic models for completeness
4. Test generated node in your application

---

## Integration with Projects

### Using Generated Nodes

```python
# Import generated node
from nodes.infrastructure.node_infrastructure_postgres_writer_effect.v1_0_0.node import (
    NodePostgresWriterEffect
)
from nodes.infrastructure.node_infrastructure_postgres_writer_effect.v1_0_0.models.model_postgres_writer_input import (
    ModelPostgresWriterInput
)

# Instantiate node
node = NodePostgresWriterEffect()

# Create input
input_data = ModelPostgresWriterInput(
    operation="INSERT",
    table="users",
    data={"name": "John", "email": "john@example.com"}
)

# Execute
result = await node.execute_effect(input_data)
```

---

## Frequently Asked Questions

### Q: What node types are supported in Phase 1?

**A**: Currently only **EFFECT** nodes are supported in POC Phase 1. Future phases will add COMPUTE, REDUCER, and ORCHESTRATOR nodes.

---

### Q: How long does generation take?

**A**: Approximately 40 seconds for a complete generation with all validation gates and compilation testing. Use `--no-compile` to reduce to ~30 seconds.

---

### Q: Can I customize the templates?

**A**: Yes, templates are located in `agents/lib/templates/`. Modifications will affect all generated nodes.

---

### Q: What happens if generation fails?

**A**: The pipeline automatically rolls back any partially written files. You can retry with a modified prompt or fix the underlying issue (e.g., install missing dependencies).

---

### Q: Can I run generation in CI/CD?

**A**: Yes! The CLI returns exit code 0 for success, 1 for failure. Example:

```bash
# CI/CD script
poetry run python cli/generate_node.py \
    --prompt "Create EFFECT node for API client" \
    --output ./generated || exit 1
```

---

## Getting Help

### Command-Line Help

```bash
poetry run python cli/generate_node.py --help
```

### Debug Mode

```bash
poetry run python cli/generate_node.py --prompt "..." --debug
```

### Report Issues

Include:
1. Full command used
2. Complete error output
3. Debug logs (with `--debug` flag)
4. Environment details (Python version, OS)

---

## References

- [Generation Pipeline Architecture](./POC_PIPELINE_ARCHITECTURE.md)
- [Phase 4 Event Bus Migration](./CLI_EVENT_BUS_MIGRATION.md)
- [ONEX Architecture Patterns](../OMNIBASE_CORE_NODE_PARADIGM.md)
- [Pipeline Events Schema](../schemas/pipeline_events.yaml)

---

**Document Status**: Complete
**Ready for Use**: Yes
**Phase**: Phase 1 (POC)
**Last Updated**: 2025-10-21
