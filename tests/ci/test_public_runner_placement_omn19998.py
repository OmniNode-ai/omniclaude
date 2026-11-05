# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Public-repository runner placement in omniclaude (OMN-19998).

RULING 2026-10-16T07:07:09Z: "Ci runners should be for private repos only."
omniclaude is public, so:

* no routing-seam fallback in a workflow names the self-hosted fleet, except
  the lab carve-outs (the hostile reviewer calls lab models; the dev-head red
  alert writes to the dev-lane CI bus), which stay until they move off GitHub
  Actions;
* a reusable workflow (``workflow_call``) falls back to the fleet only for a
  private caller, read from ``github.event.repository.private``, so a private
  repository calling it keeps its lab runner and a public one gets a hosted one;
* omnibase_core's check-public-runner-placement runs as a CI job that CI
  Summary registers and as a pre-commit hook, at the same core release.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.ci.ci_summary_gate import GATE_JOBS, STRICT_SUCCESS_JOBS

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CI_WORKFLOW = WORKFLOWS / "ci.yml"
PRECOMMIT = REPO_ROOT / ".pre-commit-config.yaml"

FLEET_FALLBACK = """'["self-hosted","omnibase-ci"]'"""
LAB_CARVE_OUTS = (
    "OMNI_HOSTILE_REVIEW_RUNS_ON_JSON",
    "OMNI_LAB_BUS_RUNS_ON_JSON",
)
PRIVATE_CALLER = "github.event.repository.private &&"
JOB_NAME = "Public Runner Placement (OMN-19998)"
HOOK_ID = "check-public-runner-placement"
CORE_RELEASE = "0.47.46"


