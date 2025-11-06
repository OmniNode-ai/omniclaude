#!/usr/bin/env python3
"""
Post-Tool-Use Hook with Pattern Learning

This hook runs after every tool execution in Claude Code.
It captures execution results and updates memory with:
- Tool execution success/failure patterns
- Error patterns for debugging
- Performance metrics
- Success rate tracking per tool

Flow:
1. Parse tool execution result
2. Extract success/failure/error information
3. Update execution history in memory
4. Update success/failure patterns
5. Store performance metrics

Performance Target: <50ms overhead
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from claude_hooks.lib.memory_client import get_memory_client
from config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_tool_result(tool_name: str, result: str) -> Dict[str, Any]:
    """Parse tool execution result"""

    # Determine success/failure
    success = True
    error = None

    # Common error indicators
    error_indicators = [
        'error', 'failed', 'exception', 'traceback',
        'not found', 'permission denied', 'cannot',
        'invalid', 'unable to'
    ]

    result_lower = result.lower()
    for indicator in error_indicators:
        if indicator in result_lower:
            success = False
            error = result[:500]  # Capture first 500 chars of error
            break

    # Extract additional metadata
    metadata = {
        "result_length": len(result),
        "has_output": len(result) > 0
    }

    return {
        "tool": tool_name,
        "success": success,
        "error": error,
        "metadata": metadata,
        "timestamp": datetime.utcnow().isoformat()
    }


async def store_execution_result(
    tool_name: str,
    success: bool,
    duration_ms: float,
    error: Optional[str] = None,
    context: Optional[Dict] = None
) -> None:
    """Store tool execution result in memory"""

    memory = get_memory_client()

    try:
        # Create execution record
        execution_id = f"tool_execution_{tool_name}_{int(datetime.utcnow().timestamp())}"
        execution_record = {
            "tool": tool_name,
            "success": success,
            "duration_ms": duration_ms,
            "error": error,
            "context": context or {},
            "timestamp": datetime.utcnow().isoformat()
        }

        # Store in execution history
        await memory.store_memory(
            key=execution_id,
            value=execution_record,
            category="execution_history",
            metadata={"tool": tool_name, "success": success}
        )

        logger.info(f"Stored execution result: {tool_name} ({'success' if success else 'failure'})")

    except Exception as e:
        logger.error(f"Failed to store execution result: {e}")


async def update_success_patterns(
    tool_name: str,
    success: bool,
    duration_ms: float,
    context: Optional[Dict] = None
) -> None:
    """Update success/failure patterns in memory"""

    memory = get_memory_client()

    try:
        if success:
            # Update success patterns
            pattern_key = "success_patterns"
            category = "patterns"

            # Get current patterns
            patterns = await memory.get_memory(pattern_key, category) or {}

            # Update tool-specific pattern
            tool_pattern = patterns.get(tool_name, {
                "count": 0,
                "total_duration_ms": 0,
                "avg_duration_ms": 0
            })

            tool_pattern["count"] += 1
            tool_pattern["total_duration_ms"] += duration_ms
            tool_pattern["avg_duration_ms"] = (
                tool_pattern["total_duration_ms"] / tool_pattern["count"]
            )

            # Add context if provided
            if context:
                tool_pattern["last_context"] = context
                tool_pattern["last_success"] = datetime.utcnow().isoformat()

            patterns[tool_name] = tool_pattern

            # Store updated patterns
            await memory.store_memory(
                key=pattern_key,
                value=patterns,
                category=category
            )

            logger.info(f"Updated success pattern for {tool_name}: "
                       f"{tool_pattern['count']} successes, "
                       f"avg {tool_pattern['avg_duration_ms']:.0f}ms")

        else:
            # Update failure patterns
            pattern_key = "failure_patterns"
            category = "patterns"

            # Get current patterns
            patterns = await memory.get_memory(pattern_key, category) or {}

            # Update tool-specific pattern
            tool_pattern = patterns.get(tool_name, {
                "count": 0,
                "recent_errors": []
            })

            tool_pattern["count"] += 1

            # Add to recent errors (keep last 5)
            error_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "context": context or {}
            }
            tool_pattern["recent_errors"].append(error_entry)
            tool_pattern["recent_errors"] = tool_pattern["recent_errors"][-5:]

            patterns[tool_name] = tool_pattern

            # Store updated patterns
            await memory.store_memory(
                key=pattern_key,
                value=patterns,
                category=category
            )

            logger.info(f"Updated failure pattern for {tool_name}: "
                       f"{tool_pattern['count']} failures")

    except Exception as e:
        logger.error(f"Failed to update patterns: {e}")


async def update_tool_sequences(
    tool_name: str,
    success: bool
) -> None:
    """Track tool usage sequences for pattern detection"""

    memory = get_memory_client()

    try:
        # Get recent tool sequence
        sequence_key = "tool_sequence"
        sequence = await memory.get_memory(sequence_key, "patterns") or []

        # Add current tool
        sequence.append({
            "tool": tool_name,
            "success": success,
            "timestamp": datetime.utcnow().isoformat()
        })

        # Keep last 10 tools
        sequence = sequence[-10:]

        # Store updated sequence
        await memory.store_memory(
            key=sequence_key,
            value=sequence,
            category="patterns"
        )

        # Detect common successful patterns
        if len(sequence) >= 3 and success:
            pattern = " → ".join([s["tool"] for s in sequence[-3:]])
            if all(s["success"] for s in sequence[-3:]):
                # This is a successful 3-tool pattern
                pattern_key = f"sequence_pattern_{pattern.replace(' → ', '_')}"
                pattern_count = await memory.get_memory(pattern_key, "patterns") or 0
                await memory.store_memory(
                    key=pattern_key,
                    value=pattern_count + 1,
                    category="patterns"
                )
                logger.info(f"Detected successful pattern: {pattern} ({pattern_count + 1} times)")

    except Exception as e:
        logger.error(f"Failed to update tool sequences: {e}")


async def main(tool_name: str, result: str, duration_ms: float = 0) -> None:
    """
    Main hook execution

    Args:
        tool_name: Name of the tool that was executed
        result: Tool execution result/output
        duration_ms: Execution duration in milliseconds
    """
    start_time = datetime.utcnow()

    try:
        # Check if memory client is enabled
        if not settings.enable_memory_client:
            logger.info("Memory client disabled, skipping pattern learning")
            return

        # Parse tool result
        parsed = parse_tool_result(tool_name, result)

        # Extract context (e.g., files mentioned in result)
        context = {
            "result_length": parsed["metadata"]["result_length"]
        }

        # Store execution result
        await store_execution_result(
            tool_name=tool_name,
            success=parsed["success"],
            duration_ms=duration_ms,
            error=parsed["error"],
            context=context
        )

        # Update success/failure patterns
        await update_success_patterns(
            tool_name=tool_name,
            success=parsed["success"],
            duration_ms=duration_ms,
            context=context
        )

        # Update tool sequences
        await update_tool_sequences(
            tool_name=tool_name,
            success=parsed["success"]
        )

        # Log performance
        hook_duration = (datetime.utcnow() - start_time).total_seconds() * 1000
        logger.info(f"Hook completed in {hook_duration:.0f}ms")

        if hook_duration > 50:
            logger.warning(f"Hook exceeded 50ms target: {hook_duration:.0f}ms")

    except Exception as e:
        logger.error(f"Hook failed: {e}", exc_info=True)


if __name__ == "__main__":
    # Parse arguments: tool_name result [duration_ms]
    if len(sys.argv) < 3:
        logger.error("Usage: post_tool_use.py <tool_name> <result> [duration_ms]")
        sys.exit(1)

    tool = sys.argv[1]
    result_text = sys.argv[2]
    duration = float(sys.argv[3]) if len(sys.argv) > 3 else 0

    # Run async main
    asyncio.run(main(tool, result_text, duration))

    logger.info(f"Pattern learning complete for {tool}")
