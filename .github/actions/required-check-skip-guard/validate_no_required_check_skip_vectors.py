#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Required-Check Skip-Vector Guard (OMN-14854; vector 5 added OMN-15057;
# vector 6 added OMN-15304) — PR-time validator.
#
# Fails closed on any of the six skip vectors enumerated in the design spec
# (docs/design or ticket OMN-14854; grounded against
# `gh api repos/OmniNode-ai/omniclaude/branches/dev/protection/required_status_checks`,
# 58 contexts, fetched 2026-07-20):
#
#   1. A path-scoped `pull_request` / `pull_request_target` / `merge_group`
#      trigger on the workflow producing (or calling) a REQUIRED context —
#      a PR touching only excluded paths never runs the job, wedging the
#      required check PENDING forever.
#   2. A job-level `if:` on the job that IS the required context (Shape A)
#      that is not provably true for every PR-reachable event — a skipped
#      job counts as "passing" under GitHub branch protection, so this is a
#      silent bypass, not merely a wedge.
#   3. A caller job (`uses:` job) gated by a conditional `if:` that is not
#      provably true — when it evaluates false the reusable workflow never
#      runs, so the composed context is never even created (permanent
#      PENDING, worse than vector 2).
#   4. A required context's producing/caller workflow has no
#      pull_request/pull_request_target/merge_group trigger at all.
#   5. (OMN-15057) A producing/caller job with a non-empty `needs:` and no
#      job-level `if:` that provably runs regardless of the needs result
#      (e.g. `if: always()`). GitHub's *implicit* job-level `if:` is
#      `success()` evaluated over `needs:`, not an unconditional true — an
#      upstream failure/cancellation SKIPS the job, and a skipped job
#      satisfies GitHub branch protection. Live proof: omnimarket#1880 — 18
#      required gates (including this guard's own required check) went
#      `skipped` when the same-file `needs: occ-preflight` poller job failed
#      on first run, satisfying branch protection without ever executing.
#   6. (OMN-15304) RESULT TRIAGE. Vector 5 asks whether the job can be
#      SKIPPED; vector 6 asks the layer-down question: when the job DOES run,
#      does it fail closed on every non-`success` value of the
#      `needs.<job>.result` it reads? The value space is
#      success/failure/cancelled/skipped; a gate blocking on only `failure`
#      renders its required context GREEN on `cancelled` and `skipped`, and
#      `if: always()` — the construct that SATISFIES vector 5 — is precisely
#      what guarantees that fail-open path is reached. Live proof:
#      omnimarket#1920, run 30298837182 — `hostile-review` job 90176999483
#      CANCELLED 04:13:14Z, `Hostile Review Gate` job 90177661758 SUCCESS
#      04:13:21Z, seven seconds later, with no adversarial verdict in
#      existence. Fixed for that one workflow in omnimarket#1926 (OMN-15296);
#      this vector hoists that test into a fleet-wide rule. Fail-closed by
#      construction: a triage shape the analyzer cannot interpret is a
#      FINDING, not a pass.
#
# KNOWN LIMITATION — base-branch retarget (OMN-15304, the "stale green"
# mirror). A `pull_request` trigger's default type list is [opened,
# synchronize, reopened]; a base-branch RETARGET fires `edited`, which is in
# neither the default list nor most explicit ones. A required check whose
# verdict depends on `github.base_ref` therefore does NOT re-evaluate when the
# PR's target branch changes: a PR opened against `dev` and later retargeted
# to `main` keeps its stale GREEN. Observed on onex_change_control's
# `main-target-guard` (OCC#5244, in the stale-RED direction). This validator
# does NOT detect that class today. It is the same family (a required check
# whose verdict does not track the state it claims to govern) but a different
# shape — trigger coverage, not result triage — and detecting it soundly needs
# a model of which expressions are base-ref-dependent plus a per-workflow
# judgement on whether adding `edited` is safe. Tracked separately; do not
# read a PASS from this validator as coverage of it.
#
# Runs identically under pre-commit (local) and CI (the reusable workflow) —
# same script, same manifest, same verdict. Enforcement, not detection
# (CLAUDE.md Rule #5).
#
# Usage:
#   python validate_no_required_check_skip_vectors.py \
#       --manifest .github/required-checks.yaml \
#       --workflows-dir .github/workflows

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from _workflow_model import (  # noqa: E402
    ALWAYS_TRUE_FOR_PR,
    PR_REACHABLE_EVENTS,
    TRIAGE_ABSENT,
    TRIAGE_FAIL_OPEN,
    TRIAGE_HARDENED,
    ParsedJob,
    ParsedWorkflow,
    ResolvedJob,
    UnresolvedContext,
    analyze_result_triage,
    classify,
    load_workflows,
    resolve_context_to_job,
)

