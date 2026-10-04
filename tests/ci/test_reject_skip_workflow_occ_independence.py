# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20073 - the skip-token reusable scans every PR without waiting on change control.

The reusable ran the central change-control preflight as a nested job and held the
token scan behind ``needs`` on it. A repository that moves its evidence into its own
code (OMN-20068) then could not drop the change-control required context without also
losing the token scan. The scan reads the PR body, title, commits and diff from the
GitHub API, so it needs nothing from the preflight.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "reject-deploy-gate-skip.yml"
)


def _doc() -> dict[str, Any]:
    doc = yaml.safe_load(WORKFLOW.read_text())
    assert isinstance(doc, dict)  # positive control: the file parses to a mapping
    return doc


def _jobs() -> dict[str, dict[str, Any]]:
    jobs = _doc()["jobs"]
    assert "scan-skip-tokens" in jobs  # positive control: the scan job exists
    return jobs


def test_no_job_calls_the_change_control_preflight() -> None:
    called = {
        name: str(job["uses"])
        for name, job in _jobs().items()
        if "uses" in job and "occ-preflight" in str(job["uses"])
    }
    assert called == {}, "the reusable must not run the change-control preflight"


def test_no_job_is_named_after_the_preflight() -> None:
    assert [name for name in _jobs() if "occ-preflight" in name] == []


def test_scan_job_does_not_wait_on_any_job() -> None:
    assert "needs" not in _jobs()["scan-skip-tokens"]


def test_scan_runs_on_pull_request_and_merge_group_and_stays_callable() -> None:
    triggers = _doc().get("on", _doc().get(True))
    assert {"workflow_call", "pull_request", "merge_group"} <= set(triggers)


def test_token_scan_step_is_preserved() -> None:
    steps = _jobs()["scan-skip-tokens"]["steps"]
    scan = [s for s in steps if "Scan all PR surfaces" in str(s.get("name", ""))]
    assert len(scan) == 1
    assert "SKIP_PATTERN='\\[skip-[a-zA-Z]'" in scan[0]["run"]
