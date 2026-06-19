#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Lint gate: plan_to_tickets plans must carry a fresh Current Verified State.

``plan_to_tickets`` turns a plan markdown file into Linear tickets. When a plan
asserts system state ("the runtime is wired", "the gate is required") without a
verified baseline, ticketization proceeds on stale assumptions — the exact
failure mode this session repeatedly disproved (doc-asserted state that did not
match live state). See OMN-13336 and
``docs/audits/2026-06-19-ratchet-enforcement-audit.md``.

This gate scans every ``*.md`` file under ``docs/plans/`` and ``docs/tracking/``
and FAILs if a plan lacks a ``Current Verified State`` section containing at
least one ``verified: <date> via <command>`` line dated within ``--max-age-days``
(default 14) of today.

The required line shape (case-insensitive ``verified:`` key)::

    verified: 2026-06-19 via gh pr checks 1781 --repo OmniNode-ai/omniclaude

- ``<date>`` is an ISO ``YYYY-MM-DD`` calendar date.
- ``<command>`` is the literal command run to establish the baseline (any
  non-empty text after ``via``). A same-session proof command, not prose.

## Ratchet semantics

Existing plan/tracking docs that predate this gate are grandfathered via a
baseline allowlist (``.onex_ratchets/plan_verified_state_allowlist.yaml``). The
baseline is burn-down only: a NEW or MODIFIED plan must comply, and the
allowlist must never grow. A plan is exempt only if its repo-relative path is
listed in the allowlist.

## Exit codes

- 0 — every non-allowlisted plan carries a fresh verified-state section
- 1 — one or more plans are missing the section, missing a ``verified:`` line,
  malformed, or stale (older than ``--max-age-days``); or a file is unreadable

## Usage

- Pre-commit: invoked with staged markdown paths passed as arguments. Only
  paths under ``docs/plans/`` or ``docs/tracking/`` are checked; others ignored.
- CI: invoked with no path arguments; scans the full plan/tracking tree.

Both surfaces fail closed: an unreadable or non-UTF-8 plan is a violation, never
a silent skip.

## Refs

- OMN-13336 (this gate)
- OMN-13325 (parent: ratchet enforcement retro R1)
- docs/audits/2026-06-19-ratchet-enforcement-audit.md
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

DEFAULT_MAX_AGE_DAYS = 14

PLAN_ROOTS: tuple[Path, ...] = (Path("docs/plans"), Path("docs/tracking"))
ALLOWLIST_PATH = Path(".onex_ratchets/plan_verified_state_allowlist.yaml")

# Section heading: "## Current Verified State" (any heading level, any trailing
# text). Case-insensitive on the phrase.
_SECTION_RE = re.compile(
    r"^#{1,6}\s+current\s+verified\s+state\b",
    re.IGNORECASE,
)

# "verified: <YYYY-MM-DD> via <command>" — the key is case-insensitive, the date
# is a strict ISO calendar date, and the command is any non-empty remainder.
_VERIFIED_RE = re.compile(
    r"^\s*verified:\s*(\d{4}-\d{2}-\d{2})\s+via\s+(\S.*\S|\S)\s*$",
    re.IGNORECASE,
)


def _parse_iso_date(value: str) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        return None


def _load_allowlist(root: Path) -> set[str]:
    """Read the grandfather allowlist.

    The allowlist is a tiny YAML document of the form::

        allowed:
          - docs/plans/legacy-plan.md
          - docs/tracking/old-tracking.md

    Parsed without a YAML dependency (the file is intentionally a flat list of
    ``- path`` entries under an ``allowed:`` key) so the gate has no import-time
    requirements beyond the stdlib. Lines that are blank, comments, or the
    ``allowed:`` header are ignored.
    """
    path = root / ALLOWLIST_PATH
    if not path.exists():
        return set()
    allowed: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        # An unreadable allowlist must not silently exempt everything; treat as
        # empty so the gate fails closed on any otherwise-violating plan.
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


