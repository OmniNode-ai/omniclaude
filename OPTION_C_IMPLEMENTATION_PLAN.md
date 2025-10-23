# Option C Implementation Plan: Hybrid Autonomous Node Generation Pipeline

**Decision**: REFACTOR & ADAPT - Build fast POC + port omnibase_3 utilities
**Timeline**: 4 phases over 6-8 weeks
**Approach**: Fix critical bugs → Build POC → Port utilities → Enhance pipeline

**Generated**: 2025-10-21
**Status**: Ready for Execution

---

## Executive Summary

### The Strategy

**Option C (Hybrid Approach)** combines the best of both worlds:
- **Fast POC**: Fix critical template bugs and build working prompt → node pipeline (1-2 weeks)
- **Production Quality**: Port proven omnibase_3 utilities for robustness (weeks 3-4)
- **Enhanced Features**: Add advanced capabilities (contract validation, model generation) (weeks 5-6)
- **Future-Proof**: Event bus integration and continuous improvement (week 7+)

### Why Hybrid?

| Aspect | Pure Template (A) | Pure omnibase_3 (B) | **Hybrid (C)** |
|--------|-------------------|---------------------|----------------|
| **Time to POC** | 1-2 weeks | 6-8 weeks | **1-2 weeks** ✅ |
| **Production Quality** | Medium | High | **High** ✅ |
| **Code Reuse** | Low (5%) | High (70%) | **Medium-High (50%)** ✅ |
| **Risk** | Low | Medium | **Low** ✅ |
| **Long-term Value** | Medium | High | **High** ✅ |
| **Total Effort** | 30-40h | 90-120h | **60-80h** ✅ |

### Critical Discovery: Template Import Bugs

**BLOCKING ISSUE** identified in template audit:
```python
# ❌ WRONG (Template currently generates this)
from omnibase_core.core.node_effect import ModelEffectInput
from omnibase_core.core.node_effect import ModelEffectOutput

# ✅ CORRECT (Actual omnibase_core location)
from omnibase_core.nodes.node_effect import NodeEffect
# Input/Output models may not exist - need to generate them!
```

**Impact**: Generated nodes will not compile until templates are fixed.
**Priority**: Phase 1 must fix this before any code generation.

---

## Phase Breakdown

### Phase 1: Critical Fixes + POC Foundation (Week 1-2)
**Goal**: Working prompt → compiled node pipeline
**Effort**: 20-24 hours
**Deliverable**: Generate first working EFFECT node from prompt

#### 1.1 Fix Template Import Bugs (Priority: 🔴 CRITICAL)

**Issue**: Template engine generates invalid import paths
**Location**: `agents/lib/omninode_template_engine.py` lines 476, 502

**Actions**:
1. **Investigate actual omnibase_core I/O model location**
   ```bash
   # Search for actual input/output models
   find ../omnibase_core -name "*.py" | xargs grep -l "class ModelEffectInput"
   find ../omnibase_core -name "*.py" | xargs grep -l "class ModelEffectOutput"
   ```

2. **Update template engine generation logic**
   - **If models exist**: Update import paths to correct location
   - **If models DON'T exist**: Generate them as part of node generation

   ```python
   # Fix in template_engine.py
   def _generate_input_model_import(self, node_type: str) -> str:
       """Generate correct import path for input models."""
       # BEFORE (WRONG):
       # return f"from omnibase_core.core.node_{node_type.lower()} import Model{node_type}Input"

       # AFTER (CORRECT):
       if node_type == "effect":
           return "from omnibase_core.nodes.node_effect import NodeEffect"
       # OR generate input model from scratch if it doesn't exist
       return f"from .models.model_{self.service_name}_input import Model{self.service_name_pascal}Input"
   ```

3. **Fix Pydantic v2 migration**
   - Replace `.dict()` with `.model_dump()` in all templates
   - Lines: effect (96), compute (96), reducer (105), orchestrator (105)

**Estimated Time**: 4-6 hours
**Testing**: Generate EFFECT node, verify imports resolve and code compiles

---

#### 1.2 Create omnibase_core Compatibility Validator (Priority: 🔴 HIGH)

**Purpose**: Prevent generation failures by validating imports BEFORE code generation

**Implementation**:
```python
# New file: agents/lib/omnibase_core_validator.py
from importlib import import_module
from typing import Dict, List
from dataclasses import dataclass

@dataclass
class ImportValidationResult:
    """Result of import validation."""
    import_path: str
    exists: bool
    error_message: str | None = None

class OmnibaseCoreValidator:
    """Validate omnibase_core imports before code generation."""

    CRITICAL_IMPORTS = [
        "omnibase_core.errors.error_codes.EnumCoreErrorCode",
        "omnibase_core.errors.model_onex_error.ModelOnexError",
        "omnibase_core.models.container.model_onex_container.ModelONEXContainer",
        "omnibase_core.nodes.node_effect.NodeEffect",
        "omnibase_core.nodes.node_compute.NodeCompute",
        "omnibase_core.nodes.node_reducer.NodeReducer",
        "omnibase_core.nodes.node_orchestrator.NodeOrchestrator",
    ]

    def validate_all_imports(self) -> Dict[str, ImportValidationResult]:
        """Validate all critical imports exist."""
        results = {}
        for import_path in self.CRITICAL_IMPORTS:
            results[import_path] = self._validate_import(import_path)
        return results

    def _validate_import(self, import_path: str) -> ImportValidationResult:
        """Validate single import path."""
        try:
            module_path, class_name = import_path.rsplit(".", 1)
            module = import_module(module_path)

            if not hasattr(module, class_name):
                return ImportValidationResult(
                    import_path=import_path,
                    exists=False,
                    error_message=f"Class '{class_name}' not found in module '{module_path}'"
                )

            return ImportValidationResult(import_path=import_path, exists=True)

        except ImportError as e:
            return ImportValidationResult(
                import_path=import_path,
                exists=False,
                error_message=str(e)
            )

    def get_failing_imports(self) -> List[str]:
        """Get list of imports that fail validation."""
        results = self.validate_all_imports()
        return [path for path, result in results.items() if not result.exists]

    def raise_if_invalid(self) -> None:
        """Raise exception if any critical imports are invalid."""
        failing = self.get_failing_imports()
        if failing:
            raise ValueError(
                f"Critical omnibase_core imports are invalid:\n" +
                "\n".join(f"  ❌ {path}" for path in failing)
            )
```

