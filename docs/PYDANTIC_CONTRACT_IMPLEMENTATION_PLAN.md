# Phase 2 Implementation Plan: Pydantic-Based Contract Generation

**Generated**: 2025-10-21
**Status**: Ready for Execution
**Timeline**: 4-6 weeks (sequential) | 2-3 weeks (parallel with 4 agents)

---

## Executive Summary

### Current State (Phase 1 - Complete ✅)

**Achievements**:
- ✅ PromptParser: Natural language → structured metadata (confidence scoring)
- ✅ GenerationPipeline: 6-stage pipeline with 14 validation gates
- ✅ FileWriter: Atomic file operations with rollback
- ✅ Template Engine: String-based code generation
- ✅ POC: EFFECT nodes generated in ~40 seconds

**Limitations**:
- ❌ Only EFFECT nodes supported (COMPUTE, REDUCER, ORCHESTRATOR missing)
- ❌ String-based contract generation (not type-safe)
- ❌ No Pydantic model usage from omnibase_core
- ❌ Limited validation (no contract schema validation)
- ❌ No AST-based generation (manual template editing required)

### Phase 2 Objectives

**Primary Goals**:
1. **Pydantic Contract Integration**: Replace string templates with `ModelContractEffect`, `ModelContractCompute`, `ModelContractReducer`, `ModelContractOrchestrator`
2. **All Node Types**: Support EFFECT, COMPUTE, REDUCER, ORCHESTRATOR
3. **omnibase_3 Utilities**: Port contract analyzer, AST builder, type mapper, enum generator
4. **Enhanced Validation**: Contract schema validation, model reference resolution, cross-node compatibility

**Success Criteria**:
- ✅ All contracts generated using Pydantic models with `.to_yaml()`
- ✅ All 4 node types supported with proper naming conventions
- ✅ Contract validation integrated with 100% schema compliance
- ✅ omnibase_3 utilities ported and working
- ✅ 100% tests passing with >90% coverage
- ✅ Performance targets met (<60s generation time)
- ✅ Production-ready quality (zero tolerance for `Any` types)

---

## Parallel Execution Strategy

### 4 Independent Work Streams

**Stream A: Contract Model Integration** (Lead: Agent 1)
- Replace string-based generation with Pydantic models
- Implement ContractBuilder for each node type
- Add contract validation gates

**Stream B: Node Type Support** (Lead: Agent 2)
- Add COMPUTE node support
- Add REDUCER node support
- Add ORCHESTRATOR node support
- Update templates and validation

**Stream C: omnibase_3 Utilities Migration** (Lead: Agent 3)
- Port contract analyzer and validator
- Port AST builder and type mapper
- Port enum generator
- Integrate with pipeline

**Stream D: Enhanced Validation & Testing** (Lead: Agent 4)
- Add contract schema validation
- Create comprehensive test suite
- Performance benchmarks
- Integration testing

### Timeline Comparison

| Approach | Duration | Resource Cost | Risk |
|----------|----------|---------------|------|
| **Sequential** | 4-6 weeks | 1 senior dev | Low |
| **Parallel (2 agents)** | 3-4 weeks | 2 senior devs | Medium |
| **Parallel (4 agents)** | 2-3 weeks | 4 senior devs | Medium-High |
| **Aggressive (4 agents + overtime)** | 1.5-2 weeks | 4 senior devs + 25% overtime | High |

**Recommended**: Parallel with 4 agents (2-3 weeks)

---

## Detailed Work Stream Specifications

### Stream A: Contract Model Integration

**Duration**: 2 weeks
**Dependencies**: None (can start immediately)
**Risk**: Low-Medium

#### Tasks

**Week 1: Contract Builder Foundation**
1. Create `ContractBuilder` base class (4h)
   - Generic builder pattern for all node types
   - Required fields validation
   - Default value population
   - Builder method chaining

2. Implement `EffectContractBuilder` (6h)
   - Build `ModelContractEffect` from parsed data
   - Populate IO operations, lifecycle, dependencies
   - Generate YAML using `.to_yaml()`
   - Unit tests for builder

3. Create `ContractBuilderFactory` (4h)
   - Factory pattern for selecting builder by node type
   - Registration system for custom builders
   - Validation hooks

