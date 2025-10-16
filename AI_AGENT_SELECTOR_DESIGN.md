# AI-Powered Agent Selector Design

**Date**: 2025-10-10
**Status**: Design Phase
**Version**: 1.0.0

---

## Executive Summary

Design for an intelligent hybrid agent selection system that combines fast pattern-based detection with AI-powered semantic analysis for the OmniClaude polymorphic agent framework.

### Key Features
- **Hybrid Detection**: Pattern-based → Trigger-based → AI-powered (3-stage fallback)
- **Multiple AI Models**: Local (RTX 5090), Cloud (Gemini, GLM-4.6), Ollama
- **Smart Fallback**: Graceful degradation when AI unavailable
- **Performance**: <5ms pattern detection, <500ms AI selection (optional)
- **52 Agents**: Full support for existing agent ecosystem

---

## Architecture

### Current System Analysis

**Existing Components**:
1. `agent_detector.py` - Pattern and trigger-based detection (LIVE)
2. `ai_agent_selector.py` - AI-powered selection (PARTIAL)
3. `user-prompt-submit-enhanced.sh` - Hook integration (LIVE)

**Current Flow**:
```
User Prompt → Pattern Detection → Trigger Matching → Context Injection
                ↓ success              ↓ success            ↓
             Agent Found          Agent Found        Enhanced Prompt
```

**Limitations**:
- Requires explicit agent naming (`@agent-name`)
- Trigger matching limited to keyword presence
- No semantic understanding of user intent
- Cannot infer best agent from natural language

### Proposed Hybrid System

```
┌─────────────────────────────────────────────────────────────────────┐
│ User Prompt: "Help me optimize this database query"                 │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 1: Pattern Detection (agent_detector.py)                      │
│ ─────────────────────────────────────────────────────────────────── │
│ Patterns: @agent-name, use agent-name, invoke agent-name            │
│ Performance: ~1ms                                                    │
│ Confidence: 1.0 (explicit)                                           │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
                ┌──────┴──────┐
                │ Found?      │
                └──────┬──────┘
           YES ◄──────┤       ├──────► NO
                      │       │
                      ▼       ▼
                     USE    Continue
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 2: Trigger Matching (agent_detector.py)                       │
│ ─────────────────────────────────────────────────────────────────── │
│ Match against activation triggers from agent registry                │
│ Performance: ~2-5ms                                                  │
│ Confidence: 0.7-0.9 (keyword-based)                                  │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
                ┌──────┴──────┐
                │ Match >0?   │
                └──────┬──────┘
           YES ◄──────┤       ├──────► NO
                      │       │
                      ▼       ▼
                     USE    Continue
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 3: AI Selection (ai_agent_selector.py) - OPTIONAL             │
│ ─────────────────────────────────────────────────────────────────── │
│ Model Selection:                                                     │
│   1. Local (RTX 5090): DeepSeek via Ollama                          │
│   2. Cloud (Gemini): gemini-2.5-flash via Zen MCP                   │
│   3. Cloud (GLM): glm-4.6 via Zen MCP                               │
│                                                                      │
│ Analysis:                                                            │
│   - Semantic intent analysis                                         │
│   - Domain expertise matching                                        │
│   - Task complexity assessment                                       │
│   - Agent capability alignment                                       │
│                                                                      │
│ Performance: ~100-500ms (model-dependent)                            │
│ Confidence: 0.0-1.0 (AI-scored)                                      │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
                ┌──────┴──────┐
                │ Conf >0.8?  │
                └──────┬──────┘
           YES ◄──────┤       ├──────► NO
                      │       │
                      ▼       ▼
                     USE    Passthrough
                             (No agent)
```

---

## Component Design

### 1. Hybrid Agent Selector

**File**: `hybrid_agent_selector.py`
**Purpose**: Coordinates 3-stage detection pipeline

```python
class HybridAgentSelector:
    """
    Intelligent agent selection with multi-stage fallback.

    Stages:
    1. Pattern Detection (explicit, ~1ms, conf=1.0)
    2. Trigger Matching (keyword, ~5ms, conf=0.7-0.9)
    3. AI Selection (semantic, ~500ms, conf=0.0-1.0)
    """

    def __init__(self, enable_ai: bool = True):
        self.pattern_detector = AgentDetector()
        self.ai_selector = AIAgentSelector() if enable_ai else None

    def select_agent(self, prompt: str, context: Dict = None) -> AgentSelection:
        # Stage 1: Pattern detection
        result = self._stage_1_pattern(prompt)
        if result.found:
            return result

        # Stage 2: Trigger matching
        result = self._stage_2_triggers(prompt)
        if result.found:
            return result

        # Stage 3: AI selection (if enabled)
        if self.ai_selector:
            result = self._stage_3_ai(prompt, context)
            if result.confidence >= 0.8:
                return result

        # No agent detected
        return AgentSelection(found=False, confidence=0.0)
```

