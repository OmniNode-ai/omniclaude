#!/usr/bin/env python3
"""
Terminal Dashboard with Colors
Real-time system monitoring in your terminal
"""

import io
import os
import re
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

# Import the dashboard logic
from ..system_dashboard_md import SystemDashboard


# ANSI Color Codes
class Colors:
    """ANSI color codes for terminal output"""

    RESET = "\033[0m"
    BOLD = "\033[1m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright foreground colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Background colors
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"


def get_terminal_size() -> Tuple[int, int]:
    """Get terminal dimensions (width, height)"""
    try:
        size = os.get_terminal_size()
        return (size.columns, size.lines)
    except Exception:
        return (100, 40)  # Default fallback


def clear_screen():
    """Clear terminal screen"""
    # Use ANSI escape sequence to clear screen (B605 fix - avoids os.system)
    # \033[2J clears entire screen, \033[H moves cursor to home position
    # This is safer than os.system() and works across platforms
    print("\033[2J\033[H", end="")


def colorize(text: str, color: str, bold: bool = False) -> str:
    """Colorize text"""
    prefix = Colors.BOLD if bold else ""
    return f"{prefix}{color}{text}{Colors.RESET}"


def status_icon(status: str) -> str:
    """Get colored status icon"""
    icons = {
        "excellent": colorize("✅", Colors.BRIGHT_GREEN, bold=True),
        "good": colorize("✅", Colors.GREEN, bold=True),
        "fair": colorize("⚠️ ", Colors.YELLOW, bold=True),
        "poor": colorize("❌", Colors.RED, bold=True),
        "critical": colorize("🔴", Colors.BRIGHT_RED, bold=True),
    }
    return icons.get(status.lower(), "●")


def health_banner(score: float, label: str) -> str:
    """Generate colored health banner"""
    if score >= 90:
        color = Colors.BRIGHT_GREEN
        emoji = "🟢"
        status = "EXCELLENT"
    elif score >= 75:
        color = Colors.GREEN
        emoji = "🟡"
        status = "GOOD"
    elif score >= 60:
        color = Colors.YELLOW
        emoji = "🟠"
        status = "FAIR"
    else:
        color = Colors.RED
        emoji = "🔴"
        status = "POOR"

    return f"{emoji} {colorize(status, color, bold=True)} {colorize(f'({score:.1f}/100)', Colors.BRIGHT_BLACK)}"


def metric_status(
    value: float, good_threshold: float, fair_threshold: float, reverse: bool = False
) -> str:
    """Get status icon based on thresholds"""
    if reverse:
        # Lower is better (e.g., latency)
        if value <= good_threshold:
            return status_icon("excellent")
        elif value <= fair_threshold:
            return status_icon("fair")
        else:
            return status_icon("poor")
    else:
        # Higher is better (e.g., confidence)
        if value >= good_threshold:
            return status_icon("excellent")
        elif value >= fair_threshold:
            return status_icon("fair")
        else:
            return status_icon("poor")


def print_header(width: int, height: int = None, layout_mode: str = "single"):
    """Print dashboard header"""
    title = "🎯 OmniClaude System Dashboard"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Optional: show terminal info in debug mode
    if height:
        size_info = f"Terminal: {width}x{height} cols/rows | Layout: {layout_mode}"
    else:
        size_info = None

    print()
    print(colorize("═" * width, Colors.BRIGHT_BLUE))
    print(colorize(title.center(width), Colors.BRIGHT_CYAN, bold=True))
    print(colorize(timestamp.center(width), Colors.BRIGHT_BLACK))
    if size_info:
        print(colorize(size_info.center(width), Colors.BRIGHT_BLACK))
    print(colorize("═" * width, Colors.BRIGHT_BLUE))
    print()