**Integration**:
```python
# In template_engine.py, add validation step
def generate_node(self, context: Dict[str, Any]) -> GeneratedNode:
    """Generate node with validation."""
    # Validate omnibase_core compatibility FIRST
    validator = OmnibaseCoreValidator()
    validator.raise_if_invalid()  # Fails fast if imports won't work

    # Proceed with generation...
    return self._generate_node_from_template(context)
```

**Estimated Time**: 3-4 hours
**Testing**: Run validator against current omnibase_core, verify all imports

---

#### 1.3 Build Simple POC Pipeline (Priority: 🔴 HIGH)

**Goal**: Prompt → validated, compiled node (end-to-end)

**Architecture**:
```
┌─────────────────────────────────────┐
│  Prompt (Natural Language)          │
│  "Create EFFECT node for Postgres"  │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  PRD Parser (LLM-based)             │
│  - Extract node type                │
│  - Identify operations               │
│  - Parse features                   │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Template Engine (Existing)         │
│  - Load templates                   │
│  - Replace placeholders             │
│  - Generate files                   │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Validator (New)                    │
│  - Import validation                │
│  - Syntax check (AST)               │
│  - ONEX compliance                  │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  File Writer                        │
│  - Create directory structure       │
│  - Write files                      │
│  - Generate manifests               │
└─────────────────────────────────────┘
```

**Implementation**:
```python
# New file: agents/lib/generation_pipeline.py
from pathlib import Path
from typing import Dict, Any
from .omninode_template_engine import OmninodeTemplateEngine
from .omnibase_core_validator import OmnibaseCoreValidator
from .prd_parser import PRDParser
import ast

class GenerationPipeline:
    """Simple POC pipeline: Prompt → Node."""

    def __init__(self):
        self.template_engine = OmninodeTemplateEngine()
        self.validator = OmnibaseCoreValidator()
        self.prd_parser = PRDParser()

    def generate_from_prompt(
        self,
        prompt: str,
        output_dir: Path,
        repository_name: str = "omniclaude"
    ) -> Dict[str, Any]:
        """
        Generate node from natural language prompt.

        Args:
            prompt: Natural language description
            output_dir: Where to write generated files
            repository_name: Target repository

        Returns:
            Generation result with paths and metadata
        """
        # Step 1: Parse PRD from prompt (LLM-based)
        prd_data = self.prd_parser.parse_prompt(prompt)

        # Step 2: Validate omnibase_core compatibility
        self.validator.raise_if_invalid()

        # Step 3: Prepare template context
        context = {
            "MICROSERVICE_NAME": prd_data["service_name"],
            "MICROSERVICE_NAME_PASCAL": prd_data["service_name_pascal"],
            "NODE_TYPE": prd_data["node_type"],
            "DOMAIN": prd_data["domain"],
            "REPOSITORY_NAME": repository_name,
            "BUSINESS_DESCRIPTION": prd_data["description"],
            "OPERATIONS": prd_data["operations"],
            # ... more context
        }

        # Step 4: Generate code from templates
        generated_files = self.template_engine.generate_node(context)

        # Step 5: Validate generated code
        self._validate_generated_code(generated_files)

        # Step 6: Write files to disk
        written_paths = self._write_files(generated_files, output_dir)

        return {
            "success": True,
            "node_type": prd_data["node_type"],
            "service_name": prd_data["service_name"],
            "files_written": written_paths,
            "validation_passed": True
        }

    def _validate_generated_code(self, generated_files: Dict[str, str]) -> None:
        """Validate generated code compiles and imports resolve."""
        for file_path, code in generated_files.items():
            if not file_path.endswith(".py"):
                continue

            # Syntax validation via AST
            try:
                ast.parse(code)
            except SyntaxError as e:
                raise ValueError(f"Generated code has syntax error in {file_path}: {e}")

            # TODO: Import validation (Phase 2)

    def _write_files(
        self,
        generated_files: Dict[str, str],
        output_dir: Path
    ) -> List[Path]:
        """Write generated files to disk."""
        written = []
        for relative_path, content in generated_files.items():
            full_path = output_dir / relative_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            written.append(full_path)
        return written
```

