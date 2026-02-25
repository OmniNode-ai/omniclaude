# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""NodeQuirkMemoryBridgeEffect -- ONEX Effect Node.

Consumes ``QuirkFinding`` events (from Kafka topic
``onex.evt.omniclaude.quirk-finding-produced.v1``) and promotes each finding
as a behaviour anti-pattern record into OmniMemory via the injected
``ProtocolPatternStore``.

Promotion semantics:
    - Each ``(quirk_type, policy_recommendation)`` pair maps to a distinct
      pattern key in OmniMemory so that upstream consumers (e.g. the Plan DAG
      Generator) can gate or annotate sessions based on known quirk patterns.
    - Promotion is idempotent: feeding the same finding twice increments the
      evidence count but does not create duplicate entries.
    - ``block``-level findings are emitted under an elevated key suffix so that
      consuming nodes can apply strict enforcement without having to re-evaluate
      the recommendation field.

Node type: Effect  (external I/O -- OmniMemory store + optional Kafka publishing)
Node name: NodeQuirkMemoryBridgeEffect

Related:
    - OMN-2533: QuirkSignal / QuirkFinding models
    - OMN-2556: Extractor + classifier (produce QuirkFindings consumed here)
    - OMN-2564: ValidatorRolloutController
    - OMN-2586: This ticket -- OmniMemory wiring + QuirkDashboard read API
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

import logging
from typing import Any

from omniclaude.nodes.node_omnimemory_promotion.models.model_promoted_pattern import (
    ModelPromotedPattern,
)
from omniclaude.nodes.node_omnimemory_promotion.protocol_pattern_store import (
    ProtocolPatternStore,
)
from omniclaude.quirks.models import QuirkFinding

logger = logging.getLogger(__name__)

# Prefix for all quirk-derived pattern keys stored in OmniMemory.
_QUIRK_PATTERN_PREFIX = "QUIRK"


def _derive_quirk_pattern_key(finding: QuirkFinding) -> str:
    """Derive a stable OmniMemory pattern key from a QuirkFinding.

    Key format: ``QUIRK:{quirk_type}:{policy_recommendation}``

    This yields 21 distinct keys (7 quirk types x 3 recommendations)
    so that OmniMemory consumers can look up the worst-case enforcement
    level ever recorded for a given quirk type.

    Args:
        finding: The QuirkFinding to derive a key from.

    Returns:
        Stable, upper-cased pattern key string.
    """
    return (
        f"{_QUIRK_PATTERN_PREFIX}"
        f":{finding.quirk_type.value.upper()}"
        f":{finding.policy_recommendation.upper()}"
    )


def _finding_to_pattern(
    finding: QuirkFinding, existing: ModelPromotedPattern | None
) -> ModelPromotedPattern:
    """Build a ``ModelPromotedPattern`` from a ``QuirkFinding``.

    If an existing pattern is supplied the evidence count and version are
    incremented; otherwise a new version-1 record is created.

    Args:
        finding: The QuirkFinding to convert.
        existing: The current pattern stored in OmniMemory, or ``None``.

    Returns:
        A new ``ModelPromotedPattern`` ready to be saved.
    """
    pattern_key = _derive_quirk_pattern_key(finding)
    new_finding_id = str(finding.finding_id)

    if existing is None:
        return ModelPromotedPattern(
            pattern_id=new_finding_id,
            pattern_key=pattern_key,
            intent_type=f"quirk.{finding.quirk_type.value.lower()}.{finding.policy_recommendation}",
            unit_specs=(
                (
                    "quirk_finding",
                    f"{finding.quirk_type.value} {finding.policy_recommendation} quirk",
                    "quirk_enforcement",
                    finding.policy_recommendation,
                ),
            ),
            dep_specs=(),
            evidence_bundle_ids=(new_finding_id,),
            evidence_count=1,
            version=1,
        )

    # Increment evidence without duplicating if same finding re-delivered.
    existing_ids = set(existing.evidence_bundle_ids)
    if new_finding_id in existing_ids:
        logger.debug(
            "NodeQuirkMemoryBridgeEffect: duplicate finding %s skipped (already in OmniMemory)",
            new_finding_id,
        )
        return existing

    new_ids = (*existing.evidence_bundle_ids, new_finding_id)
    return ModelPromotedPattern(
        pattern_id=existing.pattern_id,
        pattern_key=pattern_key,
        intent_type=existing.intent_type,
        unit_specs=existing.unit_specs,
        dep_specs=existing.dep_specs,
        evidence_bundle_ids=new_ids,
        evidence_count=existing.evidence_count + 1,
        version=existing.version + 1,
    )


