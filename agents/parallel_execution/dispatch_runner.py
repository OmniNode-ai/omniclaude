#!/usr/bin/env python3
"""
Parallel Task Dispatch Runner with Phase-by-Phase Control & Debug Support

Entry point for executing parallel agent tasks with intelligent context management,
AI-powered validation, and granular phase-level debugging capabilities.

Implements the enhanced 5-phase workflow with debug control:
- Phase 0: Global context gathering (once per dispatch)
- Phase 1: Intent validation with AI quorum (validates task breakdown)
- Phase 2: Task planning with context awareness
- Phase 3: Context filtering per task
- Phase 4: Parallel execution with filtered context

Phase Control Features:
- Execute specific phases only (--only-phase N)
- Stop after specific phase for debugging (--stop-after-phase N)
- Skip phases that are not needed (--skip-phases 0,1)
- Phase state persistence for inspection and resumption
- Phase dependency validation
- Comprehensive phase timing and logging

Interactive Mode Features:
- Human-in-the-loop validation at each major step
- Approve, edit, retry, or skip any step
- Session save/resume for interrupted workflows
- Batch approval for trusted workflows

Usage:
    # Standard execution
    python dispatch_runner.py < tasks.json
    python dispatch_runner.py --enable-context --enable-quorum < tasks.json

    # Phase-specific debugging
    python dispatch_runner.py --only-phase 0 < tasks.json  # Context gathering only
    python dispatch_runner.py --stop-after-phase 1 < tasks.json  # Stop after quorum
    python dispatch_runner.py --skip-phases 0,1 < tasks.json  # Skip context & quorum

    # Phase state management
    python dispatch_runner.py --save-phase-state phases.json < tasks.json
    python dispatch_runner.py --load-phase-state phases.json < tasks.json

    # Interactive mode
    python dispatch_runner.py --interactive --enable-quorum < tasks.json
"""

import asyncio
import json
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from agent_dispatcher import ParallelCoordinator
from agent_model import AgentTask, AgentConfig
from context_manager import ContextManager
from agent_architect import ArchitectAgent

# Import workflow phase models
from workflow.phase_models import (
    ExecutionPhase,
    PhaseConfig,
    PhaseResult,
    PhaseState
)
from agents.lib.lineage import LineageWriter, LineageEdge
from agents.lib.debug_loop import record_workflow_step
from agents.lib.state_snapshots import capture_workflow_state
from agents.lib.error_logging import log_execution_error
from agents.lib.success_logging import log_phase_success
from agents.lib.logging_config import debug_logger, LogLevel

# Import retry manager for robust error handling
try:
    from agents.lib.retry_manager import (
        execute_with_retry,
        execute_with_circuit_breaker,
        STANDARD_RETRY_CONFIG,
        API_RETRY_CONFIG,
        DATABASE_RETRY_CONFIG
    )
    RETRY_MANAGER_AVAILABLE = True
except ImportError:
    RETRY_MANAGER_AVAILABLE = False
    print("[DispatchRunner] Warning: Retry manager unavailable (retry_manager.py not found)", file=sys.stderr)

# Import performance monitor for real-time tracking
try:
    from agents.lib.performance_monitor import (
        track_phase_performance,
        check_performance_threshold,
        get_performance_level,
        get_performance_summary
    )
    PERFORMANCE_MONITOR_AVAILABLE = True
except ImportError:
    PERFORMANCE_MONITOR_AVAILABLE = False
    print("[DispatchRunner] Warning: Performance monitor unavailable (performance_monitor.py not found)", file=sys.stderr)

# Import input validator for security and quality checks
try:
    from agents.lib.input_validator import (
        validate_and_sanitize,
        sanitize_prompt,
        validate_json_input,
        InputType
    )
    INPUT_VALIDATOR_AVAILABLE = True
except ImportError:
    INPUT_VALIDATOR_AVAILABLE = False
    print("[DispatchRunner] Warning: Input validator unavailable (input_validator.py not found)", file=sys.stderr)

# Import quorum validation (optional dependency)
try:
    from quorum_minimal import MinimalQuorum, ValidationDecision
    QUORUM_AVAILABLE = True
except ImportError:
    QUORUM_AVAILABLE = False
    print("[DispatchRunner] Warning: Quorum validation unavailable (quorum_minimal.py not found)", file=sys.stderr)

# Import interactive validator (optional dependency)
try:
    from interactive_validator import (
        create_validator,
        CheckpointType,
        UserChoice,
        InteractiveValidator,
        QuietValidator
    )
    INTERACTIVE_AVAILABLE = True
except ImportError:
    INTERACTIVE_AVAILABLE = False
    print("[DispatchRunner] Warning: Interactive mode unavailable (interactive_validator.py not found)", file=sys.stderr)


# ============================================================================
# Phase Execution Functions
# ============================================================================

