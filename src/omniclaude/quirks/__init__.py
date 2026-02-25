# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Quirks Detector — public package surface.

Re-exports all public types so callers can import directly from
``omniclaude.quirks`` without knowing the internal module layout::

    from omniclaude.quirks import QuirkType, QuirkStage, QuirkSignal, QuirkFinding

Related:
    - OMN-2533: Foundation ticket — models + DB schema
    - OMN-2586: OmniMemory wiring + QuirkDashboard read API
    - OMN-2360: Quirks Detector epic
"""

from omniclaude.quirks.classifier import NodeQuirkClassifierCompute
from omniclaude.quirks.controller import NodeValidatorRolloutOrchestratorOrchestrator
from omniclaude.quirks.dashboard import NodeQuirkDashboardQueryEffect
from omniclaude.quirks.enums import QuirkStage, QuirkType
from omniclaude.quirks.extractor import NodeQuirkSignalExtractorEffect
from omniclaude.quirks.memory_bridge import NodeQuirkMemoryBridgeEffect
from omniclaude.quirks.models import QuirkFinding, QuirkSignal

__all__ = [
    "NodeQuirkClassifierCompute",
    "NodeQuirkDashboardQueryEffect",
    "NodeQuirkMemoryBridgeEffect",
    "NodeQuirkSignalExtractorEffect",
    "NodeValidatorRolloutOrchestratorOrchestrator",
    "QuirkFinding",
    "QuirkSignal",
    "QuirkStage",
    "QuirkType",
]
