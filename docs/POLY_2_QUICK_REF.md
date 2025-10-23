# Poly 2: Pattern Matcher & Applicator - Quick Reference

**Status**: ✅ Delivered | **Tests**: 25/26 passing | **Performance**: Exceeds all targets

---

## Quick Start

### Import & Initialize

```python
from agents.lib.code_refiner import ProductionPatternMatcher, CodeRefiner

# Pattern matching
matcher = ProductionPatternMatcher()

# AI refinement (requires GEMINI_API_KEY)
refiner = CodeRefiner()
```

### Find Production Patterns

```python
# Find similar nodes by type and domain
nodes = matcher.find_similar_nodes(
    node_type="effect",     # effect, compute, reducer, orchestrator
    domain="database",      # database, api, vector_search, etc.
    limit=3                 # Max examples to return
)

# Extract patterns from production code
pattern = matcher.extract_patterns(nodes[0])
print(f"Confidence: {pattern.confidence:.2f}")
print(f"Imports: {len(pattern.imports)}")
print(f"Transactions: {pattern.transaction_management}")
```

### Refine Generated Code

```python
# Apply production patterns to generated code
refined_code = await refiner.refine_code(
    code=generated_code,
    file_type="node",
    refinement_context={
        "node_type": "effect",
        "domain": "database",
        "requirements": {
            "transaction_management": True,
            "metrics_tracking": True,
        }
    }
)
```

---

## Pattern Types Extracted

1. **Imports** - Standard library, third-party, local imports
2. **Class Structure** - Inheritance and base classes
3. **Method Signatures** - Type hints, async methods
4. **Error Handling** - Try-except patterns, logging
5. **Transaction Management** - Effect node transactions
6. **Metrics Tracking** - Performance measurement
7. **Documentation** - Docstrings and comments
8. **Confidence Score** - 0.0-1.0 based on completeness

---

## Best Production Examples

### Effect Nodes (16 total)
- `node_qdrant_search_effect.py` - Vector search (100% confidence)
- `node_qdrant_vector_index_effect.py` - Batch indexing
- `node_pattern_storage_effect.py` - Database persistence

### Compute Nodes (12 total)
- `node_intent_classifier_compute.py` - Intent classification (95%)
- `node_keyword_extractor_compute.py` - Keyword extraction
- `node_onex_validator_compute.py` - ONEX validation

### Reducer Nodes (1 total)
- `node_usage_analytics_reducer.py` - Analytics aggregation (100%)

### Orchestrator Nodes (5 total)
- `node_pattern_assembler_orchestrator.py` - Pattern assembly (95%)
- `node_quality_gate_orchestrator.py` - Quality validation

---

## Performance

| Operation | Achieved |
|-----------|----------|
| Find similar nodes (3) | ~5ms |
| Extract patterns (first) | ~1-2ms |
| Extract patterns (cached) | ~0.002ms |
| Cache speedup | **500x** |
| AI refinement | ~3-5s |

---

## Critical Requirements Applied

1. ✅ Pydantic v2 `ConfigDict` (not `class Config`)
2. ✅ Full type hints on all parameters
3. ✅ Comprehensive docstrings
4. ✅ Import ordering (stdlib → third-party → local)
5. ✅ Error handling with context logging
6. ✅ Transaction management (Effect nodes)
7. ✅ Metrics tracking (`_record_metric`)
8. ✅ ONEX naming (`Node<Name><Type>`)

---

## Testing

```bash
# Run all tests
python -m pytest agents/tests/test_code_refiner.py -v

# Run demo
python -m agents.lib.demo_code_refiner

# With API key for AI refinement
GEMINI_API_KEY=your_key python -m agents.lib.demo_code_refiner
```

**Results**: 25/26 tests passing (1 skipped - integration test)

---

## Files

- `agents/lib/code_refiner.py` - Core implementation (850 lines)
- `agents/tests/test_code_refiner.py` - Tests (500+ lines)
- `agents/lib/demo_code_refiner.py` - Demo (350+ lines)
- `docs/CODE_REFINER_GUIDE.md` - Full guide (400+ lines)
- `POLY_2_DELIVERY_SUMMARY.md` - Delivery summary

---

## Error Handling

**Graceful degradation** at all levels:

1. No API key → Returns original code with warning
2. No patterns found → Returns original code with info
3. AI refinement fails → Returns original code with error
4. Code doesn't compile → Returns original code with error
5. Production codebase missing → Uses catalog examples

---

## Environment Setup

```bash
# Required for AI refinement
export GEMINI_API_KEY=your_gemini_api_key

# Optional: Custom production paths
export OMNIARCHON_PATH=/path/to/omniarchon
export OMNINODE_BRIDGE_PATH=/path/to/omninode_bridge
```

---

## Integration Example

```python
# In generation pipeline Stage 4
async def stage_4_generate_code(self):
    # 1. Generate from templates
    generated = self.template_engine.generate_node(...)

    # 2. Apply production patterns
    refiner = CodeRefiner()
    refined = await refiner.refine_code(
        code=generated,
        file_type="node",
        refinement_context={
            "node_type": self.parsed_prompt.node_type,
            "domain": self.parsed_prompt.domain,
        }
    )

    # 3. Validate and use
    self.generated_code = refined if self._validate(refined) else generated
```

---

**Full Documentation**: `docs/CODE_REFINER_GUIDE.md`
**Delivery Summary**: `POLY_2_DELIVERY_SUMMARY.md`