async def execute_phase_0_context_gathering(
    user_prompt: str,
    workspace_path: Optional[str],
    rag_queries: List[str],
    validator: Optional[Any],
    phase_state: PhaseState
) -> PhaseResult:
    """Phase 0: Global context gathering using RAG intelligence.

    Args:
        user_prompt: User's original request
        workspace_path: Optional workspace directory path
        rag_queries: List of RAG queries to execute
        validator: Optional interactive validator
        phase_state: Current phase state

    Returns:
        PhaseResult with gathered context
    """
    phase = ExecutionPhase.CONTEXT_GATHERING
    start_time = time.time()
    started_at = datetime.now().isoformat()

    debug_logger.log_phase_start("Phase 0: Context Gathering", f"Queries: {len(rag_queries)}")

    try:
        context_manager = ContextManager()

        debug_logger.log_progress("Gathering global context...")
        
        # Use retry logic for context gathering if available
        if RETRY_MANAGER_AVAILABLE:
            success, result = await execute_with_retry(
                context_manager.gather_global_context,
                user_prompt=user_prompt,
                workspace_path=workspace_path,
                rag_queries=rag_queries,
                max_rag_results=5,
                manager_name="context_gathering",
                config=API_RETRY_CONFIG
            )
            if not success:
                raise result
            global_context = result
        else:
            global_context = await context_manager.gather_global_context(
                user_prompt=user_prompt,
                workspace_path=workspace_path,
                rag_queries=rag_queries,
                max_rag_results=5
            )

        # Print context summary
        summary = context_manager.get_context_summary()
        print(
            f"[DispatchRunner] ✓ Context gathered: {summary['total_items']} items, "
            f"~{summary['total_tokens_estimate']} tokens",
            file=sys.stderr
        )

        # Interactive checkpoint: Review gathered context
        if validator:
            # Build detailed context display with actual content
            context_display = {
                "summary": summary,
                "rag_queries": rag_queries,
                "gathered_context": {}
            }

            # Include actual context content for review
            if global_context:
                for key, value in global_context.items():
                    # Extract content from ContextItem objects
                    if hasattr(value, 'content'):
                        content = value.content

                        # If it's a RAG response, extract the actual results
                        if isinstance(content, dict):
                            # Try to extract meaningful content from RAG results
                            if 'results' in content:
                                rag_results = content.get('results', {})
                                extracted = []

                                # Extract from rag_search
                                if 'rag_search' in rag_results and rag_results['rag_search'].get('results'):
                                    for item in rag_results['rag_search']['results'][:3]:
                                        if isinstance(item, dict):
                                            extracted.append({
                                                'source': 'RAG Search',
                                                'content': item.get('content', item.get('text', str(item)))[:15000]
                                            })

                                # Extract from vector_search
                                if 'vector_search' in rag_results and rag_results['vector_search'].get('results'):
                                    for item in rag_results['vector_search']['results'][:2]:
                                        if isinstance(item, dict):
                                            extracted.append({
                                                'source': 'Vector Search',
                                                'content': item.get('content', item.get('text', str(item)))[:15000]
                                            })

                                context_display["gathered_context"][key] = extracted if extracted else content
                            else:
                                context_display["gathered_context"][key] = content
                        else:
                            context_display["gathered_context"][key] = str(content)[:2000]
                    elif isinstance(value, str):
                        context_display["gathered_context"][key] = value[:2000] + "..." if len(value) > 2000 else value
                    elif isinstance(value, list):
                        context_display["gathered_context"][key] = value[:5]
                    elif isinstance(value, dict):
                        context_display["gathered_context"][key] = value
                    else:
                        context_display["gathered_context"][key] = str(value)[:500]

            checkpoint_result = validator.checkpoint(
                checkpoint_id="context_gathering",
                checkpoint_type=CheckpointType.CONTEXT_GATHERING,
                step_number=0,
                total_steps=4,
                step_name="Context Gathering",
                output_data=context_display
            )

            if checkpoint_result.choice == UserChoice.SKIP:
                print("[DispatchRunner] Context gathering skipped by user", file=sys.stderr)
                duration_ms = (time.time() - start_time) * 1000
                return PhaseResult(
                    phase=phase,
                    phase_name="Context Gathering",
                    success=True,
                    duration_ms=duration_ms,
                    started_at=started_at,
                    completed_at=datetime.now().isoformat(),
                    skipped=True
                )
            elif checkpoint_result.choice == UserChoice.QUIT:
                print("[DispatchRunner] Workflow terminated by user at context gathering", file=sys.stderr)
                sys.exit(0)

        # Store context in phase state
        phase_state.global_context = global_context

        duration_ms = (time.time() - start_time) * 1000
        debug_logger.log_phase_complete("Phase 0: Context Gathering", duration_ms, success=True)

        result_obj = PhaseResult(
            phase=phase,
            phase_name="Context Gathering",
            success=True,
            duration_ms=duration_ms,
            started_at=started_at,
            completed_at=datetime.now().isoformat(),
            output_data={
                'context_summary': summary,
                'total_items': summary['total_items']
            }
        )

        try:
            await record_workflow_step(
                run_id=phase_state.user_prompt[:16] or "run",
                step_index=0,
                phase=phase.name,
                started_at=started_at,
                completed_at=result_obj.completed_at,
                duration_ms=duration_ms,
                success=True,
            )
        except Exception:
            pass
        
        # Log success event for Phase 0
        try:
            await log_phase_success(
                run_id=phase_state.user_prompt[:16] or "run",
                phase=phase.name,
                duration_ms=duration_ms,
                metadata={
                    "context_summary": summary,
                    "total_items": summary.get('total_items', 0)
                }
            )
        except Exception:
            pass
        
        # Track performance metrics
        if PERFORMANCE_MONITOR_AVAILABLE:
            try:
                await track_phase_performance(
                    phase=phase.name,
                    duration_ms=duration_ms,
                    success=True,
                    metadata={
                        "context_summary": summary,
                        "total_items": summary.get('total_items', 0)
                    }
                )
            except Exception:
                pass

        # Capture state snapshot for Phase 0
        try:
            await capture_workflow_state(
                run_id=phase_state.user_prompt[:16] or "run",
                phase=phase.name,
                state_data={
                    "global_context": global_context,
                    "context_summary": summary,
                    "phase_result": result_obj.to_dict()
                },
                is_success=True
            )
        except Exception:
            pass
        return result_obj

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[DispatchRunner] ✗ Phase 0 failed: {e}", file=sys.stderr)
        print(f"[DispatchRunner] Phase 0 completed in {duration_ms:.0f}ms\n", file=sys.stderr)

        # Log error event
        try:
            await log_execution_error(
                run_id=phase_state.user_prompt[:16] or "run",
                phase=phase.name,
                task_id=None,
                error=e,
                details={
                    "duration_ms": duration_ms,
                    "started_at": started_at
                }
            )
        except Exception:
            pass
        
        # Track performance metrics for failure
        if PERFORMANCE_MONITOR_AVAILABLE:
            try:
                await track_phase_performance(
                    phase=phase.name,
                    duration_ms=duration_ms,
                    success=False,
                    error_type=type(e).__name__,
                    metadata={
                        "duration_ms": duration_ms,
                        "started_at": started_at
                    }
                )
            except Exception:
                pass

        # Capture error state snapshot
        try:
            await capture_workflow_state(
                run_id=phase_state.user_prompt[:16] or "run",
                phase=phase.name,
                state_data={
                    "error": str(e),
                    "duration_ms": duration_ms,
                    "started_at": started_at,
                    "phase_state": phase_state.to_dict() if hasattr(phase_state, 'to_dict') else {}
                },
                is_success=False
            )
        except Exception:
            pass

        return PhaseResult(
            phase=phase,
            phase_name="Context Gathering",
            success=False,
            duration_ms=duration_ms,
            started_at=started_at,
            completed_at=datetime.now().isoformat(),
            error=str(e)
        )


