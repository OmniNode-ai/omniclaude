#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Dependency-provenance gate: forbid unreleased first-party git overrides.

A `[tool.uv.sources]` git override that pins a first-party runtime package
(``omnibase-core`` / ``omnibase-spi`` / ``omnibase-compat``) to a **git rev or
branch** resolves that dependency from arbitrary un-released source at build/CI
time. omnibase_infra PR #2184 merged such ``rev=`` overrides to ``dev`` and all
~60 CI checks passed *because* CI resolved core/spi from those exact commits —
the released-wheel contract was silently bypassed. This gate closes that hole.

## Policy

For ``omnibase-core`` / ``omnibase-spi`` / ``omnibase-compat`` (hyphen OR
underscore spelling) under ``[tool.uv.sources]``:

- ``rev = ...``    → HARD FAIL. Key-based, NOT value-shape-based: a tag-shaped
                     value such as ``rev = "v0.43.0"`` is *also* a hard fail —
                     use ``tag =`` for a released tag.
- ``branch = ...`` → HARD FAIL (floating unreleased ref).
- ``tag = ...``    → WARN (exit 0). A tag is a released ref; the steady-state
                     target is a PyPI range, but tags do not bypass a release.

Every other package is ignored, including the explicitly EXEMPT first-party
infra/tooling packages ``onex-change-control``, ``omnibase-infra``,
``omnimarket``, and any ``omninode-*`` — these legitimately track git today.

## Escape hatch

A single genuine, ticket-tracked unreleased override may carry an inline
annotation on the *same source line*::

    omnibase-core = { git = "...", rev = "<sha>" }  # raw-override-ok: OMN-1234

The token after the colon must be non-empty. ``# raw-override-ok:`` with no
token does NOT exempt. Comments are dropped by the TOML parser, so the
annotation is matched by a raw-line scan.

## Determinism / fail-closed

Offline, deterministic, no network. A missing file or a TOML parse error is a
HARD FAIL (exit 1) with a clear message — the gate never fails open.

## Exit codes

- 0 — no hard-fail overrides (warnings may be present)
- 1 — at least one hard-fail override, or a fail-closed error

## Flags

- ``--pyproject <path>`` (default ``pyproject.toml``)
- ``--report-only``       always exit 0 (advisory mode)
- ``--json``              emit a structured JSON report to stdout

## Refs

- OMN-13873 (this gate); root cause omnibase_infra PR #2184.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Policy tables
# ---------------------------------------------------------------------------

# First-party runtime packages that MUST come from a released wheel/tag — a
# git rev/branch override on any of these is a hard fail. Normalized to hyphen.
_PROTECTED: frozenset[str] = frozenset(
    {"omnibase-core", "omnibase-spi", "omnibase-compat"}
)

# Documented exempt packages (informational — anything not in _PROTECTED is
# already ignored). These legitimately track git overrides today: infra +
# governance + market + intelligence.
_EXEMPT: frozenset[str] = frozenset(
    {"onex-change-control", "omnibase-infra", "omnimarket"}
)


def _normalize(pkg: str) -> str:
    """uv treats ``omnibase_core`` and ``omnibase-core`` as the same dist."""
    return pkg.replace("_", "-").strip().lower()


def _is_exempt(pkg: str) -> bool:
    norm = _normalize(pkg)
    return norm in _EXEMPT or norm.startswith("omninode-")


# Inline ``# raw-override-ok: <token>`` escape-hatch annotation. Requires a
# non-empty token (``\S+``) — a bare ``# raw-override-ok:`` does not match.
_OVERRIDE_ANN_RE = re.compile(r"#\s*raw-override-ok:\s*(\S+)")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    package: str
    kind: str  # "rev" | "branch" | "tag"
    value: str
    severity: str  # "hard_fail" | "warn" | "exempt_escape"
    message: str


@dataclass
class ProvenanceReport:
    pyproject: str
    findings: list[Finding] = field(default_factory=list)

    def hard_fails(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "hard_fail"]

    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warn"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pyproject": self.pyproject,
            "hard_fail": bool(self.hard_fails()),
            "findings": [asdict(f) for f in self.findings],
        }


class ProvenanceError(Exception):
    """Fail-closed error (missing file / unparseable TOML)."""


# ---------------------------------------------------------------------------
# Escape-hatch raw-line scan
# ---------------------------------------------------------------------------


