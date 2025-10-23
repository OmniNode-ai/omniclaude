# Stage 5.5 Pipeline Flow Diagram

## Complete Pipeline Flow (8 Stages, 16 Gates)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    GENERATION PIPELINE (8 STAGES)                    │
└─────────────────────────────────────────────────────────────────────┘

[User Prompt] → "Create a postgres adapter effect node..."
        ↓
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 1: Prompt Parsing                                    (5s)     │
│ ────────────────────────────────────────────────────────────────    │
│ ✓ Parse natural language prompt                                     │
│ ✓ Extract node type, service name, domain                           │
│ ✓ Analyze PRD (Product Requirements Document)                       │
│                                                                      │
│ Gates: G7 (WARNING), G8 (WARNING)                                   │
└─────────────────────────────────────────────────────────────────────┘
        ↓ [parsed_data, analysis_result]
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 1.5: Intelligence Gathering                          (3s)     │
│ ────────────────────────────────────────────────────────────────    │
│ ✓ Query RAG for best practices                                      │
│ ✓ Gather code examples from production nodes                        │
│ ✓ Extract domain-specific patterns                                  │
│ ✓ Identify common operations and anti-patterns                      │
│                                                                      │
│ Gates: I1 (WARNING)                                                 │
└─────────────────────────────────────────────────────────────────────┘
        ↓ [intelligence_context]
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 2: Contract Building                                 (2s)     │
│ ────────────────────────────────────────────────────────────────    │
│ ✓ Build ONEX contract from parsed data                              │
│ ✓ Validate with AI Quorum (Gemini + GLM models)                     │
│ ✓ Check intent alignment and deficiencies                           │
│ ✓ Store quorum_result for refinement                                │
│                                                                      │
│ Gates: Q1 (BLOCKING - Quorum Validation)                            │
└─────────────────────────────────────────────────────────────────────┘
        ↓ [contract, quorum_result]
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 3: Pre-Generation Validation                         (2s)     │
│ ────────────────────────────────────────────────────────────────    │
│ ✓ Validate prompt completeness                                      │
│ ✓ Check node type validity                                          │
│ ✓ Verify service name format                                        │
│ ✓ Test critical imports availability                                │
│ ✓ Confirm templates exist                                           │
│ ✓ Check output directory permissions                                │
│                                                                      │
│ Gates: G1, G2, G3, G4, G5, G6 (ALL BLOCKING)                        │
└─────────────────────────────────────────────────────────────────────┘
        ↓ [validation_passed]
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 4: Code Generation                                   (10-15s) │
│ ────────────────────────────────────────────────────────────────    │
│ ✓ Generate node.py from template                                    │
│ ✓ Apply intelligence context (patterns, mixins, etc.)               │
│ ✓ Create contract models and enums                                  │
│ ✓ Generate test stubs                                               │
│                                                                      │
│ Gates: None (quality checked in Stage 5)                            │
└─────────────────────────────────────────────────────────────────────┘
        ↓ [generated_files: {main_file, generated_files[]}]
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 5: Post-Generation Validation                        (5s)     │
│ ────────────────────────────────────────────────────────────────    │
│ ✓ Validate Python syntax (AST parsing)                              │
│ ✓ Check ONEX naming convention (suffix-based)                       │
│ ✓ Verify import resolution                                          │
│ ✓ Validate Pydantic model structure                                 │
│                                                                      │
│ Gates: G9, G10, G11, G12 (ALL BLOCKING)                             │
└─────────────────────────────────────────────────────────────────────┘
        ↓ [validation_gates[], generated_files]