async def execute_phase_1_quorum_validation(
    user_prompt: str,
    tasks_data: List[Dict[str, Any]],
    validator: Optional[Any],
    phase_state: PhaseState,
    max_retries: int = 3
) -> PhaseResult:
    """Phase 1: Intent validation with AI quorum and retry logic.

    Args:
        user_prompt: User's original request
        tasks_data: Generated task breakdown
        validator: Optional interactive validator
        phase_state: Current phase state
        max_retries: Maximum validation retry attempts

    Returns:
        PhaseResult with validation outcome
    """
    phase = ExecutionPhase.QUORUM_VALIDATION
    start_time = time.time()
    started_at = datetime.now().isoformat()
    retry_count = 0

    print(f"\n{'='*80}", file=sys.stderr)
    print(f"[DispatchRunner] Phase 1: Quorum Validation", file=sys.stderr)
    print(f"[DispatchRunner] Max retries: {max_retries}", file=sys.stderr)
    print(f"{'='*80}\n", file=sys.stderr)

    if not QUORUM_AVAILABLE:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[DispatchRunner] Phase 1 skipped (quorum unavailable) in {duration_ms:.0f}ms\n", file=sys.stderr)
        return PhaseResult(
            phase=phase,
            phase_name="Quorum Validation",
            success=False,
            duration_ms=duration_ms,
            started_at=started_at,
            completed_at=datetime.now().isoformat(),
            skipped=True,
            output_data={'reason': 'Quorum validation unavailable'}
        )

    # Build task breakdown for validation
    task_breakdown = {
        "tasks": tasks_data,
        "user_prompt": user_prompt
    }

    # Retry loop for quorum validation
    while retry_count <= max_retries:
        try:
            quorum = MinimalQuorum()

            if retry_count > 0:
                print(f"\n[DispatchRunner] Retry attempt {retry_count}/{max_retries}", file=sys.stderr)

            print("[DispatchRunner] Validating task breakdown with AI quorum...", file=sys.stderr)
            
            # Use retry manager for quorum validation if available
            if RETRY_MANAGER_AVAILABLE:
                success, result = await execute_with_circuit_breaker(
                    quorum.validate_intent,
                    "quorum_validation",
                    user_prompt,
                    task_breakdown,
                    manager_name="quorum_validation",
                    config=API_RETRY_CONFIG
                )
                if not success:
                    raise result
            else:
                result = await quorum.validate_intent(user_prompt, task_breakdown)

            print(f"[DispatchRunner] Quorum decision: {result.decision.value} (confidence: {result.confidence:.1%})", file=sys.stderr)

            if result.deficiencies:
                print(f"[DispatchRunner] Deficiencies found: {len(result.deficiencies)}", file=sys.stderr)
                for deficiency in result.deficiencies:
                    print(f"[DispatchRunner]   - {deficiency}", file=sys.stderr)

            quorum_result_dict = {
                "validated": result.decision == ValidationDecision.PASS,
                "decision": result.decision.value,
                "confidence": result.confidence,
                "deficiencies": result.deficiencies,
                "scores": result.scores,
                "model_count": len(result.model_responses),
                "retry_count": retry_count
            }

            # Interactive checkpoint if validator provided
            if validator and INTERACTIVE_AVAILABLE:
                checkpoint_result = validator.checkpoint(
                    checkpoint_id="quorum_validation",
                    checkpoint_type=CheckpointType.TASK_BREAKDOWN,
                    step_number=1,
                    total_steps=4,
                    step_name="Task Breakdown Validation",
                    output_data=task_breakdown,
                    quorum_result=quorum_result_dict,
                    deficiencies=result.deficiencies
                )

                # Handle user choice
                if checkpoint_result.choice == UserChoice.EDIT:
                    # User edited the breakdown
                    task_breakdown = checkpoint_result.modified_output
                    tasks_data = task_breakdown.get('tasks', tasks_data)
                    quorum_result_dict["user_edited"] = True
                    quorum_result_dict["validated"] = True

                elif checkpoint_result.choice == UserChoice.RETRY:
                    # User wants to retry with feedback
                    quorum_result_dict["user_feedback"] = checkpoint_result.user_feedback
                    retry_count += 1
                    if retry_count <= max_retries:
                        print(f"[DispatchRunner] User requested retry with feedback", file=sys.stderr)
                        continue
                    else:
                        print(f"[DispatchRunner] Max retries exceeded, proceeding anyway", file=sys.stderr)

                elif checkpoint_result.choice == UserChoice.SKIP:
                    # User wants to skip validation
                    quorum_result_dict["user_skipped"] = True
                    quorum_result_dict["validated"] = True

            # Check validation result
            decision = result.decision

            if decision == ValidationDecision.FAIL:
                # Critical failure - abort execution
                duration_ms = (time.time() - start_time) * 1000
                print(f"[DispatchRunner] ✗ Phase 1 failed critically in {duration_ms:.0f}ms\n", file=sys.stderr)
                return PhaseResult(
                    phase=phase,
                    phase_name="Quorum Validation",
                    success=False,
                    duration_ms=duration_ms,
                    started_at=started_at,
                    completed_at=datetime.now().isoformat(),
                    error="Task breakdown validation failed critically",
                    output_data=quorum_result_dict,
                    retry_count=retry_count
                )

            elif decision == ValidationDecision.RETRY:
                # Validation suggests retry
                retry_count += 1
                if retry_count <= max_retries:
                    print(f"[DispatchRunner] Quorum suggests retry (attempt {retry_count}/{max_retries})", file=sys.stderr)
                    print("[DispatchRunner] Deficiencies to address:", file=sys.stderr)
                    for deficiency in result.deficiencies:
                        print(f"[DispatchRunner]   - {deficiency}", file=sys.stderr)
                    continue
                else:
                    # Max retries exceeded, log warning but continue
                    print(f"[DispatchRunner] ⚠ Max retries exceeded, proceeding with current breakdown", file=sys.stderr)

            # Validation passed or max retries exceeded
            phase_state.quorum_result = quorum_result_dict

            duration_ms = (time.time() - start_time) * 1000
            if quorum_result_dict.get("validated", False):
                print(f"[DispatchRunner] ✓ Phase 1 completed in {duration_ms:.0f}ms (confidence: {result.confidence:.1%})\n", file=sys.stderr)
            else:
                print(f"[DispatchRunner] ⚠ Phase 1 completed with warnings in {duration_ms:.0f}ms\n", file=sys.stderr)

            result_obj = PhaseResult(
                phase=phase,
                phase_name="Quorum Validation",
                success=quorum_result_dict.get("validated", False),
                duration_ms=duration_ms,
                started_at=started_at,
                completed_at=datetime.now().isoformat(),
                output_data=quorum_result_dict,
                retry_count=retry_count
            )
            try:
                await record_workflow_step(
                    run_id=phase_state.user_prompt[:16] or "run",
                    step_index=1,
                    phase=phase.name,
                    started_at=started_at,
                    completed_at=result_obj.completed_at,
                    duration_ms=duration_ms,
                    success=result_obj.success,
                    error=result_obj.error,
                )
            except Exception:
                pass
            return result_obj

        except Exception as e:
            retry_count += 1
            if retry_count <= max_retries:
                print(f"[DispatchRunner] Quorum validation error: {e}, retrying...", file=sys.stderr)
                continue
            else:
                duration_ms = (time.time() - start_time) * 1000
                print(f"[DispatchRunner] ✗ Phase 1 failed after {max_retries} retries: {e}", file=sys.stderr)
                print(f"[DispatchRunner] Phase 1 completed in {duration_ms:.0f}ms\n", file=sys.stderr)
                return PhaseResult(
                    phase=phase,
                    phase_name="Quorum Validation",
                    success=False,
                    duration_ms=duration_ms,
                    started_at=started_at,
                    completed_at=datetime.now().isoformat(),
                    error=str(e),
                    skipped=True,
                    retry_count=retry_count
                )


