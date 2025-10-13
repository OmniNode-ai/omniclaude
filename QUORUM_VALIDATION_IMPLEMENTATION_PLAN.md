# Quorum Validation Implementation Plan
## Multi-Model Consensus System for Agent Workflow Validation

**Version**: 1.0.0
**Status**: Implementation Planning
**Target**: Eliminate false-positive success reports in parallel agent execution

---

## 1. Executive Summary

### Problem Statement
Agents in the parallel execution system generate incorrect outputs (e.g., UserAuthentication node instead of PostgreSQL adapter) but report success, leading to:
- Silent failures that waste execution time
- Incorrect code generation propagating through the system
- No feedback mechanism to correct misunderstandings
- Loss of user trust in automated workflows

### Solution Overview
Implement a **Quorum Validation System (QVS)** that uses multiple local AI models to validate each critical step of the agent workflow:
- **3 validation checkpoints** in the workflow pipeline
- **Consensus-based validation** using weighted voting from 5 AI models
- **Deficiency-driven retry** with structured feedback
- **Bounded retry logic** to prevent infinite loops
- **Performance-optimized** with caching and parallel execution

### Success Metrics
- **Validation Accuracy**: >95% detection of misaligned outputs
- **False Positive Rate**: <5% (incorrectly failing valid outputs)
- **Performance Impact**: <30% overhead per workflow execution
- **Retry Success Rate**: >80% correction on first retry
- **Time to Validation**: <2000ms per checkpoint

---

## 2. Architecture Overview

### 2.1 System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                    Quorum Validation System                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────┐      ┌──────────────────┐                 │
│  │ Validation      │      │ Quorum Voting    │                 │
│  │ Checkpoint      │─────▶│ Engine           │                 │
│  │ Manager         │      │ (5 models)       │                 │
│  └─────────────────┘      └──────────────────┘                 │
│         │                           │                            │
│         │                           ▼                            │
│         │                  ┌──────────────────┐                 │
│         │                  │ Consensus        │                 │
│         │                  │ Aggregator       │                 │
│         │                  └──────────────────┘                 │
│         │                           │                            │
│         │                           ▼                            │
│         │                  ┌──────────────────┐                 │
│         │                  │ Deficiency       │                 │
│         │                  │ Reporter         │                 │
│         │                  └──────────────────┘                 │
│         │                           │                            │
│         ▼                           ▼                            │
│  ┌─────────────────────────────────────────┐                   │
│  │     Retry Orchestrator                   │                   │
│  │  (with bounded attempts & backoff)       │                   │
│  └─────────────────────────────────────────┘                   │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Integration Points

```
User Request
    │
    ▼
┌───────────────────┐
│ task_architect.py │ ◄─── CHECKPOINT 1: Intent Validation
└───────────────────┘      Validates: prompt understanding, task breakdown
    │
    ▼
┌───────────────────┐
│ dispatch_runner.py│
└───────────────────┘
    │
    ▼
┌───────────────────┐
│ agent_coder.py    │ ◄─── CHECKPOINT 2: Generation Validation
└───────────────────┘      Validates: code correctness, contract compliance
    │
    ▼
┌───────────────────┐
│ agent_debug_      │ ◄─── CHECKPOINT 3: Quality Validation
│ intelligence.py   │      Validates: functional correctness, ONEX compliance
└───────────────────┘
    │
    ▼
Final Output
```

---

## 3. Validation Checkpoint Design

### 3.1 Checkpoint 1: Intent Validation (Post-Architecture)

**Location**: After `task_architect.py` completes task breakdown
**Purpose**: Ensure the architect correctly understood the user's intent
**Performance Target**: <1500ms

**Validation Criteria**:
```python
class IntentValidationCriteria:
    """Criteria for validating task architecture understanding"""

    # Required validations
    prompt_alignment: float  # 0.0-1.0, user prompt vs task breakdown
    completeness: float      # 0.0-1.0, all requirements captured
    specificity: float       # 0.0-1.0, tasks are concrete and actionable

    # Domain-specific checks
    correct_node_type: bool  # Effect/Compute/Reducer/Orchestrator
    correct_domain: bool     # PostgreSQL, Kafka, etc.
    correct_integration: bool # Integration requirements captured

    # Quality thresholds
    MIN_ALIGNMENT = 0.85     # Must be 85% aligned with intent
    MIN_COMPLETENESS = 0.90  # Must capture 90% of requirements
    MIN_SPECIFICITY = 0.80   # Tasks must be 80% specific
```

**Quorum Question Template**:
```
Given the user's request:
"{original_user_prompt}"

The task architect generated this breakdown:
{task_breakdown_json}

Validate the following:
1. Does the task breakdown correctly understand the user's intent? (0-100 score)
2. Are all key requirements from the prompt captured? (list missing items)
3. Is the correct node type selected? (Effect/Compute/Reducer/Orchestrator)
4. Is the correct domain/technology identified? (e.g., PostgreSQL, Kafka)
5. Are integration requirements captured? (yes/no + explanation)

Provide structured JSON response:
{
  "alignment_score": 0-100,
  "completeness_score": 0-100,
  "missing_requirements": [...],
  "correct_node_type": true/false,
  "expected_node_type": "Effect|Compute|Reducer|Orchestrator",
  "correct_domain": true/false,
  "expected_domain": "...",
  "deficiencies": [...],
  "recommendation": "PASS|RETRY|FAIL"
}
```

### 3.2 Checkpoint 2: Generation Validation (Post-Coding)

**Location**: After `agent_coder.py` generates code
**Purpose**: Ensure generated code matches the task specification
**Performance Target**: <2000ms

**Validation Criteria**:
```python
class GenerationValidationCriteria:
    """Criteria for validating code generation correctness"""

    # Code correctness
    implements_contract: float    # 0.0-1.0, contract compliance
    naming_compliance: float      # 0.0-1.0, ONEX naming conventions
    functionality_match: float    # 0.0-1.0, matches task requirements

    # ONEX compliance
    correct_node_type: bool       # File/class matches node type
    correct_method_signature: bool # execute_* method correct
    contract_usage: bool          # Proper contract usage

    # Integration checks
    dependencies_correct: bool    # Required dependencies present
    imports_valid: bool          # Import statements correct

    # Quality thresholds
    MIN_CONTRACT_COMPLIANCE = 0.95
    MIN_NAMING_COMPLIANCE = 1.0   # Must be 100% compliant
    MIN_FUNCTIONALITY = 0.90
```

**Quorum Question Template**:
```
Task specification:
{task_specification}

Generated code:
{generated_code}

Contract definition:
{contract_definition}

Validate the following:
1. Does the generated code implement the specified contract? (0-100 score)
2. Does it follow ONEX naming conventions? (Node<Name><Type>, execute_<type>)
3. Does it match the task requirements? (0-100 score)
4. Are the correct dependencies and imports present? (list missing/incorrect)
5. Is the node type correct based on the code's purpose? (Effect/Compute/Reducer/Orchestrator)

Provide structured JSON response:
{
  "contract_compliance_score": 0-100,
  "naming_compliance_score": 0-100,
  "functionality_match_score": 0-100,
  "correct_node_type": true/false,
  "expected_vs_actual": {"expected": "...", "actual": "..."},
  "missing_dependencies": [...],
  "incorrect_imports": [...],
  "deficiencies": [...],
  "recommendation": "PASS|RETRY|FAIL"
}
```

