#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CI-side detect-secrets baseline diff against the target-branch baseline (OMN-15072).

The `detect-secrets` CI job in `ci.yml` previously compared the PR's
regenerated `.secrets.baseline` against a `.bak` copy taken from the SAME
checked-out commit (`cp .secrets.baseline .secrets.baseline.bak` before the
scan). That meant a secret and its own baseline-laundering entry arriving
together in one commit -- exactly what the pre-OMN-15068 auto-approving
pre-commit hook produced, and what a `--no-verify` commit or a hand-edited
baseline can still produce -- diffed to zero and the job passed. CI was not
independent coverage of the commit-time hole OMN-15068 fixed; it shared the
same blind spot.

This script instead diffs the PR's (already re-scanned) baseline against the
baseline as it exists on the **target branch** -- a ref the PR author does
not control within their own commit. A `(file, hashed_secret)` entry present
in the PR baseline but absent from the target-branch baseline is a same-PR
addition and is classified exactly like `scripts/detect_secrets_guard.py`
(OMN-15068) classifies a new commit-time finding, by reusing its
`load_json`/`result_keys`/`load_baseline_at_ref` helpers rather than
re-implementing the audited-vs-unaudited distinction a second time:

- **New + audited** (`is_secret` key present -- set only by a human running
  `detect-secrets audit .secrets.baseline`) -- allowed.
- **New + unaudited** -- BLOCKS the job.

Two comparison modes:

1. `--target-ref REF` (e.g. `origin/dev`): the target-branch baseline is
   loaded via `git show <REF>:.secrets.baseline`. A missing/unreadable
   baseline at REF fails closed (`treat_missing_as_empty=False`) -- unlike
   the pre-commit guard's own "no prior HEAD" convenience, a CI job that
   cannot see the target branch's baseline must not silently pass.
2. `--fallback-baseline PATH`: used only for events with no meaningful
   target branch (e.g. `workflow_dispatch`). PATH is a same-commit snapshot
   taken by the caller BEFORE the scan ran (the pre-OMN-15072 `.bak`
   pattern) -- narrower than target-branch comparison by design, retained
   only for non-gating trigger types.

Exactly one of `--target-ref` / `--fallback-baseline` must be supplied.

Fails closed (non-zero exit) on: missing/unreadable/corrupt baseline on
either side, an unresolvable `--target-ref`, or neither/both selector flags
supplied.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from detect_secrets_guard import BASELINE, load_baseline_at_ref, load_json, result_keys


def _block(message: str) -> int:
    print(f"[detect-secrets-ci-diff] BLOCKED: {message}", file=sys.stderr)
    return 1


def _load_pr_baseline(path: Path) -> dict | None:
    if not path.exists():
        print(
            f"[detect-secrets-ci-diff] {path} does not exist -- nothing to diff.",
            file=sys.stderr,
        )
        return None
    try:
        text = path.read_text()
    except OSError as exc:
        print(f"[detect-secrets-ci-diff] could not read {path}: {exc}", file=sys.stderr)
        return None
    return load_json(text, f"PR baseline ({path})")


def _load_target_baseline(args: argparse.Namespace) -> dict | None:
    if args.target_ref:
        return load_baseline_at_ref(args.target_ref, treat_missing_as_empty=False)
    fallback_path = Path(args.fallback_baseline)
    if not fallback_path.exists():
        print(
            f"[detect-secrets-ci-diff] fallback baseline {fallback_path} does not exist.",
            file=sys.stderr,
        )
        return None
    try:
        text = fallback_path.read_text()
    except OSError as exc:
        print(
            f"[detect-secrets-ci-diff] could not read fallback baseline "
            f"{fallback_path}: {exc}",
            file=sys.stderr,
        )
        return None
    return load_json(text, f"fallback baseline ({fallback_path})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pr-baseline",
        default=str(BASELINE),
        help="Path to the PR's regenerated .secrets.baseline (default: .secrets.baseline)",
    )
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument(
        "--target-ref",
        help="git ref to diff against, e.g. origin/dev (fails closed if unreadable)",
    )
    selector.add_argument(
        "--fallback-baseline",
        help="Same-commit pre-scan snapshot path, only for events with no target branch",
    )
    args = parser.parse_args(argv)

    pr_baseline = _load_pr_baseline(Path(args.pr_baseline))
    if pr_baseline is None:
        return _block("PR baseline is missing, unreadable, or corrupt.")

    target_baseline = _load_target_baseline(args)
    if target_baseline is None:
        return _block("target baseline is missing, unreadable, or corrupt.")

    target_keys = result_keys(target_baseline)

    unaudited_new: list[tuple[str, int | None, str | None]] = []
    audited_new: list[tuple[str, int | None]] = []
    for filename, findings in pr_baseline.get("results", {}).items():
        for finding in findings:
            key = (filename, finding.get("hashed_secret", ""))
            if key in target_keys:
                continue  # already known on the target branch.
            if finding.get("is_secret") is not None:
                audited_new.append((filename, finding.get("line_number")))
                continue  # explicitly audited via `detect-secrets audit`.
            unaudited_new.append(
                (filename, finding.get("line_number"), finding.get("type"))
            )

    if unaudited_new:
        print(
            "[detect-secrets-ci-diff] BLOCKED: new, unaudited secret finding(s) "
            "not present on the target branch:\n",
            file=sys.stderr,
        )
        for filename, line, finding_type in unaudited_new:
            print(f"  - {filename}:{line}  [{finding_type}]", file=sys.stderr)
        print(
            f"\n::error::detect-secrets found {len(unaudited_new)} new potential "
            "secret(s) not in the target branch's baseline and not audited "
            "(no `is_secret` key). If real: remove/rotate the credential. If a "
            "false positive: run `detect-secrets audit .secrets.baseline` locally, "
            "mark it reviewed, and include the audited baseline in this PR.",
            file=sys.stderr,
        )
        return 1

    print(
        "[detect-secrets-ci-diff] OK: no new unaudited findings "
        f"({len(audited_new)} new audited entr{'y' if len(audited_new) == 1 else 'ies'} "
        "allowed)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
