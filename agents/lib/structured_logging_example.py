"""
Structured Logging Integration Example

This file demonstrates best practices for integrating structured logging
into agent workflows with correlation IDs, context propagation, and
comprehensive error handling.

Run this example:
    python -m agents.lib.structured_logging_example
"""

import asyncio
from typing import Any, Dict, List
from uuid import UUID, uuid4

from .log_context import async_log_context, with_log_context
from .log_rotation import LogRotationConfig, configure_global_rotation
from .structured_logger import get_logger

# Initialize loggers for different components
research_logger = get_logger(__name__ + ".research", component="agent-researcher")
analysis_logger = get_logger(__name__ + ".analysis", component="agent-analyzer")
workflow_logger = get_logger(__name__ + ".workflow", component="agent-workflow")


# Example 1: Simple task with correlation ID
@with_log_context(component="agent-researcher")
async def simple_research_task(query: str, correlation_id: UUID) -> Dict[str, Any]:
    """
    Simple research task with automatic correlation ID propagation.

    The @with_log_context decorator automatically sets up the correlation
    ID from the function parameter.
    """
    research_logger.info("Research task started", metadata={"query": query})

    try:
        # Simulate research
        await asyncio.sleep(0.1)
        results = {"query": query, "results": ["result1", "result2", "result3"]}

        research_logger.info(
            "Research task completed",
            metadata={"query": query, "results_count": len(results["results"])},
        )

        return results

    except Exception as e:
        research_logger.error(
            "Research task failed",
            metadata={"query": query, "error_type": type(e).__name__},
            exc_info=e,
        )
        raise