# A `result_triage: waived` row must cite a tracking ticket, exactly like the
# `skip_semantics: neutral_ok` hatch — free-text "we reviewed it" waives nothing.
_TICKET_REF_RE = re.compile(r"\bOMN-\d+\b")


@dataclass
class Finding:
    context: str
    vector: str
    message: str

    def render(self) -> str:
        return f"[{self.vector}] required context '{self.context}': {self.message}"


@dataclass
class Observation:
    """Non-failing record (OMN-15304 scope item 4).

    Where a required aggregator's fail-closed behaviour is currently backstopped
    by a SIBLING required context reporting the same upstream job's conclusion,
    that dependency is defence-in-depth by accident: nothing in the workflow or
    the manifest records it, so dropping/renaming the sibling silently converts
    the aggregator into a one-action bypass. Emitting it makes it legible.
    """

    context: str
    message: str

    def render(self) -> str:
        return f"[sibling-dependency] required context '{self.context}': {self.message}"


def _declared_events(workflow) -> tuple[str, ...]:
    return tuple(e for e in PR_REACHABLE_EVENTS if e in workflow.on_block)


def _check_path_filters(context: str, workflow, label: str) -> list[Finding]:
    findings: list[Finding] = []
    for evt in workflow.path_filtered_pr_events():
        severity = (
            "vector-1-pull_request_target-paths"
            if evt == "pull_request_target"
            else (
                "vector-1-merge_group-paths"
                if evt == "merge_group"
                else "vector-1-paths"
            )
        )
        findings.append(
            Finding(
                context=context,
                vector=severity,
                message=(
                    f"{label} ({workflow.path.name}) has a `paths`/`paths-ignore` filter "
                    f"on its `{evt}` trigger. A PR touching only excluded paths never runs "
                    "this job, so the required check goes PENDING forever (or is silently "
                    "absent depending on branch-protection strict mode)."
                    + (
                        " pull_request_target path filters are also a privilege-escalation "
                        "vector."
                        if evt == "pull_request_target"
                        else ""
                    )
                    + (
                        " A merge_group path filter wedges the whole queue, not just one PR."
                        if evt == "merge_group"
                        else ""
                    )
                ),
            )
        )
    return findings


def _check_job_if(
    context: str,
    workflow,
    job,
    label: str,
    vector: str,
    *,
    skip_semantics: str = "never",
    rationale: str = "",
) -> list[Finding]:
    verdict = classify(job.if_expr, _declared_events(workflow))
    if verdict == ALWAYS_TRUE_FOR_PR:
        return []

    # skip_semantics: neutral_ok — the only sanctioned escape hatch (design
    # spec §3a). It suppresses vector-2/vector-3 (conditional `if:`) findings
    # ONLY — it never suppresses vector-1 (path filter) or vector-4 (missing
    # trigger), which are unconditional wedges/silence, not a documented,
    # reviewed exception. A rationale citing a tracking ticket is mandatory;
    # an unratified `neutral_ok` (no ticket cited) is treated as `never`.
    if skip_semantics == "neutral_ok" and rationale.strip():
        return []

    return [
        Finding(
            context=context,
            vector=vector,
            message=(
                f"{label} '{job.job_id}' in {workflow.path.name} has `if: {job.if_expr}` "
                "that can evaluate false on an ordinary same-repo PR/merge_group event. "
                + (
                    "A skipped job satisfies GitHub branch protection (skipped counts as "
                    "passing) — this is a live silent-pass bypass, not merely a wedge."
                    if vector == "vector-2-ungated-job-if"
                    else "When the caller job is skipped, the reusable workflow never "
                    "starts, so the composed required context is never created at all — "
                    "the PR is PENDING forever, it does not pass."
                )
            ),
        )
    ]


