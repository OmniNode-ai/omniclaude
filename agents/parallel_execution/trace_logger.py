"""
Trace Logger for Agent Execution Tracking

Provides file-based tracing for all agent operations with structured logging.
Later can be migrated to database storage.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from enum import Enum
import asyncio


class TraceLevel(str, Enum):
    """Trace event severity levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class TraceEventType(str, Enum):
    """Types of trace events."""
    AGENT_START = "AGENT_START"
    AGENT_END = "AGENT_END"
    AGENT_ERROR = "AGENT_ERROR"
    COORDINATOR_START = "COORDINATOR_START"
    COORDINATOR_END = "COORDINATOR_END"
    TASK_ASSIGNED = "TASK_ASSIGNED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    PARALLEL_BATCH_START = "PARALLEL_BATCH_START"
    PARALLEL_BATCH_END = "PARALLEL_BATCH_END"
    DEPENDENCY_WAIT = "DEPENDENCY_WAIT"
    DEPENDENCY_MET = "DEPENDENCY_MET"


class TraceEvent(BaseModel):
    """Single trace event."""
    timestamp: float = Field(default_factory=time.time)
    datetime_str: str = Field(default_factory=lambda: datetime.now().isoformat())
    event_type: TraceEventType
    level: TraceLevel = TraceLevel.INFO
    agent_name: Optional[str] = None
    task_id: Optional[str] = None
    coordinator_id: Optional[str] = None
    message: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    duration_ms: Optional[float] = None
    parent_trace_id: Optional[str] = None


