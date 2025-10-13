"""
Minimal Quorum Validation System

Validates agent outputs using consensus from multiple AI models.
Uses Gemini (direct API) and local Ollama models for voting.
"""

import asyncio
import json
import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import httpx

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    # Load .env from the same directory as this script
    env_path = Path(__file__).parent / ".env"
    load_dotenv(dotenv_path=env_path)
except ImportError:
    print("Warning: python-dotenv not installed, relying on system environment variables")


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
    model_responses: List[Dict[str, Any]]


class QuorumValidator:
    """Quorum validation for AI model consensus"""

    def __init__(self):
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")

        self.zai_api_key = os.getenv("ZAI_API_KEY")
        if not self.zai_api_key:
            raise ValueError("ZAI_API_KEY environment variable not set")

        # Cloud-only models (128K minimum context)
        self.models = {
            "gemini_flash": {
                "name": "Gemini 2.5 Flash",
                "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                "weight": 1.0,
                "type": "gemini",
                "context_window": 1_000_000,  # 1M tokens
            },
            "glm_45_air": {
                "name": "GLM-4.5-Air",
                "endpoint": "https://api.z.ai/api/anthropic/v1/messages",
                "model": "glm-4.5-air",
                "weight": 1.0,
                "type": "zai",
                "context_window": 128_000,  # 128K tokens
            },
            "glm_45": {
                "name": "GLM-4.5",
                "endpoint": "https://api.z.ai/api/anthropic/v1/messages",
                "model": "glm-4.5",
                "weight": 2.0,
                "type": "zai",
                "context_window": 128_000,  # 128K tokens
            },
            "glm_46": {
                "name": "GLM-4.6",
                "endpoint": "https://api.z.ai/api/anthropic/v1/messages",
                "model": "glm-4.6",
                "weight": 1.5,
                "type": "zai",
                "context_window": 128_000,  # 128K tokens
            },
        }

    async def validate_intent(
        self,
        user_prompt: str,
        task_breakdown: Dict[str, Any],
    ) -> QuorumResult:
        """Validate task breakdown against user intent"""

        # Check if task breakdown includes node_type (ONEX architecture)
        has_node_type = False
        if "tasks" in task_breakdown:
            for task in task_breakdown["tasks"]:
                if "input_data" in task and "node_type" in task["input_data"]:
                    has_node_type = True
                    break

        # Build validation prompt (conditional based on whether ONEX is used)
        if has_node_type:
            validation_questions = """Answer these questions with JSON:
1. Does the task breakdown correctly understand the user's intent? (score 0-100)
2. Is the correct node type selected? (Effect/Compute/Reducer/Orchestrator)
3. Are all requirements captured? (list any missing)

Respond with JSON only:
{
  "alignment_score": <0-100>,
  "correct_node_type": <true/false>,
  "expected_node_type": "<Effect|Compute|Reducer|Orchestrator>",
  "missing_requirements": [<list of strings>],
  "recommendation": "<PASS|RETRY|FAIL>"
}"""
        else:
            validation_questions = """Answer these questions with JSON:
1. Does the task breakdown correctly understand the user's intent? (score 0-100)
2. Are all requirements captured? (list any missing)
3. Is the implementation approach appropriate? (true/false)

Respond with JSON only:
{
  "alignment_score": <0-100>,
  "correct_node_type": true,
  "expected_node_type": "N/A",
  "missing_requirements": [<list of strings>],
  "recommendation": "<PASS|RETRY|FAIL>"
}"""

        prompt = f"""Given user request: "{user_prompt}"

Task breakdown generated:
{json.dumps(task_breakdown, indent=2)}

{validation_questions}

CRITICAL: Do NOT repeat the task breakdown or user request in your response. Only return the validation JSON."""

        # Query models in parallel
        tasks = [
            self._query_model(model_name, config, prompt)
            for model_name, config in self.models.items()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Calculate consensus
        return self._calculate_consensus(results)

    async def _query_model(
        self, model_name: str, config: Dict[str, Any], prompt: str
    ) -> Dict[str, Any]:
        """Query a model via API"""

        try:
            if config["type"] == "gemini":
                return await self._query_gemini(model_name, config, prompt)
            elif config["type"] == "zai":
                return await self._query_zai(model_name, config, prompt)
            else:
                raise ValueError(f"Unknown model type: {config['type']}")

        except Exception as e:
            print(f"Error querying {model_name}: {e}")
            return {
                "model": model_name,
                "error": str(e),
                "recommendation": "FAIL",
            }

    async def _query_gemini(
        self, model_name: str, config: Dict[str, Any], prompt: str
    ) -> Dict[str, Any]:
        """Query Gemini API directly"""

        url = f"{config['endpoint']}?key={self.gemini_api_key}"

        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 2048,
            }
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

            data = response.json()

            # Handle Gemini API response format safely
            try:
                text = data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as e:
                print(f"Gemini API response format error: {e}")
                print(f"Response data: {json.dumps(data, indent=2)}")
                return {
                    "model": model_name,
                    "alignment_score": 50,
                    "correct_node_type": False,
                    "expected_node_type": "Unknown",
                    "missing_requirements": [f"API response error: {str(e)}"],
                    "recommendation": "RETRY",
                }

            # Extract JSON from response
            return self._parse_model_response(model_name, text)

    async def _query_zai(
        self, model_name: str, config: Dict[str, Any], prompt: str
    ) -> Dict[str, Any]:
        """Query Z.ai API using Anthropic Messages API format"""

        headers = {
            "x-api-key": self.zai_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        payload = {
            "model": config["model"],
            "max_tokens": 2048,
            "temperature": 0.1,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(config["endpoint"], headers=headers, json=payload)
            response.raise_for_status()

            data = response.json()

            # Handle Anthropic Messages API response format safely
            try:
                text = data["content"][0]["text"]
            except (KeyError, IndexError) as e:
                print(f"Z.ai API response format error: {e}")
                print(f"Response data: {json.dumps(data, indent=2)}")
                return {
                    "model": model_name,
                    "alignment_score": 50,
                    "correct_node_type": False,
                    "expected_node_type": "Unknown",
                    "missing_requirements": [f"API response error: {str(e)}"],
                    "recommendation": "RETRY",
                }

            # Extract JSON from response
            return self._parse_model_response(model_name, text)

    def _parse_model_response(
        self, model_name: str, text: str
    ) -> Dict[str, Any]:
        """Parse JSON response from model"""

        try:
            # Try to find JSON in response
            start = text.find("{")
            end = text.rfind("}") + 1

            if start >= 0 and end > start:
                json_str = text[start:end]
                parsed = json.loads(json_str)
                parsed["model"] = model_name
                return parsed
            else:
                # No JSON found, create default response
                return {
                    "model": model_name,
                    "alignment_score": 50,
                    "correct_node_type": False,
                    "expected_node_type": "Unknown",
                    "missing_requirements": ["Failed to parse response"],
                    "recommendation": "RETRY",
                }

        except json.JSONDecodeError as e:
            print(f"JSON parse error for {model_name}: {e}")
            print(f"Response text: {text[:200]}")
            return {
                "model": model_name,
                "alignment_score": 50,
                "correct_node_type": False,
                "expected_node_type": "Unknown",
                "missing_requirements": ["Failed to parse JSON"],
                "recommendation": "RETRY",
            }

    def _calculate_consensus(
        self, results: List[Dict[str, Any]]
    ) -> QuorumResult:
        """Calculate weighted consensus"""

        # Filter valid results
        valid_results = [
            r for r in results
            if isinstance(r, dict) and "recommendation" in r
        ]

        if not valid_results:
            return QuorumResult(
                decision=ValidationDecision.FAIL,
                confidence=0.0,
                deficiencies=["No models responded successfully"],
                scores={},
                model_responses=[],
            )

        # Calculate weighted votes
        total_weight = 0
        pass_weight = 0
        retry_weight = 0
        fail_weight = 0
        all_deficiencies = []
        all_scores = []

        for result in valid_results:
            model_name = result["model"]
            weight = self.models[model_name]["weight"]
            total_weight += weight

            recommendation = result.get("recommendation", "FAIL")
            if recommendation == "PASS":
                pass_weight += weight
            elif recommendation == "RETRY":
                retry_weight += weight
            else:
                fail_weight += weight

            all_deficiencies.extend(result.get("missing_requirements", []))
            all_scores.append(result.get("alignment_score", 0))

        # Determine decision
        pass_pct = pass_weight / total_weight if total_weight > 0 else 0
        retry_pct = retry_weight / total_weight if total_weight > 0 else 0
        fail_pct = fail_weight / total_weight if total_weight > 0 else 0

        if pass_pct >= 0.6:
            decision = ValidationDecision.PASS
            confidence = pass_pct
        elif retry_pct >= 0.4 or (pass_pct + retry_pct >= 0.6):
            decision = ValidationDecision.RETRY
            confidence = retry_pct
        else:
            decision = ValidationDecision.FAIL
            confidence = fail_pct

        avg_score = sum(all_scores) / len(all_scores) if all_scores else 0

        return QuorumResult(
            decision=decision,
            confidence=confidence,
            deficiencies=list(set(all_deficiencies)),
            scores={
                "alignment": avg_score,
                "pass_pct": pass_pct,
                "retry_pct": retry_pct,
                "fail_pct": fail_pct,
            },
            model_responses=valid_results,
        )


# Example usage
async def main():
    """Test the quorum with PostgreSQL adapter failure case"""

    quorum = MinimalQuorum()

    # Test case: The actual failure we experienced
    result = await quorum.validate_intent(
        user_prompt="Build a postgres adapter effect node that takes kafka event bus events and turns them into postgres api calls",
        task_breakdown={
            "node_type": "Compute",  # WRONG! Should be Effect
            "name": "UserAuthentication",  # WRONG! Should be PostgreSQLAdapter
            "description": "Contract for user authentication operations",  # WRONG domain
            "input_model": {
                "username": {"type": "str"},
                "password": {"type": "str"},
            },
        },
    )

    print("\n" + "="*60)
    print("QUORUM VALIDATION RESULT")
    print("="*60)
    print(f"Decision: {result.decision.value}")
    print(f"Confidence: {result.confidence:.1%}")
    print(f"Deficiencies: {result.deficiencies}")
    print(f"\nScores:")
    for key, value in result.scores.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.1f}")
        else:
            print(f"  {key}: {value}")

    print(f"\nModel Responses:")
    for response in result.model_responses:
        model = response.get("model", "unknown")
        recommendation = response.get("recommendation", "unknown")
        score = response.get("alignment_score", 0)
        print(f"  {model}: {recommendation} (score: {score})")

    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