**Configuration**:
```bash
# Environment variables
ENABLE_AI_AGENT_SELECTION=true         # Enable AI selection fallback
AI_AGENT_CONFIDENCE_THRESHOLD=0.8      # Minimum confidence for AI selection
AI_MODEL_PREFERENCE=auto               # auto, local, gemini, glm, 5090
AI_SELECTION_TIMEOUT_MS=500            # Max time for AI selection
```

### 2. AI Model Integration

**Model Priority** (based on availability and performance):

1. **Local (RTX 5090)** - Fastest, no API limits
   - Model: `deepseek-coder` via Ollama
   - Endpoint: `http://localhost:11434`
   - Latency: ~100-200ms
   - Availability: Check via `/api/tags`

2. **Gemini Flash** - Fast cloud option
   - Model: `gemini-2.5-flash` via Zen MCP
   - Latency: ~300-400ms
   - Rate Limits: High
   - Good for quick decisions

3. **GLM-4.6** - High-quality reasoning
   - Model: `glm-4.6` via Zen MCP
   - Latency: ~400-500ms
   - Rate Limits: Medium
   - Best for complex intent analysis

4. **Gemini Pro** - Highest quality fallback
   - Model: `gemini-2.5-pro` via Zen MCP
   - Latency: ~500-800ms
   - Rate Limits: Lower
   - Use for difficult cases only

**Model Selection Algorithm**:
```python
def _select_model(self) -> ModelConfig:
    if self.preference == "local" or self.preference == "5090":
        if self._check_ollama_available():
            return LOCAL_MODEL

    if self.preference == "gemini":
        return GEMINI_FLASH

    if self.preference == "glm":
        return GLM_46

    # Auto mode: try local first, fall back to cloud
    if self._check_ollama_available():
        return LOCAL_MODEL
    return GEMINI_FLASH  # Fast cloud fallback
```

### 3. AI Selection Prompt Engineering

**Prompt Template**:
```
You are an intelligent agent selector for OmniClaude with 52 specialized agents.

Task: Analyze the user's prompt and select the most appropriate agent.

User Prompt:
"{user_prompt}"

Context:
- Working Directory: {working_directory}
- Active Files: {active_files}
- Recent Operations: {recent_operations}

Available Agents (52 total):
{agent_catalog}

Instructions:
1. Identify the user's primary intent and domain
2. Match intent against agent purposes, domains, and triggers
3. Consider task complexity and required capabilities
4. Select the single best agent
5. Provide confidence score (0.0-1.0) and reasoning

Output (JSON):
{
    "agent": "agent-name",
    "confidence": 0.95,
    "method": "ai",
    "reasoning": "Brief explanation of why this agent is best",
    "alternatives": ["agent-name-2", "agent-name-3"]
}

Be precise. Only return confidence >0.8 if you're highly certain.
```

**Agent Catalog Format** (compact):
```
- agent-performance-optimizer: Optimize code/queries for performance (Domain: optimization, Triggers: optimize, performance, slow)
- agent-debug-intelligence: Debug complex issues systematically (Domain: debugging, Triggers: debug, error, bug)
- agent-testing: Design and implement test strategies (Domain: testing, Triggers: test, coverage, pytest)
...
```

### 4. Hook Integration

**Updated Hook Flow** (`user-prompt-submit-enhanced.sh`):
```bash
# Use hybrid selector instead of agent_detector (returns JSON)
AGENT_SELECTION=$(python3 "${HOOKS_LIB}/hybrid_agent_selector.py" "$PROMPT" \
    --enable-ai "$ENABLE_AI_AGENT_SELECTION" \
    --confidence-threshold "$AI_AGENT_CONFIDENCE_THRESHOLD" \
    --model-preference "$AI_MODEL_PREFERENCE" \
    --timeout "$AI_SELECTION_TIMEOUT_MS" \
    2>>\"$LOG_FILE\" || echo '{"agent": null, "confidence": 0, "method": "error", "reasoning": "Selection failed"}')

# Parse JSON selection result using jq
AGENT_NAME=$(echo "$AGENT_SELECTION" | jq -r '.agent // empty')
CONFIDENCE=$(echo "$AGENT_SELECTION" | jq -r '.confidence // 0')
SELECTION_METHOD=$(echo "$AGENT_SELECTION" | jq -r '.method // "unknown"')
REASONING=$(echo "$AGENT_SELECTION" | jq -r '.reasoning // "No reasoning provided"')

# Log selection details
echo "[$(date)] Agent: $AGENT_NAME, Confidence: $CONFIDENCE, Method: $SELECTION_METHOD" >> "$LOG_FILE"
```