### 3.3 Checkpoint 3: Quality Validation (Post-Debug)

**Location**: After `agent_debug_intelligence.py` validation
**Purpose**: Ensure functional correctness and production readiness
**Performance Target**: <1500ms

**Validation Criteria**:
```python
class QualityValidationCriteria:
    """Criteria for final quality validation"""

    # Functional correctness
    logic_correctness: float      # 0.0-1.0, implementation logic
    error_handling: float         # 0.0-1.0, error handling coverage
    edge_cases: float            # 0.0-1.0, edge case handling

    # ONEX architectural compliance
    architectural_compliance: float # 0.0-1.0, ONEX pattern adherence
    transaction_safety: bool       # Proper transaction management

    # Production readiness
    testability: float            # 0.0-1.0, code testability
    maintainability: float        # 0.0-1.0, code maintainability

    # Quality thresholds
    MIN_LOGIC_CORRECTNESS = 0.90
    MIN_ERROR_HANDLING = 0.85
    MIN_ARCHITECTURAL = 0.95
```

**Quorum Question Template**:
```
Original task:
{original_task}

Final generated code:
{final_code}

Debug intelligence report:
{debug_report}

Validate the following:
1. Is the implementation logic correct? (0-100 score)
2. Is error handling comprehensive? (0-100 score + gaps)
3. Are edge cases handled? (0-100 score + missing cases)
4. Does it follow ONEX architectural patterns? (0-100 score)
5. Is it production-ready? (yes/no + blockers)

Provide structured JSON response:
{
  "logic_correctness_score": 0-100,
  "error_handling_score": 0-100,
  "edge_case_score": 0-100,
  "architectural_compliance_score": 0-100,
  "production_ready": true/false,
  "blockers": [...],
  "deficiencies": [...],
  "recommendation": "PASS|RETRY|FAIL"
}
```

---

## 4. Quorum Voting Mechanism

### 4.1 Model Configuration

```python
from typing import Dict, List, Literal
from dataclasses import dataclass

@dataclass
class QuorumModel:
    """Configuration for a quorum validation model"""
    name: str
    endpoint: str  # Ollama/cloud endpoint
    weight: float  # Voting weight
    specialization: List[str]  # Areas of expertise
    timeout_ms: int
    enabled: bool = True

# AI Quorum Configuration
QUORUM_MODELS = {
    "gemini_flash": QuorumModel(
        name="Gemini Flash",
        endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent",
        weight=1.0,
        specialization=["general", "baseline"],
        timeout_ms=3000,
    ),
    "codestral": QuorumModel(
        name="Codestral",
        endpoint="http://192.168.86.200:11434/api/generate",  # Mac Studio
        weight=1.5,
        specialization=["code", "syntax", "patterns"],
        timeout_ms=5000,
    ),
    "deepseek_lite": QuorumModel(
        name="DeepSeek-Lite",
        endpoint="http://192.168.86.250:11434/api/generate",  # RTX 5090
        weight=2.0,
        specialization=["codegen", "architecture", "optimization"],
        timeout_ms=4000,
    ),
    "llama_31": QuorumModel(
        name="Llama 3.1",
        endpoint="http://192.168.86.240:11434/api/generate",  # RTX 4090
        weight=1.2,
        specialization=["reasoning", "logic", "validation"],
        timeout_ms=5000,
    ),
    "deepseek_full": QuorumModel(
        name="DeepSeek-Full",
        endpoint="http://192.168.86.230:11434/api/generate",  # Mac Mini
        weight=1.8,
        specialization=["code", "contracts", "compliance"],
        timeout_ms=6000,
    ),
}

# Total voting weight: 7.5
TOTAL_QUORUM_WEIGHT = sum(m.weight for m in QUORUM_MODELS.values())
```

### 4.2 Consensus Algorithm