def _check_needs_cascade(
    context: str,
    workflow,
    job,
    label: str,
    vector: str,
    *,
    skip_semantics: str = "never",
    rationale: str = "",
) -> list[Finding]:
    """Vector 5 (OMN-15057): a producing/caller job with a non-empty
    `needs:` whose job-level `if:` does not provably run regardless of the
    needs result. Deliberately orthogonal to `_check_job_if` (vector 2/3),
    which only inspects `if:` and treats an absent `if:` as always-safe —
    correct for a needs-less job, silently wrong for one with `needs:`,
    since GitHub's implicit job-level `if:` is `success()` over `needs:`.
    """
    if not job.needs:
        return []

    if job.if_expr is not None:
        verdict = classify(job.if_expr, _declared_events(workflow))
        if verdict == ALWAYS_TRUE_FOR_PR:
            return []

    if skip_semantics == "neutral_ok" and rationale.strip():
        return []

    return [
        Finding(
            context=context,
            vector=vector,
            message=(
                f"{label} '{job.job_id}' in {workflow.path.name} has "
                f"`needs: {list(job.needs)}` with no `if:` that provably runs "
                "regardless of the needs result (e.g. `if: always()`). "
                "GitHub's implicit job-level `if:` is `success()` evaluated "
                "over `needs:` — a failed/cancelled/skipped upstream "
                "dependency SKIPS this job, and a skipped job satisfies "
                "GitHub branch protection (skipped counts as passing). This "
                "is a live silent-pass bypass, not merely a wedge."
            ),
        )
    ]


def _check_result_triage(
    context: str,
    workflow: ParsedWorkflow,
    job: ParsedJob,
    label: str,
    *,
    result_triage: str = "enforced",
    rationale: str = "",
) -> list[Finding]:
    """Vector 6 (OMN-15304): result-triage fail-open.

    Vector 5 asks whether the job can be SKIPPED. This asks the layer-down
    question: when it DOES run, does it fail closed on every non-`success`
    value of the `needs.<job>.result` it consumes? `needs.<job>.result` has
    four values; a gate blocking on only some renders its required context
    green for the rest, and `if: always()` — the construct that satisfies
    vector 5 — is exactly what guarantees the fail-open path is reached.

    Fail-closed by construction: a triage shape the analyzer cannot interpret
    is a finding, not a pass (ticket scope item 2).
    """
    verdict = analyze_result_triage(job)
    if verdict.status in (TRIAGE_ABSENT, TRIAGE_HARDENED):
        return []

    # Sanctioned hatch, same shape as `skip_semantics: neutral_ok`: an explicit
    # manifest opt-out that must cite a tracking ticket. An unratified waiver
    # (no OMN-xxxxx in the rationale) is treated as enforced.
    if result_triage == "waived" and _TICKET_REF_RE.search(rationale or ""):
        return []

    vector = (
        "vector-6-result-triage-fail-open"
        if verdict.status == TRIAGE_FAIL_OPEN
        else "vector-6-result-triage-unverifiable"
    )
    consumed = ", ".join(verdict.consumed_jobs) or "an upstream result token"
    return [
        Finding(
            context=context,
            vector=vector,
            message=(
                f"{label} '{job.job_id}' in {workflow.path.name} reads the result of "
                f"[{consumed}] and does not provably fail closed on every non-`success` "
                f"value: {verdict.detail}. `needs.<job>.result` is one of "
                "success/failure/cancelled/skipped — anything that is not `success` is "
                "the ABSENCE of a verdict, and a required context that goes green on it "
                "is a silent bypass (omnimarket#1920 run 30298837182: reviewer cancelled "
                "04:13:14Z, gate SUCCESS 04:13:21Z). Fix with explicit four-way triage "
                "plus a default-deny catch-all (the omnimarket#1926 shape), or register "
                "`result_triage: waived` with a cited ticket in .github/required-checks.yaml."
            ),
        )
    ]


