# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Each hand-built handler of the OMN-21779 slice is built at a binding site."""

from __future__ import annotations

import pytest

from omniclaude.handlers.container import (
    container_quirks,
    container_runtime,
)
from omniclaude.handlers.handler_contract_endpoint_resolver import (
    HandlerContractEndpointResolver,
)
from omniclaude.nodes.node_git_effect.container import container_git_admission
from omniclaude.nodes.node_git_effect.handlers.handler_git_admission import (
    HandlerGitAdmission,
)
from omniclaude.nodes.node_pr_ownership_guard_effect.container import (
    container_pr_ownership,
)
from omniclaude.nodes.node_pr_ownership_guard_effect.handlers.handler_pr_ownership import (
    HandlerPrOwnership,
)
from omniclaude.nodes.node_validate_skills_compute.container import (
    container_validate_skills,
)
from omniclaude.nodes.node_validate_skills_compute.handlers import (
    HandlerSkillContracts,
    HandlerSkillHygiene,
)
from omniclaude.quirks.controller import NodeValidatorRolloutOrchestratorOrchestrator

pytestmark = pytest.mark.unit


def test_git_admission_binding_site_builds_the_handler() -> None:
    assert isinstance(
        container_git_admission.build_git_admission(), HandlerGitAdmission
    )


def test_pr_ownership_binding_site_passes_the_caller_choice() -> None:
    handler = container_pr_ownership.build_pr_ownership(defer_claims=True)
    assert isinstance(handler, HandlerPrOwnership)
    other = container_pr_ownership.build_pr_ownership(defer_claims=False)
    assert other is not handler


def test_validate_skills_binding_site_builds_both_handlers() -> None:
    assert isinstance(
        container_validate_skills.build_skill_hygiene(), HandlerSkillHygiene
    )
    assert isinstance(
        container_validate_skills.build_skill_contracts(), HandlerSkillContracts
    )


def test_quirks_binding_site_builds_the_orchestrator() -> None:
    controller = container_quirks.build_rollout_orchestrator(db_session_factory=None)
    assert isinstance(controller, NodeValidatorRolloutOrchestratorOrchestrator)


def test_runtime_binding_site_builds_resolver_and_comment_sweep() -> None:
    assert isinstance(
        container_runtime.build_contract_endpoint_resolver(),
        HandlerContractEndpointResolver,
    )
    handler = container_runtime.build_comment_sweep_skill(
        task_dispatcher=None, event_emitter=None
    )
    assert type(handler).__name__ == "HandlerCommentSweepSkill"
