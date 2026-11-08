# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The tests+coverage (shadow) job must not run on a floating hosted image.

``ubuntu-latest`` became Ubuntu 26.04 on 2026-11-06. On it,
``tests/scripts/test_gh_user_shim.py::test_lock_two_stale_renders_refresh_once``
failed on some runs of this job, and the job's conclusion feeds the required
``reason-graph`` context. The job names the image it runs on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SHADOW_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "product-readiness-shadow.yml"
PINNED_IMAGE = "ubuntu-24.04"


def floats(runs_on: object) -> bool:
    """True when a runs-on value is not the pinned image."""
    return runs_on != PINNED_IMAGE


def test_the_probe_names_the_image_dev_used() -> None:
    """Control: the value the job carried on dev is named by the probe."""
    assert floats("ubuntu-latest") is True


def test_the_probe_accepts_the_pinned_image() -> None:
    assert floats(PINNED_IMAGE) is False


def test_tests_shadow_runs_on_the_pinned_image() -> None:
    workflow = yaml.safe_load(SHADOW_WORKFLOW.read_text(encoding="utf-8"))
    assert floats(workflow["jobs"]["tests-shadow"]["runs-on"]) is False
