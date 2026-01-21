# STF Helper - Agent Behavior Integration (Phase 2)

**Status**: ✅ Implemented | ⚠️ Pending `omnibase_core` dependency

## Overview

The STF Helper provides high-level API for agents to interact with the debug loop's Specific Transformation Functions (STFs). This is Phase 2 of the Agent Behavior Integration, building on Phase 1 (manifest context injection).

## Implementation Summary

### Files Created

1. **`stf_helper.py`** (477 lines)
   - `STFHelper` class with 5 main methods
   - Wraps ONEX nodes for agent-friendly access
   - Automatic code normalization and deduplication
   - Comprehensive logging and error handling

2. **`test_stf_helper.py`** (462 lines)
   - 20 unit tests covering all functionality
   - Tests for query, retrieve, store, update operations
   - Edge cases: empty results, not found, deduplication
   - Concurrency tests for parallel agent usage

3. **`test_stf_helper_e2e.py`** (334 lines)
   - 3 end-to-end integration tests
   - Complete debugging workflow simulation
   - Parallel agent STF usage scenario
   - STF learning loop demonstration

### Agent Definitions Updated

1. **`debug-intelligence.yaml`**
   - Added `debug_loop_integration` section (64 lines)
   - STF query triggers and storage criteria
   - Two workflows: `debugging_with_stf` and `stf_contribution`
   - API methods and example usage

2. **`debug-database.yaml`**
   - Added `debug_loop_integration` section (62 lines)
   - Database-specific STF categories
   - Query optimization and connection pooling workflows
   - Example usage for database issues

3. **`debug.yaml`**
   - Added `debug_loop_integration` section (63 lines)
   - General debug categories (build, deployment, config)
   - Investigation and debug log contribution workflows
   - Incident response patterns

## API Reference

### STFHelper Methods

```python
from agents.lib.stf_helper import STFHelper

helper = STFHelper()

# 1. Query STFs by problem criteria
stfs = await helper.query_stfs(
    problem_signature="No module named",
    problem_category="import_error",
    min_quality=0.8,
    limit=10
)

# 2. Retrieve full STF details
stf = await helper.retrieve_stf(stf_id="uuid-here")

# 3. Store new STF
stf_id = await helper.store_stf(
    stf_name="fix_import_error",
    stf_code="import sys\nsys.path.append('.')",
    stf_description="Add current directory to Python path",
    problem_category="import_error",
    problem_signature="No module named",
    quality_score=0.85,
    correlation_id="abc-123"
)

# 4. Update usage metrics
success = await helper.update_stf_usage(stf_id, success=True)

# 5. Get top-ranked STFs for category
top_stfs = await helper.get_top_stfs(
    problem_category="import_error",
    limit=5,
    min_quality=0.8
)
```

## Integration Example

### Complete Debugging Workflow

```python
from agents.lib.stf_helper import STFHelper

async def debug_with_stf_integration(error_message: str, correlation_id: str):
    """Agent debugging workflow with STF integration."""

    helper = STFHelper()

    # Step 1: Detect problem signature
    if "No module named" in error_message:
        problem_signature = "No module named"
        problem_category = "import_error"

        # Step 2: Query existing STFs
        stfs = await helper.query_stfs(
            problem_signature=problem_signature,
            problem_category=problem_category,
            min_quality=0.8
        )

        if stfs:
            # Step 3: Apply top-ranked STF
            top_stf = stfs[0]
            full_stf = await helper.retrieve_stf(top_stf["stf_id"])

            # Execute transformation
            result = apply_transformation(full_stf["stf_code"])

            # Step 4: Track usage
            await helper.update_stf_usage(
                stf_id=top_stf["stf_id"],
                success=result.success
            )

            return result

        # Step 5: If no STF found, solve manually
        solution = manual_debugging()

        # Step 6: Store new STF for future
        if solution.success:
            stf_id = await helper.store_stf(
                stf_name="fix_import_requests",
                stf_code=solution.code,
                stf_description=solution.description,
                problem_category=problem_category,
                problem_signature=problem_signature,
                quality_score=0.85,
                correlation_id=correlation_id
            )
```

## STF Categories by Agent

### Debug Intelligence
- `import_error` - Python import issues
- `syntax_error` - Code syntax problems
- `runtime_error` - Runtime exceptions
- `dependency_error` - Missing dependencies
- `configuration_error` - Config issues

### Debug Database
- `query_optimization` - SQL performance
- `connection_pooling` - Connection management
- `deadlock_resolution` - Deadlock prevention
- `index_optimization` - Index tuning
- `schema_validation` - Schema integrity

### Debug (General)
- `build_failure` - Build/compilation
- `deployment_error` - Deployment issues
- `configuration_issue` - Environment config
- `service_outage` - Availability problems
- `integration_failure` - Service communication

## Known Limitations

### ⚠️ `omnibase_core` Dependency

The ONEX nodes (`NodeDebugSTFStorageEffect`, `NodeSTFHashCompute`) require `omnibase_core` which is not currently installed.

**Current Status**:
- STF Helper implementation complete
- Tests written but fail with ImportError
- Agent definitions updated with integration docs
- Mock database protocol available

**Impact**:
- Tests cannot run until `omnibase_core` is installed
- Integration requires ONEX node dependencies
- Full functionality pending dependency resolution

**Workaround**:
```python
# When omnibase_core is not available:
from agents.lib.stf_helper import STFHelper, NODES_AVAILABLE

if not NODES_AVAILABLE:
    print("Warning: omnibase_core not installed. STF Helper unavailable.")
    # Fallback to manual debugging
else:
    helper = STFHelper()
    # Use STF integration
```