class AgentTrace(BaseModel):
    """Complete trace for a single agent execution."""
    trace_id: str
    agent_name: str
    task_id: str
    start_time: float
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    status: str = "running"  # running, completed, failed
    events: List[TraceEvent] = Field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class CoordinatorTrace(BaseModel):
    """Complete trace for coordinator execution."""
    trace_id: str
    coordinator_type: str  # parallel, sequential, hybrid
    start_time: float
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    total_agents: int
    completed_agents: int = 0
    failed_agents: int = 0
    agent_traces: List[AgentTrace] = Field(default_factory=list)
    events: List[TraceEvent] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TraceLogger:
    """
    File-based trace logger for agent execution tracking.

    Features:
    - Structured JSON trace files
    - Real-time event logging
    - Parent-child trace relationships
    - Performance metrics tracking
    - Easy migration path to database
    """

    def __init__(self, trace_dir: str = "traces"):
        self.trace_dir = Path(trace_dir)
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self._current_coordinator_trace: Optional[CoordinatorTrace] = None
        self._agent_traces: Dict[str, AgentTrace] = {}
        self._lock = asyncio.Lock()

    def _generate_trace_id(self, prefix: str) -> str:
        """Generate unique trace ID."""
        timestamp = int(time.time() * 1000)
        return f"{prefix}_{timestamp}_{id(self)}"

    async def start_coordinator_trace(
        self,
        coordinator_type: str,
        total_agents: int,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Start a new coordinator trace."""
        async with self._lock:
            trace_id = self._generate_trace_id("coord")

            self._current_coordinator_trace = CoordinatorTrace(
                trace_id=trace_id,
                coordinator_type=coordinator_type,
                start_time=time.time(),
                total_agents=total_agents,
                metadata=metadata or {}
            )

            # Log start event
            event = TraceEvent(
                event_type=TraceEventType.COORDINATOR_START,
                level=TraceLevel.INFO,
                coordinator_id=trace_id,
                message=f"Coordinator started: {coordinator_type} with {total_agents} agents",
                metadata=metadata or {}
            )
            self._current_coordinator_trace.events.append(event)

            # Write initial trace file
            await self._write_coordinator_trace()

            return trace_id

    async def end_coordinator_trace(
        self,
        trace_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """End coordinator trace and finalize."""
        async with self._lock:
            if not self._current_coordinator_trace or self._current_coordinator_trace.trace_id != trace_id:
                return

            self._current_coordinator_trace.end_time = time.time()
            self._current_coordinator_trace.duration_ms = (
                (self._current_coordinator_trace.end_time - self._current_coordinator_trace.start_time) * 1000
            )

            # Log end event
            event = TraceEvent(
                event_type=TraceEventType.COORDINATOR_END,
                level=TraceLevel.INFO,
                coordinator_id=trace_id,
                message=(
                    f"Coordinator completed: {self._current_coordinator_trace.completed_agents}/"
                    f"{self._current_coordinator_trace.total_agents} succeeded, "
                    f"{self._current_coordinator_trace.failed_agents} failed"
                ),
                duration_ms=self._current_coordinator_trace.duration_ms,
                metadata=metadata or {}
            )
            self._current_coordinator_trace.events.append(event)

            # Write final trace
            await self._write_coordinator_trace()

    async def start_agent_trace(
        self,
        agent_name: str,
        task_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Start a new agent trace."""
        async with self._lock:
            trace_id = self._generate_trace_id(f"agent_{agent_name}")

            agent_trace = AgentTrace(
                trace_id=trace_id,
                agent_name=agent_name,
                task_id=task_id,
                start_time=time.time()
            )

            # Log start event
            event = TraceEvent(
                event_type=TraceEventType.AGENT_START,
                level=TraceLevel.INFO,
                agent_name=agent_name,
                task_id=task_id,
                message=f"Agent started: {agent_name} for task {task_id}",
                metadata=metadata or {},
                parent_trace_id=self._current_coordinator_trace.trace_id if self._current_coordinator_trace else None
            )
            agent_trace.events.append(event)

            self._agent_traces[trace_id] = agent_trace

            # Add to coordinator trace if active
            if self._current_coordinator_trace:
                self._current_coordinator_trace.agent_traces.append(agent_trace)

            return trace_id

    async def end_agent_trace(
        self,
        trace_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        """End agent trace with result or error."""
        async with self._lock:
            if trace_id not in self._agent_traces:
                return

            agent_trace = self._agent_traces[trace_id]
            agent_trace.end_time = time.time()
            agent_trace.duration_ms = (agent_trace.end_time - agent_trace.start_time) * 1000
            agent_trace.status = status
            agent_trace.result = result
            agent_trace.error = error

            # Log end event
            event_type = (
                TraceEventType.AGENT_END if status == "completed"
                else TraceEventType.AGENT_ERROR
            )
            level = TraceLevel.INFO if status == "completed" else TraceLevel.ERROR

            event = TraceEvent(
                event_type=event_type,
                level=level,
                agent_name=agent_trace.agent_name,
                task_id=agent_trace.task_id,
                message=f"Agent {status}: {agent_trace.agent_name} ({agent_trace.duration_ms:.2f}ms)",
                duration_ms=agent_trace.duration_ms,
                metadata={"result": result, "error": error},
                parent_trace_id=self._current_coordinator_trace.trace_id if self._current_coordinator_trace else None
            )
            agent_trace.events.append(event)

            # Update coordinator stats
            if self._current_coordinator_trace:
                if status == "completed":
                    self._current_coordinator_trace.completed_agents += 1
                else:
                    self._current_coordinator_trace.failed_agents += 1

                # Write updated coordinator trace
                await self._write_coordinator_trace()

    async def log_event(
        self,
        event_type: TraceEventType,
        message: str,
        level: TraceLevel = TraceLevel.INFO,
        agent_name: Optional[str] = None,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log a standalone event."""
        async with self._lock:
            event = TraceEvent(
                event_type=event_type,
                level=level,
                agent_name=agent_name,
                task_id=task_id,
                coordinator_id=self._current_coordinator_trace.trace_id if self._current_coordinator_trace else None,
                message=message,
                metadata=metadata or {},
                parent_trace_id=self._current_coordinator_trace.trace_id if self._current_coordinator_trace else None
            )

            if self._current_coordinator_trace:
                self._current_coordinator_trace.events.append(event)
                await self._write_coordinator_trace()

    async def _write_coordinator_trace(self):
        """Write coordinator trace to file."""
        if not self._current_coordinator_trace:
            return

        trace_file = self.trace_dir / f"{self._current_coordinator_trace.trace_id}.json"

        # Convert to JSON
        trace_data = self._current_coordinator_trace.model_dump()

        # Write atomically
        temp_file = trace_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(trace_data, f, indent=2)
        temp_file.replace(trace_file)

    def get_trace_file_path(self, trace_id: str) -> Path:
        """Get path to trace file."""
        return self.trace_dir / f"{trace_id}.json"

    async def read_trace(self, trace_id: str) -> Optional[CoordinatorTrace]:
        """Read trace from file."""
        trace_file = self.get_trace_file_path(trace_id)

        if not trace_file.exists():
            return None

        with open(trace_file) as f:
            data = json.load(f)

        return CoordinatorTrace(**data)

    def list_traces(self, limit: int = 10) -> List[Path]:
        """List recent trace files."""
        traces = sorted(
            self.trace_dir.glob("coord_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        return traces[:limit]

    async def print_trace_summary(self, trace_id: str):
        """Print human-readable trace summary."""
        trace = await self.read_trace(trace_id)

        if not trace:
            print(f"❌ Trace not found: {trace_id}")
            return

        print(f"\n{'='*80}")
        print(f"📊 Coordinator Trace Summary")
        print(f"{'='*80}")
        print(f"Trace ID: {trace.trace_id}")
        print(f"Type: {trace.coordinator_type}")
        print(f"Duration: {trace.duration_ms:.2f}ms" if trace.duration_ms else "Duration: In progress")
        print(f"Agents: {trace.completed_agents}/{trace.total_agents} completed, {trace.failed_agents} failed")
        print(f"\n{'='*80}")
        print(f"Agent Executions:")
        print(f"{'='*80}")

        for agent_trace in trace.agent_traces:
            status_emoji = "✅" if agent_trace.status == "completed" else "❌"
            duration = f"{agent_trace.duration_ms:.2f}ms" if agent_trace.duration_ms else "In progress"
            print(f"{status_emoji} {agent_trace.agent_name} [{agent_trace.task_id}]")
            print(f"   Duration: {duration}")
            print(f"   Status: {agent_trace.status}")
            if agent_trace.error:
                print(f"   Error: {agent_trace.error}")

        print(f"\n{'='*80}")
        print(f"Events Timeline:")
        print(f"{'='*80}")

        for event in trace.events[:20]:  # Show first 20 events
            print(f"[{event.datetime_str}] {event.level.value:8s} {event.event_type.value:25s} {event.message}")

        if len(trace.events) > 20:
            print(f"... and {len(trace.events) - 20} more events")

        print(f"{'='*80}\n")


# Global trace logger instance
_trace_logger: Optional[TraceLogger] = None


def get_trace_logger() -> TraceLogger:
    """Get or create global trace logger instance."""
    global _trace_logger
    if _trace_logger is None:
        _trace_logger = TraceLogger()
    return _trace_logger