def print_system_health(health: Dict[str, Any], width: int):
    """Print system health section"""
    print(colorize("┌─ System Health", Colors.BRIGHT_YELLOW, bold=True))
    print(colorize("│", Colors.BRIGHT_YELLOW))

    if not health:
        print(
            colorize("│  ", Colors.BRIGHT_YELLOW)
            + colorize("⚠️  SYSTEM OFFLINE - No recent activity", Colors.RED, bold=True)
        )
        print(colorize("└" + "─" * (width - 2), Colors.BRIGHT_YELLOW))
        return

    # Calculate health score
    # Use explicit None check to preserve zero values
    avg_conf_raw = health.get("avg_confidence")
    avg_conf = float(avg_conf_raw if avg_conf_raw is not None else 0)
    routing_health = min(100, avg_conf * 100)

    total_events_raw = health.get("total_events")
    total_events = int(total_events_raw if total_events_raw is not None else 0)
    processed_events_raw = health.get("processed_events")
    processed_events = int(
        processed_events_raw if processed_events_raw is not None else 0
    )
    hook_health = 100 if total_events == 0 else (100 * processed_events / total_events)

    hit_rate_raw = health.get("hit_rate")
    cache_health = float(hit_rate_raw if hit_rate_raw is not None else 0)

    overall_score = routing_health * 0.5 + hook_health * 0.3 + cache_health * 0.2

    print(
        colorize("│  ", Colors.BRIGHT_YELLOW) + health_banner(overall_score, "Overall")
    )
    print(colorize("└" + "─" * (width - 2), Colors.BRIGHT_YELLOW))
    print()


def print_metrics(health: Dict[str, Any], width: int):
    """Print quick metrics table"""
    if not health:
        return

    print(colorize("┌─ Quick Metrics (Last 24h)", Colors.BRIGHT_MAGENTA, bold=True))
    print(colorize("│", Colors.BRIGHT_MAGENTA))

    # Header
    print(
        colorize("│  ", Colors.BRIGHT_MAGENTA)
        + colorize("Metric".ljust(25), Colors.BRIGHT_WHITE, bold=True)
        + colorize("Value".ljust(30), Colors.BRIGHT_WHITE, bold=True)
        + colorize("Status", Colors.BRIGHT_WHITE, bold=True)
    )
    print(colorize("│  " + "─" * 60, Colors.BRIGHT_BLACK))

    # Routing decisions
    # Use explicit None check to preserve zero values
    total_decisions_raw = health.get("total_decisions")
    routing_decisions = int(
        total_decisions_raw if total_decisions_raw is not None else 0
    )
    status = status_icon("excellent") if routing_decisions > 0 else status_icon("fair")
    print(
        colorize("│  ", Colors.BRIGHT_MAGENTA)
        + "Routing Decisions".ljust(25)
        + colorize(f"{routing_decisions}", Colors.BRIGHT_CYAN, bold=True).ljust(39)
        + status
    )

    # Avg confidence
    # Use explicit None check to preserve zero values
    avg_conf_raw = health.get("avg_confidence")
    avg_conf = float(avg_conf_raw if avg_conf_raw is not None else 0) * 100
    status = metric_status(avg_conf, 85, 70)
    print(
        colorize("│  ", Colors.BRIGHT_MAGENTA)
        + "Avg Confidence".ljust(25)
        + colorize(
            f"{avg_conf:.1f}%",
            Colors.BRIGHT_GREEN if avg_conf >= 85 else Colors.YELLOW,
            bold=True,
        ).ljust(39)
        + status
    )

    # Avg routing time
    # Use explicit None check to preserve zero values
    avg_routing_ms_raw = health.get("avg_routing_ms")
    avg_routing_ms = float(avg_routing_ms_raw if avg_routing_ms_raw is not None else 0)
    status = metric_status(avg_routing_ms, 100, 500, reverse=True)
    color = (
        Colors.BRIGHT_GREEN
        if avg_routing_ms < 100
        else Colors.YELLOW if avg_routing_ms < 500 else Colors.RED
    )
    print(
        colorize("│  ", Colors.BRIGHT_MAGENTA)
        + "Avg Routing Time".ljust(25)
        + colorize(f"{avg_routing_ms:.0f}ms", color, bold=True).ljust(39)
        + status
    )

    # Hook events
    # Use explicit None check to preserve zero values
    total_events_raw = health.get("total_events")
    total_events = int(total_events_raw if total_events_raw is not None else 0)
    processed_events_raw = health.get("processed_events")
    processed_events = int(
        processed_events_raw if processed_events_raw is not None else 0
    )
    pending_events_raw = health.get("pending_events")
    pending_events = int(pending_events_raw if pending_events_raw is not None else 0)
    status = (
        status_icon("excellent")
        if pending_events == 0
        else status_icon("fair") if pending_events < 100 else status_icon("poor")
    )
    print(
        colorize("│  ", Colors.BRIGHT_MAGENTA)
        + "Hook Events".ljust(25)
        + f"{total_events} ({colorize(str(processed_events) + ' processed', Colors.GREEN)}, {colorize(str(pending_events) + ' pending', Colors.YELLOW if pending_events > 0 else Colors.GREEN)})".ljust(
            67
        )
        + status
    )

    # Cache hit rate
    # Use explicit None check to preserve zero values
    hit_rate_raw = health.get("hit_rate")
    cache_hit_rate = float(hit_rate_raw if hit_rate_raw is not None else 0)
    status = metric_status(cache_hit_rate, 60, 30)
    color = (
        Colors.BRIGHT_GREEN
        if cache_hit_rate >= 60
        else Colors.YELLOW if cache_hit_rate >= 30 else Colors.RED
    )
    print(
        colorize("│  ", Colors.BRIGHT_MAGENTA)
        + "Cache Hit Rate".ljust(25)
        + colorize(f"{cache_hit_rate:.1f}%", color, bold=True).ljust(39)
        + status
    )

    print(colorize("└" + "─" * (width - 2), Colors.BRIGHT_MAGENTA))
    print()


