# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Transport adapter that routes the Git node's admission_check request to HandlerGitAdmission."""

from __future__ import annotations

import math
import os
from pathlib import Path

from omniclaude.nodes.node_git_effect.container import container_git_admission
from omniclaude.nodes.node_git_effect.models import (
    GitOperation,
    GitResultStatus,
    ModelGitRequest,
    ModelGitResult,
)
from omniclaude.nodes.node_git_effect.models.model_git_admission import (
    ModelGitAdmissionRequest,
    ModelGitAdmissionResult,
)
from omniclaude.nodes.node_git_effect.models.model_git_timeout_policy import (
    ModelGitTimeoutPolicy,
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
        admission = container_git_admission.build_git_admission().handle(
            request.admission
        )
        return ModelGitResult(
            operation=request.operation.value,
            status=GitResultStatus.SUCCESS,
            admission=admission,
            correlation_id=request.correlation_id,
        )

    def dispatch(
        self,
        request: ModelGitAdmissionRequest,
        state_root: Path,
        *,
        runtime_timeout_seconds: float | None = None,
    ) -> ModelGitAdmissionResult:
        """Run admission on the hook host using the contract's in-memory bus.

        Resolve the contract deadline and operator overlay unless a caller
        injects a deadline. RuntimeLocal takes whole seconds, rounded upward.
        """
        from omnibase_core.enums.enum_workflow_result import EnumWorkflowResult
        from omnibase_core.runtime.runtime_local import RuntimeLocal

        if runtime_timeout_seconds is None:
            runtime_timeout_seconds = ModelGitTimeoutPolicy.from_contract(
                env=os.environ
            ).timeout_for(GitOperation.ADMISSION_CHECK)
        if not math.isfinite(runtime_timeout_seconds) or runtime_timeout_seconds <= 0:
            raise ValueError("admission runtime timeout must be finite and positive")
        state_root.mkdir(parents=True, exist_ok=True)
        input_path = state_root / "input.json"
        input_path.write_text(
            ModelGitRequest(
                operation=GitOperation.ADMISSION_CHECK,
                admission=request,
                correlation_id=request.correlation_id,
            ).model_dump_json()
        )
        runtime = RuntimeLocal(
            workflow_path=Path(__file__).resolve().parent.parent / "contract.yaml",
            state_root=state_root,
            input_path=input_path,
            backend_overrides={"event_bus": "inmemory"},
            timeout=math.ceil(runtime_timeout_seconds),
        )
        if runtime.run() is not EnumWorkflowResult.COMPLETED:
            raise RuntimeError(
                runtime.last_error or "git admission runtime did not complete"
            )
        result = runtime.handler_result
        if not isinstance(result, ModelGitResult) or result.admission is None:
            raise RuntimeError("git admission runtime returned no typed verdict")
        return result.admission
