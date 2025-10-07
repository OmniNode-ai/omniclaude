"""
Validated Task Architect

Wraps task_architect.py with quorum validation to ensure task breakdowns
correctly understand user intent before proceeding to code generation.
"""

import asyncio
import json
import subprocess
import sys
from typing import Dict, Any, List
from pathlib import Path
from quorum_minimal import MinimalQuorum, ValidationDecision

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    # Load .env from the same directory as this script
    env_path = Path(__file__).parent / ".env"
    load_dotenv(dotenv_path=env_path)
except ImportError:
    print("Warning: python-dotenv not installed, relying on system environment variables")


class ValidatedTaskArchitect:
    """Task architect with quorum validation and intelligent retry"""

    def __init__(self):
        self.quorum = MinimalQuorum()
        self.max_retries = 3

    async def breakdown_tasks_with_validation(
        self,
        user_prompt: str,
        global_context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """Break down tasks with validation and retry

        Args:
            user_prompt: Original user request
            global_context: Optional pre-gathered context

        Returns:
            Dict with validated breakdown and metadata
        """

        augmented_prompt = user_prompt
        attempt_history = []

        for attempt in range(self.max_retries):
            print(f"\n{'='*60}")
            print(f"ATTEMPT {attempt + 1}/{self.max_retries}")
            print(f"{'='*60}")

            # Generate task breakdown
            task_breakdown = await self._generate_breakdown(
                augmented_prompt, global_context
            )

            # Store attempt
            attempt_history.append({
                "attempt": attempt + 1,
                "prompt": augmented_prompt,
                "breakdown": task_breakdown,
            })

            # Validate with quorum
            print(f"\n🔍 Validating with quorum...")
            result = await self.quorum.validate_intent(user_prompt, task_breakdown)

            print(f"\n📊 Quorum Decision: {result.decision.value}")
            print(f"   Confidence: {result.confidence:.1%}")
            print(f"   Deficiencies: {len(result.deficiencies)}")

            # Show detailed model responses
            print(f"\n📋 Model Responses:")
            for response in result.model_responses:
                model = response.get("model", "unknown")
                recommendation = response.get("recommendation", "unknown")
                score = response.get("alignment_score", 0)
                correct_type = response.get("correct_node_type", None)
                expected_type = response.get("expected_node_type", "unknown")
                print(f"   {model}: {recommendation} (score: {score}, correct_type: {correct_type}, expected: {expected_type})")

            if result.decision == ValidationDecision.PASS:
                print(f"\n✅ Validation PASSED on attempt {attempt + 1}")
                return {
                    "breakdown": task_breakdown,
                    "validated": True,
                    "attempts": attempt + 1,
                    "quorum_result": {
                        "decision": result.decision.value,
                        "confidence": result.confidence,
                        "scores": result.scores,
                    },
                    "attempt_history": attempt_history,
                }

            elif result.decision == ValidationDecision.RETRY:
                print(f"\n⚠️  Validation requires RETRY:")
                print(f"   Confidence: {result.confidence:.1%}")
                print(f"   Issues found:")
                for deficiency in result.deficiencies:
                    print(f"     - {deficiency}")

                if attempt < self.max_retries - 1:
                    print(f"\n🔄 Retrying with feedback...")
                    # Augment prompt with deficiency feedback
                    augmented_prompt = self._augment_prompt(
                        user_prompt, result.deficiencies, attempt + 1
                    )
                else:
                    print(f"\n❌ Max retries reached, returning best attempt")
                    return {
                        "breakdown": task_breakdown,
                        "validated": False,
                        "attempts": attempt + 1,
                        "quorum_result": {
                            "decision": result.decision.value,
                            "confidence": result.confidence,
                            "deficiencies": result.deficiencies,
                            "scores": result.scores,
                        },
                        "attempt_history": attempt_history,
                        "error": f"Max retries ({self.max_retries}) exceeded",
                    }

            else:  # FAIL
                print(f"\n❌ Validation FAILED critically:")
                for deficiency in result.deficiencies:
                    print(f"     - {deficiency}")

                return {
                    "breakdown": task_breakdown,
                    "validated": False,
                    "attempts": attempt + 1,
                    "quorum_result": {
                        "decision": result.decision.value,
                        "confidence": result.confidence,
                        "deficiencies": result.deficiencies,
                        "scores": result.scores,
                    },
                    "attempt_history": attempt_history,
                    "error": f"Validation failed critically: {result.deficiencies}",
                }

        # Should never reach here
        return {
            "breakdown": None,
            "validated": False,
            "attempts": self.max_retries,
            "error": "Unexpected state: max retries exceeded",
        }

    async def _generate_breakdown(
        self,
        user_prompt: str,
        global_context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """Generate task breakdown by calling task_architect.py

        Args:
            user_prompt: User request (possibly augmented with feedback)
            global_context: Optional pre-gathered context

        Returns:
            Task breakdown from task_architect
        """

        # Prepare input for task_architect
        input_data = {"prompt": user_prompt}
        if global_context:
            input_data["global_context"] = global_context

        try:
            # Call task_architect.py as subprocess
            result = subprocess.run(
                ["python3", "task_architect.py"],
                input=json.dumps(input_data),
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                print(f"⚠️  task_architect.py failed: {result.stderr}")
                # Return fallback breakdown
                return self._generate_fallback_breakdown(user_prompt)

            # Parse output
            output = json.loads(result.stdout)
            return output

        except subprocess.TimeoutExpired:
            print(f"⚠️  task_architect.py timed out")
            return self._generate_fallback_breakdown(user_prompt)

        except json.JSONDecodeError as e:
            print(f"⚠️  Failed to parse task_architect output: {e}")
            return self._generate_fallback_breakdown(user_prompt)

        except Exception as e:
            print(f"⚠️  Error calling task_architect: {e}")
            return self._generate_fallback_breakdown(user_prompt)

    def _generate_fallback_breakdown(self, user_prompt: str) -> Dict[str, Any]:
        """Generate a minimal fallback breakdown when task_architect fails"""

        return {
            "tasks": [
                {
                    "task_id": "task1",
                    "agent": "agent-coder",
                    "description": f"Implement: {user_prompt}",
                    "context_requirements": ["rag:implementation-patterns"],
                }
            ],
            "fallback": True,
            "reason": "task_architect unavailable",
        }

    def _augment_prompt(
        self,
        original_prompt: str,
        deficiencies: List[str],
        attempt: int,
    ) -> str:
        """Add deficiency feedback to prompt for retry

        Args:
            original_prompt: Original user request
            deficiencies: List of issues from quorum validation
            attempt: Current attempt number

        Returns:
            Augmented prompt with feedback
        """

        if not deficiencies:
            return original_prompt

        feedback = f"\n\n{'='*60}\n"
        feedback += f"IMPORTANT - Attempt {attempt} had these issues:\n"
        feedback += f"{'='*60}\n"

        for i, deficiency in enumerate(deficiencies, 1):
            feedback += f"{i}. {deficiency}\n"

        feedback += f"\n{'='*60}\n"
        feedback += "Please correct ALL these issues in this attempt.\n"
        feedback += "Ensure the task breakdown addresses each deficiency listed above.\n"
        feedback += f"{'='*60}\n"

        return original_prompt + feedback


# CLI Interface
async def main():
    """CLI interface for validated task architect"""

    if len(sys.argv) < 2:
        print("Usage: python validated_task_architect.py '<user_prompt>'")
        print("\nOr pipe JSON input:")
        print('  echo \'{"prompt": "..."}\' | python validated_task_architect.py')
        sys.exit(1)

    # Check if there are command line arguments
    if len(sys.argv) > 1:
        # Read from command line
        user_prompt = sys.argv[1]
        global_context = None
    elif not sys.stdin.isatty():
        # Read from stdin
        input_data = json.loads(sys.stdin.read())
        user_prompt = input_data.get("prompt")
        global_context = input_data.get("global_context")
    else:
        print("Error: No input provided")
        sys.exit(1)

    architect = ValidatedTaskArchitect()

    result = await architect.breakdown_tasks_with_validation(
        user_prompt, global_context
    )

    # Output result as JSON
    print("\n" + "="*60)
    print("FINAL RESULT")
    print("="*60)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
