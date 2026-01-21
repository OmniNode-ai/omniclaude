# Pattern Library - Phase 5 Code Generation

## Overview

The Pattern Library provides intelligent, pattern-based code generation for common operations in the autonomous code generation system. It reduces manual coding by automatically generating complete method implementations based on capability analysis.

## Architecture

### Components

1. **PatternMatcher** (`pattern_matcher.py`)
   - Analyzes contract capabilities to identify applicable patterns
   - Provides confidence scoring (0.0 to 1.0)
   - Supports multiple pattern matches per capability
   - Uses keyword matching and semantic analysis

2. **PatternRegistry** (`pattern_registry.py`)
   - Central registry of all available patterns
   - Pattern lookup by type or capability
   - Code generation orchestration
   - Pattern composition and compatibility checking

3. **Pattern Implementations**
   - **CRUDPattern** (`crud_pattern.py`) - Create, Read, Update, Delete operations
   - **TransformationPattern** (`transformation_pattern.py`) - Data transformations
   - **AggregationPattern** (`aggregation_pattern.py`) - Reduce/aggregate operations
   - **OrchestrationPattern** (`orchestration_pattern.py`) - Workflow coordination

## Pattern Types

### 1. CRUD Pattern

**Use Case**: Database operations with transaction management

**Keywords**: create, insert, add, read, get, fetch, update, modify, delete, remove

**Node Types**: EFFECT nodes with database dependencies

**Generated Features**:
- Database interaction via transaction manager
- Input validation with required field checking
- Error handling with OnexError
- Event publishing (if EventBus mixin present)
- Proper async/await patterns

**Example Capability**:
```python
{
    "name": "create_user",
    "type": "create",
    "description": "Create a new user record in the database",
    "required": True
}
```

**Generated Method**:
- Validates required fields
- Wraps database operation in transaction
- Publishes `user.created` event
- Returns entity ID and confirmation

### 2. Transformation Pattern

**Use Case**: Data format conversions and validation

**Keywords**: transform, convert, parse, format, map, filter, normalize, validate

**Node Types**: COMPUTE nodes

**Generated Features**:
- Format conversion (JSON, CSV, XML, Dict)
- Data mapping with field transformations
- Input/output validation
- Streaming support for large datasets
- Pure function patterns (no side effects)

**Transformation Types**:
- **Format Conversion**: CSV→JSON, XML→Dict, etc.
- **Data Mapping**: Field mapping with transformation rules
- **Validation**: Type checking and constraint validation
- **Streaming**: Batch processing for large datasets

### 3. Aggregation Pattern

**Use Case**: Data reduction and summarization

**Keywords**: aggregate, reduce, sum, count, average, group, batch, collect, merge

**Node Types**: REDUCER nodes

**Generated Features**:
- Reduce operations (sum, count, average, min, max)
- Group by operations with field aggregation
- Windowing support (count-based and time-based)
- Stateful aggregation with persistence
- Incremental aggregation

**Aggregation Types**:
- **Reduce**: Single value from collection (sum, count, avg, etc.)
- **Group By**: Aggregate within groups by field
- **Windowed**: Sliding window aggregation
- **Stateful**: Incremental aggregation with state persistence

### 4. Orchestration Pattern

**Use Case**: Multi-step workflow coordination

**Keywords**: orchestrate, coordinate, workflow, sequence, parallel, execute, manage

**Node Types**: ORCHESTRATOR nodes

**Generated Features**:
- Multi-step workflow execution
- Sequential and parallel task execution
- Error recovery and compensation logic
- State management across workflow steps
- Saga pattern support for distributed transactions

**Orchestration Types**:
- **Sequential**: Step-by-step execution with checkpoints
- **Parallel**: Concurrent task execution with dependencies
- **Compensating**: Rollback support on failure
- **Saga**: Distributed transaction pattern

## Usage

### Basic Pattern Matching

```python
from agents.lib.patterns import PatternMatcher, PatternRegistry

# Initialize components
matcher = PatternMatcher()
registry = PatternRegistry()

# Define capability
capability = {
    "name": "create_user",
    "type": "create",
    "description": "Create a new user record in the database",
    "required": True
}

# Match patterns
matches = matcher.match_patterns(capability, max_matches=3)

# Get best match
best_match = matches[0]
print(f"Pattern: {best_match.pattern_type.value}")
print(f"Confidence: {best_match.confidence:.2%}")
print(f"Method: {best_match.suggested_method_name}")
```

### Code Generation

```python
# Generate code using matched pattern
context = {
    "has_event_bus": True,
    "service_name": "user_service",
    **best_match.context
}

generated_code = registry.generate_code_for_pattern(
    pattern_match=best_match,
    capability=capability,
    context=context
)

print(generated_code)
```

### Get Required Dependencies

```python
# Get required imports for pattern
imports = registry.get_required_imports_for_pattern(best_match.pattern_type)
for imp in imports:
    print(imp)

# Get required mixins for pattern
mixins = registry.get_required_mixins_for_pattern(best_match.pattern_type)
for mixin in mixins:
    print(f"  - {mixin}")
```

