# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20941: omniclaude's Version Pin Compliance job no longer reads onex_change_control.

The ``version-pin-check`` job (context ``Version Pin Compliance``, OMN-4810) checked
out onex_change_control ``standards/`` and ran ``check_version_pins.py`` against a
version matrix whose omnibase-core row is fourteen minor versions stale. It carried
``continue-on-error: true``, so its result could never turn Quality Gate red, yet the
manifest listed it REQUIRED. Pin integrity is enforced by the required
``pypi-pin-resolvability`` context (OMN-19655), which judges the pull request's own
wheel with the release step's own script.

The ordering is the invariant: a required check is never removed with nothing
replacing it. These tests hold the replacement REQUIRED and live before the retired
context stops being REQUIRED, and prove that nothing in ``ci.yml`` still reads the
retired job.

omnibase_core retired the same job in omnibase_core#1947 (OMN-20921).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
GITHUB_DIR = REPO_ROOT / ".github"
CI_YML = GITHUB_DIR / "workflows" / "ci.yml"
PIN_GATE_YML = GITHUB_DIR / "workflows" / "pin-resolvability-gate.yml"
REQUIRED_CHECKS = GITHUB_DIR / "required-checks.yaml"

_JOB_ID = "version-pin-check"
_JOB_NAME = "Version Pin Compliance"
_SCRIPT = "check_version_pins"
_REPLACEMENT = "pypi-pin-resolvability"
_OCC_REPOSITORY = "OmniNode-ai/onex_change_control"
_NEEDS_READ = re.compile(r"needs\.([A-Za-z0-9_-]+)\.")


def _ci_jobs() -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    jobs = data["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _manifest_gates() -> list[dict[str, Any]]:
    manifest = yaml.safe_load(REQUIRED_CHECKS.read_text(encoding="utf-8"))
    gates = manifest["gates"]
    assert isinstance(gates, list)
    return gates


def _needs_of(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def _dangling_needs(jobs: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    """Return ``(job, missing_need)`` for every ``needs:`` entry that names no job."""
    return [
        (job_id, need)
        for job_id, job in jobs.items()
        for need in _needs_of(job)
        if need not in jobs
    ]


def _unlisted_result_reads(jobs: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    """Return ``(job, read)`` for every ``needs.<x>.`` expression where x is not a need."""
    return [
        (job_id, read)
        for job_id, job in jobs.items()
        for read in sorted(set(_NEEDS_READ.findall(yaml.safe_dump(job))))
        if read not in _needs_of(job)
    ]


def test_manifest_requires_replacement_and_no_required_version_pin_compliance() -> None:
    required = {g["name"] for g in _manifest_gates() if g["mode"] == "REQUIRED"}
    assert _REPLACEMENT in required
    assert _JOB_NAME not in required


def test_replacement_gate_reports_on_every_pull_request() -> None:
    workflow = yaml.safe_load(PIN_GATE_YML.read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    assert triggers["pull_request"] in (None, {}), (
        "a paths filter leaves the context unminted"
    )
    (job,) = workflow["jobs"].values()
    assert job["name"] == _REPLACEMENT
    assert "if" not in job, "a job-level if: leaves the context unminted"


def test_retired_manifest_row_names_ticket_core_pr_and_replacement() -> None:
    (row,) = [g for g in _manifest_gates() if g["name"] == _JOB_NAME]
    assert row["mode"] == "RETIRED"
    for citation in ("OMN-20941", "omnibase_core#1947", _REPLACEMENT):
        assert citation in row["rationale"]


def test_ci_workflow_runs_no_version_pin_script() -> None:
    assert _SCRIPT not in CI_YML.read_text(encoding="utf-8")


def test_ci_workflow_checks_out_no_onex_change_control_standards() -> None:
    offenders = [
        job_id
        for job_id, job in _ci_jobs().items()
        for step in job.get("steps", [])
        if step.get("with", {}).get("repository") == _OCC_REPOSITORY
        and "standards/" in str(step["with"].get("sparse-checkout", ""))
    ]
    assert offenders == []


def test_version_pin_check_job_is_gone() -> None:
    jobs = _ci_jobs()
    assert _JOB_ID not in jobs
    assert _JOB_NAME not in {job.get("name") for job in jobs.values()}


def test_no_job_needs_the_retired_job() -> None:
    assert [j for j, job in _ci_jobs().items() if _JOB_ID in _needs_of(job)] == []
    assert _JOB_ID not in CI_YML.read_text(encoding="utf-8")


def test_every_ci_needs_entry_resolves_to_a_job() -> None:
    assert _dangling_needs(_ci_jobs()) == []


def test_every_needs_result_read_is_a_listed_need() -> None:
    assert _unlisted_result_reads(_ci_jobs()) == []


def test_dangling_needs_checker_flags_a_broken_needs_entry() -> None:
    """Positive control: the needs checker above is not vacuous."""
    jobs = _ci_jobs()
    victim = next(job_id for job_id, job in jobs.items() if "needs" in job)
    broken = {**jobs, victim: {**jobs[victim], "needs": ["no-such-job-omn20941"]}}
    assert _dangling_needs(broken) == [(victim, "no-such-job-omn20941")]


def test_unlisted_result_read_checker_flags_a_planted_read() -> None:
    """Positive control: a gate reading a job it does not need is reported."""
    jobs = _ci_jobs()
    gate = jobs["quality-gate"]
    planted = {
        **jobs,
        "quality-gate": {
            **gate,
            "needs": [n for n in _needs_of(gate) if n != "arch-invariants"],
        },
    }
    assert ("quality-gate", "arch-invariants") in _unlisted_result_reads(planted)
