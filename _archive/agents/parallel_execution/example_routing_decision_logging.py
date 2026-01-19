"""
Example: Routing Decision Logging

Demonstrates how to use the TraceLogger for routing decision logging.
"""

import asyncio

from trace_logger import get_trace_logger


async def example_routing_decision():
    """Example of logging a routing decision."""
    logger = get_trace_logger()

    # Start a coordinator trace
    coord_id = await logger.start_coordinator_trace(
        coordinator_type="routing",
        total_agents=1,
        metadata={"workflow": "agent_selection"},
    )

    # Log a routing decision
    await logger.log_routing_decision(
        user_request="Help me optimize my database queries for better performance",
        selected_agent="agent-performance-optimizer",
        confidence_score=0.92,
        alternatives=[
            {
                "agent_name": "agent-database-specialist",
                "confidence": 0.85,
                "match_type": "fuzzy",
                "reason": "Database keyword match",
            },
            {
                "agent_name": "agent-debug-intelligence",
                "confidence": 0.68,
                "match_type": "capability",
                "reason": "Performance analysis capability",
            },
            {
                "agent_name": "agent-code-quality",
                "confidence": 0.42,
                "match_type": "context",
                "reason": "Code improvement context",
            },
        ],
        reasoning=(
            "Selected agent-performance-optimizer due to: "
            "1) Explicit 'optimize' and 'performance' keywords in request, "
            "2) High confidence score from enhanced trigger matching (0.92), "
            "3) Strong capability alignment with performance optimization domain"
        ),
        routing_strategy="enhanced_fuzzy_matching",
        context={
            "domain": "performance_optimization",
            "project_type": "database_heavy",
            "previous_agent": None,
        },
        routing_time_ms=45.3,
    )

    # Log another routing decision with lower confidence
    await logger.log_routing_decision(
        user_request="Fix the thing that's broken",
        selected_agent="agent-debug-intelligence",
        confidence_score=0.58,
        alternatives=[
            {
                "agent_name": "agent-code-quality",
                "confidence": 0.55,
                "match_type": "generic",
                "reason": "Generic fix request",
            },
            {
                "agent_name": "agent-workflow-coordinator",
                "confidence": 0.51,
                "match_type": "fallback",
                "reason": "Low confidence fallback",
            },
        ],
        reasoning=(
            "Selected agent-debug-intelligence with low confidence due to: "
            "1) Vague request lacking specific context, "
            "2) No clear keywords for specialized agents, "
            "3) Debug intelligence can handle general troubleshooting"
        ),
        routing_strategy="fallback",
        context={"domain": "general", "ambiguity_score": 0.85, "previous_agent": None},
        routing_time_ms=22.1,
    )

    # End coordinator trace
    await logger.end_coordinator_trace(coord_id)

    print("✅ Routing decisions logged successfully!")


async def example_query_routing_decisions():
    """Example of querying routing decisions."""
    logger = get_trace_logger()

    print("\n" + "=" * 80)
    print("📊 Routing Decision Query Examples")
    print("=" * 80)

    # Get recent routing decisions
    print("\n1. Recent routing decisions:")
    recent = await logger.get_recent_routing_decisions(limit=5)
    for event in recent:
        metadata = event.metadata
        print(
            f"   - {metadata['selected_agent']} (confidence: {metadata['confidence_score']:.2%})"
        )
        print(f"     Request: {metadata['user_request'][:60]}...")

    # Get low confidence decisions
    print("\n2. Low confidence routing decisions (<0.7):")
    low_conf = await logger.get_low_confidence_routing_decisions(
        confidence_threshold=0.7
    )
    for event in low_conf:
        metadata = event.metadata
        print(
            f"   - {metadata['selected_agent']} (confidence: {metadata['confidence_score']:.2%})"
        )
        print(f"     Request: {metadata['user_request'][:60]}...")
        print(f"     Reasoning: {metadata['reasoning'][:80]}...")

    # Get decisions for specific agent
    print("\n3. Decisions for agent-debug-intelligence:")
    agent_decisions = await logger.get_routing_decisions_for_agent(
        "agent-debug-intelligence"
    )
    print(f"   Found {len(agent_decisions)} decisions for this agent")

    # Get routing statistics
    print("\n4. Routing Statistics:")
    await logger.print_routing_statistics()


async def main():
    """Run all examples."""
    print("🚀 Starting routing decision logging examples...\n")

    # Log some routing decisions
    await example_routing_decision()

    # Query and display routing decisions
    await example_query_routing_decisions()

    print("\n✅ All examples completed!")


if __name__ == "__main__":
    asyncio.run(main())