**PRD Parser** (LLM-based extraction):
```python
# New file: agents/lib/prd_parser.py
import re
from typing import Dict, Any, List

class PRDParser:
    """Parse natural language prompts into structured PRD data."""

    NODE_TYPE_KEYWORDS = {
        "effect": ["api", "database", "external", "write", "read", "fetch"],
        "compute": ["calculate", "transform", "process", "validate", "filter"],
        "reducer": ["aggregate", "combine", "reduce", "summarize", "state"],
        "orchestrator": ["workflow", "coordinate", "orchestrate", "pipeline"]
    }

    def parse_prompt(self, prompt: str) -> Dict[str, Any]:
        """
        Parse natural language prompt into PRD structure.

        Uses keyword matching + LLM for complex parsing.
        """
        # Detect node type
        node_type = self._detect_node_type(prompt)

        # Extract service name (simple heuristic for POC)
        service_name = self._extract_service_name(prompt)

        # Extract domain (from context or keywords)
        domain = self._extract_domain(prompt)

        # Extract operations (LLM-based or regex)
        operations = self._extract_operations(prompt, node_type)

        return {
            "node_type": node_type,
            "service_name": service_name,
            "service_name_pascal": self._to_pascal_case(service_name),
            "domain": domain,
            "description": prompt,
            "operations": operations,
            "features": self._extract_features(prompt)
        }

    def _detect_node_type(self, prompt: str) -> str:
        """Detect node type from keywords."""
        prompt_lower = prompt.lower()

        # Check for explicit type mention
        for node_type in ["effect", "compute", "reducer", "orchestrator"]:
            if node_type in prompt_lower:
                return node_type.upper()

        # Keyword-based detection
        scores = {}
        for node_type, keywords in self.NODE_TYPE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in prompt_lower)
            scores[node_type] = score

        # Return highest scoring type
        best_type = max(scores, key=scores.get)
        return best_type.upper()

    def _extract_service_name(self, prompt: str) -> str:
        """Extract service name from prompt."""
        # Simple regex: "for <service_name>"
        match = re.search(r"for\s+(\w+)", prompt, re.IGNORECASE)
        if match:
            return match.group(1).lower()

        # Fallback: use first noun
        words = re.findall(r"\b[a-z_]+\b", prompt.lower())
        return words[0] if words else "generic_service"

    def _extract_domain(self, prompt: str) -> str:
        """Extract domain from prompt."""
        # TODO: LLM-based domain extraction
        # For POC: simple keyword matching
        domain_keywords = {
            "infrastructure": ["database", "api", "storage"],
            "business": ["order", "payment", "user"],
            "analytics": ["metrics", "reporting", "data"]
        }

        prompt_lower = prompt.lower()
        for domain, keywords in domain_keywords.items():
            if any(kw in prompt_lower for kw in keywords):
                return domain

        return "general"

    def _extract_operations(self, prompt: str, node_type: str) -> List[str]:
        """Extract operation types from prompt."""
        # Default operations by node type
        defaults = {
            "EFFECT": ["create", "read", "update", "delete"],
            "COMPUTE": ["process", "validate", "transform"],
            "REDUCER": ["aggregate", "combine", "reduce"],
            "ORCHESTRATOR": ["execute_workflow", "coordinate"]
        }
        return defaults.get(node_type, ["execute"])

    def _extract_features(self, prompt: str) -> List[str]:
        """Extract top features from prompt."""
        # TODO: LLM-based feature extraction
        return ["Feature 1", "Feature 2", "Feature 3"]

    def _to_pascal_case(self, snake_case: str) -> str:
        """Convert snake_case to PascalCase."""
        return "".join(word.capitalize() for word in snake_case.split("_"))
```

**Estimated Time**: 10-12 hours
**Testing**: Generate complete node from prompt, verify compilation

---

#### 1.4 POC Testing & Validation (Priority: 🟡 MEDIUM)

**Test Cases**:
1. **EFFECT node for PostgreSQL**
   ```python
   result = pipeline.generate_from_prompt(
       prompt="Create EFFECT node for PostgreSQL database operations",
       output_dir=Path("src/nodes/postgres_adapter_effect")
   )
   assert result["success"]
   assert len(result["files_written"]) >= 5  # node.py, input/output models, etc.
   ```

2. **COMPUTE node for price calculation**
   ```python
   result = pipeline.generate_from_prompt(
       prompt="Create COMPUTE node for price calculation with tax and discounts",
       output_dir=Path("src/nodes/price_calculator_compute")
   )
   # Verify generated code compiles
   assert all(Path(p).exists() for p in result["files_written"])
   ```

3. **Import validation**
   ```bash
   # Generated node should import successfully
   poetry run python -c "from src.nodes.postgres_adapter_effect.v1_0_0.node import NodePostgresAdapterEffect"
   ```

**Success Criteria**:
- ✅ Generated node compiles without syntax errors
- ✅ All imports resolve successfully
- ✅ ONEX naming conventions followed
- ✅ Pydantic models validate correctly
- ✅ File structure matches ONEX standards

**Estimated Time**: 3-4 hours

---

### Phase 2: Port omnibase_3 Contract Validation (Week 3-4)
**Goal**: Production-grade contract validation and analysis
**Effort**: 20-25 hours
**Deliverable**: Contract-driven generation with validation

#### 2.1 Extract Contract Validation Utilities (Priority: 🔴 HIGH)

**Source Files** (from omnibase_3):
```
omnibase_3/src/omnibase/utils/generation/
├── utility_contract_analyzer.py (658 LOC)
├── utility_reference_resolver.py (303 LOC)
└── utility_schema_loader.py (205 LOC)

Total: ~1166 LOC to adapt
```

**Adaptation Strategy**:
```python
# Target location: agents/lib/generation/
omniclaude/agents/lib/generation/
├── contract_analyzer.py      # From utility_contract_analyzer.py
├── reference_resolver.py     # From utility_reference_resolver.py
└── schema_loader.py          # From utility_schema_loader.py
```

**Import Migration Table**:
| omnibase_3 Import | omnibase_core/omniclaude Replacement |
|-------------------|--------------------------------------|
| `from omnibase.core.node_base` | `from omnibase_core.core.infrastructure_service_bases` |
| `from omnibase.model.core.model_schema` | `from omnibase_core.models.contracts` |
| `from omnibase.exceptions` | `from omnibase_core.errors.model_onex_error` |
| `from omnibase.core.core_error_codes` | `from omnibase_core.errors.error_codes` |

**Adaptation Work**:
1. **Remove "Utility" prefix**: `UtilityContractAnalyzer` → `ContractAnalyzer`
2. **Update imports**: Replace all omnibase_3 imports with omnibase_core equivalents
3. **Simplify error handling**: Use omnibase_core error patterns
4. **Remove event bus dependencies**: Use simple logging for POC
5. **Test in isolation**: Verify each utility works standalone

**Example Adaptation**:
```python
# BEFORE (omnibase_3):
from omnibase.core.node_base import NodeBase
from omnibase.model.core.model_schema import ModelSchema
from omnibase.exceptions import OnexError

class UtilityContractAnalyzer:
    def __init__(self, container):
        self.container = container
        self.logger = container.logger

# AFTER (omniclaude):
from omnibase_core.models.contracts.model_contract_base import ModelContractBase
from omnibase_core.errors.model_onex_error import ModelOnexError
import logging

class ContractAnalyzer:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def load_contract(self, contract_path: Path) -> ModelContractBase:
        """Load and parse contract YAML."""
        # Same logic, updated error handling
```

**Estimated Time**: 12-15 hours
**Testing**: Load sample contracts, verify parsing and validation

---

#### 2.2 Integrate Contract Validation into Pipeline (Priority: 🟡 MEDIUM)

