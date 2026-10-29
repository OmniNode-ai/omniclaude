# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Onboarding's model-file operations must not bootstrap the orchestrator."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[2]


def test_model_config_handler_does_not_import_orchestrator() -> None:
    # Each Bash model operation starts a fresh interpreter. Check the import
    # boundary there, rather than relying on timing or pytest's loaded modules.
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; "
            "from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.handler_onboarding_model_config import HandlerOnboardingModelConfig; "
            "assert 'omnibase_core.nodes.node_orchestrator' not in sys.modules",
        ],
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr


def test_package_still_exports_the_orchestrator_node() -> None:
    from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator import (
        NodeSkillOmninodeDevSetupOrchestrator,
    )
    from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.node import (
        NodeSkillOmninodeDevSetupOrchestrator as Node,
    )

    assert NodeSkillOmninodeDevSetupOrchestrator is Node