def _scan_override_annotations(text: str) -> dict[str, str]:
    """Map normalized package name -> escape-hatch token for annotated lines.

    A line is credited to a protected package when it carries both a
    ``# raw-override-ok: <token>`` comment and that package's source-key
    assignment (``omnibase-core = ...`` or ``omnibase_core = ...``). This is
    the inline-table form used by every OmniNode pyproject; comments are dropped
    by ``tomllib`` so the association must be made against the raw text.
    """
    result: dict[str, str] = {}
    for line in text.splitlines():
        ann = _OVERRIDE_ANN_RE.search(line)
        if ann is None:
            continue
        ticket = ann.group(1).strip()
        if not ticket:
            continue
        for pkg in _PROTECTED:
            underscore = pkg.replace("-", "_")
            if re.search(
                rf"(?:^|\s)(?:{re.escape(pkg)}|{re.escape(underscore)})\s*=",
                line,
            ):
                result[pkg] = ticket
    return result


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def analyze(pyproject_path: Path) -> ProvenanceReport:
    """Analyze one pyproject.toml. Raises ProvenanceError (fail-closed)."""
    if not pyproject_path.exists():
        raise ProvenanceError(f"pyproject not found: {pyproject_path}")

    try:
        text = pyproject_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProvenanceError(f"could not read {pyproject_path}: {exc}") from exc

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ProvenanceError(f"could not parse {pyproject_path}: {exc}") from exc

    sources = (
        data.get("tool", {}).get("uv", {}).get("sources", {})
        if isinstance(data, dict)
        else {}
    )
    overrides = _scan_override_annotations(text)
    report = ProvenanceReport(pyproject=str(pyproject_path))

    for pkg, spec in sources.items():
        if not isinstance(spec, dict) or "git" not in spec:
            continue  # workspace/path/registry source — not a git override
        norm = _normalize(pkg)
        if norm not in _PROTECTED:
            continue  # exempt / unrelated package
        if _is_exempt(pkg):  # defense-in-depth; _PROTECTED and _EXEMPT are disjoint
            continue

        if "branch" in spec:
            kind, value = "branch", str(spec["branch"])
        elif "rev" in spec:
            kind, value = "rev", str(spec["rev"])
        elif "tag" in spec:
            report.findings.append(
                Finding(
                    package=pkg,
                    kind="tag",
                    value=str(spec["tag"]),
                    severity="warn",
                    message=(
                        f"{pkg} pins tag={spec['tag']!r} via git. Tags are released "
                        f"refs (allowed), but the steady-state target is a PyPI "
                        f"version range — repin when a wheel is published."
                    ),
                )
            )
            continue
        else:
            continue  # git source with no rev/branch/tag pin — nothing to flag

        if overrides.get(norm):
            report.findings.append(
                Finding(
                    package=pkg,
                    kind=kind,
                    value=value,
                    severity="exempt_escape",
                    message=(
                        f"{pkg} pins {kind}={value!r} (unreleased git override) — "
                        f"exempted by # raw-override-ok: {overrides[norm]}."
                    ),
                )
            )
            continue

        report.findings.append(
            Finding(
                package=pkg,
                kind=kind,
                value=value,
                severity="hard_fail",
                message=(
                    f"{pkg} pins {kind}={value!r} via git — this resolves the "
                    f"dependency from un-released source and bypasses the released-"
                    f"wheel contract. Repin to a PyPI version range (or tag= for a "
                    f"released tag). If a genuine unreleased override is required, "
                    f"add an inline '# raw-override-ok: <ticket>' annotation."
                ),
            )
        )

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _render_text(report: ProvenanceReport) -> None:
    for f in report.findings:
        prefix = {
            "hard_fail": "FAIL",
            "warn": "WARNING",
            "exempt_escape": "EXEMPT",
        }[f.severity]
        print(f"[{prefix}] {f.message}")
    if not report.findings:
        print(f"[OK  ] {report.pyproject}: no first-party git overrides.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--pyproject",
        default="pyproject.toml",
        help="Path to pyproject.toml (default: pyproject.toml)",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Advisory mode — always exit 0 (still prints findings)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit a structured JSON report to stdout",
    )
    args = parser.parse_args(argv)

    try:
        report = analyze(Path(args.pyproject))
    except ProvenanceError as exc:
        # Fail-closed: a missing/unparseable pyproject is a hard error.
        if args.output_json:
            print(json.dumps({"pyproject": args.pyproject, "error": str(exc)}))
        else:
            print(f"[FAIL] {exc}", file=sys.stderr)
        return 0 if args.report_only else 1

    if args.output_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _render_text(report)

    if args.report_only:
        return 0

    if report.hard_fails():
        if not args.output_json:
            print(
                f"\n{len(report.hard_fails())} forbidden first-party git override(s) "
                f"in {report.pyproject}. Repin to a released wheel/tag.",
                file=sys.stderr,
            )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
