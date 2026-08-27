# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for the OCC publisher runner carve-out (OMN-16691).

Context (OMN-16682 constraint 8). ``occ-autobind`` and ``occ-companion-effect``
publish to the TAILNET-ONLY dev-lane broker
``omninode-pc.tail75df5e.ts.net:19092``. Only the self-hosted ``omnibase-ci``
fleet on .201 is on that tailnet. Until 2026-08-26 these jobs selected their
runner from the SHARED ``OMNI_TRUSTED_CI_RUNS_ON_JSON`` seam — the same variable
that governs every lint/test/build job in the org and that the OMN-16682
hosted-runner migration exists to flip.

On 2026-08-26T22:46:41Z that seam was flipped to ``["ubuntu-latest"]``. The
publishers landed on GitHub-hosted runners, could not resolve the broker name,
and failed loud exactly as OMN-14451/OMN-14639 designed. But because the
publisher is what mints the OCC companion that stamps ``Evidence-Source:
OCC#<n>``, and the receipt gate (OMN-10419) hard-fails without that line, the
consequence was not a degraded CI job — **nothing could merge in any OCC-gated
repo for 45 minutes** (incident OMN-16691).

The carve-out these tests pin: the trusted branch of every broker-dependent OCC
publisher job reads a DEDICATED ``OMNI_OCC_AUTOBIND_RUNS_ON_JSON`` variable with
a literal ``["self-hosted","omnibase-ci"]`` fallback, and never the shared seam.
The dedicated variable is deliberately left UNSET at org and repo scope, so the
literal is the operating value and the shared seam can be flipped without
relocating these jobs.

These tests are the mechanical guard on that property. A future edit that
"harmonises" these jobs back onto ``OMNI_TRUSTED_CI_RUNS_ON_JSON`` reads as a
tidy-up in review and re-arms a merge-wide outage; it fails here instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

CARVEOUT_VAR = "OMNI_OCC_AUTOBIND_RUNS_ON_JSON"
SHARED_SEAM_VAR = "OMNI_TRUSTED_CI_RUNS_ON_JSON"
FLEET_LITERAL = '\'["self-hosted","omnibase-ci"]\''

# (workflow file, job id, is-a-reusable-with-a-fork-branch)
#
# The two reusables are the single home every caller repo inherits from: `vars`
# in a reusable resolve in the CALLER's context, so pinning here covers all 12
# consumer repos with no caller-side change (OMN-16682 constraint 7). The two
# manual-replay jobs are omniclaude's own workflow_dispatch recovery entrypoints
# for the same broker — they hardcode RUNNER_IS_TRUSTED=true, so on a hosted
# runner the recovery path would be dead exactly when an autobind outage makes
# it necessary.
BROKER_DEPENDENT_JOBS: tuple[tuple[str, str, bool], ...] = (
    ("call-occ-autobind-reusable.yml", "publish-occ-autobind", True),
    ("call-occ-companion-effect-reusable.yml", "publish-occ-companion-effect", True),
    ("call-occ-autobind.yml", "occ-autobind-manual-replay", False),
    ("call-occ-companion-effect.yml", "occ-companion-effect-manual-replay", False),
)


def _load(workflow_file: str) -> dict[str, Any]:
    path = WORKFLOWS / workflow_file
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{workflow_file} must parse as a YAML mapping"
    return cast("dict[str, Any]", loaded)


def _runs_on(workflow_file: str, job_id: str) -> str:
    jobs = _load(workflow_file).get("jobs")
    assert isinstance(jobs, dict), f"{workflow_file} must define jobs"
    job = jobs.get(job_id)
    assert isinstance(job, dict), f"{workflow_file} must define job `{job_id}`"
    runs_on = job.get("runs-on")
    assert isinstance(runs_on, str), (
        f"{workflow_file}::{job_id} must set `runs-on` to a selector expression"
    )
    return runs_on


@pytest.mark.parametrize(
    ("workflow_file", "job_id"),
    [(wf, job) for wf, job, _ in BROKER_DEPENDENT_JOBS],
)
def test_broker_publisher_uses_the_dedicated_carveout_variable(
    workflow_file: str, job_id: str
) -> None:
    runs_on = _runs_on(workflow_file, job_id)
    assert CARVEOUT_VAR in runs_on, (
        f"{workflow_file}::{job_id} reaches the tailnet-only dev-lane broker and "
        f"must select its runner from the dedicated `{CARVEOUT_VAR}` variable "
        f"(OMN-16691 / OMN-16682 constraint 8)"
    )