async def execute_phase_2_task_architecture(
    user_prompt: str,
    validator: Optional[Any],
    phase_state: PhaseState
) -> PhaseResult:
    """Phase 2: Task breakdown using architect agent.

    Args:
        user_prompt: User's original request to break down
        validator: Optional interactive validator
        phase_state: Current phase state

    Returns:
        PhaseResult with task breakdown
    """
    phase = ExecutionPhase.TASK_PLANNING
    start_time = time.time()
    started_at = datetime.now().isoformat()

    print(f"\n{'='*80}", file=sys.stderr)
    print(f"[DispatchRunner] Phase 2: Task Architecture", file=sys.stderr)
    print(f"[DispatchRunner] Breaking down user request into subtasks...", file=sys.stderr)
    print(f"{'='*80}\n", file=sys.stderr)

    try:
        # Create architect agent
        architect = ArchitectAgent()

        # Create task for architect
        architect_task = AgentTask(
            task_id="architect_breakdown",
            agent_name="agent-architect",
            description="Break down user request into parallel subtasks",
            input_data={
                "user_request": user_prompt,
                "additional_context": ""
            }
        )

        print(f"[DispatchRunner] User Request: {user_prompt[:100]}...", file=sys.stderr)
        print("[DispatchRunner] Invoking architect agent...", file=sys.stderr)

        # Execute architect agent
        result = await architect.execute(architect_task)

        if not result.success:
            raise Exception(result.error or "Architect agent failed")

        # Extract breakdown
        breakdown = result.output_data
        subtasks = breakdown.get('subtasks', [])
        execution_order = breakdown.get('execution_order', 'parallel')
        reasoning = breakdown.get('reasoning', '')
        num_subtasks = breakdown.get('num_subtasks', len(subtasks))

        print(f"[DispatchRunner] ✓ Breakdown complete: {num_subtasks} subtasks ({execution_order})", file=sys.stderr)
        print(f"[DispatchRunner] Reasoning: {reasoning[:150]}...", file=sys.stderr)

        # Interactive checkpoint: Review task breakdown
        if validator and INTERACTIVE_AVAILABLE:
            checkpoint_result = validator.checkpoint(
                checkpoint_id="task_breakdown",
                checkpoint_type=CheckpointType.TASK_BREAKDOWN,
                step_number=1,
                total_steps=4,
                step_name="Task Architecture Breakdown",
                output_data={
                    "user_prompt": user_prompt,
                    "subtasks": subtasks,
                    "execution_order": execution_order,
                    "reasoning": reasoning,
                    "num_subtasks": num_subtasks
                }
            )

            if checkpoint_result.choice == UserChoice.EDIT:
                # User edited the breakdown
                breakdown_edited = checkpoint_result.modified_output
                subtasks = breakdown_edited.get('subtasks', subtasks)
                print("[DispatchRunner] Using user-edited task breakdown", file=sys.stderr)

            elif checkpoint_result.choice == UserChoice.SKIP:
                print("[DispatchRunner] Task breakdown skipped by user", file=sys.stderr)
                duration_ms = (time.time() - start_time) * 1000
                return PhaseResult(
                    phase=phase,
                    phase_name="Task Architecture",
                    success=True,
                    duration_ms=duration_ms,
                    started_at=started_at,
                    completed_at=datetime.now().isoformat(),
                    skipped=True
                )

            elif checkpoint_result.choice == UserChoice.QUIT:
                print("[DispatchRunner] Workflow terminated by user at task breakdown", file=sys.stderr)
                sys.exit(0)

        # Update phase state with breakdown
        phase_state.tasks_data = subtasks

        duration_ms = (time.time() - start_time) * 1000
        print(f"[DispatchRunner] Phase 2 completed in {duration_ms:.0f}ms\n", file=sys.stderr)

        await architect.cleanup()

        result_obj = PhaseResult(
            phase=phase,
            phase_name="Task Architecture",
            success=True,
            duration_ms=duration_ms,
            started_at=started_at,
            completed_at=datetime.now().isoformat(),
            output_data={
                'subtasks': subtasks,
                'num_subtasks': num_subtasks,
                'execution_order': execution_order,
                'reasoning': reasoning,
                'parallel_capable': breakdown.get('parallel_capable', False)
            }
        )
        try:
            await record_workflow_step(
                run_id=phase_state.user_prompt[:16] or "run",
                step_index=2,
                phase=phase.name,
                started_at=started_at,
                completed_at=result_obj.completed_at,
                duration_ms=duration_ms,
                success=True,
            )
        except Exception:
            pass
        return result_obj

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[DispatchRunner] ✗ Phase 2 failed: {e}", file=sys.stderr)
        print(f"[DispatchRunner] Phase 2 completed in {duration_ms:.0f}ms\n", file=sys.stderr)

        return PhaseResult(
            phase=phase,
            phase_name="Task Architecture",
            success=False,
            duration_ms=duration_ms,
            started_at=started_at,
            completed_at=datetime.now().isoformat(),
            error=str(e)
        )