┌─────────────────────────────────────────────────────────────────────┐
│ ★ STAGE 5.5: AI-Powered Code Refinement ★              (3s) [NEW]  │
│ ────────────────────────────────────────────────────────────────    │
│ ✓ Aggregate refinement context from:                                │
│   • Validation warnings (G7, G8, I1)                                │
│   • Quorum deficiencies                                             │
│   • Intelligence patterns (ONEX best practices)                     │
│   • Domain-specific recommendations                                 │
│   • Anti-patterns to avoid                                          │
│                                                                      │
│ ✓ Check if refinement needed:                                       │
│   • Has validation warnings? → Refine                               │
│   • Has quorum deficiencies? → Refine                               │
│   • Low quorum confidence (<0.8)? → Refine                          │
│   • Otherwise → Skip                                                │
│                                                                      │
│ ✓ Apply AI-powered refinement (placeholder for LLM)                 │
│                                                                      │
│ ✓ Validate refinement quality:                                      │
│   • Valid Python syntax (AST)                                       │
│   • Reasonable changes (<50% line delta)                            │
│   • Node class preserved                                            │
│   • Critical imports intact                                         │
│                                                                      │
│ ✓ Graceful degradation on failure → Keep original code              │
│                                                                      │
│ Gates: R1 (BLOCKING - Refinement Quality)                           │
│                                                                      │
│ Status Options:                                                     │
│   • COMPLETED (applied) → refined_files                             │
│   • SKIPPED (not needed) → original_files                           │
│   • FAILED (error) → original_files                                 │
└─────────────────────────────────────────────────────────────────────┘
        ↓ [refined_files or original_files]
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 6: File Writing                                      (3s)     │
│ ────────────────────────────────────────────────────────────────    │
│ ✓ Write refined code to filesystem                                  │
│ ✓ Verify all files written successfully                             │
│ ✓ Track written files for potential rollback                        │
│                                                                      │
│ Gates: None (verification only)                                     │
└─────────────────────────────────────────────────────────────────────┘
        ↓ [output_path, generated_files[]]
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 7: Compilation Testing (Optional)                    (10s)    │
│ ────────────────────────────────────────────────────────────────    │
│ ✓ Run mypy type checking                                            │
│ ✓ Test Python import (verify node can be imported)                  │
│                                                                      │
│ Gates: G13, G14 (BOTH WARNING)                                      │
└─────────────────────────────────────────────────────────────────────┘
        ↓ [compilation_passed: bool]
┌─────────────────────────────────────────────────────────────────────┐
│                         PIPELINE RESULT                              │
│ ────────────────────────────────────────────────────────────────    │
│ ✓ Status: success/failed                                            │
│ ✓ Total Duration: ~51s                                              │
│ ✓ Stages: 8 stages (1, 1.5, 2, 3, 4, 5, 5.5, 6, 7)                 │
│ ✓ Validation Gates: 16 gates passed                                 │
│ ✓ Generated Files: [node.py, models/, enums/, tests/]               │
│ ✓ Refinement Applied: true/false                                    │
└─────────────────────────────────────────────────────────────────────┘
```

## Refinement Context Aggregation

```
┌──────────────────────────────────────────────────────────────────┐
│            REFINEMENT CONTEXT BUILDER                             │
└──────────────────────────────────────────────────────────────────┘

INPUT SOURCES:
═══════════════

1. Validation Warnings (from all previous stages)
   ┌─────────────────────────────────────────────────────┐
   │ G7: "Prompt has few words (<5)"                     │
   │ G8: "Context missing optional fields: operations"   │
   │ I1: "No domain best practices found"                │
   └─────────────────────────────────────────────────────┘
            ↓
   "Address validation warnings: Prompt has few words;
    Context missing operations; No domain practices"

2. Quorum Deficiencies (from Stage 2 AI Quorum)
   ┌─────────────────────────────────────────────────────┐
   │ • "Missing error handling for connection timeout"   │
   │ • "No retry logic specified"                        │
   │ • "Unclear transaction boundary"                    │
   └─────────────────────────────────────────────────────┘
            ↓
   "Address quorum deficiencies: Missing error handling;
    No retry logic; Unclear transaction boundary"

3. ONEX Best Practices (from Intelligence Context)
   ┌─────────────────────────────────────────────────────┐
   │ • "Use connection pooling for database connections" │
   │ • "Implement circuit breaker for external APIs"     │
   │ • "Use retry logic with exponential backoff"        │
   └─────────────────────────────────────────────────────┘
            ↓
   "Apply ONEX best practices: Connection pooling;
    Circuit breaker; Retry with backoff"