def print_top_agents(agents: List[Dict[str, Any]], width: int, max_items: int = 5):
    """Print top agents section"""
    if not agents:
        return

    print(colorize("┌─ Top Agents (Last 24h)", Colors.BRIGHT_CYAN, bold=True))
    print(colorize("│", Colors.BRIGHT_CYAN))

    # Header
    print(
        colorize("│  ", Colors.BRIGHT_CYAN)
        + colorize("Agent".ljust(35), Colors.BRIGHT_WHITE, bold=True)
        + colorize("Selections".ljust(12), Colors.BRIGHT_WHITE, bold=True)
        + colorize("Avg Conf".ljust(12), Colors.BRIGHT_WHITE, bold=True)
        + colorize("Avg Routing", Colors.BRIGHT_WHITE, bold=True)
    )
    print(colorize("│  " + "─" * 70, Colors.BRIGHT_BLACK))

    for agent in agents[:5]:
        agent_name = agent["selected_agent"][:33]
        selections = agent["selections"]
        avg_conf = float(agent["avg_confidence"])
        avg_routing_ms = float(agent["avg_routing_ms"])

        conf_color = Colors.BRIGHT_GREEN if avg_conf >= 85 else Colors.YELLOW
        routing_color = (
            Colors.BRIGHT_GREEN
            if avg_routing_ms < 100
            else Colors.YELLOW if avg_routing_ms < 500 else Colors.RED
        )

        print(
            colorize("│  ", Colors.BRIGHT_CYAN)
            + colorize(agent_name.ljust(35), Colors.WHITE)
            + colorize(str(selections).ljust(12), Colors.BRIGHT_CYAN, bold=True)
            + colorize(f"{avg_conf:.1f}%".ljust(12), conf_color, bold=True)
            + colorize(f"{avg_routing_ms:.0f}ms", routing_color, bold=True)
        )

    print(colorize("└" + "─" * (width - 2), Colors.BRIGHT_CYAN))
    print()


