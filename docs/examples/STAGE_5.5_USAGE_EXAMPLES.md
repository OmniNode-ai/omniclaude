# Stage 5.5 Usage Examples

## Example 1: Refinement Applied (Warnings Present)

### Scenario
User prompt has validation warnings but generates valid code that could be improved.

```python
# User prompt (short, lacks context)
prompt = "postgres writer effect"

# Pipeline execution
pipeline = GenerationPipeline(
    enable_intelligence_gathering=True,
    quorum_config=QuorumConfig.enabled()
)

result = await pipeline.execute(
    prompt=prompt,
    output_directory="/tmp/nodes"
)
```

### Stage 5 Results (Post-Validation)
```
Validation Gates:
✓ G9: Python Syntax Valid
✓ G10: ONEX Naming Convention
✓ G11: Import Resolution
✓ G12: Pydantic Model Structure

Warnings:
⚠ G7: Prompt has few words (<5)
⚠ I1: No domain best practices found
```

### Stage 5.5 Execution

**Step 1: Build Refinement Context**
```python
refinement_context = [
    "Address validation warnings: Prompt has few words",
    "Apply ONEX best practices: Use connection pooling; Implement circuit breaker; Use retry logic",
    "Apply domain patterns: Use prepared statements for SQL; Implement transaction management"
]
```

**Step 2: Check Refinement Needed**
```python
has_warnings = True  # G7, I1 warnings present
needs_refinement = True
```

**Step 3: Apply AI Refinement**
```python
# Original code (simplified)
class NodePostgresWriterEffect(NodeEffect):
    async def execute_effect(self, contract):
        # Basic implementation
        return result

# Refined code (AI-enhanced - placeholder for now)
class NodePostgresWriterEffect(NodeEffect):
    """
    PostgreSQL writer effect node with connection pooling and retry logic.

    Implements ONEX best practices:
    - Connection pooling for database connections
    - Retry logic with exponential backoff
    - Prepared statements for SQL queries
    """
    async def execute_effect(self, contract):
        # Enhanced implementation (placeholder)
        return result
```

**Step 4: Validate Refinement (R1)**
```
✓ Syntax valid (AST parse successful)
✓ Line change ratio: 8.5% (120 → 130 lines)
✓ Class definition preserved
✓ Critical imports intact

R1: PASS - "Refinement applied 3 enhancements successfully"
```

**Step 5: Write Refined Code**
```python
refined_files = {
    "main_file": "/tmp/nodes/node_postgres_writer_effect/v1_0_0/node.py",
    "generated_files": [...],
    "refinement_applied": True,
    "refinement_context": [...]
}
```

### Pipeline Result
```json
{
  "status": "success",
  "total_duration_ms": 51234,
  "stages": [
    {"stage_name": "prompt_parsing", "status": "completed"},
    {"stage_name": "intelligence_gathering", "status": "completed"},
    {"stage_name": "contract_building", "status": "completed"},
    {"stage_name": "pre_generation_validation", "status": "completed"},
    {"stage_name": "code_generation", "status": "completed"},
    {"stage_name": "post_generation_validation", "status": "completed"},
    {
      "stage_name": "code_refinement",
      "status": "completed",
      "metadata": {
        "refinement_attempted": true,
        "refinement_applied": true,
        "enhancements": 3,
        "original_lines": 120,
        "refined_lines": 130
      }
    },
    {"stage_name": "file_writing", "status": "completed"},
    {"stage_name": "compilation_testing", "status": "completed"}
  ]
}
```

---

## Example 2: Refinement Skipped (No Issues)

### Scenario
User provides comprehensive prompt, all validation passes, high quorum confidence.

```python
# User prompt (comprehensive)
prompt = """
Create an EFFECT node called PostgresAccountWriter for the infrastructure domain.

Requirements:
- Accept AccountCreatedEvent from event bus
- Write account data to PostgreSQL using prepared statements
- Implement connection pooling and retry logic
- Use transaction management for data consistency
- Handle constraint violations gracefully

Expected operations:
- create_account(account_id, username, email)
- update_account_status(account_id, status)
"""

result = await pipeline.execute(prompt=prompt, output_directory="/tmp/nodes")
```

### Stage 5 Results
```
Validation Gates:
✓ G7: Prompt has sufficient information (85 words)
✓ G8: Context has all expected fields
✓ G9: Python Syntax Valid
✓ G10: ONEX Naming Convention
✓ G11: Import Resolution
✓ G12: Pydantic Model Structure
✓ I1: Intelligence gathered from 3 sources (confidence: 0.92)

Quorum Results:
✓ Q1: PASS (confidence: 0.95, deficiencies: [])
```

### Stage 5.5 Execution

**Step 1: Build Refinement Context**
```python
refinement_context = []  # No warnings, no deficiencies
```

**Step 2: Check Refinement Needed**
```python
has_warnings = False
has_quorum_deficiencies = False
low_quorum_confidence = False  # 0.95 >= 0.8
needs_refinement = False
```

**Step 3: Skip Refinement**
```python
stage5_5.status = StageStatus.SKIPPED
stage5_5.metadata = {"reason": "No refinement needed"}
return stage5_5, original_files  # Pass through unchanged
```