## Installation (When Available)

```bash
# Install omnibase_core (when available)
pip install omnibase_core

# Verify installation
python -c "from agents.lib.stf_helper import STFHelper; print('STF Helper ready')"

# Run tests
pytest agents/lib/test_stf_helper.py -v
pytest agents/lib/test_stf_helper_e2e.py -v -s  # -s shows print statements
```

## Testing

### Unit Tests (20 tests)

```bash
pytest agents/lib/test_stf_helper.py -v

# Specific test categories:
pytest agents/lib/test_stf_helper.py -k "store" -v      # Storage tests
pytest agents/lib/test_stf_helper.py -k "query" -v      # Query tests
pytest agents/lib/test_stf_helper.py -k "retrieve" -v   # Retrieval tests
pytest agents/lib/test_stf_helper.py -k "usage" -v      # Usage tracking tests
```

### End-to-End Tests (3 scenarios)

```bash
pytest agents/lib/test_stf_helper_e2e.py -v -s

# Individual scenarios:
pytest agents/lib/test_stf_helper_e2e.py::test_complete_debugging_workflow -v -s
pytest agents/lib/test_stf_helper_e2e.py::test_parallel_agent_stf_usage -v -s
pytest agents/lib/test_stf_helper_e2e.py::test_stf_learning_loop -v -s
```

## Success Criteria

✅ **Completed**:
- [x] `stf_helper.py` created with 5 methods
- [x] Helper integrates with NodeDebugSTFStorageEffect
- [x] Helper integrates with NodeSTFHashCompute
- [x] Agent definitions updated (3 files)
- [x] Integration examples documented in agent YAML
- [x] Unit tests written (20 tests)
- [x] End-to-end tests written (3 scenarios)

⚠️ **Pending** (requires `omnibase_core`):
- [ ] Tests passing
- [ ] End-to-end workflow validated
- [ ] Agent can query → apply → track STFs

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          Agent Layer                             │
│  (debug-intelligence, debug-database, debug agents)              │
└───────────────────────┬─────────────────────────────────────────┘
                        │
                        │ Uses high-level API
                        ↓
┌─────────────────────────────────────────────────────────────────┐
│                       STFHelper                                  │
│  query_stfs() | retrieve_stf() | store_stf()                    │
│  update_stf_usage() | get_top_stfs()                            │
└───────┬──────────────────────────────┬──────────────────────────┘
        │                              │
        │ Uses ONEX nodes              │ Uses ONEX nodes
        ↓                              ↓
┌──────────────────────┐      ┌──────────────────────┐
│ NodeDebugSTFStorage  │      │  NodeSTFHashCompute  │
│      Effect          │      │                      │
│ - store()            │      │ - normalize_code()   │
│ - retrieve()         │      │ - generate_hash()    │
│ - search()           │      │                      │
│ - update_usage()     │      │                      │
└──────────┬───────────┘      └──────────────────────┘
           │
           │ Uses database protocol
           ↓
┌──────────────────────────────────────────────────────────────────┐
│                    MockDatabaseProtocol                           │
│  (In-memory storage for testing, production uses PostgreSQL)     │
└──────────────────────────────────────────────────────────────────┘
```

## Future Enhancements

### Phase 3: Intelligence Integration
- STF quality scoring with AI models
- Automatic pattern extraction from successful debugging
- Cross-agent STF sharing and ranking

### Phase 4: Production Features
- PostgreSQL backend integration
- STF approval workflow (pending → approved → rejected)
- STF versioning and deprecation
- Usage analytics and effectiveness metrics

### Phase 5: Advanced Features
- Semantic search for similar STFs
- STF composition (combine multiple patterns)
- Context-aware STF recommendations
- Automated STF testing and validation

## Related Documentation

- **Phase 1**: STF manifest context injection (already implemented)
- **ONEX Compliance**: See debug loop contracts in `omniclaude/debug_loop/`
- **Database Schema**: `debug_transform_functions` table structure
- **Agent Framework**: `agents/polymorphic-agent.md`

## Troubleshooting

### ImportError: No module named 'omnibase_core'

**Cause**: ONEX core package not installed
**Solution**: Wait for `omnibase_core` package availability or install locally

### Tests fail with ImportError

**Expected**: This is a known issue pending `omnibase_core`
**Status**: Implementation complete, awaiting dependency

### Helper initialization fails

**Check**:
```python
from agents.lib.stf_helper import NODES_AVAILABLE
print(f"Nodes available: {NODES_AVAILABLE}")
```

If `False`, omnibase_core is not installed.

## Contributing

When `omnibase_core` becomes available:

1. Install dependencies:
   ```bash
   pip install omnibase_core
   ```

2. Run tests to verify:
   ```bash
   pytest agents/lib/test_stf_helper.py -v
   pytest agents/lib/test_stf_helper_e2e.py -v -s
   ```

3. Update this README with test results

4. Remove "Pending dependency" warnings

## Contact

For questions about STF Helper implementation or integration, see:
- Agent definitions: `agents/definitions/debug-*.yaml`
- ONEX nodes: `omniclaude/debug_loop/node_*.py`
- Database schema: `omniclaude/debug_loop/mock_database_protocol.py`

---

**Last Updated**: 2025-11-11
**Phase**: 2 (Agent Behavior Integration)
**Status**: ✅ Implemented | ⚠️ Pending `omnibase_core` dependency
