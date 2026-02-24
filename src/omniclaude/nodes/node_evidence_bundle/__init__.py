# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""NodeEvidenceBundleCompute — Stage 5 of the NL Intent-Plan-Ticket Compiler.

Generates immutable evidence bundles that link each executed ticket to its
outcome, enabling the OmniMemory learning loop (OMN-2506).

Capability: nl.evidence.bundle.compute

Exported Components:
    Node:
        NodeEvidenceBundleCompute - Thin coordination shell

    Models:
        ModelAcVerificationRecord - Per-AC verification result
        ModelBundleGenerateRequest - Input to the bundle generator
        ModelEvidenceBundle - Immutable evidence artifact

    Enums:
        EnumAcVerdict - PASS/FAIL/SKIPPED/ERROR per acceptance criterion
        EnumExecutionOutcome - Overall ticket execution outcome

    Protocols:
        ProtocolBundleStore - Storage backend interface

    Implementations:
        HandlerEvidenceBundleDefault - Default bundle generation handler
        StoreBundleInMemory - In-memory store for testing

Example Usage:
    ```python
    from omniclaude.nodes.node_evidence_bundle import (
        HandlerEvidenceBundleDefault,
        ModelBundleGenerateRequest,
        StoreBundleInMemory,
    )

    store = StoreBundleInMemory()
    handler = HandlerEvidenceBundleDefault(store)
    bundle = handler.generate(request)
    ```
"""

from .enums.enum_ac_verdict import EnumAcVerdict
from .enums.enum_execution_outcome import EnumExecutionOutcome
from .handler_evidence_bundle_default import HandlerEvidenceBundleDefault
from .models.model_ac_verification_record import ModelAcVerificationRecord
from .models.model_bundle_generate_request import ModelBundleGenerateRequest
from .models.model_evidence_bundle import ModelEvidenceBundle
from .node import NodeEvidenceBundleCompute
from .protocol_bundle_store import ProtocolBundleStore
from .store_bundle_in_memory import StoreBundleInMemory

__all__ = [
    # Node
    "NodeEvidenceBundleCompute",
    # Models
    "ModelAcVerificationRecord",
    "ModelBundleGenerateRequest",
    "ModelEvidenceBundle",
    # Enums
    "EnumAcVerdict",
    "EnumExecutionOutcome",
    # Protocol
    "ProtocolBundleStore",
    # Implementations
    "HandlerEvidenceBundleDefault",
    "StoreBundleInMemory",
]
