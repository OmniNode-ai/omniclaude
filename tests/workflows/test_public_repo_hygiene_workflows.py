# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Workflow invariants for the public-repo hygiene gate."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
REUSABLE = WORKFLOWS / "public-repo-hygiene-reusable.yml"
AUDIT = WORKFLOWS / "public-repo-hygiene-audit.yml"
CALLER = WORKFLOWS / "public-repo-hygiene.yml"


def _workflow(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    assert isinstance(loaded, dict)
    return loaded


def _step(workflow_path: Path, job_name: str, step_name: str) -> dict[str, object]:
    workflow = _workflow(workflow_path)
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    job = jobs[job_name]
    assert isinstance(job, dict)
    steps = job["steps"]
    assert isinstance(steps, list)
    for candidate in steps:
        assert isinstance(candidate, dict)
        if candidate.get("name") == step_name:
            return candidate
    raise AssertionError(
        f"{workflow_path} job {job_name} has no step named {step_name!r}"
    )


def test_public_repo_hygiene_reusable_uses_org_wide_onexbot_credentials() -> None:
    """Public callers do not all receive the selected OCC app secrets."""
    step = _step(
        REUSABLE, "public-repo-hygiene", "Mint token for the private vocabulary repo"
    )
    with_block = step["with"]
    assert isinstance(with_block, dict)

    assert with_block["app-id"] == "${{ secrets.ONEXBOT_APP_ID }}"
    assert with_block["private-key"] == "${{ secrets.ONEXBOT_APP_PRIVATE_KEY }}"
    assert "ONEXBOT_OCC_APP_ID" not in REUSABLE.read_text(encoding="utf-8")


def test_public_repo_hygiene_audit_uses_org_wide_onexbot_credentials() -> None:
    """The org audit has the same public governance credential boundary."""
    step = _step(AUDIT, "audit", "Mint org-read token")
    with_block = step["with"]
    assert isinstance(with_block, dict)

    assert with_block["app-id"] == "${{ secrets.ONEXBOT_APP_ID }}"
    assert with_block["private-key"] == "${{ secrets.ONEXBOT_APP_PRIVATE_KEY }}"
    assert "ONEXBOT_OCC_APP_ID" not in AUDIT.read_text(encoding="utf-8")


def test_public_repo_hygiene_caller_still_inherits_secrets() -> None:
    workflow = _workflow(CALLER)
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    caller = jobs["public-repo-hygiene"]
    assert isinstance(caller, dict)

    assert caller["secrets"] == "inherit"


def test_public_repo_hygiene_reusable_fetches_and_passes_the_lab_vocabulary() -> None:
    """OMN-19766: the lab-config class reads a second private file.

    It resolves its repository from an org variable (never named in public
    source), fetches it with the same app token, and the gate is handed its
    path; a missing file is a refusal before the gate runs.
    """
    text = REUSABLE.read_text(encoding="utf-8")
    resolve = _step(
        REUSABLE, "public-repo-hygiene", "Resolve the private lab vocabulary repo"
    )
    env = resolve["env"]
    assert isinstance(env, dict)
    assert env["FROM_VARS"] == "${{ vars.OMNI_HYGIENE_LAB_VOCAB_REPO }}"
    assert "exit 1" in str(resolve["run"])

    mint = _step(
        REUSABLE, "public-repo-hygiene", "Mint token for the private vocabulary repo"
    )
    with_block = mint["with"]
    assert isinstance(with_block, dict)
    assert "steps.lab-vocab-repo.outputs.name" in str(with_block["repositories"])

    fetch = _step(REUSABLE, "public-repo-hygiene", "Fetch the private lab vocabulary")
    fetch_with = fetch["with"]
    assert isinstance(fetch_with, dict)
    assert fetch_with["path"] == ".public-repo-hygiene-lab-vocabulary"
    assert "public_repo_hygiene_lab_vocabulary.yaml" in str(
        fetch_with["sparse-checkout"]
    )

    gate_step = _step(
        REUSABLE, "public-repo-hygiene", "Run the public-repo hygiene gate"
    )
    run = str(gate_step["run"])
    assert '--lab-vocabulary "${LAB_VOCAB_PATH}"' in run
    assert 'if [ ! -f "${LAB_VOCAB_PATH}" ]' in run
    assert "OMNI_HYGIENE_LAB_VOCAB_REPO" in text