async def execute_phase_4_parallel_execution(
    tasks: List[AgentTask],
    validator: Optional[Any],
    phase_state: PhaseState
) -> PhaseResult:
    """Phase 4: Execute tasks in parallel with coordination.

    Args:
        tasks: List of AgentTask objects to execute
        validator: Optional interactive validator
        phase_state: Current phase state

    Returns:
        PhaseResult with execution results
    """
    phase = ExecutionPhase.PARALLEL_EXECUTION
    start_time = time.time()
    started_at = datetime.now().isoformat()

    print(f"\n{'='*80}", file=sys.stderr)
    print(f"[DispatchRunner] Phase 4: Parallel Execution", file=sys.stderr)
    print(f"[DispatchRunner] Tasks: {len(tasks)}", file=sys.stderr)
    print(f"{'='*80}\n", file=sys.stderr)

    coordinator = ParallelCoordinator()
    lineage = LineageWriter()

    try:
        print(f"[DispatchRunner] Executing {len(tasks)} tasks in parallel...", file=sys.stderr)
        results = await coordinator.execute_parallel(tasks)

        # Interactive checkpoint: Review execution results
        if validator and INTERACTIVE_AVAILABLE:
            successful = sum(1 for r in results.values() if r.success)
            failed = len(results) - successful

            checkpoint_result = validator.checkpoint(
                checkpoint_id="execution_results",
                checkpoint_type=CheckpointType.AGENT_EXECUTION,
                step_number=2,
                total_steps=3,
                step_name=f"Agent Execution Results ({successful} succeeded, {failed} failed)",
                output_data={
                    "summary": {
                        "total_tasks": len(results),
                        "successful": successful,
                        "failed": failed
                    },
                    "results": {
                        task_id: {
                            "agent": result.agent_name,
                            "success": result.success,
                            "error": result.error,
                            "execution_time_ms": result.execution_time_ms
                        }
                        for task_id, result in results.items()
                    }
                }
            )

            if checkpoint_result.choice == UserChoice.RETRY:
                print("[DispatchRunner] User requested retry of agent execution", file=sys.stderr)
                print("[DispatchRunner] Note: Retry of agent execution not yet implemented", file=sys.stderr)

        # Count successes and emit lineage edges per task result (best-effort)
        successful = sum(1 for r in results.values() if r.success)
        failed = len(results) - successful

        try:
            run_id = phase_state.user_prompt[:16] or "run"
            for task_id, result in results.items():
                attrs = {
                    "agent": result.agent_name,
                    "success": result.success,
                    "execution_time_ms": result.execution_time_ms,
                }
                if result.trace_id:
                    attrs["trace_id"] = result.trace_id
                await lineage.emit(LineageEdge(
                    edge_type="EXECUTED",
                    src_type="run",
                    src_id=run_id,
                    dst_type="task",
                    dst_id=task_id,
                    attributes=attrs,
                ))
        except Exception:
            pass

        duration_ms = (time.time() - start_time) * 1000
        print(f"[DispatchRunner] ✓ Phase 4 completed in {duration_ms:.0f}ms ({successful} succeeded, {failed} failed)\n", file=sys.stderr)

        result_obj = PhaseResult(
            phase=phase,
            phase_name="Parallel Execution",
            success=True,
            duration_ms=duration_ms,
            started_at=started_at,
            completed_at=datetime.now().isoformat(),
            output_data={
                'results': {
                    task_id: {
                        'agent_name': result.agent_name,
                        'success': result.success,
                        'execution_time_ms': result.execution_time_ms,
                        'error': result.error,
                        'trace_id': result.trace_id,
                        'output_data': result.output_data
                    }
                    for task_id, result in results.items()
                },
                'summary': {
                    'total_tasks': len(results),
                    'successful': successful,
                    'failed': failed
                }
            }
        )
        try:
            await record_workflow_step(
                run_id=phase_state.user_prompt[:16] or "run",
                step_index=4,
                phase=phase.name,
                started_at=started_at,
                completed_at=result_obj.completed_at,
                duration_ms=duration_ms,
                success=True,
            )
        except Exception:
            pass
        return result_obj

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[DispatchRunner] ✗ Phase 4 failed: {e}", file=sys.stderr)
        print(f"[DispatchRunner] Phase 4 completed in {duration_ms:.0f}ms\n", file=sys.stderr)

        return PhaseResult(
            phase=phase,
            phase_name="Parallel Execution",
            success=False,
            duration_ms=duration_ms,
            started_at=started_at,
            completed_at=datetime.now().isoformat(),
            error=str(e)
        )

    finally:
        await coordinator.cleanup()