**Expected JSON Output Format**:
```json
{
  "agent": "agent-name",           // Selected agent identifier (null if none)
  "confidence": 0.95,               // Confidence score 0.0-1.0
  "method": "ai|trigger|pattern",   // Selection method used
  "reasoning": "Explanation text",  // Why this agent was selected
  "alternatives": ["agent-2"]       // Optional: Alternative agents considered
}
```

**JSON Parsing Requirements**:
- Use `jq -r` for robust JSON parsing (not grep/sed)
- Handle null values with `// empty` or `// default` operators
- Fallback to valid JSON on errors (not plain text)
- Validate JSON structure before parsing critical fields

---

## Performance Targets

### Latency Targets
- **Pattern Detection**: <2ms (MUST)
- **Trigger Matching**: <5ms (MUST)
- **AI Selection**: <500ms (SHOULD)
- **Total (with AI)**: <510ms (SHOULD)
- **Total (without AI)**: <10ms (MUST)

### Accuracy Targets
- **Pattern Detection**: 100% (explicit matches)
- **Trigger Matching**: >85% precision
- **AI Selection**: >90% precision at confidence >0.8

### Availability Targets
- **Pattern Detection**: 100% (always works)
- **Trigger Matching**: 100% (always works)
- **AI Selection**: >95% (graceful fallback if unavailable)

---

## Configuration System

### Environment Variables
```bash
# Enable/disable AI selection
export ENABLE_AI_AGENT_SELECTION=true

# AI model preference (auto, local, gemini, glm, 5090)
export AI_MODEL_PREFERENCE=auto

# Confidence threshold for AI selection (0.0-1.0)
export AI_AGENT_CONFIDENCE_THRESHOLD=0.8

# Timeout for AI selection (ms)
export AI_SELECTION_TIMEOUT_MS=500

# Zen MCP availability
export ZEN_MCP_AVAILABLE=true

# Ollama endpoint
export OLLAMA_ENDPOINT=http://localhost:11434
```

### Configuration File
**Location**: `~/.claude/hooks/agent-selector-config.yaml`

```yaml
agent_selection:
  # Enable AI-powered selection
  enable_ai: true

  # Confidence threshold for AI selection (0.0-1.0)
  confidence_threshold: 0.8

  # Model preference
  model_preference: auto  # auto, local, gemini, glm, 5090

  # Timeout for AI selection (ms)
  timeout_ms: 500

  # Fallback behavior
  fallback:
    use_triggers: true
    use_default_agent: false
    default_agent: null

  # Model configurations
  models:
    local:
      endpoint: http://localhost:11434
      model: deepseek-coder
      timeout_ms: 200

    gemini_flash:
      model: gemini-2.5-flash
      timeout_ms: 400

    glm:
      model: glm-4.6
      timeout_ms: 500

    gemini_pro:
      model: gemini-2.5-pro
      timeout_ms: 800

  # Performance monitoring
  monitoring:
    track_latency: true
    track_accuracy: true
    log_selections: true
```

---

## Implementation Plan

### Phase 1: Core Hybrid Selector (2-3 hours)
1. ✅ Design architecture
2. Create `hybrid_agent_selector.py`
3. Implement 3-stage selection pipeline
4. Add configuration loading
5. Unit tests for each stage

### Phase 2: AI Model Integration (3-4 hours)
1. Integrate with existing `ai_agent_selector.py`
2. Implement Ollama local model calls
3. Implement Zen MCP cloud model calls
4. Add model selection algorithm
5. Add timeout and error handling

### Phase 3: Hook Integration (1-2 hours)
1. Update `user-prompt-submit-enhanced.sh`
2. Add configuration environment variables
3. Update logging for selection metadata
4. Test with hook system

### Phase 4: Testing & Validation (2-3 hours)
1. Test pattern detection accuracy
2. Test trigger matching accuracy
3. Test AI selection with multiple models
4. Test graceful degradation
5. Performance benchmarking
6. End-to-end integration tests

