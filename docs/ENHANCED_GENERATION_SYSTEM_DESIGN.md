# Enhanced Node Generation System Design Document

**Version**: 2.0
**Date**: 2025-10-21
**Status**: Design Phase
**Authors**: OmniNode AI Team

---

## Executive Summary

This document describes the architecture for enhancing the autonomous ONEX node generation system with three critical capabilities:

1. **Quorum Validation**: Multi-model consensus at key decision points
2. **Interactive Clarification**: Human-in-the-loop at critical checkpoints
3. **Problem Statement Workflow**: Document-to-implementation pipeline

**Current State**: Generation pipeline produces ONEX-compliant scaffolds in ~0.67s with 70% confidence
**Target State**: Production-ready implementations in ~10s with 95%+ confidence and user validation

**Business Value**:
- Reduce iteration cycles from 3-5 attempts to 1-2
- Increase first-time-right rate from 70% to 95%+
- Enable complex implementations from problem statements
- Provide transparent, validatable decision-making

---

## Table of Contents

1. [Current State Analysis](#current-state-analysis)
2. [Problem Statement](#problem-statement)
3. [Proposed Architecture](#proposed-architecture)
4. [Component Design](#component-design)
5. [Integration Points](#integration-points)
6. [Implementation Phases](#implementation-phases)
7. [Success Criteria](#success-criteria)
8. [Risk Analysis](#risk-analysis)
9. [Testing Strategy](#testing-strategy)
10. [Appendices](#appendices)

---

## 1. Current State Analysis

### 1.1 Existing System

**Generation Pipeline v1.0**:
```
Stage 0: Prompt Parsing (15ms)
    ↓
Stage 1: PRD Analysis (200ms)
    ↓
Stage 1.5: Intelligence Gathering (100ms)  [NEW in v1.5]
    ↓
Stage 2: Contract Building (150ms)
    ↓
Stage 3: Node Generation (100ms)
    ↓
Stage 4: File Writing (50ms)
    ↓
Stage 5: Validation (50ms)
    ↓
Total: ~0.67s, 15 validation gates
```

**Strengths**:
- ✅ Fast generation (< 1s)
- ✅ ONEX-compliant scaffolds
- ✅ Intelligence-driven best practices
- ✅ Perfect structure and type safety
- ✅ 100% test pass rate

**Weaknesses**:
- ❌ No multi-model validation (single LLM decides)
- ❌ No user feedback loop (fire-and-forget)
- ❌ Cannot process problem statement documents
- ❌ Confidence limited to ~70% (no consensus)
- ❌ Requires 2-3 iterations for complex requirements

### 1.2 Existing Assets

**Parallel Execution Framework** (`agents/parallel_execution/`):
- ✅ ValidatedTaskArchitect: Document → Task breakdown
- ✅ QuorumValidator: 4-model consensus (Gemini + GLMs)
- ✅ InteractiveValidator: Human-in-the-loop checkpoints
- ✅ ParallelDispatcher: Parallel agent execution
- ✅ Complete tracing and session management

**Intelligence System**:
- ✅ IntelligenceGatherer: Pattern library + RAG hooks
- ✅ 50+ best practices across 4 node types
- ✅ Domain-specific patterns (database, API, messaging, cache)

**Gap**: These systems are **not integrated** into generation pipeline

---

## 2. Problem Statement

### 2.1 Core Problems

**Problem 1: Ambiguous Requirements**
```
User: "Create a data processing node"
System: *guesses* COMPUTE node
Reality: User wanted EFFECT node for database writes
Result: Wasted generation + user frustration
```

**Problem 2: Single-Model Bias**
```
One LLM decides everything:
- Node type selection
- Operation extraction
- Contract structure
- Type mappings

No validation from other models
No consensus mechanism
```

**Problem 3: No Feedback Loop**
```
User discovers issues AFTER generation:
- Wrong node type
- Missing operations
- Incorrect contract structure

Must restart from scratch
No way to provide feedback mid-generation
```

**Problem 4: Cannot Process Documents**
```
Complex requirements in problem statements
Rich context in markdown files
Multiple pages of specifications

Current system: Only accepts simple prompts
```

### 2.2 Impact

| Issue | Frequency | Impact | Cost |
|-------|-----------|--------|------|
| Wrong node type | 15% of generations | High | 3-5 min rework |
| Missing operations | 25% of generations | Medium | 2-3 min additions |
| Incorrect contract | 10% of generations | Critical | 10+ min rebuild |
| Ambiguous requirements | 30% of generations | High | Multiple iterations |

**Total Impact**: ~40% of generations require rework, averaging 3-5 iterations to completion

---

## 3. Proposed Architecture

### 3.1 Enhanced Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     INPUT LAYER                                  │
├─────────────────────────────────────────────────────────────────┤
│  • Simple Prompt                                                 │
│  • Problem Statement Document (markdown)                         │
│  • Codebase Context (files, patterns)                           │
└────────────┬────────────────────────────────────────────────────┘
             ↓
┌─────────────────────────────────────────────────────────────────┐
│              VALIDATED TASK BREAKDOWN                            │
│  [NEW] Uses ValidatedTaskArchitect + QuorumValidator            │
├─────────────────────────────────────────────────────────────────┤
│  1. Parse input (prompt or document)                             │
│  2. Break into subtasks                                          │
│  3. Quorum validation (4 models vote)                            │
│  4. Interactive checkpoint (if enabled)                          │
│  └─> PASS: Continue                                              │
│  └─> RETRY: Augment with feedback                               │
│  └─> USER_OVERRIDE: Accept user decision                        │
└────────────┬────────────────────────────────────────────────────┘
             ↓
┌─────────────────────────────────────────────────────────────────┐
│                   ENHANCED GENERATION PIPELINE                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Stage 0: Prompt Parsing                                         │
│      └─> Extract node type, domain, operations                  │
│                                                                  │
│  Stage 1: PRD Analysis                                           │
│      └─> Detailed requirements analysis                         │
│      └─> [NEW] Quorum validation (optional)                     │
│      └─> [NEW] Interactive Checkpoint 1: PRD Review             │
│           • Show: Understood requirements                        │
│           • User: Approve / Edit / Retry / Quit                  │
│                                                                  │
│  Stage 1.5: Intelligence Gathering                               │
│      └─> Pattern library + RAG search                           │
│      └─> [NEW] Interactive Checkpoint 2: Pattern Review         │
│                                                                  │
│  Stage 2: Contract Building                                      │
│      └─> Generate models, enums, contracts                      │
│      └─> [NEW] Quorum validation (CRITICAL)                     │
│           • 4 models independently review contract               │
│           • Weighted voting (total weight: 5.5)                  │
│           • Decision: PASS (>75%) / RETRY (50-75%) / FAIL (<50%)│
│      └─> [NEW] Interactive Checkpoint 3: Quorum Conflict        │
│           • Shown when: quorum confidence < 75%                  │
│           • User: Break ties, provide domain expertise           │
│      └─> [NEW] Interactive Checkpoint 4: Contract Review        │
│           • Show: Input/output models, operation enum            │
│           • User: Approve / Edit / Retry                         │
│                                                                  │
│  Stage 3: Node Generation                                        │
│      └─> Generate node implementation                           │
│      └─> Apply intelligence-driven patterns                     │
│      └─> [NEW] Quorum validation (optional, strict mode)        │
│                                                                  │
│  Stage 4: File Writing                                           │
│      └─> Write 11 files to disk                                 │
│                                                                  │
│  Stage 5: Validation                                             │
│      └─> Run 15 validation gates                                │
│      └─> [NEW] Interactive Checkpoint 5: Final Review           │
│                                                                  │
└────────────┬────────────────────────────────────────────────────┘
             ↓
┌─────────────────────────────────────────────────────────────────┐
│                      OUTPUT LAYER                                │
├─────────────────────────────────────────────────────────────────┤
│  • Generated Node Files (11 files)                               │
│  • Validation Report (15 gates)                                  │
│  • Quorum Decision Log (confidence scores)                       │
│  • Session State (for resume)                                    │
│  • Trace Files (full audit trail)                               │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Execution Modes

| Mode | Quorum | Interactive | Time | Confidence | Use Case |
|------|--------|-------------|------|------------|----------|
| **fast** | ❌ | ❌ | 0.7s | 70% | Prototyping, known requirements |
| **balanced** | PRD + Contract | PRD review | 7s | 85% | **Default**, most use cases |
| **standard** | PRD + Contract | All checkpoints | 10s | 92% | Important nodes |
| **strict** | All stages | All checkpoints | 18s | 97% | Production-critical |
| **paranoid** | All stages + final | All + final review | 25s | 99% | Security/compliance |

---

## 4. Component Design

### 4.1 Quorum Integration

#### 4.1.1 QuorumConfig

```python
@dataclass
class QuorumConfig:
    """Configuration for quorum validation in generation pipeline"""

    # Validation stages
    validate_prd_analysis: bool = True      # Stage 1
    validate_intelligence: bool = False     # Stage 1.5
    validate_contract: bool = True          # Stage 2 (CRITICAL)
    validate_node_code: bool = False        # Stage 3

    # Retry configuration
    retry_on_fail: bool = True
    max_retries_per_stage: int = 2

    # Thresholds
    pass_threshold: float = 0.75   # >75% = PASS
    retry_threshold: float = 0.50  # 50-75% = RETRY, <50% = FAIL

    # Performance
    quorum_timeout_seconds: int = 10
    parallel_validation: bool = False

    @classmethod
    def from_mode(cls, mode: str) -> "QuorumConfig":
        """Create config from execution mode"""
        modes = {
            "fast": cls(
                validate_prd_analysis=False,
                validate_contract=False
            ),
            "balanced": cls(
                validate_prd_analysis=True,
                validate_contract=True,
                validate_intelligence=False,
                validate_node_code=False
            ),
            "standard": cls(
                validate_prd_analysis=True,
                validate_contract=True,
                validate_intelligence=True,
                validate_node_code=False
            ),
            "strict": cls(
                validate_prd_analysis=True,
                validate_contract=True,
                validate_intelligence=True,
                validate_node_code=True
            ),
        }
        return modes.get(mode, modes["balanced"])
```

#### 4.1.2 Contract Validation Implementation

```python
# In generation_pipeline.py - Stage 2

async def _stage_2_contract_building(
    self,
    analysis_result: SimplePRDAnalysisResult,
    intelligence: IntelligenceContext
) -> Tuple[PipelineStage, ContractBuildingResult]:
    """Stage 2: Build contract with optional quorum validation"""

    # Generate initial contract
    contract = await self.contract_builder.build(
        analysis_result=analysis_result,
        intelligence=intelligence
    )

    # Quorum validation (if enabled)
    if self.quorum_config.validate_contract:
        logger.info("🔍 Validating contract with quorum...")

        quorum_result = await self.quorum.validate_contract(
            requirements=analysis_result.prd_content,
            contract=contract,
            node_type=analysis_result.node_type,
            operations=analysis_result.operations
        )

        logger.info(
            f"📊 Quorum decision: {quorum_result.decision} "
            f"(confidence: {quorum_result.confidence:.1%})"
        )

        # Handle decision
        if quorum_result.decision == ValidationDecision.RETRY:
            # Interactive checkpoint (if enabled)
            if self.interactive:
                user_choice = await self._checkpoint_quorum_conflict(
                    quorum_result,
                    contract
                )

                if user_choice == "accept_anyway":
                    logger.info("✓ User override: Accepting contract despite quorum")
                    pass  # Continue with current contract

                elif user_choice == "provide_feedback":
                    # Retry with user feedback
                    contract = await self._retry_contract_with_user_feedback(
                        analysis_result,
                        quorum_result.deficiencies,
                        user_feedback=user_choice.feedback
                    )
            else:
                # Non-interactive: Auto-retry with deficiency feedback
                contract = await self._retry_contract_with_feedback(
                    analysis_result,
                    quorum_result.deficiencies,
                    attempt=1
                )

        elif quorum_result.decision == ValidationDecision.FAIL:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message=f"Contract validation failed quorum",
                context={
                    "deficiencies": quorum_result.deficiencies,
                    "confidence": quorum_result.confidence,
                    "scores": quorum_result.scores
                }
            )

    # Interactive contract review (if enabled, no quorum conflict)
    if self.interactive and not quorum_conflict_occurred:
        user_choice = await self._checkpoint_contract_review(contract)
        # Handle approve/edit/retry/quit

    return contract
```

### 4.2 Interactive Checkpoints

#### 4.2.1 InteractiveConfig

```python
@dataclass
class InteractiveConfig:
    """Configuration for interactive checkpoints"""

    # Checkpoint enables
    checkpoint_prd_review: bool = True
    checkpoint_pattern_review: bool = False
    checkpoint_quorum_conflict: bool = True
    checkpoint_contract_review: bool = True
    checkpoint_final_review: bool = False

    # Smart checkpoints
    auto_skip_high_confidence: bool = True
    confidence_threshold: float = 0.90

    # Session management
    enable_session_save: bool = True
    session_dir: Path = Path("/tmp/generation_sessions")

    # Editor integration
    editor: Optional[str] = None  # Uses $EDITOR if None

    @classmethod
    def from_mode(cls, mode: str) -> "InteractiveConfig":
        """Create config from execution mode"""
        modes = {
            "none": cls(
                checkpoint_prd_review=False,
                checkpoint_pattern_review=False,
                checkpoint_quorum_conflict=False,
                checkpoint_contract_review=False,
                checkpoint_final_review=False
            ),
            "minimal": cls(
                checkpoint_prd_review=True,
                checkpoint_pattern_review=False,
                checkpoint_quorum_conflict=True,
                checkpoint_contract_review=False,
                checkpoint_final_review=False
            ),
            "standard": cls(
                checkpoint_prd_review=True,
                checkpoint_pattern_review=False,
                checkpoint_quorum_conflict=True,
                checkpoint_contract_review=True,
                checkpoint_final_review=False
            ),
            "full": cls(
                checkpoint_prd_review=True,
                checkpoint_pattern_review=True,
                checkpoint_quorum_conflict=True,
                checkpoint_contract_review=True,
                checkpoint_final_review=True
            ),
        }
        return modes.get(mode, modes["standard"])
```

#### 4.2.2 Checkpoint Implementation

```python
async def _checkpoint_contract_review(
    self,
    contract: ContractBuildingResult
) -> CheckpointResult:
    """Interactive checkpoint for contract review"""

    # Format contract for display
    display_text = self._format_contract_display(contract)

    # Detect potential issues
    issues = self._detect_contract_issues(contract)

    # Build checkpoint message
    message = f"""
┌─────────────────────────────────────────────────────────────┐
│ 📜 Generated Contract Review                                │
├─────────────────────────────────────────────────────────────┤
{display_text}
"""

    if issues:
        message += f"""├─────────────────────────────────────────────────────────────┤
│ Potential Issues Detected:                                  │
"""
        for issue in issues:
            message += f"│   ⚠️  {issue}\n"

    message += """├─────────────────────────────────────────────────────────────┤
│ [A]pprove  [E]dit contract  [R]etry generation  [Q]uit    │
└─────────────────────────────────────────────────────────────┘
"""

    # Show checkpoint and get user choice
    result = await self.interactive_validator.checkpoint(
        stage_name="Contract Review",
        data=contract,
        message=message
    )

    return result
```

### 4.3 Problem Statement Workflow

#### 4.3.1 Adapter Script

Already created: `agents/parallel_execution/run_from_problem_statement.py`

**Flow**:
```python
1. Read problem statement markdown
2. Extract requirements, context, constraints
3. Feed to ValidatedTaskArchitect
4. Quorum validation on task breakdown
5. Interactive review of tasks
6. Execute via ParallelDispatcher
7. Synthesize results into final implementation
```

#### 4.3.2 Integration with Generation Pipeline

```python
# New CLI command

python cli/generate_from_problem_statement.py \
    /path/to/PROBLEM_STATEMENT.md \
    --mode balanced \
    --interactive
```

**Flow**:
1. Problem statement → ValidatedTaskArchitect
2. Task breakdown → QuorumValidator
3. For each task:
   - If task is "generate node": Use enhanced pipeline
   - If task is "create handler": Use enhanced pipeline
   - If task is "integrate": Manual or future automation
4. Aggregate results
5. Final validation

---

## 5. Integration Points

### 5.1 CLI Changes

```bash
# File: cli/generate_node.py

@click.command()
@click.argument("prompt")
@click.option("--output", type=click.Path(), default="/tmp/generated_nodes")
@click.option(
    "--mode",
    type=click.Choice(["fast", "balanced", "standard", "strict", "paranoid"]),
    default="balanced",
    help="Execution mode (speed vs quality tradeoff)"
)
@click.option(
    "--interactive/--no-interactive",
    default=False,
    help="Enable interactive checkpoints"
)
@click.option(
    "--quorum-mode",
    type=click.Choice(["none", "minimal", "standard", "strict"]),
    default=None,
    help="Override quorum validation level"
)
@click.option(
    "--resume-session",
    type=click.Path(exists=True),
    default=None,
    help="Resume from saved session"
)
def generate_node(prompt, output, mode, interactive, quorum_mode, resume_session):
    """Generate ONEX node with enhanced validation"""

    # Build configs
    if quorum_mode:
        quorum_config = QuorumConfig.from_mode(quorum_mode)
    else:
        quorum_config = QuorumConfig.from_mode(mode)

    interactive_config = InteractiveConfig.from_mode(
        "standard" if interactive else "none"
    )

    # Initialize pipeline
    pipeline = GenerationPipeline(
        quorum_config=quorum_config,
        interactive_config=interactive_config
    )

    # Generate
    asyncio.run(pipeline.generate(prompt, output_dir=output))
```

### 5.2 Environment Variables

```bash
# .env configuration

# Quorum validation (requires API keys)
GEMINI_API_KEY=...
ZAI_API_KEY=...

# Generation modes
DEFAULT_GENERATION_MODE=balanced
DEFAULT_INTERACTIVE_MODE=false

# Performance tuning
QUORUM_TIMEOUT_SECONDS=10
MAX_RETRIES_PER_STAGE=2

# Session management
SESSION_DIR=/tmp/generation_sessions
AUTO_SAVE_SESSIONS=true
```

### 5.3 Dependencies

**New Dependencies**:
```toml
# pyproject.toml

[tool.poetry.dependencies]
# Existing...
# NEW for quorum:
python-dotenv = "^1.0.0"  # Environment variable loading
httpx = "^0.27.0"         # Async HTTP for API calls
```

**Existing Dependencies** (already available):
- `pydantic` - Data validation
- `asyncio` - Async execution
- All parallel_execution/* modules

---

## 6. Implementation Phases

### Phase 1: Quorum Integration (Week 1)

**Goal**: Add multi-model validation to contract building

**Tasks**:
1. Create QuorumConfig class
2. Integrate QuorumValidator into GenerationPipeline
3. Implement contract validation with retry logic
4. Update CLI with --quorum-mode flag
5. Add quorum decision logging
6. Test with 10 diverse prompts

**Deliverables**:
- ✅ Quorum validation working for contracts
- ✅ Retry logic with deficiency feedback
- ✅ Performance metrics (time impact)
- ✅ Confidence improvement data

**Success Criteria**:
- Contract validation runs in < 5s
- Confidence increases from 70% to 85%+
- Retry rate < 20%
- FAIL rate < 5%

### Phase 2: Interactive Checkpoints (Week 2)

**Goal**: Add human-in-the-loop validation

**Tasks**:
1. Create InteractiveConfig class
2. Integrate InteractiveValidator from parallel_execution
3. Implement Checkpoint 1: PRD Review
4. Implement Checkpoint 3: Quorum Conflict
5. Implement Checkpoint 4: Contract Review
6. Add session save/resume
7. Update CLI with --interactive flag
8. Test user experience

**Deliverables**:
- ✅ 3 interactive checkpoints working
- ✅ Session save/resume functional
- ✅ User documentation
- ✅ Example workflows

**Success Criteria**:
- Checkpoints complete in < 60s user time
- Session resume works 100% of time
- User satisfaction > 90%
- Rework rate drops to < 10%

### Phase 3: Problem Statement Workflow (Week 3)

**Goal**: Enable document-to-implementation pipeline

**Tasks**:
1. Create generate_from_problem_statement.py CLI
2. Integrate ValidatedTaskArchitect
3. Add markdown parsing for requirements extraction
4. Implement task → generation routing
5. Add result aggregation
6. Test with real problem statements
7. Documentation and examples

**Deliverables**:
- ✅ Problem statement → node pipeline working
- ✅ Example problem statements
- ✅ End-to-end trace files
- ✅ User guide

**Success Criteria**:
- Complex problem statements generate correctly
- Task breakdown validated by quorum
- Final implementation matches requirements
- Time to implementation < 2 minutes

### Phase 4: Optimization & Polish (Week 4)

**Goal**: Performance tuning and UX improvements

**Tasks**:
1. Smart checkpoint detection (skip high-confidence)
2. Parallel quorum validation (multiple stages)
3. Caching of quorum results
4. Performance profiling and optimization
5. Add analytics/telemetry
6. User training materials
7. Migration guide for existing users

**Deliverables**:
- ✅ Performance optimizations
- ✅ Analytics dashboard
- ✅ Training documentation
- ✅ Migration guide

**Success Criteria**:
- Balanced mode completes in < 10s
- Smart checkpoints reduce user time by 40%
- Cache hit rate > 60%
- Zero breaking changes for existing users

---

## 7. Success Criteria

### 7.1 Quantitative Metrics

| Metric | Baseline (v1.5) | Target (v2.0) | Measurement |
|--------|-----------------|---------------|-------------|
| **First-time-right rate** | 70% | 95% | User surveys + rework tracking |
| **Average iterations** | 2.5 | 1.2 | Analytics |
| **Contract confidence** | N/A | 92% | Quorum scores |
| **Generation time (balanced)** | 0.67s | < 10s | Pipeline metrics |
| **User satisfaction** | N/A | > 90% | Surveys |
| **Rework time saved** | Baseline | 80% reduction | Time tracking |

### 7.2 Qualitative Goals

- ✅ Users trust the system's decisions
- ✅ Complex requirements handled correctly
- ✅ Transparent decision-making process
- ✅ Easy to override/correct mistakes
- ✅ Clear audit trail for compliance

### 7.3 Acceptance Criteria

**Phase 1 (Quorum)**:
- [ ] Contract validation passes 95% of test cases
- [ ] Retry logic successfully fixes issues
- [ ] Performance impact < 7s
- [ ] Confidence scores logged and measurable

**Phase 2 (Interactive)**:
- [ ] All 3 checkpoints functional
- [ ] Session save/resume works reliably
- [ ] User can override quorum decisions
- [ ] Editor integration works

**Phase 3 (Problem Statements)**:
- [ ] Can generate from markdown documents
- [ ] Task breakdown validated by quorum
- [ ] Complex implementations succeed
- [ ] Full trace files generated

**Phase 4 (Polish)**:
- [ ] Smart checkpoints reduce user time
- [ ] Performance optimized
- [ ] Analytics working
- [ ] Documentation complete

---

## 8. Risk Analysis

### 8.1 Technical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Quorum API failures** | High | Medium | Retry logic, fallback to single model |
| **Performance degradation** | Medium | Low | Parallel validation, caching |
| **Interactive UX complexity** | Medium | Medium | Smart defaults, skip high-confidence |
| **Breaking changes** | High | Low | Backward compatibility, feature flags |
| **Session corruption** | Medium | Low | Atomic saves, validation on load |

### 8.2 User Adoption Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Users resist interactive mode** | Medium | Make optional, show value |
| **Confusion about modes** | Low | Clear defaults, documentation |
| **API key setup friction** | Low | .env.example, clear instructions |

### 8.3 Cost Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| **API costs scale** | Medium | Configurable modes, caching |
| **Free tier limits** | Low | Document limits, paid tier guide |

---

## 9. Testing Strategy

### 9.1 Unit Tests

```python
# Test quorum validation
tests/test_quorum_integration.py
- test_contract_validation_pass()
- test_contract_validation_retry()
- test_contract_validation_fail()
- test_retry_with_feedback()
- test_user_override()

# Test interactive checkpoints
tests/test_interactive_mode.py
- test_prd_review_checkpoint()
- test_quorum_conflict_checkpoint()
- test_contract_review_checkpoint()
- test_session_save_restore()
- test_editor_integration()

# Test problem statement workflow
tests/test_problem_statement_workflow.py
- test_markdown_parsing()
- test_task_breakdown()
- test_task_to_generation_routing()
- test_result_aggregation()
```

### 9.2 Integration Tests

```bash
# End-to-end generation tests
tests/integration/test_e2e_generation.py
- test_fast_mode_generation()
- test_balanced_mode_generation()
- test_strict_mode_generation()
- test_interactive_session()
- test_problem_statement_generation()

# Performance benchmarks
tests/benchmarks/test_generation_performance.py
- benchmark_quorum_overhead()
- benchmark_interactive_overhead()
- benchmark_parallel_validation()
```

### 9.3 User Acceptance Tests

**Test Scenarios**:
1. Simple prompt → fast generation
2. Ambiguous prompt → interactive clarification
3. Complex problem statement → full workflow
4. Quorum disagreement → user resolution
5. Session interruption → resume

---

## 10. Appendices

### Appendix A: Execution Mode Reference

```bash
# Fast mode (0.7s, 70% confidence)
python cli/generate_node.py "Create EFFECT node..." --mode fast

# Balanced mode (7s, 85% confidence) - DEFAULT
python cli/generate_node.py "Create EFFECT node..." --mode balanced

# Standard mode (10s, 92% confidence)
python cli/generate_node.py "Create EFFECT node..." --mode standard

# Strict mode (18s, 97% confidence)
python cli/generate_node.py "Create EFFECT node..." --mode strict

# Paranoid mode (25s, 99% confidence)
python cli/generate_node.py "Create EFFECT node..." --mode paranoid

# Custom configuration
python cli/generate_node.py "Create EFFECT node..." \
    --quorum-mode standard \
    --interactive \
    --output /path/to/output
```

### Appendix B: Checkpoint Reference

| Checkpoint | Stage | When Shown | User Options |
|------------|-------|------------|--------------|
| **PRD Review** | After Stage 1 | Always (if interactive) | A/E/R/Q |
| **Pattern Review** | After Stage 1.5 | Optional | A/S/Q |
| **Quorum Conflict** | During Stage 2 | Quorum confidence < 75% | A/C/E/F/Q |
| **Contract Review** | After Stage 2 | Always (if interactive) | A/E/R/Q |
| **Final Review** | After Stage 5 | Optional | A/E/Q |

**Legend**:
- A = Approve
- E = Edit
- R = Retry with feedback
- C = Change (override quorum)
- F = Provide feedback
- S = Skip
- Q = Quit (save session)

### Appendix C: Quorum Model Configuration

```python
QUORUM_MODELS = {
    "gemini_flash": {
        "name": "Gemini 2.5 Flash",
        "weight": 1.0,
        "context_window": 1_000_000,
        "strength": "Fast, broad knowledge"
    },
    "glm_45_air": {
        "name": "GLM-4.5-Air",
        "weight": 1.0,
        "context_window": 128_000,
        "strength": "Balanced, efficient"
    },
    "glm_45": {
        "name": "GLM-4.5",
        "weight": 2.0,  # Highest weight
        "context_window": 128_000,
        "strength": "Deep reasoning, code analysis"
    },
    "glm_46": {
        "name": "GLM-4.6",
        "weight": 1.5,
        "context_window": 128_000,
        "strength": "Latest, balanced"
    },
}

Total Weight: 5.5
Pass Threshold: > 75% of total weight (> 4.125)
Retry Threshold: 50-75% of total weight (2.75 - 4.125)
Fail Threshold: < 50% of total weight (< 2.75)
```

### Appendix D: Cost Analysis

**API Costs** (approximate, as of 2025-10):
- Gemini Flash: ~$0.005 per call
- GLM-4.5-Air: ~$0.003 per call
- GLM-4.5: ~$0.008 per call
- GLM-4.6: ~$0.006 per call

**Per Generation Costs**:
- Fast mode: $0.00 (no quorum)
- Balanced mode: ~$0.03 (2 quorum calls)
- Standard mode: ~$0.05 (3 quorum calls)
- Strict mode: ~$0.08 (4 quorum calls)

**Monthly Costs** (100 generations/month):
- Fast: $0
- Balanced: $3
- Standard: $5
- Strict: $8

**ROI**: Even at $8/month (800 generations), cost is negligible compared to developer time saved

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-10-21 | OmniNode AI | Initial draft |
| 2.0 | 2025-10-21 | OmniNode AI | Complete architecture design |

---

## Approval

| Role | Name | Status | Date |
|------|------|--------|------|
| **Technical Lead** | [TBD] | Pending Review | |
| **Product Owner** | [TBD] | Pending Review | |
| **Engineering Manager** | [TBD] | Pending Review | |

---

**END OF DESIGN DOCUMENT**
