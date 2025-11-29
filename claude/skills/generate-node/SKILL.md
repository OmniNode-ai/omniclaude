---
name: generate-node
description: Generate ONEX nodes via automated code generation with ContractInferencer and LLM-powered business logic
---

# Generate ONEX Node

Fully automated ONEX node generation using the omninode_bridge codegen system. Generates complete, production-ready nodes with contracts, infrastructure code, business logic, and tests.

## 🚨 CRITICAL: ALWAYS DISPATCH TO POLYMORPHIC AGENT

**DO NOT run generation scripts directly.** When this skill is invoked, you MUST dispatch to a polymorphic-agent.

### ❌ WRONG - Running scripts directly:
```
Bash(~/.claude/skills/generate-node/generate "Create PostgreSQL CRUD Effect")
Bash(~/.claude/skills/generate-node/regenerate src/nodes/my_node)
```

### ✅ CORRECT - Dispatch to polymorphic-agent:
```
Task(
  subagent_type="polymorphic-agent",
  description="Generate PostgreSQL CRUD Effect node",
  prompt="Generate an ONEX node with the following requirements:
    Description: Create a PostgreSQL CRUD Effect node for user management
    Node Type: Effect

    Use the generate-node skill:
    ~/.claude/skills/generate-node/generate 'Create PostgreSQL CRUD Effect node for user management with async operations'

    Options available:
    - --output-dir ./generated_nodes (default)
    - --node-type effect|compute|reducer|orchestrator
    - --enable-intelligence (default)
    - --enable-quorum (multi-model validation)

    After generation:
    1. Verify the generated contract YAML
    2. Check the business logic implementation
    3. Run the generated tests
    4. Report any issues found"
)
```

**WHY**: Polymorphic agents have full ONEX capabilities, intelligence integration, quality gates, and proper observability. Running scripts directly bypasses all of this.

## What It Does

The codegen system provides **100% automated node generation** through an event-driven workflow:

1. **ContractInferencer** - Analyzes requirements and generates ONEX v2.0 contract YAML (5-10s with LLM)
2. **HybridStrategy** - Generates infrastructure code from templates (~50ms with Jinja2)
3. **BusinessLogicGenerator** - Generates complete business logic (5-15s with LLM)
4. **Validation** - Runs comprehensive tests and quality checks (~100ms)

**Total Time**: 10-25 seconds per node, **ZERO manual work** ✨

## When to Use

- Creating new ONEX Effect nodes (API interactions, external systems)
- Creating new ONEX Compute nodes (data processing, business logic)
- Creating new ONEX Reducer nodes (state management, aggregation)
- Creating new ONEX Orchestrator nodes (workflow coordination)
- Regenerating nodes with updated patterns and best practices

## Usage

### Generate New Node (From Prompt)

Use the Bash tool to execute:

```bash
~/.claude/skills/generate-node/generate "<PROMPT>" [OPTIONS]
```

### Regenerate Existing Node (From Code)

To regenerate an existing node (useful for applying updated patterns or refactoring):

```bash
~/.claude/skills/generate-node/regenerate <NODE_DIR> [OPTIONS]
```

The regenerate script intelligently extracts a generation prompt by:
1. **First**, checking for README.md and extracting description
2. **If no README**, analyzing all Python code files with Z.ai to extract purpose and functionality
3. **Then**, calling the generate skill with the extracted prompt

### Arguments

- `PROMPT` - Natural language description of the node (required)
- `--output-dir` - Output directory for generated files (default: ./generated_nodes)
- `--node-type` - Node type hint: effect|orchestrator|reducer|compute (optional, auto-inferred)
- `--interactive` - Enable interactive checkpoints for validation
- `--enable-intelligence` - Use RAG intelligence gathering (enabled by default)
- `--disable-intelligence` - Disable RAG intelligence gathering
- `--enable-quorum` - Use AI quorum validation (multi-model consensus)
- `--timeout` - Timeout in seconds (default: 300 = 5 minutes)

### Examples

**Generate New Nodes:**

```bash
# Basic usage - generate PostgreSQL CRUD Effect
~/.claude/skills/generate-node/generate "Create PostgreSQL CRUD Effect node"

# With custom output directory
~/.claude/skills/generate-node/generate "Create ML inference Orchestrator" --output-dir ./my_nodes

# With node type hint and interactive mode
~/.claude/skills/generate-node/generate "Create metrics aggregation Reducer" --node-type reducer --interactive

# With intelligence disabled (faster, less context)
~/.claude/skills/generate-node/generate "Create simple logger Effect" --disable-intelligence

# With AI quorum validation (multi-model consensus)
~/.claude/skills/generate-node/generate "Create payment processing Orchestrator" --enable-quorum
```

**Regenerate Existing Nodes:**