**Week 2: Integration & Validation**
4. Integrate ContractBuilder into GenerationPipeline (6h)
   - Replace string template usage
   - Update Stage 3 (code generation)
   - Add contract validation gate

5. Add contract validation (6h)
   - Schema compliance validation
   - Required fields check
   - Type consistency validation
   - Cross-reference validation

6. Testing & Documentation (8h)
   - Unit tests for all builders
   - Integration tests with pipeline
   - Documentation and examples

**Deliverables**:
- ✅ `ContractBuilder` base class
- ✅ `EffectContractBuilder` implementation
- ✅ Factory pattern for builder selection
- ✅ Contract validation integrated
- ✅ 100% test coverage for builders
- ✅ Documentation with examples

**Files to Create**:
```
agents/lib/generation/
├── contract_builder.py          # Base class
├── contract_builder_effect.py   # EFFECT builder
├── contract_builder_factory.py  # Factory
└── contract_validator.py        # Validation
```

---

### Stream B: Node Type Support

**Duration**: 2 weeks
**Dependencies**: None (can start immediately)
**Risk**: Medium

#### Tasks

**Week 1: COMPUTE & REDUCER Support**
1. Add COMPUTE node support (8h)
   - Update PromptParser to detect COMPUTE keywords
   - Create COMPUTE template (if not exists)
   - Update GenerationPipeline for COMPUTE
   - Create `ComputeContractBuilder`
   - Add COMPUTE validation gates

2. Add REDUCER node support (8h)
   - Update PromptParser to detect REDUCER keywords
   - Create REDUCER template (if not exists)
   - Update GenerationPipeline for REDUCER
   - Create `ReducerContractBuilder`
   - Add REDUCER validation gates (intent emission check)

**Week 2: ORCHESTRATOR Support & Testing**
3. Add ORCHESTRATOR node support (8h)
   - Update PromptParser to detect ORCHESTRATOR keywords
   - Create ORCHESTRATOR template (if not exists)
   - Update GenerationPipeline for ORCHESTRATOR
   - Create `OrchestratorContractBuilder`
   - Add ORCHESTRATOR validation gates (lease validation check)

4. Update validation gates (6h)
   - Update G2 gate to allow all 4 node types
   - Add node-specific validation gates
   - Update G10 gate for all node type suffixes

5. End-to-end testing (10h)
   - Generate EFFECT node from prompt
   - Generate COMPUTE node from prompt
   - Generate REDUCER node from prompt
   - Generate ORCHESTRATOR node from prompt
   - Verify all naming conventions
   - Verify all validation gates

**Deliverables**:
- ✅ COMPUTE node support (fully tested)
- ✅ REDUCER node support (fully tested)
- ✅ ORCHESTRATOR node support (fully tested)
- ✅ All 4 node types validated
- ✅ Updated validation gates
- ✅ End-to-end test suite

**Files to Update/Create**:
```
agents/lib/
├── prompt_parser.py              # Update detection logic
├── generation_pipeline.py        # Support all 4 types
└── generation/
    ├── contract_builder_compute.py
    ├── contract_builder_reducer.py
    └── contract_builder_orchestrator.py
```

---

### Stream C: omnibase_3 Utilities Migration

**Duration**: 2 weeks
**Dependencies**: None (can start immediately)
**Risk**: Medium-High (adaptation complexity)

#### Tasks

**Week 1: Contract & AST Utilities**
1. Port ContractAnalyzer (8h)
   - Extract from omnibase_3 `utility_contract_analyzer.py`
   - Update imports (omnibase_3 → omnibase_core)
   - Remove "Utility" prefix
   - Simplify error handling
   - Test with sample contracts

2. Port ASTBuilder (8h)
   - Extract from omnibase_3 `utility_ast_builder.py`
   - Update type hints and imports
   - Adapt to omnibase_core patterns
   - Test AST generation

**Week 2: Type Mapping & Enum Generation**
3. Port TypeMapper (6h)
   - Extract from omnibase_3 `utility_type_mapper.py`
   - Update type mappings for omnibase_core
   - Add omnibase_core-specific types
   - Test type mapping

4. Port EnumGenerator (6h)
   - Extract from omnibase_3 `utility_enum_generator.py`
   - Update naming conventions (EnumXxx pattern)
   - Test enum generation

