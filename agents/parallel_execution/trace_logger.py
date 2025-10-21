"""
Trace Logger for Agent Execution Tracking

Provides file-based tracing for all agent operations with structured logging.
Later can be migrated to database storage.
"""

import asyncio
import json
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    ROUTING_DECISION = "ROUTING_DECISION"
    AGENT_TRANSFORM = "AGENT_TRANSFORM"


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
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start a new coordinator trace."""
        async with self._lock:
            trace_id = self._generate_trace_id("coord")

            self._current_coordinator_trace = CoordinatorTrace(
                trace_id=trace_id,
                coordinator_type=coordinator_type,
                start_time=time.time(),
                total_agents=total_agents,
                metadata=metadata or {},
            )

            # Log start event
            event = TraceEvent(
                event_type=TraceEventType.COORDINATOR_START,
                level=TraceLevel.INFO,
                coordinator_id=trace_id,
                message=f"Coordinator started: {coordinator_type} with {total_agents} agents",
                metadata=metadata or {},
            )
            self._current_coordinator_trace.events.append(event)

            # Write initial trace file
            await self._write_coordinator_trace()

            return trace_id

    async def end_coordinator_trace(
        self, trace_id: str, metadata: Optional[Dict[str, Any]] = None
    ):
        """End coordinator trace and finalize."""
        async with self._lock:
            if (
                not self._current_coordinator_trace
                or self._current_coordinator_trace.trace_id != trace_id
            ):
                return

            self._current_coordinator_trace.end_time = time.time()
            self._current_coordinator_trace.duration_ms = (
                self._current_coordinator_trace.end_time
                - self._current_coordinator_trace.start_time
            ) * 1000

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
                metadata=metadata or {},
            )
            self._current_coordinator_trace.events.append(event)

            # Write final trace
            await self._write_coordinator_trace()

    async def start_agent_trace(
        self, agent_name: str, task_id: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Start a new agent trace."""
        async with self._lock:
            trace_id = self._generate_trace_id(f"agent_{agent_name}")

            agent_trace = AgentTrace(
                trace_id=trace_id,
                agent_name=agent_name,
                task_id=task_id,
                start_time=time.time(),
            )

            # Log start event
            event = TraceEvent(
                event_type=TraceEventType.AGENT_START,
                level=TraceLevel.INFO,
                agent_name=agent_name,
                task_id=task_id,
                message=f"Agent started: {agent_name} for task {task_id}",
                metadata=metadata or {},
                parent_trace_id=(
                    self._current_coordinator_trace.trace_id
                    if self._current_coordinator_trace
                    else None
                ),
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
        error: Optional[str] = None,
    ):
        """End agent trace with result or error."""
        async with self._lock:
            if trace_id not in self._agent_traces:
                return

            agent_trace = self._agent_traces[trace_id]
            agent_trace.end_time = time.time()
            agent_trace.duration_ms = (
                agent_trace.end_time - agent_trace.start_time
            ) * 1000
            agent_trace.status = status
            agent_trace.result = result
            agent_trace.error = error

            # Log end event
            event_type = (
                TraceEventType.AGENT_END
                if status == "completed"
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
                parent_trace_id=(
                    self._current_coordinator_trace.trace_id
                    if self._current_coordinator_trace
                    else None
                ),
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
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Log a standalone event."""
        async with self._lock:
            event = TraceEvent(
                event_type=event_type,
                level=level,
                agent_name=agent_name,
                task_id=task_id,
                coordinator_id=(
                    self._current_coordinator_trace.trace_id
                    if self._current_coordinator_trace
                    else None
                ),
                message=message,
                metadata=metadata or {},
                parent_trace_id=(
                    self._current_coordinator_trace.trace_id
                    if self._current_coordinator_trace
                    else None
                ),
            )

            if self._current_coordinator_trace:
                self._current_coordinator_trace.events.append(event)
                await self._write_coordinator_trace()

    async def log_routing_decision(
        self,
        user_request: str,
        selected_agent: str,
        confidence_score: float,
        alternatives: List[Dict[str, Any]],
        reasoning: str,
        task_id: Optional[str] = None,
        routing_strategy: str = "enhanced",
        context: Optional[Dict[str, Any]] = None,
        routing_time_ms: Optional[float] = None,
    ):
        """
        Log a routing decision with full context.

        Args:
            user_request: Original user request that triggered routing
            selected_agent: Name of the selected agent
            confidence_score: Confidence score for the selection (0.0-1.0)
            alternatives: List of alternative agents considered with their scores
            reasoning: Explanation for why this agent was selected
            task_id: Associated task ID if available
            routing_strategy: Strategy used for routing (enhanced, fuzzy, exact, etc.)
            context: Additional context used in routing decision
            routing_time_ms: Time taken to make routing decision
        """
        async with self._lock:
            # Build routing metadata
            routing_metadata = {
                "user_request": user_request,
                "selected_agent": selected_agent,
                "confidence_score": confidence_score,
                "reasoning": reasoning,
                "routing_strategy": routing_strategy,
                "alternatives": alternatives,  # List of {agent_name, confidence, match_type, ...}
                "context": context or {},
                "routing_time_ms": routing_time_ms,
                "alternatives_count": len(alternatives),
                "top_3_alternatives": (
                    alternatives[:3] if len(alternatives) > 3 else alternatives
                ),
            }

            # Determine log level based on confidence
            level = TraceLevel.INFO
            if confidence_score < 0.5:
                level = TraceLevel.WARNING
            elif confidence_score < 0.3:
                level = TraceLevel.ERROR

            # Create message
            message = (
                f"Routing decision: selected '{selected_agent}' "
                f"(confidence: {confidence_score:.2%}, "
                f"alternatives: {len(alternatives)}, "
                f"strategy: {routing_strategy})"
            )

            # Create trace event
            event = TraceEvent(
                event_type=TraceEventType.ROUTING_DECISION,
                level=level,
                agent_name=selected_agent,
                task_id=task_id,
                coordinator_id=(
                    self._current_coordinator_trace.trace_id
                    if self._current_coordinator_trace
                    else None
                ),
                message=message,
                metadata=routing_metadata,
                duration_ms=routing_time_ms,
                parent_trace_id=(
                    self._current_coordinator_trace.trace_id
                    if self._current_coordinator_trace
                    else None
                ),
            )

            # Add to coordinator trace if active
            if self._current_coordinator_trace:
                self._current_coordinator_trace.events.append(event)
                await self._write_coordinator_trace()

            # Also write a standalone routing decision file for easy querying
            await self._write_routing_decision_file(event)

    async def _write_routing_decision_file(self, event: TraceEvent):
        """Write standalone routing decision file for easy querying."""
        # Create routing decisions subdirectory
        routing_dir = self.trace_dir / "routing_decisions"
        routing_dir.mkdir(parents=True, exist_ok=True)

        # Create filename with timestamp
        timestamp_str = datetime.fromtimestamp(event.timestamp).strftime(
            "%Y%m%d_%H%M%S_%f"
        )
        filename = f"routing_{timestamp_str}.json"
        routing_file = routing_dir / filename

        # Convert to JSON
        routing_data = event.model_dump()

        # Write atomically
        temp_file = routing_file.with_suffix(".tmp")
        with open(temp_file, "w") as f:
            json.dump(routing_data, f, indent=2)
        temp_file.replace(routing_file)

    async def _write_coordinator_trace(self):
        """Write coordinator trace to file."""
        if not self._current_coordinator_trace:
            return

        trace_file = self.trace_dir / f"{self._current_coordinator_trace.trace_id}.json"

        # Convert to JSON
        trace_data = self._current_coordinator_trace.model_dump()

        # Write atomically
        temp_file = trace_file.with_suffix(".tmp")
        with open(temp_file, "w") as f:
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
            reverse=True,
        )
        return traces[:limit]

    async def print_trace_summary(self, trace_id: str):
        """Print human-readable trace summary."""
        trace = await self.read_trace(trace_id)

        if not trace:
            print(f"❌ Trace not found: {trace_id}")
            return

        print(f"\n{'='*80}")
        print("📊 Coordinator Trace Summary")
        print(f"{'='*80}")
        print(f"Trace ID: {trace.trace_id}")
        print(f"Type: {trace.coordinator_type}")
        print(
            f"Duration: {trace.duration_ms:.2f}ms"
            if trace.duration_ms
            else "Duration: In progress"
        )
        print(
            f"Agents: {trace.completed_agents}/{trace.total_agents} completed, {trace.failed_agents} failed"
        )
        print(f"\n{'='*80}")
        print("Agent Executions:")
        print(f"{'='*80}")

        for agent_trace in trace.agent_traces:
            status_emoji = "✅" if agent_trace.status == "completed" else "❌"
            duration = (
                f"{agent_trace.duration_ms:.2f}ms"
                if agent_trace.duration_ms
                else "In progress"
            )
            print(f"{status_emoji} {agent_trace.agent_name} [{agent_trace.task_id}]")
            print(f"   Duration: {duration}")
            print(f"   Status: {agent_trace.status}")
            if agent_trace.error:
                print(f"   Error: {agent_trace.error}")

        print(f"\n{'='*80}")
        print("Events Timeline:")
        print(f"{'='*80}")

        for event in trace.events[:20]:  # Show first 20 events
            print(
                f"[{event.datetime_str}] {event.level.value:8s} {event.event_type.value:25s} {event.message}"
            )

        if len(trace.events) > 20:
            print(f"... and {len(trace.events) - 20} more events")

        print(f"{'='*80}\n")

    async def query_routing_decisions(
        self,
        agent_name: Optional[str] = None,
        min_confidence: Optional[float] = None,
        max_confidence: Optional[float] = None,
        routing_strategy: Optional[str] = None,
        limit: int = 50,
    ) -> List[TraceEvent]:
        """
        Query routing decisions with filters.

        Args:
            agent_name: Filter by selected agent name
            min_confidence: Minimum confidence score
            max_confidence: Maximum confidence score
            routing_strategy: Filter by routing strategy
            limit: Maximum number of results

        Returns:
            List of matching routing decision events
        """
        routing_dir = self.trace_dir / "routing_decisions"
        if not routing_dir.exists():
            return []

        # Get all routing decision files
        routing_files = sorted(
            routing_dir.glob("routing_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        results = []
        for routing_file in routing_files:
            if len(results) >= limit:
                break

            try:
                with open(routing_file) as f:
                    event_data = json.load(f)
                    event = TraceEvent(**event_data)

                # Apply filters
                metadata = event.metadata
                if agent_name and metadata.get("selected_agent") != agent_name:
                    continue
                if (
                    min_confidence is not None
                    and metadata.get("confidence_score", 0) < min_confidence
                ):
                    continue
                if (
                    max_confidence is not None
                    and metadata.get("confidence_score", 1) > max_confidence
                ):
                    continue
                if (
                    routing_strategy
                    and metadata.get("routing_strategy") != routing_strategy
                ):
                    continue

                results.append(event)
            except Exception:
                # Skip corrupted files
                continue

        return results

    async def get_recent_routing_decisions(self, limit: int = 10) -> List[TraceEvent]:
        """Get N most recent routing decisions."""
        return await self.query_routing_decisions(limit=limit)

    async def get_routing_decisions_for_agent(
        self, agent_name: str, limit: int = 20
    ) -> List[TraceEvent]:
        """Get routing decisions for a specific agent."""
        return await self.query_routing_decisions(agent_name=agent_name, limit=limit)

    async def get_low_confidence_routing_decisions(
        self, confidence_threshold: float = 0.7, limit: int = 20
    ) -> List[TraceEvent]:
        """Get routing decisions with low confidence scores."""
        return await self.query_routing_decisions(
            max_confidence=confidence_threshold, limit=limit
        )

    async def get_routing_statistics(self) -> Dict[str, Any]:
        """
        Get aggregate statistics about routing decisions.

        Returns:
            Dictionary with routing statistics:
            - total_decisions: Total number of routing decisions
            - agents_selected: Count by agent name
            - avg_confidence: Average confidence score
            - confidence_distribution: Distribution by confidence ranges
            - routing_strategies: Count by strategy
            - low_confidence_count: Number of decisions below 0.7 confidence
        """
        all_decisions = await self.query_routing_decisions(limit=10000)

        if not all_decisions:
            return {
                "total_decisions": 0,
                "agents_selected": {},
                "avg_confidence": 0.0,
                "confidence_distribution": {},
                "routing_strategies": {},
                "low_confidence_count": 0,
            }

        # Collect statistics
        agents_selected = {}
        confidence_scores = []
        confidence_distribution = {
            "0.0-0.3": 0,
            "0.3-0.5": 0,
            "0.5-0.7": 0,
            "0.7-0.9": 0,
            "0.9-1.0": 0,
        }
        routing_strategies = {}
        low_confidence_count = 0

        for event in all_decisions:
            metadata = event.metadata

            # Agent selection counts
            agent = metadata.get("selected_agent", "unknown")
            agents_selected[agent] = agents_selected.get(agent, 0) + 1

            # Confidence scores
            confidence = metadata.get("confidence_score", 0.0)
            confidence_scores.append(confidence)

            # Confidence distribution
            if confidence < 0.3:
                confidence_distribution["0.0-0.3"] += 1
                low_confidence_count += 1
            elif confidence < 0.5:
                confidence_distribution["0.3-0.5"] += 1
                low_confidence_count += 1
            elif confidence < 0.7:
                confidence_distribution["0.5-0.7"] += 1
                low_confidence_count += 1
            elif confidence < 0.9:
                confidence_distribution["0.7-0.9"] += 1
            else:
                confidence_distribution["0.9-1.0"] += 1

            # Routing strategies
            strategy = metadata.get("routing_strategy", "unknown")
            routing_strategies[strategy] = routing_strategies.get(strategy, 0) + 1

        return {
            "total_decisions": len(all_decisions),
            "agents_selected": agents_selected,
            "avg_confidence": (
                sum(confidence_scores) / len(confidence_scores)
                if confidence_scores
                else 0.0
            ),
            "confidence_distribution": confidence_distribution,
            "routing_strategies": routing_strategies,
            "low_confidence_count": low_confidence_count,
            "low_confidence_rate": (
                low_confidence_count / len(all_decisions) if all_decisions else 0.0
            ),
        }

    async def print_routing_statistics(self):
        """Print human-readable routing statistics."""
        stats = await self.get_routing_statistics()

        print(f"\n{'='*80}")
        print("🎯 Routing Decision Statistics")
        print(f"{'='*80}")
        print(f"Total Decisions: {stats['total_decisions']}")
        print(f"Average Confidence: {stats['avg_confidence']:.2%}")
        print(
            f"Low Confidence Rate: {stats['low_confidence_rate']:.2%} ({stats['low_confidence_count']} decisions)"
        )

        print(f"\n{'='*80}")
        print("Agents Selected:")
        print(f"{'='*80}")
        for agent, count in sorted(
            stats["agents_selected"].items(), key=lambda x: x[1], reverse=True
        ):
            percentage = (
                (count / stats["total_decisions"]) * 100
                if stats["total_decisions"] > 0
                else 0
            )
            print(f"  {agent:40s} {count:5d} ({percentage:5.1f}%)")

        print(f"\n{'='*80}")
        print("Confidence Distribution:")
        print(f"{'='*80}")
        for range_label, count in stats["confidence_distribution"].items():
            percentage = (
                (count / stats["total_decisions"]) * 100
                if stats["total_decisions"] > 0
                else 0
            )
            bar_length = int(percentage / 2)
            bar = "█" * bar_length
            print(f"  {range_label:10s} {count:5d} ({percentage:5.1f}%) {bar}")

        print(f"\n{'='*80}")
        print("Routing Strategies:")
        print(f"{'='*80}")
        for strategy, count in sorted(
            stats["routing_strategies"].items(), key=lambda x: x[1], reverse=True
        ):
            percentage = (
                (count / stats["total_decisions"]) * 100
                if stats["total_decisions"] > 0
                else 0
            )
            print(f"  {strategy:20s} {count:5d} ({percentage:5.1f}%)")

        print(f"{'='*80}\n")


# Global trace logger instance
_trace_logger: Optional[TraceLogger] = None


def get_trace_logger() -> TraceLogger:
    """Get or create global trace logger instance."""
    global _trace_logger
    if _trace_logger is None:
        _trace_logger = TraceLogger()
    return _trace_logger