**Enhanced Pipeline**:
```python
class GenerationPipeline:
    def __init__(self):
        self.template_engine = OmninodeTemplateEngine()
        self.validator = OmnibaseCoreValidator()
        self.prd_parser = PRDParser()
        # NEW: Contract validation
        self.contract_analyzer = ContractAnalyzer()
        self.reference_resolver = ReferenceResolver()

    def generate_from_contract(
        self,
        contract_path: Path,
        output_dir: Path
    ) -> Dict[str, Any]:
        """Generate node from YAML contract (contract-driven)."""
        # Phase 1: Load and validate contract
        contract = self.contract_analyzer.load_contract(contract_path)

        # Phase 2: Resolve references
        resolved_contract = self.reference_resolver.resolve_all_refs(contract)

        # Phase 3: Extract generation context from contract
        context = self._extract_context_from_contract(resolved_contract)

        # Phase 4: Generate code (same as prompt-based)
        generated_files = self.template_engine.generate_node(context)

        # Phase 5: Validate and write
        self._validate_generated_code(generated_files)
        written_paths = self._write_files(generated_files, output_dir)

        return {
            "success": True,
            "contract_version": contract.version,
            "files_written": written_paths
        }
```

**Estimated Time**: 6-8 hours
**Testing**: Generate nodes from YAML contracts, verify correctness

---

#### 2.3 Add Contract Quality Gates (Priority: 🟢 LOW)

**Quality Checks**:
1. **Schema compliance**: Validate contract against ONEX schema
2. **Required fields**: Ensure all mandatory fields present
3. **Type consistency**: Validate type definitions
4. **Reference integrity**: All $ref references resolve
5. **Performance requirements**: Node type has appropriate SLAs

**Implementation**:
```python
class ContractQualityGates:
    """Quality gates for contract validation."""

    def validate_contract_quality(self, contract: ModelContractBase) -> ValidationResult:
        """Run all quality gates."""
        results = []

        # Gate 1: Schema compliance
        results.append(self._check_schema_compliance(contract))

        # Gate 2: Required fields
        results.append(self._check_required_fields(contract))

        # Gate 3: Type consistency
        results.append(self._check_type_consistency(contract))

        # Gate 4: Reference integrity
        results.append(self._check_reference_integrity(contract))

        # Gate 5: Performance requirements
        results.append(self._check_performance_requirements(contract))

        return ValidationResult(
            passed=all(r.passed for r in results),
            gates=results
        )
```

**Estimated Time**: 2-3 hours

---

### Phase 3: Port Model Generation Utilities (Week 5-6)
**Goal**: AST-based model generation for production quality
**Effort**: 20-25 hours
**Deliverable**: Automatic Pydantic model generation from contracts

#### 3.1 Extract AST & Type Mapping Utilities (Priority: 🔴 HIGH)

**Source Files** (from omnibase_3):
```
omnibase_3/src/omnibase/utils/generation/
├── utility_ast_builder.py (479 LOC)
├── utility_type_mapper.py (330 LOC)
├── utility_enum_generator.py (440 LOC)
└── utility_schema_composer.py (301 LOC)

Total: ~1550 LOC to adapt
```

**Target Location**:
```
omniclaude/agents/lib/generation/
├── ast_builder.py           # Core AST manipulation
├── type_mapper.py           # Schema → Python type mapping
├── enum_generator.py        # Enum class generation
└── schema_composer.py       # Schema composition
```

**Key Adaptations**:
1. **AST Builder**: Keep core logic, update type hints
2. **Type Mapper**: Add omnibase_core-specific type mappings
3. **Enum Generator**: Update naming conventions (EnumXxx pattern)
4. **Schema Composer**: Simplify for POC, remove advanced features

**Example Adaptation**:
```python
# BEFORE (omnibase_3 - utility_ast_builder.py):
class UtilityASTBuilder:
    def generate_model_class(
        self,
        class_name: str,
        schema: ModelSchema,
        base_class: str = "BaseModel"
    ) -> ast.ClassDef:
        """Generate Pydantic model class from schema."""
        # Complex AST generation...

# AFTER (omniclaude - ast_builder.py):
class ASTBuilder:
    def generate_model_class(
        self,
        class_name: str,
        schema: Dict[str, Any],  # Simplified schema type
        base_class: str = "BaseModel"
    ) -> ast.ClassDef:
        """Generate Pydantic model class from schema."""
        # Same core logic, simplified types
```

**Estimated Time**: 15-18 hours
**Testing**: Generate models from schemas, verify AST correctness

---

#### 3.2 Integrate Model Generation into Pipeline (Priority: 🔴 HIGH)

**Enhanced Generation**:
```python
class GenerationPipeline:
    def __init__(self):
        # Existing components...
        self.contract_analyzer = ContractAnalyzer()

        # NEW: Model generation
        self.ast_builder = ASTBuilder()
        self.type_mapper = TypeMapper()
        self.enum_generator = EnumGenerator()

    def generate_from_contract(self, contract_path: Path, output_dir: Path):
        """Generate with automatic model creation."""
        # Load contract
        contract = self.contract_analyzer.load_contract(contract_path)

        # NEW: Generate models from contract definitions
        models = self._generate_models_from_contract(contract)
        enums = self._generate_enums_from_contract(contract)

        # Merge generated models with template-based code
        all_files = {
            **self._generate_node_from_template(contract),
            **models,
            **enums
        }

        # Write and validate
        return self._write_and_validate(all_files, output_dir)

    def _generate_models_from_contract(
        self,
        contract: ModelContractBase
    ) -> Dict[str, str]:
        """Generate Pydantic models from contract definitions."""
        generated_models = {}

        for model_name, schema in contract.definitions.items():
            # Generate AST
            ast_class = self.ast_builder.generate_model_class(
                class_name=f"Model{model_name}",
                schema=schema
            )

            # Convert AST to Python code
            code = ast.unparse(ast_class)

            # Store in files dict
            file_path = f"models/model_{model_name.lower()}.py"
            generated_models[file_path] = code

        return generated_models
```

**Estimated Time**: 5-7 hours
**Testing**: Generate complete nodes with models, verify compilation

---

### Phase 4: Pipeline Enhancement & Event Bus (Week 7+)
**Goal**: Production-ready pipeline with event bus integration
**Effort**: 15-20 hours
**Deliverable**: Autonomous generation over event bus

