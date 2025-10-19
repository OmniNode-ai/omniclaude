#!/usr/bin/env python3
"""
Response Intelligence Module - Captures response completion intelligence

Tracks response completion, multi-tool coordination, and links to UserPromptSubmit events.
Performance target: <30ms execution time.
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add lib directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from correlation_manager import get_correlation_context
from hook_event_logger import get_logger


class ResponseIntelligence:
    """Capture response completion intelligence and multi-tool coordination."""

    def __init__(self):
        """Initialize response intelligence tracker."""
        self.logger = get_logger()

    def log_response_completion(
        self,
        session_id: str,
        tools_executed: Optional[List[str]] = None,
        completion_status: str = "complete",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Log response completion event to database.

        Args:
            session_id: Claude Code session identifier
            tools_executed: List of tools executed in this response
            completion_status: Completion status (complete, interrupted, error)
            metadata: Additional metadata

        Returns:
            Event ID if successful, None if failed
        """
        start_time = time.time()

        try:
            # Get correlation context (links to UserPromptSubmit)
            corr_context = get_correlation_context()

            if not corr_context:
                # No correlation context - standalone response
                correlation_id = None
                response_time_ms = None
                agent_name = None
                agent_domain = None
            else:
                correlation_id = corr_context.get("correlation_id")
                agent_name = corr_context.get("agent_name")
                agent_domain = corr_context.get("agent_domain")

                # Calculate response time (from UserPromptSubmit to now)
                created_at_str = corr_context.get("created_at")
                if created_at_str:
                    try:
                        created_at = datetime.fromisoformat(
                            created_at_str.replace("Z", "+00:00")
                        )
                        now = datetime.now(timezone.utc)
                        response_time_ms = (now - created_at).total_seconds() * 1000
                    except Exception:
                        response_time_ms = None
                else:
                    response_time_ms = None

            # Process tools executed
            if tools_executed is None:
                tools_executed = []

            total_tools = len(tools_executed)
            multi_tool_count = total_tools if total_tools > 1 else 0

            # Detect interruption
            interrupted = completion_status == "interrupted"

            # Build payload
            payload = {
                "tools_executed": tools_executed,
                "total_tools": total_tools,
                "multi_tool_count": multi_tool_count,
                "response_time_ms": response_time_ms,
                "completion_status": completion_status,
                "interrupted": interrupted,
            }

            # Build metadata
            event_metadata = metadata or {}
            event_metadata.update(
                {
                    "session_id": session_id,
                    "correlation_id": correlation_id,
                    "agent_name": agent_name,
                    "agent_domain": agent_domain,
                    "hook_type": "Stop",
                    "interruption_point": (
                        event_metadata.get("interruption_point")
                        if interrupted
                        else None
                    ),
                }
            )

            # Log event
            event_id = self.logger.log_event(
                source="Stop",
                action="response_completed",
                resource="response",
                resource_id=correlation_id or session_id,
                payload=payload,
                metadata=event_metadata,
            )

            # Performance tracking
            execution_time_ms = (time.time() - start_time) * 1000

            # Warn if exceeding performance target
            if execution_time_ms > 30:
                print(
                    f"⚠️  [ResponseIntelligence] Performance warning: {execution_time_ms:.2f}ms (target: <30ms)",
                    file=sys.stderr,
                )

            return event_id

        except Exception as e:
            print(
                f"⚠️  [ResponseIntelligence] Failed to log response completion: {e}",
                file=sys.stderr,
            )
            return None

    def detect_multi_tool_workflow(self, tools_executed: List[str]) -> Dict[str, Any]:
        """Analyze multi-tool workflow patterns.

        Args:
            tools_executed: List of tools executed in order

        Returns:
            Dict with workflow analysis
        """
        if not tools_executed:
            return {"is_multi_tool": False, "tool_count": 0, "workflow_pattern": None}

        tool_count = len(tools_executed)
        is_multi_tool = tool_count > 1

        # Detect common workflow patterns
        workflow_pattern = None
        if is_multi_tool:
            " -> ".join(tools_executed)

            # Common patterns
            if "Read" in tools_executed and "Edit" in tools_executed:
                workflow_pattern = "read_modify_write"
            elif "Read" in tools_executed and "Write" in tools_executed:
                workflow_pattern = "read_create"
            elif "Edit" in tools_executed and "Bash" in tools_executed:
                workflow_pattern = "modify_verify"
            elif "Write" in tools_executed and "Bash" in tools_executed:
                workflow_pattern = "create_verify"
            elif tools_executed.count("Edit") > 1:
                workflow_pattern = "multi_file_edit"
            elif tools_executed.count("Read") > 1:
                workflow_pattern = "multi_file_read"
            else:
                workflow_pattern = "custom_workflow"

        return {
            "is_multi_tool": is_multi_tool,
            "tool_count": tool_count,
            "workflow_pattern": workflow_pattern,
            "tools_sequence": tools_executed,
        }


def log_response_completion(
    session_id: str,
    tools_executed: Optional[List[str]] = None,
    completion_status: str = "complete",
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Convenience function to log response completion.

    Args:
        session_id: Claude Code session identifier
        tools_executed: List of tools executed in this response
        completion_status: Completion status (complete, interrupted, error)
        metadata: Additional metadata

    Returns:
        Event ID if successful, None if failed
    """
    intelligence = ResponseIntelligence()
    return intelligence.log_response_completion(
        session_id=session_id,
        tools_executed=tools_executed,
        completion_status=completion_status,
        metadata=metadata,
    )


if __name__ == "__main__":
    # Test response intelligence module
    print("Testing response intelligence module...")

    # Test 1: Simple response completion
    print("\n1. Testing simple response completion...")
    event_id = log_response_completion(
        session_id="test-session-123",
        tools_executed=["Write"],
        completion_status="complete",
    )
    print(f"✓ Event logged: {event_id}")

    # Test 2: Multi-tool workflow
    print("\n2. Testing multi-tool workflow...")
    event_id = log_response_completion(
        session_id="test-session-456",
        tools_executed=["Read", "Edit", "Bash"],
        completion_status="complete",
    )
    print(f"✓ Event logged: {event_id}")

    # Test 3: Interrupted response
    print("\n3. Testing interrupted response...")
    event_id = log_response_completion(
        session_id="test-session-789",
        tools_executed=["Write", "Edit"],
        completion_status="interrupted",
        metadata={"interruption_point": "mid_execution"},
    )
    print(f"✓ Event logged: {event_id}")

    # Test 4: Workflow pattern detection
    print("\n4. Testing workflow pattern detection...")
    intelligence = ResponseIntelligence()
    workflow = intelligence.detect_multi_tool_workflow(["Read", "Edit", "Bash"])
    print(f"✓ Workflow pattern: {workflow['workflow_pattern']}")
    print(f"  Multi-tool: {workflow['is_multi_tool']}")
    print(f"  Tool count: {workflow['tool_count']}")

    print("\n✅ All tests passed!")
