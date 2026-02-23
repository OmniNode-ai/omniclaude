# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Models for the NodeGitEffect node.

This package contains Pydantic models for git operations:

- ModelGitRequest: Input model for git operation requests
- ModelGitResult: Output model for git operation results

Model Ownership:
    These models are PRIVATE to omniclaude. If external repos need to
    import them, that is the signal to promote them to omnibase_core.
"""

from .model_git_request import GitOperation, ModelGitRequest
from .model_git_result import GitResultStatus, ModelGitResult

__all__ = [
    "GitOperation",
    "ModelGitRequest",
    "GitResultStatus",
    "ModelGitResult",
]
