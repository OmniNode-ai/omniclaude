# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Transport adapter that routes the Git node's admission_check request to HandlerGitAdmission."""

from omniclaude.nodes.node_git_effect.handlers.handler_git_admission import (
    HandlerGitAdmission,
)
from omniclaude.nodes.node_git_effect.models import (
    GitOperation,
    GitResultStatus,
    ModelGitRequest,
    ModelGitResult,
)


class HandlerGitAdmissionTransport:
    """Route the existing Git node request to its typed admission handler."""

    def handle(self, request: ModelGitRequest) -> ModelGitResult:
        if (
            request.operation is not GitOperation.ADMISSION_CHECK
            or request.admission is None
        ):
            raise ValueError(
                "git admission requires the admission_check operation and payload"
            )
        admission = HandlerGitAdmission().handle(request.admission)
        return ModelGitResult(
            operation=request.operation.value,
            status=GitResultStatus.SUCCESS,
            admission=admission,
            correlation_id=request.correlation_id,
        )