```python
from enum import Enum
from typing import Any, Dict, List
import asyncio

class ValidationDecision(Enum):
    """Possible validation decisions"""
    PASS = "PASS"          # All validations passed, proceed
    RETRY = "RETRY"        # Validation failed, retry with feedback
    FAIL = "FAIL"          # Critical failure, cannot retry
    UNCERTAIN = "UNCERTAIN" # Consensus not reached

@dataclass
class ModelValidationResult:
    """Result from a single model validation"""
    model_name: str
    decision: ValidationDecision
    confidence: float  # 0.0-1.0
    scores: Dict[str, float]  # Individual metric scores
    deficiencies: List[str]
    reasoning: str

@dataclass
class QuorumConsensus:
    """Aggregated consensus from all models"""
    final_decision: ValidationDecision
    confidence: float  # Weighted average
    votes: Dict[ValidationDecision, float]  # Decision -> weighted votes
    aggregated_scores: Dict[str, float]  # Metric -> weighted avg score
    aggregated_deficiencies: List[str]  # Unique deficiencies
    model_results: List[ModelValidationResult]
    consensus_reached: bool
    retry_feedback: Dict[str, Any]  # Structured feedback for retry

class QuorumVotingEngine:
    """Consensus-based validation using multiple AI models"""

    def __init__(self, models: Dict[str, QuorumModel]):
        self.models = models
        self.total_weight = sum(m.weight for m in models.values() if m.enabled)

    async def validate_checkpoint(
        self,
        checkpoint_type: Literal["intent", "generation", "quality"],
        validation_data: Dict[str, Any],
        criteria: Any,  # ValidationCriteria instance
    ) -> QuorumConsensus:
        """
        Execute quorum validation for a checkpoint

        Process:
        1. Send validation request to all models in parallel
        2. Collect and parse responses (with timeout)
        3. Calculate weighted consensus
        4. Aggregate deficiencies for retry feedback
        """

        # Parallel execution with timeout
        tasks = [
            self._query_model(model, checkpoint_type, validation_data, criteria)
            for model in self.models.values()
            if model.enabled
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out failed models (timeouts, errors)
        valid_results = [
            r for r in results
            if isinstance(r, ModelValidationResult)
        ]

        if not valid_results:
            return QuorumConsensus(
                final_decision=ValidationDecision.UNCERTAIN,
                confidence=0.0,
                votes={},
                aggregated_scores={},
                aggregated_deficiencies=["No models responded successfully"],
                model_results=[],
                consensus_reached=False,
                retry_feedback={},
            )

        # Calculate weighted consensus
        return self._calculate_consensus(valid_results, criteria)

    async def _query_model(
        self,
        model: QuorumModel,
        checkpoint_type: str,
        validation_data: Dict[str, Any],
        criteria: Any,
    ) -> ModelValidationResult:
        """Query a single model for validation"""

        # Build prompt based on checkpoint type
        prompt = self._build_validation_prompt(
            checkpoint_type, validation_data, criteria
        )

        try:
            # Query model with timeout
            response = await asyncio.wait_for(
                self._call_model_api(model, prompt),
                timeout=model.timeout_ms / 1000.0,
            )

            # Parse structured response
            return self._parse_model_response(model.name, response)

        except asyncio.TimeoutError:
            # Model timeout - treat as uncertain vote
            return ModelValidationResult(
                model_name=model.name,
                decision=ValidationDecision.UNCERTAIN,
                confidence=0.0,
                scores={},
                deficiencies=[f"{model.name} timeout"],
                reasoning="Model timed out",
            )
        except Exception as e:
            # Model error - treat as uncertain vote
            return ModelValidationResult(
                model_name=model.name,
                decision=ValidationDecision.UNCERTAIN,
                confidence=0.0,
                scores={},
                deficiencies=[f"{model.name} error: {str(e)}"],
                reasoning=f"Model error: {str(e)}",
            )

    def _calculate_consensus(
        self,
        results: List[ModelValidationResult],
        criteria: Any,
    ) -> QuorumConsensus:
        """
        Calculate weighted consensus from model results

        Consensus algorithm:
        1. Weight each vote by model weight and confidence
        2. Aggregate scores using weighted average
        3. Collect unique deficiencies
        4. Determine final decision based on weighted votes
        """

        # Calculate weighted votes
        votes: Dict[ValidationDecision, float] = {
            ValidationDecision.PASS: 0.0,
            ValidationDecision.RETRY: 0.0,
            ValidationDecision.FAIL: 0.0,
            ValidationDecision.UNCERTAIN: 0.0,
        }

        total_weighted_confidence = 0.0

        for result in results:
            model = self.models[result.model_name.lower().replace(" ", "_")]
            weighted_vote = model.weight * result.confidence
            votes[result.decision] += weighted_vote
            total_weighted_confidence += weighted_vote

        # Normalize votes to percentages
        if total_weighted_confidence > 0:
            vote_percentages = {
                decision: vote / total_weighted_confidence
                for decision, vote in votes.items()
            }
        else:
            vote_percentages = votes

        # Determine final decision
        # Threshold: >60% weighted votes for PASS, >40% for RETRY, rest FAIL
        if vote_percentages[ValidationDecision.PASS] >= 0.60:
            final_decision = ValidationDecision.PASS
            consensus_reached = True
        elif vote_percentages[ValidationDecision.RETRY] >= 0.40:
            final_decision = ValidationDecision.RETRY
            consensus_reached = True
        elif vote_percentages[ValidationDecision.FAIL] >= 0.40:
            final_decision = ValidationDecision.FAIL
            consensus_reached = True
        else:
            # No clear consensus - default to RETRY with low confidence
            final_decision = ValidationDecision.RETRY
            consensus_reached = False

        # Aggregate scores (weighted average)
        aggregated_scores = self._aggregate_scores(results)

        # Aggregate deficiencies (unique)
        all_deficiencies = []
        for result in results:
            all_deficiencies.extend(result.deficiencies)
        aggregated_deficiencies = list(set(all_deficiencies))

        # Build retry feedback
        retry_feedback = self._build_retry_feedback(
            results, aggregated_scores, aggregated_deficiencies
        )

        return QuorumConsensus(
            final_decision=final_decision,
            confidence=vote_percentages.get(final_decision, 0.0),
            votes=vote_percentages,
            aggregated_scores=aggregated_scores,
            aggregated_deficiencies=aggregated_deficiencies,
            model_results=results,
            consensus_reached=consensus_reached,
            retry_feedback=retry_feedback,
        )

    def _aggregate_scores(
        self,
        results: List[ModelValidationResult],
    ) -> Dict[str, float]:
        """Aggregate scores using weighted average"""

        # Collect all unique score keys
        all_keys = set()
        for result in results:
            all_keys.update(result.scores.keys())

        # Calculate weighted average for each score
        aggregated = {}
        for key in all_keys:
            total_weighted_score = 0.0
            total_weight = 0.0

            for result in results:
                if key in result.scores:
                    model = self.models[result.model_name.lower().replace(" ", "_")]
                    weighted_score = model.weight * result.scores[key]
                    total_weighted_score += weighted_score
                    total_weight += model.weight

            if total_weight > 0:
                aggregated[key] = total_weighted_score / total_weight
            else:
                aggregated[key] = 0.0

        return aggregated

    def _build_retry_feedback(
        self,
        results: List[ModelValidationResult],
        scores: Dict[str, float],
        deficiencies: List[str],
    ) -> Dict[str, Any]:
        """Build structured feedback for retry attempt"""

        return {
            "scores": scores,
            "deficiencies": deficiencies,
            "model_reasoning": [
                {"model": r.model_name, "reasoning": r.reasoning}
                for r in results
            ],
            "improvement_areas": self._identify_improvement_areas(scores),
        }

    def _identify_improvement_areas(
        self,
        scores: Dict[str, float],
    ) -> List[str]:
        """Identify areas needing improvement based on low scores"""

        # Thresholds for each score type
        thresholds = {
            "alignment_score": 85.0,
            "completeness_score": 90.0,
            "contract_compliance_score": 95.0,
            "naming_compliance_score": 100.0,
            "functionality_match_score": 90.0,
            "logic_correctness_score": 90.0,
            "error_handling_score": 85.0,
            "architectural_compliance_score": 95.0,
        }

        improvement_areas = []
        for key, threshold in thresholds.items():
            if key in scores and scores[key] < threshold:
                improvement_areas.append(
                    f"{key}: {scores[key]:.1f} (threshold: {threshold})"
                )

        return improvement_areas
```

### 4.3 Consensus Thresholds

```python
class ConsensusThresholds:
    """Thresholds for consensus decisions"""

    # Vote percentage thresholds
    PASS_THRESHOLD = 0.60   # 60% weighted votes required to pass
    RETRY_THRESHOLD = 0.40  # 40% weighted votes triggers retry
    FAIL_THRESHOLD = 0.40   # 40% weighted votes triggers fail

    # Score thresholds (aligned with criteria)
    INTENT_VALIDATION = {
        "alignment_score": 85.0,
        "completeness_score": 90.0,
        "specificity_score": 80.0,
    }

    GENERATION_VALIDATION = {
        "contract_compliance_score": 95.0,
        "naming_compliance_score": 100.0,
        "functionality_match_score": 90.0,
    }

    QUALITY_VALIDATION = {
        "logic_correctness_score": 90.0,
        "error_handling_score": 85.0,
        "architectural_compliance_score": 95.0,
    }

    # Confidence thresholds
    MIN_CONSENSUS_CONFIDENCE = 0.70  # Require 70% confidence in decision
    MIN_MODEL_PARTICIPATION = 0.60   # At least 60% of models must respond
```

---

## 5. Deficiency Reporting System

### 5.1 Deficiency Structure

