# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22293: the workflow adds no decision logic -- one node call from a trusted clone, and one ``if:`` on the enforcement step.

The gate-accept step runs the node's ``python -m`` entry from the omnimarket clone that
the "Clone omnimarket" step reads at a trusted revision (a dev tag anchored to its
branch), never from the pull request's checkout, so a pull request can never supply the
code that accepts itself. Its shell holds only that node call and the
``decision=unchanged`` fallbacks for a clone without the node or a node that did not run.

This repository's review step used to fail the job itself on ``degraded_quorum`` and
``infra_error``, which left no step an agent receipt could lift. Those two exits now
belong to the "Enforce hostile-review verdict" step, whose ``run:`` text is pinned by
digest here and whose only condition beyond ``always()`` is ``decision != 'pass_agent'``.
The review step keeps failing the job on ``blocked``, so no receipt can lift a blocking
finding.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pytest

from tests.ci.hostile_review_job import REVIEW_JOB, job, step_named

pytestmark = pytest.mark.unit

#: sha256 of the enforcement step's ``run:`` text as OMN-22293 wrote it.
ENFORCE_RUN_SHA256 = "b31c01b3c08ae2285a3eb6e6536d10bda798c8074b52976eb9d5e4ee7030136d"
ENFORCE_IF = "always() && steps.accept.outputs.decision != 'pass_agent'"
OVERLAY_ID = "agent_review_gate_accept"
ACCEPT_CONTEXTS = {
    "github.repository",
    "github.event.pull_request.number",
    "github.event.pull_request.head.sha",
    "github.workspace",
    "runner.temp",
    "secrets.GITHUB_TOKEN",
}
NODE_MODULE = (
    "omnimarket.nodes.node_agent_review_gate_accept_effect.runtime_gate_accept"
)


def _steps() -> list[dict[str, Any]]:
    return list(job(REVIEW_JOB)["steps"])


def _accept() -> dict[str, Any]:
    found = [s for s in _steps() if s.get("id") == "accept"]
    assert len(found) == 1, "the job must hold exactly one gate-accept step"
    return found[0]


def test_the_accept_step_runs_the_node_from_the_trusted_clone_under_if_always() -> None:
    step = _accept()
    assert set(step) == {"name", "id", "if", "env", "run"}, sorted(step)
    assert step["if"] == "always()"
    run = str(step["run"])
    assert "onex run-node" not in run
    calls = re.findall(rf"python -m {re.escape(NODE_MODULE)}\b", run)
    assert len(calls) == 1, calls
    assert (
        'PYTHONPATH="$ACCEPT_SRC" uv run --no-sync --project '
        '"$GITHUB_WORKSPACE/../omniintelligence" python -m ' + NODE_MODULE
    ) in run
    assert 'ACCEPT_SRC="$GITHUB_WORKSPACE/../omnimarket/src"' in run
    assert "PYTHONPATH" not in run.replace('PYTHONPATH="$ACCEPT_SRC"', "")
    assert "$GITHUB_WORKSPACE/src" not in run
    assert "::notice::" in run, "a clone without the node must skip with a notice"
    assert run.count("decision=unchanged") == 2, "one fallback per skipped path"
    for decided in ("pass_agent", "decision=refuse", "decision=pass"):
        assert decided not in run, f"the step shell decides: {decided}"


def test_the_accept_step_names_only_the_contexts_it_needs() -> None:
    step = _accept()
    run_contexts = set(re.findall(r"\$\{\{\s*(.+?)\s*\}\}", str(step["run"])))
    env_contexts = {
        c
        for value in step["env"].values()
        for c in re.findall(r"\$\{\{\s*(.+?)\s*\}\}", str(value))
    }
    assert run_contexts | env_contexts == ACCEPT_CONTEXTS, sorted(
        run_contexts | env_contexts
    )
    assert step["env"]["GITHUB_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"


def test_the_ci_overlay_that_holds_the_nodes_deployment_facts_is_fetched_and_rooted() -> (
    None
):
    roots = str(_accept()["env"]["ONEX_SKILL_OVERLAY_ROOTS"])
    assert roots == "${{ github.workspace }}/../ci-overlay/config/onex/overlays"
    fetch = step_named(REVIEW_JOB, "Fetch the CI overlay")
    sparse = [
        line.strip() for line in str(fetch["with"]["sparse-checkout"]).splitlines()
    ]
    assert f"config/onex/overlays/{OVERLAY_ID}" in sparse, sparse
    assert "config/onex/overlays/node_review_voters_overlay_compute" in sparse, sparse


def test_the_accept_step_sits_between_the_review_and_the_enforcement_step() -> None:
    names = [str(s.get("name", "")) for s in _steps()]
    clone = names.index(step_named(REVIEW_JOB, "Clone omnimarket")["name"])
    review = names.index(step_named(REVIEW_JOB, "Run adversarial review")["name"])
    accept = names.index(str(_accept()["name"]))
    enforce = names.index(
        step_named(REVIEW_JOB, "Enforce hostile-review verdict")["name"]
    )
    comment = names.index(step_named(REVIEW_JOB, "Post review summary")["name"])
    assert clone < review < accept < enforce < comment


def test_the_enforcement_step_changes_only_its_condition() -> None:
    step = step_named(REVIEW_JOB, "Enforce hostile-review verdict")
    assert set(step) == {"name", "if", "run"}, sorted(step)
    assert step["if"] == ENFORCE_IF
    digest = hashlib.sha256(str(step["run"]).encode()).hexdigest()
    assert digest == ENFORCE_RUN_SHA256, "the run: text of the enforcement step moved"


def test_only_a_blocked_verdict_fails_the_review_step_by_itself() -> None:
    run = str(step_named(REVIEW_JOB, "Run adversarial review")["run"])
    exits = re.findall(r"^\s*exit 1\s*$", run, flags=re.MULTILINE)
    assert len(exits) == 1, "the review step may fail the job in one place only"
    assert re.search(r'if \[ "\$VERDICT" = "blocked" \]; then\n\s+exit 1', run), (
        "that one place is a blocked verdict"
    )
    assert 'echo "verdict=degraded_quorum"' in run
    assert "verdict=infra_error" in run
    enforce = str(step_named(REVIEW_JOB, "Enforce hostile-review verdict")["run"])
    assert '"$VERDICT" != "passed"' in enforce and '"$VERDICT" != "degraded"' in enforce
