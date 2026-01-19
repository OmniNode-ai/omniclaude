"""
Validated Task Architect

Wraps task_architect.py with quorum validation to ensure task breakdowns
correctly understand user intent before proceeding to code generation.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .quorum_validator import QuorumValidator, ValidationDecision

# Use project's type-safe configuration system
# Import is deferred to avoid side effects during module import
_settings = None
_config_import_error: str | None = None

try:
    from config import settings as _imported_settings

    _settings = _imported_settings
except ImportError as e:
    _config_import_error = str(e)


def _validate_configuration() -> tuple[bool, list[str]]:
    """Validate configuration without side effects.

    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors: list[str] = []

    # Check if config module was imported successfully
    if _config_import_error is not None:
        errors.append(f"Could not import config module: {_config_import_error}")
        errors.append(
            "Make sure you're running from the project root using module syntax:"
        )
        errors.append("  cd /path/to/omniclaude")
        errors.append(
            "  python -m agents.parallel_execution.validated_task_architect '<prompt>'"
        )
        return False, errors

    if _settings is None:
        errors.append("Configuration settings not available")
        return False, errors

    # Check required API keys for QuorumValidator
    if not _settings.gemini_api_key:
        errors.append("GEMINI_API_KEY is not set")
    if not _settings.zai_api_key:
        errors.append("ZAI_API_KEY is not set")

    # Check service dependencies (optional but recommended)
    service_errors = _settings.validate_required_services()
    if service_errors:
        errors.extend([f"Service validation: {err}" for err in service_errors])

    return len(errors) == 0, errors


def _print_config_errors(errors: list[str]) -> None:
    """Print configuration errors in a formatted way."""
    print("=" * 60, file=sys.stderr)
    print("CONFIGURATION ERRORS", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)
    print("\n" + "=" * 60, file=sys.stderr)
    print(
        "Fix these issues before running validated_task_architect.py:", file=sys.stderr
    )
    print("  1. Copy .env.example to .env if not exists", file=sys.stderr)
    print("  2. Set required API keys in .env", file=sys.stderr)
    print("  3. Verify service endpoints are reachable", file=sys.stderr)
    print("  4. Run: source .env", file=sys.stderr)
    print("=" * 60, file=sys.stderr)


