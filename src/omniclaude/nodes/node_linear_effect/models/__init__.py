# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Models for the NodeLinearEffect node.

This package contains Pydantic models for Linear ticketing operations:

- ModelLinearRequest: Input model for Linear operation requests
- ModelLinearResult: Output model for Linear operation results
- ModelLocalPrStateRequest / ModelLocalPrStateResult: a PR's merge state read locally
- ModelCloseoutInstructionAuditRequest / ModelCloseoutInstructionAuditResult: the retired closeout instruction audit

Model Ownership:
    These models are PRIVATE to omniclaude.
"""

from .model_closeout_instruction_audit import (
    ModelCloseoutInstructionAuditRequest,
    ModelCloseoutInstructionAuditResult,
)
from .model_linear_endpoint import ModelLinearEndpoint
from .model_linear_request import LinearOperation, ModelLinearRequest
from .model_linear_result import LinearResultStatus, ModelLinearResult
from .model_local_pr_state import ModelLocalPrStateRequest, ModelLocalPrStateResult

__all__ = [
    "LinearOperation",
    "ModelLinearEndpoint",
    "ModelLinearRequest",
    "LinearResultStatus",
    "ModelLinearResult",
    "ModelLocalPrStateRequest",
    "ModelLocalPrStateResult",
    "ModelCloseoutInstructionAuditRequest",
    "ModelCloseoutInstructionAuditResult",
]
