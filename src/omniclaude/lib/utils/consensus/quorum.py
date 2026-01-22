#!/usr/bin/env python3
"""
AI Quorum System for Pre-commit Hook Validation
Provides multi-model consensus scoring for correction validation.

Phase 1: Stub mode with fixed scores for testing infrastructure
Phase 3-4: Full AI scoring with actual model evaluation
"""

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]
    print("Warning: httpx not available, AI scoring will be disabled", file=sys.stderr)


class ModelProvider(Enum):
    """Supported AI model providers."""

    OLLAMA = "ollama"
    GEMINI = "gemini"
    OPENAI = "openai"


# Minimum percentage of configured models that must participate (0.0-1.0)
MIN_MODEL_PARTICIPATION = 0.60  # 60% of models must respond


@dataclass
class ModelConfig:
    """Configuration for an AI model in the quorum."""

    name: str
    provider: ModelProvider
    weight: float = 1.0
    endpoint: str | None = None
    api_key: str | None = None
    timeout: float = 10.0

    def __post_init__(self) -> None:
        """Validate and set defaults."""
        if self.endpoint is None:
            if self.provider == ModelProvider.OLLAMA:
                self.endpoint = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            elif self.provider == ModelProvider.GEMINI:
                self.endpoint = "https://generativelanguage.googleapis.com/v1beta"

        if self.api_key is None and self.provider == ModelProvider.GEMINI:
            self.api_key = os.getenv("GEMINI_API_KEY", "")


@dataclass
class QuorumScore:
    """Consensus score from AI quorum evaluation."""

    consensus_score: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    model_scores: dict[str, float] = field(default_factory=dict)
    model_reasoning: dict[str, str] = field(default_factory=dict)
    recommendation: str = ""
    requires_human_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "consensus_score": self.consensus_score,
            "confidence": self.confidence,
            "model_scores": self.model_scores,
            "model_reasoning": self.model_reasoning,
            "recommendation": self.recommendation,
            "requires_human_review": self.requires_human_review,
        }

    @property
    def should_apply(self) -> bool:
        """Check if correction should be auto-applied (high confidence)."""
        return self.consensus_score >= 0.80 and self.confidence >= 0.70

    @property
    def is_approved(self) -> bool:
        """Check if correction is approved by quorum."""
        return self.consensus_score >= 0.7 and self.confidence >= 0.6


