#!/usr/bin/env python3
"""
Agent Execution Summary Banner

Displays a comprehensive summary banner at the end of agent execution showing:
- Which agent handled the request
- Routing confidence and strategy
- Tools used
- Success/failure status
- Debug traces (if DEBUG mode)
- Key learnings
"""

import os
import sys
from typing import Dict, List, Optional


# Import hook infrastructure
try:
    from .correlation_manager import get_correlation_context
    from .hook_event_logger import get_logger
except ImportError:
    print("Error: Unable to import hook infrastructure", file=sys.stderr)
    sys.exit(1)


def get_routing_decision(correlation_id: str) -> Optional[Dict]:
    """Get agent routing decision for this correlation ID."""
    logger = get_logger()
    try:
        conn = logger._get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    selected_agent,
                    confidence_score,
                    routing_strategy,
                    reasoning,
                    created_at
                FROM agent_routing_decisions
                WHERE context->>'correlation_id' = %s
                ORDER BY created_at DESC
                LIMIT 1
            """,
                (correlation_id,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "agent": row[0],
                    "confidence": float(row[1]),
                    "strategy": row[2],
                    "reasoning": row[3],
                    "timestamp": row[4].isoformat(),
                }
    except Exception as e:
        print(f"Warning: Could not query routing decision: {e}", file=sys.stderr)
    return None


def get_agent_actions(correlation_id: str) -> List[Dict]:
    """Get all agent actions for this correlation ID (debug mode only)."""
    if os.environ.get("DEBUG", "").lower() not in ("true", "1", "yes", "on"):
        return []

    logger = get_logger()
    try:
        conn = logger._get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    action_type,
                    action_name,
                    action_details,
                    duration_ms,
                    created_at
                FROM agent_actions
                WHERE correlation_id::text = %s
                ORDER BY created_at
            """,
                (correlation_id,),
            )
            rows = cur.fetchall()
            return [
                {
                    "type": row[0],
                    "name": row[1],
                    "details": row[2],
                    "duration_ms": row[3],
                    "timestamp": row[4].isoformat(),
                }
                for row in rows
            ]
    except Exception as e:
        print(f"Warning: Could not query agent actions: {e}", file=sys.stderr)
    return []


def format_banner(
    routing: Optional[Dict],
    actions: List[Dict],
    tools_executed: List[str],
    completion_status: str,
) -> str:
    """Format the agent execution summary banner."""
    lines = []

    # Top border
    lines.append("╔" + "═" * 78 + "╗")
    lines.append("║" + " " * 78 + "║")
    lines.append("║" + "  🟣 AGENT EXECUTION SUMMARY".ljust(78) + "║")
    lines.append("║" + " " * 78 + "║")

    if routing:
        # Agent info section
        lines.append("╟" + "─" * 78 + "╢")
        lines.append("║  Agent: " + routing["agent"].ljust(68) + "║")
        lines.append(
            "║  Confidence: " + f"{routing['confidence']:.0%} match".ljust(64) + "║"
        )
        lines.append("║  Strategy: " + routing["strategy"].ljust(66) + "║")
        if routing["reasoning"]:
            # Word wrap reasoning
            reasoning = routing["reasoning"]
            max_len = 72
            while reasoning:
                chunk = reasoning[:max_len]
                reasoning = reasoning[max_len:]
                lines.append("║  " + chunk.ljust(76) + "║")

    # Tools section
    if tools_executed:
        lines.append("╟" + "─" * 78 + "╢")
        lines.append("║  Tools Used:".ljust(78) + "║")
        for tool in tools_executed[:10]:  # Limit to 10 tools
            lines.append("║    • " + tool.ljust(72) + "║")
        if len(tools_executed) > 10:
            lines.append(
                f"║    ... and {len(tools_executed) - 10} more".ljust(78) + "║"
            )

    # Debug traces section (if DEBUG mode and actions available)
    if actions:
        lines.append("╟" + "─" * 78 + "╢")
        lines.append("║  Debug Trace:".ljust(78) + "║")
        for action in actions[:5]:  # Limit to 5 actions
            action_str = f"    [{action['type']}] {action['name']}"
            if action["duration_ms"]:
                action_str += f" ({action['duration_ms']}ms)"
            lines.append("║  " + action_str.ljust(76) + "║")
        if len(actions) > 5:
            lines.append(
                f"║    ... and {len(actions) - 5} more actions".ljust(78) + "║"
            )

    # Status section
    lines.append("╟" + "─" * 78 + "╢")
    status_symbol = "✅" if completion_status == "complete" else "⚠️"
    status_text = (
        "COMPLETED SUCCESSFULLY" if completion_status == "complete" else "INTERRUPTED"
    )
    lines.append(f"║  Status: {status_symbol} {status_text}".ljust(78) + "║")

    # Bottom border
    lines.append("║" + " " * 78 + "║")
    lines.append("╚" + "═" * 78 + "╝")

    return "\n".join(lines)


def display_summary_banner(
    tools_executed: List[str], completion_status: str = "complete"
):
    """
    Display agent execution summary banner.

    Args:
        tools_executed: List of tools that were executed
        completion_status: 'complete', 'interrupted', etc.
    """
    # Get correlation context
    corr_context = get_correlation_context()
    if not corr_context:
        return  # No correlation ID, skip banner

    correlation_id = corr_context.get("correlation_id")
    if not correlation_id:
        return

    # Get routing decision
    routing = get_routing_decision(correlation_id)

    # Get agent actions (debug mode only)
    actions = get_agent_actions(correlation_id)

    # Only display banner if we have routing info
    if not routing and not actions:
        return

    # Format and display banner
    banner = format_banner(routing, actions, tools_executed, completion_status)
    print("\n" + banner + "\n", file=sys.stderr)


if __name__ == "__main__":
    # Test mode - display sample banner
    sample_tools = ["Read", "Write", "Bash", "Edit"]
    sample_routing = {
        "agent": "agent-performance",
        "confidence": 0.92,
        "strategy": "enhanced_fuzzy_matching",
        "reasoning": "High confidence match on 'optimize' and 'performance' triggers",
        "timestamp": "2025-10-21T06:00:00Z",
    }

    banner = format_banner(sample_routing, [], sample_tools, "complete")
    print(banner)
