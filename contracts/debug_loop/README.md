# Debug Loop ONEX Contracts

This directory contains ONEX v2.0 contracts for all 11 debug intelligence nodes.

## Contract Status

| # | Contract File | Node Type | Status |
|---|---------------|-----------|--------|
| 1 | debug_stf_storage_effect.yaml | Effect | ✅ Complete |
| 2 | model_price_catalog_effect.yaml | Effect | 📝 TODO |
| 3 | debug_stf_extractor_compute.yaml | Compute | 📝 TODO |
| 4 | stf_quality_compute.yaml | Compute | ✅ Complete |
| 5 | stf_matcher_compute.yaml | Compute | 📝 TODO |
| 6 | stf_hash_compute.yaml | Compute | 📝 TODO |
| 7 | error_pattern_extractor_compute.yaml | Compute | 📝 TODO |
| 8 | cost_tracker_compute.yaml | Compute | 📝 TODO |
| 9 | error_success_mapping_reducer.yaml | Reducer | 📝 TODO |
| 10 | golden_state_manager_reducer.yaml | Reducer | 📝 TODO |
| 11 | debug_loop_orchestrator.yaml | Orchestrator | ✅ Complete |

## Usage

These contracts are used by the node generator to create type-safe ONEX-compliant nodes:

```bash
poetry run python cli/generate_node.py \
  --contract contracts/debug_loop/debug_stf_storage_effect.yaml \
  --output generated_nodes/debug_loop
```

## Contract Structure

Each contract includes:
- Input/output schemas (type-safe)
- Error handling definitions
- Performance targets
- ONEX compliance requirements
- Dependencies (omnibase_core, omnibase_spi)
- Testing requirements with mocks

## Next Steps

Days 3-5 (in progress): Complete all 11 contracts
Week 2: Generate nodes from contracts
Week 3-4: Integration with mocks + testing
