# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-16878: deploy-gate / receipt-honesty / contract-validation must stay enforced.

OMN-16876's enforcement census found three checks that ran on **every** omniclaude
PR and could not block a merge: they were absent from branch protection AND from
``scripts/ci/ci_summary_gate.py``'s ``EXPECTED_EXTERNAL_CONTEXTS``. Per Operating
Rule 5, detection not wired as a pre-merge gate is advisory and gets ignored.

omniclaude enforces an external context on THREE coupled surfaces, and all three
must agree or the hourly ``required-check-manifest-reconcile`` job fails closed:

1. live branch-protection ``required_status_checks`` on ``dev``;
2. ``EXPECTED_EXTERNAL_CONTEXTS`` in the ``CI Summary`` poller, which asserts the
   context independently of branch protection so a silent protection drop is
   still caught (OMN-16000); and
3. a ``mode: REQUIRED`` row in ``.github/required-checks.yaml`` (schema v3).

These tests pin surfaces 2 and 3, and pin the producer-side property that makes
surface 1 safe. Surface 1 itself is live GitHub state and is verified by the
reconcile job, not from here.

The producer property is not incidental. Each of these jobs declares
``needs: occ-preflight``. GitHub's implicit job-level ``if:`` is ``success()``
over ``needs:``, so a failed or cancelled occ-preflight SKIPS the job — and a
skipped job SATISFIES branch protection. Requiring these contexts without
``if: always()`` would have wired in a silent-pass bypass (OMN-15057 vector 5).
``test_producer_jobs_cannot_be_skipped`` is what keeps that from regressing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.ci.ci_summary_gate import (
    EXPECTED_EXTERNAL_CONTEXTS,
    EXTERNAL_GOOD_CONCLUSIONS,
)

REPO_ROOT = Path(__file__).parent.parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
MANIFEST = REPO_ROOT / ".github" / "required-checks.yaml"

# context name -> (workflow file, job id)
NEWLY_ENFORCED: dict[str, tuple[str, str]] = {
    "deploy-gate": ("deploy-gate.yml", "deploy-gate"),
    "receipt-honesty": ("receipt-honesty.yml", "receipt-honesty"),
    "contract-validation": ("contract-validation.yml", "contract-validation"),
}


def _manifest_rows() -> dict[str, dict]:
    data = yaml.safe_load(MANIFEST.read_text())
    return {row["name"]: row for row in data["gates"]}


@pytest.mark.unit
@pytest.mark.parametrize("context", sorted(NEWLY_ENFORCED))
class TestEnforcementWiring:
    """Each context must be load-bearing on every surface this repo can pin."""

    def test_in_expected_external_contexts(self, context: str) -> None:
        """Surface 2: the CI Summary poller asserts the context independently."""
        assert context in EXPECTED_EXTERNAL_CONTEXTS, (
            f"{context!r} dropped out of EXPECTED_EXTERNAL_CONTEXTS. It would go "
            "back to running on every PR while being unable to block one — the "
            "exact House Rule 5 gap OMN-16876 catalogued and OMN-16878 closed."
        )

    def test_manifest_row_is_required(self, context: str) -> None:
        """Surface 3: the v3 manifest reconciled hourly against live protection."""
        row = _manifest_rows().get(context)
        assert row is not None, (
            f"{context!r} has no row in .github/required-checks.yaml. The "
            "reconcile job fails closed in BOTH directions, so a live required "
            "context with no manifest row turns dev red."
        )
        assert row["mode"] == "REQUIRED", (
            f"{context!r} is present but mode={row['mode']!r}. Only REQUIRED "
            "rows are reconciled against live branch protection."
        )
        assert row["skip_semantics"] == "never", (
            f"{context!r} declares skip_semantics={row['skip_semantics']!r}. "
            "These jobs run unconditionally (`if: always()`), so a skip is "
            "anomalous and must never be treated as a legitimate pass."
        )

    def test_producer_job_cannot_be_skipped(self, context: str) -> None:
        """The vector-5 fix: `needs:` without `if: always()` is skip-as-pass.

        A skipped job satisfies GitHub branch protection. Any of these three
        jobs losing `if: always()` while keeping `needs: occ-preflight` would
        silently convert a required gate back into a bypass.
        """
        workflow_file, job_id = NEWLY_ENFORCED[context]
        workflow = yaml.safe_load((WORKFLOWS / workflow_file).read_text())
        job = workflow["jobs"][job_id]

        if not job.get("needs"):
            return  # no needs -> no implicit success() gate -> nothing to prove

        # `if` is a YAML boolean-ish key; PyYAML gives us the string form here
        # because the value is quoted/plain text, but be explicit either way.
        if_expr = str(job.get("if", "")).strip()
        assert if_expr == "always()", (
            f"{workflow_file}:{job_id} has needs={job['needs']!r} but "
            f"if={if_expr!r}. GitHub's implicit job-level `if:` is `success()` "
            "over `needs:`, so a failed/cancelled occ-preflight SKIPS this job "
            "— and a skipped job SATISFIES branch protection. This context is "
            "REQUIRED, so that is a live silent-pass bypass, not just a wedge."
        )


