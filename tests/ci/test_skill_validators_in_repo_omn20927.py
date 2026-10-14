# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20927: omniclaude's skill-hygiene and skill-contracts checks run in-repo.

The ``skill-hygiene`` and ``skill-contract-validation`` jobs in ``ci.yml`` minted an
onexbot-occ-writer token, checked out onex_change_control at a pinned rev and ran a
validator script from that checkout. Both validators judge omniclaude's own plugin
skills, so omniclaude owns the behaviour: they live in
``node_skill_validation_compute`` and both jobs, and the matching pre-commit hook,
run that node's CLI. The Version Pin Compliance job is the sibling slice
(omniclaude#2673) and is not touched here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
REQUIRED_CHECKS = REPO_ROOT / ".github" / "required-checks.yaml"
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"
NODE_DIR = REPO_ROOT / "src" / "omniclaude" / "nodes" / "node_skill_validation_compute"

_OCC_REPOSITORY = "OmniNode-ai/onex_change_control"
_CLI_MODULE = "omniclaude.nodes.node_skill_validation_compute"
_SKILL_JOBS = {
    "skill-hygiene": "hygiene --skills-root plugins/onex/skills --strict",
    "skill-contract-validation": "contracts --skills-root plugins/onex/skills",
}
_OCC_MARKERS = (
    "onex_change_control",
    "onex-change-control",
    "ONEXBOT_OCC",
    "onexbot-occ-writer",
)


def _ci_jobs() -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    jobs = data["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _job_steps(job_id: str) -> list[dict[str, Any]]:
    steps = _ci_jobs()[job_id]["steps"]
    assert isinstance(steps, list)
    return steps


def _occ_reads(steps: list[dict[str, Any]]) -> list[str]:
    """Return the steps of one job that name onex_change_control in any field."""
    return [
        str(step.get("name", "<unnamed>"))
        for step in steps
        if any(marker in yaml.safe_dump(step) for marker in _OCC_MARKERS)
    ]


def _hook_entry(hook_id: str) -> str:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    for repo in config["repos"]:
        for hook in repo["hooks"]:
            if hook["id"] == hook_id:
                return str(hook["entry"])
    raise AssertionError(f"pre-commit hook {hook_id} not found")


@pytest.mark.parametrize("job_id", sorted(_SKILL_JOBS))
def test_skill_job_checks_out_no_onex_change_control(job_id: str) -> None:
    steps = _job_steps(job_id)
    assert [
        s for s in steps if s.get("with", {}).get("repository") == _OCC_REPOSITORY
    ] == []
    assert _occ_reads(steps) == []


@pytest.mark.parametrize(("job_id", "arguments"), sorted(_SKILL_JOBS.items()))
def test_skill_job_runs_the_in_repo_validator(job_id: str, arguments: str) -> None:
    runs = [str(step.get("run", "")) for step in _job_steps(job_id)]
    assert any(
        f"-m {_CLI_MODULE} {arguments}" in run and "uv run" in run for run in runs
    ), runs


@pytest.mark.parametrize("job_id", sorted(_SKILL_JOBS))
def test_skill_job_installs_the_repo_before_running_the_validator(job_id: str) -> None:
    runs = [str(step.get("run", "")) for step in _job_steps(job_id)]
    sync = [i for i, run in enumerate(runs) if "uv sync" in run]
    ran = [i for i, run in enumerate(runs) if _CLI_MODULE in run]
    assert sync and ran and min(sync) < min(ran)


def test_ci_workflow_runs_no_validator_script_from_onex_change_control() -> None:
    text = CI_YML.read_text(encoding="utf-8")
    assert "onex_change_control/scripts/validation/validate_skill" not in text


@pytest.mark.parametrize("job_id", sorted(_SKILL_JOBS))
def test_skill_job_still_exists_and_is_still_gated(job_id: str) -> None:
    jobs = _ci_jobs()
    assert job_id in jobs
    gate_needs = jobs["quality-gate"]["needs"]
    assert job_id in gate_needs
    manifest = yaml.safe_load(REQUIRED_CHECKS.read_text(encoding="utf-8"))
    required = {g["name"] for g in manifest["gates"] if g["mode"] == "REQUIRED"}
    assert jobs[job_id]["name"] in required | {"Skill Contract Validation"}


@pytest.mark.parametrize("hook_id", ["skill-contract-validation", "skill-hygiene"])
def test_pre_commit_skill_hooks_read_no_onex_change_control(hook_id: str) -> None:
    entry = _hook_entry(hook_id)
    assert "onex_change_control" not in entry
    assert "validate_skill_contracts_wrapper" not in entry


def test_the_occ_backed_wrapper_script_is_gone() -> None:
    assert not (REPO_ROOT / "scripts" / "validate_skill_contracts_wrapper.sh").exists()


def test_validator_node_is_a_contract_node_with_two_handlers_and_a_cli() -> None:
    assert (NODE_DIR / "contract.yaml").is_file()
    assert (NODE_DIR / "node.py").is_file()
    assert (NODE_DIR / "__main__.py").is_file()
    for handler in ("handler_skill_hygiene.py", "handler_skill_contracts.py"):
        assert (NODE_DIR / "handlers" / handler).is_file()


def test_every_handler_module_is_routed_in_the_contract() -> None:
    """The imperative-contract guard flags any handlers/ module the contract omits."""
    contract = yaml.safe_load((NODE_DIR / "contract.yaml").read_text(encoding="utf-8"))
    routed = {
        entry["handler"]["module"].rsplit(".", 1)[1]
        for entry in contract["handler_routing"]["handlers"]
    }
    modules = {
        path.stem
        for path in (NODE_DIR / "handlers").glob("*.py")
        if not path.name.startswith("_")
    }
    assert modules == routed


def _dangling_needs(jobs: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    """Return ``(job, missing_need)`` for every ``needs:`` entry that names no job."""
    return [
        (job_id, need)
        for job_id, job in jobs.items()
        for need in (
            [job["needs"]]
            if isinstance(job.get("needs"), str)
            else job.get("needs", [])
        )
        if need not in jobs
    ]


def test_version_pin_ending_holds_across_the_whole_job_set() -> None:
    """The third job named by the ticket ended in omniclaude#2673 (the sibling slice).

    This holds the ending together with this change: no job in ``ci.yml`` runs the
    version-pin script or either skill validator from an onex_change_control
    checkout, the retired job is gone, and every ``needs:`` entry still names a job.
    """
    jobs = _ci_jobs()
    text = CI_YML.read_text(encoding="utf-8")
    assert "version-pin-check" not in jobs
    for script in (
        "check_version_pins",
        "validate_skill_hygiene",
        "validate_skill_contracts",
    ):
        assert script not in text, script
    assert _dangling_needs(jobs) == []


def test_dangling_needs_checker_flags_a_broken_needs_entry() -> None:
    """Positive control: the needs checker above is not vacuous."""
    jobs = _ci_jobs()
    victim = next(job_id for job_id, job in jobs.items() if "needs" in job)
    broken = {**jobs, victim: {**jobs[victim], "needs": ["no-such-job-omn20927"]}}
    assert _dangling_needs(broken) == [(victim, "no-such-job-omn20927")]
