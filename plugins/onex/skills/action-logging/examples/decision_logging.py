#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Decision Logging Examples

Patterns for logging agent decisions with confidence scores.
"""

import asyncio
import sys
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "agents" / "lib"))

from action_logger import ActionLogger


async def decision_examples():
    """Demonstrate decision logging patterns."""

    logger = ActionLogger(
        agent_name="agent-decision-maker", correlation_id=str(uuid4())
    )

    # Example 1: Agent Routing Decision
    print("Example 1: Agent Routing Decision")
    start_time = time.time()

    # Simulate routing analysis
    user_request = "Design a REST API for user authentication"
    candidates = ["agent-api-architect", "agent-frontend-specialist", "agent-database"]

    # Perform routing (simulated)
    await asyncio.sleep(0.01)
    selected_agent = "agent-api-architect"
    confidence = 0.92

    duration_ms = int((time.time() - start_time) * 1000)

    await logger.log_decision(
        decision_name="route_to_specialized_agent",
        decision_context={
            "user_request": user_request,
            "candidates": candidates,
            "routing_strategy": "fuzzy_match",
            "keywords_detected": ["API", "REST", "authentication"],
        },
        decision_result={
            "selected_agent": selected_agent,
            "confidence": confidence,
            "reasoning": "API design keywords strongly indicate API architect specialization",
            "second_best": {"agent": "agent-database", "confidence": 0.68},
        },
        duration_ms=duration_ms,
    )
    print(f"✓ Routed to {selected_agent} (confidence: {confidence})\n")

    # Example 2: Strategy Selection
    print("Example 2: Strategy Selection Decision")
    await logger.log_decision(
        decision_name="select_execution_strategy",
        decision_context={
            "task_type": "parallel_file_processing",
            "file_count": 15,
            "strategies_available": ["sequential", "parallel", "batch"],
        },
        decision_result={
            "selected_strategy": "parallel",
            "confidence": 0.88,
            "reasoning": "15 files justify parallel processing overhead",
            "expected_speedup": "3x",
        },
        duration_ms=8,
    )
    print("✓ Selected parallel execution strategy\n")

    # Example 3: Tool Selection
    print("Example 3: Tool Selection Decision")
    await logger.log_decision(
        decision_name="select_search_tool",
        decision_context={
            "search_task": "Find all TODO comments",
            "available_tools": ["Grep", "Read+Parse", "WebSearch"],
            "file_count": 100,
        },
        decision_result={
            "selected_tool": "Grep",
            "confidence": 0.95,
            "reasoning": "Grep optimal for pattern matching across many files",
            "alternatives_rejected": [
                "Read+Parse (too slow)",
                "WebSearch (not applicable)",
            ],
        },
        duration_ms=5,
    )
    print("✓ Selected Grep tool\n")

    # Example 4: Quality Gate Decision
    print("Example 4: Quality Gate Decision")
    await logger.log_decision(
        decision_name="quality_gate_evaluation",
        decision_context={
            "quality_score": 0.87,
            "required_threshold": 0.85,
            "metrics": {
                "code_coverage": 0.92,
                "type_safety": 0.88,
                "onex_compliance": 0.81,
            },
        },
        decision_result={
            "passed": True,
            "confidence": 0.90,
            "reasoning": "Overall score 0.87 exceeds threshold 0.85",
            "warnings": ["ONEX compliance slightly low (0.81)"],
        },
        duration_ms=12,
    )
    print("✓ Quality gate evaluation logged\n")

    # Example 5: Retry Strategy Decision
    print("Example 5: Retry Strategy Decision")
    await logger.log_decision(
        decision_name="decide_retry_strategy",
        decision_context={
            "error_type": "TransientNetworkError",
            "attempt": 2,
            "max_retries": 3,
            "error_message": "Connection timeout",
        },
        decision_result={
            "action": "retry_with_backoff",
            "confidence": 0.85,
            "reasoning": "Transient error, retry with exponential backoff",
            "backoff_delay_ms": 1000,
            "next_timeout_ms": 5000,
        },
        duration_ms=3,
    )
    print("✓ Retry strategy decision logged\n")

    print("All decision examples completed!")


if __name__ == "__main__":
    asyncio.run(decision_examples())
