#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""KB doc gate — keep product-repo markdown inside the allowed set.

OMN-16589 built the pilot; OMN-17172 rolls it to the fleet and flips it to a
required status check. This module is the canonical validator for both.

Operator ruling (2026-09-01) that this file implements verbatim — the list of
markdown that is **ALLOWED TO REMAIN** in a product repo, everything else
being "documentation that must leave" (its home is the knowledge-base repo):

  * root ``README.md`` (which must link to the knowledge base)
  * ``CLAUDE.md`` at the repo root, or anything under ``.claude/``
  * ``CHANGELOG*.md``
  * ``LICENSE*``
  * ``SECURITY.md`` at the repo root (only because GitHub looks for it there)
  * ``.github/**`` (issue/PR templates)
  * markdown that is executable agent configuration: any ``skills/**``,
    ``commands/**`` or ``agents/**`` directory used by Claude Code
  * test fixtures under ``tests/**/fixtures/**``, ``tests/**/data/**`` or
    ``tests/**/golden/**`` that a test reads as data

A repo-specific addition (``omniclaude``'s ``plugins/**``, say) goes in that
repo's own ``.kb-doc-gate.yaml``, not in this default.

**A pointer stub is not a removal.** A file whose whole content is "moved to
the knowledge base" is documentation that still exists; the root README's
knowledge-base link carries that signposting role for the entire repo. This is
why the gate has no stub-size allowance: a doc outside the allowed set is a
violation at any length. (The OMN-16589 pilot had a 30-line ``STUB_LINE_CAP``
that let a shrunken doc stay forever. The ruling above removes it.)

## Modes

``diff`` (default)
    Fails when a changed ``.md`` file's **post-image** path is outside the
    allowed set — additions and in-place modifications alike. Deletions are
    always fine (that is the migration doing its job). A rename or copy is
    judged on its DESTINATION path: moving a stray doc to another stray path
    keeps it in the repo, and treating that as exempt would be a one-command
    bypass of the whole gate; moving it *into* the allowed set passes.

``strict``
    Fails when **any** tracked markdown file on the branch is outside the
    allowed set, whether or not this change touched it. This is the end-state
    mode for a repo whose Wave-4 migration (epic OMN-16602) has landed; it is
    what keeps a scrubbed repo scrubbed. Turning it on before that repo's
    migration lands blocks every unrelated PR, so it is opt-in per repo.

## Configuration

``.kb-doc-gate.yaml`` at the consuming repo's root — absent means "default
allowed set, ``diff`` mode":

    # .kb-doc-gate.yaml
    mode: strict
    allowed:
      - "plugins/**"
      - "docs/adr/**"

``allowed:`` is ADDITIVE — the defaults above always apply on top of it. A
``mode:`` in this file always wins over the ``--mode`` CLI argument, which is
only the fallback for a repo that ships no config file.

Only that restricted YAML subset is supported (see :func:`load_config`); this
script is stdlib-only on purpose, so it can run from a bare checkout with no
dependency install step.

## Usage

Pre-commit (staged-file mode — status is read from the index vs HEAD)::

    kb_doc_gate.py --staged FILE [FILE ...]

CI (ref-diff mode, three-dot/merge-base semantics matching the PR diff)::

    kb_doc_gate.py --base-ref origin/dev --head-ref HEAD

In ``strict`` mode neither is consulted: the check is a whole-tree scan of
``git ls-files``, which is the index under pre-commit and the branch content
under CI — the same answer from both call sites.

## Exit codes

  0 — no violations
  1 — one or more violations
  2 — usage or config error (the gate did not run; never read as a pass)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MODES = ("diff", "strict")

# The operator ruling's allowed set, as path globs. Root-anchored patterns are
# deliberate: only the TOP-LEVEL README.md and SECURITY.md are presumed
# load-bearing (GitHub renders them there). A nested README.md is an ordinary
# doc and must leave with the rest.
#
# Not present, and deliberately so: CONTRIBUTING.md and CODE_OF_CONDUCT.md at
# the repo root (the ruling allows SECURITY.md only, "if GitHub requires it
# there"; both of the others are still allowed under `.github/`, which is
# where GitHub also reads them from), `rules/**` and `hooks/**` (named by the
# OMN-16589 pilot default but not by the ruling), and a blanket `tests/**`
# (narrowed to the three fixture subtrees the ruling names).
DEFAULT_ALLOWED: tuple[str, ...] = (
    "README.md",
    "CLAUDE.md",
    "**/.claude/**",
    "**/CHANGELOG*.md",
    "**/LICENSE*",
    "SECURITY.md",
    "**/.github/**",
    "**/skills/**",
    "**/commands/**",
    "**/agents/**",
    "**/tests/**/fixtures/**",
    "**/tests/**/data/**",
    "**/tests/**/golden/**",
)


