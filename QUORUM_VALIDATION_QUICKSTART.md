# Quorum Validation Quick Start Guide
## Immediate Implementation Steps

This guide provides the fastest path to implementing quorum validation for critical workflows.

---

## 1. Quick Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        User Request                                  │
│                "Create PostgreSQL adapter Effect node"               │
└─────────────────────────┬───────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│ CHECKPOINT 1: Intent Validation                                      │
│ ┌─────────────────┐    ┌──────────────────────────────────────┐   │
│ │ task_architect  │───▶│ Quorum: Does breakdown match intent? │   │
│ │ generates tasks │    │ - Gemini Flash                        │   │
│ └─────────────────┘    │ - Codestral                          │   │
│                        │ - DeepSeek-Lite                       │   │
│                        │ - Llama 3.1                           │   │
│                        │ - DeepSeek-Full                       │   │
│                        └──────────────────────────────────────┘   │
│                                     │                               │
│                        ┌────────────┴────────────┐                 │
│                        │ PASS    │    RETRY      │                 │
│                        ▼         ▼               │                 │
└────────────────────────┼─────────┼───────────────┘                 │
                         │         │                                  │
                         │    ┌────┴────────────────────────┐       │
                         │    │ Retry with deficiencies:    │       │
                         │    │ - "Node type should be      │       │
                         │    │    Effect, not Compute"     │       │
                         │    │ - "Missing Kafka            │       │
                         │    │    integration requirement" │       │
                         │    └─────────────────────────────┘       │
                         │                                            │
                         ▼                                            │
┌─────────────────────────────────────────────────────────────────────┐
│ CHECKPOINT 2: Generation Validation                                  │
│ ┌─────────────────┐    ┌──────────────────────────────────────┐   │
│ │ agent_coder     │───▶│ Quorum: Does code match spec?        │   │
│ │ generates code  │    │ Models vote on:                       │   │
│ └─────────────────┘    │ - Contract compliance: 95/100         │   │
│                        │ - Naming compliance: 100/100          │   │
│                        │ - Functionality match: 92/100         │   │
│                        └──────────────────────────────────────┘   │
│                                     │                               │
│                        ┌────────────┴────────────┐                 │
│                        │ PASS    │    RETRY      │                 │
│                        ▼         ▼               │                 │
└────────────────────────┼─────────┼───────────────┘                 │
                         │         │                                  │
                         │    ┌────┴────────────────────────┐       │
                         │    │ Retry with fixes:           │       │
                         │    │ - "Use execute_effect not   │       │
                         │    │    execute_compute"         │       │
                         │    │ - "Add Kafka import"        │       │
                         │    └─────────────────────────────┘       │
                         │                                            │
                         ▼                                            │
┌─────────────────────────────────────────────────────────────────────┐
│ CHECKPOINT 3: Quality Validation                                     │
│ ┌─────────────────┐    ┌──────────────────────────────────────┐   │
│ │ agent_debug_    │───▶│ Quorum: Is code production-ready?    │   │
│ │ intelligence    │    │ Models verify:                        │   │
│ └─────────────────┘    │ - Logic correctness: 94/100           │   │
│                        │ - Error handling: 89/100              │   │
│                        │ - ONEX compliance: 97/100             │   │
│                        └──────────────────────────────────────┘   │
│                                     │                               │
│                        ┌────────────┴────────────┐                 │
│                        │ PASS    │    FAIL       │                 │
│                        ▼         ▼               │                 │
└────────────────────────┼─────────┼───────────────┘                 │
                         │         │                                  │
                         │    ┌────┴────────────────────────┐       │
                         │    │ Critical issues found:      │       │
                         │    │ Cannot retry automatically  │       │
                         │    │ Requires manual intervention│       │
                         │    └─────────────────────────────┘       │
                         │                                            │
                         ▼                                            │
                   ┌──────────┐                                      │
                   │ SUCCESS! │                                      │
                   │ Validated│                                      │
                   │ output   │                                      │
                   └──────────┘                                      │
```

---

## 2. Minimal Implementation (1 Hour)

For immediate testing, implement a simplified version with just one checkpoint:

### Step 1: Install Dependencies

```bash
pip install anthropic ollama-python asyncio aiohttp
```

### Step 2: Create Minimal Quorum Engine

Create `quorum_minimal.py`:

```python
import asyncio
import json
from typing import Dict, Any, List
from dataclasses import dataclass
from enum import Enum

class ValidationDecision(Enum):
    PASS = "PASS"
    RETRY = "RETRY"
    FAIL = "FAIL"

@dataclass
class QuorumResult:
    decision: ValidationDecision
    confidence: float
    deficiencies: List[str]
    scores: Dict[str, float]