```bash
# Regenerate node from existing code (extracts prompt automatically)
~/.claude/skills/generate-node/regenerate src/omninode_bridge/nodes/llm_effect/v1_0_0/llm_effect_llm

# Regenerate with custom output directory
~/.claude/skills/generate-node/regenerate nodes/my_node --output-dir ./regenerated

# Regenerate with interactive mode
~/.claude/skills/generate-node/regenerate ../other_repo/nodes/custom_node --interactive

# Regenerate from node with README.md (fast - no Z.ai call)
~/.claude/skills/generate-node/regenerate nodes/well_documented_node

# Regenerate from node without README (uses Z.ai code analysis)
~/.claude/skills/generate-node/regenerate nodes/legacy_node --enable-intelligence
```

## Output

The skill generates a complete ONEX node with:

```
generated_nodes/
└── <node_name>/
    ├── contract.yaml           # ONEX v2.0 contract specification
    ├── node.py                 # Main node implementation
    ├── models/                 # Pydantic models
    │   ├── model_input.py
    │   ├── model_output.py
    │   └── model_intent.py
    ├── __init__.py            # Package initialization
    ├── README.md              # Node documentation
    └── tests/                 # Unit tests (optional)
        └── test_node.py
```

### Success Output Example

```
🚀 Generating ONEX node...
   Correlation ID: 550e8400-e29b-41d4-a716-446655440000
   Prompt: Create PostgreSQL CRUD Effect node
   Output: ./generated_nodes

[Progress updates via Kafka events...]

✅ Generation complete!
   Duration: 18.3s
   Quality Score: 0.95
   Files Generated: 8

   Generated files:
   - ./generated_nodes/postgresql_crud_effect/contract.yaml
   - ./generated_nodes/postgresql_crud_effect/node.py
   - ./generated_nodes/postgresql_crud_effect/models/model_input.py
   - ./generated_nodes/postgresql_crud_effect/models/model_output.py
   - ./generated_nodes/postgresql_crud_effect/models/model_intent.py
   - ./generated_nodes/postgresql_crud_effect/__init__.py
   - ./generated_nodes/postgresql_crud_effect/README.md
   - ./generated_nodes/postgresql_crud_effect/tests/test_node.py
```

## Architecture

The codegen uses **event-driven orchestration** via Kafka:

```
CLI (omninode-generate)
    ↓ (publishes event)
Kafka Topic: node.generation.requested
    ↓ (consumed by)
Code Generation Workflow
    ├─ ContractInferencer (AST + LLM inference)
    ├─ HybridStrategy (Jinja2 templates)
    ├─ BusinessLogicGenerator (LLM code generation)
    └─ Validation (pytest + quality checks)
    ↓ (publishes progress events)
Kafka Progress Topics
    ↓ (consumed by)
CLI Progress Display
    ↓
Generated Files
```

## Performance Metrics

| Component              | Time   | Automation Level       |
|------------------------|--------|------------------------|
| ContractInferencer     | 5-10s  | 100% (LLM-based)       |
| Jinja2 Templates       | ~50ms  | 100% (Template-based)  |
| BusinessLogicGenerator | 5-15s  | 100% (LLM-based)       |
| Validation             | ~100ms | 100% (Automated tests) |
| **TOTAL**              | 10-25s | **100% AUTOMATED**     |

**Manual work eliminated**: 45 min → 0 min per node = **100% time savings** 🎯

## Z.ai Integration (Regenerate Mode)

When regenerating nodes without README.md files, the skill uses **Z.ai LLM API** to analyze code and extract generation prompts:

**How It Works:**
1. Collects all Python files from the node directory
2. Sends code to Z.ai with a system prompt asking to analyze the node
3. Z.ai extracts: node type, functionality, operations, integrations, features
4. Returns a concise 1-2 sentence generation prompt
5. Uses extracted prompt to regenerate the node with updated patterns

**API Configuration:**
- **Endpoint**: `https://api.z.ai/api/anthropic` (Anthropic-compatible)
- **Model**: `glm-4-flash` (fast, cost-effective) - configurable via `ZAI_MODEL` env var
- **API Key**: Set `ZAI_API_KEY` in `.env` file
- **Cost**: ~$0.01 per regeneration (typical node analysis)

**Performance:**
- **With README**: <1s (no API call needed)
- **Without README**: 3-5s (includes Z.ai API call for code analysis)
- **Accuracy**: 95%+ prompt extraction quality

**Fallback Strategy:**
1. Try README.md extraction first (fastest)
2. If no README or extraction fails → Z.ai code analysis
3. If Z.ai fails → error with helpful message

## Prerequisites

**Required Infrastructure** (running on 192.168.86.200):
- PostgreSQL (port 5436) - For workflow state persistence
- Kafka/Redpanda (port 9092/29092) - For event-driven orchestration
- Consul (port 28500) - For service discovery

**Environment Variables** (in omninode_bridge/.env):
```bash
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<set_in_env>

KAFKA_BOOTSTRAP_SERVERS=omninode-bridge-redpanda:9092  # Docker services
# OR
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:29092           # Host scripts

ZAI_API_KEY=<your_key>     # For LLM-powered generation and code analysis
ZAI_ENDPOINT=https://api.z.ai/api/anthropic  # Optional, defaults to Z.ai
ZAI_MODEL=glm-4-flash      # Optional, defaults to glm-4-flash
```