@pytest.mark.parametrize(
    ("workflow_file", "job_id"),
    [(wf, job) for wf, job, _ in BROKER_DEPENDENT_JOBS],
)
def test_broker_publisher_is_not_governed_by_the_shared_seam(
    workflow_file: str, job_id: str
) -> None:
    runs_on = _runs_on(workflow_file, job_id)
    assert SHARED_SEAM_VAR not in runs_on, (
        f"{workflow_file}::{job_id} must NOT read `{SHARED_SEAM_VAR}`. That "
        "variable governs ~475 unrelated lint/test/build jobs and exists to be "
        "flipped to ubuntu-latest by the OMN-16682 migration. A hosted runner "
        "cannot resolve omninode-pc.tail75df5e.ts.net:19092, so binding this "
        "publisher to that seam makes a CI migration a merge-wide outage "
        "(incident OMN-16691, 2026-08-26 22:46:41Z-23:32:03Z)."
    )


@pytest.mark.parametrize(
    ("workflow_file", "job_id"),
    [(wf, job) for wf, job, _ in BROKER_DEPENDENT_JOBS],
)
def test_fleet_literal_is_the_operating_value(workflow_file: str, job_id: str) -> None:
    """The dedicated variable is deliberately UNSET, so the literal is live.

    If someone later sets ``OMNI_OCC_AUTOBIND_RUNS_ON_JSON`` in GitHub, that is
    an explicit operator action that must carry a broker-reachability proof.
    Until then the hardcoded fallback is what actually places these jobs, so it
    must name the fleet and not be quietly softened to ubuntu-latest.
    """
    runs_on = _runs_on(workflow_file, job_id)
    assert FLEET_LITERAL in runs_on, (
        f"{workflow_file}::{job_id} must carry the literal "
        f"{FLEET_LITERAL} fallback — with the dedicated variable unset it is "
        "the value that actually selects the runner"
    )


@pytest.mark.parametrize(
    ("workflow_file", "job_id"),
    [(wf, job) for wf, job, is_reusable in BROKER_DEPENDENT_JOBS if is_reusable],
)
def test_fork_isolation_branch_is_unchanged(workflow_file: str, job_id: str) -> None:
    """OMN-16683: the carve-out must not touch the fork-PR path.

    Fork PRs keep routing through ``OMNI_PUBLIC_PR_RUNS_ON_JSON`` (default
    ``["ubuntu-latest"]``), where the publisher skips gracefully because no
    broker exists. Routing untrusted fork code onto the LAN-attached fleet is
    the exposure OMN-16683 closed; the carve-out only re-homes the TRUSTED
    branch of the selector.
    """
    runs_on = _runs_on(workflow_file, job_id)
    assert "OMNI_PUBLIC_PR_RUNS_ON_JSON" in runs_on, (
        f"{workflow_file}::{job_id} must retain the fork-PR branch of the "
        "selector — fork isolation (OMN-16683) is out of scope for this pin"
    )
    assert "head.repo.full_name != github.repository" in runs_on, (
        f"{workflow_file}::{job_id} must retain the fork/non-fork test that "
        "chooses between the public and carved-out runner classes"
    )


@pytest.mark.parametrize(
    ("workflow_file", "job_id"),
    [(wf, job) for wf, job, _ in BROKER_DEPENDENT_JOBS],
)
def test_carveout_rationale_is_documented_inline(
    workflow_file: str, job_id: str
) -> None:
    """A bare variable rename is not self-explaining; the WHY must be adjacent.

    The next reader's default instinct is to collapse this back onto the shared
    seam for consistency. The inline note has to name the tailnet broker
    dependency and the ticket, or the guard is only mechanical.
    """
    raw = (WORKFLOWS / workflow_file).read_text(encoding="utf-8")
    assert "OMN-16691" in raw, (
        f"{workflow_file} must cite OMN-16691 inline so the carve-out is not "
        "read as an arbitrary variable rename"
    )
    assert "tail75df5e.ts.net" in raw or "TAILNET" in raw, (
        f"{workflow_file} must name the tailnet broker dependency inline — it "
        "is the entire reason this job cannot follow the shared seam"
    )
