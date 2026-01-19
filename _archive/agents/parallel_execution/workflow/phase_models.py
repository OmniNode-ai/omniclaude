"""
Phase Control Models for Workflow Execution

Defines data structures for phase-by-phase workflow control including:
- ExecutionPhase enum
- PhaseConfig for phase execution control
- PhaseResult for phase execution outcomes
- PhaseState for workflow state persistence
"""

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


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

    only_phase: int | None = None  # Execute only this phase
    stop_after_phase: int | None = None  # Stop after completing this phase
    skip_phases: list[int] = field(default_factory=list)  # Skip these phases
    save_state_file: Path | None = None  # Save phase state to file
    load_state_file: Path | None = None  # Load phase state from file

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
    output_data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    skipped: bool = False
    retry_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = asdict(self)
        result["phase"] = self.phase.name
        return result


@dataclass
class PhaseState:
    """Complete phase execution state for persistence."""

    phases_executed: list[PhaseResult] = field(default_factory=list)
    current_phase: int | None = None
    global_context: dict[str, Any] | None = None
    quorum_result: dict[str, Any] | None = None
    tasks_data: list[dict[str, Any]] = field(default_factory=list)
    user_prompt: str = ""

    def save(self, path: Path) -> None:
        """Save state to JSON file."""
        with open(path, "w") as f:
            data = {
                "phases_executed": [p.to_dict() for p in self.phases_executed],
                "current_phase": self.current_phase,
                "global_context": self.global_context,
                "quorum_result": self.quorum_result,
                "tasks_data": self.tasks_data,
                "user_prompt": self.user_prompt,
                "saved_at": datetime.now().isoformat(),
            }
            json.dump(data, f, indent=2)
        print(f"[DispatchRunner] Phase state saved to: {path}", file=sys.stderr)

    @classmethod
    def load(cls, path: Path) -> "PhaseState":
        """Load state from JSON file."""
        with open(path) as f:
            data = json.load(f)

        # Reconstruct PhaseResult objects
        phases_executed = []
        for p in data.get("phases_executed", []):
            phase_result = PhaseResult(
                phase=ExecutionPhase[p["phase"]],
                phase_name=p["phase_name"],
                success=p["success"],
                duration_ms=p["duration_ms"],
                started_at=p["started_at"],
                completed_at=p["completed_at"],
                output_data=p.get("output_data", {}),
                error=p.get("error"),
                skipped=p.get("skipped", False),
                retry_count=p.get("retry_count", 0),
            )
            phases_executed.append(phase_result)

        print(f"[DispatchRunner] Phase state loaded from: {path}", file=sys.stderr)
        return cls(
            phases_executed=phases_executed,
            current_phase=data.get("current_phase"),
            global_context=data.get("global_context"),
            quorum_result=data.get("quorum_result"),
            tasks_data=data.get("tasks_data", []),
            user_prompt=data.get("user_prompt", ""),
        )