#### 4.1 Event Bus Integration (Priority: 🟡 MEDIUM)

**Architecture**:
```
Event Bus (Kafka/Redis)
    ↓
┌─────────────────────────────────────┐
│  Generation Request Handler         │
│  - Listen: "node.generation.request"│
│  - Publish: "node.generation.status"│
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Generation Pipeline                │
│  (All phases from 1-3)              │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Result Publisher                   │
│  - Publish: "node.generation.complete"│
│  - Include: File paths, metadata    │
└─────────────────────────────────────┘
```

**Event Schemas**:
```python
class ModelGenerationRequest(BaseModel):
    """Event: Request node generation."""
    request_id: UUID
    prompt: str | None = None
    contract_path: Path | None = None
    output_dir: Path
    repository_name: str
    correlation_id: UUID

class ModelGenerationStatus(BaseModel):
    """Event: Generation progress update."""
    request_id: UUID
    status: Literal["started", "validating", "generating", "writing", "completed", "failed"]
    progress_percent: int
    current_phase: str
    correlation_id: UUID

class ModelGenerationComplete(BaseModel):
    """Event: Generation completed successfully."""
    request_id: UUID
    success: bool
    files_written: List[Path]
    node_type: str
    service_name: str
    error_message: str | None = None
    correlation_id: UUID
```

**Estimated Time**: 8-10 hours
**Testing**: Send generation requests via event bus, verify responses

---

#### 4.2 Continuous Improvement & Learning (Priority: 🟢 LOW)

**Features**:
1. **Template versioning**: Track template changes
2. **Generation analytics**: Success rates, performance metrics
3. **Pattern learning**: Learn from successful generations
4. **Auto-optimization**: Improve templates based on usage

**Implementation**: Use Archon MCP for intelligence gathering
```python
# Example: Learn from successful generations
await mcp_client.call(
    "archon_menu",
    operation="track_pattern_creation",
    params={
        "pattern_type": "node_generation",
        "metadata": {
            "node_type": "effect",
            "success": True,
            "quality_score": 0.95,
            "generation_time_ms": 1250
        }
    }
)
```

**Estimated Time**: 5-8 hours

---

## Import Migration Strategy

### Critical Import Path Updates

**Problem**: Templates generate invalid import paths that don't exist in omnibase_core

**Solution**: Systematic import path migration

#### 1. Template Import Fixes

| Template File | Line | Current (WRONG) | Corrected |
|---------------|------|-----------------|-----------|
| `template_engine.py` | 476 | `omnibase_core.core.node_effect` | `omnibase_core.nodes.node_effect` |
| `template_engine.py` | 502 | `omnibase_core.core.node_effect` | `omnibase_core.nodes.node_effect` |
| All node templates | Various | `.dict()` | `.model_dump()` |
| `template_engine.py` | 16, 220 | `OnexError` | `ModelOnexError` |

#### 2. omnibase_3 Utility Import Updates

**Comprehensive Mapping**:
```python
# Import migration map for omnibase_3 → omnibase_core
IMPORT_MIGRATIONS = {
    # Base classes
    "omnibase.core.node_base.NodeBase": "omnibase_core.core.infrastructure_service_bases.NodeCoreBase",

    # Container
    "omnibase.core.onex_container.ONEXContainer": "omnibase_core.models.container.model_onex_container.ModelONEXContainer",

    # Errors
    "omnibase.exceptions.OnexError": "omnibase_core.errors.model_onex_error.ModelOnexError",
    "omnibase.core.core_error_codes.CoreErrorCode": "omnibase_core.errors.error_codes.EnumCoreErrorCode",

    # Models
    "omnibase.model.core.model_schema.ModelSchema": "omnibase_core.models.contracts.model_contract_base.ModelContractBase",
    "omnibase.model.core.model_semver.ModelSemVer": "omnibase_core.primitives.model_semver.ModelSemVer",

    # Protocols
    "omnibase.protocol.protocol_ast_builder.ProtocolASTBuilder": "# Remove protocol dependency for POC",

    # Logging
    "omnibase.core.core_structured_logging.emit_log_event_sync": "logging.getLogger(__name__).info",
}
```

**Automated Migration Script**:
```python
# scripts/migrate_imports.py
import re
from pathlib import Path

def migrate_imports(file_path: Path, migration_map: dict) -> str:
    """Migrate imports in a Python file."""
    content = file_path.read_text()

    for old_import, new_import in migration_map.items():
        # Handle "from X import Y" pattern
        old_module, old_class = old_import.rsplit(".", 1)
        new_module, new_class = new_import.rsplit(".", 1)

        pattern = rf"from {re.escape(old_module)} import {re.escape(old_class)}"
        replacement = f"from {new_module} import {new_class}"

        content = re.sub(pattern, replacement, content)

    return content

# Usage
for util_file in Path("agents/lib/generation").glob("*.py"):
    migrated = migrate_imports(util_file, IMPORT_MIGRATIONS)
    util_file.write_text(migrated)
```

#### 3. Validation Checklist

After migration, verify:
- [ ] All imports resolve successfully
- [ ] No `omnibase.` imports remain (should be `omnibase_core.`)
- [ ] Error handling uses `ModelOnexError`
- [ ] Container uses `ModelONEXContainer`
- [ ] Pydantic models use `.model_dump()` not `.dict()`
- [ ] Node classes inherit from `NodeCoreBase` or service bases

---

## POC Scope Definition

### Minimal Viable Features

**In Scope for POC** (Week 1-2):
1. ✅ **Prompt-based generation**: Natural language → Node
2. ✅ **Template-based code**: Use existing templates
3. ✅ **Basic validation**: Import checks, syntax validation
4. ✅ **File writing**: Create correct directory structure
5. ✅ **Single node type**: Focus on EFFECT nodes initially

**Out of Scope for POC**:
1. ❌ **Contract-driven generation**: Phase 2
2. ❌ **AST-based model generation**: Phase 3
3. ❌ **Event bus integration**: Phase 4
4. ❌ **Advanced quality gates**: Phase 2+
5. ❌ **Multi-node orchestration**: Future

