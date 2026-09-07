#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Daily drift audit for the public-repo hygiene gate rollout (OMN-18016).

The gate itself (OMN-18014) runs on a pull request. That leaves three ways for
the rollout to decay silently, and this audit is the only thing that sees any
of them:

1. **A new public repository lands in the org without the gate.** Nothing in
   the PR path can notice a repository that has no PRs yet. ``omnibot`` and
   ``omnibase`` are the standing proof that a new public repo does not
   currently get a gate, a LICENSE, a SECURITY.md or a README at creation.
2. **A required status check is removed.** Branch protection is mutable by
   anyone with admin, and a context silently dropped from
   ``required_status_checks`` leaves a gate that still runs and no longer
   blocks. Worse on two repos: ``omnibase_infra`` and ``omnimarket`` assert
   external contexts through a CI-summary umbrella instead, so a context
   missing from that constant tuple is unenforced with NO branch-protection
   signal that it is missing.
3. **A public branch is pushed with no PR.** The gate runs on the pushed ref
   of a pull request; a branch that never opens one is unreviewed public
   surface. RSD carries 13 such branches today.

## Read-only, and it says so

This audit mutates nothing. It reads repository visibility, branch protection,
workflow file presence and branch/PR listings, and prints findings. Flipping a
setting it reports is a separate, gated decision (prevention plan section 7.2:
a lane may write the PR that proposes a required check; it does not flip the
setting).

## An empty result is not evidence of absence

Every listing here checks its own exit status and fails LOUD on an error
rather than treating a failed call as zero rows. That is not defensive
programming, it is the specific failure this fleet has already paid for: four
consecutive confident "zero failures" readings during the trusted-CI re-flip
canary were an errored sweep whose stderr had been discarded, and re-running
it without the suppression found 30 real rows. ``--self-test`` is the positive
control: it asserts the audit reports a finding against a repository known to
lack the gate, so a clean run is a real clean run.

## Exit codes

0  no drift (or ``--report-only``)
1  drift found
2  the audit could not run — a failed API call, never a silent zero
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass

OWNER = "OmniNode-ai"
GATE_WORKFLOW = ".github/workflows/public-repo-hygiene.yml"
GATE_CONTEXT = "public-repo-hygiene / public-repo-hygiene"
CONFIG_FILE = ".public-repo-hygiene.yaml"

# Repos that gate behind a single CI-summary umbrella rather than through
# required_status_checks. Documented in the workspace registry's own notes on
# deploy-gate: "required" means "can block a merge", not "present in
# required_status_checks".
UMBRELLA_REPOS = frozenset({"omnibase_infra", "omnimarket"})


class AuditError(Exception):
    """The audit could not run. Exit 2 — never a silent zero."""


@dataclass(frozen=True)
class Finding:
    repo: str
    kind: str
    detail: str


def _gh(args: list[str]) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AuditError(
            f"`gh {' '.join(args)}` exited {proc.returncode}: {proc.stderr.strip()}. "
            "Treating this as zero rows would be the false-zero failure this "
            "audit exists to avoid."
        )
    return proc.stdout


def public_repos() -> list[dict[str, str]]:
    out = _gh(
        [
            "api",
            f"orgs/{OWNER}/repos",
            "--paginate",
            "-X",
            "GET",
            "-f",
            "type=public",
            "-f",
            "per_page=100",
            "--jq",
            ".[] | {name, default_branch} | tostring",
        ]
    )
    repos = [json.loads(line) for line in out.splitlines() if line.strip()]
    if not repos:
        raise AuditError(
            f"the public-repository listing for {OWNER} came back EMPTY. An "
            "empty result is not evidence of absence — it is what an errored "
            "sweep returns. Re-run with a positive control."
        )
    return repos


def _file_exists(repo: str, path: str, ref: str) -> bool:
    proc = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{OWNER}/{repo}/contents/{path}?ref={ref}",
            "--jq",
            ".name",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return True
    # A 404 is a real answer: the file is absent. Anything else is an audit
    # failure and must not read as "absent".
    if "404" in proc.stderr or "Not Found" in proc.stderr:
        return False
    raise AuditError(f"could not read {repo}/{path}@{ref}: {proc.stderr.strip()}")


