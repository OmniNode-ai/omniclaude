# AI Quorum System - Pre-commit Hook Validation

Multi-model AI consensus system for validating pre-commit hook corrections with weighted scoring and confidence analysis.

## Overview

The AI Quorum System provides intelligent validation of pre-commit hook corrections by:
- Consulting multiple AI models in parallel
- Calculating weighted consensus scores
- Providing confidence metrics
- Supporting stub mode for Phase 1 testing

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AI Quorum System                         │
├─────────────────┬─────────────────┬─────────────────────────┤
│  Configuration  │   Scoring       │      Consensus          │
├─────────────────┼─────────────────┼─────────────────────────┤
│ • Model Setup   │ • Ollama Models │ • Weighted Scoring      │
│ • Weight Config │ • Gemini Models │ • Confidence Analysis   │
│ • Provider URLs │ • OpenAI Models │ • Approval Logic        │
│ • Stub Mode     │ • Parallel Exec │ • Review Flagging       │
└─────────────────┴─────────────────┴─────────────────────────┘
```

## Phase Roadmap

### Phase 1 (Current) - Stub Mode
- **Status**: ✅ Complete
- **Features**:
  - Fixed scores (0.85) for infrastructure testing
  - Configuration flag to disable AI scoring
  - Complete prompt generation for future use
  - Full test coverage
- **Purpose**: Enable testing of pre-commit hook infrastructure

### Phase 2 - Integration Testing
- **Status**: 🔄 Planned
- **Features**:
  - Integration with pre-commit hooks
  - End-to-end workflow testing
  - Performance benchmarking

### Phase 3 - AI Model Integration
- **Status**: 🔄 Planned
- **Features**:
  - Enable Ollama model scoring
  - Enable Gemini model scoring
  - Parallel execution optimization
  - Error handling and fallbacks

### Phase 4 - Full Production
- **Status**: 🔄 Planned
- **Features**:
  - Dynamic model selection
  - Advanced consensus algorithms
  - Performance optimization
  - Production monitoring

## Installation

```bash
# Already installed at:
~/.claude/hooks/lib/consensus/

# Required dependencies (for Phase 3+):
pip install httpx
```

## Usage

### Basic Usage (Phase 1 - Stub Mode)

```python
from consensus import AIQuorum

# Initialize with stub mode (Phase 1)
quorum = AIQuorum(stub_mode=True, enable_ai_scoring=False)

# Score a correction
score = await quorum.score_correction(
    original_prompt="debug the authentication issue",
    corrected_prompt="debug the authentication issue @MANDATORY_FUNCTIONS.md",
    correction_type="framework_reference",
    correction_metadata={
        "agent_detected": "agent-debug-intelligence",
        "timestamp": "2025-09-29T12:00:00"
    }
)

# Check approval
if score.is_approved:
    print(f"✓ Correction approved (score: {score.consensus_score})")
else:
    print(f"✗ Correction needs review (score: {score.consensus_score})")
```

### Custom Model Configuration

```python
from consensus import AIQuorum, ModelConfig, ModelProvider

# Configure custom models
models = [
    ModelConfig(
        name="codestral:22b-v0.1-q4_K_M",
        provider=ModelProvider.OLLAMA,
        weight=2.0,  # Higher weight for specialized model
        endpoint="http://localhost:11434",
        timeout=15.0
    ),
    ModelConfig(
        name="gemini-2.5-flash",
        provider=ModelProvider.GEMINI,
        weight=1.0,
        api_key="your-api-key-here"
    ),
]

quorum = AIQuorum(models=models, stub_mode=True)
```

### Phase 3+ AI Scoring (Future)

```python
# Enable full AI scoring (Phase 3+)
quorum = AIQuorum(
    stub_mode=False,
    enable_ai_scoring=True,
    parallel_execution=True
)

score = await quorum.score_correction(
    original_prompt="implement OAuth2",
    corrected_prompt="implement OAuth2 @MANDATORY_FUNCTIONS.md @quality-gates-spec.yaml",
    correction_type="multi_framework_reference"
)

# Access detailed model scores
for model_name, model_score in score.model_scores.items():
    print(f"{model_name}: {model_score} - {score.model_reasoning[model_name]}")

# Check consensus
print(f"Consensus: {score.consensus_score:.2f}")
print(f"Confidence: {score.confidence:.2f}")
print(f"Recommendation: {score.recommendation}")
```

## Configuration

### Environment Variables

```bash
# Ollama Configuration
export OLLAMA_BASE_URL="http://localhost:11434"

# Gemini Configuration
export GEMINI_API_KEY="your-gemini-api-key"

# OpenAI Configuration (Phase 4+)
export OPENAI_API_KEY="your-openai-api-key"
```

### Model Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | str | - | Model name/identifier |
| `provider` | ModelProvider | - | OLLAMA, GEMINI, or OPENAI |
| `weight` | float | 1.0 | Model weight in consensus (0.1-10.0) |
| `endpoint` | str | Auto | API endpoint URL |
| `api_key` | str | None | API key for provider |
| `timeout` | float | 10.0 | Request timeout in seconds |

### Quorum Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `models` | List[ModelConfig] | DEFAULT_MODELS | Model configurations |
| `stub_mode` | bool | True | Use fixed scores (Phase 1) |
| `enable_ai_scoring` | bool | False | Enable actual AI scoring (Phase 3+) |
| `parallel_execution` | bool | True | Score models in parallel |

## QuorumScore Object

The `QuorumScore` object contains:

```python
@dataclass
class QuorumScore:
    consensus_score: float       # 0.0-1.0 weighted consensus
    confidence: float            # 0.0-1.0 based on score variance
    model_scores: Dict[str, float]       # Individual model scores
    model_reasoning: Dict[str, str]      # Model explanations
    recommendation: str          # APPROVE, REJECT, REVIEW
    requires_human_review: bool  # Flag for manual review
