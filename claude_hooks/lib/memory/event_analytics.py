#!/usr/bin/env python3
"""
Event Analytics - Phase 1.2

Analyzes workflow events to identify:
- Success/failure patterns
- Correction effectiveness
- Common violation patterns
- Performance metrics
- Improvement opportunities
"""

import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .event_models import WorkflowEvent, EventType, WorkflowSummary
from .event_store import EventStore

logger = logging.getLogger(__name__)


@dataclass
class CorrectionEffectiveness:
    """
    Measures how effective corrections are.

    Attributes:
        correction_source: Origin of correction (rag, quorum, validator)
        total_attempts: Total corrections attempted
        successful_corrections: Corrections that resolved violations
        avg_confidence: Average confidence score
        success_rate: Percentage of successful corrections
        avg_iterations: Average correction attempts needed
    """

    correction_source: str
    total_attempts: int
    successful_corrections: int
    avg_confidence: float
    success_rate: float
    avg_iterations: float

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "correction_source": self.correction_source,
            "total_attempts": self.total_attempts,
            "successful_corrections": self.successful_corrections,
            "avg_confidence": self.avg_confidence,
            "success_rate": self.success_rate,
            "avg_iterations": self.avg_iterations,
        }


@dataclass
class ViolationPattern:
    """
    Common violation pattern detected across workflows.

    Attributes:
        rule: Validation rule violated
        occurrences: Number of times violated
        avg_severity: Average severity level
        resolution_rate: How often it gets resolved
        common_fixes: Most common corrections applied
    """

    rule: str
    occurrences: int
    avg_severity: float
    resolution_rate: float
    common_fixes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "rule": self.rule,
            "occurrences": self.occurrences,
            "avg_severity": self.avg_severity,
            "resolution_rate": self.resolution_rate,
            "common_fixes": self.common_fixes,
        }


@dataclass
class WorkflowMetrics:
    """
    Performance metrics for workflows.

    Attributes:
        total_workflows: Total workflows analyzed
        success_rate: Overall success rate
        avg_duration_ms: Average workflow duration
        avg_iterations: Average correction attempts
        avg_violations: Average violations per workflow
        most_common_intent: Most common intent category
        peak_hours: Hours with most activity
    """

    total_workflows: int
    success_rate: float
    avg_duration_ms: float
    avg_iterations: float
    avg_violations: float
    most_common_intent: str
    peak_hours: List[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "total_workflows": self.total_workflows,
            "success_rate": self.success_rate,
            "avg_duration_ms": self.avg_duration_ms,
            "avg_iterations": self.avg_iterations,
            "avg_violations": self.avg_violations,
            "most_common_intent": self.most_common_intent,
            "peak_hours": self.peak_hours,
        }