**For Regenerate Mode** (analyzing existing code):
```bash
# Required
ZAI_API_KEY=<your_key>     # Z.ai API key for code analysis

# Optional
ZAI_ENDPOINT=https://api.z.ai/api/anthropic  # Override endpoint
ZAI_MODEL=glm-4-flash      # Override model (glm-4-flash, glm-4-plus, etc.)
```

**Working Directory**: Must be run from within the `omninode_bridge` repository.

## Error Handling

The skill provides comprehensive error handling:

- **Empty prompt**: Returns error with helpful message
- **Invalid output directory**: Validates path and prevents path traversal
- **Timeout exceeded**: Cancels workflow and reports partial results
- **Kafka connection failure**: Provides diagnostic information
- **Generation failure**: Returns detailed error with correlation ID for debugging

## Common Pitfalls Avoided

❌ **Manual contract writing** - ContractInferencer does it automatically
❌ **Template boilerplate** - HybridStrategy generates infrastructure
❌ **Manual business logic** - BusinessLogicGenerator writes working code
❌ **Missing tests** - Validation ensures quality

✅ **100% automated** - From prompt to production-ready code
✅ **Event-driven** - Real-time progress tracking via Kafka
✅ **High quality** - LLM-powered with validation and quality checks
✅ **Fast** - 10-25s total generation time

## Skills Location

**Claude Code Access**: `~/.claude/skills/generate-node/`
**Executable**: `~/.claude/skills/generate-node/generate`
**Repository**: `omninode_bridge` (see sibling directory)

## Integration with Other Tools

This skill integrates with:
- **ContractInferencer** - AST parsing and contract generation
- **HybridStrategy** - Template-based code generation
- **BusinessLogicGenerator** - LLM-powered business logic
- **Kafka Event Bus** - Real-time progress tracking
- **PostgreSQL** - Workflow state persistence
- **Archon Intelligence** - RAG-enhanced context gathering (optional)

## Node Types Reference

**Effect Nodes**:
- External API interactions (REST, GraphQL, gRPC)
- Database operations (CRUD, queries)
- Message queue publishing/consuming
- File system operations
- Third-party service integrations

**Compute Nodes**:
- Data transformations and processing
- Business logic execution
- Algorithm implementation
- Calculations and analytics
- Data validation and sanitization

**Reducer Nodes**:
- State aggregation and management
- Data persistence and caching
- Stream reduction and windowing
- Metrics collection and rollup
- Event sourcing and replay

**Orchestrator Nodes**:
- Multi-step workflow coordination
- Service composition and routing
- Saga pattern implementation
- Distributed transaction management
- Event-driven choreography

## Debugging

If generation fails or produces unexpected results:

```bash
# Check Kafka connection
curl http://192.168.86.200:8080  # Redpanda Console

# Check PostgreSQL connection
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge

# View generation events in Kafka
kcat -C -b 192.168.86.200:29092 -t node.generation.requested

# Check correlation ID in logs
grep "<correlation_id>" /path/to/logs

# Run with shorter timeout for debugging
~/.claude/skills/generate-node/generate "Test node" --timeout 60
```

## Advanced Usage

### Batch Generation

Generate multiple nodes programmatically:

```bash
# Generate multiple related nodes
for node_desc in "User CRUD Effect" "Auth Middleware Effect" "Session Reducer"; do
    ~/.claude/skills/generate-node/generate "$node_desc" --output-dir ./my_service_nodes
done
```

### Custom Workflow Integration

```python
# Python integration example
import subprocess
import json

def generate_node(prompt: str, output_dir: str = "./generated_nodes"):
    result = subprocess.run(
        ["~/.claude/skills/generate-node/generate", prompt, "--output-dir", output_dir],
        capture_output=True,
        text=True
    )
    return result.returncode == 0
```

## Quality Assurance

**Generated nodes include**:
- ✅ ONEX v2.0 compliant contracts
- ✅ Type-safe Pydantic models
- ✅ Comprehensive error handling
- ✅ Logging and observability
- ✅ Circuit breaker patterns (where applicable)
- ✅ Retry logic (where applicable)
- ✅ Input validation
- ✅ Documentation (README, docstrings)
- ✅ Unit tests (optional)

**Quality Score**: 0.0-1.0 based on:
- Contract completeness and correctness
- Code quality and type safety
- Test coverage
- Documentation quality
- ONEX compliance

## See Also

- **ContractInferencer Documentation**: `docs/codegen/CONTRACT_INFERENCER.md`
- **HybridStrategy Guide**: `docs/codegen/HYBRID_STRATEGY.md`
- **ONEX v2.0 Specification**: `docs/architecture/ONEX_V2_SPECIFICATION.md`
- **Node Development Guide**: `docs/guides/NODE_DEVELOPMENT_GUIDE.md`
