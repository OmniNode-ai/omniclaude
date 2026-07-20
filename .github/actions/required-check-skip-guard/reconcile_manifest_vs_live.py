#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Required-Check Skip-Vector Guard (OMN-14854) — privileged manifest reconcile.
#
# Compares `.github/required-checks.yaml` schema-v3 REQUIRED rows against the
# LIVE `required_status_checks.contexts` for a branch. This is deliberately
# NOT part of the PR-time validator: the branch-protection read endpoint needs
# a token scope (`administration:read`) that must never be granted to a
# `pull_request`-triggered workflow (a malicious/careless PR could read/exfil
# protection config). This script only ever runs from `push`/`schedule`/
# `workflow_dispatch` (see required-check-manifest-reconcile.yml) — never from
# `pull_request`.
#
# Fail-closed in both directions:
#   - missing_from_manifest: live requires a context the manifest doesn't know
#     about (dangerous direction — an unaudited required check with zero
#     skip-vector coverage).
#   - stale_in_manifest: manifest claims a context is REQUIRED but branch
#     protection disagrees (the guard would be enforcing a no-op).
#
# Usage:
#   python reconcile_manifest_vs_live.py --manifest .github/required-checks.yaml \
#       --repo OmniNode-ai/omniclaude --branch dev

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml


def fetch_live_contexts(repo: str, branch: str) -> list[str]:
    result = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{repo}/branches/{branch}/protection/required_status_checks",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            f"ERROR: failed to fetch required_status_checks for {repo}@{branch}: "
            f"{result.stderr.strip()}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    payload = json.loads(result.stdout)
    return list(payload.get("contexts", []))


def reconcile(
    manifest_path: Path, live_contexts: list[str]
) -> tuple[set[str], set[str]]:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    manifest_required = {
        gate["name"]
        for gate in manifest.get("gates", [])
        if gate.get("mode") == "REQUIRED"
    }
    live_set = set(live_contexts)

    missing_from_manifest = live_set - manifest_required
    stale_in_manifest = manifest_required - live_set
    return missing_from_manifest, stale_in_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch", required=True)
    args = parser.parse_args()

    live_contexts = fetch_live_contexts(args.repo, args.branch)
    missing_from_manifest, stale_in_manifest = reconcile(args.manifest, live_contexts)

    if missing_from_manifest or stale_in_manifest:
        if missing_from_manifest:
            print(
                f"FAIL: {len(missing_from_manifest)} live required context(s) missing "
                f"from manifest ({args.repo}@{args.branch}):"
            )
            for ctx in sorted(missing_from_manifest):
                print(f"  - {ctx}")
        if stale_in_manifest:
            print(
                f"FAIL: {len(stale_in_manifest)} manifest-REQUIRED context(s) not live "
                f"in branch protection ({args.repo}@{args.branch}):"
            )
            for ctx in sorted(stale_in_manifest):
                print(f"  - {ctx}")
        return 1

    print(
        f"PASS: manifest and live required_status_checks agree for {args.repo}@{args.branch}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