### Pattern Composition

```python
# Check if two patterns can be composed
from agents.lib.patterns.pattern_matcher import PatternType

can_compose = registry.can_compose_patterns(
    PatternType.TRANSFORMATION,
    PatternType.CRUD
)

if can_compose:
    print("Patterns are compatible for composition")
```

## Integration with Business Logic Generator

The Pattern Library integrates with `business_logic_generator.py` to enhance stub generation:

```python
from agents.lib.patterns import PatternMatcher, PatternRegistry

class BusinessLogicGenerator:
    def __init__(self):
        self.pattern_matcher = PatternMatcher()
        self.pattern_registry = PatternRegistry()

    async def generate_method(self, capability: Dict[str, Any], context: Dict[str, Any]) -> str:
        # Try pattern-based generation first
        matches = self.pattern_matcher.match_patterns(capability, max_matches=1)

        if matches and matches[0].confidence >= 0.7:
            # Use pattern-based generation
            return self.pattern_registry.generate_code_for_pattern(
                pattern_match=matches[0],
                capability=capability,
                context=context
            )
        else:
            # Fallback to stub generation
            return self._generate_stub(capability, context)
```

## Pattern Detection Keywords

### CRUD Keywords
```
create, insert, add, new, save, store
read, get, fetch, retrieve, find, query, select
update, modify, edit, change, patch, set
delete, remove, destroy, drop, erase
```

### Transformation Keywords
```
transform, convert, parse, format, map, filter
translate, encode, decode, serialize, deserialize
normalize, validate, sanitize, clean, process
```

### Aggregation Keywords
```
aggregate, reduce, sum, count, average, mean
group, batch, collect, accumulate, combine
merge, join, union, consolidate, summarize
```

### Orchestration Keywords
```
orchestrate, coordinate, workflow, sequence, parallel
execute, run, schedule, trigger, dispatch
manage, control, supervise, monitor, handle
```

## Confidence Scoring

Pattern confidence is calculated based on:

1. **Keyword Match Ratio** (40%): Number of matched keywords / total pattern keywords
2. **Primary Keyword Presence** (30%): Bonus if first word matches
3. **Context Alignment** (30%): Capability type matches expected type

**Thresholds**:
- **>= 0.8**: High confidence - Use pattern generation
- **0.6 - 0.8**: Medium confidence - Suggest with review
- **< 0.6**: Low confidence - Use stub generation

## Pattern Priorities

When multiple patterns match, use priority ordering:

1. **CRUD**: 100 (Highest - Database operations)
2. **Orchestration**: 90 (High - Workflow coordination)
3. **Aggregation**: 80 (High - Reducer operations)
4. **Transformation**: 70 (Medium - Compute operations)

## Error Handling

All generated code includes:
- Try/except blocks with proper exception handling
- OnexError usage with appropriate error codes
- Logging statements for debugging
- Detailed error messages with context

## Required Mixins by Pattern

### CRUD Pattern
- `MixinDatabase` - Database transaction support
- `MixinValidation` - Input validation
- `MixinEventBus` - Event publishing (optional)

### Transformation Pattern
- `MixinValidation` - Input/output validation
- `MixinCaching` - Cache transformation results (optional)

### Aggregation Pattern
- `MixinStateManagement` - State persistence
- `MixinCaching` - Cache aggregation results

### Orchestration Pattern
- `MixinStateManagement` - Workflow state persistence
- `MixinEventBus` - Event publishing for workflow events
- `MixinRetry` - Retry logic for failed steps
- `MixinCircuitBreaker` - Circuit breaker for service calls

## Performance Targets

- **Pattern Matching**: < 50ms per capability
- **Code Generation**: < 100ms per method
- **Confidence Calculation**: < 10ms per pattern
- **Registry Lookup**: < 5ms per pattern type

## Future Enhancements

1. **Machine Learning**: Train ML models on successful pattern matches
2. **Custom Patterns**: Allow user-defined pattern templates
3. **Pattern Composition**: Automatic composition of compatible patterns
4. **Quality Feedback**: Learn from quality scores to improve pattern selection
5. **Template Variants**: Multiple implementation variants per pattern

## Testing

Run the test suite:
```bash
python agents/lib/patterns/test_patterns.py
```

## File Structure

```
agents/lib/patterns/
├── __init__.py                  # Package exports
├── pattern_matcher.py           # Pattern matching logic (323 lines)
├── pattern_registry.py          # Pattern registry (259 lines)
├── crud_pattern.py              # CRUD operations (471 lines)
├── transformation_pattern.py    # Data transformations (513 lines)
├── aggregation_pattern.py       # Reduce/aggregate (532 lines)
├── orchestration_pattern.py     # Workflow coordination (687 lines)
├── test_patterns.py             # Test suite
└── README.md                    # This file
```

**Total**: 2,809 lines of production code

## References

- Phase 5 specification: `AUTONOMOUS_CODE_GENERATION_PLAN.md`
- Enum generator: `agents/lib/enum_generator.py`
- Contract generator: `agents/lib/contract_generator.py`
- Business logic generator: `agents/lib/business_logic_generator.py`