```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Deficiency:
    """A specific deficiency identified during validation"""
    category: str  # "alignment", "completeness", "naming", "logic", etc.
    severity: str  # "critical", "high", "medium", "low"
    description: str
    location: Optional[str]  # File, line, or section where deficiency exists
    expected: str  # What was expected
    actual: str  # What was found
    suggestion: str  # How to fix

@dataclass
class DeficiencyReport:
    """Aggregated deficiency report for retry"""
    checkpoint: str  # "intent", "generation", "quality"
    total_deficiencies: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    deficiencies: List[Deficiency]
    aggregated_feedback: str  # Human-readable summary
    structured_feedback: Dict[str, Any]  # Machine-readable feedback

class DeficiencyReporter:
    """Generate structured deficiency reports for retry"""

    def generate_report(
        self,
        checkpoint: str,
        consensus: QuorumConsensus,
        original_data: Dict[str, Any],
    ) -> DeficiencyReport:
        """Generate comprehensive deficiency report"""

        # Parse deficiencies from consensus
        deficiencies = self._parse_deficiencies(
            consensus.aggregated_deficiencies,
            consensus.model_results,
        )

        # Categorize by severity
        critical = [d for d in deficiencies if d.severity == "critical"]
        high = [d for d in deficiencies if d.severity == "high"]
        medium = [d for d in deficiencies if d.severity == "medium"]
        low = [d for d in deficiencies if d.severity == "low"]

        # Generate human-readable summary
        summary = self._generate_summary(
            checkpoint, deficiencies, consensus.aggregated_scores
        )

        # Build structured feedback for retry
        structured = self._build_structured_feedback(
            checkpoint, deficiencies, consensus, original_data
        )

        return DeficiencyReport(
            checkpoint=checkpoint,
            total_deficiencies=len(deficiencies),
            critical_count=len(critical),
            high_count=len(high),
            medium_count=len(medium),
            low_count=len(low),
            deficiencies=deficiencies,
            aggregated_feedback=summary,
            structured_feedback=structured,
        )

    def _parse_deficiencies(
        self,
        raw_deficiencies: List[str],
        model_results: List[ModelValidationResult],
    ) -> List[Deficiency]:
        """Parse raw deficiencies into structured format"""

        deficiencies = []

        # Extract deficiencies from model results
        for result in model_results:
            for deficiency_text in result.deficiencies:
                # Parse deficiency (format: "category: description")
                parts = deficiency_text.split(":", 1)
                if len(parts) == 2:
                    category = parts[0].strip()
                    description = parts[1].strip()
                else:
                    category = "general"
                    description = deficiency_text

                # Determine severity based on category and scores
                severity = self._determine_severity(category, result.scores)

                deficiencies.append(Deficiency(
                    category=category,
                    severity=severity,
                    description=description,
                    location=None,  # Could be enhanced with AST parsing
                    expected="",  # Could be extracted from criteria
                    actual="",
                    suggestion="",  # Could be generated by models
                ))

        return deficiencies

    def _determine_severity(
        self,
        category: str,
        scores: Dict[str, float],
    ) -> str:
        """Determine severity based on category and scores"""

        # Critical categories
        critical_categories = [
            "naming_compliance",
            "contract_compliance",
            "node_type",
        ]

        # High priority categories
        high_categories = [
            "alignment",
            "functionality",
            "logic_correctness",
            "architectural_compliance",
        ]

        if category in critical_categories:
            return "critical"
        elif category in high_categories:
            return "high"
        else:
            # Check score thresholds
            for key, score in scores.items():
                if category in key:
                    if score < 70:
                        return "high"
                    elif score < 85:
                        return "medium"
                    else:
                        return "low"

            return "medium"

    def _generate_summary(
        self,
        checkpoint: str,
        deficiencies: List[Deficiency],
        scores: Dict[str, float],
    ) -> str:
        """Generate human-readable summary"""

        summary = f"Validation failed at {checkpoint} checkpoint.\n\n"

        # Add score summary
        summary += "Scores:\n"
        for key, score in sorted(scores.items()):
            summary += f"  - {key}: {score:.1f}/100\n"

        summary += f"\nDeficiencies ({len(deficiencies)} total):\n"

        # Group by severity
        by_severity = {
            "critical": [d for d in deficiencies if d.severity == "critical"],
            "high": [d for d in deficiencies if d.severity == "high"],
            "medium": [d for d in deficiencies if d.severity == "medium"],
            "low": [d for d in deficiencies if d.severity == "low"],
        }

        for severity, items in by_severity.items():
            if items:
                summary += f"\n{severity.upper()} ({len(items)}):\n"
                for deficiency in items:
                    summary += f"  - [{deficiency.category}] {deficiency.description}\n"

        return summary

    def _build_structured_feedback(
        self,
        checkpoint: str,
        deficiencies: List[Deficiency],
        consensus: QuorumConsensus,
        original_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build machine-readable structured feedback"""

        return {
            "checkpoint": checkpoint,
            "decision": consensus.final_decision.value,
            "confidence": consensus.confidence,
            "scores": consensus.aggregated_scores,
            "deficiencies": [
                {
                    "category": d.category,
                    "severity": d.severity,
                    "description": d.description,
                }
                for d in deficiencies
            ],
            "improvement_areas": consensus.retry_feedback.get("improvement_areas", []),
            "model_reasoning": consensus.retry_feedback.get("model_reasoning", []),
            "retry_instructions": self._generate_retry_instructions(
                checkpoint, deficiencies, original_data
            ),
        }

    def _generate_retry_instructions(
        self,
        checkpoint: str,
        deficiencies: List[Deficiency],
        original_data: Dict[str, Any],
    ) -> str:
        """Generate specific instructions for retry attempt"""

        instructions = []

        if checkpoint == "intent":
            instructions.append("Re-analyze the user prompt with focus on:")
            for d in deficiencies:
                if d.category in ["alignment", "completeness"]:
                    instructions.append(f"  - {d.description}")

        elif checkpoint == "generation":
            instructions.append("Regenerate code with corrections:")
            for d in deficiencies:
                if d.severity in ["critical", "high"]:
                    instructions.append(f"  - {d.description}")

        elif checkpoint == "quality":
            instructions.append("Improve implementation with focus on:")
            for d in deficiencies:
                instructions.append(f"  - {d.description}")

        return "\n".join(instructions)
```

---

## 6. Retry Strategy

### 6.1 Retry Configuration

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class RetryConfig:
    """Configuration for retry strategy"""

    # Retry limits
    max_retries: int = 3  # Maximum retry attempts per checkpoint
    max_total_retries: int = 5  # Maximum retries across all checkpoints

    # Backoff strategy
    initial_backoff_ms: int = 1000  # Initial backoff delay
    backoff_multiplier: float = 1.5  # Backoff multiplier per retry
    max_backoff_ms: int = 10000  # Maximum backoff delay

    # Retry conditions
    retry_on_uncertain: bool = True  # Retry if consensus is uncertain
    retry_on_low_confidence: bool = True  # Retry if confidence < threshold
    min_confidence_threshold: float = 0.70  # Minimum confidence to accept

    # Improvement requirements
    min_improvement_threshold: float = 0.10  # Require 10% improvement
    require_different_output: bool = True  # Retry must produce different output

    # Timeout configuration
    retry_timeout_multiplier: float = 1.2  # Increase timeout per retry
    max_retry_timeout_ms: int = 30000  # Maximum timeout per retry

@dataclass
class RetryAttempt:
    """Record of a retry attempt"""
    attempt_number: int
    checkpoint: str
    previous_consensus: QuorumConsensus
    deficiency_report: DeficiencyReport
    retry_context: Dict[str, Any]
    timestamp: float
```

### 6.2 Retry Orchestrator

```python
import time
from typing import Any, Callable, Dict, Optional

