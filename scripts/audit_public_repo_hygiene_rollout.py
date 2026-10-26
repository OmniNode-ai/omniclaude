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
import ast
import base64
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

OWNER = "OmniNode-ai"
GATE_WORKFLOW = ".github/workflows/public-repo-hygiene.yml"
GATE_CONTEXT = "public-repo-hygiene / public-repo-hygiene"
CONFIG_FILE = ".public-repo-hygiene.yaml"
DEPLOYMENT_CONTEXT = "public-repo-hygiene / deployment-config"
DEPLOYMENT_BASELINE = ".public-repo-hygiene.yaml"
RATCHET_REPOS = frozenset({"omnimarket", "omnibase_infra", "omniclaude"})

# Repos that gate behind a single CI-summary umbrella rather than through
# required_status_checks. Documented in the workspace registry's own notes on
# deploy-gate: "required" means "can block a merge", not "present in
# required_status_checks".
UMBRELLA_REPOS = frozenset({"omnibase_infra", "omnimarket", "omniclaude"})


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


def _file_text(repo: str, path: str, ref: str) -> str | None:
    proc = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{OWNER}/{repo}/contents/{path}?ref={ref}",
            "--jq",
            ".content",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode:
        if "404" in proc.stderr or "Not Found" in proc.stderr:
            return None
        raise AuditError(f"could not read {repo}/{path}@{ref}: {proc.stderr.strip()}")
    try:
        return base64.b64decode("".join(proc.stdout.split()), validate=True).decode(
            "utf-8"
        )
    except (ValueError, UnicodeError) as exc:
        raise AuditError(f"malformed content for {repo}/{path}@{ref}") from exc


def umbrella_contexts(text: str) -> tuple[str, ...]:
    """Read the actual CI Summary constant, never a comment containing a name."""
    try:
        tree = ast.parse(text)
        for statement in tree.body:
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else (
                    [statement.target] if isinstance(statement, ast.AnnAssign) else []
                )
            )
            if any(
                isinstance(t, ast.Name) and t.id == "EXPECTED_EXTERNAL_CONTEXTS"
                for t in targets
            ):
                value = ast.literal_eval(statement.value)
                if isinstance(value, (tuple, list)) and all(
                    isinstance(x, str) for x in value
                ):
                    return tuple(value)
    except (SyntaxError, ValueError, TypeError) as exc:
        raise AuditError("unreadable CI Summary external-context registration") from exc
    raise AuditError("CI Summary has no literal EXPECTED_EXTERNAL_CONTEXTS")


def deployment_wiring_findings(
    repo: str, read: Callable[[str], str | None]
) -> list[Finding]:
    findings: list[Finding] = []
    text = read(".pre-commit-config.yaml") or ""
    # Isolate the hook block using its YAML indentation, without a YAML dependency.
    lines = text.splitlines()
    block: list[str] | None = None
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)- id: deployment-config\s*$", line)
        if match:
            indent = len(match[1])
            block = []
            for following in lines[index + 1 :]:
                if following.strip() and not following.lstrip().startswith("#"):
                    if len(following) - len(following.lstrip()) <= indent:
                        break
                block.append(following)
            break
    if block is None:
        findings.append(
            Finding(
                repo,
                "deployment-hook-missing",
                "pre-commit has no deployment-config hook",
            )
        )
        hook = ""
    else:
        hook = "\n".join(line for line in block if not line.lstrip().startswith("#"))
        if (
            "--staged" in hook
            or re.search(
                r"\b(?:always_run:\s*false|pass_filenames:\s*true|files:|exclude:)",
                hook,
            )
            or ("stages:" in hook and "pre-commit" not in hook)
        ):
            findings.append(
                Finding(
                    repo,
                    "deployment-hook-narrowed",
                    "deployment-config must scan the whole index on every commit",
                )
            )
    if repo in RATCHET_REPOS:
        workflow = read(GATE_WORKFLOW) or ""
        if "--ratchet" not in hook or not re.search(
            r"^\s+deployment_config_ratchet:\s*true\s*$", workflow, re.M
        ):
            findings.append(
                Finding(
                    repo,
                    "deployment-ratchet-missing",
                    "whole-tree ratchet must run in both CI and pre-commit",
                )
            )
        baseline = read(DEPLOYMENT_BASELINE)
        if baseline is None or (
            not baseline.lstrip().startswith("{")
            and not re.search(r"^deployment_residue:", baseline, re.M)
        ):
            findings.append(
                Finding(
                    repo,
                    "deployment-baseline-missing",
                    f"no committed {DEPLOYMENT_BASELINE}",
                )
            )
        else:
            # Import the canonical schema validator; malformed baselines are audit errors.
            if __package__:
                from .public_repo_hygiene_gate import (
                    ConfigError,
                    load_deployment_baseline,
                )
            else:
                # Direct file imports (including the standalone script).
                import importlib.util

                spec = importlib.util.spec_from_file_location(
                    "audit_hygiene_schema",
                    Path(__file__).with_name("public_repo_hygiene_gate.py"),
                )
                assert spec is not None and spec.loader is not None
                schema = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = schema
                spec.loader.exec_module(schema)
                ConfigError = schema.ConfigError
                load_deployment_baseline = schema.load_deployment_baseline
            try:
                load_deployment_baseline(baseline)
            except ConfigError as exc:
                raise AuditError(f"{repo}: {exc}") from exc
    return findings