# Example 2: Multi-phase workflow with context manager
async def multi_phase_workflow(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Multi-phase workflow demonstrating context manager usage.

    Uses async_log_context to set up correlation ID for the entire workflow.
    All logs within the context automatically include the correlation ID.
    """
    correlation_id = uuid4()

    async with async_log_context(correlation_id=correlation_id):
        workflow_logger.info(
            "Workflow started", metadata={"request_id": request.get("id"), "phases": 3}
        )

        try:
            # Phase 1: Research
            workflow_logger.info(
                "Phase started", metadata={"phase": "research", "phase_num": 1}
            )
            research_results = await research_phase(request["query"])
            workflow_logger.info(
                "Phase completed",
                metadata={
                    "phase": "research",
                    "phase_num": 1,
                    "results_count": len(research_results),
                },
            )

            # Phase 2: Analysis
            workflow_logger.info(
                "Phase started", metadata={"phase": "analysis", "phase_num": 2}
            )
            analysis_results = await analysis_phase(research_results)
            workflow_logger.info(
                "Phase completed",
                metadata={
                    "phase": "analysis",
                    "phase_num": 2,
                    "analysis_score": analysis_results.get("score"),
                },
            )

            # Phase 3: Synthesis
            workflow_logger.info(
                "Phase started", metadata={"phase": "synthesis", "phase_num": 3}
            )
            final_results = await synthesis_phase(research_results, analysis_results)
            workflow_logger.info(
                "Phase completed", metadata={"phase": "synthesis", "phase_num": 3}
            )

            workflow_logger.info(
                "Workflow completed successfully",
                metadata={"correlation_id": str(correlation_id), "total_phases": 3},
            )

            return final_results

        except Exception as e:
            workflow_logger.error(
                "Workflow failed",
                metadata={
                    "correlation_id": str(correlation_id),
                    "error_phase": "unknown",
                },
                exc_info=e,
            )
            raise


# Example 3: Nested contexts with component switching
async def nested_context_example(query: str) -> Dict[str, Any]:
    """
    Demonstrates nested contexts with different components.

    Shows how correlation IDs propagate through nested contexts while
    components can be switched per context.
    """
    main_correlation_id = uuid4()

    async with async_log_context(
        correlation_id=main_correlation_id, component="main-workflow"
    ):
        workflow_logger.info("Main workflow started", metadata={"query": query})

        # Nested context for research (different component, same correlation ID)
        async with async_log_context(component="agent-researcher"):
            research_logger.info("Starting nested research", metadata={"query": query})
            research_results = await perform_research(query)
            research_logger.info(
                "Nested research completed",
                metadata={"results_count": len(research_results)},
            )

        # Back to main context
        workflow_logger.info(
            "Main workflow continuing", metadata={"next_step": "analysis"}
        )

        # Nested context for analysis
        async with async_log_context(component="agent-analyzer"):
            analysis_logger.info(
                "Starting nested analysis",
                metadata={"results_count": len(research_results)},
            )
            analysis_results = await perform_analysis(research_results)
            analysis_logger.info(
                "Nested analysis completed",
                metadata={"score": analysis_results["score"]},
            )

        workflow_logger.info("Main workflow completed")

        return {
            "query": query,
            "research": research_results,
            "analysis": analysis_results,
            "correlation_id": str(main_correlation_id),
        }


# Example 4: Error handling with structured logging
async def error_handling_example(task_id: str) -> Dict[str, Any]:
    """
    Demonstrates comprehensive error handling with structured logging.

    Shows different error types and how to log them with appropriate
    context and metadata.
    """
    correlation_id = uuid4()

    async with async_log_context(correlation_id=correlation_id):
        workflow_logger.info("Task started", metadata={"task_id": task_id})

        try:
            # Simulate validation error
            if not task_id:
                workflow_logger.warning(
                    "Validation warning",
                    metadata={"task_id": task_id, "validation": "empty_task_id"},
                )
                raise ValueError("Task ID cannot be empty")

            # Simulate processing
            result = await process_task(task_id)

            workflow_logger.info(
                "Task completed successfully",
                metadata={"task_id": task_id, "result_type": type(result).__name__},
            )

            return result

        except ValueError as e:
            workflow_logger.error(
                "Validation error",
                metadata={"task_id": task_id, "error_type": "validation"},
                exc_info=e,
            )
            raise

        except asyncio.TimeoutError as e:
            workflow_logger.error(
                "Timeout error",
                metadata={"task_id": task_id, "error_type": "timeout"},
                exc_info=e,
            )
            raise

        except Exception as e:
            workflow_logger.critical(
                "Unexpected error",
                metadata={"task_id": task_id, "error_type": "unexpected"},
                exc_info=e,
            )
            raise


# Helper functions for examples
async def research_phase(query: str) -> List[str]:
    """Simulate research phase"""
    research_logger.debug("Performing research", metadata={"query": query})
    await asyncio.sleep(0.1)
    return ["result1", "result2", "result3"]


async def analysis_phase(results: List[str]) -> Dict[str, Any]:
    """Simulate analysis phase"""
    analysis_logger.debug(
        "Performing analysis", metadata={"results_count": len(results)}
    )
    await asyncio.sleep(0.1)
    return {"score": 0.85, "confidence": 0.92}


async def synthesis_phase(
    research: List[str], analysis: Dict[str, Any]
) -> Dict[str, Any]:
    """Simulate synthesis phase"""
    workflow_logger.debug("Performing synthesis")
    await asyncio.sleep(0.1)
    return {
        "research_count": len(research),
        "analysis_score": analysis["score"],
        "final_recommendation": "approved",
    }


async def perform_research(query: str) -> List[str]:
    """Simulate research"""
    await asyncio.sleep(0.1)
    return ["research_result_1", "research_result_2"]


async def perform_analysis(results: List[str]) -> Dict[str, Any]:
    """Simulate analysis"""
    await asyncio.sleep(0.1)
    return {"score": 0.78, "results": results}


async def process_task(task_id: str) -> Dict[str, Any]:
    """Simulate task processing"""
    await asyncio.sleep(0.1)
    return {"task_id": task_id, "status": "completed"}


# Main demonstration
async def main():
    """
    Main demonstration of structured logging features.
    """
    print("\n" + "=" * 80)
    print("STRUCTURED LOGGING DEMONSTRATION")
    print("=" * 80 + "\n")

    # Configure log rotation for development
    print("Configuring log rotation...")
    config = LogRotationConfig.development()
    config.log_dir = "./example_logs"

    configure_global_rotation(config=config)
    print(f"✓ Logs will be written to: {config.log_dir}\n")

    # Example 1: Simple task
    print("Example 1: Simple research task with decorator")
    print("-" * 80)
    correlation_id_1 = uuid4()
    results_1 = await simple_research_task(
        "What is Python?", correlation_id=correlation_id_1
    )
    print(f"✓ Correlation ID: {correlation_id_1}")
    print(f"✓ Results: {results_1}\n")

    # Example 2: Multi-phase workflow
    print("Example 2: Multi-phase workflow with context manager")
    print("-" * 80)
    request = {"id": "req-123", "query": "Explain structured logging"}
    results_2 = await multi_phase_workflow(request)
    print(f"✓ Workflow completed: {results_2.get('correlation_id', 'N/A')}\n")

    # Example 3: Nested contexts
    print("Example 3: Nested contexts with component switching")
    print("-" * 80)
    results_3 = await nested_context_example("How does context propagation work?")
    print(f"✓ Nested workflow completed: {results_3['correlation_id']}\n")

    # Example 4: Error handling
    print("Example 4: Error handling with structured logging")
    print("-" * 80)
    try:
        await error_handling_example("")  # Empty task_id to trigger error
    except ValueError as e:
        print(f"✓ Error caught and logged: {e}\n")

    # Show log file stats
    print("Log Statistics")
    print("-" * 80)
    from .log_rotation import get_log_stats

    stats = get_log_stats(config.log_dir)
    print(f"Files created: {stats['file_count']}")
    print(f"Total size: {stats['total_size_mb']:.2f}MB")
    if stats["newest_file"]:
        print(f"Latest log: {stats['newest_file']}")

    print("\n" + "=" * 80)
    print("DEMONSTRATION COMPLETE")
    print("=" * 80)
    print(f"\nCheck {config.log_dir}/*.log for JSON log output")
    print("All logs include correlation IDs, timestamps, and metadata\n")


if __name__ == "__main__":
    asyncio.run(main())
