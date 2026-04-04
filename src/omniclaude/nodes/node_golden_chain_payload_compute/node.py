# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Golden chain payload compute node — builds synthetic test payloads.

Pure COMPUTE node. No side effects. Produces enriched payloads with
correlation_id prefix and assertion declarations for all chain definitions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from omniclaude.nodes.node_golden_chain_payload_compute.chain_registry import (
    get_chain_definitions,
)
from omniclaude.nodes.node_golden_chain_payload_compute.models.model_chain_definition import (
    ModelChainAssertion,
)
from omniclaude.nodes.node_golden_chain_payload_compute.models.model_enriched_payload import (
    ModelEnrichedPayload,
)


def build_payloads(
    chain_filter: list[str] | None = None,
    emitted_at: str | None = None,
    timeout_ms: int = 15000,
) -> list[ModelEnrichedPayload]:
    """Build enriched payloads for all (or filtered) chain definitions.

    Args:
        chain_filter: Optional list of chain names to include.
        emitted_at: ISO-8601 timestamp. Defaults to current UTC time.
        timeout_ms: DB poll timeout per chain.

    Returns:
        List of enriched payloads ready for publish_effect.
    """
    if emitted_at is None:
        emitted_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    chains = get_chain_definitions(chain_filter)
    payloads: list[ModelEnrichedPayload] = []

    for chain in chains:
        short_uuid = uuid4().hex[:12]
        correlation_id = f"golden-chain-{chain.name}-{short_uuid}"

        # Build fixture with injected correlation_id
        fixture = dict(chain.fixture_template)
        fixture["correlation_id"] = correlation_id
        fixture["emitted_at"] = emitted_at

        # Resolve __CORRELATION_ID__ sentinel in assertion expected values
        resolved_assertions = tuple(
            ModelChainAssertion(
                field=a.field,
                op=a.op,
                expected=correlation_id
                if a.expected == "__CORRELATION_ID__"
                else a.expected,
            )
            for a in chain.assertions
        )

        payloads.append(
            ModelEnrichedPayload(
                chain_name=chain.name,
                head_topic=chain.head_topic,
                tail_table=chain.tail_table,
                correlation_id=correlation_id,
                emitted_at=emitted_at,
                fixture=fixture,
                assertions=resolved_assertions,
                timeout_ms=timeout_ms,
            )
        )

    return payloads


__all__ = ["build_payloads"]