def _required_findings(
    repo: str,
    branch: str,
    contexts: list[str] | None,
    read: Callable[[str], str | None],
) -> list[Finding]:
    if contexts is None:
        return [
            Finding(
                repo, "branch-unprotected", f"{branch} carries no branch protection"
            )
        ]
    required = (GATE_CONTEXT, DEPLOYMENT_CONTEXT)
    if repo in UMBRELLA_REPOS:
        if "CI Summary" not in contexts:
            return [
                Finding(
                    repo,
                    "required-check-missing",
                    f"CI Summary is not required on {branch}",
                )
            ]
        source = read("scripts/ci/ci_summary_gate.py")
        if source is None:
            raise AuditError(f"{repo}: CI Summary implementation missing")
        contexts = list(umbrella_contexts(source))
    return [
        Finding(
            repo, "required-check-missing", f"'{context}' is not required on {branch}"
        )
        for context in required
        if context not in contexts
    ]


def audit_local(workspace_root: Path, required_contexts_file: Path) -> list[Finding]:
    """Audit supplied local checkouts against exported watcher settings, offline."""
    data = json.loads(required_contexts_file.read_text())
    if not isinstance(data, dict) or not data:
        raise AuditError(
            "required-context inventory must be a nonempty repository mapping"
        )
    findings: list[Finding] = []
    for repo, record in data.items():
        if not isinstance(record, dict) or not isinstance(record.get("contexts"), list):
            raise AuditError(f"{repo}: required contexts unreadable-from-snapshot")
        root = workspace_root / repo

        def read(path: str, root: Path = root) -> str | None:
            target = root / path
            return target.read_text() if target.is_file() else None

        findings.extend(deployment_wiring_findings(repo, read))
        findings.extend(
            _required_findings(
                repo, record.get("branch", "dev"), record["contexts"], read
            )
        )
        print(f"{repo}: audited deployment-config required check and pre-commit")
    return findings


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

        def read(path: str, name: str = name, branch: str = branch) -> str | None:
            return _file_text(name, path, branch)

        findings.extend(deployment_wiring_findings(name, read))
        if check_required:
            findings.extend(
                _required_findings(name, branch, _required_contexts(name, branch), read)
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

    This used to probe a live repository (``omnibot``) for the absence of the
    gate workflow file. That repository's rollout state is not this audit's
    to hold still -- once ``omnibot`` legitimately adopted the gate, the
    self-test read "the control is stale" and failed the audit on its
    positive control, every day, 2026-09-20 through 2026-09-24, before the
    real sweep ever ran (OMN-18016).

    The fix is a synthetic fixture instead of a live repo: a path under an
    existing, always-accessible repository that no real hygiene-rollout
    change will ever create, because its name says what it is. A repo can be
    gated later; this sentinel cannot organically start existing.
    """
    probe_repo = "omniclaude"
    probe_path = ".github/workflows/__omn18016-self-test-sentinel-do-not-create__.yml"
    if _file_exists(probe_repo, probe_path, "dev"):
        raise AuditError(
            f"self-test control is stale: {probe_repo}@{probe_path} exists, so "
            "it no longer proves the detector fires. Pick another sentinel path."
        )
    print(
        "self-test OK: the gate-missing detector fires against a synthetic "
        f"sentinel path in {probe_repo}"
    )


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
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--required-contexts-file", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.self_test:
            self_test()
            return 0
        if args.workspace_root is not None:
            if args.required_contexts_file is None or args.skip_required_check:
                raise AuditError(
                    "offline audit requires exported required contexts and cannot skip them"
                )
            findings = audit_local(args.workspace_root, args.required_contexts_file)
        else:
            findings = audit(check_required=not args.skip_required_check)
    except (AuditError, OSError, ValueError) as exc:
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
