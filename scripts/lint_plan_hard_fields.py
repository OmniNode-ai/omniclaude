#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Lint gate: plan hard fields — D-5 enforcement (OMN-13051).

Three mechanical invariants derived from the 2026-06-11 process-failure
retro (§3.D, retro D-5):

**Rule 1 — P0/P1 items with runtime-dep words require a precondition probe**

Any plan item marked P0 or P1 whose text contains a runtime-optimism
keyword ("merged", "rides the rebuild", "rides the deploy", etc.) must have
a ``precondition-probe:`` annotation within five lines of the item.
Format::

    precondition-probe: <YYYY-MM-DD>[T<HH:MM>Z] <lane>/<surface> via <command>

e.g.::

    precondition-probe: 2026-06-12T14:30Z stability/v1/health via curl http://...

"Same-day-battery-from-source-optimism" is not expressible without a probe.

**Rule 2 — Deliverable sections need an Artifact Manifest**

If a plan contains a heading matching a deliverable-section pattern
(``## Deliverables``, ``## Files to Create``, ``## Files to Create/Modify``,
``## Files to Modify``, ``## Output Files``, ``## Artifacts``) AND that
section lists file paths (lines containing a backtick-quoted path with a
slash), the plan must also contain an ``## Artifact Manifest`` section.

**Rule 3 — Artifact Manifest entries require explicit status**

Each list item (``- ``/``* ``-prefixed) or table row (``|``-prefixed)
inside ``## Artifact Manifest`` must carry an explicit status:
``[x]``/``[X]`` (done), ``DONE``, ``SKIPPED:``, ``DEFERRED:``, or
``BLOCKED-ON:`` (case-insensitive).  Header/separator rows are exempt.
Blank lines and plain-text commentary lines (not starting with ``-``/``*``/
``|``) are also exempt.

## Exit codes

- 0 — all checks pass
- 1 — one or more violations; details written to stderr
- 2 — bad arguments

## Usage

- Pre-commit: invoked with staged markdown paths as positional arguments.
  Only paths under ``docs/plans/`` or ``docs/tracking/`` are checked; others
  are silently ignored.
- CI: invoked with no path arguments; scans the full plan/tracking tree.

Fails closed on unreadable / non-UTF-8 files (same policy as the sibling
``lint_plan_verified_state.py`` gate).

## Refs

- OMN-13051 (this gate)
- OMN-13013 (epic: process enforcement ratchets)
- docs/evidence/2026-06-11-architecture-investigation/PROCESS_FAILURE_RETRO.md §3.D
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PLAN_ROOTS: tuple[Path, ...] = (Path("docs/plans"), Path("docs/tracking"))

# ---------------------------------------------------------------------------
# Rule 1 — P0/P1 runtime-dep probe patterns
# ---------------------------------------------------------------------------

# A P0/P1 marker on a line (table cell, bullet prefix, or standalone label).
# Matches e.g. "P0:", "**P0**:", "| P0 |", "- P0:", "- **P1** --", "P1 --"
# The trailing separator is colon, hyphen, en-dash (U+2013), or em-dash (U+2014).
_DASH_SEP = ":\\-\u2013\u2014"  # colon / hyphen / en-dash (U+2013) / em-dash (U+2014)
_P0P1_MARKER_RE = re.compile(
    r"(?:"
    r"\|[^|]*\bP[01]\b[^|]*\|"  # table cell
    r"|^\s*[-*+]\s+\*{0,2}P[01]\*{0,2}\s*[" + _DASH_SEP + r"]"  # bullet item prefix
    r"|^\s*\*{0,2}P[01]\*{0,2}\s*[" + _DASH_SEP + r"]"  # standalone P0/P1 line
    r")",
    re.MULTILINE,
)

# Keywords that indicate the item depends on an unverified runtime state.
_RUNTIME_DEP_PATTERNS: tuple[str, ...] = (
    r"\bonce\s+merged\b",
    r"\bafter\s+merge\b",
    r"\bafter\s+merging\b",
    r"\brides?\s+the\s+rebuild\b",
    r"\brides?\s+the\s+deploy\b",
    r"\brides?\s+the\s+redeploy\b",
    r"\brides?\s+rebuild\b",
    r"\brides?\s+deploy\b",
    r"\bon\s+next\s+rebuild\b",
    r"\brebuild\s+picks?\s+up\b",
    r"\brebuild\s+will\s+pick\s+up\b",
    r"\bafter\s+deploy\b",
    r"\bafter\s+redeploy\b",
    r"\bafter\s+restart\b",
    r"\bonce\s+it\s+lands\b",
    r"\bonce\s+it\s+merges?\b",
    r"\bsame.day\s+battery\b",
    r"\bwill\s+be\s+available\s+after\b",
)

_RUNTIME_DEP_RE = re.compile(
    "|".join(_RUNTIME_DEP_PATTERNS),
    re.IGNORECASE,
)

# precondition-probe annotation line.
# Format: precondition-probe: <YYYY-MM-DD>[T<HH:MM>Z] <lane>/<surface> via <cmd>
_PROBE_RE = re.compile(
    r"^\s*precondition-probe:\s+\d{4}-\d{2}-\d{2}",
    re.IGNORECASE,
)

# How many lines below a P0/P1 item we search for the probe annotation.
_PROBE_WINDOW = 5

# ---------------------------------------------------------------------------
# Rule 2 — deliverable section → artifact manifest required
# ---------------------------------------------------------------------------

# Headings that introduce a deliverable/artifact section.
_DELIVERABLE_HEADING_RE = re.compile(
    r"^#{1,6}\s+"
    r"(?:deliverables?|artifacts?|files?\s+to\s+create(?:/modify)?|"
    r"files?\s+to\s+modify|output\s+files?)"
    r"\b",
    re.IGNORECASE,
)

# A heading of any level (to detect the end of a section).
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)