@pytest.mark.unit
def test_skipped_is_not_a_good_external_conclusion() -> None:
    """The CI Summary layer must not accept a skip as a pass either.

    Belt to the branch-protection suspenders: even if a producer job someday
    regains a skip path, the poller's external-context layer fails closed on it.
    """
    assert "skipped" not in EXTERNAL_GOOD_CONCLUSIONS
    assert frozenset({"success"}) == EXTERNAL_GOOD_CONCLUSIONS


@pytest.mark.unit
class TestSkipGuardContextResolution:
    """OMN-16878: a context name carried by two jobs must resolve to the right one.

    ``deploy-gate.yml`` holds omniclaude's own ``deploy-gate`` job (the producer
    of this repo's required context). ``deploy-gate-reusable.yml`` holds a job
    ALSO named ``deploy-gate`` — the canonical cross-repo reusable that
    omnibase_core / omnibase_infra / omnimarket invoke via ``uses:`` to produce
    THEIR ``deploy-gate / deploy-gate`` context. That job's name is load-bearing
    for three other repos and must not be renamed to break the collision.

    Shape-A resolution was first-match-wins over a filename-sorted dict, and
    ``"deploy-gate-reusable.yml" < "deploy-gate.yml"`` bytewise, so the reusable
    won. The guard then reported ``vector-4-no-pr-trigger`` against a
    ``workflow_call``-only workflow: a true statement about the wrong file, and
    — worse — it MASKED the real vector-5 defect in the local job, because the
    local job was never the one being checked.
    """

    def _load(self):
        import sys

        guard_dir = REPO_ROOT / ".github" / "actions" / "required-check-skip-guard"
        sys.path.insert(0, str(guard_dir))
        try:
            from _workflow_model import load_workflows, resolve_context_to_job
        finally:
            sys.path.remove(str(guard_dir))
        return load_workflows(WORKFLOWS), resolve_context_to_job

    def test_both_jobs_really_are_named_deploy_gate(self) -> None:
        """Pin the collision itself, so this test cannot rot into a no-op."""
        local = yaml.safe_load((WORKFLOWS / "deploy-gate.yml").read_text())
        reusable = yaml.safe_load((WORKFLOWS / "deploy-gate-reusable.yml").read_text())
        assert "deploy-gate" in local["jobs"]
        assert "deploy-gate" in reusable["jobs"]
        assert sorted(["deploy-gate-reusable.yml", "deploy-gate.yml"])[0] == (
            "deploy-gate-reusable.yml"
        ), "the reusable no longer sorts first; the collision's shape changed"

    def test_preferred_workflow_wins(self) -> None:
        """With the manifest's `workflow:` supplied, the local job is chosen."""
        workflows, resolve = self._load()
        resolved = resolve(
            "deploy-gate", workflows, preferred_workflow="deploy-gate.yml"
        )
        assert resolved.workflow.path.name == "deploy-gate.yml", (
            "manifest-declared workflow was ignored; the guard would check the "
            "cross-repo reusable instead of omniclaude's own required producer"
        )

    def test_manifest_row_declares_the_disambiguating_workflow(self) -> None:
        """The fix is only load-bearing if the row actually carries the field."""
        row = _manifest_rows()["deploy-gate"]
        assert row.get("workflow") == "deploy-gate.yml"
        assert row.get("job_path") == ["deploy-gate"]


@pytest.mark.unit
def test_manifest_and_poller_do_not_disagree() -> None:
    """Every newly-enforced context is on BOTH pinnable surfaces, or neither.

    Guards the half-migration: adding a manifest row without the poller entry
    (or vice versa) leaves the repo believing a context is enforced on a surface
    that is not actually asserting it.
    """
    rows = _manifest_rows()
    for context in NEWLY_ENFORCED:
        in_manifest = rows.get(context, {}).get("mode") == "REQUIRED"
        in_poller = context in EXPECTED_EXTERNAL_CONTEXTS
        assert in_manifest == in_poller, (
            f"{context!r}: manifest REQUIRED={in_manifest}, "
            f"EXPECTED_EXTERNAL_CONTEXTS={in_poller}. These must move together."
        )