class MinimalQuorum:
    """Minimal quorum validation for testing"""

    def __init__(self):
        self.models = {
            "gemini": {
                "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent",
                "weight": 1.0,
            },
            "codestral": {
                "endpoint": "http://192.168.86.200:11434/api/generate",
                "weight": 1.5,
            },
        }

    async def validate_intent(
        self,
        user_prompt: str,
        task_breakdown: Dict[str, Any],
    ) -> QuorumResult:
        """Validate task breakdown against user intent"""

        # Build validation prompt
        prompt = f"""
Given user request: "{user_prompt}"

Task breakdown generated:
{json.dumps(task_breakdown, indent=2)}

Answer these questions with JSON:
1. Does the task breakdown correctly understand the user's intent? (score 0-100)
2. Is the correct node type selected? (Effect/Compute/Reducer/Orchestrator)
3. Are all requirements captured? (list any missing)

Respond with JSON only:
{{
  "alignment_score": 0-100,
  "correct_node_type": true/false,
  "expected_node_type": "Effect|Compute|Reducer|Orchestrator",
  "missing_requirements": [...],
  "recommendation": "PASS|RETRY|FAIL"
}}
"""

        # Query models in parallel
        tasks = [
            self._query_model(model_name, prompt)
            for model_name in self.models.keys()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Calculate consensus
        return self._calculate_consensus(results)

    async def _query_model(self, model_name: str, prompt: str) -> Dict[str, Any]:
        """Query a model (simplified)"""

        # TODO: Implement actual API calls
        # For now, return mock response
        import random
        score = random.randint(75, 100)

        return {
            "model": model_name,
            "alignment_score": score,
            "correct_node_type": score > 85,
            "expected_node_type": "Effect",
            "missing_requirements": [] if score > 90 else ["Kafka integration"],
            "recommendation": "PASS" if score > 85 else "RETRY",
        }

    def _calculate_consensus(self, results: List[Dict]) -> QuorumResult:
        """Calculate weighted consensus"""

        # Filter valid results
        valid_results = [r for r in results if isinstance(r, dict)]

        if not valid_results:
            return QuorumResult(
                decision=ValidationDecision.FAIL,
                confidence=0.0,
                deficiencies=["No models responded"],
                scores={},
            )

        # Calculate weighted votes
        total_weight = 0
        pass_weight = 0
        retry_weight = 0
        all_deficiencies = []
        all_scores = []

        for result in valid_results:
            model_name = result["model"]
            weight = self.models[model_name]["weight"]
            total_weight += weight

            if result["recommendation"] == "PASS":
                pass_weight += weight
            elif result["recommendation"] == "RETRY":
                retry_weight += weight

            all_deficiencies.extend(result.get("missing_requirements", []))
            all_scores.append(result.get("alignment_score", 0))

        # Determine decision
        pass_pct = pass_weight / total_weight
        retry_pct = retry_weight / total_weight

        if pass_pct >= 0.6:
            decision = ValidationDecision.PASS
            confidence = pass_pct
        elif retry_pct >= 0.4:
            decision = ValidationDecision.RETRY
            confidence = retry_pct
        else:
            decision = ValidationDecision.FAIL
            confidence = 1.0 - (pass_pct + retry_pct)

        return QuorumResult(
            decision=decision,
            confidence=confidence,
            deficiencies=list(set(all_deficiencies)),
            scores={"alignment": sum(all_scores) / len(all_scores)},
        )

# Example usage
async def main():
    quorum = MinimalQuorum()

    result = await quorum.validate_intent(
        user_prompt="Create a PostgreSQL adapter Effect node with Kafka integration",
        task_breakdown={
            "node_type": "Compute",  # WRONG!
            "name": "UserAuthentication",  # WRONG!
            "features": ["database", "authentication"],
        },
    )

    print(f"Decision: {result.decision.value}")
    print(f"Confidence: {result.confidence:.0%}")
    print(f"Deficiencies: {result.deficiencies}")
    print(f"Scores: {result.scores}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Step 3: Test the System

```bash
python quorum_minimal.py
```

Expected output:
```
Decision: RETRY
Confidence: 65%
Deficiencies: ['Kafka integration', 'Wrong node type']
Scores: {'alignment': 78}
```

---

## 3. Integration with Existing Workflow

### Step 1: Wrap task_architect.py

Create `validated_task_architect.py`:

```python
from quorum_minimal import MinimalQuorum, ValidationDecision
import asyncio

class ValidatedTaskArchitect:
    """Task architect with quorum validation"""

    def __init__(self):
        self.quorum = MinimalQuorum()
        self.max_retries = 3

    async def breakdown_tasks_with_validation(
        self,
        user_prompt: str,
    ) -> Dict[str, Any]:
        """Break down tasks with validation and retry"""

        for attempt in range(self.max_retries):
            # Generate task breakdown
            task_breakdown = await self._generate_breakdown(user_prompt, attempt)

            # Validate with quorum
            result = await self.quorum.validate_intent(user_prompt, task_breakdown)

            if result.decision == ValidationDecision.PASS:
                return {
                    "breakdown": task_breakdown,
                    "validated": True,
                    "attempts": attempt + 1,
                }

            elif result.decision == ValidationDecision.RETRY:
                print(f"Attempt {attempt + 1} failed validation:")
                print(f"  Confidence: {result.confidence:.0%}")
                print(f"  Deficiencies: {result.deficiencies}")
                print("  Retrying with feedback...")

                # Add deficiencies to next attempt
                user_prompt = self._augment_prompt(user_prompt, result.deficiencies)

            else:  # FAIL
                raise Exception(f"Validation failed critically: {result.deficiencies}")

        raise Exception(f"Max retries ({self.max_retries}) exceeded")

    async def _generate_breakdown(
        self,
        user_prompt: str,
        attempt: int,
    ) -> Dict[str, Any]:
        """Generate task breakdown (call actual task_architect here)"""

        # TODO: Call actual task_architect.py
        # For now, return mock data
        return {
            "node_type": "Effect",
            "name": "PostgreSQLAdapter",
            "features": ["database", "kafka"],
        }

    def _augment_prompt(
        self,
        original_prompt: str,
        deficiencies: List[str],
    ) -> str:
        """Add deficiency feedback to prompt"""

        if not deficiencies:
            return original_prompt

        feedback = "\n\nIMPORTANT - Previous attempt had these issues:\n"
        for deficiency in deficiencies:
            feedback += f"  - {deficiency}\n"
        feedback += "\nPlease correct these issues in this attempt."

        return original_prompt + feedback

# Example usage
async def main():
    architect = ValidatedTaskArchitect()

    result = await architect.breakdown_tasks_with_validation(
        "Create a PostgreSQL adapter Effect node with Kafka integration"
    )

    print("Validated breakdown:")
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
```

### Step 2: Test Integration

```bash
python validated_task_architect.py
```

---

## 4. Next Steps

### Immediate (Today)
1. ✅ Review implementation plan
2. ⬜ Set up model endpoints (ensure all 5 models are accessible)
3. ⬜ Test minimal quorum with real API calls
4. ⬜ Implement actual model API integrations

### Short-term (This Week)
5. ⬜ Implement all 3 validation checkpoints
6. ⬜ Add retry orchestrator
7. ⬜ Create deficiency reporter
8. ⬜ Integration testing with real workflows

### Medium-term (Next Week)
9. ⬜ Add performance monitoring
10. ⬜ Implement caching
11. ⬜ Optimize model selection
12. ⬜ Create monitoring dashboard

### Long-term (Next Month)
13. ⬜ Production hardening
14. ⬜ Documentation
15. ⬜ Phased rollout
16. ⬜ Performance tuning

---

## 5. Configuration Files

### 5.1 Model Configuration

Create `quorum_config.json`:

```json
{
  "models": {
    "gemini_flash": {
      "name": "Gemini Flash",
      "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent",
      "api_key_env": "GEMINI_API_KEY",
      "weight": 1.0,
      "specialization": ["general", "baseline"],
      "timeout_ms": 3000,
      "enabled": true
    },
    "codestral": {
      "name": "Codestral",
      "endpoint": "http://192.168.86.200:11434/api/generate",
      "model": "codestral:22b-v0.1-q4_K_M",
      "weight": 1.5,
      "specialization": ["code", "syntax", "patterns"],
      "timeout_ms": 5000,
      "enabled": true
    },
    "deepseek_lite": {
      "name": "DeepSeek-Lite",
      "endpoint": "http://192.168.86.250:11434/api/generate",
      "model": "deepseek-coder:6.7b",
      "weight": 2.0,
      "specialization": ["codegen", "architecture", "optimization"],
      "timeout_ms": 4000,
      "enabled": true
    },
    "llama_31": {
      "name": "Llama 3.1",
      "endpoint": "http://192.168.86.240:11434/api/generate",
      "model": "llama3.1:8b",
      "weight": 1.2,
      "specialization": ["reasoning", "logic", "validation"],
      "timeout_ms": 5000,
      "enabled": true
    },
    "deepseek_full": {
      "name": "DeepSeek-Full",
      "endpoint": "http://192.168.86.230:11434/api/generate",
      "model": "deepseek-coder:33b",
      "weight": 1.8,
      "specialization": ["code", "contracts", "compliance"],
      "timeout_ms": 6000,
      "enabled": true
    }
  },
  "consensus": {
    "pass_threshold": 0.60,
    "retry_threshold": 0.40,
    "min_confidence": 0.70,
    "min_model_participation": 0.60
  },
  "retry": {
    "max_retries_per_checkpoint": 3,
    "max_total_retries": 5,
    "initial_backoff_ms": 1000,
    "backoff_multiplier": 1.5,
    "max_backoff_ms": 10000,
    "min_improvement_threshold": 0.10
  },
  "performance": {
    "cache_ttl_seconds": 3600,
    "max_cache_size": 1000,
    "enable_caching": true,
    "enable_monitoring": true
  }
}
```

### 5.2 Validation Criteria

Create `validation_criteria.json`:

```json
{
  "intent_validation": {
    "min_alignment_score": 85,
    "min_completeness_score": 90,
    "min_specificity_score": 80,
    "required_fields": ["node_type", "domain", "integration_requirements"]
  },
  "generation_validation": {
    "min_contract_compliance": 95,
    "min_naming_compliance": 100,
    "min_functionality_match": 90,
    "required_patterns": [
      "Node<Name><Type> class name",
      "execute_<type> method signature",
      "ModelContract usage"
    ]
  },
  "quality_validation": {
    "min_logic_correctness": 90,
    "min_error_handling": 85,
    "min_architectural_compliance": 95,
    "min_edge_case_coverage": 80
  }
}
```

---

## 6. Troubleshooting

### Issue: Models timing out

**Solution**: Increase timeout or disable slow models:
```python
# In quorum_config.json
{
  "deepseek_full": {
    "timeout_ms": 10000,  # Increase timeout
    "enabled": false  # Or disable if consistently slow
  }
}
```

### Issue: Too many retries

**Solution**: Lower retry threshold:
```python
# In quorum_config.json
{
  "retry": {
    "max_retries_per_checkpoint": 2,  # Reduce from 3
    "min_improvement_threshold": 0.05  # Lower threshold
  }
}
```

### Issue: False positives (good code rejected)

**Solution**: Tune consensus thresholds:
```python
# In quorum_config.json
{
  "consensus": {
    "pass_threshold": 0.50,  # Lower from 0.60
    "retry_threshold": 0.30  # Lower from 0.40
  }
}
```

### Issue: False negatives (bad code accepted)

**Solution**: Increase thresholds:
```python
# In quorum_config.json
{
  "consensus": {
    "pass_threshold": 0.70,  # Raise from 0.60
    "min_confidence": 0.80  # Raise from 0.70
  }
}
```

---

## 7. Performance Optimization Tips

1. **Enable caching**: Cache validation results for identical inputs
2. **Reduce model count**: Use 3 fastest models for simple validations
3. **Parallel execution**: Ensure all model queries run in parallel
4. **Timeout tuning**: Set aggressive timeouts for fast models
5. **Adaptive selection**: Use specialized models for each checkpoint

---

## 8. Monitoring Checklist

- [ ] Track validation accuracy (precision, recall, F1)
- [ ] Monitor performance overhead (target <30%)
- [ ] Track retry success rate (target >80%)
- [ ] Monitor model response times
- [ ] Track cache hit rate (target >40%)
- [ ] Monitor false positive/negative rates
- [ ] Track consensus confidence distribution
- [ ] Monitor deficiency categories

---

## 9. Success Criteria

✅ **Phase 1 Complete When**:
- [ ] Minimal quorum validates correctly
- [ ] All 5 models respond within timeout
- [ ] Consensus calculation works
- [ ] Retry logic executes properly
- [ ] Deficiency reporting is clear

✅ **Production Ready When**:
- [ ] Validation accuracy >95%
- [ ] Performance overhead <30%
- [ ] Retry success rate >80%
- [ ] False positive rate <5%
- [ ] All 3 checkpoints operational
- [ ] Monitoring dashboard live
- [ ] Documentation complete

---

## 10. Emergency Rollback

If validation causes critical issues:

1. **Disable validation**:
```python
# In workflow code
USE_QUORUM_VALIDATION = False  # Emergency disable
```

2. **Bypass specific checkpoint**:
```python
# Skip problematic checkpoint
if checkpoint != "generation":
    result = await quorum.validate_checkpoint(...)
```

3. **Reduce model count**:
```python
# Use only fastest models
enabled_models = ["gemini_flash", "codestral"]
```

4. **Shadow mode**:
```python
# Run validation but don't block on failures
result = await quorum.validate_checkpoint(...)
if result.decision != ValidationDecision.PASS:
    log_warning(result)  # Log but continue
```

---

**Ready to implement? Start with the minimal quorum in Section 2!**
