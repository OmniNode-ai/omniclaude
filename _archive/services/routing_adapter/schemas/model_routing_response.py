#!/usr/bin/env python3
"""
Model: Routing Response Payload

Pydantic model for agent routing response payloads.
Contains routing recommendations with confidence scores and metadata.

Event Flow:
    agent-router-service → agent.routing.completed.v1 → Agent

Examples:
    Single recommendation:
    ```python
    response = ModelRoutingResponse(
        correlation_id="abc-123",
        recommendations=[
            ModelAgentRecommendation(
                agent_name="agent-performance",
                agent_title="Performance Optimization Specialist",
                confidence=ModelRoutingConfidence(
                    total=0.92,
                    trigger_score=0.95,
                    context_score=0.90,
                    capability_score=0.88,
                    historical_score=0.95
                ),
                reason="Strong trigger match with 'optimize' keyword",
                definition_path="/Users/jonah/.claude/agents/omniclaude/agent-performance.yaml"
            )
        ],
        routing_metadata=ModelRoutingMetadata(
            routing_time_ms=45,
            cache_hit=False,
            candidates_evaluated=5
        )
    )
    ```

Created: 2025-10-30
Reference: database_event_client.py, agent_router.py
"""


from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelRoutingConfidence(BaseModel):
    """
    Confidence score breakdown for routing decision.

    Attributes:
        total: Overall confidence score 0.0-1.0
        trigger_score: Trigger matching confidence (40% weight)
        context_score: Context alignment confidence (30% weight)
        capability_score: Capability matching confidence (20% weight)
        historical_score: Historical success rate confidence (10% weight)
        explanation: Human-readable explanation of confidence calculation
    """

    total: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall confidence score (0.0-1.0)",
    )
    trigger_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Trigger matching confidence (40% weight)",
    )
    context_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Context alignment confidence (30% weight)",
    )
    capability_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Capability matching confidence (20% weight)",
    )
    historical_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Historical success rate confidence (10% weight)",
    )
    explanation: str = Field(
        ...,
        min_length=1,
        description="Human-readable explanation of confidence calculation",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total": 0.92,
                "trigger_score": 0.95,
                "context_score": 0.90,
                "capability_score": 0.88,
                "historical_score": 0.95,
                "explanation": "High confidence match on 'optimize' and 'database' triggers with strong context alignment",
            }
        }
    )


class ModelAgentRecommendation(BaseModel):
    """
    Agent recommendation with confidence score.

    Attributes:
        agent_name: Agent identifier (e.g., "agent-performance")
        agent_title: Human-readable agent title
        confidence: Confidence score breakdown
        reason: Human-readable reason for recommendation
        definition_path: Absolute path to agent YAML definition
        alternatives: Optional list of alternative agents considered
    """

    agent_name: str = Field(
        ...,
        min_length=1,
        description="Agent identifier (e.g., 'agent-performance')",
    )
    agent_title: str = Field(
        ...,
        min_length=1,
        description="Human-readable agent title",
    )
    confidence: ModelRoutingConfidence = Field(
        ...,
        description="Confidence score breakdown",
    )
    reason: str = Field(
        ...,
        min_length=1,
        description="Human-readable reason for recommendation",
    )
    definition_path: str = Field(
        ...,
        min_length=1,
        description="Absolute path to agent YAML definition",
    )
    alternatives: list[str] | None = Field(
        default=None,
        description="Optional list of alternative agents considered",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_name": "agent-performance",
                "agent_title": "Performance Optimization Specialist",
                "confidence": {
                    "total": 0.92,
                    "trigger_score": 0.95,
                    "context_score": 0.90,
                    "capability_score": 0.88,
                    "historical_score": 0.95,
                    "explanation": "High confidence match on 'optimize' and 'database' triggers",
                },
                "reason": "Strong trigger match with 'optimize' keyword and database context",
                "definition_path": "/Users/jonah/.claude/agents/onex/agent-performance.yaml",
                "alternatives": ["agent-database-architect", "agent-test-generator"],
            }
        }
    )