# Artifact Manifest section heading.
_MANIFEST_HEADING_RE = re.compile(
    r"^#{1,6}\s+artifact\s+manifest\b",
    re.IGNORECASE,
)

# A file path reference inside a line (backtick-quoted path containing a slash).
_FILE_PATH_RE = re.compile(r"`[^`]*\/[^`]+`")

# ---------------------------------------------------------------------------
# Rule 3 — artifact manifest item status
# ---------------------------------------------------------------------------

# Lines that are list items or table rows (require a status annotation).
_MANIFEST_ITEM_RE = re.compile(r"^\s*[-*+]\s+|^\s*\|")

# Table separator rows (exempt from the status requirement).
_TABLE_SEP_RE = re.compile(r"^\s*\|[-| :]+\|\s*$")

# Status markers (any of these satisfies the rule).
# Em-dash variants use \u2014 escape to avoid RUF001 ambiguous-char warning.
_EM_DASH = "\u2014"  # em-dash character for use in regex patterns
_STATUS_RE = re.compile(
    r"\[x\]"  # done checkbox
    r"|\[X\]"  # done checkbox (uppercase)
    r"|\bDONE\b"  # explicit DONE
    r"|\bSKIPPED\s*:"  # skipped with colon
    r"|\bSKIPPED\s*"
    + _EM_DASH  # skipped with em-dash
    + r"|\bDEFERRED\s*:"  # deferred with colon
    r"|\bDEFERRED\s*"
    + _EM_DASH  # deferred with em-dash
    + r"|\bBLOCKED-ON\s*:"  # blocked-on with colon
    r"|\bBLOCKED-ON\s*"
    + _EM_DASH  # blocked-on with em-dash
    + r"|\bBLOCKED\s+ON\s*:"  # blocked on with colon (space variant)
    r"|\bBLOCKED\s+ON\s*" + _EM_DASH,  # blocked on with em-dash (space variant)
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rel_to_repo(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_plan_markdown(path: Path, repo_root: Path) -> bool:
    if path.suffix != ".md":
        return False
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    return rel.parts[:2] in {("docs", "plans"), ("docs", "tracking")}


def _iter_plan_markdown(roots: tuple[Path, ...]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        found.extend(p for p in root.rglob("*.md") if p.is_file())
    return sorted(set(found))


# ---------------------------------------------------------------------------
# Per-file checks
# ---------------------------------------------------------------------------


def _check_rule1_probes(lines: list[str], path: Path) -> list[str]:
    """Rule 1: P0/P1 runtime-dep items need a precondition-probe annotation."""
    violations: list[str] = []
    for idx, line in enumerate(lines):
        if not _P0P1_MARKER_RE.search(line):
            continue
        if not _RUNTIME_DEP_RE.search(line):
            continue
        # Item matches; check the next _PROBE_WINDOW lines for a probe annotation.
        window_end = min(idx + _PROBE_WINDOW + 1, len(lines))
        window = lines[idx:window_end]
        if any(_PROBE_RE.match(wl) for wl in window):
            continue
        lineno = idx + 1
        violations.append(
            f"{path}:{lineno}: P0/P1 item with runtime-dep keyword lacks "
            f"'precondition-probe: <date> <lane>/<surface> via <command>' "
            f"within {_PROBE_WINDOW} lines — see OMN-13051"
        )
    return violations


def _extract_section_lines(
    lines: list[str], heading_re: re.Pattern[str]
) -> list[tuple[int, str]]:
    """Return ``(1-based line number, line)`` pairs inside the matched section.

    Returns the first match only.  The section ends at the next heading of
    equal or higher level or at end-of-file.
    """
    start: int | None = None
    heading_level: int = 0
    result: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        if start is None:
            if heading_re.match(line):
                start = idx
                heading_level = len(line) - len(line.lstrip("#"))
        else:
            # A new heading at equal or higher level ends the section.
            m = _ANY_HEADING_RE.match(line)
            if m and (len(line) - len(line.lstrip("#"))) <= heading_level:
                break
            result.append((idx + 1, line))
    return result


def _check_rule2_manifest(lines: list[str], path: Path) -> list[str]:
    """Rule 2: deliverable sections with file paths need an Artifact Manifest."""
    violations: list[str] = []
    # Find all deliverable section headings.
    for idx, line in enumerate(lines):
        if not _DELIVERABLE_HEADING_RE.match(line):
            continue
        section_content = _extract_section_lines(lines[idx:], _DELIVERABLE_HEADING_RE)
        has_file_paths = any(_FILE_PATH_RE.search(body) for _, body in section_content)
        if not has_file_paths:
            continue
        # Section has file paths — require an Artifact Manifest section anywhere.
        has_manifest = any(_MANIFEST_HEADING_RE.match(ln) for ln in lines)
        if not has_manifest:
            lineno = idx + 1
            violations.append(
                f"{path}:{lineno}: deliverable section with file paths found but "
                f"plan has no '## Artifact Manifest' section — see OMN-13051"
            )
    return violations


def _check_rule3_manifest_status(lines: list[str], path: Path) -> list[str]:
    """Rule 3: every item in ## Artifact Manifest must carry an explicit status."""
    violations: list[str] = []
    # Find the Artifact Manifest section.
    manifest_level: int = 0
    in_manifest = False
    for idx, line in enumerate(lines):
        if not in_manifest:
            if _MANIFEST_HEADING_RE.match(line):
                manifest_level = len(line) - len(line.lstrip("#"))
                in_manifest = True
        else:
            # Check if we've left the section.
            m = _ANY_HEADING_RE.match(line)
            if m and (len(line) - len(line.lstrip("#"))) <= manifest_level:
                in_manifest = False
                continue
            # Skip non-item lines.
            if not _MANIFEST_ITEM_RE.match(line):
                continue
            # Skip table separator rows (|---|---|).
            if _TABLE_SEP_RE.match(line):
                continue
            # Skip table header rows — a table header is a | row whose
            # immediately following non-empty line is a separator row.
            if line.lstrip().startswith("|"):
                next_nonempty = next(
                    (lines[j] for j in range(idx + 1, len(lines)) if lines[j].strip()),
                    "",
                )
                if _TABLE_SEP_RE.match(next_nonempty):
                    continue  # this line is a table header row
            stripped = line.strip()
            if not stripped or stripped in {"-", "*", "+", "|"}:
                continue
            if not _STATUS_RE.search(line):
                lineno = idx + 1
                violations.append(
                    f"{path}:{lineno}: Artifact Manifest item lacks explicit status "
                    f"([x], DONE, SKIPPED:, DEFERRED:, or BLOCKED-ON:) — see OMN-13051"
                )
    return violations


def _scan_file(path: Path) -> tuple[list[str], str | None]:
    """Scan one plan file.

    Returns ``(violations, read_error)``.  ``read_error`` is set (and treated
    as a violation by the caller) when the file cannot be read — failing closed
    so an unreadable plan cannot bypass this blocking gate.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return [], f"{path}: decode error: {exc}"
    except OSError as exc:
        return [], f"{path}: read error: {exc}"

    lines = text.splitlines()
    violations: list[str] = []
    violations.extend(_check_rule1_probes(lines, path))
    violations.extend(_check_rule2_manifest(lines, path))
    violations.extend(_check_rule3_manifest_status(lines, path))
    return violations, None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="lint_plan_hard_fields.py",
        description=(
            "Enforce plan hard fields: precondition probes for P0/P1 runtime-dep "
            "items, artifact manifests for deliverable sections, and explicit status "
            "on manifest entries (OMN-13051 / retro D-5)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: cwd).",
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

    total_violations = 0
    violating_files: list[Path] = []

    for path in sorted(set(targets)):
        if not path.exists():
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
        for msg in violations:
            sys.stderr.write(f"{msg}\n")
            total_violations += 1

    if total_violations == 0:
        return 0

    sys.stderr.write(
        "\n"
        f"BLOCKED: {len(violating_files)} plan file(s) violate D-5 hard-field "
        "requirements (OMN-13051).\n"
        "\n"
        "Rule 1 — P0/P1 items with runtime-dep keywords (merged, rides the rebuild,\n"
        "  after deploy, etc.) must carry a precondition-probe: annotation within\n"
        f"  {_PROBE_WINDOW} lines:\n"
        "    precondition-probe: <YYYY-MM-DD>[T<HH:MM>Z] <lane>/<surface> via <cmd>\n"
        "\n"
        "Rule 2 — Plans with a Deliverables/Files-to-Create section that lists\n"
        "  file paths must also contain an '## Artifact Manifest' section.\n"
        "\n"
        "Rule 3 — Each item in '## Artifact Manifest' must have an explicit status:\n"
        "  [x], DONE, SKIPPED: <reason>, DEFERRED: <reason>, or BLOCKED-ON: <X>.\n"
        "\n"
        "See PROCESS_FAILURE_RETRO.md §3.D and OMN-13051.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
