"""
FSM (Finite State Machine) state models for Intelligent Context Proxy.

The FSM tracks workflow state through the following states:
- idle → request_received → intelligence_queried → context_rewritten → completed
- Any state can transition to 'failed' on error

This module provides:
- FSMState: State data model
- FSMTransition: Transition history record
- FSMStateManager: State machine logic and validation
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class WorkflowState(str, Enum):
    """Valid workflow states for the FSM."""

    IDLE = "idle"
    REQUEST_RECEIVED = "request_received"
    INTELLIGENCE_QUERIED = "intelligence_queried"
    CONTEXT_REWRITTEN = "context_rewritten"
    COMPLETED = "completed"
    FAILED = "failed"


class FSMTrigger(str, Enum):
    """FSM triggers that cause state transitions."""

    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    INTELLIGENCE_QUERIED = "INTELLIGENCE_QUERIED"
    CONTEXT_REWRITTEN = "CONTEXT_REWRITTEN"
    ANTHROPIC_FORWARDED = "ANTHROPIC_FORWARDED"
    ERROR = "ERROR"


class FSMTransition(BaseModel):
    """
    Record of a single FSM state transition.

    Tracks: from_state → to_state, trigger, timestamp, metadata
    """

    from_state: WorkflowState = Field(..., description="State before transition")
    to_state: WorkflowState = Field(..., description="State after transition")
    trigger: FSMTrigger = Field(..., description="Trigger that caused transition")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 timestamp",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    model_config = {
        "extra": "ignore",
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "from_state": "idle",
                "to_state": "request_received",
                "trigger": "REQUEST_RECEIVED",
                "timestamp": "2025-11-09T14:30:00Z",
                "metadata": {},
            }
        },
    }


class FSMState(BaseModel):
    """
    FSM state data model.

    Tracks current state, previous state, transition count, and timestamps.
    """

    workflow_id: str = Field(..., description="Correlation ID / workflow ID")
    current_state: WorkflowState = Field(
        default=WorkflowState.IDLE, description="Current FSM state"
    )
    previous_state: Optional[WorkflowState] = Field(None, description="Previous FSM state")
    transition_count: int = Field(default=0, description="Number of transitions")
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="Creation timestamp",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="Last update timestamp",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    model_config = {
        "extra": "ignore",
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "workflow_id": "abc-123",
                "current_state": "request_received",
                "previous_state": "idle",
                "transition_count": 1,
                "created_at": "2025-11-09T14:30:00Z",
                "updated_at": "2025-11-09T14:30:01Z",
                "metadata": {},
            }
        },
    }


class FSMStateManager:
    """
    FSM state manager with validation and transition logic.

    Provides:
    - State transition validation (ensures valid transitions only)
    - In-memory state cache (correlation_id → FSMState)
    - Transition history tracking
    - Query methods for Orchestrator
    """

    # Valid state transitions
    VALID_TRANSITIONS: Dict[WorkflowState, List[WorkflowState]] = {
        WorkflowState.IDLE: [WorkflowState.REQUEST_RECEIVED, WorkflowState.FAILED],
        WorkflowState.REQUEST_RECEIVED: [
            WorkflowState.INTELLIGENCE_QUERIED,
            WorkflowState.FAILED,
        ],
        WorkflowState.INTELLIGENCE_QUERIED: [
            WorkflowState.CONTEXT_REWRITTEN,
            WorkflowState.FAILED,
        ],
        WorkflowState.CONTEXT_REWRITTEN: [WorkflowState.COMPLETED, WorkflowState.FAILED],
        WorkflowState.COMPLETED: [],
        WorkflowState.FAILED: [],
    }

    # Trigger → State mapping
    TRIGGER_TO_STATE: Dict[FSMTrigger, WorkflowState] = {
        FSMTrigger.REQUEST_RECEIVED: WorkflowState.REQUEST_RECEIVED,
        FSMTrigger.INTELLIGENCE_QUERIED: WorkflowState.INTELLIGENCE_QUERIED,
        FSMTrigger.CONTEXT_REWRITTEN: WorkflowState.CONTEXT_REWRITTEN,
        FSMTrigger.ANTHROPIC_FORWARDED: WorkflowState.COMPLETED,
        FSMTrigger.ERROR: WorkflowState.FAILED,
    }

    def __init__(self):
        """Initialize FSM state manager."""
        # In-memory state cache: correlation_id → FSMState
        self._state_cache: Dict[str, FSMState] = {}

        # Transition history: correlation_id → List[FSMTransition]
        self._transition_history: Dict[str, List[FSMTransition]] = {}

    def initialize_workflow(self, workflow_id: str, metadata: Optional[Dict] = None) -> FSMState:
        """
        Initialize a new workflow with FSM state.

        Args:
            workflow_id: Correlation ID / workflow ID
            metadata: Optional metadata

        Returns:
            Initial FSM state (idle)
        """
        if workflow_id in self._state_cache:
            # Already initialized
            return self._state_cache[workflow_id]

        # Create initial state
        state = FSMState(
            workflow_id=workflow_id,
            current_state=WorkflowState.IDLE,
            previous_state=None,
            transition_count=0,
            metadata=metadata or {},
        )

        # Cache state
        self._state_cache[workflow_id] = state
        self._transition_history[workflow_id] = []

        return state

    def transition(
        self, workflow_id: str, trigger: FSMTrigger, metadata: Optional[Dict] = None
    ) -> bool:
        """
        Attempt FSM state transition.

        Args:
            workflow_id: Correlation ID / workflow ID
            trigger: FSM trigger
            metadata: Optional metadata for transition

        Returns:
            True if transition successful, False if invalid

        Raises:
            ValueError: If workflow not initialized
        """
        # Get current state
        if workflow_id not in self._state_cache:
            raise ValueError(f"Workflow {workflow_id} not initialized")

        state = self._state_cache[workflow_id]

        # Determine target state from trigger
        target_state = self.TRIGGER_TO_STATE.get(trigger)
        if not target_state:
            return False

        # Validate transition
        if not self._is_valid_transition(state.current_state, target_state):
            return False

        # Record transition
        transition = FSMTransition(
            from_state=state.current_state,
            to_state=target_state,
            trigger=trigger,
            metadata=metadata or {},
        )

        # Update state
        state.previous_state = state.current_state
        state.current_state = target_state
        state.transition_count += 1
        state.updated_at = datetime.now(UTC).isoformat()

        # Update metadata
        if metadata:
            state.metadata.update(metadata)

        # Record transition history
        self._transition_history[workflow_id].append(transition)

        return True

    def get_state(self, workflow_id: str) -> Optional[WorkflowState]:
        """
        Get current FSM state for workflow.

        Args:
            workflow_id: Correlation ID / workflow ID

        Returns:
            Current state or None if not found
        """
        state = self._state_cache.get(workflow_id)
        return state.current_state if state else None

    def get_full_state(self, workflow_id: str) -> Optional[FSMState]:
        """
        Get full FSM state object for workflow.

        Args:
            workflow_id: Correlation ID / workflow ID

        Returns:
            FSMState object or None if not found
        """
        return self._state_cache.get(workflow_id)

    def get_transition_history(self, workflow_id: str) -> List[FSMTransition]:
        """
        Get FSM transition history for workflow.

        Args:
            workflow_id: Correlation ID / workflow ID

        Returns:
            List of transitions (chronological order)
        """
        return self._transition_history.get(workflow_id, [])

    def clear_workflow(self, workflow_id: str) -> None:
        """
        Clear FSM state for workflow (cleanup).

        Args:
            workflow_id: Correlation ID / workflow ID
        """
        self._state_cache.pop(workflow_id, None)
        self._transition_history.pop(workflow_id, None)

    def _is_valid_transition(
        self, from_state: WorkflowState, to_state: WorkflowState
    ) -> bool:
        """
        Check if state transition is valid.

        Args:
            from_state: Current state
            to_state: Target state

        Returns:
            True if transition is valid
        """
        valid_targets = self.VALID_TRANSITIONS.get(from_state, [])
        return to_state in valid_targets

    def get_workflow_count(self) -> int:
        """Get count of active workflows."""
        return len(self._state_cache)

    def get_all_workflows(self) -> List[str]:
        """Get list of all workflow IDs."""
        return list(self._state_cache.keys())