# ============================================================================
# Main Entry Point
# ============================================================================

async def main():
    """Main entry point with phase-by-phase control and debugging support."""

    import argparse

    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Parallel agent dispatch runner with phase-level debugging support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Phase Control Examples:
  --only-phase 0              Execute only Phase 0 (context gathering)
  --stop-after-phase 1        Execute Phases 0-1, then stop
  --skip-phases 0,1           Skip Phases 0-1, execute 2-4

  --save-phase-state out.json Save phase state for inspection
  --load-phase-state in.json  Load phase state to resume
        """
    )

    # Feature flags
    parser.add_argument("--enable-context", action="store_true", help="Enable RAG context gathering")
    parser.add_argument("--enable-quorum", action="store_true", help="Enable quorum validation")
    parser.add_argument("--interactive", "-i", action="store_true", help="Enable interactive checkpoints")

    # Phase control flags
    parser.add_argument("--only-phase", type=int, choices=[0, 1, 2, 3, 4],
                       help="Execute only this phase (0-4)")
    parser.add_argument("--stop-after-phase", type=int, choices=[0, 1, 2, 3, 4],
                       help="Stop after completing this phase (0-4)")
    parser.add_argument("--skip-phases", type=str,
                       help="Comma-separated phases to skip (e.g., '0,1')")

    # State management
    parser.add_argument("--save-phase-state", type=str, help="Save phase state to JSON file")
    parser.add_argument("--load-phase-state", type=str, help="Load phase state from JSON file")

    # Input/session management
    parser.add_argument("--resume-session", type=str, help="Resume from saved session file")
    parser.add_argument("--input-file", "-f", type=str, help="Read input from JSON file instead of stdin")
    
    # Logging control
    parser.add_argument("--log-level", choices=["silent", "quiet", "normal", "verbose"], 
                       default="normal", help="Set logging verbosity level")

    args = parser.parse_args()

    # Initialize logging level
    log_level = LogLevel(args.log_level)
    debug_logger.set_level(log_level)

    # Build phase configuration
    skip_phases = []
    if args.skip_phases:
        skip_phases = [int(p.strip()) for p in args.skip_phases.split(',')]

    phase_config = PhaseConfig(
        only_phase=args.only_phase,
        stop_after_phase=args.stop_after_phase,
        skip_phases=skip_phases,
        save_state_file=Path(args.save_phase_state) if args.save_phase_state else None,
        load_state_file=Path(args.load_phase_state) if args.load_phase_state else None
    )

    # Extract feature flags
    enable_context = args.enable_context
    enable_quorum = args.enable_quorum
    enable_interactive = args.interactive
    resume_session_file = Path(args.resume_session) if args.resume_session else None

    # Print phase configuration
    if phase_config.only_phase is not None:
        debug_logger.log_info(f"Executing only Phase {phase_config.only_phase}")
    elif phase_config.stop_after_phase is not None:
        debug_logger.log_info(f"Stopping after Phase {phase_config.stop_after_phase}")
    if skip_phases:
        debug_logger.log_info(f"Skipping phases: {skip_phases}")

    # Create validator
    validator = None
    if enable_interactive and INTERACTIVE_AVAILABLE:
        debug_logger.log_info("Interactive mode enabled")
        validator = create_validator(
            interactive=True,
            session_file=resume_session_file
        )
    elif enable_interactive and not INTERACTIVE_AVAILABLE:
        debug_logger.log_warning("Interactive mode requested but unavailable")

    # Initialize phase state
    phase_state = PhaseState()

    # Load phase state if requested
    if phase_config.load_state_file:
        if phase_config.load_state_file.exists():
            phase_state = PhaseState.load(phase_config.load_state_file)
        else:
            print(f"[DispatchRunner] Warning: Phase state file not found: {phase_config.load_state_file}", file=sys.stderr)

    # Read input from file or stdin
    try:
        if args.input_file:
            print(f"[DispatchRunner] Reading input from file: {args.input_file}", file=sys.stderr)
            with open(args.input_file, 'r') as f:
                input_data = json.load(f)
        else:
            input_data = json.loads(sys.stdin.read())
    except FileNotFoundError as e:
        print(
            json.dumps({
                "success": False,
                "error": f"Input file not found: {args.input_file}"
            }),
            file=sys.stderr
        )
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(
            json.dumps({
                "success": False,
                "error": f"Invalid JSON input: {e}"
            }),
            file=sys.stderr
        )
        sys.exit(1)

    # Parse user prompt and tasks
    user_prompt = input_data.get("user_prompt", "")
    tasks_data = input_data.get("tasks", [])
    
    # Validate and sanitize user input
    if INPUT_VALIDATOR_AVAILABLE:
        try:
            # Validate user prompt
            prompt_result = await validate_and_sanitize(user_prompt, InputType.USER_PROMPT)
            if not prompt_result.is_valid:
                print(f"[DispatchRunner] Input validation failed: {prompt_result.errors}", file=sys.stderr)
                if prompt_result.errors:
                    print(json.dumps({
                        "success": False,
                        "error": "Input validation failed",
                        "validation_errors": prompt_result.errors
                    }))
                    sys.exit(1)
            user_prompt = prompt_result.sanitized_input
            
            # Validate tasks data
            if tasks_data:
                tasks_result = await validate_and_sanitize(tasks_data, InputType.TASK_DATA)
                if not tasks_result.is_valid:
                    print(f"[DispatchRunner] Tasks validation failed: {tasks_result.errors}", file=sys.stderr)
                    if tasks_result.errors:
                        print(json.dumps({
                            "success": False,
                            "error": "Tasks validation failed",
                            "validation_errors": tasks_result.errors
                        }))
                        sys.exit(1)
                tasks_data = tasks_result.sanitized_input
                
        except Exception as e:
            print(f"[DispatchRunner] Input validation error: {e}", file=sys.stderr)
            # Continue without validation if validator fails
    else:
        # Basic sanitization without full validation
        user_prompt = sanitize_prompt(user_prompt) if user_prompt else ""

    # If no tasks provided, Phase 2 (architect) will generate them
    if not tasks_data and not user_prompt:
        print(
            json.dumps({
                "success": False,
                "error": "Must provide either 'user_prompt' (for architect) or 'tasks' (manual breakdown)"
            }),
            file=sys.stderr
        )
        sys.exit(1)

    # Store in phase state
    phase_state.tasks_data = tasks_data
    phase_state.user_prompt = user_prompt

    # Enable architect if no tasks provided
    enable_architect = not tasks_data
    if enable_architect:
        debug_logger.log_info("No tasks provided - architect agent will generate breakdown")

    # ========================================================================
    # STARTUP BANNER
    # ========================================================================

    correlation_id = input_data.get("correlation_id", "N/A")
    workspace_path = input_data.get("workspace_path", "N/A")

    debug_logger.log_startup_banner(
        user_prompt=user_prompt,
        correlation_id=correlation_id,
        workspace_path=workspace_path,
        enable_context=enable_context,
        enable_quorum=enable_quorum,
        enable_interactive=enable_interactive,
        enable_architect=enable_architect,
        phase_config={
            'only_phase': phase_config.only_phase,
            'stop_after_phase': phase_config.stop_after_phase
        }
    )

    # ========================================================================
    # Phase Execution
    # ========================================================================

    context_manager = None
    global_context = None
    quorum_result = None

    # Phase 0: Context Gathering
    if enable_context and phase_config.should_execute_phase(ExecutionPhase.CONTEXT_GATHERING):
        result = await execute_phase_0_context_gathering(
            user_prompt=user_prompt,
            workspace_path=input_data.get("workspace_path"),
            rag_queries=input_data.get("rag_queries", []),
            validator=validator,
            phase_state=phase_state
        )
        phase_state.phases_executed.append(result)
        phase_state.current_phase = 0

        if not result.success and not result.skipped:
            print("[DispatchRunner] Warning: Context gathering failed, continuing without context", file=sys.stderr)
            enable_context = False
        elif result.skipped:
            enable_context = False
        else:
            global_context = phase_state.global_context

        if phase_config.should_stop_after_phase(ExecutionPhase.CONTEXT_GATHERING):
            print("[DispatchRunner] Stopping after Phase 0 as requested", file=sys.stderr)
            if phase_config.save_state_file:
                phase_state.save(phase_config.save_state_file)

            # Output phase results
            print(json.dumps({
                "success": True,
                "phase_results": [p.to_dict() for p in phase_state.phases_executed],
                "stopped_after_phase": 0
            }, indent=2))
            sys.exit(0)

    # Phase 1: Quorum Validation
    if enable_quorum and phase_config.should_execute_phase(ExecutionPhase.QUORUM_VALIDATION):
        result = await execute_phase_1_quorum_validation(
            user_prompt=user_prompt,
            tasks_data=tasks_data,
            validator=validator,
            phase_state=phase_state,
            max_retries=3
        )
        phase_state.phases_executed.append(result)
        phase_state.current_phase = 1

        if not result.success and not result.skipped:
            # Quorum validation failed critically
            print("[DispatchRunner] Critical validation failure, aborting", file=sys.stderr)
            if phase_config.save_state_file:
                phase_state.save(phase_config.save_state_file)

            print(json.dumps({
                "success": False,
                "error": "Quorum validation failed critically",
                "phase_results": [p.to_dict() for p in phase_state.phases_executed]
            }, indent=2))
            sys.exit(1)

        quorum_result = phase_state.quorum_result

        if phase_config.should_stop_after_phase(ExecutionPhase.QUORUM_VALIDATION):
            print("[DispatchRunner] Stopping after Phase 1 as requested", file=sys.stderr)
            if phase_config.save_state_file:
                phase_state.save(phase_config.save_state_file)

            print(json.dumps({
                "success": True,
                "phase_results": [p.to_dict() for p in phase_state.phases_executed],
                "stopped_after_phase": 1,
                "quorum_result": quorum_result
            }, indent=2))
            sys.exit(0)

    # Phase 2: Task Architecture
    if enable_architect and phase_config.should_execute_phase(ExecutionPhase.TASK_PLANNING):
        result = await execute_phase_2_task_architecture(
            user_prompt=user_prompt,
            validator=validator,
            phase_state=phase_state
        )
        phase_state.phases_executed.append(result)
        phase_state.current_phase = 2

        if not result.success and not result.skipped:
            print("[DispatchRunner] Task architecture failed, aborting", file=sys.stderr)
            if phase_config.save_state_file:
                phase_state.save(phase_config.save_state_file)

            print(json.dumps({
                "success": False,
                "error": "Task architecture failed",
                "phase_results": [p.to_dict() for p in phase_state.phases_executed]
            }, indent=2))
            sys.exit(1)

        # Update tasks_data with architect's breakdown
        if not result.skipped:
            tasks_data = phase_state.tasks_data
            print(f"[DispatchRunner] Task breakdown updated: {len(tasks_data)} subtasks", file=sys.stderr)

        if phase_config.should_stop_after_phase(ExecutionPhase.TASK_PLANNING):
            print("[DispatchRunner] Stopping after Phase 2 as requested", file=sys.stderr)
            if phase_config.save_state_file:
                phase_state.save(phase_config.save_state_file)

            print(json.dumps({
                "success": True,
                "phase_results": [p.to_dict() for p in phase_state.phases_executed],
                "stopped_after_phase": 2,
                "tasks_breakdown": tasks_data
            }, indent=2))
            sys.exit(0)

    # Phase 3: Context Filtering
    if phase_config.should_execute_phase(ExecutionPhase.CONTEXT_FILTERING):
        # Convert tasks and apply context filtering
        tasks = []

        for task_data in tasks_data:
            try:
                # Map agent name from architect's generic names to actual agent implementations
                agent_name_mapping = {
                    "coder": "agent-contract-driven-generator",
                    "debug": "agent-debug-intelligence",
                    "debugger": "agent-debug-intelligence",
                    # Map research/analysis tasks to coder for now (they can generate code/docs)
                    "researcher": "agent-contract-driven-generator",
                    "analyzer": "agent-contract-driven-generator",
                    # Map validation to debug intelligence (can analyze and validate)
                    "validator": "agent-debug-intelligence"
                }
                agent_name = agent_name_mapping.get(task_data.get("agent"), task_data.get("agent"))

                # Filter context for this task (if enabled)
                input_data_with_context = task_data.get("input_data", {}).copy()

                if enable_context and context_manager and global_context:
                    context_requirements = task_data.get("context_requirements", [])

                    if context_requirements:
                        print(
                            f"[DispatchRunner] Phase 3: Filtering context for task {task_data['task_id']}: "
                            f"{len(context_requirements)} requirements",
                            file=sys.stderr
                        )

                        # Create context manager if needed
                        if context_manager is None:
                            context_manager = ContextManager()

                        filtered_context = context_manager.filter_context(
                            context_requirements=context_requirements,
                            max_tokens=5000
                        )

                        input_data_with_context["pre_gathered_context"] = filtered_context

                        print(
                            f"[DispatchRunner] Task {task_data['task_id']}: "
                            f"{len(filtered_context)} context items attached",
                            file=sys.stderr
                        )

                task = AgentTask(
                    task_id=task_data["task_id"],
                    description=task_data["description"],
                    agent_name=agent_name,
                    input_data=input_data_with_context,
                    dependencies=task_data.get("dependencies", [])
                )
                tasks.append(task)

            except Exception as e:
                print(
                    json.dumps({
                        "success": False,
                        "error": f"Error parsing task {task_data.get('task_id', 'unknown')}: {e}"
                    }),
                    file=sys.stderr
                )
                sys.exit(1)

        if phase_config.should_stop_after_phase(ExecutionPhase.CONTEXT_FILTERING):
            print("[DispatchRunner] Stopping after Phase 3 as requested", file=sys.stderr)
            if phase_config.save_state_file:
                phase_state.save(phase_config.save_state_file)

            print(json.dumps({
                "success": True,
                "phase_results": [p.to_dict() for p in phase_state.phases_executed],
                "stopped_after_phase": 3,
                "tasks_prepared": len(tasks)
            }, indent=2))
            sys.exit(0)

    # Phase 4: Parallel Execution
    if phase_config.should_execute_phase(ExecutionPhase.PARALLEL_EXECUTION):
        # Print task dispatch banner
        print("\n" + "="*80)
        print(f"DISPATCHING {len(tasks)} TASKS TO AGENTS")
        print("="*80)
        for i, task in enumerate(tasks, 1):
            agent_display = task.agent_name.replace("agent-", "").replace("-", " ").title()
            print(f"\n  Task {i}: {task.task_id}")
            print(f"    Agent: {agent_display}")
            print(f"    Description: {task.description[:100]}{'...' if len(task.description) > 100 else ''}")
            if task.dependencies:
                print(f"    Dependencies: {', '.join(task.dependencies)}")
        print("\n" + "="*80)
        print("EXECUTING IN PARALLEL")
        print("="*80 + "\n")
        sys.stdout.flush()

        result = await execute_phase_4_parallel_execution(
            tasks=tasks,
            validator=validator,
            phase_state=phase_state
        )
        phase_state.phases_executed.append(result)
        phase_state.current_phase = 4

        if not result.success:
            print("[DispatchRunner] Parallel execution failed", file=sys.stderr)
            if phase_config.save_state_file:
                phase_state.save(phase_config.save_state_file)

            print(json.dumps({
                "success": False,
                "error": "Parallel execution failed",
                "phase_results": [p.to_dict() for p in phase_state.phases_executed]
            }, indent=2))
            sys.exit(1)

    # ========================================================================
    # Final Compilation
    # ========================================================================

    # Build final output
    output = {
        "success": True,
        "phase_results": [p.to_dict() for p in phase_state.phases_executed],
        "results": [],
        "context_filtering_enabled": enable_context,
        "quorum_validation_enabled": enable_quorum,
        "interactive_mode_enabled": enable_interactive
    }

    # Add phase timing summary
    total_duration = sum(p.duration_ms for p in phase_state.phases_executed)
    output["timing_summary"] = {
        "total_duration_ms": total_duration,
        "phases": [
            {
                "phase": p.phase.name,
                "duration_ms": p.duration_ms,
                "success": p.success,
                "skipped": p.skipped
            }
            for p in phase_state.phases_executed
        ]
    }

    if enable_context and context_manager:
        output["context_summary"] = context_manager.get_context_summary()

    if enable_quorum and quorum_result:
        output["quorum_validation"] = quorum_result

    # Extract execution results from Phase 4
    for phase_result in phase_state.phases_executed:
        if phase_result.phase == ExecutionPhase.PARALLEL_EXECUTION and phase_result.success:
            results_data = phase_result.output_data.get('results', {})
            for task_id, result_data in results_data.items():
                output["results"].append({
                    "task_id": task_id,
                    "agent_name": result_data['agent_name'],
                    "success": result_data['success'],
                    "output_data": result_data.get('output_data', {}),
                    "error": result_data.get('error'),
                    "execution_time_ms": result_data['execution_time_ms'],
                    "trace_id": result_data.get('trace_id')
                })

    # Interactive checkpoint: Review final compilation
    if validator and INTERACTIVE_AVAILABLE:
        checkpoint_result = validator.checkpoint(
            checkpoint_id="final_compilation",
            checkpoint_type=CheckpointType.FINAL_COMPILATION,
            step_number=3,
            total_steps=3,
            step_name="Final Result Compilation",
            output_data=output
        )

        if checkpoint_result.choice == UserChoice.EDIT:
            output = checkpoint_result.modified_output
            print("[DispatchRunner] Using user-edited final output", file=sys.stderr)

    # Save phase state if requested
    if phase_config.save_state_file:
        phase_state.save(phase_config.save_state_file)

    # Print results to stdout
    print(json.dumps(output, indent=2))

    # Cleanup
    if context_manager:
        await context_manager.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
