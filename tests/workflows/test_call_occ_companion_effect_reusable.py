# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for the reusable occ-companion-effect publisher workflow.

OMN-14941: the born path for the canonical RSD-3 OCC writer. These tests pin
the three properties that make this reusable a faithful, secret-free thin
publisher rather than a drifted copy of the occ-autobind reusable:

* SECRET-FREE — the dev-lane broker comes from omnimarket's committed
  ``config/ci_bus_lanes.yaml`` overlay (OMN-14813). Reintroducing the
  caller-repo Kafka bootstrap-servers secret (the pre-OMN-14813 posture) would
  silently re-create the OMN-14800 opaque-secret drift surface and force every
  caller repo to provision a secret it does not need.
* RESOLVABLE PIN — the ``omnimarket-ref`` input defaults to ``dev``, the only
  ref where the companion-effect publisher exists (the E1/OMN-14811 verifier
  failure class was a reusable pinning a ref where the sourced files were a
  404, making every invocation fail at sparse-checkout).
* CLOSURE-COMPLETE SPARSE CHECKOUT — the publisher file-path-loads its sibling
  ``publish_occ_autobind_command.py`` for the lane-overlay helpers; dropping
  the sibling from the sparse-checkout list would pass YAML review and fail
  at runtime on every invocation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "call-occ-companion-effect-reusable.yml"
)

EXPECTED_SPARSE_CHECKOUT_FILES = (
    "scripts/publish_occ_companion_effect_command.py",
    # File-path-loaded sibling: the companion-effect publisher reuses the
    # OMN-14801/OMN-14813 lane-overlay helpers from the autobind publisher by
    # file path (single source of truth). It is a REQUIRED runtime file.
    "scripts/publish_occ_autobind_command.py",
    "config/ci_bus_lanes.yaml",
    "src/omnimarket/events/topics.py",
)


def _load_workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "workflow must parse as a YAML mapping"
    return cast("dict[str, Any]", loaded)