### POC Success Criteria

**Must Achieve**:
- ✅ Generate compilable EFFECT node from prompt in <2 minutes
- ✅ All generated imports resolve successfully
- ✅ Code passes `poetry run mypy` type checking
- ✅ ONEX naming conventions followed (suffix-based)
- ✅ Directory structure matches omnibase_core standards
- ✅ No manual fixes required to generated code

**Test Case**:
```python
# POC acceptance test
def test_poc_end_to_end():
    """Test complete POC flow."""
    pipeline = GenerationPipeline()

    # Generate from prompt
    result = pipeline.generate_from_prompt(
        prompt="Create EFFECT node for PostgreSQL database write operations",
        output_dir=Path("src/nodes/postgres_writer_effect")
    )

    # Verify success
    assert result["success"]
    assert result["node_type"] == "EFFECT"
    assert len(result["files_written"]) >= 5

    # Verify compilation
    node_file = Path("src/nodes/postgres_writer_effect/v1_0_0/node.py")
    assert node_file.exists()

    # Verify import
    import sys
    sys.path.insert(0, "src")
    from nodes.postgres_writer_effect.v1_0_0.node import NodePostgresWriterEffect

    # Verify type checking
    result = subprocess.run(
        ["poetry", "run", "mypy", str(node_file)],
        capture_output=True
    )
    assert result.returncode == 0  # No type errors
```

---

## Utility Porting Prioritization

### High Priority (Phase 2)
**Reason**: Contract validation is critical for production quality

| Utility | Source LOC | Adaptation Effort | Value |
|---------|-----------|-------------------|-------|
| `utility_contract_analyzer.py` | 658 | 12h | Critical - contract parsing |
| `utility_reference_resolver.py` | 303 | 6h | High - $ref resolution |
| `utility_schema_loader.py` | 205 | 4h | High - YAML loading |

**Total**: 1166 LOC, 22 hours, **Critical Value**

### Medium Priority (Phase 3)
**Reason**: AST generation provides production-grade model creation

| Utility | Source LOC | Adaptation Effort | Value |
|---------|-----------|-------------------|-------|
| `utility_ast_builder.py` | 479 | 10h | High - AST generation |
| `utility_type_mapper.py` | 330 | 6h | High - Type mapping |
| `utility_enum_generator.py` | 440 | 8h | Medium - Enum generation |
| `utility_schema_composer.py` | 301 | 5h | Medium - Schema composition |

**Total**: 1550 LOC, 29 hours, **High Value**

### Low Priority (Phase 4+)
**Reason**: Advanced features for optimization

| Utility | Source LOC | Adaptation Effort | Value |
|---------|-----------|-------------------|-------|
| `tool_workflow_generator` | ~500 | 15h | Medium - Workflow generation |
| `tool_protocol_generator` | ~300 | 8h | Low - Protocol generation |
| `tool_ast_renderer` | ~200 | 5h | Low - AST to Python |

**Total**: ~1000 LOC, 28 hours, **Medium Value**

---

## Risk Mitigation

### Technical Risks

#### Risk 1: Template Import Path Bugs 🔴
**Probability**: High (100% - already identified)
**Impact**: Critical (blocks all code generation)

**Mitigation**:
1. ✅ **Immediate Fix**: Phase 1.1 fixes invalid import paths
2. ✅ **Validation**: OmnibaseCoreValidator prevents future issues
3. ✅ **Testing**: Integration tests verify all imports resolve
4. ✅ **Rollback**: Keep original templates until migration validated

**Contingency**: If imports can't be fixed, generate models from scratch (fallback to omnibase_3 approach)

---

#### Risk 2: omnibase_3 Utility Adaptation Complexity 🟡
**Probability**: Medium (60%)
**Impact**: Medium (delays Phase 2/3)

**Mitigation**:
1. ✅ **Phased Approach**: Port utilities incrementally, test each one
2. ✅ **Simplification**: Remove advanced features for POC
3. ✅ **Fallback**: Template-based generation still works (Phase 1)
4. ✅ **Documentation**: Document all import migrations

**Contingency**: If adaptation takes >30h, defer to Phase 4 and ship POC without AST generation

---

#### Risk 3: Event Bus Integration Complexity 🟢
**Probability**: Low (30%)
**Impact**: Low (only affects Phase 4)

**Mitigation**:
1. ✅ **Deferred**: Event bus is Phase 4, not critical for POC
2. ✅ **Simple Events**: Use basic event schemas, avoid complex orchestration
3. ✅ **Gradual Integration**: Add event bus incrementally

**Contingency**: If event bus integration fails, use REST API or CLI interface instead

---

### Process Risks

#### Risk 4: Scope Creep 🟡
**Probability**: Medium (50%)
**Impact**: Medium (timeline delays)

**Mitigation**:
1. ✅ **Strict POC Definition**: Phase 1 scope locked
2. ✅ **Phase Gates**: Approval required before starting next phase
3. ✅ **Backlog Management**: Defer non-critical features

**Contingency**: If timeline slips, deliver Phase 1 POC first, defer Phase 2/3

---

#### Risk 5: omnibase_core Breaking Changes 🔴
**Probability**: Low (20%)
**Impact**: Critical (invalidates all work)

**Mitigation**:
1. ✅ **Version Pinning**: Pin omnibase_core to specific version
2. ✅ **Compatibility Tests**: Run tests against omnibase_core updates
3. ✅ **Version Matrix**: Document supported omnibase_core versions

**Contingency**: If breaking changes occur, create adapter layer or fork omnibase_core

---

## Timeline & Resources

### Gantt Chart Overview

```
Week 1-2 (Phase 1): Critical Fixes + POC
┌─────────────────────────────────────────────┐
│ ████████████████ Fix Templates (4-6h)       │
│     ████████ Validator (3-4h)               │
│         ████████████ POC Pipeline (10-12h)  │
│                 ████ Testing (3-4h)         │
└─────────────────────────────────────────────┘

Week 3-4 (Phase 2): Contract Validation
┌─────────────────────────────────────────────┐
│ ████████████████████ Extract Utils (12-15h) │
│             ████████ Integration (6-8h)     │
│                 ████ Quality Gates (2-3h)   │
└─────────────────────────────────────────────┘

Week 5-6 (Phase 3): Model Generation
┌─────────────────────────────────────────────┐
│ ████████████████████████ Extract AST (15-18h)│
│                     ████████ Integration (5-7h)│
└─────────────────────────────────────────────┘

Week 7+ (Phase 4): Enhancements
┌─────────────────────────────────────────────┐
│ ████████████ Event Bus (8-10h)              │
│         ████████ Learning (5-8h)            │
└─────────────────────────────────────────────┘
```