class RetryOrchestrator:
    """Orchestrate retry logic with bounded attempts and improvement tracking"""

    def __init__(self, config: RetryConfig):
        self.config = config
        self.retry_history: List[RetryAttempt] = []
        self.total_retries = 0

    async def execute_with_retry(
        self,
        checkpoint: str,
        validation_func: Callable,
        generation_func: Callable,
        initial_data: Dict[str, Any],
    ) -> tuple[QuorumConsensus, Optional[Any]]:
        """
        Execute validation with retry logic

        Args:
            checkpoint: Checkpoint name
            validation_func: Function that validates output
            generation_func: Function that generates/regenerates output
            initial_data: Initial input data

        Returns:
            (final_consensus, final_output) or raises RetryExhausted
        """

        current_data = initial_data
        previous_scores = None

        for attempt in range(self.config.max_retries + 1):
            # Check global retry limit
            if self.total_retries >= self.config.max_total_retries:
                raise RetryExhausted(
                    f"Maximum total retries ({self.config.max_total_retries}) exceeded"
                )

            # Generate output (first attempt uses initial data, retries use feedback)
            if attempt == 0:
                output = await generation_func(current_data)
            else:
                # Apply backoff delay
                backoff_ms = min(
                    self.config.initial_backoff_ms * (self.config.backoff_multiplier ** (attempt - 1)),
                    self.config.max_backoff_ms,
                )
                await asyncio.sleep(backoff_ms / 1000.0)

                # Regenerate with deficiency feedback
                retry_context = self._build_retry_context(
                    current_data,
                    self.retry_history[-1].deficiency_report,
                )
                output = await generation_func(retry_context)

                # Check if output changed
                if self.config.require_different_output:
                    if self._is_same_output(output, current_data.get("previous_output")):
                        # Output didn't change, skip validation
                        continue

            # Validate output
            consensus = await validation_func(output)

            # Record attempt
            if attempt > 0:
                self.retry_history.append(RetryAttempt(
                    attempt_number=attempt,
                    checkpoint=checkpoint,
                    previous_consensus=consensus,
                    deficiency_report=DeficiencyReporter().generate_report(
                        checkpoint, consensus, current_data
                    ),
                    retry_context=current_data,
                    timestamp=time.time(),
                ))
                self.total_retries += 1

            # Check if validation passed
            if consensus.final_decision == ValidationDecision.PASS:
                # Check confidence threshold
                if consensus.confidence >= self.config.min_confidence_threshold:
                    return (consensus, output)
                elif not self.config.retry_on_low_confidence:
                    return (consensus, output)

            # Check if validation failed critically
            if consensus.final_decision == ValidationDecision.FAIL:
                raise ValidationFailed(
                    f"Critical validation failure at {checkpoint}",
                    consensus=consensus,
                )

            # Check if we should retry
            if not self._should_retry(consensus, attempt):
                # Consensus is uncertain but we've exhausted retries
                if consensus.final_decision == ValidationDecision.UNCERTAIN:
                    raise RetryExhausted(
                        f"No consensus reached after {attempt + 1} attempts"
                    )
                else:
                    # RETRY decision but no more attempts
                    raise RetryExhausted(
                        f"Maximum retries ({self.config.max_retries}) exceeded"
                    )

            # Check improvement requirement
            if previous_scores and self.config.min_improvement_threshold > 0:
                improvement = self._calculate_improvement(
                    previous_scores,
                    consensus.aggregated_scores,
                )
                if improvement < self.config.min_improvement_threshold:
                    raise InsufficientImprovement(
                        f"Improvement {improvement:.1%} below threshold "
                        f"{self.config.min_improvement_threshold:.1%}"
                    )

            # Prepare for retry
            previous_scores = consensus.aggregated_scores
            current_data = {
                **current_data,
                "previous_output": output,
                "deficiency_report": DeficiencyReporter().generate_report(
                    checkpoint, consensus, current_data
                ),
                "retry_attempt": attempt + 1,
            }

        # Exhausted all retries
        raise RetryExhausted(
            f"Maximum retries ({self.config.max_retries}) exceeded"
        )

    def _should_retry(
        self,
        consensus: QuorumConsensus,
        attempt: int,
    ) -> bool:
        """Determine if we should retry based on consensus and attempt count"""

        # Don't retry if we've hit max attempts
        if attempt >= self.config.max_retries:
            return False

        # Retry on RETRY decision
        if consensus.final_decision == ValidationDecision.RETRY:
            return True

        # Retry on UNCERTAIN if configured
        if consensus.final_decision == ValidationDecision.UNCERTAIN:
            return self.config.retry_on_uncertain

        # Retry on low confidence PASS if configured
        if consensus.final_decision == ValidationDecision.PASS:
            if consensus.confidence < self.config.min_confidence_threshold:
                return self.config.retry_on_low_confidence

        return False

    def _build_retry_context(
        self,
        original_data: Dict[str, Any],
        deficiency_report: DeficiencyReport,
    ) -> Dict[str, Any]:
        """Build context for retry attempt with deficiency feedback"""

        return {
            **original_data,
            "retry_feedback": {
                "deficiencies": deficiency_report.structured_feedback["deficiencies"],
                "improvement_areas": deficiency_report.structured_feedback["improvement_areas"],
                "retry_instructions": deficiency_report.structured_feedback["retry_instructions"],
                "scores": deficiency_report.structured_feedback["scores"],
            },
            "is_retry": True,
        }

    def _is_same_output(
        self,
        output1: Any,
        output2: Any,
    ) -> bool:
        """Check if two outputs are substantially the same"""

        # Simple string comparison for now
        # Could be enhanced with AST comparison for code
        if isinstance(output1, str) and isinstance(output2, str):
            return output1.strip() == output2.strip()

        return output1 == output2

    def _calculate_improvement(
        self,
        previous_scores: Dict[str, float],
        current_scores: Dict[str, float],
    ) -> float:
        """Calculate improvement percentage between attempts"""

        if not previous_scores or not current_scores:
            return 0.0

        # Calculate average score improvement
        improvements = []
        for key in previous_scores:
            if key in current_scores:
                prev = previous_scores[key]
                curr = current_scores[key]
                if prev > 0:
                    improvement = (curr - prev) / prev
                    improvements.append(improvement)

        if improvements:
            return sum(improvements) / len(improvements)

        return 0.0

    def get_retry_statistics(self) -> Dict[str, Any]:
        """Get retry statistics for monitoring"""

        return {
            "total_retries": self.total_retries,
            "attempts_by_checkpoint": self._count_by_checkpoint(),
            "average_improvement": self._average_improvement(),
            "retry_success_rate": self._calculate_success_rate(),
        }

    def _count_by_checkpoint(self) -> Dict[str, int]:
        """Count retry attempts by checkpoint"""

        counts = {}
        for attempt in self.retry_history:
            counts[attempt.checkpoint] = counts.get(attempt.checkpoint, 0) + 1
        return counts

    def _average_improvement(self) -> float:
        """Calculate average improvement across retries"""

        # Implementation would track score improvements
        return 0.0

    def _calculate_success_rate(self) -> float:
        """Calculate retry success rate"""

        if not self.retry_history:
            return 0.0

        # Success = eventually passed validation
        # This would need to track final outcomes
        return 0.0

# Custom exceptions
class RetryExhausted(Exception):
    """Raised when maximum retries are exhausted"""
    pass

class ValidationFailed(Exception):
    """Raised when validation fails critically"""
    def __init__(self, message: str, consensus: QuorumConsensus):
        super().__init__(message)
        self.consensus = consensus

class InsufficientImprovement(Exception):
    """Raised when retry doesn't show sufficient improvement"""
    pass
