#!/usr/bin/env python3
"""
Agent Announcement Module
Provides colored, emoji-enhanced announcements when agents are activated.
"""

import sys
from typing import Dict, Optional


# Agent emoji mappings
AGENT_EMOJIS = {
    "agent-testing": "🧪",
    "agent-debug": "🐛",
    "agent-debug-intelligence": "🔍",
    "agent-code-generator": "⚡",
    "agent-workflow-coordinator": "🎯",
    "agent-parallel-dispatcher": "⚙️",
    "agent-repository-crawler-claude-code": "📚",
}

# ANSI color codes for different agents
AGENT_COLORS = {
    "agent-testing": "\033[96m",                    # Cyan
    "agent-debug": "\033[91m",                       # Light red
    "agent-debug-intelligence": "\033[94m",          # Light blue
    "agent-code-generator": "\033[93m",              # Yellow
    "agent-workflow-coordinator": "\033[95m",        # Magenta
    "agent-parallel-dispatcher": "\033[92m",         # Light green
    "agent-repository-crawler-claude-code": "\033[97m", # White
}

# ANSI formatting codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def get_emoji(agent_name: str) -> str:
    """Get emoji for agent, default to robot if not found."""
    return AGENT_EMOJIS.get(agent_name, "🤖")


def get_color(agent_name: str) -> str:
    """Get color for agent, default to white if not found."""
    return AGENT_COLORS.get(agent_name, "\033[97m")


def announce_agent(
    agent_name: str,
    confidence: float,
    method: str,
    agent_domain: Optional[str] = None,
    agent_purpose: Optional[str] = None,
    file=sys.stderr
) -> None:
    """
    Print colored agent announcement with emoji.

    Args:
        agent_name: Name of the activated agent
        confidence: Confidence score (0.0-1.0)
        method: Detection method (pattern_match, trigger_match, meta_trigger, etc.)
        agent_domain: Optional agent domain for additional context
        agent_purpose: Optional agent purpose description
        file: Output file (default: stderr)
    """
    emoji = get_emoji(agent_name)
    color = get_color(agent_name)

    # Format confidence as percentage
    confidence_pct = f"{confidence * 100:.0f}%"

    # Build announcement
    lines = [
        f"{color}{BOLD}{emoji} Agent Activated: {agent_name}{RESET}",
        f"{color}├─ Confidence: {confidence_pct}{RESET}",
        f"{color}├─ Method: {method}{RESET}",
    ]

    # Add optional context
    if agent_domain:
        lines.append(f"{color}├─ Domain: {agent_domain}{RESET}")

    if agent_purpose:
        # Truncate long purpose descriptions
        purpose_short = agent_purpose[:60] + "..." if len(agent_purpose) > 60 else agent_purpose
        lines.append(f"{color}├─ Purpose: {purpose_short}{RESET}")

    # Closing line
    lines.append(f"{color}└─ {DIM}Ready to assist!{RESET}")

    # Print announcement
    announcement = "\n".join(lines)
    print(announcement, file=file, flush=True)


def announce_meta_trigger(
    original_prompt: str,
    file=sys.stderr
) -> None:
    """
    Announce that a meta-trigger was detected and coordinator is being invoked.

    Args:
        original_prompt: The user's original prompt
        file: Output file (default: stderr)
    """
    color = get_color("agent-workflow-coordinator")
    emoji = get_emoji("agent-workflow-coordinator")

    # Truncate prompt if too long
    prompt_short = original_prompt[:50] + "..." if len(original_prompt) > 50 else original_prompt

    announcement = f"""
{color}{BOLD}{emoji} Meta-Trigger Detected!{RESET}
{color}├─ Task: {prompt_short}{RESET}
{color}├─ Routing to: agent-workflow-coordinator{RESET}
{color}└─ {DIM}Coordinator will select specialized agent and gather intelligence...{RESET}
"""

    print(announcement, file=file, flush=True)


def announce_intelligence_gathering(
    agent_name: str,
    status: str = "starting",
    execution_time_ms: Optional[float] = None,
    sources_count: Optional[int] = None,
    file=sys.stderr
) -> None:
    """
    Announce intelligence gathering progress.

    Args:
        agent_name: Name of the agent gathering intelligence
        status: Status (starting, in_progress, complete, timeout, error)
        execution_time_ms: Optional execution time in milliseconds
        sources_count: Optional count of intelligence sources consulted
        file: Output file (default: stderr)
    """
    color = get_color(agent_name)

    if status == "starting":
        msg = f"{color}🔍 Gathering intelligence...{RESET}"
    elif status == "in_progress":
        msg = f"{color}  ├─ Searching knowledge base...{RESET}"
    elif status == "complete" and execution_time_ms and sources_count:
        msg = f"{color}  └─ ✅ Intelligence ready ({execution_time_ms:.0f}ms, {sources_count} sources){RESET}"
    elif status == "timeout":
        msg = f"{color}  └─ ⚠️  Intelligence gathering timed out (continuing without){RESET}"
    elif status == "error":
        msg = f"{color}  └─ ⚠️  Intelligence gathering failed (continuing without){RESET}"
    else:
        msg = f"{color}  └─ {status}{RESET}"

    print(msg, file=file, flush=True)


# CLI interface for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test agent announcements")
    parser.add_argument("agent", help="Agent name")
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--method", default="pattern_match")
    parser.add_argument("--domain", default=None)
    parser.add_argument("--purpose", default=None)

    args = parser.parse_args()

    # Test announcement
    announce_agent(
        agent_name=args.agent,
        confidence=args.confidence,
        method=args.method,
        agent_domain=args.domain,
        agent_purpose=args.purpose
    )

    # Test meta-trigger
    if args.method == "meta_trigger":
        announce_meta_trigger("use an agent to write tests")

    # Test intelligence gathering
    announce_intelligence_gathering(args.agent, "starting")
    announce_intelligence_gathering(args.agent, "in_progress")
    announce_intelligence_gathering(args.agent, "complete", 1234.5, 8)
