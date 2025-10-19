#!/usr/bin/env python3
"""
Workflow Executor - Complete 6-Phase Agent Orchestration Pipeline

Integrates with agent-workflow-coordinator to execute:
- Phase 0: Context Gathering
- Phase 1: Task Decomposition with AI Quorum Validation
- Phase 2: Context Filtering
- Phase 3: Parallel Agent Execution
- Phase 4: Result Aggregation
- Phase 5: Quality Reporting
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Add agents directory to path (use environment variable or relative path)
AGENTS_PATH = os.getenv("OMNICLAUDE_AGENTS_PATH")
if AGENTS_PATH:
    AGENTS_PATH = Path(AGENTS_PATH)
else:
    # Try relative to current file location
    current_dir = Path(__file__).resolve().parent.parent.parent
    AGENTS_PATH = current_dir / "agents" / "parallel_execution"

if AGENTS_PATH.exists():
    sys.path.insert(0, str(AGENTS_PATH))

try:
    from agent_dispatcher import ParallelCoordinator
    from agent_model import AgentTask
    from context_manager import ContextManager
    from validated_task_architect import ValidatedTaskArchitect

    COMPONENTS_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Agent components not available: {e}", file=sys.stderr)
    COMPONENTS_AVAILABLE = False


class WorkflowExecutor:
    """
    Complete workflow orchestration using the full 6-phase pipeline.

    Designed to be invoked from hooks when agent-workflow-coordinator is detected.
    """

    def __init__(
        self,
        correlation_id: Optional[str] = None,
        workspace: Optional[str] = None,
        db_logging: bool = True,
    ):
        """
        Initialize workflow executor.

        Args:
            correlation_id: Correlation ID for tracking
            workspace: Optional workspace path for file context
            db_logging: Enable database logging
        """
        self.correlation_id = correlation_id
        self.workspace = workspace or str(Path.cwd())
        self.db_logging = db_logging
        self.execution_trace = []

    async def execute_workflow(
        self, user_prompt: str, agent_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute complete 6-phase workflow orchestration.

        Args:
            user_prompt: User's natural language request
            agent_context: Optional context from agent detection

        Returns:
            Complete workflow result with generated code, quality metrics, traces
        """

        if not COMPONENTS_AVAILABLE:
            return {
                "success": False,
                "error": "Agent components not available",
                "fallback_message": "Workflow executor requires agent components",
            }

        workflow_start = time.time()

        try:
            # =================================================================
            # PHASE 0: CONTEXT GATHERING
            # =================================================================
            phase_start = time.time()
            self._log_phase("PHASE 0: Context Gathering", "started")

            context_manager = ContextManager()
            global_context = await context_manager.gather_global_context(
                user_prompt=user_prompt,
                workspace_path=self.workspace,
                max_rag_results=5,
            )

            context_summary = context_manager.get_context_summary()
            phase_time = (time.time() - phase_start) * 1000

            self._log_phase(
                "PHASE 0: Context Gathering",
                "completed",
                {
                    "duration_ms": phase_time,
                    "context_items": context_summary["total_items"],
                    "total_tokens": context_summary["total_tokens_estimate"],
                },
            )

            if self.db_logging:
                await self._log_to_database(
                    "context_gathering",
                    {
                        "phase": "context_gathering",
                        "duration_ms": phase_time,
                        "items_gathered": context_summary["total_items"],
                        "items_by_type": context_summary["items_by_type"],
                        "correlation_id": self.correlation_id,
                    },
                )

            # =================================================================
            # PHASE 1: TASK DECOMPOSITION WITH VALIDATION
            # =================================================================
            phase_start = time.time()
            self._log_phase("PHASE 1: Task Decomposition + Validation", "started")

            architect = ValidatedTaskArchitect()

            # Convert ContextItem objects to serializable dicts
            serializable_context = {}
            for key, context_item in global_context.items():
                serializable_context[key] = {
                    "type": context_item.context_type,
                    "content": context_item.content,
                    "metadata": context_item.metadata,
                }

            breakdown_result = await architect.breakdown_tasks_with_validation(
                user_prompt=user_prompt, global_context=serializable_context
            )

            phase_time = (time.time() - phase_start) * 1000

            if not breakdown_result.get("validated"):
                # Validation failed
                return {
                    "success": False,
                    "phase_failed": "task_decomposition",
                    "error": breakdown_result.get(
                        "error", "Task decomposition validation failed"
                    ),
                    "attempts": breakdown_result.get("attempts", 0),
                    "quorum_result": breakdown_result.get("quorum_result"),
                    "execution_time_ms": (time.time() - workflow_start) * 1000,
                }

            task_plan = breakdown_result["breakdown"]
            quorum_confidence = breakdown_result["quorum_result"]["confidence"]

            self._log_phase(
                "PHASE 1: Task Decomposition + Validation",
                "completed",
                {
                    "duration_ms": phase_time,
                    "tasks_identified": len(task_plan.get("tasks", [])),
                    "validation_attempts": breakdown_result["attempts"],
                    "quorum_confidence": quorum_confidence,
                },
            )

            if self.db_logging:
                await self._log_to_database(
                    "task_decomposition",
                    {
                        "phase": "task_decomposition",
                        "duration_ms": phase_time,
                        "task_count": len(task_plan.get("tasks", [])),
                        "validation_confidence": quorum_confidence,
                        "validation_attempts": breakdown_result["attempts"],
                        "correlation_id": self.correlation_id,
                    },
                )

            # =================================================================
            # PHASE 2: CONTEXT FILTERING
            # =================================================================
            phase_start = time.time()
            self._log_phase("PHASE 2: Context Filtering", "started")

            filtered_contexts = {}
            for task_def in task_plan.get("tasks", []):
                requirements = task_def.get("context_requirements", [])
                filtered_contexts[task_def["task_id"]] = context_manager.filter_context(
                    context_requirements=requirements, max_tokens=5000
                )

            phase_time = (time.time() - phase_start) * 1000

            self._log_phase(
                "PHASE 2: Context Filtering",
                "completed",
                {
                    "duration_ms": phase_time,
                    "contexts_filtered": len(filtered_contexts),
                },
            )

            # =================================================================
            # PHASE 3: PARALLEL AGENT EXECUTION
            # =================================================================
            phase_start = time.time()
            self._log_phase("PHASE 3: Parallel Agent Execution", "started")

            coordinator = ParallelCoordinator(
                use_enhanced_router=True, router_confidence_threshold=0.6
            )
            await coordinator.initialize()

            # Convert to AgentTask objects with filtered context
            tasks = []
            for task_def in task_plan.get("tasks", []):
                task = AgentTask(
                    task_id=task_def["task_id"],
                    description=task_def["description"],
                    input_data={
                        **task_def.get("input_data", {}),
                        "pre_gathered_context": filtered_contexts.get(
                            task_def["task_id"], {}
                        ),
                    },
                    dependencies=task_def.get("dependencies", []),
                )
                tasks.append(task)

            # Execute with dependency tracking
            results = await coordinator.execute_parallel(tasks)

            phase_time = (time.time() - phase_start) * 1000

            self._log_phase(
                "PHASE 3: Parallel Agent Execution",
                "completed",
                {
                    "duration_ms": phase_time,
                    "tasks_executed": len(results),
                    "successful": sum(1 for r in results.values() if r.success),
                    "failed": sum(1 for r in results.values() if not r.success),
                },
            )

            if self.db_logging:
                await self._log_to_database(
                    "parallel_execution",
                    {
                        "phase": "parallel_execution",
                        "duration_ms": phase_time,
                        "total_tasks": len(results),
                        "successful_tasks": sum(
                            1 for r in results.values() if r.success
                        ),
                        "router_stats": coordinator.get_router_stats(),
                        "correlation_id": self.correlation_id,
                    },
                )

            # =================================================================
            # PHASE 4: RESULT AGGREGATION
            # =================================================================
            phase_start = time.time()
            self._log_phase("PHASE 4: Result Aggregation", "started")

            aggregated = await self._aggregate_results(results)

            phase_time = (time.time() - phase_start) * 1000

            self._log_phase(
                "PHASE 4: Result Aggregation",
                "completed",
                {
                    "duration_ms": phase_time,
                    "code_files_generated": len(aggregated.get("generated_code", {})),
                    "average_quality": aggregated.get("average_quality_score", 0),
                },
            )

            # =================================================================
            # PHASE 5: QUALITY REPORTING
            # =================================================================
            total_workflow_time = (time.time() - workflow_start) * 1000

            final_result = {
                "success": True,
                "workflow_type": "complete_orchestration",
                "correlation_id": self.correlation_id,
                "total_time_ms": total_workflow_time,
                "phases": {
                    "context_gathering": (
                        self.execution_trace[0] if len(self.execution_trace) > 0 else {}
                    ),
                    "task_decomposition": (
                        self.execution_trace[1] if len(self.execution_trace) > 1 else {}
                    ),
                    "context_filtering": (
                        self.execution_trace[2] if len(self.execution_trace) > 2 else {}
                    ),
                    "parallel_execution": (
                        self.execution_trace[3] if len(self.execution_trace) > 3 else {}
                    ),
                    "result_aggregation": (
                        self.execution_trace[4] if len(self.execution_trace) > 4 else {}
                    ),
                },
                "tasks": {
                    "total": len(tasks),
                    "successful": aggregated["successful_tasks"],
                    "failed": aggregated["failed_tasks"],
                },
                "quality": {
                    "average_score": aggregated.get("average_quality_score", 0),
                    "validation_passed": aggregated.get("average_quality_score", 0)
                    >= 0.7,
                },
                "outputs": aggregated.get("outputs", {}),
                "generated_code": aggregated.get("generated_code", {}),
                "router_performance": coordinator.get_router_stats(),
            }

            self._log_phase(
                "PHASE 5: Quality Reporting",
                "completed",
                {
                    "total_workflow_time_ms": total_workflow_time,
                    "overall_success": final_result["success"],
                    "quality_validation_passed": final_result["quality"][
                        "validation_passed"
                    ],
                },
            )

            if self.db_logging:
                await self._log_to_database(
                    "workflow_complete",
                    {
                        "phase": "workflow_complete",
                        "total_time_ms": total_workflow_time,
                        "successful": final_result["success"],
                        "tasks_completed": aggregated["successful_tasks"],
                        "average_quality": aggregated.get("average_quality_score", 0),
                        "correlation_id": self.correlation_id,
                    },
                )

            # Cleanup
            await context_manager.cleanup()
            await coordinator.cleanup()

            return final_result

        except Exception as e:
            error_time = (time.time() - workflow_start) * 1000

            error_result = {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "execution_time_ms": error_time,
                "correlation_id": self.correlation_id,
                "execution_trace": self.execution_trace,
            }

            if self.db_logging:
                await self._log_to_database(
                    "workflow_error",
                    {
                        "phase": "workflow_error",
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "duration_ms": error_time,
                        "correlation_id": self.correlation_id,
                    },
                )

            return error_result

    async def _aggregate_results(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Aggregate results from parallel execution."""

        aggregated = {
            "workflow_status": "completed",
            "total_tasks": len(results),
            "successful_tasks": sum(1 for r in results.values() if r.success),
            "failed_tasks": sum(1 for r in results.values() if not r.success),
            "outputs": {},
            "quality_metrics": {},
            "generated_code": {},
        }

        for task_id, result in results.items():
            if result.success:
                output_data = result.output_data or {}

                # Collect generated code
                if "generated_code" in output_data:
                    aggregated["generated_code"][task_id] = output_data[
                        "generated_code"
                    ]

                # Collect quality metrics
                if "quality_score" in output_data:
                    aggregated["quality_metrics"][task_id] = output_data[
                        "quality_score"
                    ]

                aggregated["outputs"][task_id] = {
                    "agent": result.agent_name,
                    "execution_time_ms": result.execution_time_ms,
                    "summary": output_data,
                }

        # Calculate overall quality
        if aggregated["quality_metrics"]:
            avg_quality = sum(aggregated["quality_metrics"].values()) / len(
                aggregated["quality_metrics"]
            )
            aggregated["average_quality_score"] = avg_quality
        else:
            aggregated["average_quality_score"] = 0.0

        return aggregated

    def _log_phase(
        self, phase_name: str, status: str, metadata: Optional[Dict[str, Any]] = None
    ):
        """Log phase execution to trace."""

        log_entry = {
            "phase": phase_name,
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata or {},
        }

        self.execution_trace.append(log_entry)

        # Print to stderr for hook logging
        print(f"[WorkflowExecutor] {phase_name}: {status}", file=sys.stderr)
        if metadata:
            print(f"  {json.dumps(metadata, indent=2)}", file=sys.stderr)

    async def _log_to_database(self, event_type: str, payload: Dict[str, Any]):
        """Log event to database via hook_event_logger."""

        try:
            # Import here to avoid circular dependencies
            from hook_event_logger import log_hook_event

            log_hook_event(
                source="WorkflowExecutor",
                action=event_type,
                resource_id=self.correlation_id,
                payload=payload,
                metadata={
                    "correlation_id": self.correlation_id,
                    "workspace": self.workspace,
                },
            )
        except Exception as e:
            print(f"[WorkflowExecutor] Database logging failed: {e}", file=sys.stderr)


async def execute_from_hook(
    user_prompt: str,
    correlation_id: str,
    workspace: Optional[str] = None,
    agent_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Entry point for hook invocation.

    Args:
        user_prompt: User's natural language request
        correlation_id: Correlation ID from hook
        workspace: Optional workspace path
        agent_context: Optional agent detection context

    Returns:
        Workflow execution result
    """

    executor = WorkflowExecutor(
        correlation_id=correlation_id, workspace=workspace, db_logging=True
    )

    return await executor.execute_workflow(
        user_prompt=user_prompt, agent_context=agent_context
    )


def main():
    """CLI entry point for testing."""

    if len(sys.argv) < 2:
        print(
            "Usage: workflow_executor.py '<user_prompt>' [correlation_id] [workspace]"
        )
        sys.exit(1)

    user_prompt = sys.argv[1]
    correlation_id = sys.argv[2] if len(sys.argv) > 2 else None
    workspace = sys.argv[3] if len(sys.argv) > 3 else None

    result = asyncio.run(
        execute_from_hook(
            user_prompt=user_prompt,
            correlation_id=correlation_id or "test-" + str(int(time.time())),
            workspace=workspace,
        )
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
