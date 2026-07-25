#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Lint gate: plans must not propose new scripts/** without a canonical-form declaration.

The DEFAULT-DENY scripts policy (OMN-14475) blocks new ``scripts/**`` files at
code time — a new script passes CI only if it is baselined or has a
CODEOWNERS-approved exceptions-registry entry. This gate moves that decision
EARLIER: it catches a plan that proposes creating a new ``scripts/**`` file
BEFORE the code exists, so the plan either designs the work as a canonical
CONTRACT+NODE+HANDLER or consciously declares a justified exception.

A plan under ``docs/plans/`` or ``docs/tracking/`` is FLAGGED when it proposes
creating/adding a ``scripts/**`` file (``.py``/``.sh``/``.bash``) — detected by a
create-intent verb on the same line as the script path — UNLESS the plan carries
a ``canonical-form:`` declaration:

    canonical-form: node-backed
    canonical-form: justified-shim: <reason>
    canonical-form: convert OMN-XXXX
    canonical-form: exception OMN-XXXX

The declaration is the plan author's conscious statement of how the proposed
script satisfies the deny-new policy (dispatches to a node, or is a reviewed
CI/deploy/bootstrap glue exception with a ticket). Its presence clears the plan;
the code-time guard (OMN-14475) still enforces the actual mechanism.

## Ratchet semantics

Existing plan/tracking docs that predate this gate are grandfathered via a
baseline allowlist (``.onex_ratchets/plan_canonical_scripts_allowlist.yaml``).
Burn-down only: a NEW or MODIFIED plan must comply; the allowlist must never grow.

## Exit codes

- 0 — every non-allowlisted plan either proposes no new script or declares its
  canonical form
- 1 — one or more plans propose a new script with no ``canonical-form:``
  declaration; or a file is unreadable (fail-closed)

## Usage

- Pre-commit: invoked with staged markdown paths; only paths under
  ``docs/plans/`` or ``docs/tracking/`` are checked; others ignored.
- CI: invoked with no path arguments; scans the full plan/tracking tree.

## Refs

- OMN-14476 (this gate); OMN-14475 (code-time deny-new guard); OMN-13674 (epic).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PLAN_ROOTS: tuple[Path, ...] = (Path("docs/plans"), Path("docs/tracking"))
ALLOWLIST_PATH = Path(".onex_ratchets/plan_canonical_scripts_allowlist.yaml")

# A create-intent verb on the same line as a scripts/**.{py,sh,bash} path.
# Case-insensitive. The verb must precede the path so a mere mention of an
# existing script ("the existing scripts/foo.py") is not misread as a proposal.
_PROPOSE_SCRIPT_RE = re.compile(
    r"\b(create|add|new|write|implement|introduce|build)\b[^\n]*?"
    r"(?P<path>scripts/[\w./-]+\.(?:py|sh|bash))\b",
    re.IGNORECASE,
)

# A canonical-form declaration clearing the proposal.
_DECLARATION_RE = re.compile(
    r"canonical-form:\s*(node-backed|justified-shim|convert|exception)\b",
    re.IGNORECASE,
)


def _load_allowlist(root: Path) -> set[str]:
    """Read the grandfather allowlist (flat ``- path`` list, no YAML dep).

    An unreadable allowlist is treated as empty so the gate fails closed on any
    otherwise-violating plan (never silently exempts everything).
    """
    path = root / ALLOWLIST_PATH
    if not path.exists():
        return set()
    allowed: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return set()
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in ("allowed:", "allowed: []"):
            continue
        if stripped.startswith("- "):
            entry = stripped[2:].strip().strip("\"'")
            if entry:
                allowed.add(entry)
    return allowed


def _scan_file(path: Path) -> tuple[list[str], str | None]:
    """Scan one plan file for undeclared new-script proposals.

    Returns ``(violations, read_error)``. ``read_error`` is set (and treated as
    a violation by the caller) when the file cannot be read or decoded — failing
    closed so an unreadable plan cannot slip past this blocking gate.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return [], f"{path}: decode error: {exc}"
    except OSError as exc:
        return [], f"{path}: read error: {exc}"

    proposed: list[tuple[int, str]] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        match = _PROPOSE_SCRIPT_RE.search(line)
        if match is not None:
            proposed.append((idx, match.group("path")))

    if not proposed:
        return [], None

    if _DECLARATION_RE.search(text):
        # The plan proposes scripts but declares its canonical form → allowed.
        return [], None

    violations = [
        f"{path}:{line_no}: proposes new script '{script}' with no "
        "'canonical-form:' declaration"
        for line_no, script in proposed
    ]
    return violations, None


def _iter_plan_markdown(roots: tuple[Path, ...]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        found.extend(p for p in root.rglob("*.md") if p.is_file())
    return sorted(set(found))


def _is_plan_markdown(path: Path, repo_root: Path) -> bool:
    if path.suffix != ".md":
        return False
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    return rel.parts[:2] in {("docs", "plans"), ("docs", "tracking")}


def _rel_to_repo(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="lint_plan_canonical_scripts.py",
        description=(
            "Fail when a plan proposes a new scripts/** file with no "
            "'canonical-form:' declaration (OMN-14476)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root used to resolve plan paths and the allowlist.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Plan markdown paths (pre-commit). Empty → scan full tree (CI).",
    )
    args = parser.parse_args(argv[1:])

    repo_root: Path = args.repo_root
    if args.paths:
        targets = [Path(a) for a in args.paths if _is_plan_markdown(Path(a), repo_root)]
    else:
        roots = tuple(repo_root / r for r in PLAN_ROOTS)
        targets = _iter_plan_markdown(roots)

    allowlist = _load_allowlist(repo_root)

    total_violations = 0
    violating_files: list[Path] = []
    for path in sorted(set(targets)):
        if not path.exists():
            continue
        rel = _rel_to_repo(path, repo_root)
        if rel in allowlist:
            continue
        violations, read_error = _scan_file(path)
        if read_error is not None:
            sys.stderr.write(f"{read_error}\n")
            violating_files.append(path)
            total_violations += 1
            continue
        if not violations:
            continue
        violating_files.append(path)
        for line in violations:
            sys.stderr.write(f"{line}\n")
            total_violations += 1

    if total_violations == 0:
        return 0

    sys.stderr.write(
        "\n"
        f"BLOCKED: {len(violating_files)} plan file(s) propose a new "
        "scripts/** file without declaring its canonical form.\n"
        "\n"
        "Default answer: build the work as a canonical CONTRACT+NODE+HANDLER,\n"
        "not a script. If the script provably cannot be a node yet (CI/deploy/\n"
        "bootstrap/git-hook glue), declare it in the plan with a line:\n"
        "\n"
        "    canonical-form: node-backed\n"
        "    canonical-form: justified-shim: <reason>\n"
        "    canonical-form: exception OMN-XXXX\n"
        "\n"
        "The code-time deny-new guard (OMN-14475) still enforces the mechanism:\n"
        "a new scripts/** file passes CI only if baselined or in the\n"
        "CODEOWNERS-approved exceptions registry.\n"
        "\n"
        "If a plan genuinely predates this gate, grandfather it by adding its\n"
        f"repo-relative path to {ALLOWLIST_PATH} (burn-down only — never grow it).\n"
        "\n"
        "See OMN-14476 / OMN-14475.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
