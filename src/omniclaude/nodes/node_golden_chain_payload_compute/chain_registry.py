# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Golden chain registry — the 5 chain definitions for Kafka-to-DB validation.

Chain definitions reference topics from omnidash/topics.yaml (contract-first).
Never hardcode topic strings outside this registry.
"""

from __future__ import annotations

from omniclaude.hooks.topics import TopicBase
from omniclaude.nodes.node_golden_chain_payload_compute.models.model_chain_definition import (
    ModelChainAssertion,
    ModelChainDefinition,
    ModelChainMetadata,
)

# All runnable topics below must match entries in omnidash/topics.yaml read_model_topics.
# The broader metadata registry is kept in parity with omnimarket's canonical YAML
# by scripts/validation/validate_golden_chain_integrity.py.
GOLDEN_CHAIN_DEFINITIONS: tuple[ModelChainDefinition, ...] = (
    # agent_routing_decisions: correlation_id is UUID NOT NULL
    ModelChainDefinition(
        name="registration",
        head_topic=TopicBase.ROUTING_DECISION,
        tail_table="agent_routing_decisions",
        correlation_id_is_uuid=True,
        fixture_template={
            "selected_agent": "golden-chain-test-agent",
            "confidence_score": "0.9500",
            "routing_strategy": "golden-chain-test",
            "entity_id": "00000000-0000-0000-0000-000000000000",
            "session_id": "golden-chain-test-session",
        },
        assertions=(
            ModelChainAssertion(
                field="selected_agent", op="eq", expected="golden-chain-test-agent"
            ),
            ModelChainAssertion(field="confidence_score", op="gte", expected="0.0000"),
            ModelChainAssertion(
                field="correlation_id", op="eq", expected="__CORRELATION_ID__"
            ),
        ),
    ),
    # pattern_learning_artifacts: no correlation_id column; lookup by pattern_name
    ModelChainDefinition(
        name="pattern_learning",
        head_topic=TopicBase.PATTERN_STORED,
        tail_table="pattern_learning_artifacts",
        lookup_column="pattern_name",
        lookup_fixture_key="pattern_name",
        fixture_template={
            "pattern_name": "golden-chain-test-pattern",
            "pattern_type": "golden-chain-test",
            "state": "stored",
        },
        assertions=(
            ModelChainAssertion(
                field="pattern_name", op="eq", expected="golden-chain-test-pattern"
            ),
            ModelChainAssertion(
                field="pattern_type", op="eq", expected="golden-chain-test"
            ),
        ),
    ),
    # delegation_events: correlation_id is TEXT NOT NULL
    ModelChainDefinition(
        name="delegation",
        head_topic=TopicBase.TASK_DELEGATED,
        tail_table="delegation_events",
        fixture_template={
            "delegate_model": "golden-chain-test-model",
            "task_type": "golden-chain-test",
            "session_id": "golden-chain-test-session",
            "cost_savings_usd": 0.0112,
            "cost_usd": 0.001,
            "delegation_latency_ms": 150,
        },
        assertions=(
            ModelChainAssertion(
                field="delegate_model", op="eq", expected="golden-chain-test-model"
            ),
            ModelChainAssertion(
                field="task_type", op="eq", expected="golden-chain-test"
            ),
            ModelChainAssertion(
                field="correlation_id", op="eq", expected="__CORRELATION_ID__"
            ),
        ),
    ),
    # llm_routing_decisions: correlation_id migrated from TEXT to UUID by 0011a
    ModelChainDefinition(
        name="routing",
        head_topic=TopicBase.LLM_ROUTING_DECISION,
        tail_table="llm_routing_decisions",
        correlation_id_is_uuid=True,
        fixture_template={
            "selected_model": "golden-chain-test-model",
            "decision_method": "fallback",
            "session_id": "golden-chain-test-session",
        },
        assertions=(
            ModelChainAssertion(
                field="selected_model", op="eq", expected="golden-chain-test-model"
            ),
            ModelChainAssertion(
                field="decision_method", op="in", expected=["llm", "fuzzy", "fallback"]
            ),
            ModelChainAssertion(
                field="correlation_id", op="eq", expected="__CORRELATION_ID__"
            ),
        ),
    ),
    # session_outcomes: correlation_id column added by migration 0058 (OMN-8521)
    ModelChainDefinition(
        name="evaluation",
        head_topic=TopicBase.SESSION_OUTCOME_EVT,
        tail_table="session_outcomes",
        fixture_template={
            "outcome": "success",
            "session_id": "golden-chain-test-session",
        },
        assertions=(
            ModelChainAssertion(field="outcome", op="eq", expected="success"),
            ModelChainAssertion(
                field="correlation_id", op="eq", expected="__CORRELATION_ID__"
            ),
        ),
    ),
)

GOLDEN_CHAIN_METADATA: tuple[ModelChainMetadata, ...] = (
    ModelChainMetadata(
        name="registration",
        head_topic=TopicBase.ROUTING_DECISION,
        tail_table="agent_routing_decisions",
        expected_fields=("correlation_id", "selected_agent"),
    ),
    ModelChainMetadata(
        name="pattern_learning",
        head_topic=TopicBase.PATTERN_STORED,
        tail_table="pattern_learning_artifacts",
        expected_fields=("correlation_id",),
    ),
    ModelChainMetadata(
        name="delegation",
        head_topic=TopicBase.TASK_DELEGATED,
        tail_table="delegation_events",
        expected_fields=(
            "correlation_id",
            "tokens_to_compliance",
            "compliance_attempts",
        ),
    ),
    ModelChainMetadata(
        name="routing",
        head_topic=TopicBase.LLM_ROUTING_DECISION,
        tail_table="llm_routing_decisions",
        expected_fields=("correlation_id",),
    ),
    ModelChainMetadata(
        name="evaluation",
        head_topic=TopicBase.SESSION_OUTCOME_EVT,
        tail_table="session_outcomes",
        expected_fields=("session_id",),
    ),
    ModelChainMetadata(
        name="sea_acceptance",
        head_topic=TopicBase.DELEGATION_REQUEST,
        tail_table="delegation_events",
        expected_fields=("correlation_id", "task_type", "delegated_to"),
        proof_classification="diagnostic",
        replay_status="replay-not-applicable",
        stages=(
            {
                "name": "routing_decision",
                "handler": "node_delegation_routing_reducer.HandlerRoutingIntent",
                "topic": TopicBase.DELEGATION_ROUTING_DECISION,
            },
            {
                "name": "inference_response",
                "handler": "node_llm_delegation_call_effect.HandlerInferenceIntent",
                "topic": TopicBase.DELEGATION_INFERENCE_RESPONSE,
            },
            {
                "name": "terminal_projection",
                "handler": "node_projection_delegation.HandlerProjectionDelegation",
                "topic": TopicBase.DELEGATION_INFRA_COMPLETED,
            },
        ),
    ),
    ModelChainMetadata(
        name="d3_local_routing",
        head_topic=TopicBase.DELEGATION_INFERENCE_REQUEST,
        tail_table="delegation_events",
        expected_fields=("correlation_id", "base_url", "model"),
    ),
    ModelChainMetadata(
        name="d1_d2_scaffold",
        head_topic=TopicBase.DELEGATION_INFRA_COMPLETED,
        tail_table="delegation_events",
        expected_fields=("correlation_id", "node_name", "contract_passed", "content"),
    ),
    ModelChainMetadata(
        name="d4_blank_content",
        head_topic=TopicBase.DELEGATION_INFERENCE_RESPONSE,
        tail_table="delegation_events",
        expected_fields=("correlation_id", "content", "model_used"),
    ),
    ModelChainMetadata(
        name="d9_wheel_module",
        head_topic=TopicBase.DELEGATION_REQUEST,
        tail_table="delegation_events",
        expected_fields=("correlation_id", "node_startup_ok"),
    ),
    ModelChainMetadata(
        name="f1_publish_loop",
        head_topic=TopicBase.DELEGATION_REQUEST,
        tail_table="delegation_events",
        expected_fields=("correlation_id", "published_at"),
    ),
    ModelChainMetadata(
        name="delegation_inference_round_trip",
        head_topic=TopicBase.DELEGATION_INFERENCE_REQUEST,
        tail_table=f"event_bus:{TopicBase.DELEGATION_INFERENCE_RESPONSE}",
        expected_fields=(
            "correlation_id",
            "content",
            "model_used",
            "llm_call_id",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
        ),
        proof_classification="diagnostic",
        replay_status="replay-not-applicable",
        stages=(
            {
                "name": "inference_request",
                "handler": "node_llm_delegation_call_effect.HandlerInferenceIntent",
                "topic": TopicBase.DELEGATION_INFERENCE_REQUEST,
            },
            {
                "name": "inference_response",
                "handler": "node_llm_delegation_call_effect.HandlerInferenceIntent",
                "topic": TopicBase.DELEGATION_INFERENCE_RESPONSE,
            },
        ),
    ),
    ModelChainMetadata(
        name="delegation_projection_materialization",
        head_topic=TopicBase.DELEGATION_INFRA_COMPLETED,
        tail_table="delegation_events",
        expected_fields=(
            "correlation_id",
            "task_type",
            "delegated_to",
            "model_name",
            "quality_gate_passed",
            "response_text",
            "tokens_input",
            "tokens_output",
            "tokens_to_compliance",
            "compliance_attempts",
        ),
        proof_classification="diagnostic",
        replay_status="replay-proven",
        stages=(
            {
                "name": "delegation_completed",
                "handler": "node_projection_delegation.HandlerProjectionDelegation",
                "topic": TopicBase.DELEGATION_INFRA_COMPLETED,
            },
            {
                "name": "delegation_events_row",
                "handler": "node_projection_delegation.HandlerProjectionDelegation",
                "table": "delegation_events",
            },
        ),
    ),
)


def get_chain_definitions(
    chain_filter: list[str] | None = None,
) -> tuple[ModelChainDefinition, ...]:
    """Return chain definitions, optionally filtered by name.

    Args:
        chain_filter: If provided, only return chains whose name is in this list.

    Returns:
        Tuple of matching chain definitions.
    """
    if chain_filter is None:
        return GOLDEN_CHAIN_DEFINITIONS
    return tuple(c for c in GOLDEN_CHAIN_DEFINITIONS if c.name in chain_filter)


def get_chain_metadata(
    chain_filter: list[str] | None = None,
) -> tuple[ModelChainMetadata, ...]:
    """Return canonical chain metadata, optionally filtered by name."""
    if chain_filter is None:
        return GOLDEN_CHAIN_METADATA
    return tuple(c for c in GOLDEN_CHAIN_METADATA if c.name in chain_filter)


__all__ = [
    "GOLDEN_CHAIN_DEFINITIONS",
    "GOLDEN_CHAIN_METADATA",
    "get_chain_definitions",
    "get_chain_metadata",
]
