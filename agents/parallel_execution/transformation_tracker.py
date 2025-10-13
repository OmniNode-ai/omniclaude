"""
Agent Transformation Event Tracker

Tracks agent identity transformations and polymorphic behavior for the workflow coordinator.
Provides comprehensive logging of when agents assume specialized identities.

Features:
- Transformation event tracking with full context
- Performance measurement (target: <50ms overhead)
- Pattern analysis for common transformations
- Dashboard-ready metrics generation
- File-based persistence (database migration ready)
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from collections import defaultdict, Counter
import asyncio

from .trace_logger import TraceLogger, TraceEventType, TraceLevel, get_trace_logger


class TransformationEvent(BaseModel):
    """Single agent transformation event."""
    transformation_id: str
    timestamp: float = Field(default_factory=time.time)
    datetime_str: str = Field(default_factory=lambda: datetime.now().isoformat())

    # Transformation details
    source_identity: str  # e.g., "agent-workflow-coordinator"
    target_identity: str  # e.g., "agent-debug-intelligence"
    transformation_reason: str  # Why this transformation occurred

    # Context and capabilities
    user_request: str  # Original user request
    routing_confidence: Optional[float] = None
    capabilities_inherited: List[str] = Field(default_factory=list)
    context_preserved: Dict[str, Any] = Field(default_factory=dict)

    # Performance tracking
    transformation_overhead_ms: Optional[float] = None  # Target: <50ms
    agent_load_time_ms: Optional[float] = None
    total_time_ms: Optional[float] = None

    # Metadata
    task_id: Optional[str] = None
    coordinator_id: Optional[str] = None
    agent_definition_path: Optional[str] = None
    success: bool = True
    error: Optional[str] = None


class TransformationPattern(BaseModel):
    """Identified transformation pattern."""
    pattern_id: str
    source_target_pair: Tuple[str, str]  # (source, target)
    occurrence_count: int
    avg_transformation_time_ms: float
    avg_confidence_score: float
    success_rate: float
    common_reasons: List[str]
    last_occurrence: float


class TransformationMetrics(BaseModel):
    """Dashboard-ready transformation metrics."""
    total_transformations: int
    unique_source_identities: int
    unique_target_identities: int
    avg_transformation_overhead_ms: float
    median_transformation_overhead_ms: float
    max_transformation_overhead_ms: float
    success_rate: float

    # Performance thresholds (from performance-thresholds.yaml: CTX-002 = 25ms)
    transformations_under_threshold: int
    transformations_over_threshold: int
    threshold_compliance_rate: float

    # Common patterns
    most_common_source: str
    most_common_target: str
    most_common_transformation: Tuple[str, str]

    # Time-based metrics
    transformations_last_hour: int
    transformations_last_day: int
    avg_transformations_per_hour: float


class AgentTransformationTracker:
    """
    Tracks agent identity transformations with comprehensive observability.

    Features:
    - File-based transformation event storage
    - Real-time pattern recognition
    - Performance measurement (<50ms target)
    - Dashboard metrics generation
    - Integration with TraceLogger for event propagation
    """

    # Performance threshold from performance-thresholds.yaml (CTX-002)
    TRANSFORMATION_THRESHOLD_MS = 50.0

    def __init__(
        self,
        storage_dir: str = "traces/transformations",
        trace_logger: Optional[TraceLogger] = None
    ):
        """
        Initialize transformation tracker.

        Args:
            storage_dir: Directory for storing transformation events
            trace_logger: Optional TraceLogger for event integration
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.trace_logger = trace_logger or get_trace_logger()
        self._lock = asyncio.Lock()

        # In-memory cache for pattern analysis
        self._transformation_cache: List[TransformationEvent] = []
        self._pattern_cache: Dict[str, TransformationPattern] = {}
        self._cache_max_size = 1000  # Keep last 1000 transformations in memory

        # Statistics
        self._stats = {
            'total_tracked': 0,
            'successful': 0,
            'failed': 0,
            'cache_hits': 0,
            'pattern_recognitions': 0
        }

    async def track_transformation(
        self,
        source_identity: str,
        target_identity: str,
        user_request: str,
        transformation_reason: str,
        capabilities_inherited: Optional[List[str]] = None,
        context_preserved: Optional[Dict[str, Any]] = None,
        routing_confidence: Optional[float] = None,
        task_id: Optional[str] = None,
        agent_definition_path: Optional[str] = None,
        measure_performance: bool = True
    ) -> TransformationEvent:
        """
        Track a single agent transformation event.

        Args:
            source_identity: Original agent identity
            target_identity: Transformed agent identity
            user_request: Original user request
            transformation_reason: Why this transformation occurred
            capabilities_inherited: List of capabilities from target agent
            context_preserved: Context preserved during transformation
            routing_confidence: Confidence score from routing decision
            task_id: Associated task ID
            agent_definition_path: Path to agent definition file
            measure_performance: Whether to measure transformation overhead

        Returns:
            TransformationEvent with performance metrics
        """
        start_time = time.time()

        async with self._lock:
            # Generate transformation ID
            transformation_id = self._generate_transformation_id()

            # Measure performance if requested
            overhead_ms = None
            if measure_performance:
                # Simulate transformation overhead measurement
                # In real integration, this would measure actual load/init time
                overhead_ms = (time.time() - start_time) * 1000

            # Create transformation event
            event = TransformationEvent(
                transformation_id=transformation_id,
                source_identity=source_identity,
                target_identity=target_identity,
                user_request=user_request,
                transformation_reason=transformation_reason,
                capabilities_inherited=capabilities_inherited or [],
                context_preserved=context_preserved or {},
                routing_confidence=routing_confidence,
                task_id=task_id,
                agent_definition_path=agent_definition_path,
                transformation_overhead_ms=overhead_ms,
                total_time_ms=(time.time() - start_time) * 1000
            )

            # Update statistics
            self._stats['total_tracked'] += 1
            if event.success:
                self._stats['successful'] += 1
            else:
                self._stats['failed'] += 1

            # Add to cache
            self._transformation_cache.append(event)
            if len(self._transformation_cache) > self._cache_max_size:
                self._transformation_cache.pop(0)

            # Write to file
            await self._write_transformation_file(event)

            # Log to TraceLogger
            await self._log_to_trace_logger(event)

            # Update patterns (async background task)
            asyncio.create_task(self._update_patterns(event))

            return event

    async def track_transformation_with_timing(
        self,
        source_identity: str,
        target_identity: str,
        user_request: str,
        transformation_reason: str,
        agent_load_time_ms: float,
        capabilities_inherited: Optional[List[str]] = None,
        context_preserved: Optional[Dict[str, Any]] = None,
        routing_confidence: Optional[float] = None,
        task_id: Optional[str] = None,
        agent_definition_path: Optional[str] = None
    ) -> TransformationEvent:
        """
        Track transformation with pre-measured timing data.

        Use this when you've already measured the transformation overhead
        externally (e.g., from agent loading/initialization).

        Args:
            agent_load_time_ms: Pre-measured agent load time
            (other args same as track_transformation)

        Returns:
            TransformationEvent with provided timing data
        """
        start_time = time.time()

        async with self._lock:
            transformation_id = self._generate_transformation_id()

            # Calculate overhead (total time - agent load time)
            total_time_ms = (time.time() - start_time) * 1000
            overhead_ms = max(0, total_time_ms - agent_load_time_ms)

            event = TransformationEvent(
                transformation_id=transformation_id,
                source_identity=source_identity,
                target_identity=target_identity,
                user_request=user_request,
                transformation_reason=transformation_reason,
                capabilities_inherited=capabilities_inherited or [],
                context_preserved=context_preserved or {},
                routing_confidence=routing_confidence,
                task_id=task_id,
                agent_definition_path=agent_definition_path,
                transformation_overhead_ms=overhead_ms,
                agent_load_time_ms=agent_load_time_ms,
                total_time_ms=total_time_ms
            )

            self._stats['total_tracked'] += 1
            if event.success:
                self._stats['successful'] += 1
            else:
                self._stats['failed'] += 1

            self._transformation_cache.append(event)
            if len(self._transformation_cache) > self._cache_max_size:
                self._transformation_cache.pop(0)

            await self._write_transformation_file(event)
            await self._log_to_trace_logger(event)
            asyncio.create_task(self._update_patterns(event))

            return event

    async def get_transformation_history(
        self,
        source_identity: Optional[str] = None,
        target_identity: Optional[str] = None,
        limit: int = 100
    ) -> List[TransformationEvent]:
        """
        Get transformation history with optional filtering.

        Args:
            source_identity: Filter by source identity
            target_identity: Filter by target identity
            limit: Maximum number of events to return

        Returns:
            List of transformation events (newest first)
        """
        async with self._lock:
            # Filter cache
            events = self._transformation_cache

            if source_identity:
                events = [e for e in events if e.source_identity == source_identity]

            if target_identity:
                events = [e for e in events if e.target_identity == target_identity]

            # Sort by timestamp (newest first)
            events = sorted(events, key=lambda e: e.timestamp, reverse=True)

            return events[:limit]

    async def analyze_patterns(
        self,
        min_occurrences: int = 3
    ) -> List[TransformationPattern]:
        """
        Analyze transformation patterns from historical data.

        Args:
            min_occurrences: Minimum occurrences to qualify as pattern

        Returns:
            List of identified transformation patterns
        """
        async with self._lock:
            patterns = []

            # Group by source-target pair
            pair_groups: Dict[Tuple[str, str], List[TransformationEvent]] = defaultdict(list)

            for event in self._transformation_cache:
                pair = (event.source_identity, event.target_identity)
                pair_groups[pair].append(event)

            # Analyze each pattern
            for pair, events in pair_groups.items():
                if len(events) < min_occurrences:
                    continue

                # Calculate metrics
                total_time = sum(e.transformation_overhead_ms or 0 for e in events)
                avg_time = total_time / len(events)

                confidences = [e.routing_confidence for e in events if e.routing_confidence is not None]
                avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

                successful = sum(1 for e in events if e.success)
                success_rate = successful / len(events)

                # Extract common reasons
                reason_counter = Counter(e.transformation_reason for e in events)
                common_reasons = [reason for reason, _ in reason_counter.most_common(3)]

                pattern = TransformationPattern(
                    pattern_id=f"pattern_{pair[0]}_{pair[1]}",
                    source_target_pair=pair,
                    occurrence_count=len(events),
                    avg_transformation_time_ms=avg_time,
                    avg_confidence_score=avg_confidence,
                    success_rate=success_rate,
                    common_reasons=common_reasons,
                    last_occurrence=events[-1].timestamp
                )

                patterns.append(pattern)
                self._pattern_cache[pattern.pattern_id] = pattern

            self._stats['pattern_recognitions'] = len(patterns)

            # Sort by occurrence count
            patterns.sort(key=lambda p: p.occurrence_count, reverse=True)

            return patterns

    async def get_metrics(self) -> TransformationMetrics:
        """
        Generate dashboard-ready transformation metrics.

        Returns:
            TransformationMetrics with comprehensive statistics
        """
        async with self._lock:
            if not self._transformation_cache:
                # Return empty metrics
                return TransformationMetrics(
                    total_transformations=0,
                    unique_source_identities=0,
                    unique_target_identities=0,
                    avg_transformation_overhead_ms=0.0,
                    median_transformation_overhead_ms=0.0,
                    max_transformation_overhead_ms=0.0,
                    success_rate=0.0,
                    transformations_under_threshold=0,
                    transformations_over_threshold=0,
                    threshold_compliance_rate=0.0,
                    most_common_source="N/A",
                    most_common_target="N/A",
                    most_common_transformation=("N/A", "N/A"),
                    transformations_last_hour=0,
                    transformations_last_day=0,
                    avg_transformations_per_hour=0.0
                )

            # Basic counts
            total = len(self._transformation_cache)
            successful = sum(1 for e in self._transformation_cache if e.success)

            # Identity analysis
            sources = set(e.source_identity for e in self._transformation_cache)
            targets = set(e.target_identity for e in self._transformation_cache)

            # Performance metrics
            overhead_times = [e.transformation_overhead_ms for e in self._transformation_cache
                            if e.transformation_overhead_ms is not None]

            avg_overhead = sum(overhead_times) / len(overhead_times) if overhead_times else 0.0
            sorted_times = sorted(overhead_times)
            median_overhead = sorted_times[len(sorted_times) // 2] if sorted_times else 0.0
            max_overhead = max(overhead_times) if overhead_times else 0.0

            # Threshold compliance
            under_threshold = sum(1 for t in overhead_times if t <= self.TRANSFORMATION_THRESHOLD_MS)
            over_threshold = len(overhead_times) - under_threshold
            compliance_rate = under_threshold / len(overhead_times) if overhead_times else 0.0

            # Common patterns
            source_counter = Counter(e.source_identity for e in self._transformation_cache)
            target_counter = Counter(e.target_identity for e in self._transformation_cache)
            pair_counter = Counter((e.source_identity, e.target_identity)
                                  for e in self._transformation_cache)

            most_common_source = source_counter.most_common(1)[0][0] if source_counter else "N/A"
            most_common_target = target_counter.most_common(1)[0][0] if target_counter else "N/A"
            most_common_pair = pair_counter.most_common(1)[0][0] if pair_counter else ("N/A", "N/A")

            # Time-based analysis
            now = time.time()
            hour_ago = now - 3600
            day_ago = now - 86400

            last_hour = sum(1 for e in self._transformation_cache if e.timestamp >= hour_ago)
            last_day = sum(1 for e in self._transformation_cache if e.timestamp >= day_ago)

            # Calculate average per hour based on oldest event
            oldest_timestamp = min(e.timestamp for e in self._transformation_cache)
            hours_elapsed = (now - oldest_timestamp) / 3600
            avg_per_hour = total / hours_elapsed if hours_elapsed > 0 else 0.0

            return TransformationMetrics(
                total_transformations=total,
                unique_source_identities=len(sources),
                unique_target_identities=len(targets),
                avg_transformation_overhead_ms=avg_overhead,
                median_transformation_overhead_ms=median_overhead,
                max_transformation_overhead_ms=max_overhead,
                success_rate=successful / total if total > 0 else 0.0,
                transformations_under_threshold=under_threshold,
                transformations_over_threshold=over_threshold,
                threshold_compliance_rate=compliance_rate,
                most_common_source=most_common_source,
                most_common_target=most_common_target,
                most_common_transformation=most_common_pair,
                transformations_last_hour=last_hour,
                transformations_last_day=last_day,
                avg_transformations_per_hour=avg_per_hour
            )

    async def print_metrics_summary(self):
        """Print human-readable metrics summary."""
        metrics = await self.get_metrics()

        print(f"\n{'='*80}")
        print(f"🔄 Agent Transformation Metrics Summary")
        print(f"{'='*80}")
        print(f"Total Transformations: {metrics.total_transformations}")
        print(f"Success Rate: {metrics.success_rate:.2%}")
        print(f"Unique Source Identities: {metrics.unique_source_identities}")
        print(f"Unique Target Identities: {metrics.unique_target_identities}")
        print(f"\n{'='*80}")
        print(f"Performance Metrics:")
        print(f"{'='*80}")
        print(f"Average Overhead: {metrics.avg_transformation_overhead_ms:.2f}ms")
        print(f"Median Overhead: {metrics.median_transformation_overhead_ms:.2f}ms")
        print(f"Max Overhead: {metrics.max_transformation_overhead_ms:.2f}ms")
        print(f"Threshold Compliance: {metrics.threshold_compliance_rate:.2%} "
              f"({metrics.transformations_under_threshold} under {self.TRANSFORMATION_THRESHOLD_MS}ms)")

        if metrics.transformations_over_threshold > 0:
            print(f"⚠️  {metrics.transformations_over_threshold} transformations exceeded threshold!")

        print(f"\n{'='*80}")
        print(f"Common Patterns:")
        print(f"{'='*80}")
        print(f"Most Common Source: {metrics.most_common_source}")
        print(f"Most Common Target: {metrics.most_common_target}")
        print(f"Most Common Transformation: {metrics.most_common_transformation[0]} → "
              f"{metrics.most_common_transformation[1]}")

        print(f"\n{'='*80}")
        print(f"Activity:")
        print(f"{'='*80}")
        print(f"Last Hour: {metrics.transformations_last_hour}")
        print(f"Last Day: {metrics.transformations_last_day}")
        print(f"Average per Hour: {metrics.avg_transformations_per_hour:.1f}")
        print(f"{'='*80}\n")

    def get_stats(self) -> Dict[str, Any]:
        """Get tracker statistics."""
        return self._stats.copy()

    # Private methods

    def _generate_transformation_id(self) -> str:
        """Generate unique transformation ID."""
        timestamp = int(time.time() * 1000000)  # microseconds
        return f"transform_{timestamp}"

    async def _write_transformation_file(self, event: TransformationEvent):
        """Write transformation event to file."""
        # Create daily subdirectory
        date_str = datetime.fromtimestamp(event.timestamp).strftime("%Y%m%d")
        daily_dir = self.storage_dir / date_str
        daily_dir.mkdir(parents=True, exist_ok=True)

        # Create filename
        timestamp_str = datetime.fromtimestamp(event.timestamp).strftime("%H%M%S_%f")
        filename = f"transform_{timestamp_str}_{event.source_identity}_to_{event.target_identity}.json"
        transform_file = daily_dir / filename

        # Convert to JSON
        transform_data = event.model_dump()

        # Write atomically
        temp_file = transform_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(transform_data, f, indent=2)
        temp_file.replace(transform_file)

    async def _log_to_trace_logger(self, event: TransformationEvent):
        """Log transformation to TraceLogger."""
        # Determine log level based on performance
        level = TraceLevel.INFO
        if event.transformation_overhead_ms and event.transformation_overhead_ms > self.TRANSFORMATION_THRESHOLD_MS:
            level = TraceLevel.WARNING

        # Create message
        message = (
            f"Agent transformation: {event.source_identity} → {event.target_identity} "
            f"(overhead: {event.transformation_overhead_ms:.2f}ms, "
            f"confidence: {event.routing_confidence:.2%})" if event.routing_confidence
            else f"Agent transformation: {event.source_identity} → {event.target_identity} "
                 f"(overhead: {event.transformation_overhead_ms:.2f}ms)"
        )

        # Build metadata
        metadata = {
            "transformation_id": event.transformation_id,
            "source_identity": event.source_identity,
            "target_identity": event.target_identity,
            "transformation_reason": event.transformation_reason,
            "capabilities_inherited": event.capabilities_inherited,
            "routing_confidence": event.routing_confidence,
            "transformation_overhead_ms": event.transformation_overhead_ms,
            "agent_definition_path": event.agent_definition_path,
            "user_request_preview": event.user_request[:100] + "..." if len(event.user_request) > 100 else event.user_request
        }

        # Log event
        await self.trace_logger.log_event(
            event_type=TraceEventType.AGENT_TRANSFORM,
            message=message,
            level=level,
            agent_name=event.target_identity,
            task_id=event.task_id,
            metadata=metadata
        )

    async def _update_patterns(self, event: TransformationEvent):
        """Update pattern cache with new event (background task)."""
        # Run pattern analysis periodically (every 10 transformations)
        if self._stats['total_tracked'] % 10 == 0:
            await self.analyze_patterns(min_occurrences=3)


# Global transformation tracker instance
_transformation_tracker: Optional[AgentTransformationTracker] = None


def get_transformation_tracker() -> AgentTransformationTracker:
    """Get or create global transformation tracker instance."""
    global _transformation_tracker
    if _transformation_tracker is None:
        _transformation_tracker = AgentTransformationTracker()
    return _transformation_tracker
