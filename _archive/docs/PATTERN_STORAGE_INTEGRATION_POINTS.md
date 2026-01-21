# Pattern Storage Integration Points Analysis

**Task**: Identify exact integration points for pattern storage in code generation pipeline

**Date**: 2025-10-25
**Correlation ID**: 6a512f46-fdf2-41d5-bde6-7c6dc58be4f4

---

## Executive Summary

**Current State**: PatternLibrary exists but is **NOT integrated** into production pipeline.
**Test Usage**: PatternLibrary is only used in test files, not in actual generation.
**Gap**: Generated code doesn't benefit from learned patterns - each generation starts from scratch.

**Integration Strategy**: Wire PatternLibrary into 3 key points:
1. **Pre-Generation**: Query learned patterns before template rendering
2. **Post-Generation**: Extract patterns after successful generation
3. **Feedback Loop**: Track pattern effectiveness after validation

---

## 1. Current Pattern Library Usage

### Location
```
/Volumes/PRO-G40/Code/omniclaude/agents/lib/pattern_library.py
```

### Class Structure
```python
class PatternLibrary:
    def __init__(self):
        self.matcher = PatternMatcher()
        self.registry = PatternRegistry()

    # Key methods:
    def detect_pattern(contract, min_confidence=0.7) -> Dict
    def detect_all_patterns(contract, min_confidence=0.5) -> Dict
    def generate_pattern_code(pattern_name, contract, node_type, class_name) -> Dict
    def compose_pattern_code(patterns, contract, node_type, class_name) -> Dict
```

### Current Usage (Tests Only)
```python
# File: agents/tests/test_phase5_integration.py:209-220
pattern_result = pattern_library.detect_pattern(contract_result["contract"])

business_logic_result = await business_logic_generator.generate_node_stub(
    node_type="EFFECT",
    microservice_name="user_management",
    domain="identity",
    contract=contract_result["contract"],
    analysis_result=EFFECT_ANALYSIS_RESULT,
    pattern_hint=pattern_result["pattern_name"] if pattern_result["matched"] else None
)
```

**Problem**: This pattern detection happens in tests but NOT in production pipeline!

---

## 2. Current Generation Pipeline Data Flow

### Flow Diagram
```
User Request
    ↓
PRDAnalyzer.analyze_prd()
    ↓ (PRDAnalysisResult)
ContractGenerator.generate_contract_yaml()
    ↓ (contract dict)
GenerationPipeline._stage_4_generate_code()  [generation_pipeline.py:1778]
    ↓
OmniNodeTemplateEngine.generate_node()  [omninode_template_engine.py:464]
    ↓
    ├─ Input Validation (lines 494-497)
    ├─ Get Intelligence Context (lines 499-502)
    ├─ Get Template (lines 504-511)
    ├─ Prepare Context (lines 513-516) ⚠️ INTEGRATION POINT 1
    ├─ Render Template (line 519)
    ├─ Generate Files (lines 522-555)
    └─ Return Metadata (lines 569-584) ⚠️ INTEGRATION POINT 2
    ↓
Generated Code (no learned patterns applied!)
```

### Key Files
1. **Generation Pipeline**: `/Volumes/PRO-G40/Code/omniclaude/agents/lib/generation_pipeline.py`
2. **Template Engine**: `/Volumes/PRO-G40/Code/omniclaude/agents/lib/omninode_template_engine.py`
3. **Business Logic Generator**: `/Volumes/PRO-G40/Code/omniclaude/agents/lib/business_logic_generator.py`
4. **Pattern Library**: `/Volumes/PRO-G40/Code/omniclaude/agents/lib/pattern_library.py`

---

## 3. Integration Point #1: Pre-Generation Pattern Query

### Purpose
Query learned patterns BEFORE template rendering to enhance code generation with battle-tested solutions.

### Location
**File**: `omninode_template_engine.py`
**Method**: `generate_node()`
**Line Range**: 513-516 (in `_prepare_template_context` call)

### Current Code (lines 513-519)
```python
# Prepare context for template rendering with intelligence
context = self._prepare_template_context(
    analysis_result, node_type, microservice_name, domain, intelligence
)

# Generate node implementation
node_content = template.render(context)
```

