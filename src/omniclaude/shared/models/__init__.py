# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Shared skill node models — request, result, contract, completion event, and PR events."""

from .model_merge_gate_result import ModelGateCheckResult, ModelMergeGateResult
from .model_pr_changeset import (
    CHANGESET_UUID_NAMESPACE,
    ModelContractChange,
    ModelPRChangeSet,
    build_changeset_id,
)
from .model_pr_outcome import ModelPROutcome
from .model_skill_completion_event import ModelSkillCompletionEvent
from .model_skill_node_contract import ModelSkillNodeContract, ModelSkillNodeExecution
from .model_skill_request import ModelSkillRequest
from .model_skill_result import ModelSkillResult, SkillResult, SkillResultStatus

__all__ = [
    "CHANGESET_UUID_NAMESPACE",
    "ModelContractChange",
    "ModelGateCheckResult",
    "ModelMergeGateResult",
    "ModelPRChangeSet",
    "ModelPROutcome",
    "ModelSkillCompletionEvent",
    "ModelSkillNodeContract",
    "ModelSkillNodeExecution",
    "ModelSkillRequest",
    "ModelSkillResult",
    "SkillResult",
    "SkillResultStatus",
    "build_changeset_id",
]