5. Integration & Testing (10h)
   - Integrate utilities into GenerationPipeline
   - Replace template-based model generation with AST
   - End-to-end testing
   - Performance benchmarks

**Deliverables**:
- ✅ `ContractAnalyzer` ported and tested
- ✅ `ASTBuilder` ported and tested
- ✅ `TypeMapper` ported and tested
- ✅ `EnumGenerator` ported and tested
- ✅ Utilities integrated into pipeline
- ✅ Performance benchmarks documented

**Files to Create**:
```
agents/lib/generation/
├── contract_analyzer.py      # From utility_contract_analyzer.py
├── ast_builder.py           # From utility_ast_builder.py
├── type_mapper.py           # From utility_type_mapper.py
├── enum_generator.py        # From utility_enum_generator.py
└── reference_resolver.py    # From utility_reference_resolver.py (optional)
```

**Import Migration Table**:
| omnibase_3 Import | omnibase_core Replacement |
|-------------------|---------------------------|
| `omnibase.core.node_base` | `omnibase_core.core.infrastructure_service_bases` |
| `omnibase.model.core.model_schema` | `omnibase_core.models.contracts` |
| `omnibase.exceptions` | `omnibase_core.errors.model_onex_error` |
| `omnibase.core.core_error_codes` | `omnibase_core.errors.error_codes` |

---

### Stream D: Enhanced Validation & Testing

**Duration**: 2 weeks
**Dependencies**: Partial (needs Streams A, B, C for integration testing)
**Risk**: Low

#### Tasks

**Week 1: Contract Schema Validation**
1. Implement contract schema validator (8h)
   - Load contract schemas from omnibase_core
   - Validate generated contracts against schemas
   - Required fields validation
   - Type consistency checks
   - Reference integrity validation

2. Add model reference resolution (6h)
   - Resolve $ref references in contracts
   - Validate referenced models exist
   - Check circular references
   - Test resolution logic

**Week 2: Comprehensive Testing**
3. Create test suite (10h)
   - Unit tests for all components
   - Integration tests for pipeline
   - End-to-end tests for all 4 node types
   - Performance benchmarks
   - Edge case testing

4. Performance optimization (6h)
   - Profile generation pipeline
   - Identify bottlenecks
   - Optimize slow operations
   - Verify <60s generation time

5. Documentation & Examples (6h)
   - Update README with Phase 2 features
   - Create usage examples for all node types
   - Document contract builder API
   - Create troubleshooting guide

**Deliverables**:
- ✅ Contract schema validator implemented
- ✅ Model reference resolution working
- ✅ Comprehensive test suite (>90% coverage)
- ✅ Performance benchmarks documented
- ✅ Complete documentation

**Files to Create**:
```
agents/lib/generation/
├── schema_validator.py       # Schema validation
└── reference_resolver.py     # Reference resolution

tests/
├── test_contract_builder.py
├── test_node_generation.py
├── test_validation_gates.py
└── test_performance.py
```

---

## Integration Points & Dependencies

### Critical Path (Blocks Completion)

```
Stream A (Week 1) → Stream D (Week 2, Integration testing)
Stream B (Week 2) → Stream D (Week 2, End-to-end testing)
Stream C (Week 2) → Stream D (Week 2, Performance testing)
```

### Synchronization Points

**Week 1 (No synchronization required)**:
- All streams work independently
- No shared code changes
- No merge conflicts expected

**Week 2 (Daily synchronization)**:
- Stream A completes → Stream D can test contract builders
- Stream B completes → Stream D can test all 4 node types
- Stream C completes → Stream D can test AST generation
- Final integration requires all streams complete

---

## Success Metrics

### Functional Requirements

- ✅ Generate EFFECT node using Pydantic contracts (Pass/Fail)
- ✅ Generate COMPUTE node using Pydantic contracts (Pass/Fail)
- ✅ Generate REDUCER node using Pydantic contracts (Pass/Fail)
- ✅ Generate ORCHESTRATOR node using Pydantic contracts (Pass/Fail)
- ✅ All contracts validate against schema (100% pass rate)
- ✅ All generated code compiles without errors (100% pass rate)
- ✅ ONEX naming conventions followed (100% compliance)

### Quality Requirements

