# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20074 S6: omniclaude has no OCC caller left.

Pull-request admission here requires repo-owned evidence and nothing from
onex_change_control: no event-triggered workflow calls an OCC reusable, no job
waits on ``occ-preflight``, no CI job resolves a PR's OCC evidence companion,
the repo-evidence caller neither shadows nor compares with OCC, and neither
CI Summary nor the required-checks manifest expects an OCC context.

omniclaude also HOSTS reusables other repositories still call
(call-occ-autobind-reusable.yml, call-occ-companion-effect-reusable.yml,
deploy-gate-reusable.yml, reject-deploy-gate-skip.yml). A workflow whose only
trigger is ``workflow_call`` is such a hosted definition, not a caller here, so
it is out of scope for these assertions. The assertions read the parsed
workflow files, so a comment naming a retired workflow cannot trip them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.ci import ci_summary_gate as gate

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
REQUIRED_CHECKS = REPO_ROOT / ".github" / "required-checks.yaml"
CALLER_PATH = WORKFLOWS / "call-repo-evidence-gate.yml"

# A reusable whose file name starts with ``occ-`` or ``call-occ-`` is an OCC
# preflight, autobind or companion-effect path.
_OCC_REUSABLE = re.compile(r"^(?:call-)?occ-[a-z0-9-]+\.ya?ml$")
_PREFLIGHT = re.compile(r"occ-preflight")

_OCC_CONTEXTS = frozenset(
    {
        "occ-preflight / eligibility",
        "call-reject-skip-token / occ-preflight / eligibility",
        "verify / verify",
        "OCC Companion Merged Gate (OMN-15214)",
        "DoD Evidence Check",
        "Contract Compliance Check",
        "occ-companion-effect / Publish occ-companion-effect command",
        "occ-autobind / outcome",
        "occ-autobind / mint status",
        "occ-companion-effect / mint status",
    }
)

_RETIRED_CALLERS = (
    "call-occ-preflight.yml",
    "call-occ-autobind.yml",
    "call-occ-companion-effect.yml",
    "occ-companion-merge-heal.yml",
    "call-receipt-gate.yml",
)


def _triggers(data: dict[str, Any]) -> set[str]:
    # PyYAML 1.1 resolves the bare `on:` key to the boolean True.
    on = data.get("on", data.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    return set(on or {})


def _caller_workflows() -> dict[str, dict[str, Any]]:
    parsed: dict[str, dict[str, Any]] = {}
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), path.name
        if _triggers(data) == {"workflow_call"}:
            continue
        parsed[path.name] = data
    return parsed


def _jobs() -> list[tuple[str, str, dict[str, Any]]]:
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for name, data in _caller_workflows().items():
        for job_id, job in (data.get("jobs") or {}).items():
            assert isinstance(job, dict), f"{name}:{job_id}"
            rows.append((name, job_id, job))
    return rows


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs") or []
    return [needs] if isinstance(needs, str) else list(needs)


def test_no_occ_callers_workflow_calls_an_occ_reusable() -> None:
    offenders = []
    for name, job_id, job in _jobs():
        uses = job.get("uses")
        if not isinstance(uses, str):
            continue
        reusable = uses.split("@", 1)[0].rsplit("/", 1)[-1]
        if _OCC_REUSABLE.match(reusable):
            offenders.append(f"{name}:{job_id} -> {reusable}")
    assert not offenders, offenders


def test_no_occ_callers_receipt_gate_runs_only_in_caller_mode() -> None:
    offenders = []
    for name, job_id, job in _jobs():
        uses = job.get("uses")
        if not isinstance(uses, str) or not uses.split("@", 1)[0].endswith(
            "/receipt-gate.yml"
        ):
            continue
        if (job.get("with") or {}).get("evidence-source") != "caller":
            offenders.append(f"{name}:{job_id}")
    assert not offenders, offenders


def test_no_occ_callers_job_waits_on_occ_preflight() -> None:
    offenders = []
    for name, job_id, job in _jobs():
        if _PREFLIGHT.search(job_id):
            offenders.append(f"{name}:{job_id} is a preflight job")
        if "occ-preflight" in _needs(job):
            offenders.append(f"{name}:{job_id} needs occ-preflight")
        if _PREFLIGHT.search(str(job.get("if", ""))):
            offenders.append(f"{name}:{job_id} conditions on occ-preflight")
        for step in job.get("steps") or []:
            if "needs.occ-preflight" in str(step.get("run", "")):
                offenders.append(f"{name}:{job_id} step reads occ-preflight")
    assert not offenders, offenders


def test_no_occ_callers_workflow_runs_the_companion_gate_or_heals() -> None:
    present = [name for name in _RETIRED_CALLERS if (WORKFLOWS / name).exists()]
    assert not present, present
    ci_jobs = _caller_workflows()["ci.yml"]["jobs"]
    assert "occ-companion-merged" not in ci_jobs
    assert not [
        job_id
        for job_id, job in ci_jobs.items()
        if "OCC" in str(job.get("name", "")) and "Companion" in str(job.get("name", ""))
    ]


def test_no_occ_callers_ci_resolves_no_evidence_source() -> None:
    """No ci.yml job resolves a PR's companion or checks out OCC evidence data."""
    ci_jobs = _caller_workflows()["ci.yml"]["jobs"]
    assert "contract-compliance" not in ci_jobs
    assert "dod-evidence-check" not in ci_jobs
    offenders = []
    for job_id, job in ci_jobs.items():
        for step in job.get("steps") or []:
            run = str(step.get("run", ""))
            if "Evidence-Source" in run or "materialize-dod-evidence-from-occ" in run:
                offenders.append(f"{job_id}: {step.get('name')}")
            if "run_contract_compliance_with_evidence" in run:
                offenders.append(f"{job_id}: {step.get('name')}")
    assert not offenders, offenders


def test_no_occ_callers_repo_evidence_caller_enforces_without_occ() -> None:
    job = yaml.safe_load(CALLER_PATH.read_text(encoding="utf-8"))["jobs"][
        "repo-evidence"
    ]
    assert job["with"].get("shadow") == "false"
    assert job["with"].get("compare-with-occ") == "false"


def test_no_occ_callers_ci_summary_expects_no_occ_context() -> None:
    expected = set(gate.EXPECTED_EXTERNAL_CONTEXTS)
    strict = set(gate.STRICT_SUCCESS_JOBS) | set(gate.GATE_JOBS)
    assert not _OCC_CONTEXTS & expected
    assert not _OCC_CONTEXTS & strict
    assert not _OCC_CONTEXTS & set(gate.SOFT_ALLOWLIST)
    assert not _OCC_CONTEXTS & set(gate.EXTERNAL_SWEEP_EXCLUSIONS)
    assert not _OCC_CONTEXTS & set(gate.ALL_MUST_SUCCEED_EXTERNAL_NAMES)
    assert "repo-evidence / dod-verify" in expected


def test_no_occ_callers_required_checks_manifest_names_no_occ_context() -> None:
    manifest = yaml.safe_load(REQUIRED_CHECKS.read_text(encoding="utf-8"))
    names = {row["name"] for row in manifest["gates"] if isinstance(row, dict)}
    assert not _OCC_CONTEXTS & names
