# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The cross-repo runner-route shim holds no decision (OMN-18423).

A caller outside omnibase_infra asks this reusable workflow where its jobs
should run. The answer comes from an ONEX COMPUTE node in omnibase_infra whose
contract declares the thresholds, the label sets and the private-repository
refusal. This file is the mechanical guard on the word SHIM: the moment a
threshold, a label set or a second copy of the decision appears here, there are
two routing policies that agree until somebody edits one of them.

THREE FAILURES PINNED HERE ARE INVISIBLE TO EVERY CHECK-BASED GATE, which is
why they are tests rather than review items:

* An expression in a ``workflow_call`` description fails every CALLING workflow
  at startup -- zero jobs, no red check, and a run title that falls back to the
  file path (omnibase_infra run 35037012235).
* A route job without its environment raises ModuleNotFoundError, falls through
  the fail-closed floor, and reports SUCCESS carrying
  ``reason=probe_error:module_unavailable`` while placing everything hosted
  (omnibase_infra run 35039101488).
* A floor that runs AFTER the refusal check would overwrite a deliberate
  refusal with hosted labels, which is the one placement the ruling forbids.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "route-runner-reusable.yml"

# The routing node's home, pinned by full commit sha.
NODE_REPO = "OmniNode-ai/omnibase_infra"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return cast("dict[str, Any]", loaded)


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    """The ``on:`` block.

    YAML 1.1 parses the bare key ``on`` as the boolean True, so
    ``workflow["on"]`` raises on every GitHub workflow file. Resolved once here
    rather than rediscovered at each call site.
    """
    block = workflow.get(True, workflow.get("on"))
    assert isinstance(block, dict)
    return cast("dict[str, Any]", block)


def _route_job() -> dict[str, Any]:
    job = _workflow()["jobs"]["route"]
    assert isinstance(job, dict)
    return cast("dict[str, Any]", job)


def _step(step_id: str) -> dict[str, Any]:
    for step in _route_job()["steps"]:
        if isinstance(step, dict) and step.get("id") == step_id:
            return cast("dict[str, Any]", step)
    raise AssertionError(f"no step with id {step_id!r}")


# --- it is callable at all ---------------------------------------------------


def test_it_is_a_reusable_workflow_with_the_inputs_a_caller_needs() -> None:
    block = _triggers(_workflow())["workflow_call"]
    assert set(block["inputs"]) == {"workflow_path", "force", "dry_run"}
    assert block["inputs"]["workflow_path"]["required"] is True
    assert block["inputs"]["force"]["default"] == "auto"


def test_it_exposes_the_outputs_a_consumer_resolves_its_placement_from() -> None:
    outputs = _triggers(_workflow())["workflow_call"]["outputs"]
    assert set(outputs) == {"runs_on", "decision", "reason"}
    assert "jobs.route.outputs.runs_on" in outputs["runs_on"]["value"]


def test_no_workflow_call_description_carries_an_expression() -> None:
    """A STARTUP FAILURE, and the most expensive shape of one.

    Actions evaluates expressions inside a ``workflow_call`` block, where the
    ``needs`` context does not exist. An illustrative snippet in a description
    therefore fails every CALLING workflow before a single job starts. Nothing
    reports on a run that never started, so no check-based gate can see it.
    """
    block = _triggers(_workflow())["workflow_call"]
    for section in ("inputs", "outputs"):
        for field, spec in (block.get(section) or {}).items():
            description = str((spec or {}).get("description", ""))
            assert "${{" not in description, (
                f"workflow_call.{section}.{field} description carries an "
                f"expression; that is a startup failure in every caller"
            )


# --- it is a SHIM: no decision, no thresholds --------------------------------


def test_the_shim_declares_no_threshold() -> None:
    """Every threshold is contract-declared in the node, not restated here.

    Checked as an absence of NUMBERS in the placement path rather than by
    reading the prose: a threshold that appears here is a second policy, and
    the copy nobody reads is the one that goes stale.
    """
    job = _route_job()
    placement = str(job.get("runs-on"))
    for forbidden in ("min_idle", "max_busy", "min_online", "idle", "busy_fraction"):
        assert forbidden not in placement
    body = _step("decide")["run"]
    for forbidden in (
        "min_idle_runners",
        "max_busy_fraction",
        "min_online_fraction",
        "max_lab_load_ratio",
        "min_lab_free_mem_mib",
    ):
        assert forbidden not in body, f"{forbidden} is the node's to declare"