class NodeQuirkMemoryBridgeEffect:
    """ONEX Effect Node that wires QuirkFindings into OmniMemory.

    On each ``promote_finding`` call the node:
    1. Derives a stable OmniMemory pattern key from the finding.
    2. Reads the current pattern (if any) from the store.
    3. Writes a new or updated ``ModelPromotedPattern`` back to the store.
    4. Logs the promotion for observability.

    Usage::

        store = StorePatternInMemory()  # or a Qdrant-backed store
        bridge = NodeQuirkMemoryBridgeEffect(store=store)

        finding = ...  # QuirkFinding from NodeQuirkClassifierCompute
        bridge.promote_finding(finding)
    """

    def __init__(self, store: ProtocolPatternStore) -> None:
        """Initialise the memory bridge.

        Args:
            store: OmniMemory storage backend.  Any implementation of
                ``ProtocolPatternStore`` is accepted (in-memory for tests,
                Qdrant-backed for production).
        """
        self._store = store

    def promote_finding(self, finding: QuirkFinding) -> ModelPromotedPattern:
        """Promote a QuirkFinding into OmniMemory.

        Idempotent: re-delivering the same ``finding_id`` is a no-op.

        Args:
            finding: The QuirkFinding to promote.

        Returns:
            The ``ModelPromotedPattern`` that was saved (new or updated).
        """
        pattern_key = _derive_quirk_pattern_key(finding)
        existing = self._store.get_by_key(pattern_key)
        pattern = _finding_to_pattern(finding, existing)

        # Only write if the pattern changed (idempotency guard already in _finding_to_pattern).
        if existing is None or pattern is not existing:
            self._store.save(pattern)
            action = "PROMOTED" if existing is None else "UPDATED"
            logger.info(
                "NodeQuirkMemoryBridgeEffect: %s quirk pattern "
                "(key=%s quirk_type=%s recommendation=%s evidence_count=%d version=%d)",
                action,
                pattern_key,
                finding.quirk_type.value,
                finding.policy_recommendation,
                pattern.evidence_count,
                pattern.version,
            )
        return pattern

    def get_pattern_for_finding(
        self, finding: QuirkFinding
    ) -> ModelPromotedPattern | None:
        """Look up the current OmniMemory pattern for a finding type.

        Args:
            finding: The QuirkFinding whose pattern key to look up.

        Returns:
            Stored pattern, or ``None`` if not yet promoted.
        """
        key = _derive_quirk_pattern_key(finding)
        return self._store.get_by_key(key)

    def get_pattern_by_key(self, pattern_key: str) -> ModelPromotedPattern | None:
        """Look up a quirk pattern by its raw key.

        Args:
            pattern_key: The OmniMemory pattern key (e.g. ``QUIRK:STUB_CODE:WARN``).

        Returns:
            Stored pattern, or ``None`` if not found.
        """
        return self._store.get_by_key(pattern_key)

    # ------------------------------------------------------------------
    # Helpers used by external consumers (e.g. dashboard, CI hooks)
    # ------------------------------------------------------------------

    @staticmethod
    def build_pattern_key(quirk_type_value: str, recommendation: str) -> str:
        """Build the canonical OmniMemory key for a quirk type + recommendation.

        Useful for read-path lookups without constructing a full QuirkFinding.

        Args:
            quirk_type_value: Raw QuirkType enum value (e.g. ``"STUB_CODE"``).
            recommendation: Policy recommendation string (``"observe"``,
                ``"warn"``, or ``"block"``).

        Returns:
            Canonical OmniMemory pattern key.
        """
        return f"{_QUIRK_PATTERN_PREFIX}:{quirk_type_value.upper()}:{recommendation.upper()}"

    def process_payload(self, payload: dict[str, Any]) -> ModelPromotedPattern | None:
        """Process a raw Kafka finding payload dict.

        Deserialises the payload into a ``QuirkFinding`` and promotes it.
        Returns ``None`` and logs a warning if the payload is malformed.

        Args:
            payload: Raw dict from the Kafka finding event body.

        Returns:
            Promoted ``ModelPromotedPattern``, or ``None`` on parse error.
        """
        try:
            finding = QuirkFinding.model_validate(payload)
        except Exception:
            logger.warning(
                "NodeQuirkMemoryBridgeEffect: failed to parse QuirkFinding payload: %r",
                payload,
                exc_info=True,
            )
            return None
        return self.promote_finding(finding)


__all__ = [
    "NodeQuirkMemoryBridgeEffect",
    "_derive_quirk_pattern_key",
]