class AIQuorum:
    """
    Multi-model AI quorum system for correction validation.

    Phase 1: Operates in stub mode with fixed scores
    Phase 3-4: Full AI model evaluation
    """

    DEFAULT_MODELS = [
        ModelConfig(
            name="codestral:22b-v0.1-q4_K_M",
            provider=ModelProvider.OLLAMA,
            weight=1.5,  # Higher weight for code-specialized model
        ),
        ModelConfig(name="gemini-2.5-flash", provider=ModelProvider.GEMINI, weight=1.0),
    ]

    def __init__(
        self,
        models: list[ModelConfig] | None = None,
        stub_mode: bool = True,  # Phase 1: Default to stub mode
        enable_ai_scoring: bool = False,  # Phase 1: Default disabled
        parallel_execution: bool = True,
        config_path: Path | None = None,
    ):
        """
        Initialize AI Quorum system.

        Args:
            models: List of model configurations (defaults to config.yaml or DEFAULT_MODELS)
            stub_mode: If True, use fixed scores for testing (Phase 1)
            enable_ai_scoring: If True, use actual AI models (Phase 3-4)
            parallel_execution: If True, score models in parallel
            config_path: Path to config.yaml (defaults to ~/.claude/hooks/config.yaml)
        """
        # Load from config.yaml if no models provided
        if models is None:
            models = self._load_models_from_config(config_path)

        self.models = models or self.DEFAULT_MODELS
        self.stub_mode = stub_mode
        self.enable_ai_scoring = enable_ai_scoring and not stub_mode
        self.parallel_execution = parallel_execution

        # Validate configuration - use getattr to avoid type narrowing issues
        if self.enable_ai_scoring and getattr(sys.modules.get("httpx"), "__name__", None) is None:
            print(
                "Warning: httpx not available, falling back to stub mode",
                file=sys.stderr,
            )
            self.stub_mode = True
            self.enable_ai_scoring = False

    def _load_models_from_config(self, config_path: Path | None = None) -> list[ModelConfig]:
        """
        Load model configurations from config.yaml.

        Args:
            config_path: Path to config file (defaults to ~/.claude/hooks/config.yaml)

        Returns:
            List of ModelConfig objects
        """
        if config_path is None:
            config_path = Path.home() / ".claude" / "hooks" / "config.yaml"

        if not config_path.exists():
            print(f"Config file not found: {config_path}, using defaults", file=sys.stderr)
            return self.DEFAULT_MODELS

        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)

            quorum_config = config.get("quorum", {})
            if not quorum_config.get("enabled", False):
                print("AI Quorum disabled in config", file=sys.stderr)
                return self.DEFAULT_MODELS

            models = []
            model_configs = quorum_config.get("models", {})

            for model_name, model_data in model_configs.items():
                if not model_data.get("enabled", False):
                    continue

                provider_str = model_data.get("type", "ollama")
                try:
                    provider = ModelProvider(provider_str)
                except ValueError:
                    print(
                        f"Unknown provider type: {provider_str}, skipping {model_name}",
                        file=sys.stderr,
                    )
                    continue

                # Build endpoint based on provider
                endpoint = None
                if provider == ModelProvider.OPENAI and "base_url" in model_data:
                    endpoint = model_data["base_url"]
                elif provider == ModelProvider.OLLAMA:
                    # Allow per-model Ollama endpoint override
                    if "base_url" in model_data:
                        endpoint = model_data["base_url"]
                    else:
                        ollama_config = quorum_config.get("ollama", {})
                        endpoint = ollama_config.get("base_url", "http://localhost:11434")

                model_config = ModelConfig(
                    name=model_data.get("name", model_name),
                    provider=provider,
                    weight=model_data.get("weight", 1.0),
                    endpoint=endpoint,
                    api_key=model_data.get("api_key"),
                    timeout=model_data.get("timeout", 10.0),
                )
                models.append(model_config)

            if models:
                print(
                    f"Loaded {len(models)} models from config: {[m.name for m in models]}",
                    file=sys.stderr,
                )
                return models
            else:
                print("No enabled models in config, using defaults", file=sys.stderr)
                return self.DEFAULT_MODELS

        except Exception as e:
            print(f"Error loading config from {config_path}: {e}", file=sys.stderr)
            return self.DEFAULT_MODELS

    async def score_correction(
        self,
        original_prompt: str,
        corrected_prompt: str,
        correction_type: str,
        correction_metadata: dict[str, Any] | None = None,
    ) -> QuorumScore:
        """
        Score a correction using AI quorum consensus.

        Args:
            original_prompt: Original user prompt
            corrected_prompt: Corrected prompt with framework references
            correction_type: Type of correction applied
            correction_metadata: Additional context about the correction

        Returns:
            QuorumScore with consensus evaluation
        """
        if self.stub_mode:
            return self._stub_score_correction(
                original_prompt, corrected_prompt, correction_type, correction_metadata
            )

        if not self.enable_ai_scoring:
            return self._default_approval_score()

        # Phase 3-4: Full AI scoring
        return await self._ai_score_correction(
            original_prompt, corrected_prompt, correction_type, correction_metadata
        )

    def _stub_score_correction(
        self,
        original_prompt: str,
        corrected_prompt: str,
        correction_type: str,
        correction_metadata: dict[str, Any] | None = None,
    ) -> QuorumScore:
        """
        Stub implementation for Phase 1 testing.
        Returns fixed high scores to enable infrastructure testing.

        Args:
            original_prompt: Original user prompt
            corrected_prompt: Corrected prompt
            correction_type: Type of correction
            correction_metadata: Additional context

        Returns:
            QuorumScore with fixed high scores
        """
        # Phase 1: Return safe default scores for testing
        model_scores = {model.name: 0.85 for model in self.models}

        model_reasoning = {
            model.name: f"[STUB] Auto-approved for Phase 1 testing - {correction_type}"
            for model in self.models
        }

        return QuorumScore(
            consensus_score=0.85,
            confidence=0.9,
            model_scores=model_scores,
            model_reasoning=model_reasoning,
            recommendation="AUTO_APPROVED_PHASE1_STUB",
            requires_human_review=False,
        )

    def _default_approval_score(self) -> QuorumScore:
        """
        Default approval score when AI scoring is disabled.

        Returns:
            QuorumScore with default approval
        """
        return QuorumScore(
            consensus_score=1.0,
            confidence=1.0,
            model_scores={"default": 1.0},
            model_reasoning={"default": "AI scoring disabled, auto-approved"},
            recommendation="AUTO_APPROVED_NO_AI",
            requires_human_review=False,
        )

    async def _ai_score_correction(
        self,
        original_prompt: str,
        corrected_prompt: str,
        correction_type: str,
        correction_metadata: dict[str, Any] | None = None,
    ) -> QuorumScore:
        """
        Full AI model scoring (Phase 3-4).

        Args:
            original_prompt: Original user prompt
            corrected_prompt: Corrected prompt
            correction_type: Type of correction
            correction_metadata: Additional context

        Returns:
            QuorumScore with AI consensus
        """
        metadata = correction_metadata or {}

        # Generate scoring prompt for models
        scoring_prompt = self._generate_scoring_prompt(
            original_prompt, corrected_prompt, correction_type, metadata
        )

        # Score with all models in parallel or sequential
        if self.parallel_execution:
            scores = await asyncio.gather(
                *[self._score_with_model(model, scoring_prompt) for model in self.models],
                return_exceptions=True,
            )
        else:
            scores = []
            for model in self.models:
                score = await self._score_with_model(model, scoring_prompt)
                scores.append(score)

        # Calculate weighted consensus - filter out exceptions
        valid_scores: list[tuple[ModelConfig, dict[str, Any]]] = [
            item for item in scores if not isinstance(item, BaseException)
        ]
        return self._calculate_consensus(valid_scores)

    def _generate_scoring_prompt(
        self,
        original_prompt: str,
        corrected_prompt: str,
        correction_type: str,
        metadata: dict[str, Any],
    ) -> str:
        """
        Generate prompt for AI model scoring.

        Args:
            original_prompt: Original prompt
            corrected_prompt: Corrected prompt
            correction_type: Type of correction
            metadata: Additional context

        Returns:
            Formatted scoring prompt
        """
        return f"""# Pre-commit Hook Correction Evaluation

## Task
Evaluate the quality and appropriateness of a pre-commit hook correction applied to a user prompt.

## Correction Type
{correction_type}

## Original Prompt
```
{original_prompt}
```

## Corrected Prompt
```
{corrected_prompt}
```

## Correction Metadata
{json.dumps(metadata, indent=2)}

## Evaluation Criteria

Rate the correction on a scale of 0.0 to 1.0 based on:

1. **Correctness** (0.0-1.0): Does the correction properly address the identified issue?
2. **Necessity** (0.0-1.0): Was this correction necessary and valuable?
3. **Preservation** (0.0-1.0): Does the correction preserve user intent?
4. **Quality** (0.0-1.0): Is the correction well-formatted and clear?

## Response Format

Respond with ONLY a JSON object:

```json
{{
  "score": 0.85,
  "correctness": 0.9,
  "necessity": 0.8,
  "preservation": 0.9,
  "quality": 0.8,
  "reasoning": "Brief explanation of the score",
  "concerns": ["Any concerns or issues identified"],
  "recommendation": "APPROVE | REJECT | REVIEW"
}}
```

Provide your evaluation:"""

    async def _score_with_model(
        self, model: ModelConfig, scoring_prompt: str
    ) -> tuple[ModelConfig, dict[str, Any]]:
        """
        Score correction with a single AI model.

        Args:
            model: Model configuration
            scoring_prompt: Prompt for scoring

        Returns:
            Tuple of (model, score_dict)
        """
        if model.provider == ModelProvider.OLLAMA:
            return await self._score_with_ollama(model, scoring_prompt)
        elif model.provider == ModelProvider.GEMINI:
            return await self._score_with_gemini(model, scoring_prompt)
        elif model.provider == ModelProvider.OPENAI:
            return await self._score_with_openai(model, scoring_prompt)
        else:
            raise ValueError(f"Unsupported model provider: {model.provider}")

    async def _score_with_ollama(
        self, model: ModelConfig, scoring_prompt: str
    ) -> tuple[ModelConfig, dict[str, Any]]:
        """
        Score using Ollama model.

        Args:
            model: Ollama model configuration
            scoring_prompt: Prompt for scoring

        Returns:
            Tuple of (model, score_dict)
        """
        url = f"{model.endpoint}/api/generate"

        payload = {
            "model": model.name,
            "prompt": scoring_prompt,
            "stream": False,
            "format": "json",
        }

        try:
            async with httpx.AsyncClient(timeout=model.timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()

                result = response.json()
                response_text = result.get("response", "{}")

                # Parse JSON response
                try:
                    score_data = json.loads(response_text)
                except json.JSONDecodeError:
                    score_data = {
                        "score": 0.5,
                        "reasoning": f"Failed to parse model response: {response_text[:100]}",
                        "recommendation": "REVIEW",
                    }

                return (model, score_data)

        except Exception as e:
            print(f"Error scoring with Ollama {model.name}: {e}", file=sys.stderr)
            return (
                model,
                {
                    "score": 0.5,
                    "reasoning": f"Error: {str(e)}",
                    "recommendation": "REVIEW",
                },
            )

    async def _score_with_gemini(
        self, model: ModelConfig, scoring_prompt: str
    ) -> tuple[ModelConfig, dict[str, Any]]:
        """
        Score using Gemini model.

        Args:
            model: Gemini model configuration
            scoring_prompt: Prompt for scoring

        Returns:
            Tuple of (model, score_dict)
        """
        url = f"{model.endpoint}/models/{model.name}:generateContent"

        headers = {"Content-Type": "application/json"}

        if model.api_key:
            headers["Authorization"] = f"Bearer {model.api_key}"

        payload = {
            "contents": [{"parts": [{"text": scoring_prompt}]}],
            "generationConfig": {"temperature": 0.1, "topP": 0.8, "topK": 40},
        }

        try:
            async with httpx.AsyncClient(timeout=model.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()

                result = response.json()
                response_text = (
                    result.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "{}")
                )

                # Parse JSON response
                try:
                    score_data = json.loads(response_text)
                except json.JSONDecodeError:
                    score_data = {
                        "score": 0.5,
                        "reasoning": f"Failed to parse model response: {response_text[:100]}",
                        "recommendation": "REVIEW",
                    }

                return (model, score_data)

        except Exception as e:
            print(f"Error scoring with Gemini {model.name}: {e}", file=sys.stderr)
            return (
                model,
                {
                    "score": 0.5,
                    "reasoning": f"Error: {str(e)}",
                    "recommendation": "REVIEW",
                },
            )

    async def _score_with_openai(
        self, model: ModelConfig, scoring_prompt: str
    ) -> tuple[ModelConfig, dict[str, Any]]:
        """
        Score using OpenAI-compatible API (including vLLM).

        Args:
            model: OpenAI model configuration
            scoring_prompt: Prompt for scoring

        Returns:
            Tuple of (model, score_dict)
        """
        # Use base_url if provided, otherwise default OpenAI endpoint
        base_url = model.endpoint or "https://api.openai.com/v1"
        url = f"{base_url}/chat/completions"

        payload = {
            "model": model.name,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert code reviewer evaluating naming convention corrections. Respond in JSON format.",
                },
                {"role": "user", "content": scoring_prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 500,
        }

        headers = {}
        if model.api_key:
            headers["Authorization"] = f"Bearer {model.api_key}"

        try:
            async with httpx.AsyncClient(timeout=model.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()

                result = response.json()
                response_text = (
                    result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                )

                # Parse JSON response - handle markdown code blocks
                try:
                    # Strip markdown code blocks if present
                    cleaned_text = response_text.strip()
                    if cleaned_text.startswith("```"):
                        # Extract JSON from markdown code block
                        lines = cleaned_text.split("\n")
                        # Remove first line (```json) and last line (```)
                        json_lines = [line for line in lines[1:-1] if line.strip()]
                        cleaned_text = "\n".join(json_lines)

                    score_data = json.loads(cleaned_text)
                except json.JSONDecodeError:
                    # Try to extract score from text if JSON parsing fails
                    score_data = {
                        "score": 0.5,
                        "reasoning": f"Failed to parse model response: {response_text[:200]}",
                        "recommendation": "REVIEW",
                    }

                return (model, score_data)

        except Exception as e:
            print(f"Error scoring with OpenAI {model.name}: {e}", file=sys.stderr)
            return (
                model,
                {
                    "score": 0.5,
                    "reasoning": f"Error: {str(e)}",
                    "recommendation": "REVIEW",
                },
            )

    def _calculate_consensus(self, scores: list[tuple[ModelConfig, dict[str, Any]]]) -> QuorumScore:
        """
        Calculate weighted consensus from model scores.

        Args:
            scores: List of (model, score_dict) tuples

        Returns:
            QuorumScore with consensus evaluation
        """
        valid_scores = []
        model_scores = {}
        model_reasoning = {}
        recommendations = []

        total_weight = 0.0
        weighted_score_sum = 0.0

        for item in scores:
            model, score_data = item

            score = score_data.get("score", 0.5)
            reasoning = score_data.get("reasoning", "No reasoning provided")
            recommendation = score_data.get("recommendation", "REVIEW")

            valid_scores.append(score)
            model_scores[model.name] = score
            model_reasoning[model.name] = reasoning
            recommendations.append(recommendation)

            weighted_score_sum += score * model.weight
            total_weight += model.weight

        # Enforce MIN_MODEL_PARTICIPATION threshold
        total_models = len(self.models)
        participating_models = len(valid_scores)
        participation_rate = participating_models / total_models if total_models > 0 else 0.0

        if participation_rate < MIN_MODEL_PARTICIPATION:
            return QuorumScore(
                consensus_score=0.0,
                confidence=0.0,
                model_scores=model_scores,
                model_reasoning={
                    **model_reasoning,
                    "quorum_error": f"Insufficient model participation: {participating_models}/{total_models} "
                    f"({participation_rate:.0%}) responded, minimum {MIN_MODEL_PARTICIPATION:.0%} required",
                },
                recommendation="FAIL_PARTICIPATION",
                requires_human_review=True,
            )

        # Calculate consensus score
        consensus_score = weighted_score_sum / total_weight if total_weight > 0 else 0.5

        # Calculate confidence based on score variance
        if len(valid_scores) > 1:
            score_variance = sum((s - consensus_score) ** 2 for s in valid_scores) / len(
                valid_scores
            )
            confidence = max(0.0, 1.0 - score_variance)
        else:
            confidence = 0.5

        # Determine final recommendation
        approve_count = sum(1 for r in recommendations if r == "APPROVE")
        reject_count = sum(1 for r in recommendations if r == "REJECT")

        if reject_count > len(recommendations) / 2:
            final_recommendation = "REJECT"
            requires_review = True
        elif approve_count > len(recommendations) / 2:
            final_recommendation = "APPROVE"
            requires_review = False
        else:
            final_recommendation = "REVIEW"
            requires_review = True

        return QuorumScore(
            consensus_score=consensus_score,
            confidence=confidence,
            model_scores=model_scores,
            model_reasoning=model_reasoning,
            recommendation=final_recommendation,
            requires_human_review=requires_review,
        )


# CLI interface for testing
async def main() -> None:
    """Test CLI interface for AI Quorum system."""

    if len(sys.argv) < 3:
        print(
            "Usage: quorum.py <original_prompt> <corrected_prompt> [correction_type]",
            file=sys.stderr,
        )
        print("\nExample:", file=sys.stderr)
        print(
            '  quorum.py "fix the bug" "fix the bug @MANDATORY_FUNCTIONS.md" "framework_reference"',
            file=sys.stderr,
        )
        sys.exit(1)

    original_prompt = sys.argv[1]
    corrected_prompt = sys.argv[2]
    correction_type = sys.argv[3] if len(sys.argv) > 3 else "unknown"

    # Phase 1: Use stub mode
    quorum = AIQuorum(stub_mode=True, enable_ai_scoring=False)

    print("AI Quorum System (Phase 1 - Stub Mode)")
    print(f"Original: {original_prompt}")
    print(f"Corrected: {corrected_prompt}")
    print(f"Correction Type: {correction_type}")
    print()

    score = await quorum.score_correction(
        original_prompt, corrected_prompt, correction_type, {"test_mode": True}
    )

    print(json.dumps(score.to_dict(), indent=2))
    print()
    print(f"Approved: {score.is_approved}")
    print(f"Recommendation: {score.recommendation}")


if __name__ == "__main__":
    asyncio.run(main())