def _load(path: Path) -> dict[object, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def fleet_fallbacks(text: str) -> list[str]:
    """Code lines that fall back to the self-hosted fleet for a public caller."""
    reusable = "workflow_call:" in text
    return [
        line.strip()
        for line in text.splitlines()
        if FLEET_FALLBACK in line
        and not line.lstrip().startswith("#")
        and not any(knob in line for knob in LAB_CARVE_OUTS)
        and not (reusable and PRIVATE_CALLER in line)
    ]


def test_fleet_fallback_detector_positive_control() -> None:
    planted = (
        "    runs-on: ${{ fromJSON(vars.OMNI_TRUSTED_CI_RUNS_ON_JSON || "
        """'["self-hosted","omnibase-ci"]') }}\n"""
    )
    carve_out = (
        "        || fromJSON(vars.OMNI_HOSTILE_REVIEW_RUNS_ON_JSON || "
        """'["self-hosted","omnibase-ci"]')\n"""
    )
    private_caller = (
        "        || fromJSON(vars.OMNI_TRUSTED_CI_RUNS_ON_JSON || "
        """(github.event.repository.private && '["self-hosted","omnibase-ci"]' """
        """|| '["ubuntu-latest"]'))\n"""
    )
    hosted = (
        "    runs-on: ${{ fromJSON(vars.OMNI_TRUSTED_CI_RUNS_ON_JSON || "
        """'["ubuntu-latest"]') }}\n"""
    )
    assert fleet_fallbacks(planted) == [planted.strip()]
    assert fleet_fallbacks(carve_out) == []
    assert fleet_fallbacks(hosted) == []
    # The private-caller form is accepted only in a reusable workflow; in a
    # workflow only omniclaude runs, the caller is always public.
    assert fleet_fallbacks("on:\n  workflow_call:\n" + private_caller) == []
    assert fleet_fallbacks(private_caller) == [private_caller.strip()]


def test_no_workflow_falls_back_to_the_self_hosted_fleet() -> None:
    offenders = {
        path.name: found
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
        if (found := fleet_fallbacks(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}, (
        "A public repository's routing fallback must be GitHub-hosted "
        "(RULING 2026-10-16T07:07:09Z): " + repr(offenders)
    )


def _ci_job() -> dict[str, object]:
    jobs = _load(CI_WORKFLOW)["jobs"]
    assert isinstance(jobs, dict)
    job = jobs["public-runner-placement"]
    assert isinstance(job, dict)
    return job


def _hooks() -> list[tuple[str, dict[str, object]]]:
    repos = _load(PRECOMMIT)["repos"]
    assert isinstance(repos, list)
    return [
        (str(repo["rev"]), hook)
        for repo in repos
        if isinstance(repo, dict)
        for hook in repo.get("hooks", [])
        if isinstance(hook, dict) and hook.get("id") == HOOK_ID
    ]


def test_ci_job_runs_the_core_check_unconditionally_on_a_hosted_runner() -> None:
    job = _ci_job()
    assert job["name"] == JOB_NAME
    assert job["runs-on"] == "ubuntu-latest"
    assert "needs" not in job
    assert "if" not in job
    steps = job["steps"]
    assert isinstance(steps, list)
    runs = "\n".join(str(step.get("run", "")) for step in steps)
    assert "omnibase_core.handlers.handler_public_runner_placement_cli" in runs
    assert "POSITIVE CONTROL FAILED" in runs
    assert "--base-ref" in runs
    assert "--repo omniclaude --visibility public" in runs


def test_ci_job_and_hook_run_the_same_core_release() -> None:
    """The CI job installs 0.47.46 and the hook's rev is that release's tag."""
    env = _ci_job()["env"]
    assert isinstance(env, dict)
    assert env["RUNNER_PLACEMENT_CORE"] == f"omnibase-core=={CORE_RELEASE}"
    hooks = _hooks()
    assert len(hooks) == 1, f"expected one {HOOK_ID} hook, found {len(hooks)}"
    assert hooks[0][0] == f"v{CORE_RELEASE}"


def test_ci_summary_requires_the_job_to_succeed() -> None:
    assert JOB_NAME in GATE_JOBS
    assert JOB_NAME in STRICT_SUCCESS_JOBS


def test_precommit_hook_names_this_public_repository() -> None:
    hooks = _hooks()
    assert hooks
    assert hooks[0][1]["args"] == ["--repo", "omniclaude", "--visibility", "public"]


GUARDED_REUSABLES = (
    "anti-growth-baseline-reusable.yml",
    "branch-claim-check-reusable.yml",
    "deploy-gate-reusable.yml",
    "doctrine-claim-gate-reusable.yml",
    "private-repo-runner-placement-reusable.yml",
    "public-repo-hygiene-reusable.yml",
    "route-runner-reusable.yml",
    "secrets-baseline-wiring-reusable.yml",
)


@pytest.mark.parametrize("name", GUARDED_REUSABLES)
def test_reusable_lab_route_is_taken_by_a_private_caller_only(name: str) -> None:
    jobs = _load(WORKFLOWS / name)["jobs"]
    assert isinstance(jobs, dict)
    for job in jobs.values():
        runs_on = " ".join(str(job["runs-on"]).split())
        if "self-hosted" not in runs_on:
            continue
        body = runs_on.removeprefix("${{").removesuffix("}}").strip()
        assert body.startswith(f"{PRIVATE_CALLER} ("), name
        assert body.endswith(") || 'ubuntu-latest'"), name


def test_reusable_lab_route_control_an_unguarded_fleet_route_is_seen() -> None:
    """The failing control: the test above reads the shape it would refuse."""
    unguarded = (
        """${{ fromJSON(vars.OMNI_TRUSTED_CI_RUNS_ON_JSON || '["self-hosted"]') }}"""
    )
    body = unguarded.removeprefix("${{").removesuffix("}}").strip()
    assert "self-hosted" in body
    assert not body.startswith(f"{PRIVATE_CALLER} (")


def test_reusable_lab_route_the_runner_label_gate_is_hosted() -> None:
    jobs = _load(WORKFLOWS / "runner-label-exists-reusable.yml")["jobs"]
    assert isinstance(jobs, dict)
    assert jobs["runner-label-exists"]["runs-on"] == "ubuntu-latest"


def test_the_lab_selection_refusal_is_in_the_required_job() -> None:
    """The refusal runs in the job CI Summary sweeps, with its failing control first."""
    steps = _load(CI_WORKFLOW)["jobs"]["public-runner-placement"]["steps"]
    runs = [str(step.get("run", "")) for step in steps]
    control = next(i for i, run in enumerate(runs) if "FAILING CONTROL FAILED" in run)
    refusal = next(
        i
        for i, run in enumerate(runs)
        if "validator_public_lab_selection" in run and "--variables-json" in run
    )
    assert control < refusal