def _scan_file(
    path: Path, today: _dt.date, max_age_days: int
) -> tuple[list[str], str | None]:
    """Scan one plan file.

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

    lines = text.splitlines()

    has_section = any(_SECTION_RE.match(line) for line in lines)
    if not has_section:
        return [
            f"{path}: missing required '## Current Verified State' section",
        ], None

    fresh_dates: list[_dt.date] = []
    malformed_after_key: list[tuple[int, str]] = []
    any_verified_key = False
    for idx, line in enumerate(lines, start=1):
        # Only consider lines whose first non-space token is the verified key,
        # so prose mentioning the word "verified" elsewhere is not misread.
        if not re.match(r"^\s*verified:", line, re.IGNORECASE):
            continue
        any_verified_key = True
        match = _VERIFIED_RE.match(line)
        if match is None:
            malformed_after_key.append((idx, line.rstrip()))
            continue
        parsed = _parse_iso_date(match.group(1))
        if parsed is None:
            malformed_after_key.append((idx, line.rstrip()))
            continue
        if parsed > today:
            # A future-dated proof is not a valid baseline.
            malformed_after_key.append(
                (idx, f"{line.rstrip()}  (future date not allowed)")
            )
            continue
        if (today - parsed).days <= max_age_days:
            fresh_dates.append(parsed)

    if not any_verified_key:
        return [
            f"{path}: 'Current Verified State' section has no "
            "'verified: <date> via <command>' line",
        ], None

    if fresh_dates:
        return [], None

    # Has a verified key but nothing fresh/well-formed: report why.
    violations: list[str] = []
    if malformed_after_key:
        for line_no, raw in malformed_after_key:
            violations.append(f"{path}:{line_no}: malformed verified line: {raw}")
    violations.append(
        f"{path}: no 'verified: <date> via <command>' line within "
        f"{max_age_days} days of {today.isoformat()}"
    )
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
        prog="lint_plan_verified_state.py",
        description=(
            "Fail when a plan_to_tickets plan lacks a fresh "
            "'Current Verified State' section (OMN-13336)."
        ),
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help=f"Max age in days for a verified: line (default {DEFAULT_MAX_AGE_DAYS}).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root used to resolve plan paths and the allowlist.",
    )
    parser.add_argument(
        "--today",
        type=str,
        default=None,
        help="Override today's date (YYYY-MM-DD) for deterministic testing.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Plan markdown paths (pre-commit). Empty → scan full tree (CI).",
    )
    args = parser.parse_args(argv[1:])

    if args.max_age_days < 0:
        sys.stderr.write("--max-age-days must be >= 0\n")
        return 2

    repo_root: Path = args.repo_root
    if args.today is not None:
        today = _parse_iso_date(args.today)
        if today is None:
            sys.stderr.write(f"--today is not a valid ISO date: {args.today}\n")
            return 2
    else:
        # UTC-anchored so the freshness window is machine-timezone independent.
        today = _dt.datetime.now(tz=_dt.UTC).date()

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
        violations, read_error = _scan_file(path, today, args.max_age_days)
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
        f"BLOCKED: {len(violating_files)} plan file(s) consumed by "
        "plan_to_tickets lack a fresh 'Current Verified State' section.\n"
        "\n"
        "Every plan under docs/plans/ or docs/tracking/ must carry a\n"
        "'## Current Verified State' section with at least one line of the form:\n"
        "\n"
        "    verified: <YYYY-MM-DD> via <command-you-ran>\n"
        "\n"
        f"dated within {args.max_age_days} days. The command is the same-session\n"
        "proof that established the baseline (e.g. a gh/psql/rpk probe), not\n"
        "prose. This blocks ticketizing plans built on stale doc-asserted state.\n"
        "\n"
        "If a plan genuinely predates this gate, grandfather it by adding its\n"
        f"repo-relative path to {ALLOWLIST_PATH} (burn-down only — never grow it).\n"
        "\n"
        "See OMN-13336 / docs/audits/2026-06-19-ratchet-enforcement-audit.md.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