```

### 6.3 Retry Integration Example

```python
class ValidatedWorkflow:
    """Workflow with integrated quorum validation and retry"""

    def __init__(self):
        self.quorum = QuorumVotingEngine(QUORUM_MODELS)
        self.retry_orchestrator = RetryOrchestrator(RetryConfig())
        self.deficiency_reporter = DeficiencyReporter()

    async def execute_intent_validation(
        self,
        user_prompt: str,
    ) -> Dict[str, Any]:
        """Execute task architecture with validation and retry"""

        async def generate_architecture(data):
            """Generate task breakdown"""
            # Call task_architect.py
            return await task_architect.breakdown_tasks(data["user_prompt"])

        async def validate_architecture(architecture):
            """Validate architecture with quorum"""
            validation_data = {
                "original_user_prompt": user_prompt,
                "task_breakdown_json": architecture,
            }
            criteria = IntentValidationCriteria()
            return await self.quorum.validate_checkpoint(
                "intent", validation_data, criteria
            )

        # Execute with retry
        consensus, architecture = await self.retry_orchestrator.execute_with_retry(
            checkpoint="intent",
            validation_func=validate_architecture,
            generation_func=generate_architecture,
            initial_data={"user_prompt": user_prompt},
        )

        return {
            "architecture": architecture,
            "consensus": consensus,
            "validated": True,
        }