4. Domain Patterns (from Intelligence Context)
   ┌─────────────────────────────────────────────────────┐
   │ • "Use prepared statements for SQL"                 │
   │ • "Implement proper transaction management"         │
   └─────────────────────────────────────────────────────┘
            ↓
   "Apply domain patterns: Prepared statements;
    Transaction management"

5. Anti-Patterns to Avoid (from Intelligence Context)
   ┌─────────────────────────────────────────────────────┐
   │ • "Avoid string concatenation for SQL queries"      │
   │ • "Don't use bare except clauses"                   │
   └─────────────────────────────────────────────────────┘
            ↓
   "Avoid anti-patterns: String SQL concatenation;
    Bare except clauses"

OUTPUT:
═══════

refinement_context = [
    "Address validation warnings: ...",
    "Address quorum deficiencies: ...",
    "Apply ONEX best practices: ...",
    "Apply domain patterns: ...",
    "Avoid anti-patterns: ..."
]
        ↓
[Pass to AI Model for Code Refinement]
```

## Validation Gate R1 Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                    GATE R1: REFINEMENT QUALITY                    │
└──────────────────────────────────────────────────────────────────┘

INPUT: original_code, refined_code, refinement_context

CHECK 1: Syntax Validation
─────────────────────────────
    try:
        ast.parse(refined_code)
    except SyntaxError:
        ✗ FAIL → "Refined code has syntax error"

    ✓ PASS

CHECK 2: Line Change Ratio
─────────────────────────────
    original_lines = 150
    refined_lines = 160
    change_ratio = |160 - 150| / 150 = 6.7%

    if change_ratio > 50%:
        ✗ WARNING → "Significant code change"

    ✓ PASS (6.7% < 50%)

CHECK 3: Class Preservation
─────────────────────────────
    "class Node" in original_code? → YES
    "class Node" in refined_code? → YES

    ✓ PASS

CHECK 4: Critical Imports
─────────────────────────────
    Check: "from omnibase_core.nodes" → ✓ Present
    Check: "from omnibase_core.errors" → ✓ Present
    Check: "from omnibase_core.models" → ✓ Present

    ✓ PASS

RESULT:
═══════
✓ PASS: "Refinement applied 5 enhancements successfully"
```

## Performance Targets

| Stage | Target Duration | Cumulative |
|-------|----------------|------------|
| Stage 1 | 5s | 5s |
| Stage 1.5 | 3s | 8s |
| Stage 2 | 2s | 10s |
| Stage 3 | 2s | 12s |
| Stage 4 | 10-15s | 22-27s |
| Stage 5 | 5s | 27-32s |
| **Stage 5.5** | **3s** | **30-35s** |
| Stage 6 | 3s | 33-38s |
| Stage 7 | 10s | 43-48s |
| **TOTAL** | **~51s** | **51s** |

## Error Handling Strategy

```
┌──────────────────────────────────────────────────────────────────┐
│               GRACEFUL DEGRADATION STRATEGY                       │
└──────────────────────────────────────────────────────────────────┘

Scenario 1: Refinement Not Needed
──────────────────────────────────
    IF no warnings AND no quorum deficiencies AND confidence ≥ 0.8:
        status = SKIPPED
        return original_files

    → Pipeline continues with original code ✓

Scenario 2: Refinement Quality Check Fails (R1)
────────────────────────────────────────────────
    IF refined_code fails syntax check:
        status = COMPLETED (with metadata)
        return original_files

    → Pipeline continues with original code ✓

Scenario 3: Refinement Exception
─────────────────────────────────
    TRY:
        refined_code = await _apply_ai_refinement(...)
    EXCEPT Exception as e:
        logger.error(f"Refinement failed: {e}")
        status = FAILED
        return original_files

    → Pipeline continues with original code ✓

Scenario 4: File Not Found
───────────────────────────
    IF main_file_path.exists() == False:
        status = FAILED
        error = "Main file not found"
        return original_files

    → Pipeline fails at Stage 5.5 (appropriate failure) ✗

Result: Pipeline NEVER crashes due to refinement failures
```
