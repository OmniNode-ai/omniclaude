# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""omniclaude's test jobs must not run on a floating hosted image.

``ubuntu-latest`` became Ubuntu 26.04 on 2026-11-06. On it,
``tests/scripts/test_gh_user_shim.py::test_lock_two_stale_renders_refresh_once``
failed on some runs of this job, and the job's conclusion feeds the required
``reason-graph`` context. The job names the image it runs on.

#3199 pinned ``tests-shadow`` and stopped there, so the REQUIRED
``Tests (Split N/5)`` job in ``ci.yml`` kept resolving ``ubuntu-latest`` through
the runner selector and kept failing the same test: omniclaude#3211 job
128629007778 reports ``labels: ["ubuntu-latest"]`` and
``20 pr-list calls in 2 group(s)``, and omniclaude#3201 job 128627344288 fails
the same way carrying the lock fix itself. Measured the same day: both
``OMNI_PUBLIC_PR_RUNS_ON_JSON`` and ``OMNI_TRUSTED_CI_RUNS_ON_JSON`` are set to
``["ubuntu-latest"]`` at the organization AND at this repository, so the
selector's ``|| '["ubuntu-latest"]'`` literals are dead code and no edit to them
could move the image. Pinning the job is the only repo-local fix, which is what
``test_the_required_test_job_runs_on_the_pinned_image`` holds.

A pin is a stopgap for a floating image. The durable fix is a lock that does not
need ``mkdir`` to be exclusive (OMN-19998), and these assertions are the thing to
delete when it lands.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SHADOW_WORKFLOW = WORKFLOWS / "product-readiness-shadow.yml"
CI_WORKFLOW = WORKFLOWS / "ci.yml"
PINNED_IMAGE = "ubuntu-24.04"

#: The job whose name renders as ``Tests (Split N/5)`` -- the required one.
REQUIRED_TEST_JOB = "test"


def floats(runs_on: object) -> bool:
    """True when a runs-on value is not the pinned image."""
    return runs_on != PINNED_IMAGE


def test_the_probe_names_the_image_dev_used() -> None:
    """Control: the value the job carried on dev is named by the probe."""
    assert floats("ubuntu-latest") is True


def test_the_probe_accepts_the_pinned_image() -> None:
    assert floats(PINNED_IMAGE) is False


def test_the_probe_names_a_selector_expression_as_floating() -> None:
    """Control: the expression ``ci.yml``'s test job carried is not a pin.

    It is the shape the probe must refuse, and the reason it must: a value that
    resolves at run time through a variable this repository sets to
    ``["ubuntu-latest"]`` is a floating image however it is spelled.
    """
    selector = (
        "${{ (github.event_name == 'pull_request') "
        "&& fromJSON(vars.OMNI_PUBLIC_PR_RUNS_ON_JSON || '[\"ubuntu-latest\"]') "
        "|| fromJSON(vars.OMNI_TRUSTED_CI_RUNS_ON_JSON || '[\"ubuntu-latest\"]') }}"
    )
    assert floats(selector) is True


def _jobs(path: Path) -> dict[str, Any]:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def test_tests_shadow_runs_on_the_pinned_image() -> None:
    assert floats(_jobs(SHADOW_WORKFLOW)["tests-shadow"]["runs-on"]) is False


def test_the_required_test_job_runs_on_the_pinned_image() -> None:
    """The job #3199 left behind: ``Tests (Split N/5)``, which gates every PR."""
    job = _jobs(CI_WORKFLOW)[REQUIRED_TEST_JOB]
    assert floats(job["runs-on"]) is False, job["runs-on"]


def test_the_required_test_job_is_the_one_that_renders_the_split_name() -> None:
    """Pinning the wrong job would pass the test above and fix nothing."""
    assert "Tests (Split " in _jobs(CI_WORKFLOW)[REQUIRED_TEST_JOB]["name"]
