#!/usr/bin/env python3
"""
Quality Dashboard - ONEX v2.0 Framework

Rich terminal dashboard for quality gate visualization.
Provides beautiful, comprehensive quality reporting with:
- Overall quality status and score
- Detailed gate results table
- Performance analytics
- Category-based breakdown
- Actionable recommendations

Uses the rich library for terminal styling and layout.
"""


from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table

from ..models.model_gate_aggregation import (
    ModelPipelineQualityReport,
)


class QualityDashboard:
    """
    Rich terminal dashboard for quality gate visualization.

    Features:
    - Color-coded status indicators
    - Comprehensive gate results table
    - Performance metrics panel
    - Category breakdown
    - Recommendations and critical issues
    - Quality score visualization
    """

    def __init__(self):
        """Initialize quality dashboard."""
        self.console = Console()

    def display_summary(self, report: ModelPipelineQualityReport) -> None:
        """
        Display comprehensive quality summary.

        Args:
            report: Pipeline quality report to display
        """
        # Create layout
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=9),
            Layout(name="main"),
            Layout(name="footer", size=12),
        )

        # Split main into left (gates) and right (performance + categories)
        layout["main"].split_row(
            Layout(name="gates", ratio=2),
            Layout(name="side", ratio=1),
        )

        # Split side into performance and categories
        layout["side"].split_column(
            Layout(name="performance"),
            Layout(name="categories"),
        )

        # Populate layout sections
        layout["header"].update(self._create_header(report))
        layout["gates"].update(self._create_gate_table(report))
        layout["performance"].update(self._create_performance_panel(report))
        layout["categories"].update(self._create_category_panel(report))
        layout["footer"].update(self._create_recommendations(report))

        # Print layout
        self.console.print(layout)

    def display_compact_summary(self, report: ModelPipelineQualityReport) -> None:
        """
        Display compact quality summary (single panel).

        Args:
            report: Pipeline quality report to display
        """
        agg = report.gate_aggregation

        # Create compact summary text
        lines = []
        lines.append(
            f"Quality Score: {agg.overall_quality_score:.1%} (Grade: {agg.quality_grade})"
        )
        lines.append(
            f"Gates: {agg.passed_gates}/{agg.total_gates} passed "
            f"({agg.compliance_rate:.1%} compliance)"
        )
        lines.append(
            f"Performance: {agg.performance_compliance_rate:.1%} meeting targets"
        )

        if agg.has_blocking_failures:
            lines.append(f"\nBlocking Failures: {len(agg.blocking_failures)}")
            for failure in agg.blocking_failures[:2]:
                lines.append(f"  - {failure}")

        if report.critical_issues:
            lines.append(f"\nCritical Issues: {len(report.critical_issues)}")

        summary_text = "\n".join(lines)

        # Color based on status
        border_color = self._get_status_color(report.overall_status)

        panel = Panel(
            summary_text,
            title=f"Quality Report: {report.overall_status}",
            border_style=border_color,
        )

        self.console.print(panel)

    def _create_header(self, report: ModelPipelineQualityReport) -> Panel:
        """Create header with overall status."""
        agg = report.gate_aggregation

        status_emoji = self._get_status_emoji(report.overall_status)
        quality_bar = self._create_quality_bar(agg.overall_quality_score)

        header_lines = [
            f"{status_emoji} Pipeline Quality: {report.overall_status}",
            f"Correlation ID: {report.correlation_id[:16]}...",
            "",
            f"Quality Score: {agg.overall_quality_score:.1%} (Grade: {agg.quality_grade})",
            quality_bar,
            "",
            f"Gates: {agg.passed_gates}/{agg.total_gates} passed  |  "
            f"Performance Compliance: {agg.performance_compliance_rate:.1%}",
        ]

        header_text = "\n".join(header_lines)
        border_color = self._get_status_color(report.overall_status)

        return Panel(
            header_text,
            title="Quality Summary",
            border_style=border_color,
            padding=(1, 2),
        )

    def _create_gate_table(self, report: ModelPipelineQualityReport) -> Table:
        """Create table of gate results."""
        table = Table(
            title="Quality Gate Results", show_header=True, header_style="bold"
        )

        table.add_column("Gate", style="cyan", no_wrap=True)
        table.add_column("Category", style="magenta")
        table.add_column("Status", justify="center", style="bold")
        table.add_column("Time", justify="right", style="yellow")
        table.add_column("Target", justify="right", style="dim")
        table.add_column("Perf", justify="center")

        # Add rows for each gate in timeline
        for entry in report.gate_aggregation.execution_timeline:
            status_text = self._format_status(entry["status"], entry["passed"])
            perf_indicator = self._format_performance(entry["meets_performance_target"])

            # Truncate category for display
            category_short = (
                entry["category"].replace("_validation", "").replace("_", " ").title()
            )

            table.add_row(
                entry["gate_name"],
                category_short,
                status_text,
                f"{entry['execution_time_ms']}ms",
                f"{entry['performance_target_ms']}ms",
                perf_indicator,
            )

        return table

    def _create_performance_panel(self, report: ModelPipelineQualityReport) -> Panel:
        """Create performance metrics panel."""
        agg = report.gate_aggregation

        lines = []
        lines.append(f"Total Execution: {agg.total_execution_time_ms}ms")
        lines.append(f"Average Gate: {agg.average_execution_time_ms:.1f}ms")
        lines.append("")

        if agg.slowest_gate:
            slowest = agg.slowest_gate
            lines.append(f"Slowest: {slowest['gate_name']}")
            lines.append(
                f"  {slowest['execution_time_ms']}ms (target: {slowest['performance_target_ms']}ms)"
            )

            if slowest["exceeded_target_by_ms"] > 0:
                lines.append(f"  Exceeded by: {slowest['exceeded_target_by_ms']}ms")

        if agg.fastest_gate:
            fastest = agg.fastest_gate
            lines.append("")
            lines.append(f"Fastest: {fastest['gate_name']}")
            lines.append(f"  {fastest['execution_time_ms']}ms")

        perf_text = "\n".join(lines)

        return Panel(
            perf_text,
            title="Performance Metrics",
            border_style="blue",
            padding=(1, 1),
        )

    def _create_category_panel(self, report: ModelPipelineQualityReport) -> Panel:
        """Create category breakdown panel."""
        agg = report.gate_aggregation

        lines = []

        # Sort categories by pass rate (worst first)
        sorted_categories = sorted(
            agg.category_summary.items(),
            key=lambda x: x[1].pass_rate,
        )

        for category, summary in sorted_categories:
            status_emoji = (
                "✅"
                if summary.pass_rate == 1.0
                else "❌" if summary.has_failures else "⚠️"
            )
            lines.append(
                f"{status_emoji} {category.display_name}: "
                f"{summary.passed_gates}/{summary.total_gates}"
            )

        if not lines:
            lines.append("No category data available")

        category_text = "\n".join(lines)

        return Panel(
            category_text,
            title="Category Breakdown",
            border_style="green",
            padding=(1, 1),
        )

    def _create_recommendations(self, report: ModelPipelineQualityReport) -> Panel:
        """Create recommendations panel."""
        lines = []

        # Critical issues first
        if report.critical_issues:
            lines.append("[bold red]Critical Issues:[/bold red]")
            for issue in report.critical_issues:
                lines.append(f"  🚨 {issue}")
            lines.append("")

        # Then recommendations
        if report.recommendations:
            lines.append("[bold yellow]Recommendations:[/bold yellow]")
            for rec in report.recommendations[:5]:  # Show top 5
                lines.append(f"  💡 {rec}")

            if len(report.recommendations) > 5:
                lines.append(f"  ... and {len(report.recommendations) - 5} more")

        if not lines:
            lines.append("[green]No issues found. Quality is excellent![/green]")

        rec_text = "\n".join(lines)

        border_color = (
            "red"
            if report.critical_issues
            else "yellow" if report.recommendations else "green"
        )

        return Panel(
            rec_text,
            title="Action Items",
            border_style=border_color,
            padding=(1, 2),
        )

    def _create_quality_bar(self, score: float, width: int = 40) -> str:
        """Create visual quality score bar."""
        filled = int(score * width)
        empty = width - filled

        # Color based on score
        if score >= 0.9:
            color = "green"
        elif score >= 0.7:
            color = "yellow"
        else:
            color = "red"

        bar = f"[{color}]{'█' * filled}[/{color}]{'░' * empty}"
        return bar

    def _get_status_emoji(self, status: str) -> str:
        """Get emoji for status."""
        emojis = {
            "SUCCESS": "✅",
            "WARNING": "⚠️",
            "PARTIAL": "⚡",
            "FAILED": "❌",
        }
        return emojis.get(status, "❓")

    def _get_status_color(self, status: str) -> str:
        """Get color for status."""
        colors = {
            "SUCCESS": "green",
            "WARNING": "yellow",
            "PARTIAL": "yellow",
            "FAILED": "red",
        }
        return colors.get(status, "white")

    def _format_status(self, status: str, passed: bool) -> str:
        """Format status text with color."""
        if status == "passed" or passed:
            return "[green]✓ PASS[/green]"
        elif status == "failed":
            return "[red]✗ FAIL[/red]"
        elif status == "skipped":
            return "[dim]⊝ SKIP[/dim]"
        else:
            return "[yellow]? UNKNOWN[/yellow]"

    def _format_performance(self, meets_target: bool) -> str:
        """Format performance indicator."""
        return "[green]🚀[/green]" if meets_target else "[yellow]🐌[/yellow]"

    def print_text_summary(self, report: ModelPipelineQualityReport) -> None:
        """
        Print plain text summary (no rich formatting).

        Useful for environments that don't support rich terminal output.

        Args:
            report: Pipeline quality report to display
        """
        agg = report.gate_aggregation

        print("\n" + "=" * 70)
        print(f"QUALITY REPORT: {report.overall_status}")
        print("=" * 70)
        print(
            f"Quality Score: {agg.overall_quality_score:.1%} (Grade: {agg.quality_grade})"
        )
        print(f"Gates: {agg.passed_gates}/{agg.total_gates} passed")
        print(f"Compliance: {agg.compliance_rate:.1%}")
        print(f"Performance Compliance: {agg.performance_compliance_rate:.1%}")
        print()

        if agg.blocking_failures:
            print("BLOCKING FAILURES:")
            for failure in agg.blocking_failures:
                print(f"  - {failure}")
            print()

        if report.critical_issues:
            print("CRITICAL ISSUES:")
            for issue in report.critical_issues:
                print(f"  - {issue}")
            print()

        if report.recommendations:
            print("RECOMMENDATIONS:")
            for rec in report.recommendations[:5]:
                print(f"  - {rec}")
            print()

        print("=" * 70)
