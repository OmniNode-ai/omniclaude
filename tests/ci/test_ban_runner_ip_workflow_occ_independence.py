# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20074 - the runner-IP reusable scans without the change-control preflight.

The reusable nested the central change-control preflight as a job beside the scan.
Every caller of the reusable therefore carried the extra required context
``ban-hardcoded-runner-ip / occ-preflight / eligibility`` and a checkout of the
change-control repository, although the scan reads only the caller's own
``.github/workflows/**`` and ``tests/**``. Same shape as OMN-20073 for the skip-token
reusable. The caller context ``ban-hardcoded-runner-ip / ban-hardcoded-runner-ip``
is the scan job and must not change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "ban-hardcoded-runner-ip.yml"
)

SCAN_JOB = "ban-hardcoded-runner-ip"


def _doc() -> dict[str, Any]:
    doc = yaml.safe_load(WORKFLOW.read_text())
    assert isinstance(doc, dict)  # positive control: the file parses to a mapping
    return doc


def _jobs() -> dict[str, dict[str, Any]]:
    jobs = _doc()["jobs"]
    assert SCAN_JOB in jobs  # positive control: the scan job exists
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


def test_no_step_references_the_change_control_repository() -> None:
    steps = [step for job in _jobs().values() for step in job.get("steps", [])]
    assert steps  # positive control: the scan job has steps to inspect
    assert [s for s in steps if "onex_change_control" in yaml.safe_dump(s)] == []


def test_scan_job_does_not_wait_on_any_job() -> None:
    scan = _jobs()[SCAN_JOB]
    assert "needs" not in scan
    assert "if" not in scan, "the scan must run unconditionally"


def test_scan_job_keeps_its_name() -> None:
    assert _jobs()[SCAN_JOB]["name"] == SCAN_JOB


def test_scan_runs_on_pull_request_and_stays_callable() -> None:
    triggers = _doc().get("on", _doc().get(True))
    assert {"workflow_call", "pull_request"} <= set(triggers)


def test_both_scan_steps_are_preserved() -> None:
    names = [str(s.get("name", "")) for s in _jobs()[SCAN_JOB]["steps"]]
    assert any("Reject hardcoded runner IP literals" in n for n in names)
    assert any("Reject machine pins" in n for n in names)
