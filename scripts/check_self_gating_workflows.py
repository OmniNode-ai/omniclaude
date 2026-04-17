#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pre-commit gate: block cross-repo @main refs in self-gating workflows.

When a `.github/workflows/*.y{a,}ml` file references another repo's workflow
via `uses: <owner>/<other-repo>/.github/workflows/<name>.yml@main`, the @main
ref resolves to the pre-merge state at CI time. A PR that fixes the referenced
workflow will therefore NEVER apply its own fix to its own CI check — the PR
wedges forever (the 2026-04-17 CR Thread Gate rollout failure, retro §4.8).

This hook runs on every `.github/workflows/*.y{a,}ml` file passed on the
command line (pre-commit invokes it once per staged workflow) and exits 2
on any cross-repo @main ref that is not annotated as an intentional
exception.

## Exit codes

- 0 — all workflow refs OK
- 2 — at least one cross-repo @main ref without an exception annotation

## Exception annotation

To intentionally keep a cross-repo @main ref (e.g., when the target workflow
is NOT a required status check on this repo's main branch), prefix the `uses:`
line with a comment:

    # self-gating-ok: <reason>
    uses: OmniNode-ai/other-repo/.github/workflows/foo.yml@main

The reason is required and must not be empty.

## Refs

- OMN-9039 (this hook)
- OMN-9038 (pre-mutation complement via PreToolUse hook)
- Retro §4.8 chicken-egg analysis
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_USES_RE = re.compile(
    r"""
    ^                                # start of line
    (?P<indent>\s*)                  # indent
    (?P<key>uses\s*:\s*)             # "uses:"
    (?P<value>
        (?P<owner>[A-Za-z0-9_-]+)    # GitHub owner
        /
        (?P<repo>[A-Za-z0-9_.-]+)    # repo name
        /\.github/workflows/
        (?P<workflow>[A-Za-z0-9_.-]+\.ya?ml)
        @
        (?P<ref>\S+)                 # ref (branch/tag/sha)
    )
    \s*$                             # end (ignore trailing ws)
    """,
    re.VERBOSE,
)

_ANNOTATION_RE = re.compile(r"#\s*self-gating-ok\s*:\s*(?P<reason>\S.*?)\s*$")


def _owner_repo_for_workflow(path: Path) -> tuple[str | None, str | None]:
    """Walk up from the workflow file looking for a git remote to infer owner/repo.

    Returns (owner, repo) on success or (None, None) if not resolvable.
    The owner/repo detection is best-effort — when we can't resolve, we treat
    every `<owner>/<repo>` ref as potentially cross-repo and rely on the
    annotation escape for same-repo false positives.
    """
    # For MVP we do NOT probe git; we rely on the "cross-repo @main" signature
    # being the trigger. Same-repo authors who use the full form get the same
    # actionable error and are told to switch to `./`. Noise is acceptable
    # because the fix (`./`) is also better than full-path @main even on
    # self-refs.
    return (None, None)


def _scan_file(path: Path) -> list[str]:
    """Return a list of violation messages for path; empty list = clean."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{path}: could not read file: {exc}"]

    violations: list[str] = []
    prev_annotation_line: int | None = None
    for idx, raw in enumerate(lines, start=1):
        ann_match = _ANNOTATION_RE.search(raw)
        if ann_match is not None:
            prev_annotation_line = idx
            continue

        # Allow comment-only lines without annotation to reset the flag too,
        # but keep blank lines AND non-comment lines scannable.
        stripped = raw.strip()
        is_comment = stripped.startswith("#") and ann_match is None

        m = _USES_RE.match(raw)
        if m is None:
            # Only clear annotation when we hit a non-blank, non-comment line
            # that isn't itself a `uses:`. That way `# annotation\n  uses: …`
            # with intervening blanks/comments still honors the annotation.
            if stripped and not is_comment and idx != prev_annotation_line:
                prev_annotation_line = None
            continue

        ref = m.group("ref")
        if ref != "main":
            # @sha or @v1.0.0 etc — pinned, safe.
            continue

        # Check whether the immediately previous non-blank line was the
        # self-gating-ok annotation.
        if prev_annotation_line is not None and (idx - prev_annotation_line) <= 3:
            # Allowed with annotation; require that the reason was non-empty.
            prev_line = lines[prev_annotation_line - 1]
            prev_ann_match = _ANNOTATION_RE.search(prev_line)
            if prev_ann_match and prev_ann_match.group("reason").strip():
                # OK
                prev_annotation_line = None
                continue

        owner = m.group("owner")
        repo = m.group("repo")
        workflow = m.group("workflow")
        violations.append(
            f"{path}:{idx}: cross-repo @main ref in self-gating workflow\n"
            f"  uses: {owner}/{repo}/.github/workflows/{workflow}@main\n"
            f"\n"
            f"  Cross-repo @main refs in .github/workflows/ resolve to the\n"
            f"  pre-merge state at CI time. A PR that fixes the referenced\n"
            f"  workflow will never apply its own fix to its own CI check\n"
            f"  (retro §4.8, OMN-9039).\n"
            f"\n"
            f"  Fix — switch to local path:\n"
            f"    uses: ./.github/workflows/{workflow}\n"
            f"\n"
            f"  OR annotate an intentional exception (the target is NOT a\n"
            f"  required status check on this repo's main branch):\n"
            f"    # self-gating-ok: <reason>\n"
            f"    uses: {owner}/{repo}/.github/workflows/{workflow}@main\n"
        )
        prev_annotation_line = None

    return violations


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv[1:]]
    if not files:
        return 0

    all_violations: list[str] = []
    for path in files:
        if not path.exists():
            continue
        all_violations.extend(_scan_file(path))

    if not all_violations:
        return 0

    sys.stderr.write(
        "BLOCKED: self-gating workflow @main ref(s) detected ("
        f"{len(all_violations)} violation(s)):\n\n"
    )
    for msg in all_violations:
        sys.stderr.write(msg)
        sys.stderr.write("\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
