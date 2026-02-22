# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Default Evidence Bundle handler.

Stage 5 of the NL Intent-Plan-Ticket Compiler.

Generates an immutable ModelEvidenceBundle for each executed ticket,
stores it via the injected ProtocolBundleStore, and returns it for
downstream consumers (OmniMemory pattern promotion, OMN-2506).

All timestamps are injected by the caller via ModelBundleGenerateRequest —
no datetime.now() defaults are used.
"""

from __future__ import annotations

import logging
import uuid

from omniclaude.nodes.node_evidence_bundle.models.model_bundle_generate_request import (
    ModelBundleGenerateRequest,
)
from omniclaude.nodes.node_evidence_bundle.models.model_evidence_bundle import (
    ModelEvidenceBundle,
)
from omniclaude.nodes.node_evidence_bundle.protocol_bundle_store import (
    ProtocolBundleStore,
)

__all__ = ["HandlerEvidenceBundleDefault"]

logger = logging.getLogger(__name__)


class HandlerEvidenceBundleDefault:
    """Default handler for evidence bundle generation.

    Generates a ModelEvidenceBundle from a completed ticket execution,
    persists it via the bundle store, and returns it.
    """

    def __init__(self, store: ProtocolBundleStore) -> None:
        """Initialise the evidence bundle handler.

        Args:
            store: Storage backend conforming to ProtocolBundleStore.
        """
        self._store = store

    @property
    def handler_key(self) -> str:
        """Registry key for handler lookup."""
        return "default"

    def generate(
        self,
        request: ModelBundleGenerateRequest,
    ) -> ModelEvidenceBundle:
        """Generate and store an evidence bundle for a ticket execution.

        Args:
            request: Bundle generation request with execution data.

        Returns:
            The generated and stored ModelEvidenceBundle.

        Raises:
            RuntimeError: If the bundle store fails to persist the bundle.
        """
        bundle_id = str(uuid.uuid4())

        bundle = ModelEvidenceBundle(
            bundle_id=bundle_id,
            ticket_id=request.ticket_id,
            work_unit_id=request.work_unit_id,
            dag_id=request.dag_id,
            intent_id=request.intent_id,
            nl_input_hash=request.nl_input_hash,
            outcome=request.outcome,
            ac_records=request.ac_records,
            actual_outputs=request.actual_outputs,
            started_at=request.started_at,
            completed_at=request.completed_at,
        )

        self._store.save(bundle)

        logger.debug(
            "Generated evidence bundle %s for ticket=%s outcome=%s",
            bundle_id,
            request.ticket_id,
            request.outcome.value,
        )

        return bundle