```

### Approval Logic

A correction is approved when:
- `consensus_score >= 0.7` AND
- `confidence >= 0.6`

```python
score.is_approved  # Property that checks both thresholds
```

## Testing

### Run Unit Tests

```bash
cd ~/.claude/hooks
python3 lib/consensus/test_quorum.py
```

### Run CLI Test

```bash
cd ~/.claude/hooks
python3 -m lib.consensus.quorum \
    "debug this code" \
    "debug this code @MANDATORY_FUNCTIONS.md" \
    "framework_reference"
```

### Example Test Output

```
AI Quorum System (Phase 1 - Stub Mode)
Original: debug this code
Corrected: debug this code @MANDATORY_FUNCTIONS.md
Correction Type: framework_reference

{
  "consensus_score": 0.85,
  "confidence": 0.9,
  "model_scores": {
    "codestral:22b-v0.1-q4_K_M": 0.85,
    "gemini-2.5-flash": 0.85
  },
  "model_reasoning": {
    "codestral:22b-v0.1-q4_K_M": "[STUB] Auto-approved for Phase 1 testing - framework_reference",
    "gemini-2.5-flash": "[STUB] Auto-approved for Phase 1 testing - framework_reference"
  },
  "recommendation": "AUTO_APPROVED_PHASE1_STUB",
  "requires_human_review": false
}

Approved: True
Recommendation: AUTO_APPROVED_PHASE1_STUB
```

## Integration with Pre-commit Hooks

### Example Integration (Phase 2+)

```python
#!/usr/bin/env python3
from consensus import AIQuorum

async def validate_correction(original, corrected, correction_type):
    """Validate correction with AI quorum."""
    quorum = AIQuorum(stub_mode=True)  # Phase 1

    score = await quorum.score_correction(
        original_prompt=original,
        corrected_prompt=corrected,
        correction_type=correction_type
    )

    return score.is_approved, score.consensus_score
```

## Scoring Prompt Template

The system generates structured prompts for AI models:

```
# Pre-commit Hook Correction Evaluation

## Task
Evaluate the quality and appropriateness of a pre-commit hook correction.

## Correction Type
{correction_type}

## Original Prompt
{original_prompt}

## Corrected Prompt
{corrected_prompt}

## Evaluation Criteria
1. Correctness (0.0-1.0): Proper issue resolution
2. Necessity (0.0-1.0): Value of correction
3. Preservation (0.0-1.0): User intent preserved
4. Quality (0.0-1.0): Format and clarity

## Response Format
{
  "score": 0.85,
  "correctness": 0.9,
  "necessity": 0.8,
  "preservation": 0.9,
  "quality": 0.8,
  "reasoning": "Explanation",
  "concerns": ["Any issues"],
  "recommendation": "APPROVE|REJECT|REVIEW"
}
```

## Default Models

### Phase 1-4 Default Configuration

```python
DEFAULT_MODELS = [
    ModelConfig(
        name="codestral:22b-v0.1-q4_K_M",
        provider=ModelProvider.OLLAMA,
        weight=1.5  # Higher weight for code specialization
    ),
    ModelConfig(
        name="gemini-2.5-flash",
        provider=ModelProvider.GEMINI,
        weight=1.0
    ),
]
```

## Consensus Calculation

### Weighted Scoring

```python
consensus_score = Σ(model_score_i × model_weight_i) / Σ(model_weight_i)
```

### Confidence Calculation

```python
score_variance = Σ(score_i - consensus_score)² / n
confidence = max(0.0, 1.0 - score_variance)
```

### Recommendation Logic

- **APPROVE**: > 50% models approve
- **REJECT**: > 50% models reject
- **REVIEW**: Split decision or errors

## Error Handling

The system includes robust error handling:

```python
# Individual model failures don't block consensus
# Timeouts default to 0.5 score with REVIEW recommendation
# Network errors gracefully degraded
# Invalid responses trigger fallback scoring
```

## Performance

### Phase 1 (Stub Mode)
- **Latency**: < 1ms (synchronous)
- **Throughput**: Unlimited

### Phase 3+ (AI Scoring)
- **Latency**: 2-10s (parallel models)
- **Throughput**: Limited by model APIs
- **Optimization**: Parallel execution reduces latency 50-75%

## Future Enhancements

### Phase 5+ Possibilities
- [ ] Model result caching
- [ ] Adaptive model selection
- [ ] Learning from corrections
- [ ] Custom scoring algorithms
- [ ] Real-time model performance tracking
- [ ] Multi-tier consensus (fast → thorough)

## Troubleshooting

### Issue: "httpx not available"
**Solution**: Install httpx for Phase 3+
```bash
pip install httpx
```

### Issue: Model timeout
**Solution**: Increase timeout in ModelConfig
```python
ModelConfig(..., timeout=30.0)
```

### Issue: Low confidence scores
**Solution**: Check model agreement variance
```python
for model, score in score.model_scores.items():
    print(f"{model}: {score}")
```

## References

- Design Document: Lines 563-817
- Pre-commit Hook Spec: `@quality-gates-spec.yaml`
- Performance Thresholds: `@performance-thresholds.yaml`
- Framework Functions: `@MANDATORY_FUNCTIONS.md`

## License

Part of the Claude Code pre-commit hook framework.

---

**Status**: Phase 1 Complete - Ready for Integration Testing
**Last Updated**: 2025-09-29