def print_alerts(health: Dict[str, Any], width: int):
    """Print alerts section"""
    if not health:
        return

    alerts = []

    # Use explicit None check to preserve zero values
    pending_events_raw = health.get("pending_events")
    pending_events = int(pending_events_raw if pending_events_raw is not None else 0)
    if pending_events > 100:
        alerts.append(("CRITICAL", "Hook event backlog >100 - processor may be down"))

    hit_rate_raw = health.get("hit_rate")
    cache_hit_rate = float(hit_rate_raw if hit_rate_raw is not None else 0)
    if cache_hit_rate == 0:
        alerts.append(("CRITICAL", "Cache system not functioning (0% hit rate)"))

    avg_conf_raw = health.get("avg_confidence")
    avg_conf = float(avg_conf_raw if avg_conf_raw is not None else 0) * 100
    if avg_conf < 70:
        alerts.append(
            (
                "WARNING",
                f"Low average confidence {avg_conf:.1f}% - review agent definitions",
            )
        )

    total_decisions_raw = health.get("total_decisions")
    total_decisions = int(total_decisions_raw if total_decisions_raw is not None else 0)
    if total_decisions == 0:
        alerts.append(("INFO", "No routing activity in last 24 hours"))

    if not alerts:
        return

    print(colorize("┌─ 🚨 Alerts", Colors.BRIGHT_RED, bold=True))
    print(colorize("│", Colors.BRIGHT_RED))

    for level, message in alerts:
        if level == "CRITICAL":
            icon = colorize("🔴", Colors.BRIGHT_RED)
            text_color = Colors.RED
        elif level == "WARNING":
            icon = colorize("🟠", Colors.YELLOW)
            text_color = Colors.YELLOW
        else:
            icon = colorize("🟡", Colors.BLUE)
            text_color = Colors.BRIGHT_BLACK

        print(
            colorize("│  ", Colors.BRIGHT_RED)
            + icon
            + " "
            + colorize(level + ": ", text_color, bold=True)
            + colorize(message, text_color)
        )

    print(colorize("└" + "─" * (width - 2), Colors.BRIGHT_RED))
    print()