### Proposed Integration
```python
# INTEGRATION POINT 1: Pre-Generation Pattern Query
from .pattern_library import PatternLibrary

# Initialize pattern library (can be class member)
pattern_library = PatternLibrary()

# Query learned patterns from contract
pattern_result = pattern_library.detect_pattern(
    contract=analysis_result.contract,  # Contract from analysis
    min_confidence=0.7
)

# Prepare context with pattern enhancement
context = self._prepare_template_context(
    analysis_result, node_type, microservice_name, domain, intelligence
)

# Add pattern context if detected
if pattern_result["matched"]:
    context["DETECTED_PATTERN"] = pattern_result["pattern_name"]
    context["PATTERN_CONFIDENCE"] = pattern_result["confidence"]

    # Generate pattern-specific code blocks
    pattern_code = pattern_library.generate_pattern_code(
        pattern_name=pattern_result["pattern_name"],
        contract=analysis_result.contract,
        node_type=node_type,
        class_name=context["MICROSERVICE_NAME_PASCAL"]
    )
    context["PATTERN_CODE_BLOCKS"] = pattern_code.get("code", "")

# Generate node implementation with patterns
node_content = template.render(context)
```

### Data Needed
- **Contract**: Already available in `analysis_result.contract` (needs verification)
- **Pattern Library Instance**: Initialize once in `__init__` or create lazily
- **Template Enhancement**: Templates need to support `{PATTERN_CODE_BLOCKS}` placeholder

### Impact
- **Performance**: +20-50ms for pattern detection (acceptable)
- **Quality**: Significantly improved - uses proven patterns
- **Consistency**: All nodes with similar contracts get similar implementations

---

## 4. Integration Point #2: Post-Generation Pattern Extraction

### Purpose
Extract patterns from successfully generated code to build pattern library over time.

### Location
**File**: `omninode_template_engine.py`
**Method**: `generate_node()`
**Line Range**: 569-584 (return statement with metadata)

### Current Code (lines 569-584)
```python
return {
    "node_type": node_type,
    "microservice_name": microservice_name,
    "domain": domain,
    "output_path": str(node_path),
    "main_file": str(main_file_path),
    "generated_files": full_file_paths,
    "metadata": {
        "session_id": str(analysis_result.session_id),
        "correlation_id": str(analysis_result.correlation_id),
        "node_metadata": metadata,
        "confidence_score": analysis_result.confidence_score,
        "quality_baseline": analysis_result.quality_baseline,
    },
    "context": context,
}
```

### Proposed Integration
```python
# INTEGRATION POINT 2: Post-Generation Pattern Extraction
from .pattern_extraction import extract_patterns_from_code

# Extract patterns from generated code
try:
    extracted_patterns = extract_patterns_from_code(
        code=node_content,
        contract=analysis_result.contract,
        node_type=node_type,
        quality_score=analysis_result.quality_baseline
    )

    # Store patterns if quality threshold met
    if analysis_result.quality_baseline >= 0.8:
        for pattern in extracted_patterns:
            pattern_library.store_pattern(
                pattern_name=pattern["name"],
                pattern_type=pattern["type"],
                code_example=pattern["code"],
                contract_signature=pattern["contract_sig"],
                quality_score=analysis_result.quality_baseline,
                session_id=str(analysis_result.session_id),
                metadata={
                    "node_type": node_type,
                    "domain": domain,
                    "microservice": microservice_name
                }
            )
except Exception as e:
    # Don't fail generation if pattern extraction fails
    self.logger.warning(f"Pattern extraction failed: {e}")
    extracted_patterns = []

return {
    "node_type": node_type,
    "microservice_name": microservice_name,
    "domain": domain,
    "output_path": str(node_path),
    "main_file": str(main_file_path),
    "generated_files": full_file_paths,
    "metadata": {
        "session_id": str(analysis_result.session_id),
        "correlation_id": str(analysis_result.correlation_id),
        "node_metadata": metadata,
        "confidence_score": analysis_result.confidence_score,
        "quality_baseline": analysis_result.quality_baseline,
        "extracted_patterns": extracted_patterns,  # NEW!
    },
    "context": context,
}
```

### Requirements
- **Pattern Extraction Module**: Create `pattern_extraction.py` to analyze generated code
- **Pattern Storage**: Add `store_pattern()` method to PatternLibrary
- **Quality Threshold**: Only store patterns from high-quality code (≥0.8)
- **Non-Blocking**: Pattern extraction failures should NOT fail generation

