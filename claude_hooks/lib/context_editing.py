"""
Context Editing Integration for Anthropic's Context Management API Beta

This module provides utilities for integrating Anthropic's context editing
feature, which automatically removes stale tool calls and results from the
context window when approaching token limits.

Features:
- Context editing configuration
- Monitoring and logging of context cleanup
- Token savings tracking
- Integration helpers for API calls

Note: Context editing is an API-level feature. For Claude Code CLI usage,
this module provides monitoring and configuration utilities.

Beta Header: anthropic-beta: context-management-2025-06-27
API Parameter: context_management.edit_types = ["clear_tool_uses_20250919"]

Usage:
    from claude_hooks.lib.context_editing import ContextEditingMonitor

    monitor = ContextEditingMonitor()
    monitor.log_context_state(tokens_used=180000, tokens_total=200000)
    monitor.track_cleanup(tools_removed=5, tokens_saved=3000)
"""

import json
import logging
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ContextState:
    """Represents the state of the context window"""
    timestamp: str
    tokens_used: int
    tokens_total: int
    tokens_remaining: int
    utilization_percent: float
    tools_in_context: int = 0
    needs_cleanup: bool = False


@dataclass
class CleanupEvent:
    """Represents a context cleanup event"""
    timestamp: str
    tools_removed: int
    tokens_saved: int
    tokens_before: int
    tokens_after: int
    cleanup_reason: str = "approaching_limit"


