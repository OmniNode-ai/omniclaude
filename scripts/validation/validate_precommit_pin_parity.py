#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
CI/pre-commit check: pin-parity ratchet between .pre-commit-config.yaml and
.github/workflows/ci.yml (OMN-14655, DRIFT-3 recurrence guard).

Two blocks in .pre-commit-config.yaml used to pin the SAME upstream
(omnibase_core) at TWO DIFFERENT revs (458f44e for check-stub-implementations,
63635097 for no-noncanonical-lifecycle-classes) -- staleness by construction,
even though the second rev happened to already match CI's own pin at
ci.yml:3102. OMN-14655 converged both hooks onto one `rev:` (see the `repos:`
block comment in .pre-commit-config.yaml). This gate keeps it converged: it
fails closed the moment the pre-commit pin and the CI-pinned SHA for the same
validator diverge again, on either side of the pair.

PIN_PAIRS below is a small, explicitly-verified table -- add a new pair only
after confirming (by hand, via `git diff <old-rev> <new-rev>`) that both
sides really do reference the same validator, not two independently-pinned
tools that happen to share an upstream repo.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / ".pre-commit-config.yaml"
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# (pre-commit hook id, pre-commit repo URL, CI git-dependency repo substring)
# -> both sides must resolve to the identical pinned SHA.
PIN_PAIRS: tuple[tuple[str, str, str], ...] = (
    (
        "no-noncanonical-lifecycle-classes",
        "https://github.com/OmniNode-ai/omnibase_core",
        "github.com/OmniNode-ai/omnibase_core",
    ),
)

_CI_PIN_RE = re.compile(
    r"omnibase-core\s*@\s*git\+https://github\.com/OmniNode-ai/omnibase_core"
    r"@([0-9a-f]{40})"
)


def _find_hook_rev(config: dict, hook_id: str, repo_url: str) -> str | None:
    for repo in config.get("repos", []):
        if repo.get("repo") != repo_url:
            continue
        for hook in repo.get("hooks", []):
            if hook.get("id") == hook_id:
                return repo.get("rev")
    return None


def _find_ci_pins(ci_text: str, repo_substring: str) -> list[str]:
    return [
        m.group(1) for m in _CI_PIN_RE.finditer(ci_text) if repo_substring in m.group(0)
    ]


def main() -> int:
    if not CONFIG_PATH.is_file():
        print(f"ERROR: {CONFIG_PATH} not found", file=sys.stderr)
        return 1
    if not CI_WORKFLOW_PATH.is_file():
        print(f"ERROR: {CI_WORKFLOW_PATH} not found", file=sys.stderr)
        return 1

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    ci_text = CI_WORKFLOW_PATH.read_text(encoding="utf-8")

    violations: list[str] = []

    for hook_id, repo_url, repo_substring in PIN_PAIRS:
        precommit_rev = _find_hook_rev(config, hook_id, repo_url)
        if precommit_rev is None:
            violations.append(
                f"pin-parity: hook id={hook_id!r} not found under repo={repo_url!r} "
                f"in {CONFIG_PATH.name} -- update PIN_PAIRS or the config."
            )
            continue

        ci_pins = _find_ci_pins(ci_text, repo_substring)
        if not ci_pins:
            violations.append(
                f"pin-parity: no CI-pinned SHA found in {CI_WORKFLOW_PATH.name} "
                f"for repo substring {repo_substring!r} (hook {hook_id!r}) -- "
                "update PIN_PAIRS or restore the CI pin."
            )
            continue

        mismatched = [p for p in ci_pins if p != precommit_rev]
        if mismatched:
            violations.append(
                f"pin-parity: hook {hook_id!r} pins rev={precommit_rev} in "
                f"{CONFIG_PATH.name}, but {CI_WORKFLOW_PATH.name} pins "
                f"{mismatched} for the same validator. These must match -- "
                "bump whichever side is stale."
            )

    if violations:
        print(f"FAIL: {len(violations)} pin-parity violation(s):\n")
        for v in violations:
            print(f"  {v}\n")
        return 1

    print("OK: all pinned revs in PIN_PAIRS match their CI-pinned counterpart.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