### Phase 5: Documentation (1 hour)
1. Update AGENT_SYSTEM_REACTIVATED.md
2. Create usage examples
3. Document configuration options
4. Create troubleshooting guide

**Total Estimated Time**: 9-13 hours

---

## Success Criteria

### Functional Requirements
- ✅ Backward compatible with existing pattern detection
- ✅ AI selection works with local and cloud models
- ✅ Graceful fallback when AI unavailable
- ✅ Configurable via environment variables
- ✅ Comprehensive logging and debugging

### Performance Requirements
- ✅ Pattern detection <2ms
- ✅ Total latency <510ms with AI
- ✅ Total latency <10ms without AI
- ✅ AI selection accuracy >90% at confidence >0.8

### Reliability Requirements
- ✅ 100% uptime for pattern/trigger detection
- ✅ >95% availability for AI selection
- ✅ No blocking failures
- ✅ Proper error handling and recovery

---

## Risk Analysis

### Risks

1. **AI Model Latency**
   - Risk: AI selection >500ms impacts user experience
   - Mitigation: Strict timeouts, async execution, local model preference
   - Fallback: Disable AI selection if consistently slow

2. **Model Availability**
   - Risk: Ollama or cloud models unavailable
   - Mitigation: Multi-model fallback chain, graceful degradation
   - Fallback: Pattern/trigger detection always works

3. **AI Selection Accuracy**
   - Risk: AI picks wrong agent, user confused
   - Mitigation: High confidence threshold (>0.8), reasoning logging
   - Fallback: User can override with explicit @agent-name

4. **Configuration Complexity**
   - Risk: Users confused by multiple configuration options
   - Mitigation: Smart defaults, auto mode, clear documentation
   - Fallback: Simple enable/disable flag

5. **Token Cost (Cloud Models)**
   - Risk: High API costs for frequent AI selections
   - Mitigation: Local model preference, caching, confidence threshold
   - Fallback: Disable AI selection

---

## Future Enhancements

### Phase 2 Features
- **Selection Caching**: Cache AI selections for similar prompts (TTL: 1 hour)
- **Learning System**: Track successful/failed selections, improve over time
- **Multi-Agent Recommendations**: Return top 3 agents with confidence scores
- **Context-Aware Selection**: Use working directory, recent files, git branch
- **Agent Chaining**: Suggest multi-agent workflows for complex tasks

### Phase 3 Features
- **Fine-Tuned Models**: Train custom models on agent selection task
- **Collaborative Filtering**: Learn from user's agent preferences
- **Dynamic Confidence**: Adjust thresholds based on historical accuracy
- **Agent Analytics**: Dashboard showing agent usage patterns
- **Automated A/B Testing**: Compare selection strategies

---

## Appendix

### Agent Catalog (52 Total)

**Development (15)**:
- agent-api-architect
- agent-code-generator
- agent-python-expert
- agent-python-fastapi-expert
- agent-typescript-expert
- agent-contract-driven-generator
- agent-refactoring-expert
- agent-architecture-reviewer
- agent-dependency-manager
- agent-code-reviewer
- agent-migration-specialist
- agent-integration-expert
- agent-polyglot-developer
- agent-frontend-specialist
- agent-backend-specialist

**Testing & Quality (8)**:
- agent-testing
- agent-debug-intelligence
- agent-performance-optimizer
- agent-security-auditor
- agent-code-quality-analyzer
- agent-regression-tester
- agent-load-tester
- agent-chaos-engineer

**DevOps (7)**:
- agent-devops-infrastructure
- agent-production-monitor
- agent-incident-responder
- agent-deployment-manager
- agent-container-specialist
- agent-kubernetes-expert
- agent-cicd-architect

**Git/VCS (6)**:
- agent-commit
- agent-pr-create
- agent-pr-review
- agent-ticket-manager
- agent-git-workflow-expert
- agent-merge-conflict-resolver

**Documentation (5)**:
- agent-documentation
- agent-readme-generator
- agent-api-documentation
- agent-tutorial-writer
- agent-diagram-creator

**Data & Database (5)**:
- agent-database-optimizer
- agent-sql-expert
- agent-data-pipeline-engineer
- agent-schema-designer
- agent-query-optimizer

**AI/ML (3)**:
- agent-ml-engineer
- agent-model-optimizer
- agent-data-scientist

**Other (3)**:
- agent-troubleshooter
- agent-research-assistant
- agent-automation-specialist

---

**Status**: Design Complete ✅
**Next**: Implementation Phase 1
**Estimated Completion**: 9-13 hours