```

---

## 7. Integration with Quality Gates

### 7.1 Quality Gate Mapping

Map quorum validation checkpoints to existing quality gates:

```python
# Quality gate integration
CHECKPOINT_TO_QUALITY_GATES = {
    "intent": [
        "SV-001",  # Input Validation
        "IV-001",  # RAG Query Validation
        "IV-002",  # Knowledge Application
    ],
    "generation": [
        "SV-002",  # Process Validation
        "QC-001",  # ONEX Standards
        "QC-003",  # Type Safety
    ],
    "quality": [
        "SV-003",  # Output Validation
        "QC-002",  # Anti-YOLO Compliance
        "QC-004",  # Error Handling
        "PF-001",  # Performance Thresholds
    ],
}
```

### 7.2 Enhanced Quality Gate Execution

```python
class EnhancedQualityGate:
    """Quality gate with integrated quorum validation"""

    def __init__(
        self,
        gate_id: str,
        gate_config: Dict[str, Any],
        quorum_engine: QuorumVotingEngine,
    ):
        self.gate_id = gate_id
        self.config = gate_config
        self.quorum = quorum_engine

    async def execute(
        self,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute quality gate with quorum validation

        Process:
        1. Run traditional quality gate checks
        2. If traditional checks pass, run quorum validation
        3. Combine results for final decision
        """

        # Traditional quality gate checks
        traditional_result = await self._execute_traditional_checks(data)

        # If traditional checks fail, no need for quorum
        if not traditional_result["passed"]:
            return traditional_result

        # Run quorum validation
        checkpoint_type = self._map_gate_to_checkpoint()
        if checkpoint_type:
            quorum_result = await self.quorum.validate_checkpoint(
                checkpoint_type,
                data,
                self._get_criteria(checkpoint_type),
            )

            # Combine results
            return self._combine_results(traditional_result, quorum_result)

        return traditional_result

    def _map_gate_to_checkpoint(self) -> Optional[str]:
        """Map quality gate to validation checkpoint"""
        for checkpoint, gates in CHECKPOINT_TO_QUALITY_GATES.items():
            if self.gate_id in gates:
                return checkpoint
        return None
```

---

## 8. Performance Optimization

### 8.1 Caching Strategy

```python
from functools import lru_cache
import hashlib
import json

class ValidationCache:
    """Cache for validation results to avoid redundant quorum queries"""

    def __init__(self, ttl_seconds: int = 3600):
        self.cache: Dict[str, tuple[QuorumConsensus, float]] = {}
        self.ttl_seconds = ttl_seconds

    def _compute_hash(self, checkpoint: str, data: Dict[str, Any]) -> str:
        """Compute cache key from checkpoint and data"""
        # Create stable hash of validation input
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(f"{checkpoint}:{data_str}".encode()).hexdigest()

    def get(
        self,
        checkpoint: str,
        data: Dict[str, Any],
    ) -> Optional[QuorumConsensus]:
        """Get cached validation result if available and fresh"""
        cache_key = self._compute_hash(checkpoint, data)

        if cache_key in self.cache:
            consensus, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.ttl_seconds:
                return consensus
            else:
                # Expired, remove from cache
                del self.cache[cache_key]

        return None

    def set(
        self,
        checkpoint: str,
        data: Dict[str, Any],
        consensus: QuorumConsensus,
    ):
        """Cache validation result"""
        cache_key = self._compute_hash(checkpoint, data)
        self.cache[cache_key] = (consensus, time.time())

    def clear_expired(self):
        """Remove expired entries"""
        current_time = time.time()
        expired_keys = [
            key for key, (_, timestamp) in self.cache.items()
            if current_time - timestamp >= self.ttl_seconds
        ]
        for key in expired_keys:
            del self.cache[key]
```

### 8.2 Parallel Model Querying

Already implemented in `QuorumVotingEngine._query_model` using `asyncio.gather` for parallel execution.

### 8.3 Model Selection Optimization

```python
class AdaptiveModelSelector:
    """Select optimal subset of models based on checkpoint and history"""

    def __init__(self, quorum_models: Dict[str, QuorumModel]):
        self.all_models = quorum_models
        self.performance_history: Dict[str, Dict[str, float]] = {}

    def select_models(
        self,
        checkpoint: str,
        complexity: str = "medium",
    ) -> Dict[str, QuorumModel]:
        """Select optimal models for checkpoint"""

        # For low complexity, use fast models only
        if complexity == "low":
            return {
                "gemini_flash": self.all_models["gemini_flash"],
                "codestral": self.all_models["codestral"],
            }

        # For high complexity, use all models
        if complexity == "high":
            return self.all_models

        # Medium complexity: select based on specialization
        selected = {}
        for name, model in self.all_models.items():
            if self._is_specialized_for(model, checkpoint):
                selected[name] = model

        # Ensure minimum of 3 models
        if len(selected) < 3:
            # Add models by weight
            remaining = {
                k: v for k, v in self.all_models.items()
                if k not in selected
            }
            sorted_models = sorted(
                remaining.items(),
                key=lambda x: x[1].weight,
                reverse=True,
            )
            for name, model in sorted_models:
                selected[name] = model
                if len(selected) >= 3:
                    break

        return selected

    def _is_specialized_for(self, model: QuorumModel, checkpoint: str) -> bool:
        """Check if model is specialized for checkpoint"""
        specialization_map = {
            "intent": ["reasoning", "general"],
            "generation": ["code", "codegen", "patterns"],
            "quality": ["validation", "architecture", "compliance"],
        }

        required_specs = specialization_map.get(checkpoint, [])
        return any(spec in model.specialization for spec in required_specs)
```

### 8.4 Performance Monitoring

```python
from dataclasses import dataclass
import time
from typing import List

@dataclass
class ValidationMetrics:
    """Performance metrics for validation"""
    checkpoint: str
    total_time_ms: float
    quorum_time_ms: float
    model_times_ms: Dict[str, float]
    cache_hit: bool
    retry_count: int
    decision: ValidationDecision
    confidence: float

class PerformanceMonitor:
    """Monitor validation performance"""

    def __init__(self):
        self.metrics: List[ValidationMetrics] = []

    async def monitor_validation(
        self,
        checkpoint: str,
        validation_func: Callable,
    ) -> tuple[QuorumConsensus, ValidationMetrics]:
        """Monitor validation performance"""

        start_time = time.time()

        # Execute validation
        consensus = await validation_func()

        total_time = (time.time() - start_time) * 1000

        # Collect metrics
        metrics = ValidationMetrics(
            checkpoint=checkpoint,
            total_time_ms=total_time,
            quorum_time_ms=total_time,  # Simplified
            model_times_ms={},  # Would track individual model times
            cache_hit=False,
            retry_count=0,
            decision=consensus.final_decision,
            confidence=consensus.confidence,
        )

        self.metrics.append(metrics)

        return consensus, metrics

    def get_statistics(self) -> Dict[str, Any]:
        """Get performance statistics"""
        if not self.metrics:
            return {}

        return {
            "total_validations": len(self.metrics),
            "average_time_ms": sum(m.total_time_ms for m in self.metrics) / len(self.metrics),
            "cache_hit_rate": sum(1 for m in self.metrics if m.cache_hit) / len(self.metrics),
            "average_confidence": sum(m.confidence for m in self.metrics) / len(self.metrics),
            "decision_distribution": self._decision_distribution(),
        }

    def _decision_distribution(self) -> Dict[str, int]:
        """Get distribution of decisions"""
        distribution = {}
        for metric in self.metrics:
            decision = metric.decision.value
            distribution[decision] = distribution.get(decision, 0) + 1
        return distribution
```

---

## 9. Implementation Phases

### Phase 1: Core Infrastructure (Week 1)

**Deliverables**:
- [ ] `quorum_voting_engine.py` - Quorum voting mechanism
- [ ] `validation_criteria.py` - Checkpoint validation criteria
- [ ] `deficiency_reporter.py` - Deficiency reporting system
- [ ] `retry_orchestrator.py` - Retry logic with bounded attempts

**Success Criteria**:
- All core components pass unit tests
- Mock validation succeeds with >90% accuracy
- Performance overhead <500ms per checkpoint (without model calls)

### Phase 2: Model Integration (Week 2)

**Deliverables**:
- [ ] Integrate with 5 AI Quorum models
- [ ] Implement parallel model querying
- [ ] Add timeout and error handling
- [ ] Create model response parsers

**Success Criteria**:
- All models respond within timeout
- Parallel execution <2000ms for 5 models
- Error handling prevents cascade failures
- Response parsing >95% accuracy

### Phase 3: Checkpoint Integration (Week 3)

**Deliverables**:
- [ ] Integrate Checkpoint 1: Intent Validation
- [ ] Integrate Checkpoint 2: Generation Validation
- [ ] Integrate Checkpoint 3: Quality Validation
- [ ] Add checkpoint orchestration

**Success Criteria**:
- Each checkpoint validates correctly
- Integration with existing agents works
- No regression in existing functionality
- End-to-end workflow completes successfully

### Phase 4: Optimization & Monitoring (Week 4)

**Deliverables**:
- [ ] Implement validation caching
- [ ] Add performance monitoring
- [ ] Optimize model selection
- [ ] Create monitoring dashboard

**Success Criteria**:
- Cache hit rate >40%
- Performance overhead <30%
- Monitoring captures all key metrics
- Dashboard shows real-time validation status

### Phase 5: Production Hardening (Week 5)

**Deliverables**:
- [ ] Integration with quality gates
- [ ] Production error handling
- [ ] Performance tuning
- [ ] Documentation and runbooks

**Success Criteria**:
- All quality gates pass
- Error rate <5%
- Performance targets met
- Complete documentation delivered

---

## 10. Success Metrics & Monitoring

### 10.1 Validation Accuracy Metrics

```python
class AccuracyMetrics:
    """Track validation accuracy"""

    # Detection metrics
    true_positives: int  # Correctly identified bad outputs
    false_positives: int  # Incorrectly rejected good outputs
    true_negatives: int  # Correctly accepted good outputs
    false_negatives: int  # Incorrectly accepted bad outputs

    @property
    def precision(self) -> float:
        """Precision: TP / (TP + FP)"""
        if self.true_positives + self.false_positives == 0:
            return 0.0
        return self.true_positives / (self.true_positives + self.false_positives)

    @property
    def recall(self) -> float:
        """Recall: TP / (TP + FN)"""
        if self.true_positives + self.false_negatives == 0:
            return 0.0
        return self.true_positives / (self.true_positives + self.false_negatives)

    @property
    def f1_score(self) -> float:
        """F1 Score: 2 * (precision * recall) / (precision + recall)"""
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * (self.precision * self.recall) / (self.precision + self.recall)
```

### 10.2 Performance Impact Metrics

```python
class PerformanceImpactMetrics:
    """Track performance impact of validation"""

    baseline_execution_time_ms: float  # Without validation
    validation_execution_time_ms: float  # With validation

    @property
    def overhead_percentage(self) -> float:
        """Overhead as percentage of baseline"""
        if self.baseline_execution_time_ms == 0:
            return 0.0
        overhead = self.validation_execution_time_ms - self.baseline_execution_time_ms
        return (overhead / self.baseline_execution_time_ms) * 100

    @property
    def acceptable(self) -> bool:
        """Check if overhead is acceptable (<30%)"""
        return self.overhead_percentage < 30.0
```

### 10.3 Retry Effectiveness Metrics

```python
class RetryEffectivenessMetrics:
    """Track retry effectiveness"""

    total_retries: int
    successful_retries: int  # Retries that eventually passed
    failed_retries: int  # Retries that exhausted attempts

    @property
    def retry_success_rate(self) -> float:
        """Percentage of retries that succeeded"""
        if self.total_retries == 0:
            return 0.0
        return (self.successful_retries / self.total_retries) * 100

    @property
    def acceptable(self) -> bool:
        """Check if retry success rate is acceptable (>80%)"""
        return self.retry_success_rate >= 80.0
```

### 10.4 Monitoring Dashboard

```python
class ValidationDashboard:
    """Real-time monitoring dashboard"""

    def __init__(self):
        self.accuracy = AccuracyMetrics()
        self.performance = PerformanceImpactMetrics()
        self.retry = RetryEffectivenessMetrics()

    def get_status(self) -> Dict[str, Any]:
        """Get current validation system status"""
        return {
            "accuracy": {
                "precision": f"{self.accuracy.precision:.2%}",
                "recall": f"{self.accuracy.recall:.2%}",
                "f1_score": f"{self.accuracy.f1_score:.2%}",
                "target": "F1 > 95%",
                "status": "✓" if self.accuracy.f1_score >= 0.95 else "✗",
            },
            "performance": {
                "overhead": f"{self.performance.overhead_percentage:.1f}%",
                "target": "< 30%",
                "status": "✓" if self.performance.acceptable else "✗",
            },
            "retry": {
                "success_rate": f"{self.retry.retry_success_rate:.1f}%",
                "target": "> 80%",
                "status": "✓" if self.retry.acceptable else "✗",
            },
        }
```

---

## 11. Risk Mitigation

### 11.1 Identified Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Model timeout cascades | Medium | High | Individual timeouts, graceful degradation |
| False positive validations | Medium | Medium | Tune thresholds, manual override option |
| Performance degradation | High | Medium | Caching, adaptive model selection |
| Infinite retry loops | Low | High | Bounded retries, improvement requirements |
| Consensus disagreement | Medium | Medium | Weighted voting, uncertainty handling |

### 11.2 Fallback Strategies

```python
class ValidationFallbackStrategy:
    """Fallback strategies for validation failures"""

    @staticmethod
    async def handle_model_timeout(
        checkpoint: str,
        available_models: List[str],
    ) -> QuorumConsensus:
        """Handle scenario where models timeout"""

        # If <60% of models respond, return uncertain
        if len(available_models) < 3:
            return QuorumConsensus(
                final_decision=ValidationDecision.UNCERTAIN,
                confidence=0.0,
                # ...
            )

        # Continue with available models
        return await quorum.validate_checkpoint(
            checkpoint,
            validation_data,
            criteria,
            models=available_models,
        )

    @staticmethod
    def handle_no_consensus(
        checkpoint: str,
        consensus: QuorumConsensus,
    ) -> ValidationDecision:
        """Handle scenario where no consensus is reached"""

        # Default to RETRY with human review flag
        return ValidationDecision.RETRY
```

---

## 12. Testing Strategy

### 12.1 Unit Tests

```python
# test_quorum_voting.py
async def test_consensus_calculation():
    """Test consensus calculation with various vote distributions"""

    # Test case: 60% PASS, 30% RETRY, 10% UNCERTAIN
    results = [
        ModelValidationResult("model1", ValidationDecision.PASS, 0.9, ...),
        ModelValidationResult("model2", ValidationDecision.PASS, 0.85, ...),
        ModelValidationResult("model3", ValidationDecision.RETRY, 0.7, ...),
        ModelValidationResult("model4", ValidationDecision.UNCERTAIN, 0.3, ...),
    ]

    consensus = quorum._calculate_consensus(results, criteria)

    assert consensus.final_decision == ValidationDecision.PASS
    assert consensus.confidence >= 0.60

# test_retry_orchestrator.py
async def test_retry_with_improvement():
    """Test retry succeeds when output improves"""

    attempt_count = 0
    async def mock_generation(data):
        nonlocal attempt_count
        attempt_count += 1
        return f"output_v{attempt_count}"

    async def mock_validation(output):
        # First attempt fails, second succeeds
        if "v1" in output:
            return QuorumConsensus(ValidationDecision.RETRY, ...)
        else:
            return QuorumConsensus(ValidationDecision.PASS, ...)

    consensus, output = await retry_orchestrator.execute_with_retry(
        "test", mock_validation, mock_generation, {}
    )

    assert consensus.final_decision == ValidationDecision.PASS
    assert attempt_count == 2
```

### 12.2 Integration Tests

```python
# test_end_to_end_validation.py
async def test_full_workflow_with_validation():
    """Test complete workflow with all three checkpoints"""

    user_prompt = "Create a PostgreSQL adapter Effect node"

    # Execute validated workflow
    result = await validated_workflow.execute(user_prompt)

    # Verify all checkpoints passed
    assert result["intent_validation"].final_decision == ValidationDecision.PASS
    assert result["generation_validation"].final_decision == ValidationDecision.PASS
    assert result["quality_validation"].final_decision == ValidationDecision.PASS

    # Verify output is correct
    assert "PostgreSQL" in result["generated_code"]
    assert "NodeEffect" in result["generated_code"]
```

### 12.3 Performance Tests

```python
# test_performance.py
async def test_validation_performance():
    """Test validation meets performance targets"""

    start_time = time.time()

    # Execute validation
    consensus = await quorum.validate_checkpoint("intent", data, criteria)

    elapsed_ms = (time.time() - start_time) * 1000

    # Performance targets
    assert elapsed_ms < 1500  # Intent validation <1500ms
    assert consensus.final_decision != ValidationDecision.UNCERTAIN
```

---

## 13. Deployment Plan

### 13.1 Rollout Strategy

**Phase 1: Shadow Mode (Week 1)**
- Run validation in parallel without blocking
- Collect metrics on accuracy and performance
- Identify false positives/negatives
- Tune thresholds

**Phase 2: Soft Launch (Week 2)**
- Enable validation for 10% of workflows
- Monitor for issues
- Collect user feedback
- Iterate on deficiency reporting

**Phase 3: Full Deployment (Week 3)**
- Enable validation for all workflows
- Monitor performance impact
- Continue optimization
- Expand model pool if needed

### 13.2 Monitoring Plan

```python
# monitoring/validation_monitoring.py
class ValidationMonitoring:
    """Production monitoring for validation system"""

    def __init__(self):
        self.metrics_collector = MetricsCollector()
        self.alert_manager = AlertManager()

    async def monitor_validation_health(self):
        """Continuously monitor validation system health"""

        while True:
            # Collect metrics
            metrics = self.metrics_collector.collect()

            # Check thresholds
            if metrics["accuracy"]["f1_score"] < 0.90:
                await self.alert_manager.send_alert(
                    severity="high",
                    message=f"Validation accuracy dropped to {metrics['accuracy']['f1_score']:.2%}",
                )

            if metrics["performance"]["overhead"] > 35.0:
                await self.alert_manager.send_alert(
                    severity="medium",
                    message=f"Validation overhead at {metrics['performance']['overhead']:.1f}%",
                )

            # Wait before next check
            await asyncio.sleep(60)  # Check every minute
```

---

## 14. Documentation Requirements

### 14.1 User Documentation

- **Validation Overview**: How quorum validation works
- **Deficiency Reports**: How to interpret validation failures
- **Retry Behavior**: What happens during retries
- **Performance Impact**: Expected overhead and optimization tips

### 14.2 Developer Documentation

- **Integration Guide**: How to integrate validation into agents
- **Model Configuration**: How to add/configure models
- **Threshold Tuning**: How to tune validation thresholds
- **Debugging Guide**: How to debug validation issues

### 14.3 Operations Documentation

- **Monitoring Runbook**: How to monitor validation health
- **Alert Response**: How to respond to validation alerts
- **Performance Tuning**: How to optimize validation performance
- **Disaster Recovery**: How to recover from validation failures

---

## 15. Conclusion

This implementation plan provides a comprehensive approach to implementing quorum-based validation for the parallel agent execution system. The system addresses the critical issue of agents generating incorrect outputs while claiming success by:

1. **Validating at 3 checkpoints**: Intent, Generation, and Quality
2. **Using consensus from 5 AI models**: Weighted voting with specialization
3. **Providing actionable feedback**: Structured deficiency reports for retry
4. **Implementing bounded retry**: Maximum 3 retries per checkpoint, 5 total
5. **Integrating with existing framework**: Quality gates and performance thresholds
6. **Maintaining performance**: <30% overhead target through caching and optimization

**Expected Outcomes**:
- >95% detection of incorrect outputs
- <5% false positive rate
- >80% retry success rate
- <30% performance overhead
- Significant improvement in user trust and system reliability

**Next Steps**:
1. Review and approve implementation plan
2. Begin Phase 1: Core Infrastructure
3. Set up monitoring and metrics collection
4. Create test harness for validation accuracy
5. Proceed with phased rollout

This system will transform the parallel agent execution from a "hope for the best" approach to a validated, reliable system with confidence-scored outputs and automatic correction capabilities.