### Impact
- **Learning Curve**: System improves over time with each generation
- **Pattern Database Growth**: Accumulates proven patterns
- **Performance**: Minimal overhead (async storage recommended)

---

## 5. Integration Point #3: Feedback Loop

### Purpose
Track pattern effectiveness by correlating pattern usage with quality scores over time.

### Location
**File**: `generation_pipeline.py`
**Method**: After quality validation stages
**Line Range**: After Stage 5/6 validation (not in current code - needs investigation)

### Proposed Integration
```python
# INTEGRATION POINT 3: Pattern Effectiveness Feedback

# After quality validation completes
async def _record_pattern_feedback(
    self,
    generation_result: Dict[str, Any],
    validation_result: Dict[str, Any],
    pattern_used: Optional[str] = None
):
    """Record pattern usage effectiveness for continuous learning"""

    if not pattern_used:
        return  # No pattern was used

    # Calculate effectiveness score
    effectiveness = {
        "pattern_name": pattern_used,
        "quality_score": validation_result.get("quality_score", 0.0),
        "validation_passed": validation_result.get("valid", False),
        "generation_time_ms": generation_result["metadata"].get("generation_time_ms", 0),
        "session_id": generation_result["metadata"]["session_id"],
        "timestamp": datetime.utcnow().isoformat()
    }

    # Store feedback for pattern confidence adjustment
    await pattern_library.record_pattern_effectiveness(effectiveness)

    self.logger.info(
        f"Pattern feedback recorded: {pattern_used} "
        f"(quality={effectiveness['quality_score']:.2f})"
    )
```

### Call Site
After validation stages in `generation_pipeline.py`:
```python
# After stage 5 or 6 validation
validation_result = await self._validate_generation(generation_result)

# Record pattern feedback
pattern_used = generation_result["metadata"].get("detected_pattern")
await self._record_pattern_feedback(
    generation_result,
    validation_result,
    pattern_used
)
```

### Requirements
- **Feedback Storage**: Add `record_pattern_effectiveness()` to PatternLibrary
- **Confidence Adjustment**: Update pattern confidence scores based on success rate
- **Analytics**: Track pattern usage statistics (usage count, avg quality, success rate)

### Impact
- **Self-Improving**: Pattern confidence scores adjust based on real results
- **Pattern Ranking**: High-performing patterns get higher confidence
- **Pattern Pruning**: Low-performing patterns can be identified and removed

---

## 6. Data Flow with Integration

### Enhanced Pipeline Flow
```
User Request
    ↓
PRDAnalyzer.analyze_prd()
    ↓
ContractGenerator.generate_contract_yaml()
    ↓
GenerationPipeline._stage_4_generate_code()
    ↓
OmniNodeTemplateEngine.generate_node()
    ↓
    ├─ Input Validation
    ├─ Get Intelligence Context
    ├─ ⚡ POINT 1: Query Learned Patterns (NEW!)
    │   └─ PatternLibrary.detect_pattern(contract)
    ├─ Prepare Context (enhanced with patterns)
    ├─ Render Template (with pattern blocks)
    ├─ Generate Files
    ├─ ⚡ POINT 2: Extract Patterns (NEW!)
    │   └─ extract_patterns_from_code() → store_pattern()
    └─ Return Metadata (with pattern info)
    ↓
Quality Validation
    ↓
⚡ POINT 3: Record Feedback (NEW!)
    └─ PatternLibrary.record_pattern_effectiveness()
    ↓
Improved Pattern Library for Next Generation
```

---

## 7. Implementation Strategy

### Phase 1: Minimal Invasive Integration (Week 1)
1. **Add PatternLibrary instance** to `OmniNodeTemplateEngine.__init__`
2. **Integrate Point 1**: Query patterns in `generate_node()` before rendering
3. **Update templates**: Add `{PATTERN_CODE_BLOCKS}` placeholder support
4. **Test**: Verify pattern detection works without breaking existing flow

### Phase 2: Pattern Storage (Week 2)
5. **Create pattern_extraction.py** module
6. **Integrate Point 2**: Extract and store patterns after generation
7. **Add storage methods**: `store_pattern()` to PatternLibrary
8. **Test**: Verify patterns are stored after successful generations