def test_the_shim_carries_no_runner_label_but_the_fork_and_floor_fallbacks() -> None:
    """The only literals allowed are the two fail-safe fallbacks.

    ``ubuntu-latest`` appears in the fork branch (untrusted code never reaches
    self-hosted compute) and in the fail-closed floor (a crashed router must
    still hand the run a schedulable label). Any OTHER label literal here is a
    placement decision that belongs to the node.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    placement = str(_route_job()["runs-on"])
    assert "self-hosted" in placement, "the seam fallback must name the fleet"
    # The fleet literal may appear ONLY inside the seam fallback expression,
    # never as a bare placement or inside the decision step.
    assert "self-hosted" not in _step("decide")["run"]
    assert text.count("omnibase-ci") == 1, (
        "the fleet label belongs in the seam fallback and nowhere else"
    )


def test_the_shim_runs_the_node_rather_than_reimplementing_it() -> None:
    body = _step("decide")["run"]
    assert "scripts/ci/runner_route_decision.py" in body
    # The words a reimplementation would need. Their absence is what makes
    # "this file holds no decision" a checked statement rather than a claim.
    for decision_word in ("fleet_saturated", "capacity_available", "if idle", "busy /"):
        assert decision_word not in body


# --- the pin -----------------------------------------------------------------


def test_the_node_is_pinned_to_an_immutable_full_sha() -> None:
    """A floating ref would change the routing decision under every caller at
    once, with no pull request anywhere recording it."""
    checkout = next(
        step
        for step in _route_job()["steps"]
        if isinstance(step, dict)
        and step.get("with", {}).get("repository") == NODE_REPO
    )
    ref = str(checkout["with"]["ref"])
    assert SHA_RE.match(ref), f"pin must be a full 40-character sha, got {ref!r}"
    assert checkout["with"]["persist-credentials"] is False


@pytest.mark.parametrize("field", ["repository", "ref", "path"])
def test_the_checkout_names_the_node_repo_explicitly(field: str) -> None:
    checkout = next(
        step
        for step in _route_job()["steps"]
        if isinstance(step, dict)
        and step.get("with", {}).get("repository") == NODE_REPO
    )
    assert field in checkout["with"]


# --- fork isolation ----------------------------------------------------------


def test_the_fork_branch_precedes_the_seam_in_the_placement_expression() -> None:
    """INVIOLABLE, and first.

    A fork pull request is untrusted code. It may not reach self-hosted compute
    at any idle level and under any override, so the fork test is evaluated
    before the seam rather than after it.
    """
    placement = str(_route_job()["runs-on"])
    fork_at = placement.index("head.repo.full_name")
    seam_at = placement.index("OMNI_TRUSTED_CI_RUNS_ON_JSON")
    assert fork_at < seam_at
    assert "OMNI_PUBLIC_PR_RUNS_ON_JSON" in placement
    public_at = placement.index("OMNI_PUBLIC_PR_RUNS_ON_JSON")
    assert public_at < seam_at


def test_the_seam_is_read_and_never_written() -> None:
    """Rule 14, single-owner: routing may only ever downgrade from the seam."""
    text = WORKFLOW.read_text(encoding="utf-8")
    for write_verb in ("gh variable set", "actions/variables", "-X PATCH", "-X PUT"):
        assert write_verb not in text


# --- the environment, and the silent degradation it prevents -----------------


def test_the_sync_and_the_run_select_the_same_dependency_groups() -> None:
    """MEASURED, not stylistic. `uv run` includes the dev group by default.

    A run whose flags differ from its sync re-resolves and installs the
    difference, on the critical path, every time. On omninode_infra run
    35048508160 that was 57 extra packages -- numpy, botocore, a source build
    of the project -- to make a decision that needs a typed model and a YAML
    parser: 69 of the route job's 155 seconds, spent inside the step that was
    supposed to just decide, after the step that exists to prepare the
    environment had already finished in 23.

    Nothing reports it. The job is green either way; the cost is simply added
    to every pipeline that calls this workflow.
    """
    body = _step("decide")["run"]
    assert "uv run --frozen --no-dev" in body, (
        "the run must select the same groups as the sync, or it re-resolves"
    )


def test_the_uv_cache_is_off_because_the_runners_are_ephemeral() -> None:
    """A cache that is always written and never read is pure cost.

    Same measured run: the post-job cache SAVE took 34 seconds. Every fleet
    runner is an ephemeral container, so the cache it writes is discarded with
    it -- the save is paid on the critical path of every consuming run and the
    restore never hits.
    """
    setup = next(
        step
        for step in _route_job()["steps"]
        if isinstance(step, dict) and "setup-uv" in str(step.get("uses", ""))
    )
    assert setup["with"]["enable-cache"] is False


def test_the_environment_is_synced_before_the_decision_runs() -> None:
    """THE SILENT DEGRADATION.

    Importing anything in the node's package executes its ``__init__``, which
    pulls the database and broker surfaces, so the decision cannot run without
    that project's environment. Without this step the job raises
    ModuleNotFoundError, falls through its own fail-closed floor, and reports a
    GREEN route job that placed everything hosted. The floor exists precisely so
    a broken router still schedules, which is why nothing else can see this.
    """
    steps = _route_job()["steps"]
    uv_at = next(
        i
        for i, step in enumerate(steps)
        if isinstance(step, dict) and "uv sync" in str(step.get("run", ""))
    )
    decide_at = next(
        i
        for i, step in enumerate(steps)
        if isinstance(step, dict) and step.get("id") == "decide"
    )
    assert uv_at < decide_at
    # Both carry --no-dev, so the run cannot re-resolve what the sync already
    # installed, and a dependency failure is still diagnosed in its own step.
    assert "uv run --frozen --no-dev" in _step("decide")["run"]
    assert "--no-dev" in str(steps[uv_at]["run"])


def test_every_step_that_needs_the_node_runs_inside_its_checkout() -> None:
    """The node is checked out into a subdirectory of the CALLER's workspace.

    A step that forgets the working directory runs against the caller's tree,
    where the module does not exist -- which lands in the floor again, green.
    """
    for step in _route_job()["steps"]:
        if not isinstance(step, dict):
            continue
        run = str(step.get("run", ""))
        if "runner_route_decision.py" in run or "uv sync" in run:
            assert step.get("working-directory") == ".runner-route"


# --- the refusal -------------------------------------------------------------


def test_a_refusal_fails_the_run_and_the_floor_cannot_overwrite_it() -> None:
    """ORDER IS THE MECHANISM.

    Exit 3 is a refusal, not a crash: a private caller whose only allowed
    placement is GitHub-hosted. The node writes its outputs first, so the
    fail-closed floor finds a ``runs_on=`` line already present and is a no-op
    on that path. If the refusal check ran BEFORE the floor the ordering would
    not matter; if the floor could run after it, a forbidden hosted placement
    would be emitted by the very step that exists to make failures safe.
    """
    body = _step("decide")["run"]
    assert "rc=0" in body, "rc must be initialised or set -u makes the check the error"
    assert "|| rc=$?" in body, "a discarded exit status cannot signal a refusal"
    floor_at = body.index("probe_error:module_unavailable")
    refusal_at = body.index('[ "${rc}" = "3" ]')
    assert floor_at < refusal_at
    assert "exit 1" in body


def test_the_refusal_exit_code_matches_the_node() -> None:
    """The workflow tests a literal 3; the node returns a named constant.

    Compared rather than assumed equal, because a renumber on either side
    disarms the check silently and the symptom is a private repository running
    hosted.
    """
    # Resolved from the workspace root rather than this checkout's parent: in a
    # worktree the parent is the ticket directory, not the clone registry, and a
    # test that silently could not find the file would report a skip that reads
    # like a pass.
    candidates = [
        Path(os.environ["OMNI_HOME"]) if os.environ.get("OMNI_HOME") else None,
        REPO_ROOT.parent,
        REPO_ROOT.parents[2] if len(REPO_ROOT.parents) > 2 else None,
    ]
    module = next(
        (
            path
            for root in candidates
            if root is not None
            for path in [root / "omnibase_infra/scripts/ci/runner_route_decision.py"]
            if path.exists()
        ),
        REPO_ROOT / "does-not-exist",
    )
    if not module.exists():  # pragma: no cover - sibling clone not always present
        pytest.skip(
            "omnibase_infra clone not resolvable here, so the constant cannot be "
            "compared; this assertion did NOT run and is not evidence"
        )
    source = module.read_text(encoding="utf-8")
    assert "REFUSED_EXIT_CODE = 3" in source
    assert '[ "${rc}" = "3" ]' in _step("decide")["run"]


def test_the_decision_record_is_uploaded_even_on_a_refusal() -> None:
    """A refused run must still leave something to read.

    The artifact is the evidence surface; the run log is not. An upload gated
    on success would discard exactly the records worth having.
    """
    upload = next(
        step
        for step in _route_job()["steps"]
        if isinstance(step, dict) and "upload-artifact" in str(step.get("uses", ""))
    )
    assert upload.get("if") == "always()"
    assert upload["with"]["path"].startswith(".runner-route/")