class EventAnalytics:
    """
    Analytics engine for event memory store.

    Provides insights into:
    - Correction effectiveness by source
    - Common violation patterns
    - Success/failure trends
    - Performance metrics
    """

    def __init__(self, event_store: EventStore):
        """
        Initialize analytics engine.

        Args:
            event_store: Event store to analyze
        """
        self.event_store = event_store

    def get_correction_stats(self, days: int = 30) -> Dict[str, CorrectionEffectiveness]:
        """
        Analyze correction effectiveness by source.

        Args:
            days: Number of days to analyze

        Returns:
            Dict mapping correction source to effectiveness metrics
        """
        # Get recent workflow correlation IDs
        correlation_ids = self.event_store.get_recent_workflows(days=days)

        correction_data = defaultdict(lambda: {"attempts": 0, "successes": 0, "confidences": [], "iterations": []})

        for correlation_id in correlation_ids:
            workflow = self.event_store.get_workflow(correlation_id)
            if not workflow:
                continue

            # Analyze corrections in this workflow
            self._analyze_workflow_corrections(workflow, correction_data)

        # Calculate effectiveness metrics
        results = {}
        for source, data in correction_data.items():
            if data["attempts"] > 0:
                results[source] = CorrectionEffectiveness(
                    correction_source=source,
                    total_attempts=data["attempts"],
                    successful_corrections=data["successes"],
                    avg_confidence=sum(data["confidences"]) / len(data["confidences"]) if data["confidences"] else 0.0,
                    success_rate=data["successes"] / data["attempts"],
                    avg_iterations=sum(data["iterations"]) / len(data["iterations"]) if data["iterations"] else 1.0,
                )

        return results

    def _analyze_workflow_corrections(self, workflow: List[WorkflowEvent], correction_data: Dict) -> None:
        """
        Analyze corrections in a single workflow.

        Updates correction_data with metrics from this workflow.
        """
        # Find correction generation events
        correction_events = [e for e in workflow if e.event_type == EventType.CORRECTION_GENERATED]

        if not correction_events:
            return

        # Determine workflow outcome
        final_event = workflow[-1]
        workflow_success = final_event.event_type == EventType.WRITE_SUCCESS or (final_event.success is True)

        # Track iterations
        max_iteration = max(e.iteration_number for e in workflow)

        for event in correction_events:
            if not event.corrections:
                continue

            for correction in event.corrections:
                source = correction.source
                correction_data[source]["attempts"] += 1
                correction_data[source]["confidences"].append(correction.confidence)

                if workflow_success and correction.applied:
                    correction_data[source]["successes"] += 1

                correction_data[source]["iterations"].append(max_iteration)

    def find_violation_patterns(self, days: int = 30, min_occurrences: int = 3) -> List[ViolationPattern]:
        """
        Identify common violation patterns.

        Args:
            days: Number of days to analyze
            min_occurrences: Minimum occurrences to include

        Returns:
            List of violation patterns sorted by occurrence
        """
        correlation_ids = self.event_store.get_recent_workflows(days=days)

        violation_data = defaultdict(lambda: {"count": 0, "severities": [], "resolved": 0, "fixes": []})

        for correlation_id in correlation_ids:
            workflow = self.event_store.get_workflow(correlation_id)
            if not workflow:
                continue

            # Find validation failures
            validation_events = [e for e in workflow if e.event_type == EventType.VALIDATION_FAILED]

            # Check if workflow eventually succeeded
            workflow_success = any(e.event_type == EventType.WRITE_SUCCESS for e in workflow)

            for event in validation_events:
                if not event.violations:
                    continue

                for violation in event.violations:
                    rule = violation.rule
                    violation_data[rule]["count"] += 1

                    # Track severity (convert to numeric)
                    severity_map = {"error": 3, "warning": 2, "info": 1}
                    violation_data[rule]["severities"].append(severity_map.get(violation.severity, 2))

                    if workflow_success:
                        violation_data[rule]["resolved"] += 1

                    # Track suggested fixes
                    if violation.suggested_fix:
                        violation_data[rule]["fixes"].append(violation.suggested_fix)

        # Build violation patterns
        patterns = []
        for rule, data in violation_data.items():
            if data["count"] >= min_occurrences:
                avg_severity = sum(data["severities"]) / len(data["severities"]) if data["severities"] else 2.0
                resolution_rate = data["resolved"] / data["count"] if data["count"] > 0 else 0.0

                # Get most common fixes
                fix_counter = Counter(data["fixes"])
                common_fixes = [fix for fix, _ in fix_counter.most_common(3)]

                patterns.append(
                    ViolationPattern(
                        rule=rule,
                        occurrences=data["count"],
                        avg_severity=avg_severity,
                        resolution_rate=resolution_rate,
                        common_fixes=common_fixes,
                    )
                )

        # Sort by occurrence
        patterns.sort(key=lambda p: p.occurrences, reverse=True)

        return patterns

    def get_workflow_metrics(self, days: int = 7) -> WorkflowMetrics:
        """
        Get high-level workflow performance metrics.

        Args:
            days: Number of days to analyze

        Returns:
            WorkflowMetrics with summary statistics
        """
        correlation_ids = self.event_store.get_recent_workflows(days=days)

        if not correlation_ids:
            return WorkflowMetrics(
                total_workflows=0,
                success_rate=0.0,
                avg_duration_ms=0.0,
                avg_iterations=0.0,
                avg_violations=0.0,
                most_common_intent="unknown",
                peak_hours=[],
            )

        successes = 0
        durations = []
        iterations = []
        violations_counts = []
        intents = []
        hours = []

        for correlation_id in correlation_ids:
            workflow = self.event_store.get_workflow(correlation_id)
            if not workflow:
                continue

            # Success determination
            if any(e.event_type == EventType.WRITE_SUCCESS for e in workflow):
                successes += 1

            # Duration calculation
            if len(workflow) >= 2:
                start_time = workflow[0].timestamp
                end_time = workflow[-1].timestamp
                duration_ms = (end_time - start_time).total_seconds() * 1000
                durations.append(duration_ms)

            # Iterations
            max_iteration = max(e.iteration_number for e in workflow)
            iterations.append(max_iteration)

            # Violations count
            violation_events = [e for e in workflow if e.event_type == EventType.VALIDATION_FAILED and e.violations]
            total_violations = sum(len(e.violations) for e in violation_events)
            violations_counts.append(total_violations)

            # Intent tracking
            intent_events = [e for e in workflow if e.intent]
            if intent_events:
                intents.append(intent_events[0].intent.primary_intent)

            # Time of day tracking
            hours.append(workflow[0].timestamp.hour)

        # Calculate metrics
        total_workflows = len(correlation_ids)
        success_rate = successes / total_workflows if total_workflows > 0 else 0.0

        avg_duration_ms = sum(durations) / len(durations) if durations else 0.0
        avg_iterations = sum(iterations) / len(iterations) if iterations else 1.0
        avg_violations = sum(violations_counts) / len(violations_counts) if violations_counts else 0.0

        # Most common intent
        intent_counter = Counter(intents)
        most_common_intent = intent_counter.most_common(1)[0][0] if intent_counter else "unknown"

        # Peak hours (top 3)
        hour_counter = Counter(hours)
        peak_hours = [hour for hour, _ in hour_counter.most_common(3)]

        return WorkflowMetrics(
            total_workflows=total_workflows,
            success_rate=success_rate,
            avg_duration_ms=avg_duration_ms,
            avg_iterations=avg_iterations,
            avg_violations=avg_violations,
            most_common_intent=most_common_intent,
            peak_hours=peak_hours,
        )

    def create_workflow_summary(self, correlation_id: str) -> Optional[WorkflowSummary]:
        """
        Create summary for a specific workflow.

        Args:
            correlation_id: Workflow to summarize

        Returns:
            WorkflowSummary or None if workflow not found
        """
        workflow = self.event_store.get_workflow(correlation_id)
        if not workflow:
            return None

        # Calculate metrics
        start_time = workflow[0].timestamp
        end_time = workflow[-1].timestamp
        duration_ms = (end_time - start_time).total_seconds() * 1000

        # Determine success
        success = any(e.event_type == EventType.WRITE_SUCCESS for e in workflow)

        # Count iterations
        max_iteration = max(e.iteration_number for e in workflow)

        # Count violations
        violation_events = [e for e in workflow if e.event_type == EventType.VALIDATION_FAILED and e.violations]
        violations_count = sum(len(e.violations) for e in violation_events)

        # Count applied corrections
        correction_events = [e for e in workflow if e.event_type == EventType.CORRECTION_GENERATED and e.corrections]
        corrections_applied = sum(sum(1 for c in e.corrections if c.applied) for e in correction_events)

        # Get intent category
        intent_category = "unknown"
        intent_events = [e for e in workflow if e.intent]
        if intent_events:
            intent_category = intent_events[0].intent.primary_intent

        # Determine final outcome
        final_event = workflow[-1]
        if final_event.event_type == EventType.WRITE_SUCCESS:
            final_outcome = "Write completed successfully"
        elif final_event.event_type == EventType.WRITE_FAILED:
            final_outcome = "Write failed"
        elif final_event.event_type == EventType.VALIDATION_PASSED:
            final_outcome = "Validation passed, pending write"
        else:
            final_outcome = f"Ended at: {final_event.event_type.value}"

        return WorkflowSummary(
            correlation_id=correlation_id,
            start_time=start_time,
            end_time=end_time,
            duration_ms=duration_ms,
            tool_name=workflow[0].tool_name,
            file_path=workflow[0].file_path,
            intent_category=intent_category,
            total_events=len(workflow),
            success=success,
            iterations=max_iteration,
            violations_count=violations_count,
            corrections_applied=corrections_applied,
            final_outcome=final_outcome,
            metadata={"event_types": [e.event_type.value for e in workflow]},
        )

    def find_improvement_opportunities(self, days: int = 30) -> Dict[str, List[str]]:
        """
        Identify areas for improvement based on patterns.

        Args:
            days: Number of days to analyze

        Returns:
            Dict with categories and improvement suggestions
        """
        opportunities = defaultdict(list)

        # Analyze correction effectiveness
        correction_stats = self.get_correction_stats(days=days)
        for source, stats in correction_stats.items():
            if stats.success_rate < 0.6:
                opportunities["low_success_corrections"].append(
                    f"{source} has only {stats.success_rate:.1%} success rate - review correction quality"
                )

            if stats.avg_iterations > 2.5:
                opportunities["high_iteration_corrections"].append(
                    f"{source} requires {stats.avg_iterations:.1f} iterations on average - improve first-attempt accuracy"
                )

        # Analyze violation patterns
        violation_patterns = self.find_violation_patterns(days=days)
        for pattern in violation_patterns[:5]:  # Top 5
            if pattern.resolution_rate < 0.5:
                opportunities["hard_to_resolve_violations"].append(
                    f"Rule '{pattern.rule}' only resolved {pattern.resolution_rate:.1%} of the time - needs better correction strategies"
                )

        # Analyze workflow metrics
        metrics = self.get_workflow_metrics(days=days)
        if metrics.success_rate < 0.8:
            opportunities["low_success_rate"].append(
                f"Overall success rate is {metrics.success_rate:.1%} - investigate common failure modes"
            )

        if metrics.avg_violations > 3:
            opportunities["high_violation_rate"].append(
                f"Average {metrics.avg_violations:.1f} violations per workflow - improve validation rules or code quality"
            )

        return dict(opportunities)

    def generate_report(self, days: int = 7) -> str:
        """
        Generate comprehensive analytics report.

        Args:
            days: Number of days to analyze

        Returns:
            Formatted report string
        """
        metrics = self.get_workflow_metrics(days=days)
        correction_stats = self.get_correction_stats(days=days)
        violation_patterns = self.find_violation_patterns(days=days, min_occurrences=2)
        opportunities = self.find_improvement_opportunities(days=days)

        report_lines = [
            "=" * 80,
            f"Event Memory Analytics Report - Last {days} Days",
            "=" * 80,
            "",
            "📊 WORKFLOW METRICS",
            "-" * 40,
            f"Total Workflows: {metrics.total_workflows}",
            f"Success Rate: {metrics.success_rate:.1%}",
            f"Avg Duration: {metrics.avg_duration_ms:.0f}ms",
            f"Avg Iterations: {metrics.avg_iterations:.1f}",
            f"Avg Violations: {metrics.avg_violations:.1f}",
            f"Most Common Intent: {metrics.most_common_intent}",
            f"Peak Activity Hours: {metrics.peak_hours}",
            "",
            "🔧 CORRECTION EFFECTIVENESS",
            "-" * 40,
        ]

        if correction_stats:
            for source, stats in correction_stats.items():
                report_lines.extend(
                    [
                        f"",
                        f"{source.upper()}:",
                        f"  Attempts: {stats.total_attempts}",
                        f"  Successes: {stats.successful_corrections}",
                        f"  Success Rate: {stats.success_rate:.1%}",
                        f"  Avg Confidence: {stats.avg_confidence:.2f}",
                        f"  Avg Iterations: {stats.avg_iterations:.1f}",
                    ]
                )
        else:
            report_lines.append("No correction data available")

        report_lines.extend(
            [
                "",
                "⚠️  VIOLATION PATTERNS",
                "-" * 40,
            ]
        )

        if violation_patterns:
            for pattern in violation_patterns[:10]:  # Top 10
                report_lines.extend(
                    [
                        f"",
                        f"Rule: {pattern.rule}",
                        f"  Occurrences: {pattern.occurrences}",
                        f"  Avg Severity: {pattern.avg_severity:.1f}",
                        f"  Resolution Rate: {pattern.resolution_rate:.1%}",
                    ]
                )
                if pattern.common_fixes:
                    report_lines.append(f"  Common Fixes: {len(pattern.common_fixes)}")
        else:
            report_lines.append("No violation patterns detected")

        report_lines.extend(
            [
                "",
                "💡 IMPROVEMENT OPPORTUNITIES",
                "-" * 40,
            ]
        )

        if opportunities:
            for category, suggestions in opportunities.items():
                report_lines.append(f"")
                report_lines.append(f"{category.replace('_', ' ').title()}:")
                for suggestion in suggestions:
                    report_lines.append(f"  - {suggestion}")
        else:
            report_lines.append("No improvement opportunities identified - system performing well!")

        report_lines.extend(
            [
                "",
                "=" * 80,
            ]
        )

        return "\n".join(report_lines)