### Resource Requirements

**Phase 1** (Week 1-2):
- **Personnel**: 1 senior developer
- **Effort**: 20-24 hours
- **Dependencies**: Access to omnibase_core source
- **Tools**: Python 3.11+, Poetry, VSCode

**Phase 2** (Week 3-4):
- **Personnel**: 1 senior developer
- **Effort**: 20-25 hours
- **Dependencies**: omnibase_3 source code access
- **Tools**: AST manipulation tools, YAML validators

**Phase 3** (Week 5-6):
- **Personnel**: 1 senior developer
- **Effort**: 20-25 hours
- **Dependencies**: Phase 2 completion
- **Tools**: Python AST library, type checkers

**Phase 4** (Week 7+):
- **Personnel**: 1 senior developer (part-time)
- **Effort**: 15-20 hours
- **Dependencies**: Event bus infrastructure
- **Tools**: Kafka/Redis, Archon MCP client

**Total**: 75-94 hours over 7-8 weeks (1 senior developer)

---

## Parallel Execution Opportunities

### What Can Run in Parallel

#### Phase 1 Parallelization

**Team A** (Template Fixes):
- Fix import path bugs
- Update Pydantic v2 migrations
- Create compatibility validator

**Team B** (POC Development):
- Build PRD parser
- Implement file writer
- Create integration tests

**Coordination**: Teams sync after template fixes complete

---

#### Phase 2 Parallelization

**Team A** (Contract Utilities):
- Port contract analyzer
- Port reference resolver

**Team B** (Quality Gates):
- Build quality validation framework
- Create contract test suite

**Coordination**: Merge at integration step

---

#### Phase 3 Parallelization

**Team A** (AST Generation):
- Port AST builder
- Port type mapper

**Team B** (Enum & Schema):
- Port enum generator
- Port schema composer

**Coordination**: Both teams needed for integration

---

### Single Developer Timeline

If only 1 developer available:
- **Phase 1**: 2 weeks (sequential)
- **Phase 2**: 2 weeks (sequential)
- **Phase 3**: 2 weeks (sequential)
- **Phase 4**: 1-2 weeks (partial parallel)

**Total**: 7-8 weeks

### Two Developer Timeline

If 2 developers available:
- **Phase 1**: 1.5 weeks (60% parallel)
- **Phase 2**: 1.5 weeks (70% parallel)
- **Phase 3**: 1.5 weeks (80% parallel)
- **Phase 4**: 1 week (50% parallel)

**Total**: 5.5-6 weeks (25% faster)

---

## Success Metrics

### Phase 1 Success Criteria

**Functional**:
- [ ] Generate EFFECT node from prompt in <2 minutes
- [ ] All generated code compiles without errors
- [ ] All imports resolve successfully
- [ ] ONEX naming conventions followed (100%)
- [ ] Directory structure matches standards

**Quality**:
- [ ] `poetry run mypy` passes (0 type errors)
- [ ] `poetry run ruff check` passes (0 lint errors)
- [ ] Generated code has >80% test coverage (if tests generated)

**Performance**:
- [ ] Generation time: <2 minutes end-to-end
- [ ] Template rendering: <500ms
- [ ] Validation: <1 second

---

### Phase 2 Success Criteria

**Functional**:
- [ ] Generate node from YAML contract
- [ ] All contract references ($ref) resolve
- [ ] Contract validation identifies errors
- [ ] Quality gates execute in <5 seconds

**Quality**:
- [ ] Contract schema compliance: 100%
- [ ] Reference resolution: 100% success rate
- [ ] Contract validation accuracy: >95%

---

### Phase 3 Success Criteria

**Functional**:
- [ ] Auto-generate Pydantic models from schemas
- [ ] Auto-generate enums from contract definitions
- [ ] AST-based code generation works for all node types
- [ ] Type annotations are 100% correct

**Quality**:
- [ ] Generated models pass Pydantic validation
- [ ] No `Any` types in generated code (ZERO TOLERANCE)
- [ ] All models have docstrings and field descriptions

---

### Phase 4 Success Criteria

**Functional**:
- [ ] Event bus integration works end-to-end
- [ ] Generation requests received and processed
- [ ] Status updates published during generation
- [ ] Completion events published with results

**Performance**:
- [ ] Event processing latency: <100ms
- [ ] End-to-end generation time: <3 minutes
- [ ] Event bus throughput: >10 requests/minute

---

## Risk Register

### Risk Matrix

| Risk ID | Risk | Probability | Impact | Severity | Mitigation | Owner |
|---------|------|-------------|--------|----------|------------|-------|
| **R-001** | Template import bugs block generation | High (100%) | Critical | 🔴 **HIGH** | Fix in Phase 1.1 | Dev Team |
| **R-002** | omnibase_3 adaptation complexity | Medium (60%) | Medium | 🟡 **MEDIUM** | Incremental porting | Dev Team |
| **R-003** | Event bus integration delays | Low (30%) | Low | 🟢 **LOW** | Defer to Phase 4 | Dev Team |
| **R-004** | Scope creep delays timeline | Medium (50%) | Medium | 🟡 **MEDIUM** | Strict phase gates | PM |
| **R-005** | omnibase_core breaking changes | Low (20%) | Critical | 🟡 **MEDIUM** | Version pinning | DevOps |
| **R-006** | Generated code quality issues | Medium (40%) | Medium | 🟡 **MEDIUM** | Comprehensive testing | QA |
| **R-007** | PRD parser inaccuracy | Medium (50%) | Low | 🟢 **LOW** | User validation | Dev Team |
| **R-008** | Resource availability | Low (30%) | Medium | 🟡 **MEDIUM** | Timeline buffer | PM |