@dataclass(frozen=True)
class Violation:
    path: str
    reason: str


@dataclass(frozen=True)
class ChangedFile:
    status: str  # single-letter git status: A, M, D, R, C, T, ... (rename % stripped)
    path: str  # new/current path, POSIX-style, relative to repo root
    old_path: str | None = None  # only set for R/C


# ---------------------------------------------------------------------------
# Glob matching (stdlib-only; supports '**' across path separators)
# ---------------------------------------------------------------------------

_GLOB_CACHE: dict[str, re.Pattern[str]] = {}


def _glob_to_regex(pattern: str) -> str:
    parts: list[str] = ["^"]
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern[i : i + 3] == "**/":
                parts.append("(?:.*/)?")
                i += 3
                continue
            if pattern[i : i + 2] == "**":
                parts.append(".*")
                i += 2
                continue
            parts.append("[^/]*")
            i += 1
            continue
        if c == "?":
            parts.append("[^/]")
            i += 1
            continue
        parts.append(re.escape(c))
        i += 1
    parts.append("$")
    return "".join(parts)


def _compile_glob(pattern: str) -> re.Pattern[str]:
    compiled = _GLOB_CACHE.get(pattern)
    if compiled is None:
        compiled = re.compile(_glob_to_regex(pattern))
        _GLOB_CACHE[pattern] = compiled
    return compiled


def is_allowed(path: str, patterns: tuple[str, ...]) -> bool:
    return any(_compile_glob(pattern).match(path) is not None for pattern in patterns)


def is_markdown(path: str) -> bool:
    return path.lower().endswith(".md")


# ---------------------------------------------------------------------------
# Config loading — restricted stdlib-only YAML subset
# ---------------------------------------------------------------------------


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_config(path: Path) -> tuple[str | None, tuple[str, ...]]:
    """Parse a repo's ``.kb-doc-gate.yaml``.

    Returns ``(mode, extra_allowed)``. ``mode`` is ``None`` when the file is
    absent or does not set ``mode`` — callers apply their own default in that
    case, never here, so config-file precedence stays unambiguous.

    Supports only::

        mode: diff|strict
        allowed:
          - "glob/pattern/**"
          - 'another/pattern'

    Full-line ``#`` comments and blank lines are ignored; anything else is a
    hard error (fail closed on a config the parser cannot understand, rather
    than silently ignoring part of it).
    """
    if not path.is_file():
        return None, ()

    mode: str | None = None
    allowed: list[str] = []
    section: str | None = None

    for lineno, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            if section != "allowed":
                raise ValueError(
                    f"{path}:{lineno}: list item outside an 'allowed:' section"
                )
            allowed.append(_strip_quotes(line[2:].strip()))
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key == "mode":
                value = _strip_quotes(value)
                if value not in MODES:
                    raise ValueError(
                        f"{path}:{lineno}: mode must be one of {MODES}, got {value!r}"
                    )
                mode = value
                section = None
                continue
            if key == "allowed":
                if value:
                    raise ValueError(
                        f"{path}:{lineno}: 'allowed:' must be followed by a '- ' list, not an inline value"
                    )
                section = "allowed"
                continue
            raise ValueError(
                f"{path}:{lineno}: unknown key {key!r} (expected 'mode' or 'allowed')"
            )
        raise ValueError(f"{path}:{lineno}: unrecognized line: {raw!r}")

    return mode, tuple(allowed)


# ---------------------------------------------------------------------------
# Git plumbing
# ---------------------------------------------------------------------------


def _git(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def _git_name_status(repo_root: Path, *diff_args: str) -> list[ChangedFile]:
    out = _git(repo_root, "diff", "--no-color", "--name-status", "-M", *diff_args)
    changed: list[ChangedFile] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0][0]  # strip similarity suffix, e.g. "R100" -> "R"
        if status in ("R", "C") and len(parts) >= 3:
            changed.append(ChangedFile(status=status, path=parts[2], old_path=parts[1]))
        else:
            changed.append(ChangedFile(status=status, path=parts[1]))
    return changed


def staged_changed_files(repo_root: Path, files: list[str]) -> list[ChangedFile]:
    """Pre-commit mode: staged files (index) vs HEAD."""
    all_staged = _git_name_status(repo_root, "--cached")
    if not files:
        return all_staged
    wanted = {str(Path(f).as_posix()) for f in files}
    return [
        cf
        for cf in all_staged
        if cf.path in wanted or (cf.old_path is not None and cf.old_path in wanted)
    ]


def ref_diff_changed_files(
    repo_root: Path, base_ref: str, head_ref: str
) -> list[ChangedFile]:
    """CI mode: diff between two refs, merge-base semantics (matches PR diffs)."""
    return _git_name_status(repo_root, f"{base_ref}...{head_ref}")