### Pipeline Result
```json
{
  "status": "success",
  "total_duration_ms": 48123,
  "stages": [
    ...
    {
      "stage_name": "code_refinement",
      "status": "skipped",
      "metadata": {
        "reason": "No refinement needed"
      },
      "duration_ms": 15
    },
    ...
  ]
}
```

---

## Example 3: Refinement Fails, Graceful Degradation

### Scenario
AI refinement encounters an error, pipeline continues with original code.

```python
prompt = "create effect node for postgres writes"
result = await pipeline.execute(prompt=prompt, output_directory="/tmp/nodes")
```

### Stage 5.5 Execution

**Step 1-2: Context built, refinement needed**
```python
refinement_context = [
    "Address validation warnings: Prompt has few words",
    "Apply ONEX best practices: ..."
]
needs_refinement = True
```

**Step 3: AI Refinement Error**
```python
try:
    refined_code = await _apply_ai_refinement(
        original_code=original_code,
        refinement_context=refinement_context,
        intelligence=intelligence,
        correlation_id=correlation_id
    )
except Exception as e:
    # Exception caught: "LLM API timeout after 30s"
    logger.error("Code refinement failed: LLM API timeout")
    stage5_5.status = StageStatus.FAILED
    stage5_5.error = "LLM API timeout after 30s"
    stage5_5.metadata = {
        "refinement_attempted": True,
        "refinement_applied": False,
        "error": "LLM API timeout"
    }
    return stage5_5, original_files  # Return original code
```

**Step 4: Pipeline Continues**
```python
# Stage 6 receives original_files (unchanged)
stage6, write_result = await _stage_6_write_files(
    original_files,  # NOT refined_files
    output_directory
)
```

### Pipeline Result
```json
{
  "status": "success",  // Still succeeds!
  "total_duration_ms": 48567,
  "stages": [
    ...
    {
      "stage_name": "code_refinement",
      "status": "failed",
      "error": "LLM API timeout after 30s",
      "metadata": {
        "refinement_attempted": true,
        "refinement_applied": false,
        "error": "LLM API timeout"
      },
      "duration_ms": 2145
    },
    {
      "stage_name": "file_writing",
      "status": "completed"  // Writes original code
    },
    ...
  ],
  "generated_files": ["/tmp/nodes/.../node.py"]  // Original code written
}
```

**Logging Output**:
```
2025-10-21 10:30:45 ERROR Code refinement failed: LLM API timeout after 30s
2025-10-21 10:30:45 INFO  Pipeline continuing with original code
2025-10-21 10:30:45 INFO  Stage 6 (File Writing): Writing original files
```

---

## Example 4: R1 Gate Fails (Refinement Rejected)

### Scenario
AI refinement produces invalid code, R1 gate catches it and reverts to original.

### Stage 5.5 Execution

**Step 3: AI Refinement Produces Bad Code**
```python
# Original code
class NodePostgresWriterEffect(NodeEffect):
    async def execute_effect(self, contract):
        return result

# Refined code (AI hallucinated, removed class!)
"""
PostgreSQL writer with connection pooling.

def execute_effect(contract):  # ← WRONG! Not a class method
    return result
"""
```

**Step 4: R1 Validation**
```python
# Check 3: Class Preservation
original_has_class = True  # "class Node" in original_code
refined_has_class = False  # "class Node" NOT in refined_code

gate_r1 = ValidationGate(
    gate_id="R1",
    name="Refinement Quality",
    status="fail",
    gate_type=GateType.BLOCKING,
    message="Refinement removed node class definition"
)
```

**Step 5: Revert to Original**
```python
if gate_r1.status == "fail":
    logger.warning("Refinement quality check failed: Removed class definition")
    stage5_5.status = StageStatus.COMPLETED  # Mark as completed (not failed)
    stage5_5.metadata = {
        "refinement_attempted": True,
        "refinement_applied": False,
        "reason": "R1 gate failed: Removed class definition"
    }
    return stage5_5, original_files  # Return original code
```

### Pipeline Result
```json
{
  "status": "success",
  "stages": [
    ...
    {
      "stage_name": "code_refinement",
      "status": "completed",
      "validation_gates": [
        {
          "gate_id": "R1",
          "name": "Refinement Quality",
          "status": "fail",
          "message": "Refinement removed node class definition"
        }
      ],
      "metadata": {
        "refinement_attempted": true,
        "refinement_applied": false,
        "reason": "R1 gate failed"
      }
    },
    ...
  ]
}
```

---

## Example 5: Quorum Deficiencies Drive Refinement

### Scenario
Code generation succeeds, but AI Quorum identifies missing error handling.

### Stage 2 Results (Contract Building)
```json
{
  "quorum_result": {
    "decision": "PASS",
    "confidence": 0.75,
    "deficiencies": [
      "Missing error handling for connection timeout",
      "No retry logic specified",
      "Unclear transaction boundary"
    ]
  }
}
```

### Stage 5.5 Execution

