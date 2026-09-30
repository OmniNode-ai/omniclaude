#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Plugin version-bump gate [OMN-16913].

The Claude Code plugin cache is keyed on the manifest ``version``. A change under
``plugins/onex/`` that lands without a bump never reaches an installed cache:
``claude plugin update`` answers already-latest. On 2026-09-30 the onex cache was
2.3.2 (built 2026-08-29) and differed from the tree by about 180 files.

This gate fails when files under ``plugins/onex/`` differ from the merge base with
the base ref and ``plugins/onex/.claude-plugin/plugin.json`` ``version`` is not
strictly greater than its merge-base value. It also fails when the dev marketplace
entry for ``onex`` pins a different version than the plugin manifest.

The diff is merge-base to the working tree, so the same check serves CI (a clean
checkout of the PR head) and the pre-commit hook (staged and unstaged edits).
Plugin tests and bytecode are not shipped behaviour and do not require a bump.

Exit codes: 0 clean, 1 finding, 2 the gate could not run (never a pass).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PLUGIN_DIR = "plugins/onex/"
PLUGIN_JSON = "plugins/onex/.claude-plugin/plugin.json"
#: The in-repo directory marketplace(s) that pin the onex plugin version.
MARKETPLACE_GLOB = "plugins/*-marketplace/.claude-plugin/marketplace.json"
PLUGIN_NAME = "onex"
_EXEMPT_PREFIXES = ("plugins/onex/tests/",)
_EXEMPT_PARTS = ("__pycache__", ".venv")
_EXEMPT_SUFFIXES = (".pyc",)


class GateError(RuntimeError):
    """The gate could not decide; the caller must treat this as a refusal."""


@dataclass(frozen=True)
class Finding:
    kind: str
    detail: str


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise GateError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _is_shipped(path: str) -> bool:
    if not path.startswith(PLUGIN_DIR):
        return False
    if path.startswith(_EXEMPT_PREFIXES) or path.endswith(_EXEMPT_SUFFIXES):
        return False
    return not any(part in _EXEMPT_PARTS for part in path.split("/"))


def _version_key(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in version.split("."))
    except ValueError as exc:
        raise GateError(f"non-numeric plugin version {version!r}") from exc


def _plugin_version(text: str, source: str) -> str:
    try:
        version = json.loads(text)["version"]
    except (ValueError, KeyError, TypeError) as exc:
        raise GateError(f"{source} has no readable version") from exc
    if not isinstance(version, str):
        raise GateError(f"{source} version is not a string")
    return version


def marketplace_skew(repo: Path) -> list[Finding]:
    plugin = _plugin_version((repo / PLUGIN_JSON).read_text(), PLUGIN_JSON)
    manifests = sorted(repo.glob(MARKETPLACE_GLOB))
    if not manifests:
        raise GateError(f"no marketplace manifest matches {MARKETPLACE_GLOB}")
    findings = []
    for manifest in manifests:
        name = manifest.relative_to(repo).as_posix()
        try:
            entries = json.loads(manifest.read_text())["plugins"]
        except (ValueError, KeyError, TypeError) as exc:
            raise GateError(f"{name} has no readable plugins list") from exc
        for entry in entries:
            if entry.get("name") == PLUGIN_NAME and entry.get("version") != plugin:
                findings.append(
                    Finding(
                        "MARKETPLACE_SKEW",
                        f"{name} pins {PLUGIN_NAME} {entry.get('version')} "
                        f"but {PLUGIN_JSON} is {plugin}; bump both together.",
                    )
                )
    return findings


def check(repo: Path, base: str) -> list[Finding]:
    _git(repo, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    merge_base = _git(repo, "merge-base", base, "HEAD").strip()
    changed = [
        p
        for p in _git(repo, "diff", "--name-only", merge_base).splitlines()
        if _is_shipped(p)
    ]
    findings = marketplace_skew(repo)
    if not changed:
        return findings
    current = _plugin_version((repo / PLUGIN_JSON).read_text(), PLUGIN_JSON)
    previous = _plugin_version(
        _git(repo, "show", f"{merge_base}:{PLUGIN_JSON}"), f"{merge_base}:{PLUGIN_JSON}"
    )
    if _version_key(current) <= _version_key(previous):
        shown = ", ".join(changed[:5]) + (" ..." if len(changed) > 5 else "")
        findings.insert(
            0,
            Finding(
                "NO_BUMP",
                f"{len(changed)} file(s) under {PLUGIN_DIR} changed ({shown}) but "
                f"{PLUGIN_JSON} version is {current}, not above {previous} at the "
                f"merge base with {base}. The plugin cache is version-keyed, so "
                "without a bump the change never reaches an installed plugin. "
                f"Bump {PLUGIN_JSON} and the onex entry in the in-repo marketplace manifest.",
            ),
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--base", default="origin/dev")
    parser.add_argument(
        "--defer-to-workflow-in-ci",
        action="store_true",
        help=(
            "Exit 0 when running under GitHub Actions. The whole-tree pre-commit "
            "job checks out one commit with no base ref to compare against; the "
            "dedicated Plugin Version Bump Gate workflow is the blocking verdict "
            "there. Local runs are unaffected."
        ),
    )
    args = parser.parse_args(argv)
    if args.defer_to_workflow_in_ci and os.environ.get("GITHUB_ACTIONS") == "true":
        print(
            "plugin-version-bump: deferred to the Plugin Version Bump Gate workflow",
            file=sys.stderr,
        )
        return 0
    try:
        findings = check(args.repo_root, args.base)
    except GateError as exc:
        print(f"plugin-version-bump gate could not run: {exc}", file=sys.stderr)
        return 2
    for finding in findings:
        print(f"{finding.kind}: {finding.detail}", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
