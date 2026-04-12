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
)

# All topics below must match entries in omnidash/topics.yaml read_model_topics
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
        head_topic=TopicBase.RUN_EVALUATED,
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


__all__ = ["GOLDEN_CHAIN_DEFINITIONS", "get_chain_definitions"]