def print_recent_activity(
    routing_decisions: List[Dict[str, Any]],
    hook_events: List[Dict[str, Any]],
    width: int,
    max_items: int = 10,
):
    """Print recent activity timeline"""
    print(
        colorize(
            f"┌─ 📅 Recent Activity Timeline (Last {max_items})",
            Colors.BRIGHT_GREEN,
            bold=True,
        )
    )
    print(colorize("│", Colors.BRIGHT_GREEN))

    if not routing_decisions:
        print(
            colorize("│  ", Colors.BRIGHT_GREEN)
            + colorize("No recent activity", Colors.BRIGHT_BLACK)
        )
        print(colorize("└" + "─" * (width - 2), Colors.BRIGHT_GREEN))
        return

    # Header
    print(
        colorize("│  ", Colors.BRIGHT_GREEN)
        + colorize("Timestamp".ljust(22), Colors.BRIGHT_WHITE, bold=True)
        + colorize("Event".ljust(30), Colors.BRIGHT_WHITE, bold=True)
        + colorize("Details".ljust(50), Colors.BRIGHT_WHITE, bold=True)
    )
    print(colorize("│  " + "─" * (width - 4), Colors.BRIGHT_BLACK))

    for decision in routing_decisions[:max_items]:
        timestamp = decision["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        agent = decision["selected_agent"][:28]
        confidence = float(decision["confidence_score"]) * 100
        routing_ms = int(decision["routing_time_ms"] or 0)

        conf_color = (
            Colors.BRIGHT_GREEN
            if confidence >= 95
            else Colors.GREEN if confidence >= 85 else Colors.YELLOW
        )
        time_color = (
            Colors.BRIGHT_GREEN
            if routing_ms < 100
            else Colors.YELLOW if routing_ms < 500 else Colors.RED
        )

        event_type = colorize("Agent Routing", Colors.CYAN, bold=True)
        details = f"{colorize(agent, Colors.WHITE)} • {colorize(f'{confidence:.0f}%', conf_color)} • {colorize(f'{routing_ms}ms', time_color)}"

        print(
            colorize("│  ", Colors.BRIGHT_GREEN)
            + colorize(timestamp, Colors.BRIGHT_CYAN).ljust(31)
            + event_type.ljust(45)
            + details
        )

    print(colorize("└" + "─" * (width - 2), Colors.BRIGHT_GREEN))
    print()


def print_agent_details(
    agent_stats: List[Dict[str, Any]], width: int, max_items: int = 8
):
    """Print detailed agent statistics"""
    if not agent_stats:
        return

    print(
        colorize(
            "┌─ 🤖 Detailed Agent Statistics (Last 24h)", Colors.BRIGHT_BLUE, bold=True
        )
    )
    print(colorize("│", Colors.BRIGHT_BLUE))

    # Header
    print(
        colorize("│  ", Colors.BRIGHT_BLUE)
        + colorize("Agent".ljust(35), Colors.BRIGHT_WHITE, bold=True)
        + colorize("Total".ljust(7), Colors.BRIGHT_WHITE, bold=True)
        + colorize("Excellent".ljust(11), Colors.BRIGHT_WHITE, bold=True)
        + colorize("Good".ljust(7), Colors.BRIGHT_WHITE, bold=True)
        + colorize("Poor".ljust(7), Colors.BRIGHT_WHITE, bold=True)
        + colorize("Avg Conf".ljust(10), Colors.BRIGHT_WHITE, bold=True)
        + colorize("Avg Time", Colors.BRIGHT_WHITE, bold=True)
    )
    print(colorize("│  " + "─" * 90, Colors.BRIGHT_BLACK))

    for stats in agent_stats[:max_items]:
        agent_name = stats["selected_agent"][:33]
        total = stats["total_selections"]
        excellent = stats["excellent_count"]
        good = stats["good_count"]
        poor = stats["poor_count"]
        avg_conf = float(stats["avg_confidence"])
        avg_routing = float(stats["avg_routing_ms"])

        # Color coding
        conf_color = (
            Colors.BRIGHT_GREEN
            if avg_conf >= 95
            else Colors.GREEN if avg_conf >= 85 else Colors.YELLOW
        )
        time_color = (
            Colors.BRIGHT_GREEN
            if avg_routing < 100
            else Colors.YELLOW if avg_routing < 500 else Colors.RED
        )

        print(
            colorize("│  ", Colors.BRIGHT_BLUE)
            + colorize(agent_name.ljust(35), Colors.WHITE)
            + colorize(str(total).ljust(7), Colors.BRIGHT_CYAN, bold=True)
            + colorize(str(excellent).ljust(11), Colors.BRIGHT_GREEN)
            + colorize(str(good).ljust(7), Colors.GREEN)
            + colorize(
                str(poor).ljust(7), Colors.RED if poor > 0 else Colors.BRIGHT_BLACK
            )
            + colorize(f"{avg_conf:.1f}%".ljust(10), conf_color, bold=True)
            + colorize(f"{avg_routing:.0f}ms", time_color, bold=True)
        )

    print(colorize("└" + "─" * (width - 2), Colors.BRIGHT_BLUE))
    print()


def print_system_info(health: Dict[str, Any], width: int):
    """Print additional system information"""
    if not health:
        return

    print(colorize("┌─ 🔧 System Information", Colors.BRIGHT_MAGENTA, bold=True))
    print(colorize("│", Colors.BRIGHT_MAGENTA))

    # Time range
    first_decision = health.get("first_decision")
    last_decision = health.get("last_decision")

    if first_decision and last_decision:
        duration = last_decision - first_decision
        hours = duration.total_seconds() / 3600

        print(
            colorize("│  ", Colors.BRIGHT_MAGENTA)
            + colorize("Activity Period: ", Colors.WHITE, bold=True)
            + colorize(
                f"{hours:.1f} hours ({first_decision.strftime('%H:%M')} - {last_decision.strftime('%H:%M')})",
                Colors.BRIGHT_CYAN,
            )
        )

    # Database status
    print(
        colorize("│  ", Colors.BRIGHT_MAGENTA)
        + colorize("Database: ", Colors.WHITE, bold=True)
        + colorize("✅ Connected", Colors.BRIGHT_GREEN)
        + colorize(" (omninode_bridge @ localhost:5436)", Colors.BRIGHT_BLACK)
    )

    # Total queries
    total_queries_raw = health.get("total_queries")
    total_queries = int(total_queries_raw if total_queries_raw is not None else 0)
    if total_queries > 0:
        print(
            colorize("│  ", Colors.BRIGHT_MAGENTA)
            + colorize("Router Queries: ", Colors.WHITE, bold=True)
            + colorize(f"{total_queries}", Colors.BRIGHT_CYAN)
        )

    print(colorize("└" + "─" * (width - 2), Colors.BRIGHT_MAGENTA))
    print()


def print_issues(issues: List[Dict[str, Any]], width: int):
    """Print system issues and problems"""
    if not issues:
        print(colorize("┌─ ✅ No Issues Detected", Colors.BRIGHT_GREEN, bold=True))
        print(colorize("│", Colors.BRIGHT_GREEN))
        print(
            colorize("│  ", Colors.BRIGHT_GREEN)
            + colorize("All systems operational!", Colors.BRIGHT_GREEN, bold=True)
        )
        print(colorize("└" + "─" * (width - 2), Colors.BRIGHT_GREEN))
        print()
        return

    print(colorize("┌─ ⚠️  System Issues & Problems", Colors.BRIGHT_RED, bold=True))
    print(colorize("│", Colors.BRIGHT_RED))

    # Group by severity
    critical = [i for i in issues if i["severity"] == "critical"]
    warnings = [i for i in issues if i["severity"] == "warning"]
    info = [i for i in issues if i["severity"] == "info"]

    def print_issue_group(issue_list, severity_label, icon, color):
        if not issue_list:
            return

        print(colorize("│", Colors.BRIGHT_RED))
        print(
            colorize("│  ", Colors.BRIGHT_RED)
            + colorize(f"{icon} {severity_label}:", color, bold=True)
        )

        for issue in issue_list:
            print(
                colorize("│  ", Colors.BRIGHT_RED)
                + colorize("  • ", color)
                + colorize(f"[{issue['category']}] ", Colors.WHITE, bold=True)
                + colorize(issue["issue"], color)
            )

            if issue.get("details"):
                print(
                    colorize("│  ", Colors.BRIGHT_RED)
                    + colorize("    ", Colors.BRIGHT_BLACK)
                    + colorize(issue["details"], Colors.BRIGHT_BLACK)
                )

            if issue.get("impact"):
                print(
                    colorize("│  ", Colors.BRIGHT_RED)
                    + colorize("    Impact: ", Colors.BRIGHT_BLACK)
                    + colorize(issue["impact"], Colors.YELLOW)
                )

    print_issue_group(critical, "CRITICAL", "🔴", Colors.RED)
    print_issue_group(warnings, "WARNINGS", "🟠", Colors.YELLOW)
    print_issue_group(info, "INFO", "🔵", Colors.BLUE)

    print(colorize("└" + "─" * (width - 2), Colors.BRIGHT_RED))
    print()


def print_footer(width: int):
    """Print dashboard footer"""
    print(colorize("═" * width, Colors.BRIGHT_BLUE))
    print(
        colorize(
            "Press Ctrl+C to exit | Run `python3 claude_hooks/tools/dashboard_tui.py` to refresh".center(
                width
            ),
            Colors.BRIGHT_BLACK,
        )
    )
    print(colorize("═" * width, Colors.BRIGHT_BLUE))
    print()


def capture_section_output(func, *args, **kwargs) -> List[str]:
    """Capture output of a print function as list of lines"""
    f = io.StringIO()
    with redirect_stdout(f):
        func(*args, **kwargs)

    output = f.getvalue()
    return output.split("\n") if output else []


# Compile ANSI escape pattern once for efficiency
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def print_columns(
    left_lines: List[str],
    right_lines: List[str],
    left_width: int,
    right_width: int,
    separator: str = "  ",
):
    """Print two columns side by side"""
    max_lines = max(len(left_lines), len(right_lines))

    for i in range(max_lines):
        left_line = left_lines[i] if i < len(left_lines) else ""
        right_line = right_lines[i] if i < len(right_lines) else ""

        # Strip ANSI codes to calculate actual visible length
        visible_left = ANSI_ESCAPE.sub("", left_line)

        # Pad left column to align right column
        padding_needed = max(0, left_width - len(visible_left))
        print(left_line + (" " * padding_needed) + separator + right_line)


def print_three_columns(
    left_lines: List[str],
    middle_lines: List[str],
    right_lines: List[str],
    left_width: int,
    middle_width: int,
    right_width: int,
    separator: str = "  ",
):
    """Print three columns side by side"""
    max_lines = max(len(left_lines), len(middle_lines), len(right_lines))

    for i in range(max_lines):
        left_line = left_lines[i] if i < len(left_lines) else ""
        middle_line = middle_lines[i] if i < len(middle_lines) else ""
        right_line = right_lines[i] if i < len(right_lines) else ""

        # Calculate visible lengths
        visible_left = ANSI_ESCAPE.sub("", left_line)
        visible_middle = ANSI_ESCAPE.sub("", middle_line)

        # Pad columns to align
        left_padding = max(0, left_width - len(visible_left))
        middle_padding = max(0, middle_width - len(visible_middle))

        print(
            left_line
            + (" " * left_padding)
            + separator
            + middle_line
            + (" " * middle_padding)
            + separator
            + right_line
        )


def display_dashboard():
    """Display the full terminal dashboard"""
    clear_screen()

    # Get terminal dimensions
    width, height = get_terminal_size()

    # Create dashboard instance
    dashboard = SystemDashboard()

    # Get data
    health = dashboard.get_system_health()
    top_agents = dashboard.get_top_agents()
    recent_routing = dashboard.get_recent_routing_decisions(limit=15)
    recent_events = dashboard.get_recent_hook_events(limit=15)
    agent_stats = dashboard.get_agent_statistics()
    issues = dashboard.get_system_issues()

    # Determine layout based on width
    if width >= 180:
        # Wide monitor: 3-column layout
        display_three_column_layout(
            width,
            height,
            health,
            top_agents,
            recent_routing,
            recent_events,
            agent_stats,
            issues,
        )
    elif width >= 120:
        # Medium-wide: 2-column layout
        display_two_column_layout(
            width,
            height,
            health,
            top_agents,
            recent_routing,
            recent_events,
            agent_stats,
            issues,
        )
    else:
        # Narrow: single column (original layout)
        display_single_column_layout(
            width,
            height,
            health,
            top_agents,
            recent_routing,
            recent_events,
            agent_stats,
            issues,
        )


def display_single_column_layout(
    width,
    height,
    health,
    top_agents,
    recent_routing,
    recent_events,
    agent_stats,
    issues,
):
    """Original single-column layout for narrow terminals"""
    # Calculate how many lines we need (estimate)
    base_lines = 5  # Header
    base_lines += 5  # System health
    base_lines += 8  # Metrics
    base_lines += 3  # Footer

    # Calculate lines for issues
    if issues:
        issue_lines = 4 + len(issues) * 3
    else:
        issue_lines = 5

    base_lines += issue_lines

    # Remaining lines for dynamic content
    available_lines = max(0, height - base_lines)

    # Distribute remaining lines across sections
    if available_lines < 20:
        activity_lines = min(3, available_lines // 4)
        agent_detail_lines = 0
        top_agent_lines = 0
        show_system_info = False
        show_alerts = False
    elif available_lines < 35:
        activity_lines = min(5, available_lines // 3)
        agent_detail_lines = min(3, available_lines // 4)
        top_agent_lines = 0
        show_system_info = False
        show_alerts = True
    else:
        activity_lines = min(10, available_lines // 3)
        agent_detail_lines = min(5, (available_lines - activity_lines) // 2)
        top_agent_lines = 3
        show_system_info = True
        show_alerts = True

    # Print sections
    print_header(width, height, "single-column")
    print_system_health(health, width)
    print_metrics(health, width)
    print_issues(issues, width)

    if activity_lines > 0:
        print_recent_activity(
            recent_routing, recent_events, width, max_items=activity_lines
        )

    if agent_detail_lines > 0:
        print_agent_details(agent_stats, width, max_items=agent_detail_lines)

    if top_agent_lines > 0:
        print_top_agents(top_agents, width, max_items=top_agent_lines)

    if show_system_info:
        print_system_info(health, width)

    if show_alerts:
        print_alerts(health, width)

    print_footer(width)


def display_two_column_layout(
    width,
    height,
    health,
    top_agents,
    recent_routing,
    recent_events,
    agent_stats,
    issues,
):
    """Two-column layout for medium-wide terminals (120-179 columns)"""
    # Header spans full width
    print_header(width, height, "2-column")

    # Calculate column widths
    separator = "  "
    left_width = (width - len(separator)) // 2
    right_width = width - left_width - len(separator)

    # Left column: Health, Metrics, Issues
    left_lines = []
    left_lines.extend(capture_section_output(print_system_health, health, left_width))
    left_lines.extend(capture_section_output(print_metrics, health, left_width))
    left_lines.extend(capture_section_output(print_issues, issues, left_width))

    # Right column: Activity, Agent Details, Top Agents
    right_lines = []
    right_lines.extend(
        capture_section_output(
            print_recent_activity,
            recent_routing,
            recent_events,
            right_width,
            max_items=12,
        )
    )
    right_lines.extend(
        capture_section_output(
            print_agent_details, agent_stats, right_width, max_items=8
        )
    )
    right_lines.extend(
        capture_section_output(print_top_agents, top_agents, right_width, max_items=5)
    )

    # Print columns side by side
    print_columns(left_lines, right_lines, left_width, right_width, separator)

    print()

    # Footer spans full width
    print_footer(width)


def display_three_column_layout(
    width,
    height,
    health,
    top_agents,
    recent_routing,
    recent_events,
    agent_stats,
    issues,
):
    """Three-column layout for very wide terminals (180+ columns)"""
    # Header spans full width
    print_header(width, height, "3-column")

    # Calculate column widths
    separator = "  "
    col_width = (width - 2 * len(separator)) // 3
    left_width = col_width
    middle_width = col_width
    right_width = width - left_width - middle_width - 2 * len(separator)

    # Left column: Health, Metrics
    left_lines = []
    left_lines.extend(capture_section_output(print_system_health, health, left_width))
    left_lines.extend(capture_section_output(print_metrics, health, left_width))
    left_lines.extend(capture_section_output(print_alerts, health, left_width))

    # Middle column: Issues, Top Agents
    middle_lines = []
    middle_lines.extend(capture_section_output(print_issues, issues, middle_width))
    middle_lines.extend(
        capture_section_output(print_top_agents, top_agents, middle_width, max_items=8)
    )
    middle_lines.extend(capture_section_output(print_system_info, health, middle_width))

    # Right column: Activity, Agent Details
    right_lines = []
    right_lines.extend(
        capture_section_output(
            print_recent_activity,
            recent_routing,
            recent_events,
            right_width,
            max_items=15,
        )
    )
    right_lines.extend(
        capture_section_output(
            print_agent_details, agent_stats, right_width, max_items=10
        )
    )

    # Print three columns side by side
    print_three_columns(
        left_lines,
        middle_lines,
        right_lines,
        left_width,
        middle_width,
        right_width,
        separator,
    )

    print()

    # Footer spans full width
    print_footer(width)


if __name__ == "__main__":
    try:
        display_dashboard()
    except KeyboardInterrupt:
        print("\n\n" + colorize("Dashboard closed.", Colors.BRIGHT_BLACK))
        sys.exit(0)
    except Exception as e:
        print(colorize(f"\n❌ Error: {e}", Colors.RED, bold=True))
        sys.exit(1)
