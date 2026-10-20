# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The coderabbit_triage skill is removed with its backing node (OMN-17427 AC50).

omnimarket#4070 deleted ``node_coderabbit_triage``. A skill that still declares
it fails the ``validate-skill-backing-node`` pre-commit hook as soon as the
omnimarket pin moves past that merge, so the skill, its hook handler and its
manifest and compat registrations go with it.

The orchestrator node ``node_skill_coderabbit_triage_orchestrator`` and its
``pyproject.toml`` entry point stay until a follow-up, tracked by
``_ORPHAN_REMOVAL_PENDING`` in ``tests/unit/nodes/test_skill_node_coverage.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

_REMOVED_PATHS = (
    "plugins/onex/skills/coderabbit_triage",
    "src/omniclaude/hooks/handlers/coderabbit_triage.py",
)

_REGISTRATION_FILES = (
    "plugins/distribution_manifest.yaml",
    "plugins/onex/plugin-compat.yaml",
    ".onex_ratchets/canonical_file_shape_baseline.txt",
)


@pytest.mark.unit
@pytest.mark.parametrize("relpath", _REMOVED_PATHS)
def test_removed_path_is_absent(relpath: str) -> None:
    assert not (_REPO_ROOT / relpath).exists(), relpath


@pytest.mark.unit
@pytest.mark.parametrize("relpath", _REGISTRATION_FILES)
def test_registration_does_not_name_coderabbit_triage(relpath: str) -> None:
    text = (_REPO_ROOT / relpath).read_text(encoding="utf-8")
    assert "coderabbit_triage" not in text
    assert "coderabbit-triage" not in text
