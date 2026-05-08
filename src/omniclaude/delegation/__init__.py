# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Delegation routing package for omniclaude."""

from omniclaude.delegation.bus_bootstrap import (
    ProtocolProjectionDatabaseSync,
    bootstrap_delegation_bus,
)
from omniclaude.delegation.daemon_fallback import is_daemon_available
from omniclaude.delegation.emitter import emit_task_delegated
from omniclaude.delegation.evidence_bundle import (
    EnumBundleArtifact,
    EvidenceBundleWriter,
    ModelBifrostResponse,
    ModelBundleReceipt,
    ModelCostEvent,
    ModelQualityGateArtifact,
    ModelRunManifest,
    hash_prompt,
    new_bundle_id,
)
from omniclaude.delegation.inprocess_runner import (
    DelegationRunnerError,
    EnumDelegationTaskType,
    InProcessDelegationRunner,
)
from omniclaude.delegation.runner import (
    DelegationRunner,
    ModelBifrostRunnerResult,
    ModelDelegationAuditEvent,
)
from omniclaude.delegation.savings import ModelSavingsEstimate, SavingsCalculator
from omniclaude.delegation.sensitivity_gate import (
    EnumSensitivityPolicy,
    ModelSensitivityResult,
    SensitivityGate,
)
from omniclaude.delegation.transport import (
    DelegationTransportSelector,
    EnumDelegationTransport,
    get_delegation_transport,
)

__all__: list[str] = [
    "DelegationRunner",
    "DelegationTransportSelector",
    "DelegationRunnerError",
    "ProtocolProjectionDatabaseSync",
    "bootstrap_delegation_bus",
    "emit_task_delegated",
    "EnumBundleArtifact",
    "EnumDelegationTransport",
    "EnumDelegationTaskType",
    "EnumSensitivityPolicy",
    "EvidenceBundleWriter",
    "InProcessDelegationRunner",
    "ModelBifrostResponse",
    "ModelBifrostRunnerResult",
    "ModelBundleReceipt",
    "ModelCostEvent",
    "ModelDelegationAuditEvent",
    "ModelQualityGateArtifact",
    "ModelRunManifest",
    "ModelSavingsEstimate",
    "ModelSensitivityResult",
    "SavingsCalculator",
    "SensitivityGate",
    "get_delegation_transport",
    "hash_prompt",
    "is_daemon_available",
    "new_bundle_id",
]