def _on_block(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML (YAML 1.1) parses the bare `on:` key as boolean True.
    block = workflow.get("on", workflow.get(True))
    assert isinstance(block, dict), "workflow must define an `on:` block"
    return cast("dict[str, Any]", block)


def _publish_job(workflow: dict[str, Any]) -> dict[str, Any]:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "workflow must define jobs"
    job = jobs.get("publish-occ-companion-effect")
    assert isinstance(job, dict), "publish-occ-companion-effect job must exist"
    return cast("dict[str, Any]", job)


def _step(job: dict[str, Any], name: str) -> dict[str, Any]:
    steps = job.get("steps")
    assert isinstance(steps, list), "job must define steps"
    step = next(
        item for item in steps if isinstance(item, dict) and item.get("name") == name
    )
    return cast("dict[str, Any]", step)


def test_workflow_is_workflow_call_only() -> None:
    on_block = _on_block(_load_workflow())
    assert set(on_block) == {"workflow_call"}, (
        "the reusable must be invocable only via workflow_call — a direct "
        "pull_request trigger here would double-publish for omniclaude PRs"
    )


def test_workflow_is_secret_free() -> None:
    """OMN-14813: no caller-repo secret may feed the broker resolution."""
    workflow = _load_workflow()
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")

    # No GitHub secrets expression anywhere in the workflow.
    assert "${{ secrets." not in raw, (
        "the reusable must not consume ANY caller secret — the dev-lane "
        "broker is committed in omnimarket config/ci_bus_lanes.yaml "
        "(OMN-14813) and the dev listener is plaintext (no SASL)"
    )

    # workflow_call declares no secrets contract.
    on_block = _on_block(workflow)
    workflow_call = on_block["workflow_call"]
    assert isinstance(workflow_call, dict)
    assert "secrets" not in workflow_call, (
        "workflow_call must not declare a secrets: block (secret-free by "
        "construction, OMN-14813)"
    )

    # The publish step env carries exactly the PR context + lane — nothing
    # broker-shaped.
    step = _step(
        _publish_job(workflow),
        "Publish onex.cmd.omnimarket.occ-companion-effect-requested.v1",
    )
    env = step.get("env")
    assert isinstance(env, dict)
    assert set(env) == {"PR_REPO", "PR_NUMBER", "PR_HEAD_SHA", "PR_BODY", "LANE"}


def test_omnimarket_ref_defaults_to_dev_the_only_resolvable_ref() -> None:
    """E1/OMN-14811 failure class: a pin at a ref where the files are a 404."""
    on_block = _on_block(_load_workflow())
    inputs = on_block["workflow_call"]["inputs"]
    ref_input = inputs["omnimarket-ref"]
    assert ref_input["default"] == "dev", (
        "omnimarket-ref must default to `dev`: the companion-effect publisher "
        "exists only on omnimarket dev until OMN-14941 promotes to main "
        "(re-pin to `main` then — OMN-14812-style follow-up)"
    )
    assert ref_input.get("required") is False

    lane_input = inputs["lane"]
    assert lane_input["default"] == "dev"


def test_sparse_checkout_covers_the_full_file_path_load_closure() -> None:
    workflow = _load_workflow()
    fetch_step = _step(
        _publish_job(workflow),
        "Fetch canonical occ-companion-effect publisher (omnimarket)",
    )
    with_block = fetch_step.get("with")
    assert isinstance(with_block, dict)
    assert with_block["repository"] == "OmniNode-ai/omnimarket"
    assert with_block["ref"] == "${{ inputs.omnimarket-ref }}"
    assert with_block["persist-credentials"] is False
    assert with_block["sparse-checkout-cone-mode"] is False

    sparse_checkout = with_block["sparse-checkout"]
    assert isinstance(sparse_checkout, str)
    listed = [line.strip() for line in sparse_checkout.splitlines() if line.strip()]
    assert listed == list(EXPECTED_SPARSE_CHECKOUT_FILES), (
        "sparse-checkout must list exactly the publisher's file-path-load "
        "closure (publisher + sibling helper script + lane overlay + topic "
        "registry) — a missing sibling passes YAML review and fails at "
        "runtime on every invocation"
    )


def test_trusted_runner_bifurcation_and_fail_loud_threading() -> None:
    job = _publish_job(_load_workflow())

    runs_on = job.get("runs-on")
    assert isinstance(runs_on, str)
    assert "OMNI_PUBLIC_PR_RUNS_ON_JSON" in runs_on
    # OMN-16691 carve-out: the trusted branch moved OFF the shared
    # `OMNI_TRUSTED_CI_RUNS_ON_JSON` seam onto the dedicated
    # `OMNI_OCC_AUTOBIND_RUNS_ON_JSON` knob. The bifurcation this test names is
    # unchanged (fork -> public class, trusted -> fleet); only the source of the
    # trusted class changed, so that a hosted-runner migration of general CI
    # cannot relocate a tailnet-broker-dependent publisher. Full rationale and
    # the cross-file guard live in test_occ_publisher_runner_carveout.py.
    assert "OMNI_OCC_AUTOBIND_RUNS_ON_JSON" in runs_on
    assert "OMNI_TRUSTED_CI_RUNS_ON_JSON" not in runs_on

    env = job.get("env")
    assert isinstance(env, dict)
    assert "RUNNER_IS_TRUSTED" in env, (
        "RUNNER_IS_TRUSTED must be threaded to the publisher so a broker "
        "wiring gap fails loud on the trusted runner (OMN-14451) instead of "
        "silently exiting 0"
    )

    assert job.get("timeout-minutes") == 5


def test_bot_and_omn_ticket_gate_materializes_the_required_context() -> None:
    job = _publish_job(_load_workflow())
    assert "if" not in job, (
        "a job-level eligibility guard suppresses the required check run; "
        "the producer must execute and no-op ineligible PRs"
    )

    eligibility = _step(job, "Classify OCC companion-effect eligibility")
    assert eligibility.get("id") == "eligibility"
    run = eligibility.get("run")
    assert isinstance(run, str)
    assert "dependabot[bot]" in run
    assert "renovate[bot]" in run
    assert "OMN-" in run
    assert "eligible=$eligible" in run

    steps = job.get("steps")
    assert isinstance(steps, list)
    publisher_steps = [
        step
        for step in steps
        if isinstance(step, dict)
        and step.get("name") != "Classify OCC companion-effect eligibility"
    ]
    assert publisher_steps
    assert all(
        step.get("if") == "steps.eligibility.outputs.eligible == 'true'"
        for step in publisher_steps
    ), "every expensive publisher step must no-op when eligibility is false"


def test_publish_step_runs_canonical_script_with_lane() -> None:
    workflow = _load_workflow()
    step = _step(
        _publish_job(workflow),
        "Publish onex.cmd.omnimarket.occ-companion-effect-requested.v1",
    )
    run = step.get("run")
    assert isinstance(run, str)
    assert (
        'python scripts/publish_occ_companion_effect_command.py --lane "${LANE}"' in run
    )
    assert step.get("working-directory") == ".occ-companion-effect-src"


def test_permissions_are_contents_read_only() -> None:
    workflow = _load_workflow()
    assert workflow.get("permissions") == {"contents": "read"}
