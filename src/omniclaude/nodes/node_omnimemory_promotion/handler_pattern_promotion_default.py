# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Default OmniMemory Pattern Promotion handler.

Stage 6 of the NL Intent-Plan-Ticket Compiler.

Evaluates whether a ticket generation pattern meets promotion criteria and,
if so, writes it to OmniMemory via the injected ProtocolPatternStore.

Promotion is idempotent:
- If the exact same pattern key already exists with the same or higher evidence
  count, the result is ALREADY_CURRENT (no-op, stale requests are safe).
- If the pattern exists but with strictly lower evidence count, the version is
  incremented (VERSION_BUMPED).
- If the pattern is new and meets criteria, it is PROMOTED.
- If criteria are not met (evidence threshold or ACs gate), the result is
  SKIPPED (no write).

Promoted patterns are retrievable by the Plan DAG Generator (OMN-2502)
via pattern_key lookup to short-circuit full DAG generation.
"""

from __future__ import annotations

import hashlib
import logging
import uuid

from omniclaude.nodes.node_omnimemory_promotion.enums.enum_promotion_status import (
    EnumPromotionStatus,
)
from omniclaude.nodes.node_omnimemory_promotion.models.model_pattern_promotion_request import (
    ModelPatternPromotionRequest,
)
from omniclaude.nodes.node_omnimemory_promotion.models.model_pattern_promotion_result import (
    ModelPatternPromotionResult,
)
from omniclaude.nodes.node_omnimemory_promotion.models.model_promoted_pattern import (
    ModelPromotedPattern,
)
from omniclaude.nodes.node_omnimemory_promotion.protocol_pattern_store import (
    ProtocolPatternStore,
)

__all__ = ["HandlerPatternPromotionDefault"]

logger = logging.getLogger(__name__)


class HandlerPatternPromotionDefault:
    """Default handler for OmniMemory pattern promotion.

    Evaluates promotion criteria, writes eligible patterns to OmniMemory,
    and logs cache hits for observability.
    """

    def __init__(self, store: ProtocolPatternStore) -> None:
        """Initialise the pattern promotion handler.

        Args:
            store: OmniMemory storage backend conforming to ProtocolPatternStore.
        """
        self._store = store

    @property
    def handler_key(self) -> str:
        """Registry key for handler lookup."""
        return "default"

    def promote(
        self,
        request: ModelPatternPromotionRequest,
    ) -> ModelPatternPromotionResult:
        """Evaluate and potentially promote a ticket generation pattern.

        Args:
            request: Promotion request with pattern template and evidence data.

        Returns:
            ModelPatternPromotionResult with status and promoted pattern (if any).
        """
        pattern_key = _derive_pattern_key(request.intent_type, request.unit_specs)
        evidence_threshold_met = (
            request.evidence_count >= request.criteria.min_evidence_count
        )
        acs_gate_met = (
            not request.criteria.require_all_acs_passing or request.all_acs_passing
        )
        criteria_met = evidence_threshold_met and acs_gate_met

        if not criteria_met:
            logger.debug(
                "Pattern promotion SKIPPED for intent=%s "
                "(evidence=%d, required=%d, evidence_threshold_met=%s, acs_gate_met=%s)",
                request.intent_type,
                request.evidence_count,
                request.criteria.min_evidence_count,
                evidence_threshold_met,
                acs_gate_met,
            )
            return ModelPatternPromotionResult(
                status=EnumPromotionStatus.SKIPPED,
                pattern_key=pattern_key,
                criteria_met=False,
                evidence_count=request.evidence_count,
                min_evidence_required=request.criteria.min_evidence_count,
            )

        existing = self._store.get_by_key(pattern_key)

        if existing is None:
            # First-time promotion
            pattern = ModelPromotedPattern(
                pattern_id=str(uuid.uuid4()),
                pattern_key=pattern_key,
                intent_type=request.intent_type,
                unit_specs=request.unit_specs,
                dep_specs=request.dep_specs,
                evidence_bundle_ids=request.evidence_bundle_ids,
                evidence_count=request.evidence_count,
                version=1,
            )
            self._store.save(pattern)
            logger.info(
                "Pattern PROMOTED for intent=%s key=%s evidence=%d",
                request.intent_type,
                pattern_key,
                request.evidence_count,
            )
            return ModelPatternPromotionResult(
                status=EnumPromotionStatus.PROMOTED,
                promoted_pattern=pattern,
                pattern_key=pattern_key,
                criteria_met=True,
                evidence_count=request.evidence_count,
                min_evidence_required=request.criteria.min_evidence_count,
            )

        if request.evidence_count <= existing.evidence_count:
            # Idempotent or stale: do not downgrade or overwrite higher-evidence pattern
            logger.debug(
                "Pattern ALREADY_CURRENT for intent=%s key=%s (evidence=%d <= %d)",
                request.intent_type,
                pattern_key,
                request.evidence_count,
                existing.evidence_count,
            )
            return ModelPatternPromotionResult(
                status=EnumPromotionStatus.ALREADY_CURRENT,
                promoted_pattern=existing,
                pattern_key=pattern_key,
                criteria_met=True,
                evidence_count=request.evidence_count,
                min_evidence_required=request.criteria.min_evidence_count,
            )

        # Version bump — more evidence available than currently stored
        bumped = ModelPromotedPattern(
            pattern_id=existing.pattern_id,
            pattern_key=pattern_key,
            intent_type=request.intent_type,
            unit_specs=request.unit_specs,
            dep_specs=request.dep_specs,
            evidence_bundle_ids=request.evidence_bundle_ids,
            evidence_count=request.evidence_count,
            version=existing.version + 1,
        )
        self._store.save(bumped)
        logger.info(
            "Pattern VERSION_BUMPED for intent=%s key=%s v%d→v%d evidence=%d",
            request.intent_type,
            pattern_key,
            existing.version,
            bumped.version,
            request.evidence_count,
        )
        return ModelPatternPromotionResult(
            status=EnumPromotionStatus.VERSION_BUMPED,
            promoted_pattern=bumped,
            pattern_key=pattern_key,
            criteria_met=True,
            evidence_count=request.evidence_count,
            min_evidence_required=request.criteria.min_evidence_count,
        )

    def lookup(
        self, intent_type: str, unit_specs: tuple[tuple[str, str, str, str], ...]
    ) -> ModelPromotedPattern | None:
        """Look up a promoted pattern for the given intent type and shape.

        Used by the Plan DAG Generator to check for a cache hit before
        running full template generation.  A cache hit is logged for
        observability.

        Args:
            intent_type: The intent type to look up.
            unit_specs: The work unit specs defining the pattern shape.

        Returns:
            Promoted pattern if found; None for a cache miss (fallback to full generation).
        """
        pattern_key = _derive_pattern_key(intent_type, unit_specs)
        result = self._store.get_by_key(pattern_key)
        if result is not None:
            logger.info(
                "OmniMemory cache HIT for intent=%s key=%s", intent_type, pattern_key
            )
        else:
            logger.debug(
                "OmniMemory cache MISS for intent=%s key=%s", intent_type, pattern_key
            )
        return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _derive_pattern_key(
    intent_type: str,
    unit_specs: tuple[tuple[str, str, str, str], ...],
) -> str:
    """Derive a stable, normalized pattern lookup key.

    Key is: ``{intent_type}:{sha256_of_sorted_unit_types}``

    Args:
        intent_type: Intent type string.
        unit_specs: Work unit specs (local_id, title, unit_type, scope).

    Returns:
        Normalized pattern key string.
    """
    # Only unit_type values participate in the key (not local IDs or scopes)
    sorted_types = sorted(spec[2] for spec in unit_specs)
    shape_input = "|".join(sorted_types).encode()
    shape_hash = hashlib.sha256(shape_input).hexdigest()[:16]
    return f"{intent_type.upper()}:{shape_hash}"