def tracked_markdown(repo_root: Path) -> list[str]:
    """Every tracked markdown path on the branch, POSIX-style, repo-relative.

    ``git ls-files`` reads the INDEX, which is the right answer at both call
    sites: under pre-commit the index is what is about to become the commit,
    and under CI the index of a fresh checkout is the branch content. Listing
    is unfiltered by pathspec and filtered in Python instead, because a
    ``*.md`` pathspec is case-sensitive on a case-sensitive filesystem and
    would miss a ``.MD`` file on Linux while catching it on macOS.
    """
    out = _git(repo_root, "ls-files", "-z")
    return sorted(p for p in out.split("\0") if p and is_markdown(p))


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def evaluate_diff(
    changed: list[ChangedFile], *, allowed: tuple[str, ...]
) -> list[Violation]:
    """``diff`` mode: any changed markdown whose post-image is outside the set.

    Deletions are the only status that is always fine. A rename/copy is judged
    on its destination, so ``git mv docs/a.md docs/b.md`` cannot launder a doc
    past the gate.
    """
    violations: list[Violation] = []
    for cf in changed:
        if not is_markdown(cf.path):
            continue
        if cf.status == "D":
            continue
        if is_allowed(cf.path, allowed):
            continue
        if cf.status == "A":
            reason = "new markdown file outside the allowed set"
        elif cf.status in ("R", "C"):
            reason = (
                f"markdown moved to a path outside the allowed set (from {cf.old_path})"
            )
        else:
            reason = "existing markdown outside the allowed set was modified"
        violations.append(Violation(cf.path, reason))
    return violations


def evaluate_tree(paths: list[str], *, allowed: tuple[str, ...]) -> list[Violation]:
    """``strict`` mode: any tracked markdown on the branch outside the set."""
    return [
        Violation(path, "markdown outside the allowed set exists on this branch")
        for path in paths
        if not is_allowed(path, allowed)
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--mode",
        choices=list(MODES),
        default=None,
        help="fallback mode when the repo's .kb-doc-gate.yaml does not set 'mode' (default: diff)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="path to .kb-doc-gate.yaml (default: <repo-root>/.kb-doc-gate.yaml)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(),
        help="repo root for resolving relative paths, the default config path, and git invocations",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="diff mode: evaluate staged FILES (positional) against HEAD",
    )
    parser.add_argument(
        "--base-ref", default=None, help="diff mode: diff base ref, e.g. origin/dev"
    )
    parser.add_argument(
        "--head-ref", default="HEAD", help="diff mode: diff head ref (default: HEAD)"
    )
    parser.add_argument(
        "files", nargs="*", help="staged files to evaluate (only used with --staged)"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = args.repo_root.resolve()
    config_path = args.config or (repo_root / ".kb-doc-gate.yaml")

    try:
        file_mode, extra_allowed = load_config(config_path)
    except ValueError as exc:
        print(f"kb-doc-gate: config error: {exc}", file=sys.stderr)
        return 2

    mode = file_mode or args.mode or "diff"
    allowed = DEFAULT_ALLOWED + tuple(extra_allowed)

    if mode == "strict":
        paths = tracked_markdown(repo_root)
        violations = evaluate_tree(paths, allowed=allowed)
        inspected = f"{len(paths)} tracked markdown file(s)"
    else:
        if args.staged:
            changed = staged_changed_files(repo_root, args.files)
        elif args.base_ref:
            changed = ref_diff_changed_files(repo_root, args.base_ref, args.head_ref)
        else:
            print(
                "kb-doc-gate: diff mode needs one of --staged or --base-ref",
                file=sys.stderr,
            )
            return 2
        violations = evaluate_diff(changed, allowed=allowed)
        inspected = f"{len(changed)} changed file(s)"

    if not violations:
        print(f"kb-doc-gate: OK ({mode} mode, {inspected} inspected)")
        return 0

    print(
        f"kb-doc-gate: FAILED ({mode} mode) — {len(violations)} violation(s):",
        file=sys.stderr,
    )
    for v in violations:
        print(f"  {v.path}: {v.reason}", file=sys.stderr)
    print(
        "Canonical docs live in the knowledge-base repo, not here. Move the content "
        "there and DELETE the local file — a pointer stub is not a removal, the root "
        "README's knowledge-base link already carries that role. Genuinely local, "
        "repo-specific markdown goes in the allowed set: see DEFAULT_ALLOWED in "
        "omniclaude/scripts/kb_doc_gate.py, or add a path glob under 'allowed:' in "
        "this repo's .kb-doc-gate.yaml (OMN-16589, OMN-17172).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
