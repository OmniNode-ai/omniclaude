# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The ratchet uses the landed-proof verifier without dropping its proof inputs."""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit


def test_ratchet_uses_landed_proof_validator_with_full_proof_checks() -> None:
    """The pre-fix release rejects even unchanged, already landed receipts."""
    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
    job = yaml.safe_load(workflow.read_text())["jobs"]["canon-shape-ratchet"]
    checkout = next(
        step
        for step in job["steps"]
        if step.get("with", {}).get("repository") == "OmniNode-ai/omnibase_core"
    )
    assert (
        job["env"]["VALIDATOR_COMMIT_ID"] == "9ec8cd90765fe9d5af66c84532f389397e9b14f2"
    )
    assert checkout["with"]["ref"] == "${{ steps.core_pin.outputs.rev }}"
    resolver = next(step for step in job["steps"] if step.get("id") == "core_pin")
    assert 'echo "rev=$VALIDATOR_COMMIT_ID" >> "$GITHUB_OUTPUT"' in resolver["run"]
    assert any(
        'test "$(git -C .ci/omnibase_core rev-parse HEAD)" = "$VALIDATOR_COMMIT_ID"'
        in step.get("run", "")
        for step in job["steps"]
    )
    command = next(
        step["run"]
        for step in job["steps"]
        if "canonical_handler_shape.py" in step.get("run", "")
    )
    assert "python .ci/omnibase_core/scripts/ci/canonical_handler_shape.py" in command
    assert "--package omniclaude --src-root src" in command
    assert "--baseline scripts/ci/canonical_handler_shape_baseline.py" in command
    assert "--receipts-dir scripts/ci/adequacy_receipts" in command
    assert "--full" in command