def _observe_sibling_dependency(
    context: str,
    job: ParsedJob,
    workflow: ParsedWorkflow,
    required_context_names: set[str],
) -> list[Observation]:
    verdict = analyze_result_triage(job)
    if verdict.status in (TRIAGE_ABSENT, TRIAGE_HARDENED):
        return []
    siblings = []
    for needed_id in verdict.consumed_jobs:
        needed = workflow.jobs.get(needed_id)
        if needed is not None and needed.name in required_context_names:
            siblings.append(f"{needed_id} -> '{needed.name}'")
    if not siblings:
        return []
    return [
        Observation(
            context=context,
            message=(
                f"job '{job.job_id}' does not fail closed on its own, but the upstream "
                f"job(s) it aggregates are INDEPENDENTLY required contexts ({'; '.join(siblings)}). "
                "That is defence-in-depth by accident: nothing in the workflow or the "
                "manifest records the dependency, so dropping or renaming the sibling "
                "context converts this aggregator into a one-action bypass (OMN-15304 §4)."
            ),
        )
    ]


def validate_gate(
    context: str,
    gate: dict,
    workflows: dict,
    required_context_names: set[str] | None = None,
    observations: list[Observation] | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    required_context_names = required_context_names or set()
    result_triage = gate.get("result_triage", "enforced")
    producer_kind = gate.get("producer_kind", "local")
    skip_semantics = gate.get("skip_semantics", "never")
    rationale = gate.get("rationale", "")

    try:
        resolved: ResolvedJob = resolve_context_to_job(context, workflows)
    except UnresolvedContext:
        if producer_kind == "local":
            findings.append(
                Finding(
                    context=context,
                    vector="vector-unresolved",
                    message=(
                        "does not resolve to any job in .github/workflows/ — manifest "
                        "drift or a renamed job. Fail-closed per design spec §1."
                    ),
                )
            )
        return findings

    if resolved.cross_repo_ref is not None:
        # Only the local caller side is checkable from this repo.
        assert resolved.caller_job_id is not None  # noqa: S101 - invariant of resolve_context_to_job
        caller_wf = resolved.workflow
        caller_job = caller_wf.jobs[resolved.caller_job_id]
        findings.extend(
            _check_path_filters(
                context, caller_wf, "producing workflow (cross-repo caller)"
            )
        )
        findings.extend(
            _check_job_if(
                context,
                caller_wf,
                caller_job,
                "caller job",
                "vector-3-ungated-caller-if",
                skip_semantics=skip_semantics,
                rationale=rationale,
            )
        )
        findings.extend(
            _check_needs_cascade(
                context,
                caller_wf,
                caller_job,
                "caller job",
                "vector-5-ungated-needs-cascade",
                skip_semantics=skip_semantics,
                rationale=rationale,
            )
        )
        findings.extend(
            _check_result_triage(
                context,
                caller_wf,
                caller_job,
                "caller job",
                result_triage=result_triage,
                rationale=rationale,
            )
        )
        if observations is not None:
            observations.extend(
                _observe_sibling_dependency(
                    context, caller_job, caller_wf, required_context_names
                )
            )
        if not caller_wf.triggers_on_pr_or_merge_group():
            findings.append(
                Finding(
                    context=context,
                    vector="vector-4-no-pr-trigger",
                    message=(
                        f"caller workflow {caller_wf.path.name} has no pull_request/"
                        "merge_group trigger — the cross-repo call can never fire on a PR."
                    ),
                )
            )
        return findings

    if not resolved.is_nested:
        wf = resolved.workflow
        job = wf.jobs[resolved.job_id]
        findings.extend(_check_path_filters(context, wf, "producing workflow"))
        findings.extend(
            _check_job_if(
                context,
                wf,
                job,
                "producing job",
                "vector-2-ungated-job-if",
                skip_semantics=skip_semantics,
                rationale=rationale,
            )
        )
        findings.extend(
            _check_needs_cascade(
                context,
                wf,
                job,
                "producing job",
                "vector-5-ungated-needs-cascade",
                skip_semantics=skip_semantics,
                rationale=rationale,
            )
        )
        findings.extend(
            _check_result_triage(
                context,
                wf,
                job,
                "producing job",
                result_triage=result_triage,
                rationale=rationale,
            )
        )
        if observations is not None:
            observations.extend(
                _observe_sibling_dependency(context, job, wf, required_context_names)
            )
        if not wf.triggers_on_pr_or_merge_group():
            findings.append(
                Finding(
                    context=context,
                    vector="vector-4-no-pr-trigger",
                    message=(
                        f"{wf.path.name} has no pull_request/pull_request_target/"
                        "merge_group trigger in its `on:` block — it can never fire on a "
                        "PR, so branch protection can never see it satisfied."
                    ),
                )
            )
        return findings

    caller_wf = resolved.workflow
    caller_job = caller_wf.jobs[resolved.job_id]
    findings.extend(_check_path_filters(context, caller_wf, "caller workflow"))
    findings.extend(
        _check_job_if(
            context,
            caller_wf,
            caller_job,
            "caller job",
            "vector-3-ungated-caller-if",
            skip_semantics=skip_semantics,
            rationale=rationale,
        )
    )
    findings.extend(
        _check_needs_cascade(
            context,
            caller_wf,
            caller_job,
            "caller job",
            "vector-5-ungated-needs-cascade",
            skip_semantics=skip_semantics,
            rationale=rationale,
        )
    )
    findings.extend(
        _check_result_triage(
            context,
            caller_wf,
            caller_job,
            "caller job",
            result_triage=result_triage,
            rationale=rationale,
        )
    )
    if observations is not None:
        observations.extend(
            _observe_sibling_dependency(
                context, caller_job, caller_wf, required_context_names
            )
        )
    # The nested reusable job is the one that actually RENDERS the composed
    # context, so its own result triage is in scope too (the caller job is a
    # `uses:` job and has no steps of its own).
    if resolved.nested_workflow is not None and resolved.nested_job_id is not None:
        nested_wf = resolved.nested_workflow
        nested_job = nested_wf.jobs[resolved.nested_job_id]
        findings.extend(
            _check_result_triage(
                context,
                nested_wf,
                nested_job,
                "reusable job",
                result_triage=result_triage,
                rationale=rationale,
            )
        )
        if observations is not None:
            observations.extend(
                _observe_sibling_dependency(
                    context, nested_job, nested_wf, required_context_names
                )
            )
    if not caller_wf.triggers_on_pr_or_merge_group():
        findings.append(
            Finding(
                context=context,
                vector="vector-4-no-pr-trigger",
                message=(
                    f"{caller_wf.path.name} (caller) has no pull_request/merge_group "
                    "trigger — the composed context can never be created."
                ),
            )
        )
    return findings


def run(
    manifest_path: Path,
    workflows_dir: Path,
    observations: list[Observation] | None = None,
) -> list[Finding]:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    workflows = load_workflows(workflows_dir)

    required_gates = [
        g for g in manifest.get("gates", []) if g.get("mode") == "REQUIRED"
    ]
    required_context_names = {str(g["name"]) for g in required_gates}

    findings: list[Finding] = []
    for gate in required_gates:
        context = gate["name"]
        findings.extend(
            validate_gate(
                context,
                gate,
                workflows,
                required_context_names=required_context_names,
                observations=observations,
            )
        )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--workflows-dir", required=True, type=Path)
    args = parser.parse_args()

    observations: list[Observation] = []
    findings = run(args.manifest, args.workflows_dir, observations=observations)

    if observations:
        print(f"OBSERVATIONS ({len(observations)}, non-blocking):\n")
        for o in observations:
            print(f"  - {o.render()}")
        print()

    if findings:
        print(f"FAIL: {len(findings)} required-check skip vector(s) found:\n")
        for f in findings:
            print(f"  - {f.render()}")
        print(
            "\nFix: remove the path filter / job-level if: for these required checks, "
            "make the result triage fail closed on every non-`success` value, "
            "or register an explicit skip_semantics / result_triage contract in "
            ".github/required-checks.yaml with a cited ticket."
        )
        return 1

    print("PASS: no required-check skip vectors found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
