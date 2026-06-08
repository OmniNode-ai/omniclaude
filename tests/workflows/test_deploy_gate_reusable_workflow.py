# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for the reusable deploy-gate workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy-gate-reusable.yml"


def _load_workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "workflow must parse as a YAML mapping"
    return cast("dict[str, Any]", loaded)


def _deploy_gate_job(workflow: dict[str, Any]) -> dict[str, Any]:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "workflow must define jobs"
    job = jobs.get("deploy-gate")
    assert isinstance(job, dict), "deploy-gate job must exist"
    return cast("dict[str, Any]", job)


def _step(job: dict[str, Any], name: str) -> dict[str, Any]:
    steps = job.get("steps")
    assert isinstance(steps, list), "deploy-gate job must define steps"
    step = next(
        item for item in steps if isinstance(item, dict) and item.get("name") == name
    )
    return cast("dict[str, Any]", step)


CHECKOUT_SCRIPT = REPO_ROOT / "scripts" / "deploy-gate" / "checkout-occ-contracts.sh"


def test_reusable_deploy_gate_delegates_occ_checkout_to_bounded_script() -> None:
    """OMN-12564: the OCC checkout is delegated to the hardened, bounded script.

    The previous inline block only bounded the fetch (``timeout 90 git ... &&
    git ... checkout``), letting a wedged blobless-partial-clone checkout spin
    until the job timeout. The workflow must now (a) sparse-fetch the script
    from omniclaude, (b) run it under a step-level timeout, and (c) carry no
    inline lazy-filter fetch/checkout sequence.
    """
    workflow = _load_workflow()
    job = _deploy_gate_job(workflow)

    assert job["timeout-minutes"] == 25

    # The hardened checkout script must be present and referenced by name.
    assert CHECKOUT_SCRIPT.is_file(), f"checkout script missing: {CHECKOUT_SCRIPT}"

    # A dedicated sparse checkout of the omniclaude script is wired in.
    fetch_step = _step(job, "Fetch OCC checkout script (omniclaude)")
    assert fetch_step["if"] == "github.event_name != 'merge_group'"
    assert fetch_step["uses"].startswith("actions/checkout@")
    assert fetch_step["with"]["repository"] == "OmniNode-ai/omniclaude"
    assert (
        fetch_step["with"]["sparse-checkout"]
        == "scripts/deploy-gate/checkout-occ-contracts.sh"
    )

    step = _step(
        job, "Checkout onex_change_control contracts (canonical contract source)"
    )
    assert step["if"] == "github.event_name != 'merge_group'"
    assert "uses" not in step
    # Step-level hard timeout (outer bound) is present.
    assert step["timeout-minutes"] == 12
    assert step["env"]["OCC_REF"] == "dev"
    assert (
        step["env"]["OCC_REPO_URL"]
        == "https://github.com/OmniNode-ai/onex_change_control.git"
    )

    run = step["run"]
    # Still fail-fast on a missing token.
    assert "OCC contracts checkout requires GITHUB_TOKEN" in run
    # Delegates to the bounded script — no inline fetch/checkout loop.
    assert "scripts/deploy-gate/checkout-occ-contracts.sh" in run
    assert "--filter=blob:none" not in run
    assert "checkout --force FETCH_HEAD" not in run
    assert "retry_delays=(0 10 20 30 45)" not in run


def test_checkout_script_is_bounded_and_self_diagnosing() -> None:
    """The hardened script bounds fetch + checkout and emits diagnostics."""
    text = CHECKOUT_SCRIPT.read_text(encoding="utf-8")

    # Hard timeout binary is resolved and used (git-level inner bound).
    assert 'TIMEOUT_BIN="timeout"' in text
    assert 'TIMEOUT_BIN="gtimeout"' in text
    assert "run_git_bounded" in text

    # Both phases (fetch and checkout) run under the bounded helper.
    assert 'run_git_bounded "$OCC_FETCH_TIMEOUT_SECS"' in text
    assert 'run_git_bounded "$OCC_CHECKOUT_TIMEOUT_SECS"' in text

    # Deterministic full-ref checkout — no lazy blob filter in an active command.
    active = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    assert "--filter=blob:none" not in active

    # Diagnostic block fields required by the acceptance criteria.
    assert "OCC checkout diagnostics" in text
    assert "OCC ref:" in text
    assert "Fetch command:" in text
    assert "Elapsed:" in text
    assert "Last git subprocess:" in text
    assert "emit_process_tree" in text