### Phase 3: Feedback Loop (Week 3)
9. **Integrate Point 3**: Record pattern effectiveness after validation
10. **Add analytics**: Pattern usage tracking and confidence adjustment
11. **Dashboard**: Pattern library inspection tools
12. **Test**: End-to-end learning cycle validation

---

## 8. File Modification Summary

### Files to Modify
1. **`omninode_template_engine.py`** (Primary Integration)
   - Line 176: Add `self.pattern_library = PatternLibrary()` to `__init__`
   - Line 513-519: Add pattern detection before template rendering
   - Line 569-584: Add pattern extraction before return

2. **`generation_pipeline.py`** (Feedback Integration)
   - Add `_record_pattern_feedback()` method
   - Call after validation stages

3. **`pattern_library.py`** (New Methods)
   - Add `store_pattern()` method
   - Add `record_pattern_effectiveness()` method
   - Add pattern confidence adjustment logic

### New Files to Create
1. **`pattern_extraction.py`**: AST-based pattern extraction from generated code
2. **`pattern_storage_backend.py`**: Database/file storage for patterns
3. **Tests**: Integration tests for pattern learning cycle

---

## 9. Success Criteria

✅ **Pre-Generation**: PatternLibrary.detect_pattern() called before template render
✅ **Pattern Enhancement**: Template context includes detected pattern code blocks
✅ **Post-Generation**: Patterns extracted from high-quality code (≥0.8)
✅ **Storage**: Patterns stored with metadata (session_id, quality_score)
✅ **Feedback**: Pattern effectiveness tracked after validation
✅ **Learning**: Pattern confidence scores improve over time
✅ **Non-Breaking**: Integration doesn't break existing generation pipeline

---

## 10. Risks and Mitigation

### Risk 1: Pattern Detection Overhead
- **Impact**: +20-50ms per generation
- **Mitigation**: Cache pattern detection results, async processing
- **Acceptable**: <100ms overhead for significant quality improvement

### Risk 2: Pattern Extraction Failures
- **Impact**: Could fail generation if not handled
- **Mitigation**: Wrap in try/except, log warnings, don't fail on errors

### Risk 3: Pattern Storage Bottleneck
- **Impact**: Slow I/O could block generation
- **Mitigation**: Async storage, queue-based background processing

### Risk 4: Contract Availability
- **Impact**: `analysis_result.contract` might not exist
- **Mitigation**: Verify contract is available, generate from analysis if needed

---

## 11. Next Steps

1. ✅ **Document Integration Points** (Current Task - COMPLETE)
2. ⬜ **Verify Contract Availability**: Check if `analysis_result.contract` exists
3. ⬜ **Create Pattern Extraction Module**: Implement `pattern_extraction.py`
4. ⬜ **Implement Point 1**: Pre-generation pattern query
5. ⬜ **Test Point 1**: Verify patterns enhance generation without breaking
6. ⬜ **Implement Point 2**: Post-generation pattern storage
7. ⬜ **Implement Point 3**: Feedback loop integration
8. ⬜ **End-to-End Testing**: Full learning cycle validation

---

## Appendix A: Code References

### PatternLibrary Key Methods
```python
# File: agents/lib/pattern_library.py

def detect_pattern(contract: Dict[str, Any], min_confidence: float = 0.7) -> Dict[str, Any]:
    """Returns: {"pattern_name": str, "confidence": float, "matched": bool}"""

def generate_pattern_code(pattern_name: str, contract: Dict, node_type: str,
                         class_name: str) -> Dict[str, Any]:
    """Returns: {"code": str}"""
```

### Template Engine Entry Point
```python
# File: agents/lib/omninode_template_engine.py:464

async def generate_node(
    self,
    analysis_result: PRDAnalysisResult,
    node_type: str,
    microservice_name: str,
    domain: str,
    output_directory: str,
    intelligence: Optional[IntelligenceContext] = None,
) -> Dict[str, Any]:
```

### Generation Pipeline Trigger
```python
# File: agents/lib/generation_pipeline.py:1798

generation_result = await self.template_engine.generate_node(
    analysis_result=analysis_result,
    node_type=node_type,
    microservice_name=service_name,
    domain=domain,
    output_directory=output_directory,
    intelligence=intelligence_context,
)
```

---

**Document Status**: ✅ Complete
**Ready for Implementation**: Phase 1 (Pre-Generation Integration)
**Estimated Effort**: 3 weeks (1 week per phase)
