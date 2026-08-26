#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""KB doc gate — block new/regrown non-KB markdown docs in product repos.

OMN-16589. Operator direction (2026-08-26), verbatim: "all we need is a hook
that stops new MD docs from getting created in non kb repos" — plus two
ratified amendments: (1) non-README ``.md`` files must also stay stub-sized,
blocking regrowth-by-edit of an existing pointer stub; (2) functional
markdown (plugin skills/agents/commands/rules, CLAUDE.md, README.md,
community-health files, ``.github/`` templates, test fixtures) is exempt.

This supersedes wiring the knowledge-base-hosted, manifest-driven
``docs-drift-guard-reusable.yml`` into product repos: that guard needs a live
manifest fetched from ``knowledge-base@main`` at run time (a single point of
failure fanning out to every wired repo) and only covers repos with existing
migrated-doc rows. This gate needs no repo inventory or external manifest —
it evaluates the PR/commit diff directly, so it applies to any product repo,
migrated or not.

## Behavior

FAILS when a changed ``.md`` file is:

  (a) **NEW** and not exempt, or
  (b) **existing** (modified in place), not exempt, not the repo-root
      ``README.md``, and exceeds the stub-size cap (``STUB_LINE_CAP`` lines)
      — only enforced in ``strict`` mode.

Renames and deletions are always allowed regardless of content or mode.

## Modes

  transition (default) — new-file block only. For repos not yet stripped
    down to pointer stubs by the Wave-4 KB migration.
  strict — new-file block + stub-size cap. For repos already stripped.

## Exemptions

A shared default set is baked into this script (``DEFAULT_EXEMPTIONS``
below). A repo may add its own path globs via a ``.kb-doc-gate.yaml`` file at
its root — additive only, the defaults always apply. The same file may set
``mode: strict`` to opt a repo into the size cap; an explicit ``--mode`` CLI
argument is the fallback when the repo carries no config file (or the config
file does not set ``mode``), never an override of a config-file mode.

    # .kb-doc-gate.yaml
    mode: strict
    exemptions:
      - "docs/adr/**"
      - "docs/decisions/*.md"

Only a restricted subset of YAML is supported (see ``load_config`` below) —
this script is stdlib-only, no PyYAML dependency.

## Usage

Pre-commit (staged-file mode, invoked once per commit with the staged
markdown files as positional args — status is read from the index vs HEAD):

    kb_doc_gate.py --staged FILE [FILE ...]

CI (ref-diff mode, invoked against a full or partially-fetched checkout):

    kb_doc_gate.py --base-ref origin/dev --head-ref HEAD

## Exit codes

  0 — no violations (or nothing to evaluate)
  1 — one or more violations
  2 — usage error (e.g. neither --staged nor --base-ref given)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

STUB_LINE_CAP = 30

