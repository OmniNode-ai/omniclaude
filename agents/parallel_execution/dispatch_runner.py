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
import logging
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# Pydantic imports for handling typed agent outputs
try:
    from pydantic import BaseModel
    PYDANTIC_AVAILABLE = True
except ImportError:
    BaseModel = None
    PYDANTIC_AVAILABLE = False

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Configure logging to write to both stderr and file
log_file = Path("/tmp/logging_implementation_coord.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, mode='a'),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)
logger.info("[DispatchRunner] Logging initialized, output saved to: %s", log_file)

from agent_dispatcher import ParallelCoordinator
from agent_model import AgentTask, AgentConfig
from context_manager import ContextManager
from agent_architect import ArchitectAgent
from agent_registry import agent_exists, get_agent_module_name

# Import all agents to trigger self-registration via decorators
# This ensures agents register themselves when dispatch_runner loads
logger.info("[AgentImport] Starting agent module imports...")
try:
    logger.info("[AgentImport] Importing agent_analyzer...")
    import agent_analyzer
    logger.info("[AgentImport] Successfully imported agent_analyzer")
except ImportError as e:
    logger.error("[AgentImport] Failed to import agent_analyzer: %s", e)

try:
    logger.info("[AgentImport] Importing agent_researcher...")
    import agent_researcher
    logger.info("[AgentImport] Successfully imported agent_researcher")
except ImportError as e:
    logger.error("[AgentImport] Failed to import agent_researcher: %s", e)

try:
    logger.info("[AgentImport] Importing agent_validator...")
    import agent_validator
    logger.info("[AgentImport] Successfully imported agent_validator")
except ImportError as e:
    logger.error("[AgentImport] Failed to import agent_validator: %s", e)

try:
    logger.info("[AgentImport] Importing agent_debug_intelligence...")
    import agent_debug_intelligence
    logger.info("[AgentImport] Successfully imported agent_debug_intelligence")
except ImportError as e:
    logger.error("[AgentImport] Failed to import agent_debug_intelligence: %s", e)

logger.info("[AgentImport] Agent module imports completed")

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
# Phase Control Models
# ============================================================================

class ExecutionPhase(Enum):
    """Workflow execution phases with numeric ordering."""
    CONTEXT_GATHERING = 0
    QUORUM_VALIDATION = 1
    TASK_PLANNING = 2
    CONTEXT_FILTERING = 3
    PARALLEL_EXECUTION = 4


@dataclass
class PhaseConfig:
    """Configuration for phase execution control."""

    only_phase: Optional[int] = None  # Execute only this phase
    stop_after_phase: Optional[int] = None  # Stop after completing this phase
    skip_phases: List[int] = field(default_factory=list)  # Skip these phases
    save_state_file: Optional[Path] = None  # Save phase state to file
    load_state_file: Optional[Path] = None  # Load phase state from file

    def should_execute_phase(self, phase: ExecutionPhase) -> bool:
        """Check if a phase should be executed based on configuration."""
        phase_num = phase.value

        # Check skip list
        if phase_num in self.skip_phases:
            return False

        # Check only_phase constraint
        if self.only_phase is not None:
            return phase_num == self.only_phase

        # Check stop_after_phase constraint (execute up to and including the phase)
        if self.stop_after_phase is not None:
            return phase_num <= self.stop_after_phase

        return True

    def should_stop_after_phase(self, phase: ExecutionPhase) -> bool:
        """Check if execution should stop after this phase."""
        phase_num = phase.value

        # Stop if this is the only_phase
        if self.only_phase is not None and phase_num == self.only_phase:
            return True

        # Stop if this is the stop_after_phase
        if self.stop_after_phase is not None and phase_num == self.stop_after_phase:
            return True

        return False


@dataclass
class PhaseResult:
    """Result from executing a single phase."""

    phase: ExecutionPhase
    phase_name: str
    success: bool
    duration_ms: float
    started_at: str
    completed_at: str
    output_data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    skipped: bool = False
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = asdict(self)
        result['phase'] = self.phase.name
        return result


@dataclass
class PhaseState:
    """Complete phase execution state for persistence."""

    phases_executed: List[PhaseResult] = field(default_factory=list)
    current_phase: Optional[int] = None
    global_context: Optional[Dict[str, Any]] = None
    quorum_result: Optional[Dict[str, Any]] = None
    tasks_data: List[Dict[str, Any]] = field(default_factory=list)
    user_prompt: str = ""

    def save(self, path: Path) -> None:
        """Save state to JSON file."""
        with open(path, 'w') as f:
            data = {
                'phases_executed': [p.to_dict() for p in self.phases_executed],
                'current_phase': self.current_phase,
                'global_context': self.global_context,
                'quorum_result': self.quorum_result,
                'tasks_data': self.tasks_data,
                'user_prompt': self.user_prompt,
                'saved_at': datetime.now().isoformat()
            }
            json.dump(data, f, indent=2)
        print(f"[DispatchRunner] Phase state saved to: {path}", file=sys.stderr)

    @classmethod
    def load(cls, path: Path) -> 'PhaseState':
        """Load state from JSON file."""
        with open(path, 'r') as f:
            data = json.load(f)

        # Reconstruct PhaseResult objects
        phases_executed = []
        for p in data.get('phases_executed', []):
            phase_result = PhaseResult(
                phase=ExecutionPhase[p['phase']],
                phase_name=p['phase_name'],
                success=p['success'],
                duration_ms=p['duration_ms'],
                started_at=p['started_at'],
                completed_at=p['completed_at'],
                output_data=p.get('output_data', {}),
                error=p.get('error'),
                skipped=p.get('skipped', False),
                retry_count=p.get('retry_count', 0)
            )
            phases_executed.append(phase_result)

        print(f"[DispatchRunner] Phase state loaded from: {path}", file=sys.stderr)
        return cls(
            phases_executed=phases_executed,
            current_phase=data.get('current_phase'),
            global_context=data.get('global_context'),
            quorum_result=data.get('quorum_result'),
            tasks_data=data.get('tasks_data', []),
            user_prompt=data.get('user_prompt', '')
        )


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

    print(f"\n{'='*80}", file=sys.stderr)
    print(f"[DispatchRunner] Phase 0: Context Gathering", file=sys.stderr)
    print(f"[DispatchRunner] Queries: {len(rag_queries)}", file=sys.stderr)
    print(f"{'='*80}\n", file=sys.stderr)

    try:
        context_manager = ContextManager()

        print("[DispatchRunner] Gathering global context...", file=sys.stderr)
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
        print(f"[DispatchRunner] Phase 0 completed in {duration_ms:.0f}ms\n", file=sys.stderr)

        return PhaseResult(
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

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[DispatchRunner] ✗ Phase 0 failed: {e}", file=sys.stderr)
        print(f"[DispatchRunner] Phase 0 completed in {duration_ms:.0f}ms\n", file=sys.stderr)

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

            return PhaseResult(
                phase=phase,
                phase_name="Quorum Validation",
                success=quorum_result_dict.get("validated", False),
                duration_ms=duration_ms,
                started_at=started_at,
                completed_at=datetime.now().isoformat(),
                output_data=quorum_result_dict,
                retry_count=retry_count
            )

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

        return PhaseResult(
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

    try:
        print(f"[DispatchRunner] Executing {len(tasks)} tasks in parallel...", file=sys.stderr)

        # Log execution start for each task
        for task in tasks:
            agent_name = getattr(task, 'agent_name', 'unknown-agent')
            logger.info("[AgentExecution] Starting: %s for task '%s'", agent_name, task.task_id)
            logger.info("[AgentExecution] Task: '%s'", task.description)

        execution_start = time.time()
        results = await coordinator.execute_parallel(tasks)
        execution_duration = (time.time() - execution_start) * 1000

        # Log execution completion for each task
        for task_id, result in results.items():
            logger.info(
                "[AgentExecution] Completed: %s (success=%s, time=%.1fms)",
                result.agent_name, result.success, result.execution_time_ms
            )
            if not result.success and result.error:
                logger.error("[AgentExecution] Error for task '%s': %s", task_id, result.error)

        # Automatic code extraction from debug agent outputs
        # Supports both Pydantic AI typed outputs (BaseModel) and legacy JSON (dict)
        for task_id, result in results.items():
            if result.success and result.agent_name == "agent-debug-intelligence":
                try:
                    # Extract fixed code - support both Pydantic BaseModel and JSON dict
                    output_data = result.output_data
                    fixed_code = None
                    extraction_method = None

                    # Method 1: Pydantic BaseModel with typed attributes
                    if PYDANTIC_AVAILABLE and isinstance(output_data, BaseModel):
                        # Check for solution.fixed_code using attribute access
                        if hasattr(output_data, "solution"):
                            solution = output_data.solution
                            if hasattr(solution, "fixed_code"):
                                fixed_code = solution.fixed_code
                                extraction_method = "Pydantic BaseModel (solution.fixed_code)"

                        print(
                            f"[DispatchRunner] Pydantic extraction for {task_id}: "
                            f"{'found' if fixed_code else 'no fixed_code attribute'}",
                            file=sys.stderr
                        )

                    # Method 2: Legacy JSON dict with nested keys
                    elif isinstance(output_data, dict):
                        solution = output_data.get("solution", {})
                        fixed_code = solution.get("fixed_code") if isinstance(solution, dict) else None
                        extraction_method = "JSON dict (solution.fixed_code)" if fixed_code else None

                        print(
                            f"[DispatchRunner] JSON extraction for {task_id}: "
                            f"{'found' if fixed_code else 'no fixed_code key'}",
                            file=sys.stderr
                        )

                    # Method 3: Handle None or unexpected types gracefully
                    else:
                        output_type = type(output_data).__name__ if output_data is not None else "None"
                        print(
                            f"[DispatchRunner] Skipping {task_id}: "
                            f"output_data is {output_type}, expected BaseModel or dict",
                            file=sys.stderr
                        )

                    if fixed_code:
                        # Find the corresponding task to get output file info
                        task = next((t for t in tasks if t.task_id == task_id), None)
                        if not task:
                            print(
                                f"[DispatchRunner] Warning: Task {task_id} not found for code extraction",
                                file=sys.stderr
                            )
                            continue

                        # Determine output file path
                        input_data = task.input_data or {}
                        output_files = input_data.get("output_files", [])
                        target_directory = input_data.get("target_directory", ".")

                        if output_files and len(output_files) > 0:
                            output_file = Path(target_directory) / output_files[0]
                        else:
                            # Fallback: use task_id as filename
                            output_file = Path(target_directory) / f"agent_{task_id}.py"

                        # Ensure directory exists
                        output_file.parent.mkdir(parents=True, exist_ok=True)

                        # Write the extracted code
                        output_file.write_text(fixed_code, encoding="utf-8")

                        print(
                            f"[DispatchRunner] ✓ Code extracted from {task_id} using {extraction_method}: {output_file}",
                            file=sys.stderr
                        )

                        # Update result metadata - preserve BaseModel or create dict
                        if isinstance(output_data, dict):
                            result.output_data["_code_extracted"] = True
                            result.output_data["_extracted_file"] = str(output_file)
                            result.output_data["_extraction_method"] = extraction_method
                        else:
                            # For BaseModel, store metadata separately to avoid mutating the model
                            if not hasattr(result, "_extraction_metadata"):
                                result._extraction_metadata = {}
                            result._extraction_metadata["code_extracted"] = True
                            result._extraction_metadata["extracted_file"] = str(output_file)
                            result._extraction_metadata["extraction_method"] = extraction_method

                except Exception as e:
                    print(
                        f"[DispatchRunner] Warning: Failed to extract code from {task_id}: {e}",
                        file=sys.stderr
                    )

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

        # Count successes
        successful = sum(1 for r in results.values() if r.success)
        failed = len(results) - successful

        duration_ms = (time.time() - start_time) * 1000
        print(f"[DispatchRunner] ✓ Phase 4 completed in {duration_ms:.0f}ms ({successful} succeeded, {failed} failed)\n", file=sys.stderr)

        return PhaseResult(
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

    args = parser.parse_args()

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
        print(f"[DispatchRunner] Executing only Phase {phase_config.only_phase}", file=sys.stderr)
    elif phase_config.stop_after_phase is not None:
        print(f"[DispatchRunner] Stopping after Phase {phase_config.stop_after_phase}", file=sys.stderr)
    if skip_phases:
        print(f"[DispatchRunner] Skipping phases: {skip_phases}", file=sys.stderr)

    # Create validator
    validator = None
    if enable_interactive and INTERACTIVE_AVAILABLE:
        print("[DispatchRunner] Interactive mode enabled", file=sys.stderr)
        validator = create_validator(
            interactive=True,
            session_file=resume_session_file
        )
    elif enable_interactive and not INTERACTIVE_AVAILABLE:
        print("[DispatchRunner] Warning: Interactive mode requested but unavailable", file=sys.stderr)

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
        print("[DispatchRunner] No tasks provided - architect agent will generate breakdown", file=sys.stderr)

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
                # Use dynamic agent registry to check if agent exists, with intelligent fallbacks
                requested_agent = task_data.get("agent", "")
                task_id = task_data.get("task_id", "unknown")

                logger.info("[AgentSelection] Requested agent: '%s' for task '%s'", requested_agent, task_id)

                # Static mappings for known aliases
                agent_alias_mapping = {
                    "coder": "contract-driven-generator",
                    "debug": "debug-intelligence",
                    "debugger": "debug-intelligence",
                }

                # Resolve alias first
                agent_base_name = agent_alias_mapping.get(requested_agent, requested_agent)
                if requested_agent in agent_alias_mapping:
                    logger.info("[AgentSelection] Agent alias resolved: '%s' -> '%s'", requested_agent, agent_base_name)

                # Check if the agent exists in the registry
                logger.info("[AgentSelection] Checking if agent exists: %s", agent_base_name)
                agent_exists_result = agent_exists(agent_base_name)
                logger.info("[AgentSelection] agent_exists('%s') = %s", agent_base_name, agent_exists_result)

                if agent_exists_result:
                    # Agent exists, use it
                    agent_name = f"agent-{agent_base_name}"
                    logger.info("[AgentSelection] Selected agent: '%s' (from registry)", agent_name)
                    logger.info("[AgentSelection] Fallback: False")
                    agent_metadata = {"agent_source": "registry", "fallback_used": False}
                else:
                    # Agent doesn't exist, use intelligent fallback
                    logger.warning(
                        "[AgentSelection] Agent '%s' not found in registry. Using fallback for task '%s'",
                        agent_base_name, task_id
                    )
                    print(
                        f"[DispatchRunner] Warning: Agent '{agent_base_name}' not found in registry. "
                        f"Using fallback for task {task_id}",
                        file=sys.stderr
                    )

                    # Fallback logic based on task type
                    if agent_base_name in ["researcher", "analyzer"]:
                        # Research/analysis tasks - use coder for now (can generate docs)
                        agent_name = "agent-contract-driven-generator"
                        fallback_reason = "research/analysis tasks mapped to coder temporarily"
                    elif agent_base_name in ["validator"]:
                        # Validation tasks - use debug intelligence (can analyze)
                        agent_name = "agent-debug-intelligence"
                        fallback_reason = "validation tasks mapped to debug temporarily"
                    else:
                        # Default fallback to coder
                        agent_name = "agent-contract-driven-generator"
                        fallback_reason = "unknown agent type defaulted to coder"

                    logger.info("[AgentSelection] Selected agent: '%s' (fallback)", agent_name)
                    logger.info("[AgentSelection] Fallback: True - Reason: %s", fallback_reason)

                    agent_metadata = {
                        "agent_source": "fallback",
                        "fallback_used": True,
                        "requested_agent": requested_agent,
                        "fallback_reason": fallback_reason
                    }

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

                # Add agent metadata to input_data for tracking
                input_data_with_context["_agent_metadata"] = agent_metadata

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