### Risk Response Plans

#### R-001: Template Import Bugs (HIGH SEVERITY)
**Response**: AVOID
- **Action**: Fix immediately in Phase 1.1 (first task)
- **Timeline**: Complete within 4-6 hours
- **Verification**: Run compatibility validator
- **Success Criteria**: All imports resolve successfully

#### R-002: Adaptation Complexity (MEDIUM SEVERITY)
**Response**: MITIGATE + ACCEPT
- **Action**: Simplify utilities, remove advanced features
- **Fallback**: If >30h effort, defer to Phase 4
- **Verification**: Incremental testing after each utility port
- **Success Criteria**: Each utility passes integration tests

#### R-005: omnibase_core Breaking Changes (MEDIUM SEVERITY)
**Response**: MITIGATE + TRANSFER
- **Action**: Pin omnibase_core version in pyproject.toml
- **Monitoring**: Weekly dependency checks
- **Contingency**: Create adapter layer if breaking changes occur
- **Communication**: Notify stakeholders of version requirements

---

## Appendices

### Appendix A: Import Migration Checklist

**Template Fixes**:
- [ ] `template_engine.py` line 476: Update ModelEffectInput import
- [ ] `template_engine.py` line 502: Update ModelEffectOutput import
- [ ] `effect_node_template.py` line 96: Replace `.dict()` with `.model_dump()`
- [ ] `compute_node_template.py` line 96: Replace `.dict()` with `.model_dump()`
- [ ] `reducer_node_template.py` line 105: Verify `.model_dump()` usage
- [ ] `orchestrator_node_template.py` line 105: Verify `.model_dump()` usage
- [ ] All templates: Verify `ModelOnexError` usage (not `OnexError`)

**omnibase_3 Utility Migrations**:
- [ ] `utility_contract_analyzer.py`: Update all imports
- [ ] `utility_reference_resolver.py`: Update all imports
- [ ] `utility_schema_loader.py`: Update all imports
- [ ] `utility_ast_builder.py`: Update all imports
- [ ] `utility_type_mapper.py`: Update all imports
- [ ] `utility_enum_generator.py`: Update all imports
- [ ] `utility_schema_composer.py`: Update all imports

**Verification**:
- [ ] Run `poetry run mypy` on all migrated files
- [ ] Run compatibility validator
- [ ] Import all modules in Python REPL
- [ ] Run integration tests

---

### Appendix B: Directory Structure

**Target Structure** (after all phases):
```
omniclaude/
├── agents/
│   ├── lib/
│   │   ├── generation/                     # NEW: Generation utilities
│   │   │   ├── __init__.py
│   │   │   ├── contract_analyzer.py        # From omnibase_3
│   │   │   ├── reference_resolver.py       # From omnibase_3
│   │   │   ├── schema_loader.py            # From omnibase_3
│   │   │   ├── ast_builder.py              # From omnibase_3
│   │   │   ├── type_mapper.py              # From omnibase_3
│   │   │   ├── enum_generator.py           # From omnibase_3
│   │   │   └── schema_composer.py          # From omnibase_3
│   │   ├── omninode_template_engine.py     # Updated
│   │   ├── omnibase_core_validator.py      # NEW
│   │   ├── generation_pipeline.py          # NEW
│   │   └── prd_parser.py                   # NEW
│   └── templates/                          # Updated templates
└── scripts/
    └── migrate_imports.py                  # NEW: Import migration script
```

---

### Appendix C: Testing Strategy

**Unit Tests** (per phase):
- Phase 1: Template rendering, import validation, PRD parsing
- Phase 2: Contract loading, reference resolution, quality gates
- Phase 3: AST generation, type mapping, enum generation
- Phase 4: Event handling, status updates

**Integration Tests**:
- End-to-end generation from prompt
- End-to-end generation from contract
- Event bus round-trip

**Acceptance Tests**:
- Generate all 4 node types (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
- Verify compilation and import resolution
- Type checking passes (mypy)
- ONEX compliance validation

**Performance Tests**:
- Generation time benchmarks
- Template rendering performance
- Event bus throughput

---

### Appendix D: Phase Gate Criteria

**Phase 1 → Phase 2 Gate**:
- [ ] POC generates compilable EFFECT node from prompt
- [ ] All template import bugs fixed
- [ ] Compatibility validator passes
- [ ] Integration tests pass (>90%)
- [ ] Stakeholder demo approved

**Phase 2 → Phase 3 Gate**:
- [ ] Contract validation works end-to-end
- [ ] Reference resolution 100% success rate
- [ ] Quality gates execute successfully
- [ ] Integration tests pass (>95%)
- [ ] Performance targets met (<5s validation)

**Phase 3 → Phase 4 Gate**:
- [ ] AST-based model generation works
- [ ] All node types (4) generate successfully
- [ ] ZERO TOLERANCE (no `Any` types) achieved
- [ ] Type checking passes (0 errors)
- [ ] Production readiness review approved

**Phase 4 Completion Gate**:
- [ ] Event bus integration complete
- [ ] Full pipeline operational
- [ ] All acceptance tests pass
- [ ] Documentation complete
- [ ] Production deployment approved

---

## Conclusion

**Option C (Hybrid Approach)** provides the optimal balance:
- ✅ **Fast POC**: Working pipeline in 1-2 weeks
- ✅ **Production Quality**: Proven omnibase_3 utilities
- ✅ **Manageable Risk**: Phased approach with clear gates
- ✅ **Long-term Value**: Foundation for autonomous generation

**Next Steps**:
1. ✅ Approve this implementation plan
2. 📅 Schedule Phase 1 kick-off meeting
3. 🔧 Set up development environment
4. 🚀 Begin Phase 1.1 (Fix template import bugs)

**Total Effort**: 75-94 hours over 7-8 weeks
**Team**: 1 senior developer (or 2 developers for 25% faster delivery)
**Risk Level**: LOW-MEDIUM (all high risks mitigated)
**Success Probability**: HIGH (>80%)

---

**Document Version**: 1.0
**Last Updated**: 2025-10-21
**Status**: Ready for Execution
**Owner**: OmniClaude Development Team