- ✅ Test coverage >90% (measured via pytest-cov)
- ✅ Type checking passes (0 mypy errors)
- ✅ Linting passes (0 ruff errors)
- ✅ Zero tolerance for `Any` types in generated code
- ✅ All docstrings present (Google style)
- ✅ Error handling uses `ModelOnexError` (100% compliance)

### Performance Requirements

- ✅ Generation time <60s for all node types (95th percentile)
- ✅ Contract validation <2s (average)
- ✅ AST generation <5s (average)
- ✅ File writing <3s (average)
- ✅ Memory usage <500MB (peak)

---

## Risk Register & Mitigation

### Technical Risks

**R1: Pydantic Contract Complexity** (Medium Probability, High Impact)
- **Mitigation**: Start with simple EFFECT contracts, iterate to complex
- **Contingency**: Fallback to string templates for complex cases
- **Owner**: Stream A Lead

**R2: omnibase_3 Adaptation Issues** (High Probability, Medium Impact)
- **Mitigation**: Incremental porting, test each utility independently
- **Contingency**: Skip advanced features, use simplified versions
- **Owner**: Stream C Lead

**R3: Node Type Support Incompatibilities** (Medium Probability, Medium Impact)
- **Mitigation**: Reference ONEX_CORE_NODE_PARADIGM.md for all node types
- **Contingency**: Phase 2.5 for REDUCER/ORCHESTRATOR if needed
- **Owner**: Stream B Lead

**R4: Integration Conflicts** (Low Probability, High Impact)
- **Mitigation**: Daily synchronization meetings, shared Git branch strategy
- **Contingency**: Dedicated integration week if conflicts severe
- **Owner**: Stream D Lead

### Process Risks

**R5: Scope Creep** (Medium Probability, Medium Impact)
- **Mitigation**: Strict adherence to Phase 2 scope, backlog for Phase 3
- **Contingency**: Push non-critical features to Phase 3
- **Owner**: Project Manager

**R6: Resource Availability** (Low Probability, High Impact)
- **Mitigation**: Cross-train team members on multiple streams
- **Contingency**: Extend timeline by 1 week if resource loss
- **Owner**: Project Manager

---

## Phase Gates

### Gate 1: Week 1 Checkpoint (Stream A, B, C)

**Criteria**:
- ✅ Stream A: ContractBuilder base class complete
- ✅ Stream B: COMPUTE node detection working
- ✅ Stream C: ContractAnalyzer and ASTBuilder ported
- ✅ All streams: Unit tests passing (>80% coverage)

**Action**: If any stream fails, adjust Week 2 priorities

### Gate 2: Week 2 Checkpoint (All Streams)

**Criteria**:
- ✅ Stream A: All 4 contract builders complete
- ✅ Stream B: All 4 node types supported
- ✅ Stream C: All utilities ported and integrated
- ✅ Stream D: Integration tests passing (>90%)

**Action**: If any stream incomplete, extend by 3 days

### Gate 3: Phase 2 Completion

**Criteria**:
- ✅ All functional requirements met
- ✅ All quality requirements met
- ✅ All performance requirements met
- ✅ Documentation complete
- ✅ Stakeholder demo approved

**Action**: If incomplete, create Phase 2.5 for remaining work

---

## Rollout Plan

### Week 3 (Post-Development): Production Readiness

1. **Code Review** (2 days)
   - Peer review all streams
   - Address feedback
   - Refactor if needed

2. **Performance Testing** (2 days)
   - Run benchmarks on all 4 node types
   - Optimize slow paths
   - Verify <60s generation time

3. **Documentation Review** (1 day)
   - Complete README updates
   - Create usage examples
   - Update troubleshooting guide

4. **Stakeholder Demo** (1 day)
   - Demonstrate all 4 node types
   - Show contract validation
   - Performance metrics presentation
   - Get approval for production deployment

---

## Appendix A: Detailed Task Breakdown

### Stream A: Contract Builder Tasks

| Task ID | Task | Effort (h) | Dependencies |
|---------|------|------------|--------------|
| A1 | Create `ContractBuilder` base class | 4 | None |
| A2 | Implement `EffectContractBuilder` | 6 | A1 |
| A3 | Create `ContractBuilderFactory` | 4 | A2 |
| A4 | Integrate into GenerationPipeline | 6 | A3 |
| A5 | Add contract validation | 6 | A4 |
| A6 | Testing & Documentation | 8 | A5 |
| **Total** | **34 hours** | **~1.5 weeks** | |