# Root-anchored: only the top-level README is presumed load-bearing (GitHub
# renders it, contributors expect it). Nested READMEs (src/README.md, etc.)
# are NOT automatically exempt — they are ordinary docs subject to both checks.
DEFAULT_EXEMPTIONS: tuple[str, ...] = (
    "README.md",
    "**/CLAUDE.md",
    "**/.claude/**",
    "**/.github/**",
    "**/skills/**",
    "**/agents/**",
    "**/commands/**",
    "**/rules/**",
    "**/hooks/**",
    "**/LICENSE*",
    "**/SECURITY.md",
    "**/CODE_OF_CONDUCT.md",
    "**/CONTRIBUTING.md",
    "**/CHANGELOG.md",
    "**/tests/**",
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


def is_exempt(path: str, patterns: tuple[str, ...]) -> bool:
    return any(_compile_glob(pattern).match(path) is not None for pattern in patterns)


# ---------------------------------------------------------------------------
# Config loading — restricted stdlib-only YAML subset
# ---------------------------------------------------------------------------


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_config(path: Path) -> tuple[str | None, tuple[str, ...]]:
    """Parse a repo's ``.kb-doc-gate.yaml``.

    Returns ``(mode, extra_exemptions)``. ``mode`` is ``None`` when the file
    is absent or does not set ``mode`` — callers apply their own default in
    that case, never here, so config-file precedence stays unambiguous.

    Supports only:

        mode: strict|transition
        exemptions:
          - "glob/pattern/**"
          - 'another/pattern'

    Full-line ``#`` comments and blank lines are ignored; anything else is a
    hard error (fail closed on a config the parser cannot understand, rather
    than silently ignoring part of it).
    """
    if not path.is_file():
        return None, ()

    mode: str | None = None
    exemptions: list[str] = []
    section: str | None = None

    for lineno, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            if section != "exemptions":
                raise ValueError(
                    f"{path}:{lineno}: list item outside an 'exemptions:' section"
                )
            exemptions.append(_strip_quotes(line[2:].strip()))
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key == "mode":
                value = _strip_quotes(value)
                if value not in ("transition", "strict"):
                    raise ValueError(
                        f"{path}:{lineno}: mode must be 'transition' or 'strict', got {value!r}"
                    )
                mode = value
                section = None
                continue
            if key == "exemptions":
                if value:
                    raise ValueError(
                        f"{path}:{lineno}: 'exemptions:' must be followed by a '- ' list, not an inline value"
                    )
                section = "exemptions"
                continue
            raise ValueError(
                f"{path}:{lineno}: unknown key {key!r} (expected 'mode' or 'exemptions')"
            )
        raise ValueError(f"{path}:{lineno}: unrecognized line: {raw!r}")

    return mode, tuple(exemptions)


# ---------------------------------------------------------------------------
# Git plumbing
# ---------------------------------------------------------------------------


def _git_name_status(repo_root: Path, *diff_args: str) -> list[ChangedFile]:
    proc = subprocess.run(
        ["git", "diff", "--no-color", "--name-status", "-M", *diff_args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    changed: list[ChangedFile] = []
    for line in proc.stdout.splitlines():
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


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _line_count(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, IsADirectoryError):
        return 0
    if text == "":
        return 0
    return len(text.splitlines())


def evaluate(
    changed: list[ChangedFile],
    *,
    mode: str,
    extra_exemptions: tuple[str, ...],
    repo_root: Path,
) -> list[Violation]:
    patterns = DEFAULT_EXEMPTIONS + tuple(extra_exemptions)
    violations: list[Violation] = []

    for cf in changed:
        if not cf.path.lower().endswith(".md"):
            continue
        if cf.status == "D":
            continue  # deletions always allowed
        if cf.status in ("R", "C"):
            continue  # renames/copies always allowed regardless of content
        if is_exempt(cf.path, patterns):
            continue
        if cf.status == "A":
            violations.append(
                Violation(
                    cf.path, "new non-KB markdown file (not in the exemption set)"
                )
            )
            continue
        # Everything else (M, T, and any other git status) is "modified in
        # place" semantics: only checked under strict mode's stub-size cap.
        if mode == "strict":
            line_count = _line_count(repo_root / cf.path)
            if line_count > STUB_LINE_CAP:
                violations.append(
                    Violation(
                        cf.path,
                        f"modified doc exceeds the {STUB_LINE_CAP}-line stub cap "
                        f"({line_count} lines) in strict mode",
                    )
                )

    return violations


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--mode",
        choices=["transition", "strict"],
        default=None,
        help="fallback mode when the repo's .kb-doc-gate.yaml does not set 'mode' (default: transition)",
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
        help="pre-commit mode: evaluate staged FILES (positional) against HEAD",
    )
    parser.add_argument(
        "--base-ref", default=None, help="CI mode: diff base ref, e.g. origin/dev"
    )
    parser.add_argument(
        "--head-ref", default="HEAD", help="CI mode: diff head ref (default: HEAD)"
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
        file_mode, extra_exemptions = load_config(config_path)
    except ValueError as exc:
        print(f"kb-doc-gate: config error: {exc}", file=sys.stderr)
        return 2

    mode = file_mode or args.mode or "transition"

    if args.staged:
        changed = staged_changed_files(repo_root, args.files)
    elif args.base_ref:
        changed = ref_diff_changed_files(repo_root, args.base_ref, args.head_ref)
    else:
        print("kb-doc-gate: one of --staged or --base-ref is required", file=sys.stderr)
        return 2

    violations = evaluate(
        changed, mode=mode, extra_exemptions=extra_exemptions, repo_root=repo_root
    )

    if not violations:
        print(
            f"kb-doc-gate: OK ({mode} mode, {len(changed)} changed file(s) inspected)"
        )
        return 0

    print(
        f"kb-doc-gate: FAILED ({mode} mode) — {len(violations)} violation(s):",
        file=sys.stderr,
    )
    for v in violations:
        print(f"  {v.path}: {v.reason}", file=sys.stderr)
    print(
        "Canonical docs live in the knowledge-base repo. New/regrown local markdown is "
        "blocked outside the exemption set — see omniclaude/scripts/kb_doc_gate.py "
        "DEFAULT_EXEMPTIONS, or add a repo-scoped .kb-doc-gate.yaml (OMN-16589).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