def _required_contexts(repo: str, branch: str) -> list[str] | None:
    """Returns the required contexts, or ``None`` when the branch carries no
    protection at all — which is itself a finding, not an empty list.
    """
    proc = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{OWNER}/{repo}/branches/{branch}/protection/required_status_checks",
            "--jq",
            ".contexts",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        if "404" in proc.stderr or "Not Found" in proc.stderr:
            return None
        raise AuditError(
            f"could not read protection for {repo}@{branch}: {proc.stderr.strip()}"
        )
    return list(json.loads(proc.stdout or "[]"))


def _branches_without_a_pr(repo: str, default_branch: str) -> list[str]:
    """Branches with no pull request, ever.

    ``--paginate`` with a jq program that CONSTRUCTS an array emits one array
    per page, which is several JSON documents concatenated and not parseable
    as one. Emit one name per line instead and collect — the shape that
    survives pagination.
    """
    branches = [
        line.strip()
        for line in _gh(
            ["api", f"repos/{OWNER}/{repo}/branches", "--paginate", "--jq", ".[].name"]
        ).splitlines()
        if line.strip()
    ]
    with_prs = {
        line.strip()
        for line in _gh(
            [
                "api",
                f"repos/{OWNER}/{repo}/pulls",
                "--paginate",
                "-X",
                "GET",
                "-f",
                "state=all",
                "-f",
                "per_page=100",
                "--jq",
                ".[].head.ref",
            ]
        ).splitlines()
        if line.strip()
    }
    return sorted(b for b in branches if b != default_branch and b not in with_prs)


def audit(check_required: bool) -> list[Finding]:
    findings: list[Finding] = []
    for repo in public_repos():
        name = repo["name"]
        branch = repo["default_branch"]

        if not _file_exists(name, GATE_WORKFLOW, branch):
            findings.append(
                Finding(name, "gate-missing", f"no {GATE_WORKFLOW} on {branch}")
            )
        if not _file_exists(name, CONFIG_FILE, branch):
            findings.append(
                Finding(
                    name,
                    "config-missing",
                    f"no {CONFIG_FILE} on {branch} — layer (a) cannot run without "
                    "the repo declaring its permitted root entries",
                )
            )

        if check_required and name not in UMBRELLA_REPOS:
            contexts = _required_contexts(name, branch)
            if contexts is None:
                findings.append(
                    Finding(
                        name,
                        "branch-unprotected",
                        f"{branch} carries no branch protection",
                    )
                )
            elif GATE_CONTEXT not in contexts:
                findings.append(
                    Finding(
                        name,
                        "required-check-missing",
                        f"'{GATE_CONTEXT}' is not in required_status_checks on {branch}",
                    )
                )

        stranded = _branches_without_a_pr(name, branch)
        if stranded:
            findings.append(
                Finding(
                    name,
                    "branch-without-pr",
                    f"{len(stranded)} public branch(es) with no pull request, so the "
                    f"gate has never run on them: {', '.join(stranded[:10])}"
                    + (" ..." if len(stranded) > 10 else ""),
                )
            )
    return findings


def self_test() -> None:
    """Positive control. A zero-finding run is only meaningful if the audit can
    be shown to produce a finding at all.
    """
    probe = "omnibot"
    if _file_exists(probe, GATE_WORKFLOW, "main"):
        raise AuditError(
            f"self-test control is stale: {probe} now carries {GATE_WORKFLOW}, so "
            "it no longer proves the detector fires. Pick another control."
        )
    print(f"self-test OK: the gate-missing detector fires against {probe}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="print findings and exit 0 — the rollout mode",
    )
    parser.add_argument(
        "--skip-required-check",
        action="store_true",
        help=(
            "do not audit required_status_checks. Set while the required-check "
            "registration is still parked on an operator decision, so the audit "
            "reports real drift instead of 18 copies of a known open item."
        ),
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.self_test:
            self_test()
            return 0
        findings = audit(check_required=not args.skip_required_check)
    except AuditError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2

    if not findings:
        print("public-repo hygiene rollout: no drift")
        return 0

    by_kind: dict[str, list[Finding]] = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)
    for kind in sorted(by_kind):
        print(f"\n{kind}: {len(by_kind[kind])}")
        for f in by_kind[kind]:
            print(f"  {f.repo}: {f.detail}")

    return 0 if args.report_only else 1


if __name__ == "__main__":
    sys.exit(main())