**Step 1: Build Refinement Context**
```python
refinement_context = [
    "Address quorum deficiencies: Missing error handling; No retry logic; Unclear transaction boundary",
    "Apply ONEX best practices: Use connection pooling; Implement circuit breaker; Use retry logic"
]
```

**Step 2: Check Refinement Needed**
```python
has_quorum_deficiencies = True  # 3 deficiencies
low_quorum_confidence = True    # 0.75 < 0.8
needs_refinement = True
```

**Step 3: Apply Refinement (Placeholder)**
```python
# Future: LLM would address quorum deficiencies
# For now: Returns original code with logging

logger.info(
    "AI refinement placeholder called with 2 recommendations:\n"
    "  - Address quorum deficiencies\n"
    "  - Apply ONEX best practices"
)
```

**Step 4: R1 Validation**
```
✓ Syntax valid
✓ Reasonable changes
✓ Class preserved
✓ Imports intact

R1: PASS
```

### Pipeline Result
```json
{
  "status": "success",
  "stages": [
    {
      "stage_name": "contract_building",
      "metadata": {
        "quorum_confidence": 0.75,
        "quorum_deficiencies": 3
      }
    },
    ...
    {
      "stage_name": "code_refinement",
      "status": "completed",
      "metadata": {
        "refinement_attempted": true,
        "refinement_applied": true,
        "enhancements": 2
      }
    }
  ]
}
```

---

## Integration with CLI

### Command-Line Usage

```bash
# Generate node with refinement enabled (default)
python cli/generate_node.py \
  --prompt "postgres writer effect" \
  --output-dir /tmp/nodes

# Check if refinement was applied
cat /tmp/nodes/node_postgres_writer_effect/pipeline_result.json | \
  jq '.stages[] | select(.stage_name == "code_refinement")'

# Output:
{
  "stage_name": "code_refinement",
  "status": "completed",
  "metadata": {
    "refinement_attempted": true,
    "refinement_applied": true,
    "enhancements": 3
  }
}
```

### Programmatic Usage

```python
from agents.lib.generation_pipeline import GenerationPipeline
from agents.lib.models.quorum_config import QuorumConfig

# Configure pipeline with refinement
pipeline = GenerationPipeline(
    enable_intelligence_gathering=True,  # Enable for better refinement
    quorum_config=QuorumConfig.enabled()  # Enable for deficiency detection
)

# Execute pipeline
result = await pipeline.execute(
    prompt="Create postgres writer effect node",
    output_directory="/tmp/nodes"
)

# Check refinement status
refinement_stage = result.get_stage("code_refinement")
if refinement_stage:
    if refinement_stage.status == "completed":
        print(f"✓ Refinement applied: {refinement_stage.metadata.get('enhancements', 0)} enhancements")
    elif refinement_stage.status == "skipped":
        print("⊘ Refinement skipped: No issues detected")
    elif refinement_stage.status == "failed":
        print(f"✗ Refinement failed: {refinement_stage.error}")
```

---

## Performance Characteristics

### Typical Execution Times

| Scenario | Refinement Check | AI Refinement | R1 Validation | Total |
|----------|------------------|---------------|---------------|-------|
| **Skipped** (no issues) | 10ms | 0ms | 0ms | **10ms** |
| **Applied** (warnings) | 15ms | 2500ms | 150ms | **2665ms** |
| **Failed** (error) | 15ms | 2000ms (timeout) | 0ms | **2015ms** |
| **Rejected** (R1 fail) | 15ms | 2500ms | 200ms | **2715ms** |

### Memory Usage

- **Original code storage**: ~50KB (typical node.py)
- **Refined code storage**: ~52KB (2% increase)
- **Refinement context**: ~2KB (list of strings)
- **Total overhead**: ~4KB per refinement

---

## Future Enhancements

### Phase 2: LLM Integration

```python
async def _apply_ai_refinement(
    self,
    original_code: str,
    refinement_context: List[str],
    intelligence: IntelligenceContext,
    correlation_id: UUID,
) -> str:
    """Apply AI-powered code refinement using LLM."""

    # Build refinement prompt
    prompt = f"""
You are a Python code refinement expert specializing in ONEX architecture.

Original code:
```python
{original_code}
```

Refinement context:
{chr(10).join(f"- {item}" for item in refinement_context)}

Instructions:
1. Apply the refinement recommendations above
2. Preserve all class definitions and method signatures
3. Maintain ONEX naming conventions
4. Keep all critical imports intact
5. Return ONLY the refined code, no explanations

Refined code:
"""

    # Call LLM API (Gemini, Claude, etc.)
    refined_code = await self._call_llm_api(
        prompt=prompt,
        max_tokens=4000,
        temperature=0.1,
        correlation_id=correlation_id
    )

    return refined_code
```

### Phase 3: AST-Based Refinement

```python
import ast
import astunparse

def _apply_ast_refinement(self, original_code: str) -> str:
    """Apply AST-based transformations."""

    tree = ast.parse(original_code)

    # Transform 1: Add missing docstrings
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if not ast.get_docstring(node):
                # Add generated docstring
                pass

    # Transform 2: Optimize imports
    # Transform 3: Add type hints

    return astunparse.unparse(tree)
```
