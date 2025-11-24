#!/usr/bin/env python3
"""
Error Handling and Success Logging Examples

Patterns for logging errors and successes with rich context.
"""

import asyncio
import sys
import traceback
from pathlib import Path
from uuid import uuid4


sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "agents" / "lib"))

from action_logger import ActionLogger


async def error_and_success_examples():
    """Demonstrate error and success logging patterns."""

    logger = ActionLogger(agent_name="agent-error-handler", correlation_id=str(uuid4()))

    # Example 1: Simple Error Logging
    print("Example 1: Simple Error Logging")
    try:
        # Simulate error
        raise FileNotFoundError("/path/to/missing/file.py")
    except FileNotFoundError as e:
        await logger.log_error(
            error_type=type(e).__name__,
            error_message=str(e),
            error_context={"file": __file__, "operation": "read_config"},
        )
    print("✓ Simple error logged\n")

    # Example 2: Error with Full Stack Trace
    print("Example 2: Error with Stack Trace")
    try:
        # Simulate error
        raise ValueError("Invalid configuration value")
    except ValueError as e:
        await logger.log_error(
            error_type=type(e).__name__,
            error_message=str(e),
            error_context={
                "file": __file__,
                "stack_trace": traceback.format_exc(),
                "config_key": "api_timeout",
                "invalid_value": "not_a_number",
                "expected_type": "int",
            },
        )
    print("✓ Error with stack trace logged\n")

    # Example 3: Retry Exhaustion Error
    print("Example 3: Retry Exhaustion Error")
    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        try:
            # Simulate failing operation
            if attempt < max_retries:
                raise ConnectionError("API connection failed")
        except ConnectionError as e:
            last_error = e
            if attempt == max_retries - 1:
                # Log final failure
                await logger.log_error(
                    error_type="MaxRetriesExceeded",
                    error_message=f"Failed after {max_retries} attempts: {e}",
                    error_context={
                        "max_retries": max_retries,
                        "attempts": attempt + 1,
                        "last_error": str(last_error),
                        "operation": "fetch_api_data",
                    },
                )
                print(f"✓ Retry exhaustion logged after {max_retries} attempts\n")

    # Example 4: Task Completion Success
    print("Example 4: Task Completion Success")
    await logger.log_success(
        success_name="task_completed",
        success_details={
            "task_type": "code_analysis",
            "files_analyzed": 15,
            "patterns_found": 42,
            "quality_score": 0.95,
            "onex_compliant": True,
        },
        duration_ms=1234,
    )
    print("✓ Task completion logged\n")

    # Example 5: Milestone Success
    print("Example 5: Milestone Success")
    await logger.log_success(
        success_name="milestone_reached",
        success_details={
            "milestone": "all_tests_passed",
            "test_count": 156,
            "coverage_percent": 92.5,
            "failures": 0,
            "warnings": 3,
        },
        duration_ms=5678,
    )
    print("✓ Milestone success logged\n")

    # Example 6: Recovery Success After Error
    print("Example 6: Recovery Success")
    # Simulate error and recovery
    try:
        raise ImportError("Module 'optional_module' not found")
    except ImportError as e:
        # Log error
        await logger.log_error(
            error_type=type(e).__name__,
            error_message=str(e),
            error_context={"module": "optional_module"},
        )

        # Simulate recovery
        await asyncio.sleep(0.01)

        # Log successful recovery
        await logger.log_success(
            success_name="recovered_from_error",
            success_details={
                "original_error": type(e).__name__,
                "recovery_strategy": "use_fallback_implementation",
                "fallback_used": "builtin_module",
                "functionality_preserved": True,
            },
            duration_ms=15,
        )
    print("✓ Recovery success logged\n")

    # Example 7: Validation Success
    print("Example 7: Validation Success")
    await logger.log_success(
        success_name="validation_passed",
        success_details={
            "validation_type": "onex_compliance",
            "node_type": "effect",
            "checks_performed": 23,
            "checks_passed": 23,
            "compliance_score": 1.0,
            "issues_found": [],
        },
        duration_ms=150,
    )
    print("✓ Validation success logged\n")

    # Example 8: Batch Processing Success
    print("Example 8: Batch Processing Success")
    await logger.log_success(
        success_name="batch_processing_completed",
        success_details={
            "total_items": 100,
            "processed_successfully": 97,
            "failed": 3,
            "skipped": 0,
            "success_rate": 0.97,
            "avg_processing_time_ms": 12.5,
            "total_duration_ms": 1234,
        },
        duration_ms=1234,
    )
    print("✓ Batch processing success logged\n")

    print("All error and success examples completed!")


async def error_recovery_pattern():
    """Demonstrate comprehensive error recovery pattern with logging."""

    logger = ActionLogger(agent_name="agent-resilient", correlation_id=str(uuid4()))

    print("\nComprehensive Error Recovery Pattern:")

    max_retries = 3
    success = False

    for attempt in range(max_retries):
        try:
            # Simulate operation
            if attempt < 2:
                raise ConnectionError("Temporary network issue")

            # Success on third attempt
            success = True
            result = {"data": "success"}

            # Log success
            await logger.log_success(
                success_name="operation_succeeded_after_retry",
                success_details={
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "result": result,
                },
                duration_ms=50,
            )
            print(f"✓ Success after {attempt + 1} attempts\n")
            break

        except ConnectionError as e:
            # Log retry attempt
            await logger.log_decision(
                decision_name="retry_operation",
                decision_context={
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "error": str(e),
                },
                decision_result={
                    "action": "retry",
                    "delay_ms": (attempt + 1) * 100,  # Exponential backoff
                },
            )

            if attempt == max_retries - 1:
                # Log final failure
                await logger.log_error(
                    error_type="MaxRetriesExceeded",
                    error_message=f"Failed after {max_retries} attempts: {e}",
                    error_context={"attempts": max_retries, "last_error": str(e)},
                )
                print(f"✗ Failed after {max_retries} attempts\n")

            # Wait before retry
            await asyncio.sleep(0.01)


if __name__ == "__main__":
    asyncio.run(error_and_success_examples())
    asyncio.run(error_recovery_pattern())
