#!/usr/bin/env python3
"""
Intelligence Context Model

Captures intelligence gathered from RAG, code examples, and domain patterns
for enhanced node generation.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class IntelligenceContext(BaseModel):
    """
    Intelligence context for template generation.

    Contains best practices, patterns, and domain-specific knowledge
    gathered from RAG queries and code analysis.
    """

    # Node Type Patterns
    node_type_patterns: List[str] = Field(
        default_factory=list,
        description="Best practices specific to the node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)",
    )

    # Common Operations
    common_operations: List[str] = Field(
        default_factory=list,
        description="Common operations found in similar nodes (e.g., 'create', 'update', 'delete')",
    )

    # Required Mixins
    required_mixins: List[str] = Field(
        default_factory=list,
        description="Recommended mixins based on requirements (e.g., 'MixinRetry', 'MixinEventBus')",
    )

    # Performance Targets
    performance_targets: Dict[str, Any] = Field(
        default_factory=dict,
        description="Performance targets from similar implementations (e.g., {'query_time_ms': 10})",
    )

    # Error Scenarios
    error_scenarios: List[str] = Field(
        default_factory=list,
        description="Common error scenarios to handle (e.g., 'Connection timeout', 'Constraint violation')",
    )

    # Domain Best Practices
    domain_best_practices: List[str] = Field(
        default_factory=list,
        description="Domain-specific patterns and best practices (e.g., 'Use prepared statements for SQL')",
    )

    # Code Examples
    code_examples: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Relevant code examples from similar implementations",
    )

    # Anti-patterns to Avoid
    anti_patterns: List[str] = Field(
        default_factory=list,
        description="Anti-patterns to avoid based on historical issues",
    )

    # Dependencies
    recommended_dependencies: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Recommended external dependencies (e.g., [{'name': 'PostgreSQL', 'type': 'database'}])",
    )

    # Testing Recommendations
    testing_recommendations: List[str] = Field(
        default_factory=list,
        description="Testing strategies based on node type and domain",
    )

    # Security Considerations
    security_considerations: List[str] = Field(
        default_factory=list,
        description="Security best practices relevant to this node",
    )

    # RAG Query Metadata
    rag_sources: List[str] = Field(
        default_factory=list, description="Sources of intelligence (for traceability)"
    )

    confidence_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score for intelligence quality (0.0-1.0)",
    )

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class NodeTypeIntelligence(BaseModel):
    """
    Node type-specific intelligence patterns.

    Provides default intelligence for each node type when
    RAG intelligence is not available.
    """

    node_type: str = Field(
        ..., description="Node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)"
    )

    default_patterns: List[str] = Field(
        default_factory=list, description="Default best practices for this node type"
    )

    typical_operations: List[str] = Field(
        default_factory=list, description="Typical operations for this node type"
    )

    common_mixins: List[str] = Field(
        default_factory=list, description="Commonly used mixins for this node type"
    )

    performance_baseline: Dict[str, Any] = Field(
        default_factory=dict,
        description="Baseline performance metrics for this node type",
    )

    model_config = ConfigDict(extra="forbid")


# Default intelligence for each node type
DEFAULT_NODE_TYPE_INTELLIGENCE: Dict[str, NodeTypeIntelligence] = {
    "EFFECT": NodeTypeIntelligence(
        node_type="EFFECT",
        default_patterns=[
            "Use connection pooling for database connections",
            "Implement circuit breaker pattern for external API calls",
            "Use retry logic with exponential backoff for transient failures",
            "Validate inputs before external operations",
            "Use prepared statements for SQL queries",
            "Implement proper transaction management",
            "Log all external interactions for audit trail",
            "Use timeout mechanisms for all I/O operations",
        ],
        typical_operations=["create", "read", "update", "delete", "execute"],
        common_mixins=["MixinRetry", "MixinEventBus", "MixinHealthCheck"],
        performance_baseline={"max_response_time_ms": 500, "timeout_ms": 5000},
    ),
    "COMPUTE": NodeTypeIntelligence(
        node_type="COMPUTE",
        default_patterns=[
            "Ensure pure functions with no side effects",
            "Use immutable data structures",
            "Implement deterministic algorithms",
            "Cache expensive computations when appropriate",
            "Optimize for CPU efficiency",
            "Use parallel processing for batch operations",
            "Validate computational inputs strictly",
            "Document algorithm complexity (Big O notation)",
        ],
        typical_operations=["calculate", "transform", "validate", "analyze"],
        common_mixins=["MixinCaching", "MixinValidation"],
        performance_baseline={"single_operation_max_ms": 2000, "cpu_bound": True},
    ),
    "REDUCER": NodeTypeIntelligence(
        node_type="REDUCER",
        default_patterns=[
            "Implement state aggregation with correlation_id grouping",
            "Emit intents instead of executing side effects",
            "Use FSM (Finite State Machine) for state transitions",
            "Implement windowing for time-based aggregations",
            "Handle out-of-order events gracefully",
            "Maintain idempotency for event processing",
            "Use event sourcing patterns for state rebuilding",
            "Implement proper state persistence and recovery",
        ],
        typical_operations=["aggregate", "reduce", "accumulate", "merge"],
        common_mixins=["MixinEventBus", "MixinStateMachine", "MixinPersistence"],
        performance_baseline={
            "aggregation_window_ms": 1000,
            "max_aggregation_delay_ms": 5000,
        },
    ),
    "ORCHESTRATOR": NodeTypeIntelligence(
        node_type="ORCHESTRATOR",
        default_patterns=[
            "Use lease management for distributed coordination",
            "Implement epoch-based versioning for workflow state",
            "Issue ModelAction with proper lease_id and epoch",
            "Manage workflow dependencies and ordering",
            "Implement saga pattern for compensating transactions",
            "Use distributed locks for critical sections",
            "Implement workflow timeouts and retry policies",
            "Maintain workflow state for recovery and replay",
        ],
        typical_operations=["coordinate", "orchestrate", "schedule", "monitor"],
        common_mixins=["MixinEventBus", "MixinWorkflow", "MixinLeaseManager"],
        performance_baseline={
            "workflow_timeout_ms": 30000,
            "coordination_overhead_ms": 100,
        },
    ),
}


def get_default_intelligence(node_type: str) -> Optional[IntelligenceContext]:
    """
    Get default intelligence for a node type.

    Args:
        node_type: Node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)

    Returns:
        IntelligenceContext with default patterns, or None if unknown type
    """
    node_intel = DEFAULT_NODE_TYPE_INTELLIGENCE.get(node_type)
    if not node_intel:
        return None

    return IntelligenceContext(
        node_type_patterns=node_intel.default_patterns,
        common_operations=node_intel.typical_operations,
        required_mixins=node_intel.common_mixins,
        performance_targets=node_intel.performance_baseline,
        rag_sources=["default_node_type_intelligence"],
        confidence_score=0.5,  # Medium confidence for defaults
    )