class ModelRoutingMetadata(BaseModel):
    """
    Metadata about the routing decision process.

    Attributes:
        routing_time_ms: Time taken for routing decision (milliseconds)
        cache_hit: Whether result was retrieved from cache
        candidates_evaluated: Number of agents considered
        routing_strategy: Strategy used (e.g., "enhanced_fuzzy_matching")
        service_version: Optional routing service version
    """

    routing_time_ms: int = Field(
        ...,
        ge=0,
        description="Time taken for routing decision (milliseconds)",
    )
    cache_hit: bool = Field(
        ...,
        description="Whether result was retrieved from cache",
    )
    candidates_evaluated: int = Field(
        ...,
        ge=0,
        description="Number of agents considered",
    )
    routing_strategy: str = Field(
        ...,
        min_length=1,
        description="Strategy used (e.g., 'enhanced_fuzzy_matching')",
    )
    service_version: str | None = Field(
        default=None,
        description="Optional routing service version",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "routing_time_ms": 45,
                "cache_hit": False,
                "candidates_evaluated": 5,
                "routing_strategy": "enhanced_fuzzy_matching",
                "service_version": "1.0.0",
            }
        }
    )


class ModelRoutingResponse(BaseModel):
    """
    Agent routing response payload.

    This is the payload inside the event envelope when routing completes successfully.

    Attributes:
        correlation_id: Unique request identifier matching the request
        recommendations: List of agent recommendations (sorted by confidence)
        routing_metadata: Metadata about the routing process
        selected_agent: Optional pre-selected agent (highest confidence)

    Validation:
        - recommendations: Must have at least one recommendation
        - correlation_id: Must be valid UUID string

    Examples:
        ```python
        response = ModelRoutingResponse(
            correlation_id="abc-123",
            recommendations=[
                ModelAgentRecommendation(
                    agent_name="agent-performance",
                    agent_title="Performance Optimization Specialist",
                    confidence=ModelRoutingConfidence(
                        total=0.92,
                        trigger_score=0.95,
                        context_score=0.90,
                        capability_score=0.88,
                        historical_score=0.95,
                        explanation="High confidence match"
                    ),
                    reason="Strong trigger match",
                    definition_path="/path/to/agent.yaml"
                )
            ],
            routing_metadata=ModelRoutingMetadata(
                routing_time_ms=45,
                cache_hit=False,
                candidates_evaluated=5,
                routing_strategy="enhanced_fuzzy_matching"
            )
        )
        ```
    """

    correlation_id: str = Field(
        ...,
        description="Unique request identifier matching the request (UUID string)",
    )
    recommendations: list[ModelAgentRecommendation] = Field(
        ...,
        min_length=1,
        description="List of agent recommendations (sorted by confidence, highest first)",
    )
    routing_metadata: ModelRoutingMetadata = Field(
        ...,
        description="Metadata about the routing process",
    )
    selected_agent: str | None = Field(
        default=None,
        description="Optional pre-selected agent (highest confidence)",
    )

    @field_validator("recommendations")
    @classmethod
    def validate_recommendations_sorted(
        cls, v: list[ModelAgentRecommendation]
    ) -> list[ModelAgentRecommendation]:
        """Validate recommendations are sorted by confidence (highest first)."""
        if len(v) > 1:
            for i in range(len(v) - 1):
                if v[i].confidence.total < v[i + 1].confidence.total:
                    raise ValueError(
                        "Recommendations must be sorted by confidence (highest first)"
                    )
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "correlation_id": "a2f33abd-34c2-4d63-bfe7-2cb14ded13fd",
                "recommendations": [
                    {
                        "agent_name": "agent-performance",
                        "agent_title": "Performance Optimization Specialist",
                        "confidence": {
                            "total": 0.92,
                            "trigger_score": 0.95,
                            "context_score": 0.90,
                            "capability_score": 0.88,
                            "historical_score": 0.95,
                            "explanation": "High confidence match on 'optimize' and 'database' triggers",
                        },
                        "reason": "Strong trigger match with 'optimize' keyword and database context",
                        "definition_path": "/Users/jonah/.claude/agents/onex/agent-performance.yaml",
                        "alternatives": [
                            "agent-database-architect",
                            "agent-test-generator",
                        ],
                    }
                ],
                "routing_metadata": {
                    "routing_time_ms": 45,
                    "cache_hit": False,
                    "candidates_evaluated": 5,
                    "routing_strategy": "enhanced_fuzzy_matching",
                    "service_version": "1.0.0",
                },
                "selected_agent": "agent-performance",
            }
        }
    )


__all__ = [
    "ModelRoutingResponse",
    "ModelAgentRecommendation",
    "ModelRoutingConfidence",
    "ModelRoutingMetadata",
]
