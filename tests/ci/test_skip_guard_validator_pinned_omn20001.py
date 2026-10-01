# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20001 - the skip-guard reusable reads its validator at its own pinned sha."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "required-check-skip-guard-reusable.yml"
)


def _steps() -> list[dict[str, Any]]:
    doc = yaml.safe_load(WORKFLOW.read_text())
    return [s for job in doc["jobs"].values() for s in job["steps"]]


def test_validator_checkout_ref_is_the_resolved_workflow_sha() -> None:
    fetch = [
        s
        for s in _steps()
        if isinstance(s.get("with"), dict)
        and s["with"].get("repository") == "OmniNode-ai/omniclaude"
    ]
    assert len(fetch) == 1  # positive control: the fetch step exists
    ref = str(fetch[0]["with"]["ref"])
    assert ref == "${{ steps.pin.outputs.sha }}", (
        "a live branch ref moves callers' verdicts"
    )


def test_pin_step_reads_job_workflow_sha() -> None:
    pin = [s for s in _steps() if s.get("id") == "pin"]
    assert len(pin) == 1
    assert "job.workflow_sha" in str(pin[0]["env"])