class ValidatedTaskArchitect:
    """Task architect with quorum validation and intelligent retry"""

    def __init__(self):
        self.quorum = QuorumValidator()
        self.max_retries = 3

    async def breakdown_tasks_with_validation(
        self,
        user_prompt: str,
        global_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
            attempt_history.append(
                {
                    "attempt": attempt + 1,
                    "prompt": augmented_prompt,
                    "breakdown": task_breakdown,
                }
            )

            # Validate with quorum
            print("\n🔍 Validating with quorum...")
            result = await self.quorum.validate_intent(user_prompt, task_breakdown)

            print(f"\n📊 Quorum Decision: {result.decision.value}")
            print(f"   Confidence: {result.confidence:.1%}")
            print(f"   Deficiencies: {len(result.deficiencies)}")

            # Show detailed model responses
            print("\n📋 Model Responses:")
            for response in result.model_responses:
                model = response.get("model", "unknown")
                recommendation = response.get("recommendation", "unknown")
                score = response.get("alignment_score", 0)
                correct_type = response.get("correct_node_type", None)
                expected_type = response.get("expected_node_type", "unknown")
                print(
                    f"   {model}: {recommendation} (score: {score}, correct_type: {correct_type}, expected: {expected_type})"
                )

            if result.decision == ValidationDecision.PASS:
                print(f"\n✅ Validation PASSED on attempt {attempt + 1}")

                # Add final validation task using agent-workflow-coordinator
                enhanced_breakdown = self._add_final_validation_task(
                    task_breakdown, user_prompt, global_context
                )

                return {
                    "breakdown": enhanced_breakdown,
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
                print("\n⚠️  Validation requires RETRY:")
                print(f"   Confidence: {result.confidence:.1%}")
                print("   Issues found:")
                for deficiency in result.deficiencies:
                    print(f"     - {deficiency}")

                if attempt < self.max_retries - 1:
                    print("\n🔄 Retrying with feedback...")
                    # Augment prompt with deficiency feedback
                    augmented_prompt = self._augment_prompt(
                        user_prompt, result.deficiencies, attempt + 1
                    )
                else:
                    print("\n❌ Max retries reached, returning best attempt")
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
                print("\n❌ Validation FAILED critically:")
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
        global_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate task breakdown by calling task_architect.py

        Args:
            user_prompt: User request (possibly augmented with feedback)
            global_context: Optional pre-gathered context

        Returns:
            Task breakdown from task_architect
        """

        # Prepare input for task_architect
        input_data: dict[str, Any] = {"prompt": user_prompt}
        if global_context:
            input_data["global_context"] = global_context

        try:
            # Get absolute path to task_architect.py (same directory as this file)
            task_architect_path = Path(__file__).parent / "task_architect.py"

            # Validate that task_architect.py exists
            if not task_architect_path.exists():
                raise FileNotFoundError(
                    f"task_architect.py not found at {task_architect_path}"
                )

            # Find Python interpreter (prefer python3, fallback to python)
            python_exe = shutil.which("python3") or shutil.which("python")
            if not python_exe:
                raise RuntimeError(
                    "Python interpreter not found. Please ensure python3 or python is in PATH"
                )

            # Prepare environment variables for subprocess
            # Inherit current environment and ensure critical vars are set
            env = os.environ.copy()

            # Add PYTHONPATH if not set (needed for imports)
            project_root = Path(__file__).parent.parent.parent
            if "PYTHONPATH" not in env:
                env["PYTHONPATH"] = str(project_root)
            else:
                # Prepend project root to existing PYTHONPATH
                env["PYTHONPATH"] = f"{project_root}:{env['PYTHONPATH']}"

            # Ensure critical API keys are available in subprocess
            required_vars = ["GEMINI_API_KEY", "ZAI_API_KEY"]
            missing_vars = [var for var in required_vars if not env.get(var)]
            if missing_vars:
                raise OSError(
                    f"Required environment variables not set: {', '.join(missing_vars)}"
                )

            # Call task_architect.py as subprocess
            result = subprocess.run(
                [python_exe, str(task_architect_path)],
                input=json.dumps(input_data),
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(project_root),  # Run from project root
                env=env,  # Pass environment with proper setup
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                print(f"⚠️  task_architect.py failed with exit code {result.returncode}")
                print(f"    Error: {error_msg}")
                if result.stdout:
                    print(f"    Stdout: {result.stdout[:500]}")  # First 500 chars
                # Return fallback breakdown
                return self._generate_fallback_breakdown(user_prompt)

            # Parse output
            try:
                output: dict[str, Any] = json.loads(result.stdout)
                return output
            except json.JSONDecodeError as e:
                print(f"⚠️  Failed to parse task_architect output: {e}")
                print(f"    Raw output (first 500 chars): {result.stdout[:500]}")
                return self._generate_fallback_breakdown(user_prompt)

        except subprocess.TimeoutExpired:
            print("⚠️  task_architect.py timed out after 30 seconds")
            return self._generate_fallback_breakdown(user_prompt)

        except FileNotFoundError as e:
            print(f"⚠️  File not found: {e}")
            return self._generate_fallback_breakdown(user_prompt)

        except OSError as e:
            print(f"⚠️  Environment error: {e}")
            return self._generate_fallback_breakdown(user_prompt)

        except Exception as e:
            print(
                f"⚠️  Unexpected error calling task_architect: {type(e).__name__}: {e}"
            )
            return self._generate_fallback_breakdown(user_prompt)

    def _generate_fallback_breakdown(self, user_prompt: str) -> dict[str, Any]:
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

    def _add_final_validation_task(
        self,
        task_breakdown: dict[str, Any],
        user_prompt: str,
        global_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add final validation task using agent-workflow-coordinator

        Args:
            task_breakdown: Original task breakdown from task_architect
            user_prompt: Original user request
            global_context: Optional pre-gathered context

        Returns:
            Enhanced task breakdown with validation task appended
        """
        tasks = task_breakdown.get("tasks", [])

        # Collect all task IDs for dependencies
        all_task_ids = [task.get("task_id") for task in tasks]

        # Create validation task that depends on all previous tasks
        validation_task = {
            "task_id": "validation-final",
            "description": f"Validate output for: {user_prompt}",
            "agent": "agent-workflow-coordinator",  # Use full agent name for subagent routing
            "input_data": {
                "validation_type": "output_quality_check",
                "original_request": user_prompt,
                "context_summary": {
                    "has_context": global_context is not None,
                    "context_keys": (
                        list(global_context.keys()) if global_context else []
                    ),
                },
                "validation_criteria": [
                    "Does output meet original requirements?",
                    "Is code quality production-ready?",
                    "Are all requested features implemented?",
                    "Does implementation follow best practices?",
                    "Are there any missing error handlers?",
                    "Is documentation complete?",
                ],
            },
            "context_requirements": [
                "rag:validation-patterns",
                "previous-task-outputs",  # Special marker for outputs from dependencies
            ],
            "dependencies": all_task_ids,  # Depends on all previous tasks
        }

        # Append validation task
        enhanced_tasks = tasks + [validation_task]

        # Return enhanced breakdown
        return {**task_breakdown, "tasks": enhanced_tasks, "has_validation_task": True}

    def _augment_prompt(
        self,
        original_prompt: str,
        deficiencies: list[str],
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
        feedback += (
            "Ensure the task breakdown addresses each deficiency listed above.\n"
        )
        feedback += f"{'='*60}\n"

        return original_prompt + feedback


# CLI Interface
async def main() -> int:
    """CLI interface for validated task architect

    Usage:
        # Command line argument (from project root)
        python -m agents.parallel_execution.validated_task_architect 'Create a REST API'

        # Piped JSON input
        echo '{"prompt": "Create a REST API", "global_context": {...}}' | python -m agents.parallel_execution.validated_task_architect

        # From file
        cat request.json | python -m agents.parallel_execution.validated_task_architect

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    # Validate configuration first (moved from module-level)
    is_valid, config_errors = _validate_configuration()
    if not is_valid:
        _print_config_errors(config_errors)
        return 1

    user_prompt = None
    global_context = None

    # Try to read from stdin first (if available)
    if not sys.stdin.isatty():
        try:
            stdin_content = sys.stdin.read().strip()
            if stdin_content:
                # Parse JSON input
                input_data = json.loads(stdin_content)
                user_prompt = input_data.get("prompt")
                global_context = input_data.get("global_context")

                if not user_prompt:
                    print(
                        "ERROR: JSON input must contain 'prompt' field", file=sys.stderr
                    )
                    print(
                        'Expected format: {"prompt": "...", "global_context": {...}}',
                        file=sys.stderr,
                    )
                    return 1
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON input: {e}", file=sys.stderr)
            print(
                'Expected format: {"prompt": "...", "global_context": {...}}',
                file=sys.stderr,
            )
            return 1
        except Exception as e:
            print(f"ERROR: Failed to read stdin: {e}", file=sys.stderr)
            return 1

    # If no stdin, check command line arguments
    if user_prompt is None:
        if len(sys.argv) < 2:
            print("ERROR: No input provided", file=sys.stderr)
            print(file=sys.stderr)
            print("Usage (from project root):", file=sys.stderr)
            print(
                "  python -m agents.parallel_execution.validated_task_architect '<user_prompt>'",
                file=sys.stderr,
            )
            print(file=sys.stderr)
            print("Or pipe JSON input:", file=sys.stderr)
            print(
                '  echo \'{"prompt": "..."}\' | python -m agents.parallel_execution.validated_task_architect',
                file=sys.stderr,
            )
            print(file=sys.stderr)
            print("Examples:", file=sys.stderr)
            print(
                '  python -m agents.parallel_execution.validated_task_architect "Create a REST API"',
                file=sys.stderr,
            )
            print(
                '  echo \'{"prompt": "Create a REST API"}\' | python -m agents.parallel_execution.validated_task_architect',
                file=sys.stderr,
            )
            return 1

        # Read from command line argument
        user_prompt = " ".join(sys.argv[1:])  # Join all args in case of spaces

        # Validate prompt is not empty
        if not user_prompt.strip():
            print("ERROR: User prompt cannot be empty", file=sys.stderr)
            return 1

    # Show configuration status (use _settings which is validated above)
    print("Configuration check:")
    print(
        f"  - GEMINI_API_KEY: {'set' if _settings and _settings.gemini_api_key else 'NOT SET'}"
    )
    print(
        f"  - ZAI_API_KEY: {'set' if _settings and _settings.zai_api_key else 'NOT SET'}"
    )
    print()

    # Create architect and run validation
    architect = ValidatedTaskArchitect()

    try:
        result = await architect.breakdown_tasks_with_validation(
            user_prompt, global_context
        )

        # Output result as JSON
        print("\n" + "=" * 60)
        print("FINAL RESULT")
        print("=" * 60)
        print(json.dumps(result, indent=2))

        # Return appropriate exit code
        if result.get("validated"):
            return 0  # Success
        else:
            return 1  # Validation failed

    except KeyboardInterrupt:
        print("\n\nInterrupted by user", file=sys.stderr)
        return 130  # Standard exit code for SIGINT
    except Exception as e:
        print(f"\n\nFATAL ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
