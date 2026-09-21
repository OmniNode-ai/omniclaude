# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18530 AC8: the hook inventory gate cannot be skipped into silence.

OMN-18530 shipped the ``UNDECLARED_GATE_SCRIPT`` finding kind -- a gate-shaped
hook script declared in neither the expected nor the disabled list is now
reported rather than invisible -- and declared the 34 scripts it matched. That
half is merged at ``c124c41ea``. It also proved, in
``tests/hooks/test_hook_inventory_undeclared_gate.py``, that a red run of this
gate blocks a merge: ``Hook Inventory Gate`` is not a branch-protection context,
but CI Summary's layer-5 default-deny sweep walks every external check-run on
the head and a name in neither registry must conclude ``success``.

**That proof has a precondition the gate did not meet.** A default-deny sweep
reasons about check-runs that EXIST. This workflow carried a ``paths:`` filter
naming six hook paths, so on any pull request touching none of them the job
never ran, no check-run was ever written, and the sweep had nothing to deny.
The gate was blocking on the pull requests that already touch hooks and absent
on every other one -- and "absent" is indistinguishable from "passed" to
everything downstream. That is skip-vector 1, and it is the same failure this
gate exists to detect, one level up: a refusal mechanism that reads as green
because nothing ran it.

The filter was also wrong on its own terms. The inventory gate enforces the
review dates on declared disables, and a review date expires with the calendar
rather than with a commit. The change that must re-run this gate is a change to
nothing at all, which no path filter can ever express. That matters immediately
rather than in principle: the 34 placeholder declarations OMN-18530 landed all
carry review dates, and OMN-18531 is the ticket that has to replace them before
those dates pass.

Skip-vector 5 is the second half. ``needs: occ-preflight`` with no ``if:``
means the implicit job condition is ``success()`` over ``needs:``, so a failed
or cancelled preflight skips the gate. A skipped job is not a refusal, and on
the branch-protection surface a skip positively SATISFIES a requirement -- so
closing vector 1 without closing vector 5 would leave a one-step bypass in
place for anyone who could redden the preflight.

**What this lane could not do.** AC8's falsifier names two surfaces: the
repository's required contexts and its summary-gate tuple. The gate is in
neither, and neither is reachable from here. Adding the tuple entry is
mechanically bound to adding the protection row -- ``TestExternalContextComple
teness::test_no_classified_entry_is_a_phantom`` fails any layer-4 name absent
from the live required-contexts snapshot, on purpose, so the tuple cannot carry
a name that gates nothing. Branch protection is a required-context mutation and
is outside a lane's authority, so it is requested in the pull request rather
than taken. With the two vectors below closed the gate runs on every pull
request and a red run fails a required ``CI Summary`` through layer 5; the
protection row adds a second, independent assertion on top of that.

Every predicate here is exercised against a known-positive and a known-negative
before it is trusted, so an assertion that can only ever return True cannot pass
for the wrong reason. That is the two-control rule OMN-18531 applies to a
register verdict, applied to the assertions themselves.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ci.ci_summary_gate import (  # noqa: E402
    EXPECTED_EXTERNAL_CONTEXTS,
    EXTERNAL_SWEEP_EXCLUSIONS,
    SWEEP_GOOD_CONCLUSIONS,
)

WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: The gate under test, and the job id inside its workflow file.
GATE_CONTEXT = "Hook Inventory Gate"
GATE_WORKFLOW = "hook-inventory-gate.yml"
GATE_JOB_ID = "hook-inventory-gate"

#: Known-positive control. OMN-17204 brought this gate to exactly the trigger
#: shape AC8 needs -- no ``paths:`` filter, ``if: always()`` -- so every
#: predicate here must read True against it. A predicate that cannot return
#: True for the one file in the tree that satisfies it is broken, and its
#: verdict about the gate under test would mean nothing.
CONTROL_POSITIVE_WORKFLOW = "hook-edge-lane-gate.yml"
CONTROL_POSITIVE_JOB_ID = "hook-edge-lane-gate"


def _load_workflow(filename: str) -> dict[str, Any]:
    """Parse a workflow file, normalising the YAML 1.1 ``on:`` -> ``True`` key.

    PyYAML resolves the bare key ``on`` to the boolean ``True`` under the YAML
    1.1 rules GitHub Actions files are written against, so ``wf["on"]`` raises
    ``KeyError`` on every workflow in the tree. A trigger assertion that errors
    instead of failing is not a measurement of anything.
    """
    raw = yaml.safe_load((WORKFLOWS / filename).read_text(encoding="utf-8"))
    assert isinstance(raw, dict), f"{filename} did not parse as a mapping"
    if True in raw and "on" not in raw:
        raw["on"] = raw.pop(True)
    return raw


def _trigger_paths_filters(workflow: dict[str, Any]) -> dict[str, list[str]]:
    """Return every ``paths:``/``paths-ignore:`` filter, keyed by trigger name.

    An empty mapping means the workflow runs on every event of its declared
    kinds, which is the property skip-vector 1 requires.
    """
    found: dict[str, list[str]] = {}
    triggers = workflow.get("on")
    if not isinstance(triggers, dict):
        return found
    for trigger_name, spec in triggers.items():
        if not isinstance(spec, dict):
            continue
        for key in ("paths", "paths-ignore"):
            if key in spec:
                found[f"{trigger_name}.{key}"] = list(spec[key] or [])
    return found


def _job_if_condition(workflow: dict[str, Any], job_id: str) -> str | None:
    """Return a job's ``if:`` expression, or ``None`` when it declares none."""
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "workflow declares no jobs mapping"
    assert job_id in jobs, f"job id {job_id!r} not found; jobs={sorted(jobs)}"
    condition = jobs[job_id].get("if")
    return None if condition is None else str(condition).strip()