### Stream B: Node Type Support Tasks

| Task ID | Task | Effort (h) | Dependencies |
|---------|------|------------|--------------|
| B1 | Add COMPUTE node support | 8 | None |
| B2 | Add REDUCER node support | 8 | None |
| B3 | Add ORCHESTRATOR node support | 8 | None |
| B4 | Update validation gates | 6 | B1, B2, B3 |
| B5 | End-to-end testing | 10 | B4 |
| **Total** | **40 hours** | **~2 weeks** | |

### Stream C: Utilities Migration Tasks

| Task ID | Task | Effort (h) | Dependencies |
|---------|------|------------|--------------|
| C1 | Port ContractAnalyzer | 8 | None |
| C2 | Port ASTBuilder | 8 | None |
| C3 | Port TypeMapper | 6 | None |
| C4 | Port EnumGenerator | 6 | None |
| C5 | Integration & Testing | 10 | C1, C2, C3, C4 |
| **Total** | **38 hours** | **~2 weeks** | |

### Stream D: Validation & Testing Tasks

| Task ID | Task | Effort (h) | Dependencies |
|---------|------|------------|--------------|
| D1 | Contract schema validator | 8 | None |
| D2 | Model reference resolution | 6 | D1 |
| D3 | Create test suite | 10 | A5, B5, C5 |
| D4 | Performance optimization | 6 | D3 |
| D5 | Documentation & Examples | 6 | D4 |
| **Total** | **36 hours** | **~2 weeks** | |

---

## Appendix B: File Structure After Phase 2

```
omniclaude/
├── agents/
│   ├── lib/
│   │   ├── generation/                          # NEW: Generation utilities
│   │   │   ├── __init__.py
│   │   │   ├── contract_builder.py              # Base class
│   │   │   ├── contract_builder_effect.py       # EFFECT builder
│   │   │   ├── contract_builder_compute.py      # COMPUTE builder
│   │   │   ├── contract_builder_reducer.py      # REDUCER builder
│   │   │   ├── contract_builder_orchestrator.py # ORCHESTRATOR builder
│   │   │   ├── contract_builder_factory.py      # Factory
│   │   │   ├── contract_validator.py            # Validation
│   │   │   ├── schema_validator.py              # Schema validation
│   │   │   ├── contract_analyzer.py             # From omnibase_3
│   │   │   ├── ast_builder.py                   # From omnibase_3
│   │   │   ├── type_mapper.py                   # From omnibase_3
│   │   │   ├── enum_generator.py                # From omnibase_3
│   │   │   └── reference_resolver.py            # From omnibase_3
│   │   ├── prompt_parser.py                     # Updated for all 4 types
│   │   ├── generation_pipeline.py               # Updated for all 4 types
│   │   └── models/
│   │       ├── contract_build_result.py         # NEW
│   │       └── validation_result.py             # NEW
│   └── tests/
│       ├── test_contract_builder.py             # NEW
│       ├── test_node_generation.py              # NEW
│       ├── test_validation_gates.py             # UPDATED
│       └── test_performance.py                  # NEW
├── docs/
│   ├── PHASE_2_IMPLEMENTATION_PLAN.md          # This document
│   ├── PHASE_2_MIGRATION_CHECKLIST.md          # Migration guide
│   ├── CONTRACT_BUILDER_SPEC.md                # Builder specification
│   ├── OMNIBASE3_UTILITY_PORTING.md            # Porting guide
│   └── PARALLEL_EXECUTION_MATRIX.md            # Execution strategy
└── tools/
    └── node_gen/
        └── file_writer.py                       # UPDATED for all 4 types
```

---

**End of Phase 2 Implementation Plan**

**Next Steps**:
1. ✅ Review and approve this plan
2. 📅 Schedule Phase 2 kick-off meeting
3. 👥 Assign agents to work streams
4. 🚀 Begin Stream A, B, C in parallel (Week 1)
5. 🧪 Stream D begins validation (Week 2)
6. ✅ Phase 2 completion and production deployment (Week 3)

**Estimated Completion**: 2-3 weeks (parallel) | 4-6 weeks (sequential)
**Success Probability**: 85% (with 4-agent parallel execution)
