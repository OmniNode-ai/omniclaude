"""
Parallel Agent Coordinator

Executes multiple agents concurrently with dependency tracking and trace logging.
"""

import asyncio
import time
from collections import defaultdict
from typing import Any

from trace_logger import TraceEventType, TraceLevel, get_trace_logger

from .agent_analyzer import ArchitecturalAnalyzerAgent
from .agent_coder import CoderAgent
from .agent_debug_intelligence import DebugIntelligenceAgent
from .agent_model import AgentResult, AgentTask
from .agent_researcher import ResearchIntelligenceAgent
from .agent_validator import AgentValidator


class ParallelCoordinator:
    """
    Coordinates parallel execution of agents with dependency tracking.

    Features:
    - Concurrent agent execution
    - Dependency graph resolution
    - Trace logging for all operations
    - Result aggregation
    """

    def __init__(self):
        self.trace_logger = get_trace_logger()
        self._coordinator_trace_id: str | None = None

        # Agent registry
        self.agents = {
            "agent-contract-driven-generator": CoderAgent(),
            "agent-debug-intelligence": DebugIntelligenceAgent(),
            "agent-analyzer": ArchitecturalAnalyzerAgent(),
            "agent-researcher": ResearchIntelligenceAgent(),
            "agent-validator": AgentValidator(),
        }

    async def execute_parallel(self, tasks: list[AgentTask]) -> dict[str, AgentResult]:
        """
        Execute tasks in parallel with dependency resolution.

        Args:
            tasks: List of tasks to execute

        Returns:
            Dictionary mapping task_id to AgentResult
        """
        start_time = time.time()

        # Start coordinator trace
        self._coordinator_trace_id = await self.trace_logger.start_coordinator_trace(
            coordinator_type="parallel",
            total_agents=len(tasks),
            metadata={
                "tasks": [
                    {"task_id": t.task_id, "description": t.description} for t in tasks
                ]
            },
        )

        await self.trace_logger.log_event(
            event_type=TraceEventType.COORDINATOR_START,
            message=f"Starting parallel execution of {len(tasks)} tasks",
            level=TraceLevel.INFO,
        )

        # Build dependency graph
        self._build_dependency_graph(tasks)

        # Execute in waves based on dependencies
        results = {}
        completed_tasks = set()

        while len(completed_tasks) < len(tasks):
            # Find tasks ready to execute (no pending dependencies)
            ready_tasks = [
                task
                for task in tasks
                if task.task_id not in completed_tasks
                and all(dep in completed_tasks for dep in task.dependencies)
            ]

            if not ready_tasks:
                # Deadlock detected
                pending = [t.task_id for t in tasks if t.task_id not in completed_tasks]
                error_msg = f"Dependency deadlock detected. Pending tasks: {pending}"

                await self.trace_logger.log_event(
                    event_type=TraceEventType.PARALLEL_BATCH_END,
                    message=error_msg,
                    level=TraceLevel.ERROR,
                )
                break

            # Log batch start
            await self.trace_logger.log_event(
                event_type=TraceEventType.PARALLEL_BATCH_START,
                message=f"Executing batch of {len(ready_tasks)} tasks in parallel",
                level=TraceLevel.INFO,
                metadata={"task_ids": [t.task_id for t in ready_tasks]},
            )

            # Execute ready tasks in parallel
            batch_results = await self._execute_batch(ready_tasks)

            # Update results and completed set
            results.update(batch_results)
            completed_tasks.update(batch_results.keys())

            # Log batch completion
            await self.trace_logger.log_event(
                event_type=TraceEventType.PARALLEL_BATCH_END,
                message=f"Batch complete: {len(batch_results)} tasks finished",
                level=TraceLevel.INFO,
                metadata={
                    "completed": list(batch_results.keys()),
                    "success_count": sum(
                        1 for r in batch_results.values() if r.success
                    ),
                },
            )

        # Calculate total execution time
        total_time_ms = (time.time() - start_time) * 1000

        # End coordinator trace
        await self.trace_logger.end_coordinator_trace(
            trace_id=self._coordinator_trace_id,
            metadata={
                "total_time_ms": total_time_ms,
                "tasks_completed": len(results),
                "success_count": sum(1 for r in results.values() if r.success),
            },
        )

        await self.trace_logger.log_event(
            event_type=TraceEventType.COORDINATOR_END,
            message=f"Parallel execution complete: {len(results)} tasks in {total_time_ms:.2f}ms",
            level=TraceLevel.INFO,
            metadata={
                "total_time_ms": total_time_ms,
                "results": {tid: r.success for tid, r in results.items()},
            },
        )

        return results

    def _build_dependency_graph(self, tasks: list[AgentTask]) -> dict[str, list[str]]:
        """Build dependency graph from tasks."""
        graph = defaultdict(list)

        for task in tasks:
            for dep in task.dependencies:
                graph[dep].append(task.task_id)

        return dict(graph)

    async def _execute_batch(self, tasks: list[AgentTask]) -> dict[str, AgentResult]:
        """Execute a batch of tasks in parallel."""
        batch_results = {}

        # Create execution coroutines
        execution_coros = []

        for task in tasks:
            # Determine which agent to use based on task
            agent_name = self._select_agent_for_task(task)

            if agent_name not in self.agents:
                # Create error result for unknown agent
                batch_results[task.task_id] = AgentResult(
                    task_id=task.task_id,
                    agent_name=agent_name,
                    success=False,
                    error=f"Unknown agent: {agent_name}",
                    execution_time_ms=0.0,
                )
                continue

            # Log task assignment
            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_ASSIGNED,
                message=f"Task {task.task_id} assigned to {agent_name}",
                level=TraceLevel.INFO,
                agent_name=agent_name,
                task_id=task.task_id,
            )

            # Create execution coroutine
            agent = self.agents[agent_name]
            execution_coros.append(self._execute_with_logging(agent, task))

        # Execute all in parallel
        if execution_coros:
            results_list = await asyncio.gather(
                *execution_coros, return_exceptions=True
            )

            # Process results
            for i, result in enumerate(results_list):
                task = tasks[i] if i < len(tasks) else None

                if isinstance(result, Exception):
                    # Handle exception
                    error_msg = f"Task execution error: {str(result)}"

                    if task:
                        batch_results[task.task_id] = AgentResult(
                            task_id=task.task_id,
                            agent_name="unknown",
                            success=False,
                            error=error_msg,
                            execution_time_ms=0.0,
                        )

                        await self.trace_logger.log_event(
                            event_type=TraceEventType.TASK_FAILED,
                            message=error_msg,
                            level=TraceLevel.ERROR,
                            task_id=task.task_id,
                        )
                elif isinstance(result, AgentResult):
                    batch_results[result.task_id] = result

        return batch_results

    async def _execute_with_logging(self, agent: Any, task: AgentTask) -> AgentResult:
        """Execute agent with additional logging."""
        try:
            result = await agent.execute(task)

            # Log completion
            status = "succeeded" if result.success else "failed"
            level = TraceLevel.INFO if result.success else TraceLevel.ERROR

            await self.trace_logger.log_event(
                event_type=(
                    TraceEventType.TASK_COMPLETED
                    if result.success
                    else TraceEventType.TASK_FAILED
                ),
                message=f"Task {task.task_id} {status} in {result.execution_time_ms:.2f}ms",
                level=level,
                agent_name=result.agent_name,
                task_id=task.task_id,
                metadata={"execution_time_ms": result.execution_time_ms},
            )

            return result

        except Exception as e:
            error_msg = f"Agent execution exception: {str(e)}"

            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_ERROR,
                message=error_msg,
                level=TraceLevel.ERROR,
                task_id=task.task_id,
            )

            return AgentResult(
                task_id=task.task_id,
                agent_name=(
                    task.agent_name if hasattr(task, "agent_name") else "unknown"
                ),
                success=False,
                error=error_msg,
                execution_time_ms=0.0,
            )

    def _select_agent_for_task(self, task: AgentTask) -> str:
        """Select appropriate agent based on task metadata."""
        # Priority 1: Use explicit agent_name if provided
        if hasattr(task, "agent_name") and task.agent_name:
            return task.agent_name

        # Priority 2: Fall back to keyword-based selection
        description_lower = task.description.lower()

        # Check for debug keywords first (higher priority)
        if (
            "debug" in description_lower
            or "investigate" in description_lower
            or "bug" in description_lower
        ):
            return "agent-debug-intelligence"
        # Then check for generation keywords
        elif (
            "generate" in description_lower
            or "contract" in description_lower
            or "build" in description_lower
            or "create" in description_lower
        ):
            return "agent-contract-driven-generator"
        # If contains "code" but not debug/generate, check context
        elif "code" in description_lower:
            # If it's about analyzing/fixing code, use debug intelligence
            if any(
                word in description_lower
                for word in ["analyze", "fix", "error", "issue", "problem"]
            ):
                return "agent-debug-intelligence"
            # Otherwise use code generator
            return "agent-contract-driven-generator"
        else:
            # Default to code generator for unknown tasks (changed from debug)
            return "agent-contract-driven-generator"

    async def cleanup(self):
        """Cleanup all agents."""
        for agent in self.agents.values():
            if hasattr(agent, "cleanup"):
                await agent.cleanup()