# --------------------------------------------------------------------------
# Controls. These run first, because every assertion in the RED block below is
# only as good as the predicate underneath it.
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_control_positive_predicates_read_true_on_the_settled_shape() -> None:
    """Known-positive: the predicates return True for a gate already correct."""
    workflow = _load_workflow(CONTROL_POSITIVE_WORKFLOW)

    assert _trigger_paths_filters(workflow) == {}, (
        "known-positive control regressed: hook-edge-lane-gate.yml has grown a "
        "paths filter, which would re-open skip-vector 1 on a REQUIRED context"
    )
    assert _job_if_condition(workflow, CONTROL_POSITIVE_JOB_ID) == "always()", (
        "known-positive control regressed: hook-edge-lane-gate's job lost "
        "`if: always()`, re-opening skip-vector 5"
    )


@pytest.mark.unit
def test_control_negative_predicates_read_false_on_a_filtered_workflow() -> None:
    """Known-negative: the predicates return False for the shape AC8 rejects.

    Synthesised rather than borrowed from the tree, so the control keeps
    discriminating after the tree is repaired. A predicate that only ever
    returned True would pass the RED block below for the wrong reason.
    """
    source = """
name: Synthetic Advisory Job
on:
  pull_request:
    branches: [dev]
    paths:
      - 'some/narrow/path/**'
jobs:
  occ-preflight:
    uses: org/repo/.github/workflows/occ-preflight.yml@main
  synthetic:
    needs: occ-preflight
    name: Synthetic Advisory Job
    steps:
      - run: 'true'
"""
    raw = yaml.safe_load(source)
    if True in raw and "on" not in raw:
        raw["on"] = raw.pop(True)

    assert _trigger_paths_filters(raw) == {
        "pull_request.paths": ["some/narrow/path/**"]
    }, "negative control: a paths filter must be detected, not ignored"
    assert _job_if_condition(raw, "synthetic") is None, (
        "negative control: an absent `if:` must read as None -- that is "
        "skip-vector 5 -- rather than as a passing condition"
    )


# --------------------------------------------------------------------------
# RED block. Each of these fails against origin/dev at c124c41ea.
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_gate_has_no_paths_filter_so_it_reports_on_every_pull_request() -> None:
    """AC8 / skip-vector 1: a sweep can only deny a check-run that exists.

    With a path filter, a pull request touching no hook file produces no
    check-run for this gate at all, and the default-deny sweep that makes it
    blocking has nothing to read. The review dates on the 34 placeholder
    declarations expire with the calendar, so the change that must re-run this
    gate is a change to no file -- which no path filter can express.
    """
    filters = _trigger_paths_filters(_load_workflow(GATE_WORKFLOW))
    assert filters == {}, (
        f"{GATE_WORKFLOW} still filters by path ({sorted(filters)}); on a pull "
        "request touching none of those paths the gate never runs, writes no "
        "check-run, and its absence is indistinguishable from a pass"
    )


@pytest.mark.unit
def test_gate_job_runs_even_when_its_preflight_fails() -> None:
    """AC8 / skip-vector 5: ``needs:`` without ``if:`` is a one-step bypass.

    The implicit job condition is ``success()`` over ``needs:``, so a failed or
    cancelled ``occ-preflight`` skips this job -- and a skip is not a refusal.
    Closing vector 1 without this would leave the gate switchable off by
    anyone who could redden the preflight.
    """
    condition = _job_if_condition(_load_workflow(GATE_WORKFLOW), GATE_JOB_ID)
    assert condition == "always()", (
        f"{GATE_WORKFLOW} job {GATE_JOB_ID!r} declares `if: {condition}`; with "
        "`needs: occ-preflight` the implicit condition is success(), so a red "
        "preflight skips the gate rather than failing it"
    )


@pytest.mark.unit
def test_gate_runs_on_pull_requests_into_dev() -> None:
    """The branch the umbrella it blocks through is posted on."""
    triggers = _load_workflow(GATE_WORKFLOW).get("on")
    assert isinstance(triggers, dict) and "pull_request" in triggers
    branches = triggers["pull_request"].get("branches") or []
    assert "dev" in branches, (
        f"{GATE_WORKFLOW} does not run on pull requests into dev, where every "
        "product change in this repository lands"
    )


@pytest.mark.unit
def test_gate_blocks_through_exactly_one_of_the_two_sweep_layers() -> None:
    """AC8's standing invariant, written so either resolution keeps it true.

    Two routes make this context blocking. Layer 4 requires a named context to
    be PRESENT and ``success``; layer 5 default-deny requires any check-run
    outside both registries to be ``success``. Today only layer 5 applies,
    because a layer-4 name must also be a branch-protection context and that
    row is a required-context mutation this lane cannot make.

    This asserts the disjunction rather than either branch, so adding the
    protection row and the tuple entry later strengthens the gate without
    turning this test red -- while putting the gate in the exclusion registry,
    the one move that would silently return it to advisory, fails here.
    """
    in_layer_4 = GATE_CONTEXT in EXPECTED_EXTERNAL_CONTEXTS
    excluded = GATE_CONTEXT in EXTERNAL_SWEEP_EXCLUSIONS

    assert not excluded, (
        f"{GATE_CONTEXT!r} is in EXTERNAL_SWEEP_EXCLUSIONS, which exempts it "
        "from the default-deny sweep and returns it to advisory -- the exact "
        "move OMN-18530 exists to prevent"
    )
    assert in_layer_4 or frozenset({"success"}) == SWEEP_GOOD_CONCLUSIONS, (
        f"{GATE_CONTEXT!r} is not a layer-4 context, so it blocks only through "
        "the default-deny sweep -- and that sweep now tolerates a non-success "
        "conclusion, leaving the gate enforcing nothing"
    )