class ContextEditingMonitor:
    """
    Monitor and track context editing behavior

    Tracks:
    - Context window utilization
    - Cleanup events
    - Token savings
    - Performance impact
    """

    def __init__(self, log_dir: Optional[str] = None):
        """
        Initialize monitor

        Args:
            log_dir: Directory for context editing logs
                     Defaults to ~/.claude/context_editing_logs/
        """
        if log_dir is None:
            log_dir = str(Path.home() / ".claude" / "context_editing_logs")

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.cleanup_events: List[CleanupEvent] = []
        self.context_states: List[ContextState] = []

    def log_context_state(
        self,
        tokens_used: int,
        tokens_total: int = 200000,
        tools_in_context: int = 0
    ) -> ContextState:
        """
        Log current context window state

        Args:
            tokens_used: Current tokens in context
            tokens_total: Total context window size
            tools_in_context: Number of tool calls in context

        Returns:
            ContextState object
        """
        tokens_remaining = tokens_total - tokens_used
        utilization = (tokens_used / tokens_total) * 100

        # Determine if cleanup is needed (>90% utilization)
        needs_cleanup = utilization > 90

        state = ContextState(
            timestamp=datetime.utcnow().isoformat(),
            tokens_used=tokens_used,
            tokens_total=tokens_total,
            tokens_remaining=tokens_remaining,
            utilization_percent=utilization,
            tools_in_context=tools_in_context,
            needs_cleanup=needs_cleanup
        )

        self.context_states.append(state)

        # Log to file
        self._write_state_log(state)

        if needs_cleanup:
            logger.warning(f"Context at {utilization:.1f}% utilization - cleanup recommended")
        else:
            logger.info(f"Context utilization: {utilization:.1f}% ({tokens_used}/{tokens_total})")

        return state

    def track_cleanup(
        self,
        tools_removed: int,
        tokens_saved: int,
        tokens_before: int,
        tokens_after: int,
        reason: str = "approaching_limit"
    ) -> CleanupEvent:
        """
        Track a context cleanup event

        Args:
            tools_removed: Number of tool calls removed
            tokens_saved: Tokens freed by cleanup
            tokens_before: Tokens before cleanup
            tokens_after: Tokens after cleanup
            reason: Reason for cleanup

        Returns:
            CleanupEvent object
        """
        event = CleanupEvent(
            timestamp=datetime.utcnow().isoformat(),
            tools_removed=tools_removed,
            tokens_saved=tokens_saved,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            cleanup_reason=reason
        )

        self.cleanup_events.append(event)

        # Log to file
        self._write_cleanup_log(event)

        logger.info(
            f"Context cleanup: removed {tools_removed} tools, "
            f"saved {tokens_saved} tokens ({tokens_before} → {tokens_after})"
        )

        return event

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get aggregated statistics

        Returns:
            Dictionary with cleanup statistics
        """
        if not self.cleanup_events:
            return {
                "total_cleanups": 0,
                "total_tools_removed": 0,
                "total_tokens_saved": 0,
                "avg_tokens_saved_per_cleanup": 0,
                "avg_utilization": 0
            }

        total_cleanups = len(self.cleanup_events)
        total_tools_removed = sum(e.tools_removed for e in self.cleanup_events)
        total_tokens_saved = sum(e.tokens_saved for e in self.cleanup_events)
        avg_tokens_saved = total_tokens_saved / total_cleanups if total_cleanups > 0 else 0

        avg_utilization = 0
        if self.context_states:
            avg_utilization = sum(s.utilization_percent for s in self.context_states) / len(self.context_states)

        return {
            "total_cleanups": total_cleanups,
            "total_tools_removed": total_tools_removed,
            "total_tokens_saved": total_tokens_saved,
            "avg_tokens_saved_per_cleanup": avg_tokens_saved,
            "avg_utilization": avg_utilization,
            "context_states_tracked": len(self.context_states)
        }

    def _write_state_log(self, state: ContextState) -> None:
        """Write context state to log file"""
        try:
            log_file = self.log_dir / f"context_states_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"

            with open(log_file, 'a') as f:
                f.write(json.dumps({
                    "timestamp": state.timestamp,
                    "tokens_used": state.tokens_used,
                    "tokens_total": state.tokens_total,
                    "tokens_remaining": state.tokens_remaining,
                    "utilization_percent": state.utilization_percent,
                    "tools_in_context": state.tools_in_context,
                    "needs_cleanup": state.needs_cleanup
                }) + '\n')

        except Exception as e:
            logger.error(f"Failed to write state log: {e}")

    def _write_cleanup_log(self, event: CleanupEvent) -> None:
        """Write cleanup event to log file"""
        try:
            log_file = self.log_dir / f"cleanup_events_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"

            with open(log_file, 'a') as f:
                f.write(json.dumps({
                    "timestamp": event.timestamp,
                    "tools_removed": event.tools_removed,
                    "tokens_saved": event.tokens_saved,
                    "tokens_before": event.tokens_before,
                    "tokens_after": event.tokens_after,
                    "cleanup_reason": event.cleanup_reason
                }) + '\n')

        except Exception as e:
            logger.error(f"Failed to write cleanup log: {e}")


# Global monitor instance
_monitor: Optional[ContextEditingMonitor] = None


def get_context_monitor() -> ContextEditingMonitor:
    """Get global context editing monitor"""
    global _monitor
    if _monitor is None:
        _monitor = ContextEditingMonitor()
    return _monitor


# Example integration functions for API usage

def create_context_management_config(enable_editing: bool = True) -> Dict[str, Any]:
    """
    Create context management configuration for API calls

    Args:
        enable_editing: Enable automatic context editing

    Returns:
        Configuration dict for API request

    Example:
        config = create_context_management_config(enable_editing=True)
        # Use in API request:
        # response = anthropic.messages.create(
        #     ...,
        #     context_management=config,
        #     headers={"anthropic-beta": "context-management-2025-06-27"}
        # )
    """
    if not enable_editing:
        return {}

    return {
        "edit_types": ["clear_tool_uses_20250919"]
    }


def create_full_context_config(
    enable_editing: bool = True,
    enable_memory: bool = True
) -> Dict[str, Any]:
    """
    Create full context management configuration

    Includes both context editing and memory tool

    Args:
        enable_editing: Enable automatic context editing
        enable_memory: Enable memory tool

    Returns:
        Configuration dict for API request
    """
    edit_types = []

    if enable_editing:
        edit_types.append("clear_tool_uses_20250919")

    if enable_memory:
        edit_types.append("memory_20250818")

    return {
        "edit_types": edit_types
    }


# Example usage documentation
EXAMPLE_API_USAGE = """
Example API Usage with Context Editing:

```python
import anthropic

client = anthropic.Anthropic(api_key="your-api-key")

# Enable context editing
response = client.messages.create(
    model="claude-sonnet-4.5",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}],
    context_management={
        "edit_types": ["clear_tool_uses_20250919"]
    },
    headers={
        "anthropic-beta": "context-management-2025-06-27"
    }
)

# Monitor context
from claude_hooks.lib.context_editing import get_context_monitor

monitor = get_context_monitor()
monitor.log_context_state(
    tokens_used=response.usage.input_tokens,
    tokens_total=200000
)
```

Expected Behavior:
- When context approaches ~180K tokens (90% utilization)
- Anthropic automatically removes stale tool calls
- Preserves conversation flow
- 29% performance improvement on average

Benefits:
- Longer agent runtime without manual intervention
- Automatic cleanup of stale data
- Reduced token waste
- Better context hygiene
"""
